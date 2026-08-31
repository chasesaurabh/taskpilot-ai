"""Small typed HTTP/SSE client shared by CLI commands."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

import httpx


class ApiClientError(RuntimeError):
    """A user-presentable API communication failure."""


@dataclass(frozen=True, slots=True)
class SseEvent:
    sequence: int
    event_type: str
    data: dict[str, Any]


class TaskPilotClient:
    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.BaseTransport | None = None,
        api_token: str | None = None,
    ) -> None:
        timeout = httpx.Timeout(connect=10, read=None, write=30, pool=10)
        token = api_token or os.environ.get("TASKPILOT_API_TOKEN")
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            transport=transport,
            headers={"Authorization": f"Bearer {token}"} if token else None,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> TaskPilotClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def create_run(
        self,
        *,
        repository: str,
        task: str,
        max_repair_attempts: int,
        require_approval: bool,
        require_write_approval: bool = False,
        require_command_approval: bool = False,
        model_profile: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "repository": repository,
            "task": task,
            "max_repair_attempts": max_repair_attempts,
            "require_approval": require_approval,
            "require_write_approval": require_write_approval,
            "require_command_approval": require_command_approval,
        }
        if model_profile is not None:
            payload["model_profile"] = model_profile
        return self._request_json(
            "POST",
            "/runs",
            json=payload,
        )

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"/runs/{run_id}")

    def decide(
        self,
        run_id: str,
        *,
        action: str,
        actor: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        if action not in {"approve", "reject"}:
            raise ValueError(f"Unsupported approval action: {action}")
        return self._request_json(
            "POST",
            f"/runs/{run_id}/{action}",
            json={"actor": actor, "reason": reason},
        )

    def events(self, run_id: str, *, after: int = 0) -> Iterator[SseEvent]:
        headers = {"Accept": "text/event-stream"}
        if after:
            headers["Last-Event-ID"] = str(after)
        try:
            with self._client.stream(
                "GET",
                f"/runs/{run_id}/events",
                headers=headers,
            ) as response:
                response.raise_for_status()
                yield from parse_sse(response.iter_lines())
        except httpx.HTTPError as exc:
            raise ApiClientError(_http_error_message(exc)) from exc

    def _request_json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self._client.request(method, path, **kwargs)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ApiClientError(_http_error_message(exc)) from exc
        payload = response.json()
        if not isinstance(payload, dict):
            raise ApiClientError("TaskPilot API returned a non-object response")
        return payload


def parse_sse(lines: Iterable[str]) -> Iterator[SseEvent]:
    """Parse the subset of the SSE standard emitted by TaskPilot."""

    sequence: int | None = None
    event_type = "message"
    data_lines: list[str] = []
    for line in lines:
        if line == "":
            if sequence is not None and data_lines:
                payload = json.loads("\n".join(data_lines))
                if not isinstance(payload, dict):
                    raise ApiClientError("SSE data payload must be a JSON object")
                yield SseEvent(sequence=sequence, event_type=event_type, data=payload)
            sequence = None
            event_type = "message"
            data_lines = []
        elif line.startswith(":"):
            continue
        elif line.startswith("id:"):
            try:
                sequence = int(line[3:].strip())
            except ValueError as exc:
                raise ApiClientError("SSE event ID is not an integer") from exc
        elif line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())


def _http_error_message(exc: httpx.HTTPError) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            detail = exc.response.json().get("detail")
        except (json.JSONDecodeError, AttributeError):
            detail = None
        return str(detail or f"TaskPilot API returned HTTP {exc.response.status_code}")
    return f"Could not reach the TaskPilot API: {exc}"
