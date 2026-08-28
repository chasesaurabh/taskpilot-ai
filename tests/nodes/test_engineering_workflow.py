from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from taskpilot.domain.models import (
    AnalysisReport,
    FailureDiagnosis,
    FinalReport,
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
from taskpilot.tools.types import RepositoryToolPolicy


def _gateway(*, repair_content: str = "good\n") -> ModelGateway:
    def proposal(prompt: str) -> ImplementationProposal:
        content = repair_content if "Failure diagnosis" in prompt else "bad\n"
        if "Failure diagnosis" not in prompt:
            current = b"initial\n"
        elif "--- value.txt\nstill-bad\n" in prompt:
            current = b"still-bad\n"
        else:
            current = b"bad\n"
        return ImplementationProposal(
            summary="Update status value",
            changes=(
                ProposedFileChange(
                    path="value.txt",
                    operation="replace",
                    content=content,
                    expected_sha256=hashlib.sha256(current).hexdigest(),
                ),
            ),
        )

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
        ReviewResult: lambda _: ReviewResult(summary="Diff accepted", blocking=False),
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


def _graph(repository: Path, *, repair_content: str = "good\n"):
    repository_policy = RepositoryToolPolicy(
        allowed_roots=(repository.parent,),
        allow_writes=True,
        allow_commands=True,
        allowed_commands=((Path(sys.executable).name, "-c"),),
        command_timeout_seconds=5,
    )
    nodes = EngineeringNodes(
        models=_gateway(repair_content=repair_content), repository_policy=repository_policy
    )
    return build_workflow(nodes.as_workflow_nodes())


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
