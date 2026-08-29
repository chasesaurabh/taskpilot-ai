from __future__ import annotations

import asyncio
from pathlib import Path

from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt

from taskpilot.api import create_app
from taskpilot.application.runs import RunService
from taskpilot.domain.models import (
    AnalysisReport,
    ApprovalDecision,
    ApprovalStatus,
    ChangeSet,
    FinalReport,
    ImplementationPlan,
    NodeRecord,
    PlanStep,
    RepositoryContext,
    ReviewResult,
    RunStatus,
    TaskAnalysis,
    ValidationResult,
)
from taskpilot.graph import WorkflowNodes, build_workflow
from taskpilot.graph.state import WorkflowState, WorkflowUpdate
from taskpilot.persistence.runs import SqliteRunStore
from taskpilot.tools.types import RepositoryToolPolicy


def _update(node: str, **values: object) -> WorkflowUpdate:
    return WorkflowUpdate(
        **values,
        node_history=[NodeRecord(node=node, status="completed")],
    )


def _api_nodes() -> WorkflowNodes:
    def context(_: WorkflowState) -> WorkflowUpdate:
        return _update("repository_context", context=RepositoryContext(summary="context"))

    def analyze(_: WorkflowState) -> WorkflowUpdate:
        return _update("task_analysis", task_analysis=TaskAnalysis(objective="objective"))

    def plan(_: WorkflowState) -> WorkflowUpdate:
        return _update(
            "planning",
            plan=ImplementationPlan(
                summary="plan",
                steps=(PlanStep(order=1, description="change", expected_files=("app.py",)),),
            ),
        )

    def architecture(_: WorkflowState) -> WorkflowUpdate:
        return _update("architecture_review", architecture_report=AnalysisReport(summary="safe"))

    def repository(_: WorkflowState) -> WorkflowUpdate:
        return _update("repository_analysis", repository_report=AnalysisReport(summary="impact"))

    def approval(_: WorkflowState) -> WorkflowUpdate:
        response = interrupt({"kind": "approval", "plan": "plan"})
        status = (
            ApprovalStatus.APPROVED if response["action"] == "approve" else ApprovalStatus.REJECTED
        )
        return _update(
            "approval", approval=ApprovalDecision(status=status, actor=response["actor"])
        )

    def implementation(_: WorkflowState) -> WorkflowUpdate:
        return _update("implementation", change_set=ChangeSet(summary="changed"))

    def testing(_: WorkflowState) -> WorkflowUpdate:
        return _update(
            "testing",
            validation=ValidationResult(passed=True, command=("pytest",)),
        )

    def impossible(_: WorkflowState) -> WorkflowUpdate:
        raise AssertionError("unreachable")

    def review(_: WorkflowState) -> WorkflowUpdate:
        return _update("code_review", review=ReviewResult(summary="accepted"))

    def report(state: WorkflowState) -> WorkflowUpdate:
        outcome = (
            RunStatus.REJECTED
            if state["approval"].status == ApprovalStatus.REJECTED
            else RunStatus.COMPLETED
        )
        return _update(
            "final_report",
            final_report=FinalReport(outcome=outcome, summary="finished"),
        )

    return WorkflowNodes(
        context,
        analyze,
        plan,
        architecture,
        repository,
        approval,
        implementation,
        testing,
        impossible,
        impossible,
        review,
        report,
    )


async def _wait_for_status(store: SqliteRunStore, run_id: str, status: RunStatus) -> None:
    for _ in range(200):
        if (await store.get_run(run_id)).status == status:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"Run did not reach {status}")


def test_api_create_approve_status_and_sse_replay(tmp_path: Path) -> None:
    async def scenario() -> None:
        repository = tmp_path / "repo"
        repository.mkdir()
        store = await SqliteRunStore.open(tmp_path / "runs.sqlite")
        service = RunService(
            graph=build_workflow(_api_nodes(), checkpointer=InMemorySaver()),
            store=store,
            repository_policy=RepositoryToolPolicy(allowed_roots=(tmp_path,)),
            model_profiles=("balanced", "private"),
            default_model_profile="balanced",
        )
        app = create_app(service)
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                profiles = await client.get("/model-profiles")
                assert profiles.json() == {
                    "default_profile": "balanced",
                    "profiles": ["balanced", "private"],
                }
                unknown = await client.post(
                    "/runs",
                    json={
                        "repository": str(repository),
                        "task": "Make a change",
                        "model_profile": "missing",
                    },
                )
                assert unknown.status_code == 422
                assert "Available profiles: balanced, private" in unknown.json()["detail"]
                created = await client.post(
                    "/runs",
                    json={
                        "repository": str(repository),
                        "task": "Make a change",
                        "model_profile": "private",
                    },
                )
                assert created.status_code == 202
                assert created.json()["policy"]["model_profile"] == "private"
                run_id = created.json()["run_id"]
                await _wait_for_status(store, run_id, RunStatus.WAITING)

                waiting = await client.get(f"/runs/{run_id}")
                assert waiting.json()["status"] == "waiting_for_approval"

                approved = await client.post(
                    f"/runs/{run_id}/approve",
                    json={"actor": "reviewer@example.com"},
                )
                assert approved.status_code == 202
                await _wait_for_status(store, run_id, RunStatus.COMPLETED)

                events = await client.get(f"/runs/{run_id}/events")
                assert events.status_code == 200
                assert events.headers["content-type"].startswith("text/event-stream")
                assert "event: approval.required" in events.text
                assert "event: run.completed" in events.text
                assert 'content"' not in events.text

                replay = await client.get(
                    f"/runs/{run_id}/events",
                    headers={"Last-Event-ID": "2"},
                )
                assert "id: 1\n" not in replay.text
                assert "id: 2\n" not in replay.text
        finally:
            await service.wait_for_background_tasks()
            await store.close()

    asyncio.run(scenario())


def test_api_reject_is_idempotently_guarded_and_unknown_run_is_404(tmp_path: Path) -> None:
    async def scenario() -> None:
        repository = tmp_path / "repo"
        repository.mkdir()
        store = await SqliteRunStore.open(tmp_path / "runs.sqlite")
        service = RunService(
            graph=build_workflow(_api_nodes(), checkpointer=InMemorySaver()),
            store=store,
            repository_policy=RepositoryToolPolicy(allowed_roots=(tmp_path,)),
        )
        app = create_app(service)
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                assert (await client.get("/runs/missing")).status_code == 404
                created = await client.post(
                    "/runs",
                    json={"repository": str(repository), "task": "Reject me"},
                )
                run_id = created.json()["run_id"]
                await _wait_for_status(store, run_id, RunStatus.WAITING)

                rejected = await client.post(
                    f"/runs/{run_id}/reject",
                    json={"actor": "reviewer@example.com", "reason": "scope is too broad"},
                )
                assert rejected.status_code == 202
                duplicate = await client.post(
                    f"/runs/{run_id}/reject",
                    json={"actor": "reviewer@example.com"},
                )
                assert duplicate.status_code == 409
                await _wait_for_status(store, run_id, RunStatus.REJECTED)
        finally:
            await service.wait_for_background_tasks()
            await store.close()

    asyncio.run(scenario())
