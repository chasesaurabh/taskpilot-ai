from __future__ import annotations

import json

import httpx
import pytest

from taskpilot.cli.client import ApiClientError, TaskPilotClient, parse_sse


def test_sse_parser_supports_comments_and_multiline_json() -> None:
    events = list(
        parse_sse(
            [
                ": keep-alive",
                "",
                "id: 7",
                "event: node.completed",
                'data: {"node":"testing",',
                'data: "data":{"passed":true}}',
                "",
            ]
        )
    )

    assert events[0].sequence == 7
    assert events[0].data["data"]["passed"] is True


def test_client_creates_run_replays_events_and_sends_decision() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/runs" and request.method == "POST":
            return httpx.Response(202, json={"run_id": "run-1", "status": "running"})
        if request.url.path.endswith("/approve"):
            return httpx.Response(202, json={"run_id": "run-1", "status": "running"})
        if request.url.path.endswith("/events"):
            payload = {
                "run_id": "run-1",
                "sequence": 4,
                "event_type": "run.completed",
                "node": None,
                "data": {"outcome": "completed"},
                "created_at": "2026-08-28T12:00:00Z",
            }
            body = f"id: 4\nevent: run.completed\ndata: {json.dumps(payload)}\n\n"
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with TaskPilotClient("http://taskpilot.test", transport=httpx.MockTransport(handler)) as client:
        created = client.create_run(
            repository="repo",
            task="change",
            max_repair_attempts=2,
            require_approval=True,
            model_profile="balanced",
        )
        client.decide("run-1", action="approve", actor="tester")
        events = list(client.events("run-1", after=3))

    assert created["run_id"] == "run-1"
    assert json.loads(requests[0].content)["model_profile"] == "balanced"
    assert events[0].event_type == "run.completed"
    assert requests[-1].headers["Last-Event-ID"] == "3"


def test_client_surfaces_api_detail_and_rejects_invalid_action() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "run is already complete"})

    with TaskPilotClient("http://taskpilot.test", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ApiClientError, match="already complete"):
            client.get_run("run-1")
        with pytest.raises(ValueError, match="Unsupported"):
            client.decide("run-1", action="skip", actor="tester")
