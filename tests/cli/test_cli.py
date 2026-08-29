from __future__ import annotations

from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from taskpilot.cli import app as cli_module
from taskpilot.cli.client import SseEvent


class FakeClient:
    created: dict[str, Any] | None = None

    def __init__(self, _: str) -> None:
        pass

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def create_run(self, **kwargs: Any) -> dict[str, Any]:
        FakeClient.created = kwargs
        return {"run_id": "run-cli", "status": "running"}

    def events(self, _: str, *, after: int = 0):
        yield SseEvent(
            sequence=after + 1,
            event_type="approval.required",
            data={"node": "approval", "data": {"plan": {"summary": "Safe plan"}}},
        )


def test_run_command_starts_and_stops_at_approval(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cli_module, "TaskPilotClient", FakeClient)
    result = CliRunner().invoke(
        cli_module.app,
        [
            "run",
            "--repo",
            str(tmp_path),
            "--task",
            "Add pagination",
            "--approval",
            "stop",
            "--model-profile",
            "private",
        ],
    )

    assert result.exit_code == 0
    assert FakeClient.created is not None
    assert FakeClient.created["task"] == "Add pagination"
    assert FakeClient.created["model_profile"] == "private"
