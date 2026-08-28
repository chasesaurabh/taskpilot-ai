from taskpilot.domain.models import (
    ApprovalDecision,
    ApprovalStatus,
    ReviewResult,
    ValidationResult,
    WorkflowPolicy,
)
from taskpilot.graph.routing import (
    route_after_approval,
    route_after_review,
    route_after_validation,
)
from taskpilot.graph.state import WorkflowState


def test_approval_requires_explicit_approval() -> None:
    pending = WorkflowState(approval=ApprovalDecision())
    approved = WorkflowState(
        approval=ApprovalDecision(status=ApprovalStatus.APPROVED, actor="tester")
    )

    assert route_after_approval(pending) == "final_report"
    assert route_after_approval(approved) == "implementation"


def test_validation_routes_success_to_review() -> None:
    state = WorkflowState(
        validation=ValidationResult(passed=True, command=("pytest",)),
        repair_attempts=0,
        policy=WorkflowPolicy(max_repair_attempts=2),
    )

    assert route_after_validation(state) == "code_review"


def test_validation_routes_failure_to_diagnosis_with_budget() -> None:
    state = WorkflowState(
        validation=ValidationResult(passed=False, command=("pytest",)),
        repair_attempts=1,
        policy=WorkflowPolicy(max_repair_attempts=2),
    )

    assert route_after_validation(state) == "failure_analysis"


def test_validation_stops_when_retry_budget_is_exhausted() -> None:
    state = WorkflowState(
        validation=ValidationResult(passed=False, command=("pytest",)),
        repair_attempts=2,
        policy=WorkflowPolicy(max_repair_attempts=2),
    )

    assert route_after_validation(state) == "final_report"


def test_blocking_review_uses_same_retry_budget() -> None:
    repairable = WorkflowState(
        review=ReviewResult(summary="unsafe", blocking=True),
        repair_attempts=0,
        policy=WorkflowPolicy(max_repair_attempts=1),
    )
    exhausted = WorkflowState(
        review=ReviewResult(summary="unsafe", blocking=True),
        repair_attempts=1,
        policy=WorkflowPolicy(max_repair_attempts=1),
    )

    assert route_after_review(repairable) == "repair"
    assert route_after_review(exhausted) == "final_report"
