"""Dataset-driven end-to-end evaluations against a configured TaskPilot API."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from taskpilot.cli.client import TaskPilotClient


class EvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvaluationExpectation(EvaluationModel):
    outcome: str = "completed"
    changed_files: tuple[str, ...] = ()
    path_contains: tuple[str, ...] = ()
    min_repairs: int = Field(default=0, ge=0)
    max_repairs: int = Field(default=10, ge=0)


class EvaluationCase(EvaluationModel):
    name: str = Field(min_length=1)
    repository: str = Field(min_length=1)
    task: str = Field(min_length=1)
    model_profile: str | None = None
    expectation: EvaluationExpectation = EvaluationExpectation()


class EvaluationDataset(EvaluationModel):
    name: str = Field(min_length=1)
    cases: tuple[EvaluationCase, ...] = Field(min_length=1)


class EvaluationResult(EvaluationModel):
    case: str
    passed: bool
    run_id: str
    failures: tuple[str, ...] = ()
    outcome: str
    path: tuple[str, ...]
    repairs: int


def load_dataset(path: Path) -> EvaluationDataset:
    with path.resolve().open(encoding="utf-8") as stream:
        return EvaluationDataset.model_validate(yaml.safe_load(stream))


def run_dataset(
    dataset: EvaluationDataset,
    *,
    client: TaskPilotClient,
    dataset_directory: Path,
    actor: str,
) -> tuple[EvaluationResult, ...]:
    return tuple(
        _run_case(case, client=client, dataset_directory=dataset_directory, actor=actor)
        for case in dataset.cases
    )


def _run_case(
    case: EvaluationCase,
    *,
    client: TaskPilotClient,
    dataset_directory: Path,
    actor: str,
) -> EvaluationResult:
    repository = Path(case.repository)
    if not repository.is_absolute():
        repository = (dataset_directory / repository).resolve()
    created = client.create_run(
        repository=str(repository),
        task=case.task,
        max_repair_attempts=case.expectation.max_repairs,
        require_approval=True,
        model_profile=case.model_profile,
    )
    run_id = str(created["run_id"])
    path: list[str] = []
    repairs = 0
    for event in client.events(run_id):
        envelope = event.data
        if event.event_type == "approval.required":
            client.decide(run_id, action="approve", actor=actor)
            continue
        if event.event_type == "node.completed" and envelope.get("node"):
            node = str(envelope["node"])
            path.append(node)
            if node == "repair":
                repairs += 1
        if event.event_type in {"run.completed", "run.stopped", "run.failed"}:
            break
    record = client.get_run(run_id)
    report = record.get("final_report") or {}
    outcome = str(report.get("outcome", record.get("status", "failed")))
    changed_files = set(report.get("changed_files", []))
    failures: list[str] = []
    if outcome != case.expectation.outcome:
        failures.append(f"expected outcome {case.expectation.outcome}, got {outcome}")
    missing_files = set(case.expectation.changed_files) - changed_files
    if missing_files:
        failures.append(f"missing changed files: {', '.join(sorted(missing_files))}")
    if not _is_subsequence(case.expectation.path_contains, tuple(path)):
        failures.append("required graph path was not observed")
    if not case.expectation.min_repairs <= repairs <= case.expectation.max_repairs:
        failures.append(
            f"expected {case.expectation.min_repairs}..{case.expectation.max_repairs} repairs, "
            f"got {repairs}"
        )
    return EvaluationResult(
        case=case.name,
        passed=not failures,
        run_id=run_id,
        failures=tuple(failures),
        outcome=outcome,
        path=tuple(path),
        repairs=repairs,
    )


def _is_subsequence(required: tuple[str, ...], observed: tuple[str, ...]) -> bool:
    iterator = iter(observed)
    return all(any(candidate == expected for candidate in iterator) for expected in required)
