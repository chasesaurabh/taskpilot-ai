from collections.abc import Callable
from threading import Barrier

from taskpilot.domain.models import (
    AnalysisReport,
    ApprovalDecision,
    ApprovalStatus,
    ChangeSet,
    FailureDiagnosis,
    FinalReport,
    ImplementationPlan,
    NodeRecord,
    PlanStep,
    RepositoryContext,
    ReviewResult,
    RunStatus,
    TaskAnalysis,
    ValidationResult,
    WorkflowPolicy,
)
from taskpilot.graph import WorkflowNodes, build_workflow, create_initial_state
from taskpilot.graph.state import WorkflowState, WorkflowUpdate


def _record(node: str, **updates: object) -> WorkflowUpdate:
    return WorkflowUpdate(
        **updates,
        node_history=[NodeRecord(node=node, status="completed")],
    )


def _nodes(
    *,
    test_results: list[bool],
    approved: bool = True,
    parallel_barrier: Barrier | None = None,
) -> WorkflowNodes:
    remaining_results = iter(test_results)

    def context(_: WorkflowState) -> WorkflowUpdate:
        return _record("repository_context", context=RepositoryContext(summary="bounded context"))

    def analyze(state: WorkflowState) -> WorkflowUpdate:
        return _record(
            "task_analysis", task_analysis=TaskAnalysis(objective=state["task"].description)
        )

    def plan(_: WorkflowState) -> WorkflowUpdate:
        return _record(
            "planning",
            plan=ImplementationPlan(
                summary="Make the requested change",
                steps=(PlanStep(order=1, description="Implement and validate"),),
            ),
        )

    def architecture(_: WorkflowState) -> WorkflowUpdate:
        if parallel_barrier is not None:
            parallel_barrier.wait(timeout=2)
        return _record(
            "architecture_review",
            architecture_report=AnalysisReport(summary="Architecture remains coherent"),
        )

    def repository(_: WorkflowState) -> WorkflowUpdate:
        if parallel_barrier is not None:
            parallel_barrier.wait(timeout=2)
        return _record(
            "repository_analysis",
            repository_report=AnalysisReport(summary="One component is affected"),
        )

    def approval(_: WorkflowState) -> WorkflowUpdate:
        status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        return _record("approval", approval=ApprovalDecision(status=status, actor="test"))

    def implementation(_: WorkflowState) -> WorkflowUpdate:
        return _record("implementation", change_set=ChangeSet(summary="Applied"))

    def testing(_: WorkflowState) -> WorkflowUpdate:
        passed = next(remaining_results)
        return _record(
            "testing",
            validation=ValidationResult(passed=passed, command=("pytest",)),
        )

    def diagnosis(_: WorkflowState) -> WorkflowUpdate:
        return _record("failure_analysis", diagnosis=FailureDiagnosis(summary="Test failure"))

    def repair(state: WorkflowState) -> WorkflowUpdate:
        return _record("repair", repair_attempts=state["repair_attempts"] + 1)

    def review(_: WorkflowState) -> WorkflowUpdate:
        return _record("code_review", review=ReviewResult(summary="Accepted"))

    def report(state: WorkflowState) -> WorkflowUpdate:
        if state["approval"].status == ApprovalStatus.REJECTED:
            outcome = RunStatus.REJECTED
        elif state.get("validation") and not state["validation"].passed:
            outcome = RunStatus.FAILED
        else:
            outcome = RunStatus.COMPLETED
        return _record(
            "final_report",
            final_report=FinalReport(outcome=outcome, summary="Workflow finished"),
        )

    functions: tuple[Callable[[WorkflowState], WorkflowUpdate], ...] = (
        context,
        analyze,
        plan,
        architecture,
        repository,
        approval,
        implementation,
        testing,
        diagnosis,
        repair,
        review,
        report,
    )
    return WorkflowNodes(*functions)


def test_graph_runs_parallel_analysis_and_success_path() -> None:
    graph = build_workflow(_nodes(test_results=[True], parallel_barrier=Barrier(2)))

    result = graph.invoke(
        create_initial_state(run_id="run-1", task="Add pagination", repository_root="repo")
    )

    history = [record.node for record in result["node_history"]]
    assert set(history[3:5]) == {"architecture_review", "repository_analysis"}
    assert history[-4:] == ["implementation", "testing", "code_review", "final_report"]
    assert result["final_report"].outcome == RunStatus.COMPLETED


def test_graph_repairs_a_failed_test_then_retests() -> None:
    graph = build_workflow(_nodes(test_results=[False, True]))

    result = graph.invoke(
        create_initial_state(
            run_id="run-2",
            task="Fix validation",
            repository_root="repo",
            policy=WorkflowPolicy(max_repair_attempts=2),
        )
    )

    history = [record.node for record in result["node_history"]]
    assert history[-7:] == [
        "implementation",
        "testing",
        "failure_analysis",
        "repair",
        "testing",
        "code_review",
        "final_report",
    ]
    assert result["repair_attempts"] == 1


def test_graph_rejection_never_enters_implementation() -> None:
    graph = build_workflow(_nodes(test_results=[], approved=False))

    result = graph.invoke(
        create_initial_state(run_id="run-3", task="Risky change", repository_root="repo")
    )

    history = [record.node for record in result["node_history"]]
    assert "implementation" not in history
    assert result["final_report"].outcome == RunStatus.REJECTED


def test_graph_stops_after_retry_exhaustion() -> None:
    graph = build_workflow(_nodes(test_results=[False, False]))

    result = graph.invoke(
        create_initial_state(
            run_id="run-4",
            task="Impossible change",
            repository_root="repo",
            policy=WorkflowPolicy(max_repair_attempts=1),
        )
    )

    history = [record.node for record in result["node_history"]]
    assert history.count("repair") == 1
    assert "code_review" not in history
    assert result["final_report"].outcome == RunStatus.FAILED
