"""Explicit, versioned state passed between LangGraph nodes."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from taskpilot.domain.models import (
    AnalysisReport,
    ApprovalDecision,
    ChangeSet,
    FailureDiagnosis,
    FilePrecondition,
    FinalReport,
    ImplementationPlan,
    ImplementationProposal,
    ModelDecision,
    NodeRecord,
    RepositoryContext,
    RepositoryDescriptor,
    ReviewResult,
    RunMetadata,
    TaskAnalysis,
    TaskRequest,
    ValidationResult,
    WorkflowPolicy,
)


class WorkflowState(TypedDict, total=False):
    """Durable graph state.

    Append-only fields declare reducers so parallel nodes can safely contribute in
    the same superstep. Context and command output are bounded; proposal content is
    retained for durable writes but redacted from public events.
    """

    metadata: RunMetadata
    task: TaskRequest
    repository: RepositoryDescriptor
    policy: WorkflowPolicy
    context: RepositoryContext
    task_analysis: TaskAnalysis
    plan: ImplementationPlan
    architecture_report: AnalysisReport
    repository_report: AnalysisReport
    approval: ApprovalDecision
    approval_history: Annotated[list[ApprovalDecision], operator.add]
    change_set: ChangeSet
    proposal: ImplementationProposal
    proposal_preconditions: tuple[FilePrecondition, ...]
    validation: ValidationResult
    diagnosis: FailureDiagnosis
    repair_attempts: int
    review: ReviewResult
    final_report: FinalReport
    model_decisions: Annotated[list[ModelDecision], operator.add]
    node_history: Annotated[list[NodeRecord], operator.add]


class WorkflowUpdate(TypedDict, total=False):
    """Typed partial update returned by a node."""

    metadata: RunMetadata
    context: RepositoryContext
    task_analysis: TaskAnalysis
    plan: ImplementationPlan
    architecture_report: AnalysisReport
    repository_report: AnalysisReport
    approval: ApprovalDecision
    approval_history: list[ApprovalDecision]
    change_set: ChangeSet
    proposal: ImplementationProposal
    proposal_preconditions: tuple[FilePrecondition, ...]
    validation: ValidationResult
    diagnosis: FailureDiagnosis
    repair_attempts: int
    review: ReviewResult
    final_report: FinalReport
    model_decisions: list[ModelDecision]
    node_history: list[NodeRecord]


def create_initial_state(
    *,
    run_id: str,
    task: str,
    repository_root: str,
    policy: WorkflowPolicy | None = None,
) -> WorkflowState:
    """Create the only supported initial shape for a new workflow."""

    return WorkflowState(
        metadata=RunMetadata(run_id=run_id),
        task=TaskRequest(description=task),
        repository=RepositoryDescriptor(root=repository_root),
        policy=policy or WorkflowPolicy(),
        approval=ApprovalDecision(),
        approval_history=[],
        repair_attempts=0,
        model_decisions=[],
        node_history=[],
    )
