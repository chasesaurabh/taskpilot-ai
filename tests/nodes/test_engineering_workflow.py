from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from taskpilot.domain.models import (
    AnalysisReport,
    FailureDiagnosis,
    FinalReport,
    Finding,
    ImplementationPlan,
    ImplementationProposal,
    PlanStep,
    ProposedFileChange,
    ReviewResult,
    RunStatus,
    TaskAnalysis,
    WorkflowPolicy,
)
from taskpilot.graph import build_workflow, create_initial_state
from taskpilot.models.config import ModelConfig, ModelRole, ModelRoutingPolicy
from taskpilot.models.demo import DeterministicModel, DeterministicModelFactory
from taskpilot.models.gateway import ModelGateway
from taskpilot.models.routing import ModelRouter
from taskpilot.nodes import EngineeringNodes
from taskpilot.tools.errors import RepositoryToolError
from taskpilot.tools.repository import RepositoryWorkspace
from taskpilot.tools.types import RepositoryToolPolicy


def _gateway(
    *,
    repair_content: str = "good\n",
    blocking_review_once: bool = False,
) -> ModelGateway:
    review_calls = 0

    def proposal(prompt: str) -> ImplementationProposal:
        content = repair_content if "Failure diagnosis" in prompt else "bad\n"
        return ImplementationProposal(
            summary="Update status value",
            changes=(
                ProposedFileChange(
                    path="value.txt",
                    operation="replace",
                    content=content,
                ),
            ),
        )

    def review(_: str) -> ReviewResult:
        nonlocal review_calls
        review_calls += 1
        if blocking_review_once and review_calls == 1:
            return ReviewResult(
                summary="A blocking issue remains",
                blocking=True,
                findings=(
                    Finding(
                        title="Normalize output",
                        detail="Ensure the stored value remains normalized",
                        severity="blocking",
                    ),
                ),
            )
        return ReviewResult(summary="Diff accepted", blocking=False)

    handlers = {
        TaskAnalysis: lambda _: TaskAnalysis(objective="Update value", risk_level="low"),
        ImplementationPlan: lambda _: ImplementationPlan(
            summary="Change value and validate",
            steps=(PlanStep(order=1, description="Update value.txt"),),
            proposed_commands=(
                (
                    Path(sys.executable).name,
                    "-c",
                    "import pathlib,sys;"
                    "sys.exit(pathlib.Path('value.txt').read_text().strip()!='good')",
                ),
            ),
        ),
        AnalysisReport: lambda prompt: AnalysisReport(
            summary="Architecture reviewed" if "boundaries" in prompt else "Impact reviewed"
        ),
        ImplementationProposal: proposal,
        FailureDiagnosis: lambda _: FailureDiagnosis(
            summary="The value is invalid",
            likely_causes=("bad fixture value",),
            repair_strategy=("write good",),
        ),
        ReviewResult: review,
        FinalReport: lambda _: FinalReport(
            outcome=RunStatus.COMPLETED,
            summary="Value updated and validation passed",
        ),
    }
    config = ModelConfig(provider="demo", model="deterministic")
    policy = ModelRoutingPolicy(
        models={"demo": config},
        assignments={role: "demo" for role in ModelRole},
    )
    return ModelGateway(
        ModelRouter(policy),
        DeterministicModelFactory(DeterministicModel(handlers)),
    )


def _graph(
    repository: Path,
    *,
    repair_content: str = "good\n",
    blocking_review_once: bool = False,
    checkpointer: Any | None = None,
):
    repository_policy = RepositoryToolPolicy(
        allowed_roots=(repository.parent,),
        allow_writes=True,
        allow_commands=True,
        allowed_commands=((Path(sys.executable).name, "-c"),),
        command_timeout_seconds=5,
    )
    nodes = EngineeringNodes(
        models=_gateway(
            repair_content=repair_content,
            blocking_review_once=blocking_review_once,
        ),
        repository_policy=repository_policy,
    )
    return build_workflow(nodes.as_workflow_nodes(), checkpointer=checkpointer)


