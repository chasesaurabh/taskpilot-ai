from __future__ import annotations

from pathlib import Path

from langgraph.types import Command, interrupt

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
from taskpilot.graph import WorkflowNodes, build_workflow, create_initial_state
from taskpilot.graph.state import WorkflowState, WorkflowUpdate
from taskpilot.persistence import open_sqlite_checkpointer


def _update(node: str, **values: object) -> WorkflowUpdate:
    return WorkflowUpdate(
        **values,
        node_history=[NodeRecord(node=node, status="completed")],
    )


def _durable_nodes() -> WorkflowNodes:
    def repository_context(_: WorkflowState) -> WorkflowUpdate:
        return _update("repository_context", context=RepositoryContext(summary="context"))

    def task_analysis(_: WorkflowState) -> WorkflowUpdate:
        return _update("task_analysis", task_analysis=TaskAnalysis(objective="change"))

    def planning(_: WorkflowState) -> WorkflowUpdate:
        return _update(
            "planning",
            plan=ImplementationPlan(
                summary="plan",
                steps=(PlanStep(order=1, description="change"),),
            ),
        )

    def architecture(_: WorkflowState) -> WorkflowUpdate:
        return _update("architecture_review", architecture_report=AnalysisReport(summary="safe"))

    def repository(_: WorkflowState) -> WorkflowUpdate:
        return _update("repository_analysis", repository_report=AnalysisReport(summary="bounded"))

    def approval(_: WorkflowState) -> WorkflowUpdate:
        response = interrupt({"kind": "plan_approval", "message": "Approve the plan"})
        status = (
            ApprovalStatus.APPROVED if response["action"] == "approve" else ApprovalStatus.REJECTED
        )
        return _update(
            "approval",
            approval=ApprovalDecision(status=status, actor=response["actor"]),
        )

    def implementation(_: WorkflowState) -> WorkflowUpdate:
        return _update("implementation", change_set=ChangeSet(summary="changed"))

    def testing(_: WorkflowState) -> WorkflowUpdate:
        return _update(
            "testing",
            validation=ValidationResult(passed=True, command=("pytest",)),
        )

    def failure(_: WorkflowState) -> WorkflowUpdate:
        raise AssertionError("failure analysis must not run")

    def repair(_: WorkflowState) -> WorkflowUpdate:
        raise AssertionError("repair must not run")

    def review(_: WorkflowState) -> WorkflowUpdate:
        return _update("code_review", review=ReviewResult(summary="accepted"))

    def report(_: WorkflowState) -> WorkflowUpdate:
        return _update(
            "final_report",
            final_report=FinalReport(outcome=RunStatus.COMPLETED, summary="done"),
        )

    return WorkflowNodes(
        repository_context,
        task_analysis,
        planning,
        architecture,
        repository,
        approval,
        implementation,
        testing,
        failure,
        repair,
        review,
        report,
    )


def test_run_survives_checkpointer_close_and_resumes_exact_thread(tmp_path: Path) -> None:
    database = tmp_path / "checkpoints.sqlite"
    config = {"configurable": {"thread_id": "durable-run"}}
    initial = create_initial_state(
        run_id="durable-run",
        task="Make a durable change",
        repository_root="repo",
    )

    with open_sqlite_checkpointer(database) as first_checkpointer:
        graph = build_workflow(_durable_nodes(), checkpointer=first_checkpointer)
        paused = graph.invoke(initial, config)
        snapshot = graph.get_state(config)

        assert paused["__interrupt__"][0].value["kind"] == "plan_approval"
        assert snapshot.next == ("approval",)
        assert "implementation" not in [record.node for record in snapshot.values["node_history"]]

    with open_sqlite_checkpointer(database) as restarted_checkpointer:
        restarted_graph = build_workflow(_durable_nodes(), checkpointer=restarted_checkpointer)
        result = restarted_graph.invoke(
            Command(resume={"action": "approve", "actor": "reviewer@example.com"}),
            config,
        )

    history = [record.node for record in result["node_history"]]
    assert history.count("repository_context") == 1
    assert history.count("planning") == 1
    assert history[-4:] == ["implementation", "testing", "code_review", "final_report"]
    assert result["approval"].status == ApprovalStatus.APPROVED


def test_rejected_resume_routes_to_report_without_implementation(tmp_path: Path) -> None:
    database = tmp_path / "rejected.sqlite"
    config = {"configurable": {"thread_id": "rejected-run"}}

    with open_sqlite_checkpointer(database) as checkpointer:
        graph = build_workflow(_durable_nodes(), checkpointer=checkpointer)
        graph.invoke(
            create_initial_state(
                run_id="rejected-run",
                task="Do not implement",
                repository_root="repo",
            ),
            config,
        )
        result = graph.invoke(
            Command(resume={"action": "reject", "actor": "reviewer@example.com"}),
            config,
        )

    history = [record.node for record in result["node_history"]]
    assert "implementation" not in history
    assert history[-1] == "final_report"
