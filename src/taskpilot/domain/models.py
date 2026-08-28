"""Serializable domain models for a TaskPilot workflow."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class DomainModel(BaseModel):
    """Base model with strict inputs and JSON-compatible defaults."""

    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting_for_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    BLOCKING = "blocking"


class RunMetadata(DomainModel):
    run_id: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: RunStatus = RunStatus.QUEUED
    state_schema_version: int = 1


class TaskRequest(DomainModel):
    description: str = Field(min_length=1, max_length=20_000)


class RepositoryDescriptor(DomainModel):
    root: str = Field(min_length=1)
    default_branch: str | None = None
    head_commit: str | None = None
    is_dirty: bool = False


class WorkflowPolicy(DomainModel):
    max_repair_attempts: int = Field(default=2, ge=0, le=10)
    require_plan_approval: bool = True
    require_write_approval: bool = False
    require_command_approval: bool = False


class ContextFile(DomainModel):
    path: str
    size_bytes: int = Field(ge=0)
    sha256: str
    language: str | None = None


class RepositoryContext(DomainModel):
    files: tuple[ContextFile, ...] = ()
    summary: str = ""
    truncated: bool = False
    artifact_id: str | None = None


class TaskAnalysis(DomainModel):
    objective: str
    acceptance_criteria: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    risk_level: str = "medium"


class PlanStep(DomainModel):
    order: int = Field(ge=1)
    description: str
    expected_files: tuple[str, ...] = ()
    validation: tuple[str, ...] = ()


class ImplementationPlan(DomainModel):
    summary: str
    steps: tuple[PlanStep, ...]
    proposed_commands: tuple[tuple[str, ...], ...] = ()


class Finding(DomainModel):
    title: str
    detail: str
    severity: Severity = Severity.INFO
    paths: tuple[str, ...] = ()


class AnalysisReport(DomainModel):
    summary: str
    findings: tuple[Finding, ...] = ()


class ApprovalDecision(DomainModel):
    status: ApprovalStatus = ApprovalStatus.PENDING
    actor: str | None = None
    reason: str | None = None
    decided_at: datetime | None = None


class FileChange(DomainModel):
    path: str
    operation: str
    before_sha256: str | None = None
    after_sha256: str | None = None
    artifact_id: str | None = None


class ChangeSet(DomainModel):
    summary: str
    changes: tuple[FileChange, ...] = ()


class ValidationResult(DomainModel):
    passed: bool
    command: tuple[str, ...]
    exit_code: int | None = None
    duration_ms: int = Field(default=0, ge=0)
    output_artifact_id: str | None = None
    summary: str = ""


class FailureDiagnosis(DomainModel):
    summary: str
    likely_causes: tuple[str, ...] = ()
    repair_strategy: tuple[str, ...] = ()


class ReviewResult(DomainModel):
    summary: str
    findings: tuple[Finding, ...] = ()
    blocking: bool = False


class ModelDecision(DomainModel):
    role: str
    provider: str
    model: str
    reason: str
    latency_ms: int = Field(default=0, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class ErrorRecord(DomainModel):
    node: str
    error_type: str
    message: str
    retryable: bool = False


class NodeRecord(DomainModel):
    node: str
    status: str
    detail: str = ""


class FinalReport(DomainModel):
    outcome: RunStatus
    summary: str
    changed_files: tuple[str, ...] = ()
    validation_summary: str | None = None
    review_summary: str | None = None
    stop_reason: str | None = None
