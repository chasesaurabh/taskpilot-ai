"""Production node responsibilities composed from model and repository boundaries."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from langgraph.types import interrupt
from pydantic import BaseModel, ConfigDict, Field

from taskpilot.artifacts import ArtifactStore
from taskpilot.domain.models import (
    AnalysisReport,
    ApprovalAction,
    ApprovalDecision,
    ApprovalKind,
    ApprovalRequest,
    ApprovalResponse,
    ApprovalStatus,
    ArtifactKind,
    ArtifactRef,
    ChangeSet,
    ContextFile,
    FailureDiagnosis,
    FileChange,
    FilePrecondition,
    FinalReport,
    ImplementationPlan,
    ImplementationProposal,
    NodeRecord,
    ProposedFileChange,
    RepositoryContext,
    ReviewResult,
    RunStatus,
    TaskAnalysis,
    ValidationResult,
)
from taskpilot.graph.builder import WorkflowNodes
from taskpilot.graph.state import WorkflowState, WorkflowUpdate
from taskpilot.models.config import ModelRole, RoutingContext, TaskComplexity
from taskpilot.models.gateway import ModelGateway
from taskpilot.prompts.catalog import (
    ARCHITECTURE_PROMPT,
    CODE_REVIEW_PROMPT,
    FAILURE_ANALYSIS_PROMPT,
    FINAL_REPORT_PROMPT,
    IMPLEMENTATION_PROMPT,
    PLANNING_PROMPT,
    REPAIR_PROMPT,
    REPOSITORY_IMPACT_PROMPT,
    TASK_ANALYSIS_PROMPT,
)
from taskpilot.tools.errors import RepositoryToolError
from taskpilot.tools.repository import RepositoryWorkspace
from taskpilot.tools.types import RepositoryToolPolicy


class EngineeringNodesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_context_bytes: int = Field(default=1_048_576, ge=1)
    context_file_limit: int = Field(default=100, ge=1)
    default_validation_commands: tuple[tuple[str, ...], ...] = ()


class EngineeringNodes:
    """Node collection with deterministic policy around probabilistic outputs."""

    def __init__(
        self,
        *,
        models: ModelGateway,
        repository_policy: RepositoryToolPolicy,
        config: EngineeringNodesConfig | None = None,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self._models = models
        self._repository_policy = repository_policy
        self._config = config or EngineeringNodesConfig()
        self._artifact_store = artifact_store

    def as_workflow_nodes(self) -> WorkflowNodes:
        return WorkflowNodes(
            repository_context=self.repository_context,
            task_analysis=self.task_analysis,
            planning=self.planning,
            architecture_review=self.architecture_review,
            repository_analysis=self.repository_analysis,
            approval=self.approval,
            implementation=self.implementation,
            testing=self.testing,
            failure_analysis=self.failure_analysis,
            repair=self.repair,
            code_review=self.code_review,
            final_report=self.final_report,
            write_approval=self.write_approval,
            apply_changes=self.apply_changes,
            command_approval=self.command_approval,
        )

    def _workspace(self, state: WorkflowState) -> RepositoryWorkspace:
        return RepositoryWorkspace(Path(state["repository"].root), self._repository_policy)

    def _routing_context(self, state: WorkflowState) -> RoutingContext:
        file_count = len(state.get("context", RepositoryContext()).files)
        risk = state.get("task_analysis")
        complexity = TaskComplexity.STANDARD
        if risk and risk.risk_level.lower() == "high":
            complexity = TaskComplexity.COMPLEX
        elif risk and risk.risk_level.lower() == "low":
            complexity = TaskComplexity.SIMPLE
        return RoutingContext(
            complexity=complexity,
            repository_file_count=file_count,
            profile=state["policy"].model_profile,
        )

    @staticmethod
    def _record(node: str, detail: str = "") -> list[NodeRecord]:
        return [NodeRecord(node=node, status="completed", detail=detail)]

    def _context_text(self, workspace: RepositoryWorkspace) -> str:
        sections: list[str] = []
        consumed = 0
        for entry in workspace.list_files()[: self._config.context_file_limit]:
            if consumed + entry.size_bytes > self._config.max_context_bytes:
                break
            try:
                content = workspace.read_file(entry.path)
            except RepositoryToolError:
                continue
            section = f"--- {entry.path}\n{content.content}"
            encoded_size = len(section.encode())
            if consumed + encoded_size > self._config.max_context_bytes:
                break
            sections.append(section)
            consumed += encoded_size
        return "\n\n".join(sections)

    def repository_context(self, state: WorkflowState) -> WorkflowUpdate:
        workspace = self._workspace(state)
        entries = workspace.list_files()
        files: list[ContextFile] = []
        consumed = 0
        truncated = len(entries) > self._config.context_file_limit
        for entry in entries[: self._config.context_file_limit]:
            if consumed + entry.size_bytes > self._config.max_context_bytes:
                truncated = True
                break
            try:
                content = workspace.read_file(entry.path)
            except RepositoryToolError:
                continue
            files.append(
                ContextFile(
                    path=entry.path,
                    size_bytes=entry.size_bytes,
                    sha256=content.sha256,
                    language=_language_for(entry.path),
                )
            )
            consumed += entry.size_bytes
        context = RepositoryContext(
            files=tuple(files),
            summary=f"Collected {len(files)} text files ({consumed} bytes)",
            truncated=truncated,
        )
        return WorkflowUpdate(
            context=context,
            node_history=self._record("repository_context", context.summary),
        )

    def task_analysis(self, state: WorkflowState) -> WorkflowUpdate:
        workspace = self._workspace(state)
        call = self._models.invoke_structured(
            role=ModelRole.ANALYST,
            routing_context=self._routing_context(state),
            prompt=TASK_ANALYSIS_PROMPT,
            variables={
                "task": state["task"].description,
                "context": self._context_text(workspace),
            },
            output_schema=TaskAnalysis,
        )
        return WorkflowUpdate(
            task_analysis=call.output,
            model_decisions=[call.decision],
            node_history=self._record("task_analysis", call.output.objective),
        )

    def planning(self, state: WorkflowState) -> WorkflowUpdate:
        workspace = self._workspace(state)
        allowed_commands = "\n".join(
            "- " + " ".join(command) for command in self._repository_policy.allowed_commands
        )
        call = self._models.invoke_structured(
            role=ModelRole.PLANNER,
            routing_context=self._routing_context(state),
            prompt=PLANNING_PROMPT,
            variables={
                "analysis": state["task_analysis"].model_dump_json(indent=2),
                "context": self._context_text(workspace),
                "allowed_commands": allowed_commands or "No validation commands are configured.",
            },
            output_schema=ImplementationPlan,
        )
        plan = call.output.model_copy(
            update={
                "proposed_commands": self._select_validation_commands(call.output.proposed_commands)
            }
        )
        return WorkflowUpdate(
            plan=plan,
            model_decisions=[call.decision],
            node_history=self._record("planning", plan.summary),
        )

    def architecture_review(self, state: WorkflowState) -> WorkflowUpdate:
        call = self._models.invoke_structured(
            role=ModelRole.ARCHITECT,
            routing_context=self._routing_context(state),
            prompt=ARCHITECTURE_PROMPT,
            variables={
                "task": state["task"].description,
                "plan": state["plan"].model_dump_json(indent=2),
            },
            output_schema=AnalysisReport,
        )
        return WorkflowUpdate(
            architecture_report=call.output,
            model_decisions=[call.decision],
            node_history=self._record("architecture_review", call.output.summary),
        )

    def repository_analysis(self, state: WorkflowState) -> WorkflowUpdate:
        workspace = self._workspace(state)
        call = self._models.invoke_structured(
            role=ModelRole.ANALYST,
            routing_context=self._routing_context(state),
            prompt=REPOSITORY_IMPACT_PROMPT,
            variables={
                "plan": state["plan"].model_dump_json(indent=2),
                "context": self._context_text(workspace),
            },
            output_schema=AnalysisReport,
        )
        return WorkflowUpdate(
            repository_report=call.output,
            model_decisions=[call.decision],
            node_history=self._record("repository_analysis", call.output.summary),
        )

    def approval(self, state: WorkflowState) -> WorkflowUpdate:
        proposed_files = tuple(
            dict.fromkeys(path for step in state["plan"].steps for path in step.expected_files)
        )
        risks = tuple(
            finding.detail
            for report in (state["architecture_report"], state["repository_report"])
            for finding in report.findings
            if finding.severity in {"warning", "blocking"}
        )
        return self._approval_update(
            state,
            kind=ApprovalKind.PLAN,
            required=state["policy"].require_plan_approval,
            node="approval",
            summary=state["plan"].summary,
            proposed_files=proposed_files,
            proposed_commands=state["plan"].proposed_commands,
            risks=risks,
            architecture=state["architecture_report"],
            repository_impact=state["repository_report"],
        )

    def implementation(self, state: WorkflowState) -> WorkflowUpdate:
        workspace = self._workspace(state)
        context, expected_hashes = self._proposal_context(workspace)
        call = self._models.invoke_structured(
            role=ModelRole.CODER,
            routing_context=self._routing_context(state),
            prompt=IMPLEMENTATION_PROMPT,
            variables={
                "plan": state["plan"].model_dump_json(indent=2),
                "context": context,
            },
            output_schema=ImplementationProposal,
        )
        preconditions = self._proposal_preconditions(call.output, expected_hashes)
        return WorkflowUpdate(
            proposal=call.output,
            proposal_preconditions=preconditions,
            model_decisions=[call.decision],
            node_history=self._record("implementation", call.output.summary),
        )

    def write_approval(self, state: WorkflowState) -> WorkflowUpdate:
        proposal = state["proposal"]
        return self._approval_update(
            state,
            kind=ApprovalKind.WRITE,
            required=state["policy"].require_write_approval,
            node="write_approval",
            summary=proposal.summary,
            proposed_files=tuple(change.path for change in proposal.changes),
        )

    def apply_changes(self, state: WorkflowState) -> WorkflowUpdate:
        workspace = self._workspace(state)
        expected_hashes = {
            item.path: item.expected_sha256 for item in state["proposal_preconditions"]
        }
        change_set = self._apply_proposal(workspace, state["proposal"], expected_hashes)
        artifact = self._put_artifact(
            state,
            kind=ArtifactKind.PATCH,
            content=workspace.git_diff().output,
            media_type="text/x-diff",
        )
        if artifact is not None:
            change_set = change_set.model_copy(update={"artifacts": (artifact,)})
        return WorkflowUpdate(
            change_set=change_set,
            node_history=self._record("apply_changes", change_set.summary),
        )

    def command_approval(self, state: WorkflowState) -> WorkflowUpdate:
        commands = self._select_validation_commands(state["plan"].proposed_commands)
        return self._approval_update(
            state,
            kind=ApprovalKind.COMMAND,
            required=state["policy"].require_command_approval,
            node="command_approval",
            summary="Run configured validation commands",
            proposed_commands=commands,
        )

    def testing(self, state: WorkflowState) -> WorkflowUpdate:
        workspace = self._workspace(state)
        commands = self._select_validation_commands(state["plan"].proposed_commands)
        artifacts: list[ArtifactRef] = []
        if not commands:
            validation = ValidationResult(
                passed=False,
                command=(),
                summary="No validation command was configured",
            )
        else:
            validation = ValidationResult(
                passed=True,
                command=commands[-1],
                summary="All configured validation commands passed",
            )
            for command in commands:
                try:
                    result = workspace.execute(command)
                except RepositoryToolError as exc:
                    validation = ValidationResult(
                        passed=False,
                        command=command,
                        summary=f"Validation command was denied or unavailable: {exc}",
                    )
                    break
                artifact = self._put_artifact(
                    state,
                    kind=ArtifactKind.VALIDATION_LOG,
                    content=result.output,
                    media_type="text/plain",
                )
                if artifact is not None:
                    artifacts.append(artifact)
                if result.exit_code != 0 or result.timed_out or result.output_truncated:
                    summary = result.output[-4_000:] or "Validation command failed without output"
                    validation = ValidationResult(
                        passed=False,
                        command=command,
                        exit_code=result.exit_code,
                        duration_ms=result.duration_ms,
                        summary=summary,
                    )
                    break
                validation = ValidationResult(
                    passed=True,
                    command=command,
                    exit_code=result.exit_code,
                    duration_ms=result.duration_ms,
                    summary=result.output[-4_000:] or "Validation command passed",
                )
            validation = validation.model_copy(update={"artifacts": tuple(artifacts)})
        status = "passed" if validation.passed else "failed"
        return WorkflowUpdate(
            validation=validation,
            node_history=self._record("testing", status),
        )

    def _select_validation_commands(
        self,
        proposed: tuple[tuple[str, ...], ...],
    ) -> tuple[tuple[str, ...], ...]:
        allowed = tuple(
            command
            for command in proposed
            if command
            and any(
                command[: len(prefix)] == prefix
                for prefix in self._repository_policy.allowed_commands
            )
        )
        return allowed or self._config.default_validation_commands

    def failure_analysis(self, state: WorkflowState) -> WorkflowUpdate:
        call = self._models.invoke_structured(
            role=ModelRole.CODER,
            routing_context=self._routing_context(state),
            prompt=FAILURE_ANALYSIS_PROMPT,
            variables={
                "changes": state["change_set"].model_dump_json(indent=2),
                "validation": state["validation"].model_dump_json(indent=2),
            },
            output_schema=FailureDiagnosis,
        )
        return WorkflowUpdate(
            diagnosis=call.output,
            model_decisions=[call.decision],
            node_history=self._record("failure_analysis", call.output.summary),
        )

    def repair(self, state: WorkflowState) -> WorkflowUpdate:
        workspace = self._workspace(state)
        context, expected_hashes = self._proposal_context(workspace)
        diagnosis = _repair_diagnosis(state)
        call = self._models.invoke_structured(
            role=ModelRole.CODER,
            routing_context=self._routing_context(state),
            prompt=REPAIR_PROMPT,
            variables={
                "plan": state["plan"].model_dump_json(indent=2),
                "context": context,
                "diagnosis": diagnosis.model_dump_json(indent=2),
            },
            output_schema=ImplementationProposal,
        )
        attempts = state["repair_attempts"] + 1
        return WorkflowUpdate(
            proposal=call.output,
            proposal_preconditions=self._proposal_preconditions(call.output, expected_hashes),
            repair_attempts=attempts,
            model_decisions=[call.decision],
            node_history=self._record("repair", f"repair attempt {attempts}"),
        )

    def _approval_update(
        self,
        state: WorkflowState,
        *,
        kind: ApprovalKind,
        required: bool,
        node: str,
        summary: str,
        proposed_files: tuple[str, ...] = (),
        proposed_commands: tuple[tuple[str, ...], ...] = (),
        risks: tuple[str, ...] = (),
        architecture: AnalysisReport | None = None,
        repository_impact: AnalysisReport | None = None,
    ) -> WorkflowUpdate:
        approval_id = f"{state['metadata'].run_id}:{kind.value}:{state.get('repair_attempts', 0)}"
        if required:
            request = ApprovalRequest(
                kind=kind,
                approval_id=approval_id,
                run_id=state["metadata"].run_id,
                task=state["task"].description,
                plan=state["plan"],
                architecture=architecture,
                repository_impact=repository_impact,
                summary=summary,
                proposed_files=proposed_files,
                proposed_commands=proposed_commands,
                risks=risks,
            )
            response = ApprovalResponse.model_validate(interrupt(request.model_dump(mode="json")))
            status = (
                ApprovalStatus.APPROVED
                if response.action == ApprovalAction.APPROVE
                else ApprovalStatus.REJECTED
            )
            decision = ApprovalDecision(
                kind=kind,
                approval_id=approval_id,
                status=status,
                actor=response.actor,
                reason=response.reason,
                decided_at=datetime.now(UTC),
            )
            detail = f"{response.action} by {response.actor}"
        else:
            decision = ApprovalDecision(
                kind=kind,
                approval_id=approval_id,
                status=ApprovalStatus.APPROVED,
                actor="policy:auto",
            )
            detail = "auto-approved by policy"
        return WorkflowUpdate(
            approval=decision,
            approval_history=[decision],
            node_history=self._record(node, detail),
        )

    def _put_artifact(
        self,
        state: WorkflowState,
        *,
        kind: ArtifactKind,
        content: str,
        media_type: str,
    ) -> ArtifactRef | None:
        if self._artifact_store is None:
            return None
        return self._artifact_store.put_text(
            run_id=state["metadata"].run_id,
            kind=kind,
            content=content,
            media_type=media_type,
        )

    def code_review(self, state: WorkflowState) -> WorkflowUpdate:
        workspace = self._workspace(state)
        diff = workspace.git_diff()
        call = self._models.invoke_structured(
            role=ModelRole.REVIEWER,
            routing_context=self._routing_context(state),
            prompt=CODE_REVIEW_PROMPT,
            variables={
                "task": state["task"].description,
                "diff": diff.output,
                "validation": state["validation"].model_dump_json(indent=2),
            },
            output_schema=ReviewResult,
        )
        return WorkflowUpdate(
            review=call.output,
            model_decisions=[call.decision],
            node_history=self._record("code_review", call.output.summary),
        )

    def final_report(self, state: WorkflowState) -> WorkflowUpdate:
        outcome, stop_reason = _determine_outcome(state)
        call = self._models.invoke_structured(
            role=ModelRole.REPORTER,
            routing_context=self._routing_context(state),
            prompt=FINAL_REPORT_PROMPT,
            variables={
                "task": state["task"].description,
                "state_summary": _state_summary(state, outcome, stop_reason),
            },
            output_schema=FinalReport,
        )
        changed_files = tuple(
            change.path for change in state.get("change_set", ChangeSet(summary="")).changes
        )
        validation = state.get("validation")
        review = state.get("review")
        report = call.output.model_copy(
            update={
                "outcome": outcome,
                "changed_files": changed_files,
                "validation_summary": validation.summary if validation else None,
                "review_summary": review.summary if review else None,
                "stop_reason": stop_reason,
            }
        )
        return WorkflowUpdate(
            final_report=report,
            model_decisions=[call.decision],
            node_history=self._record("final_report", outcome),
        )

    def _proposal_context(
        self,
        workspace: RepositoryWorkspace,
    ) -> tuple[str, dict[str, str]]:
        sections: list[str] = []
        hashes: dict[str, str] = {}
        consumed = 0
        for entry in workspace.list_files()[: self._config.context_file_limit]:
            if consumed + entry.size_bytes > self._config.max_context_bytes:
                break
            try:
                content = workspace.read_file(entry.path)
            except RepositoryToolError:
                continue
            section = f"--- {entry.path}\n{content.content}"
            encoded_size = len(section.encode())
            if consumed + encoded_size > self._config.max_context_bytes:
                break
            sections.append(section)
            hashes[entry.path] = content.sha256
            consumed += encoded_size
        return "\n\n".join(sections), hashes

    @staticmethod
    def _proposal_preconditions(
        proposal: ImplementationProposal,
        expected_hashes: dict[str, str],
    ) -> tuple[FilePrecondition, ...]:
        return tuple(
            FilePrecondition(
                path=Path(change.path).as_posix().removeprefix("./"),
                expected_sha256=expected_hashes.get(
                    Path(change.path).as_posix().removeprefix("./")
                ),
            )
            for change in proposal.changes
        )

    @staticmethod
    def _apply_proposal(
        workspace: RepositoryWorkspace,
        proposal: ImplementationProposal,
        expected_hashes: dict[str, str | None],
    ) -> ChangeSet:
        normalized_changes: list[tuple[str, ProposedFileChange]] = []
        seen: set[str] = set()
        for change in proposal.changes:
            normalized_path = Path(change.path).as_posix().removeprefix("./")
            if normalized_path in seen:
                raise RepositoryToolError(
                    f"Proposal contains the same path more than once: {normalized_path}"
                )
            seen.add(normalized_path)
            normalized_changes.append((normalized_path, change))

        applied: list[FileChange] = []
        for normalized_path, change in normalized_changes:
            result = workspace.write_file(
                normalized_path,
                change.content,
                expected_sha256=expected_hashes.get(normalized_path),
            )
            applied.append(
                FileChange(
                    path=result.path,
                    operation="create" if result.created else "replace",
                    before_sha256=result.previous_sha256,
                    after_sha256=result.sha256,
                )
            )
        return ChangeSet(summary=proposal.summary, changes=tuple(applied))


def _language_for(path: str) -> str | None:
    return {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
    }.get(Path(path).suffix.lower())


def _determine_outcome(state: WorkflowState) -> tuple[RunStatus, str | None]:
    approval = state["approval"].status
    if approval == ApprovalStatus.REJECTED:
        kind = state["approval"].kind
        return RunStatus.REJECTED, state["approval"].reason or f"The {kind} action was rejected"
    if approval != ApprovalStatus.APPROVED:
        return RunStatus.FAILED, "Implementation did not receive approval"
    validation = state.get("validation")
    if validation is None or not validation.passed:
        return RunStatus.FAILED, "Validation failed and the repair budget was exhausted"
    review = state.get("review")
    if review and review.blocking:
        return RunStatus.FAILED, "Blocking review findings remained after the repair budget"
    return RunStatus.COMPLETED, None


def _state_summary(
    state: WorkflowState,
    outcome: RunStatus,
    stop_reason: str | None,
) -> str:
    parts = [
        f"outcome={outcome}",
        f"repairs={state['repair_attempts']}/{state['policy'].max_repair_attempts}",
        f"approval={state['approval'].kind}:{state['approval'].status}",
    ]
    if state.get("validation"):
        parts.append(f"validation={state['validation'].summary}")
    if state.get("review"):
        parts.append(f"review={state['review'].summary}")
    if stop_reason:
        parts.append(f"stop_reason={stop_reason}")
    return "\n".join(parts)


def _repair_diagnosis(state: WorkflowState) -> FailureDiagnosis:
    review = state.get("review")
    if review is not None and review.blocking:
        return FailureDiagnosis(
            summary="Code review reported blocking findings",
            likely_causes=tuple(finding.detail for finding in review.findings),
            repair_strategy=tuple(
                f"Resolve {finding.title}: {finding.detail}" for finding in review.findings
            ),
        )
    diagnosis = state.get("diagnosis")
    if diagnosis is None:
        raise RepositoryToolError("Repair was requested without a validation or review diagnosis")
    return diagnosis
