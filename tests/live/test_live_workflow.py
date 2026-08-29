from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from taskpilot.configuration import AppSettings
from taskpilot.runtime import create_runtime_app

PROJECT_ROOT = Path(__file__).parents[2]
LIVE_ENABLED = os.getenv("TASKPILOT_RUN_LIVE_TESTS", "").lower() == "true"

SCENARIOS = {
    "a": (
        "Add GET /products/{product_id}. Return the matching product and a 404 response when the "
        "ID does not exist. Add focused API tests and preserve existing endpoints."
    ),
    "b": (
        "Add optional category filtering and bounded offset/limit pagination to GET /products. "
        "Update the product data and tests to cover filtering combined with pagination, invalid "
        "query values, the empty result case, and the existing health endpoint."
    ),
}

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not LIVE_ENABLED,
        reason="set TASKPILOT_RUN_LIVE_TESTS=true to invoke a configured provider",
    ),
]


@pytest.mark.parametrize(("scenario", "task"), SCENARIOS.items())
def test_live_provider_completes_the_real_workflow(
    scenario: str,
    task: str,
    tmp_path: Path,
) -> None:
    selected = os.getenv("TASKPILOT_LIVE_SCENARIO", "all").lower()
    if selected not in {"all", scenario}:
        pytest.skip(f"live scenario selection is {selected}")

    policy_file = Path(
        os.getenv("TASKPILOT_LIVE_POLICY_FILE", str(PROJECT_ROOT / "config.live.example.yaml"))
    ).resolve()
    repository = tmp_path / f"sample-api-{scenario}"
    shutil.copytree(PROJECT_ROOT / "examples" / "sample-api", repository)
    settings = AppSettings(
        allowed_repository_roots=str(tmp_path),
        policy_file=policy_file,
        database_url=f"sqlite+aiosqlite:///{tmp_path / f'runs-{scenario}.db'}",
        checkpoint_url=str(tmp_path / f"checkpoints-{scenario}.db"),
        demo_mode=False,
    )

    with TestClient(create_runtime_app(settings)) as client:
        created = client.post(
            "/runs",
            json={"repository": str(repository), "task": task, "max_repair_attempts": 2},
        )
        assert created.status_code == 202, created.text
        run_id = created.json()["run_id"]
        _wait_for_status(client, run_id, "waiting_for_approval", timeout=300)
        approved = client.post(
            f"/runs/{run_id}/approve",
            json={"actor": "live-validation@example.com"},
        )
        assert approved.status_code == 202, approved.text
        completed = _wait_for_status(client, run_id, "completed", timeout=600)
        events = _parse_sse(client.get(f"/runs/{run_id}/events").text)

    trace = _execution_trace(scenario, completed, events)
    print("TASKPILOT_LIVE_RESULT=" + json.dumps(trace, indent=2, sort_keys=True))
    assert trace["approval"] == "approve"
    assert trace["models"]
    assert trace["graph_path"][-1] == "final_report"
    assert "write_file" in trace["tools"]
    assert "execute" in trace["tools"]
    assert trace["changed_files"]
    assert trace["validation_passed"] is True


def _wait_for_status(
    client: TestClient,
    run_id: str,
    expected: str,
    *,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = client.get(f"/runs/{run_id}")
        assert response.status_code == 200
        last = response.json()
        if last["status"] == expected:
            return last
        if last["status"] in {"failed", "rejected"}:
            events = client.get(f"/runs/{run_id}/events").text
            raise AssertionError(f"Live run stopped unexpectedly: {last}\n{events}")
        time.sleep(0.2)
    raise AssertionError(f"Live run did not reach {expected}: {last}")


def _parse_sse(body: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in body.splitlines():
        if line.startswith("data: "):
            payload = json.loads(line.removeprefix("data: "))
            if isinstance(payload, dict):
                events.append(payload)
    return events


def _execution_trace(
    scenario: str,
    completed: dict[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    model_events = [event for event in events if event["event_type"] == "model.completed"]
    tool_events = [event for event in events if event["event_type"] == "tool.completed"]
    validation = next(
        (
            event["data"]
            for event in reversed(tool_events)
            if event["data"].get("tool") == "execute"
        ),
        {},
    )
    started = datetime.fromisoformat(completed["created_at"])
    finished = datetime.fromisoformat(completed["updated_at"])
    return {
        "scenario": scenario,
        "run_id": completed["run_id"],
        "approval": completed.get("approval", {}).get("action"),
        "graph_path": [
            event["node"] for event in events if event["event_type"] == "node.completed"
        ],
        "models": [
            {
                "role": event["data"].get("role"),
                "provider": event["data"].get("provider"),
                "model": event["data"].get("model"),
                "input_tokens": event["data"].get("input_tokens"),
                "output_tokens": event["data"].get("output_tokens"),
                "latency_ms": event["data"].get("latency_ms"),
            }
            for event in model_events
        ],
        "tools": [event["data"].get("tool") for event in tool_events],
        "changed_files": completed["final_report"]["changed_files"],
        "validation_passed": validation.get("passed"),
        "validation_summary": validation.get("summary"),
        "repair_attempts": sum(
            event["event_type"] == "node.completed" and event["node"] == "repair"
            for event in events
        ),
        "duration_ms": round((finished - started).total_seconds() * 1_000),
    }
