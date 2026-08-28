"""Run lifecycle orchestration above LangGraph's execution API."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path
from typing import Any
from uuid import uuid4

import structlog
from fastapi.encoders import jsonable_encoder
from langgraph.types import Command
from structlog.contextvars import bind_contextvars, clear_contextvars

from taskpilot.domain.models import ApprovalAction, RunStatus, WorkflowPolicy
from taskpilot.graph.state import create_initial_state
from taskpilot.persistence.protocols import RunStore
from taskpilot.persistence.runs import (
    RunConflictError,
    RunRecord,
)
from taskpilot.tools.repository import RepositoryWorkspace
from taskpilot.tools.types import RepositoryToolPolicy


class RunService:
    """Own API-visible lifecycle, concurrency, and graph event normalization."""

    def __init__(
        self,
        *,
        graph: Any,
        store: RunStore,
        repository_policy: RepositoryToolPolicy,
    ) -> None:
        self._graph = graph
        self.store = store
        self._repository_policy = repository_policy
        self._tasks: set[asyncio.Task[None]] = set()

    async def start_run(
        self,
        *,
        task: str,
        repository: str,
        policy: WorkflowPolicy,
    ) -> RunRecord:
        workspace = RepositoryWorkspace(Path(repository), self._repository_policy)
        run_id = str(uuid4())
        await self.store.create_run(
            run_id=run_id,
            task=task,
            repository=str(workspace.root),
            policy=policy,
        )
        await self.store.append_event(
            run_id,
            "run.created",
            data={"task": task, "repository": str(workspace.root)},
            idempotency_key="run.created",
        )
        record = await self.store.transition(
            run_id,
            expected={RunStatus.QUEUED},
            target=RunStatus.RUNNING,
        )
        self._spawn(
            self._drive(
                run_id,
                create_initial_state(
                    run_id=run_id,
                    task=task,
                    repository_root=str(workspace.root),
                    policy=policy,
                ),
                resumed=False,
            )
        )
        return record

    async def resume(
        self,
        run_id: str,
        *,
        action: ApprovalAction,
        actor: str,
        reason: str | None,
    ) -> RunRecord:
        record = await self.store.transition(
            run_id,
            expected={RunStatus.WAITING},
            target=RunStatus.RUNNING,
            approval={"action": action, "actor": actor, "reason": reason},
        )
        await self.store.append_event(
            run_id,
            "approval.decided",
            node="approval",
            data={"action": action, "actor": actor, "reason": reason},
            idempotency_key="approval.decided",
        )
        self._spawn(
            self._drive(
                run_id,
                Command(resume={"action": action, "actor": actor, "reason": reason}),
                resumed=True,
            )
        )
        return record

    def _spawn(self, coroutine: Any) -> None:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def wait_for_background_tasks(self) -> None:
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks))

    async def _drive(self, run_id: str, graph_input: Any, *, resumed: bool) -> None:
        clear_contextvars()
        bind_contextvars(run_id=run_id)
        logger = structlog.get_logger(__name__)
        config = {"configurable": {"thread_id": run_id}}
        interrupted = False
        await self.store.append_event(
            run_id,
            "run.resumed" if resumed else "run.started",
            idempotency_key="run.resumed" if resumed else "run.started",
        )
        logger.info("workflow_started", resumed=resumed)
        try:
            async for mode, chunk in self._graph.astream(
                graph_input,
                config,
                stream_mode=["updates", "tasks"],
            ):
                if mode == "tasks":
                    await self._handle_task_event(run_id, chunk)
                    continue
                if "__interrupt__" in chunk:
                    interrupted = True
                    interrupt_value = chunk["__interrupt__"][0].value
                    await self.store.append_event(
                        run_id,
                        "approval.required",
                        node="approval",
                        data=jsonable_encoder(interrupt_value),
                        idempotency_key="approval.required",
                    )
                    continue
                for node, update in chunk.items():
                    event = await self.store.append_event(
                        run_id,
                        "node.completed",
                        node=node,
                        data=_public_update(update),
                    )
                    await self._emit_derived_events(run_id, node, update, event.sequence)
            if interrupted:
                await self.store.transition(
                    run_id,
                    expected={RunStatus.RUNNING},
                    target=RunStatus.WAITING,
                )
                logger.info("workflow_waiting_for_approval")
                return

            snapshot = await self._graph.aget_state(config)
            report = snapshot.values.get("final_report")
            if report is None:
                raise RuntimeError("Graph ended without a final report")
            outcome = RunStatus(report.outcome)
            await self.store.transition(
                run_id,
                expected={RunStatus.RUNNING},
                target=outcome,
                final_report=report,
            )
            await self.store.append_event(
                run_id,
                "run.completed" if outcome == RunStatus.COMPLETED else "run.stopped",
                data={"outcome": outcome, "summary": report.summary},
                idempotency_key="run.terminal",
            )
            logger.info("workflow_finished", outcome=outcome)
        except Exception as exc:
            logger.exception("workflow_failed", error_type=type(exc).__name__)
            with suppress(RunConflictError):
                await self.store.transition(
                    run_id,
                    expected={RunStatus.RUNNING},
                    target=RunStatus.FAILED,
                )
            await self.store.append_event(
                run_id,
                "run.failed",
                data={"error_type": type(exc).__name__, "message": str(exc)},
                idempotency_key="run.terminal",
            )
        finally:
            clear_contextvars()

    async def _emit_derived_events(
        self,
        run_id: str,
        node: str,
        update: Any,
        parent_sequence: int,
    ) -> None:
        public = _public_update(update)
        for index, decision in enumerate(public.get("model_decisions", [])):
            await self.store.append_event(
                run_id,
                "model.completed",
                node=node,
                data=decision,
                idempotency_key=f"derived:{parent_sequence}:model:{index}",
            )
        if "context" in public:
            context = public["context"]
            await self.store.append_event(
                run_id,
                "tool.completed",
                node=node,
                data={"tool": "repository_context", "summary": context.get("summary", "")},
                idempotency_key=f"derived:{parent_sequence}:context",
            )
        if "change_set" in public:
            change_set = public["change_set"]
            await self.store.append_event(
                run_id,
                "tool.completed",
                node=node,
                data={"tool": "write_file", **change_set},
                idempotency_key=f"derived:{parent_sequence}:changes",
            )
        if "validation" in public:
            validation = public["validation"]
            await self.store.append_event(
                run_id,
                "tool.completed",
                node=node,
                data={"tool": "execute", **validation},
                idempotency_key=f"derived:{parent_sequence}:validation",
            )

    async def _handle_task_event(self, run_id: str, chunk: dict[str, Any]) -> None:
        task_id = str(chunk["id"])
        node = str(chunk["name"])
        if "result" not in chunk and "error" not in chunk:
            await self.store.append_event(
                run_id,
                "node.started",
                node=node,
                idempotency_key=f"task:{task_id}:started",
            )
        elif chunk.get("error") is not None:
            await self.store.append_event(
                run_id,
                "node.failed",
                node=node,
                data={"error": str(chunk["error"])},
                idempotency_key=f"task:{task_id}:failed",
            )


def _public_update(update: Any) -> dict[str, Any]:
    encoded = jsonable_encoder(update)
    if not isinstance(encoded, dict):
        return {"value": encoded}
    proposal = encoded.get("proposal")
    if isinstance(proposal, dict):
        for change in proposal.get("changes", []):
            if isinstance(change, dict) and "content" in change:
                content = str(change.pop("content"))
                change["content_bytes"] = len(content.encode())
                change["content_redacted"] = True
    return encoded
