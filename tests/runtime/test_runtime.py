from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.prompt_values import StringPromptValue

from taskpilot.configuration import AppSettings, load_policy, repository_policy
from taskpilot.domain.models import TaskAnalysis
from taskpilot.models.scenario import pagination_demo_model
from taskpilot.runtime import create_runtime_app

PROJECT_ROOT = Path(__file__).parents[2]


def test_environment_repository_roots_override_yaml(tmp_path: Path) -> None:
    settings = AppSettings(allowed_repository_roots=str(tmp_path))
    policy = load_policy(PROJECT_ROOT / "config.example.yaml")

    resolved = repository_policy(settings, policy)

    assert resolved.allowed_roots == (tmp_path.resolve(),)


def test_no_key_demo_rejects_tasks_it_cannot_implement_credibly() -> None:
    runnable = pagination_demo_model().with_structured_output(TaskAnalysis)

    with pytest.raises(ValueError, match="supports only"):
        runnable.invoke(StringPromptValue(text="Add a billing system"))


def test_packaged_runtime_executes_the_no_key_pagination_demo(tmp_path: Path) -> None:
    repository = tmp_path / "sample-api"
    shutil.copytree(PROJECT_ROOT / "examples" / "sample-api", repository)
    settings = AppSettings(
        allowed_repository_roots=str(tmp_path),
        policy_file=PROJECT_ROOT / "config.example.yaml",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'runs.db'}",
        checkpoint_url=str(tmp_path / "checkpoints.db"),
        demo_mode=True,
    )

    with TestClient(create_runtime_app(settings)) as client:
        response = client.post(
            "/runs",
            json={
                "repository": str(repository),
                "task": "Add pagination to the products endpoint and update tests",
            },
        )
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        waiting = _wait_for_status(client, run_id, "waiting_for_approval")
        assert waiting["status"] == "waiting_for_approval"

        approval = client.post(
            f"/runs/{run_id}/approve",
            json={"actor": "runtime-test@example.com"},
        )
        assert approval.status_code == 202
        completed = _wait_for_status(client, run_id, "completed")

        assert completed["final_report"]["changed_files"] == [
            "sample_api/app.py",
            "tests/test_app.py",
        ]
        events = client.get(f"/runs/{run_id}/events").text
        assert "event: model.completed" in events
        assert "event: tool.completed" in events
        assert "content_redacted" in events
        assert "PRODUCTS[offset : offset + limit]" not in events

    source = (repository / "sample_api" / "app.py").read_text(encoding="utf-8")
    assert "offset: int" in source
    assert "limit: int" in source


def test_packaged_runtime_resumes_after_application_restart(tmp_path: Path) -> None:
    repository = tmp_path / "sample-api"
    shutil.copytree(PROJECT_ROOT / "examples" / "sample-api", repository)
    settings = AppSettings(
        allowed_repository_roots=str(tmp_path),
        policy_file=PROJECT_ROOT / "config.example.yaml",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'runs.db'}",
        checkpoint_url=str(tmp_path / "checkpoints.db"),
        demo_mode=True,
    )

    with TestClient(create_runtime_app(settings)) as first_process:
        created = first_process.post(
            "/runs",
            json={
                "repository": str(repository),
                "task": "Add pagination to the products endpoint and update tests",
            },
        )
        run_id = created.json()["run_id"]
        _wait_for_status(first_process, run_id, "waiting_for_approval")
        assert "offset: int" not in (repository / "sample_api" / "app.py").read_text(
            encoding="utf-8"
        )

    with TestClient(create_runtime_app(settings)) as restarted_process:
        waiting = restarted_process.get(f"/runs/{run_id}")
        assert waiting.json()["status"] == "waiting_for_approval"
        approved = restarted_process.post(
            f"/runs/{run_id}/approve",
            json={"actor": "restart-test@example.com"},
        )
        assert approved.status_code == 202
        completed = _wait_for_status(restarted_process, run_id, "completed")
        events = restarted_process.get(f"/runs/{run_id}/events").text

    assert completed["final_report"] is not None
    assert events.count("event: run.started") == 1
    assert events.count("event: run.resumed") == 1
    assert "offset: int" in (repository / "sample_api" / "app.py").read_text(encoding="utf-8")


def _wait_for_status(
    client: TestClient,
    run_id: str,
    expected: str,
    *,
    timeout: float = 10,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last: dict[str, object] = {}
    while time.monotonic() < deadline:
        response = client.get(f"/runs/{run_id}")
        assert response.status_code == 200
        last = response.json()
        if last["status"] == expected:
            return last
        if last["status"] in {"failed", "rejected"}:
            raise AssertionError(f"Run stopped unexpectedly: {last}")
        time.sleep(0.02)
    raise AssertionError(f"Run did not reach {expected}: {last}")