def _repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(("git", "init", "--quiet"), cwd=repository, check=True)
    (repository / "value.txt").write_bytes(b"initial\n")
    return repository


def test_real_nodes_apply_repair_retest_review_and_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _repository(tmp_path)
    monkeypatch.setenv(
        "PATH", f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}"
    )
    graph = _graph(repository)

    result = graph.invoke(
        create_initial_state(
            run_id="real-success",
            task="Set the value to good",
            repository_root=str(repository),
            policy=WorkflowPolicy(require_plan_approval=False, max_repair_attempts=2),
        )
    )

    assert (repository / "value.txt").read_text(encoding="utf-8") == "good\n"
    assert result["repair_attempts"] == 1
    assert result["validation"].passed is True
    assert result["final_report"].outcome == RunStatus.COMPLETED
    assert len(result["model_decisions"]) == 9


def test_real_nodes_stop_safely_when_repairs_never_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _repository(tmp_path)
    monkeypatch.setenv(
        "PATH", f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}"
    )
    graph = _graph(repository, repair_content="still-bad\n")

    result = graph.invoke(
        create_initial_state(
            run_id="exhausted",
            task="Set the value to good",
            repository_root=str(repository),
            policy=WorkflowPolicy(require_plan_approval=False, max_repair_attempts=2),
        )
    )

    assert result["repair_attempts"] == 2
    assert result["validation"].passed is False
    assert result["final_report"].outcome == RunStatus.FAILED
    assert "exhausted" in (result["final_report"].stop_reason or "")
    assert "code_review" not in [record.node for record in result["node_history"]]


def test_blocking_review_drives_a_focused_repair_without_stale_validation_diagnosis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(tmp_path)
    monkeypatch.setenv(
        "PATH", f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}"
    )
    graph = _graph(repository, blocking_review_once=True)

    result = graph.invoke(
        create_initial_state(
            run_id="review-repair",
            task="Set the value to good and resolve blocking review findings",
            repository_root=str(repository),
            policy=WorkflowPolicy(require_plan_approval=False, max_repair_attempts=3),
        )
    )

    history = [record.node for record in result["node_history"]]
    assert history.count("code_review") == 2
    assert history[-5:] == ["code_review", "repair", "testing", "code_review", "final_report"]
    assert result["repair_attempts"] == 2
    assert result["final_report"].outcome == RunStatus.COMPLETED


def test_proposal_is_fully_validated_before_the_first_repository_write(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    workspace = RepositoryWorkspace(
        repository,
        RepositoryToolPolicy(allowed_roots=(tmp_path,), allow_writes=True),
    )
    proposal = ImplementationProposal(
        summary="Invalid duplicate proposal",
        changes=(
            ProposedFileChange(path="value.txt", operation="replace", content="first\n"),
            ProposedFileChange(path="value.txt", operation="replace", content="second\n"),
        ),
    )

    with pytest.raises(RepositoryToolError, match="same path"):
        EngineeringNodes._apply_proposal(
            workspace,
            proposal,
            {"value.txt": hashlib.sha256(b"initial\n").hexdigest()},
        )

    assert (repository / "value.txt").read_bytes() == b"initial\n"


def test_real_approval_interrupt_discloses_plan_and_blocks_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _repository(tmp_path)
    monkeypatch.setenv(
        "PATH", f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}"
    )
    graph = _graph(repository, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "approval-run"}}

    paused = graph.invoke(
        create_initial_state(
            run_id="approval-run",
            task="Set the value to good",
            repository_root=str(repository),
            policy=WorkflowPolicy(require_plan_approval=True, max_repair_attempts=2),
        ),
        config,
    )

    payload = paused["__interrupt__"][0].value
    assert payload["run_id"] == "approval-run"
    assert payload["plan"]["summary"] == "Change value and validate"
    assert payload["proposed_commands"]
    assert (repository / "value.txt").read_bytes() == b"initial\n"

    result = graph.invoke(
        Command(resume={"action": "approve", "actor": "principal@example.com"}),
        config,
    )

    assert result["approval"].actor == "principal@example.com"
    assert result["final_report"].outcome == RunStatus.COMPLETED
