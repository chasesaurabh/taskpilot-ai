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

from taskpilot.artifacts import ArtifactStore
from taskpilot.domain.models import ApprovalAction, RunStatus, WorkflowPolicy
from taskpilot.graph.state import create_initial_state
from taskpilot.models.errors import ModelConfigurationError
from taskpilot.persistence.protocols import RunStore
from taskpilot.persistence.runs import (
    RunConflictError,
    RunNotFoundError,
    RunRecord,
)
from taskpilot.tools.repository import RepositoryWorkspace
from taskpilot.tools.types import RepositoryToolPolicy


class LeaseLostError(RuntimeError):
    """The current worker no longer owns the run lease."""


class RunService:
    """Own API-visible lifecycle, concurrency, and graph event normalization."""

    def __init__(
        self,
        *,
        graph: Any,
        store: RunStore,
        repository_policy: RepositoryToolPolicy,
        model_profiles: tuple[str, ...] = ("default",),
        default_model_profile: str = "default",
        artifacts: ArtifactStore | None = None,
        deferred_execution: bool = False,
        worker_id: str = "embedded-worker",
        lease_seconds: float = 300,
        worker_poll_seconds: float = 0.5,
    ) -> None:
        self._graph = graph
        self.store = store
        self._repository_policy = repository_policy
        self.model_profiles = tuple(sorted(model_profiles))
        self.default_model_profile = default_model_profile
        self.artifacts = artifacts
        self._deferred_execution = deferred_execution
        self._worker_id = worker_id
        self._lease_seconds = lease_seconds
        self._worker_poll_seconds = worker_poll_seconds
        if self.default_model_profile not in self.model_profiles:
            raise ValueError("The default model profile must be available")
        self._tasks: set[asyncio.Task[None]] = set()
        self._worker_task: asyncio.Task[None] | None = None
        self._worker_stop = asyncio.Event()

    async def start_run(
        self,
        *,
        task: str,
        repository: str,
        policy: WorkflowPolicy,
        owner_id: str = "local",
    ) -> RunRecord:
        selected_profile = policy.model_profile or self.default_model_profile
        if selected_profile not in self.model_profiles:
            available = ", ".join(self.model_profiles)
            raise ModelConfigurationError(
                f"Unknown model profile '{selected_profile}'. Available profiles: {available}"
            )
        policy = policy.model_copy(update={"model_profile": selected_profile})
        workspace = RepositoryWorkspace(Path(repository), self._repository_policy)
        run_id = str(uuid4())
        await self.store.create_run(
            run_id=run_id,
            task=task,
            repository=str(workspace.root),
            policy=policy,
            owner_id=owner_id,
        )
        await self.store.append_event(
            run_id,
            "run.created",
            data={
                "task": task,
                "repository": str(workspace.root),
                "model_profile": selected_profile,
                "owner_id": owner_id,
            },
            idempotency_key="run.created",
        )
        if self._deferred_execution:
            return await self.store.get_run(run_id)
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
        owner_id: str = "local",
    ) -> RunRecord:
        waiting = await self.get_owned_run(run_id, owner_id=owner_id)
        request = waiting.approval.get("request", {}) if waiting.approval else {}
        approval_id = str(request.get("approval_id", "approval"))
        kind = str(request.get("kind", "plan"))
        target = RunStatus.QUEUED if self._deferred_execution else RunStatus.RUNNING
        record = await self.store.transition(
            run_id,
            expected={RunStatus.WAITING},
            target=target,
            approval={
                "approval_id": approval_id,
                "kind": kind,
                "action": action,
                "actor": actor,
                "reason": reason,
            },
        )
        await self.store.append_event(
            run_id,
            "approval.decided",
            node=_approval_node(kind),
            data={
                "approval_id": approval_id,
                "kind": kind,
                "action": action,
                "actor": actor,
                "reason": reason,
            },
            idempotency_key=f"approval.decided:{approval_id}",
        )
        if not self._deferred_execution:
            self._spawn(
                self._drive(
                    run_id,
                    Command(resume={"action": action, "actor": actor, "reason": reason}),
                    resumed=True,
                    resume_id=approval_id,
                )
            )
        return record

    async def get_owned_run(self, run_id: str, *, owner_id: str) -> RunRecord:
        record = await self.store.get_run(run_id)
        if record.owner_id != owner_id:
            raise RunNotFoundError(f"Run not found: {run_id}")
        return record

    def _spawn(self, coroutine: Any) -> None:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def wait_for_background_tasks(self) -> None:
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks))

    def start_worker(self) -> None:
        if self._worker_task is not None:
            raise RuntimeError("Worker is already running")
        self._worker_stop.clear()
        self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop_worker(self) -> None:
        self._worker_stop.set()
        if self._worker_task is not None:
            await self._worker_task
            self._worker_task = None

    async def _worker_loop(self) -> None:
        while not self._worker_stop.is_set():
            record = await self.store.claim_next(
                worker_id=self._worker_id,
                lease_seconds=self._lease_seconds,
            )
            if record is None:
                with suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._worker_stop.wait(), timeout=self._worker_poll_seconds
                    )
                continue
            await self._drive_claimed(record)

    async def _drive_claimed(self, record: RunRecord) -> None:
        approval = record.approval or {}
        action = approval.get("action")
        if action is not None:
            graph_input: Any = Command(
                resume={
                    "action": action,
                    "actor": approval.get("actor"),
                    "reason": approval.get("reason"),
                }
            )
            resumed = True
            resume_id = str(approval.get("approval_id", "approval"))
        elif record.lease_recovered:
            snapshot = await self._graph.aget_state({"configurable": {"thread_id": record.run_id}})
            graph_input = None if snapshot.values else self._initial_state(record)
            resumed = False
            resume_id = None
        else:
            graph_input = self._initial_state(record)
            resumed = False
            resume_id = None
        await self._drive(
            record.run_id,
            graph_input,
            resumed=resumed,
            resume_id=resume_id,
            recovered=record.lease_recovered,
            lease_owner=self._worker_id,
        )

    @staticmethod
    def _initial_state(record: RunRecord) -> Any:
        return create_initial_state(
            run_id=record.run_id,
            task=record.task,
            repository_root=record.repository,
            policy=record.policy,
        )

    async def _drive(
        self,
        run_id: str,
        graph_input: Any,
        *,
        resumed: bool,
        resume_id: str | None = None,
        recovered: bool = False,
        lease_owner: str | None = None,
    ) -> None:
        clear_contextvars()
        bind_contextvars(run_id=run_id)
        logger = structlog.get_logger(__name__)
        config = {"configurable": {"thread_id": run_id}}
        interrupted = False
        pending_approval: dict[str, Any] | None = None
        event_type = "run.recovered" if recovered else "run.resumed" if resumed else "run.started"
        event_key = (
            f"run.recovered:{resume_id or 'lease'}"
            if recovered
            else f"run.resumed:{resume_id}"
            if resumed
            else "run.started"
        )
        await self.store.append_event(
            run_id,
            event_type,
            idempotency_key=event_key,
        )
        logger.info("workflow_started", resumed=resumed)
        heartbeat_stop = asyncio.Event()
        lease_lost = asyncio.Event()
        heartbeat = (
            asyncio.create_task(
                self._lease_heartbeat(run_id, lease_owner, heartbeat_stop, lease_lost)
            )
            if lease_owner is not None
            else None
        )
        try:
            async for mode, chunk in self._graph.astream(
                graph_input,
                config,
                stream_mode=["updates", "tasks"],
            ):
                if lease_lost.is_set():
                    raise LeaseLostError(f"Worker lost the lease for run '{run_id}'")
                if mode == "tasks":
                    await self._handle_task_event(run_id, chunk)
                    continue
                if "__interrupt__" in chunk:
                    interrupted = True
                    interrupt_value = chunk["__interrupt__"][0].value
                    pending_approval = jsonable_encoder(interrupt_value)
                    approval_id = str(pending_approval.get("approval_id", "approval"))
                    kind = str(pending_approval.get("kind", "plan"))
                    await self.store.append_event(
                        run_id,
                        "approval.required",
                        node=_approval_node(kind),
                        data=pending_approval,
                        idempotency_key=f"approval.required:{approval_id}",
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
                if lease_lost.is_set():
                    raise LeaseLostError(f"Worker lost the lease for run '{run_id}'")
                await self.store.transition(
                    run_id,
                    expected={RunStatus.RUNNING},
                    target=RunStatus.WAITING,
                    approval={"request": pending_approval or {}},
                    lease_owner=lease_owner,
                )
                logger.info("workflow_waiting_for_approval")
                return

            snapshot = await self._graph.aget_state(config)
            report = snapshot.values.get("final_report")
            if report is None:
                raise RuntimeError("Graph ended without a final report")
            if lease_lost.is_set():
                raise LeaseLostError(f"Worker lost the lease for run '{run_id}'")
            outcome = RunStatus(report.outcome)
            await self.store.transition(
                run_id,
                expected={RunStatus.RUNNING},
                target=outcome,
                final_report=report,
                lease_owner=lease_owner,
            )
            await self.store.append_event(
                run_id,
                "run.completed" if outcome == RunStatus.COMPLETED else "run.stopped",
                data={"outcome": outcome, "summary": report.summary},
                idempotency_key="run.terminal",
            )
            logger.info("workflow_finished", outcome=outcome)
        except LeaseLostError:
            logger.warning("workflow_lease_lost")
        except Exception as exc:
            if lease_owner is not None and not await self.store.renew_lease(
                run_id,
                worker_id=lease_owner,
                lease_seconds=self._lease_seconds,
            ):
                logger.warning("workflow_lease_lost", error_type=type(exc).__name__)
                return
            logger.exception("workflow_failed", error_type=type(exc).__name__)
            with suppress(RunConflictError):
                await self.store.transition(
                    run_id,
                    expected={RunStatus.RUNNING},
                    target=RunStatus.FAILED,
                    lease_owner=lease_owner,
                )
            await self.store.append_event(
                run_id,
                "run.failed",
                data={"error_type": type(exc).__name__, "message": str(exc)},
                idempotency_key="run.terminal",
            )
        finally:
            heartbeat_stop.set()
            if heartbeat is not None:
                await heartbeat
            clear_contextvars()

    async def _lease_heartbeat(
        self,
        run_id: str,
        worker_id: str,
        stop: asyncio.Event,
        lost: asyncio.Event,
    ) -> None:
        interval = max(1.0, self._lease_seconds / 3)
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except TimeoutError:
                renewed = await self.store.renew_lease(
                    run_id,
                    worker_id=worker_id,
                    lease_seconds=self._lease_seconds,
                )
                if not renewed:
                    lost.set()
                    return

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
            await self._emit_artifact_events(run_id, node, change_set, parent_sequence)
        if "validation" in public:
            validation = public["validation"]
            await self.store.append_event(
                run_id,
                "tool.completed",
                node=node,
                data={"tool": "execute", **validation},
                idempotency_key=f"derived:{parent_sequence}:validation",
            )
            await self._emit_artifact_events(run_id, node, validation, parent_sequence)

    async def _emit_artifact_events(
        self,
        run_id: str,
        node: str,
        payload: dict[str, Any],
        parent_sequence: int,
    ) -> None:
        for index, artifact in enumerate(payload.get("artifacts", [])):
            await self.store.append_event(
                run_id,
                "artifact.created",
                node=node,
                data=artifact,
                idempotency_key=f"derived:{parent_sequence}:artifact:{index}",
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


def _approval_node(kind: str) -> str:
    return {"plan": "approval", "write": "write_approval", "command": "command_approval"}.get(
        kind, "approval"
    )
