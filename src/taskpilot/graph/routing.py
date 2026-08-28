"""Deterministic conditional routes for the engineering workflow."""

from typing import Literal

from taskpilot.domain.models import ApprovalStatus
from taskpilot.graph.state import WorkflowState

ApprovalRoute = Literal["implementation", "final_report"]
ValidationRoute = Literal["code_review", "failure_analysis", "final_report"]
ReviewRoute = Literal["repair", "final_report"]


def route_after_approval(state: WorkflowState) -> ApprovalRoute:
    """Only an explicit approval can enter the write-capable implementation node."""

    decision = state["approval"]
    if decision.status == ApprovalStatus.APPROVED:
        return "implementation"
    return "final_report"


def route_after_validation(state: WorkflowState) -> ValidationRoute:
    """Send failed validation through repair while the policy budget remains."""

    if state["validation"].passed:
        return "code_review"
    if state["repair_attempts"] < state["policy"].max_repair_attempts:
        return "failure_analysis"
    return "final_report"


def route_after_review(state: WorkflowState) -> ReviewRoute:
    """Permit review-driven repair without bypassing the shared retry budget."""

    review = state["review"]
    if review.blocking and state["repair_attempts"] < state["policy"].max_repair_attempts:
        return "repair"
    return "final_report"
