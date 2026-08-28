"""HTTP lifecycle and replayable SSE transport."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from taskpilot.api.schemas import ApprovalRequestBody, CreateRunRequest
from taskpilot.application.runs import RunService
from taskpilot.domain.models import ApprovalAction, WorkflowPolicy
from taskpilot.persistence.runs import (
    TERMINAL_STATUSES,
    RunConflictError,
    RunEvent,
    RunNotFoundError,
    RunRecord,
)
from taskpilot.tools.errors import RepositoryToolError


def create_app(service: RunService) -> FastAPI:
    app = FastAPI(
        title="TaskPilot AI API",
        version="0.1.0",
        description="Lifecycle API for durable software-engineering workflows.",
    )
    app.state.run_service = service

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/runs", response_model=RunRecord, status_code=status.HTTP_202_ACCEPTED)
    async def create_run(body: CreateRunRequest, request: Request) -> RunRecord:
        run_service = _service(request)
        try:
            return await run_service.start_run(
                task=body.task,
                repository=body.repository,
                policy=WorkflowPolicy(
                    max_repair_attempts=body.max_repair_attempts,
                    require_plan_approval=body.require_approval,
                ),
            )
        except RepositoryToolError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/runs/{run_id}", response_model=RunRecord)
    async def get_run(run_id: str, request: Request) -> RunRecord:
        try:
            return await _service(request).store.get_run(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/runs/{run_id}/events")
    async def stream_events(
        run_id: str,
        request: Request,
        last_event_id: int | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        try:
            await _service(request).store.get_run(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return StreamingResponse(
            _event_stream(_service(request), run_id, last_event_id or 0),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/runs/{run_id}/approve", response_model=RunRecord, status_code=202)
    async def approve(
        run_id: str,
        body: ApprovalRequestBody,
        request: Request,
    ) -> RunRecord:
        return await _resume(request, run_id, ApprovalAction.APPROVE, body)

    @app.post("/runs/{run_id}/reject", response_model=RunRecord, status_code=202)
    async def reject(
        run_id: str,
        body: ApprovalRequestBody,
        request: Request,
    ) -> RunRecord:
        return await _resume(request, run_id, ApprovalAction.REJECT, body)

    return app


def _service(request: Request) -> RunService:
    service: RunService = request.app.state.run_service
    return service


async def _resume(
    request: Request,
    run_id: str,
    action: ApprovalAction,
    body: ApprovalRequestBody,
) -> RunRecord:
    try:
        return await _service(request).resume(
            run_id,
            action=action,
            actor=body.actor,
            reason=body.reason,
        )
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RunConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


async def _event_stream(service: RunService, run_id: str, after: int) -> AsyncIterator[str]:
    cursor = after
    revision = service.store.revision
    while True:
        events = await service.store.list_events(run_id, after=cursor)
        for event in events:
            cursor = event.sequence
            yield _format_sse(event)
        record = await service.store.get_run(run_id)
        if record.status in TERMINAL_STATUSES:
            return
        next_revision = await service.store.wait_for_change(revision)
        if next_revision == revision:
            yield ": keep-alive\n\n"
        revision = next_revision


def _format_sse(event: RunEvent) -> str:
    payload = event.model_dump(mode="json")
    return (
        f"id: {event.sequence}\n"
        f"event: {event.event_type}\n"
        f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
    )
