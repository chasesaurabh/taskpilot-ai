"""HTTP lifecycle and replayable SSE transport."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from uuid import uuid4

import structlog
from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from structlog.contextvars import bind_contextvars, clear_contextvars

from taskpilot.api.schemas import ApprovalRequestBody, CreateRunRequest, ModelProfilesResponse
from taskpilot.application.runs import RunService
from taskpilot.artifacts import ArtifactNotFoundError
from taskpilot.auth import AuthenticationError, Authenticator, Principal, TokenAuthenticator
from taskpilot.domain.models import ApprovalAction, WorkflowPolicy
from taskpilot.models.errors import ModelConfigurationError
from taskpilot.persistence.runs import (
    TERMINAL_STATUSES,
    RunConflictError,
    RunEvent,
    RunNotFoundError,
    RunRecord,
)
from taskpilot.tools.errors import RepositoryToolError

Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def create_app(
    service: RunService | None = None,
    *,
    lifespan: Lifespan | None = None,
    authenticator: Authenticator | None = None,
    approval_role: str | None = None,
    admin_role: str = "admin",
) -> FastAPI:
    app = FastAPI(
        title="TaskPilot AI API",
        version="0.2.0",
        description="Lifecycle API for durable software-engineering workflows.",
        lifespan=lifespan,
    )
    if service is not None:
        app.state.run_service = service
    app.state.authenticator = authenticator or TokenAuthenticator()
    app.state.approval_role = approval_role
    app.state.admin_role = admin_role
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        clear_contextvars()
        bind_contextvars(request_id=request_id)
        logger = structlog.get_logger(__name__)
        logger.info("request_started", method=request.method, path=request.url.path)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            logger.info("request_finished", status_code=response.status_code)
            return response
        except Exception:
            logger.exception("request_failed")
            raise
        finally:
            clear_contextvars()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/runs", response_model=RunRecord, status_code=status.HTTP_202_ACCEPTED)
    async def create_run(body: CreateRunRequest, request: Request) -> RunRecord:
        run_service = _service(request)
        principal = _principal(request)
        try:
            return await run_service.start_run(
                task=body.task,
                repository=body.repository,
                policy=WorkflowPolicy(
                    max_repair_attempts=body.max_repair_attempts,
                    require_plan_approval=body.require_approval,
                    require_write_approval=body.require_write_approval,
                    require_command_approval=body.require_command_approval,
                    model_profile=body.model_profile,
                ),
                owner_id=principal.principal_id,
            )
        except (ModelConfigurationError, RepositoryToolError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/model-profiles", response_model=ModelProfilesResponse)
    async def model_profiles(request: Request) -> ModelProfilesResponse:
        _principal(request)
        run_service = _service(request)
        return ModelProfilesResponse(
            default_profile=run_service.default_model_profile,
            profiles=run_service.model_profiles,
        )

    @app.get("/runs", response_model=list[RunRecord])
    async def list_runs(request: Request) -> tuple[RunRecord, ...]:
        principal = _principal(request)
        return await _service(request).store.list_runs(owner_id=principal.principal_id)

    @app.get("/admin/runs", response_model=list[RunRecord])
    async def admin_runs(request: Request) -> tuple[RunRecord, ...]:
        _require_role(_principal(request), request.app.state.admin_role)
        return await _service(request).store.list_all_runs()

    @app.get("/admin/runs/{run_id}/events", response_model=list[RunEvent])
    async def admin_run_events(run_id: str, request: Request) -> tuple[RunEvent, ...]:
        _require_role(_principal(request), request.app.state.admin_role)
        try:
            return await _service(request).store.list_events(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/runs/{run_id}", response_model=RunRecord)
    async def get_run(run_id: str, request: Request) -> RunRecord:
        try:
            return await _service(request).get_owned_run(
                run_id, owner_id=_principal(request).principal_id
            )
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/runs/{run_id}/artifacts/{artifact_id}")
    async def get_artifact(run_id: str, artifact_id: str, request: Request) -> Response:
        run_service = _service(request)
        try:
            await run_service.get_owned_run(run_id, owner_id=_principal(request).principal_id)
            if run_service.artifacts is None:
                raise ArtifactNotFoundError("Artifact storage is not configured")
            ref, content = run_service.artifacts.get_bytes(run_id=run_id, artifact_id=artifact_id)
        except (RunNotFoundError, ArtifactNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(
            content=content,
            media_type=ref.media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{artifact_id}"',
                "X-Artifact-SHA256": ref.sha256,
            },
        )

    @app.get("/runs/{run_id}/events")
    async def stream_events(
        run_id: str,
        request: Request,
        last_event_id: int | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        try:
            await _service(request).get_owned_run(run_id, owner_id=_principal(request).principal_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return StreamingResponse(
            _event_stream(
                _service(request),
                run_id,
                last_event_id or 0,
                owner_id=_principal(request).principal_id,
            ),
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


def _principal(request: Request) -> Principal:
    authenticator: Authenticator = request.app.state.authenticator
    try:
        return authenticator.authenticate(request.headers.get("Authorization"))
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=401,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def _require_role(principal: Principal, role: str | None) -> None:
    if role is not None and not principal.has_role(role):
        raise HTTPException(status_code=403, detail=f"Role '{role}' is required")


async def _resume(
    request: Request,
    run_id: str,
    action: ApprovalAction,
    body: ApprovalRequestBody,
) -> RunRecord:
    try:
        principal = _principal(request)
        _require_role(principal, request.app.state.approval_role)
        actor = principal.principal_id if principal.authenticated else body.actor
        if actor is None:
            raise HTTPException(status_code=422, detail="actor is required without authentication")
        service = _service(request)
        waiting = await service.get_owned_run(run_id, owner_id=principal.principal_id)
        approval_request = waiting.approval.get("request", {}) if waiting.approval else {}
        approval_id = str(approval_request.get("approval_id", "approval"))
        await service.store.append_event(
            run_id,
            "audit.approval_authorized",
            data={
                "principal_id": principal.principal_id,
                "roles": principal.roles,
                "action": action,
            },
            idempotency_key=f"audit.approval:{approval_id}",
        )
        return await service.resume(
            run_id,
            action=action,
            actor=actor,
            reason=body.reason,
            owner_id=principal.principal_id,
        )
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RunConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


async def _event_stream(
    service: RunService, run_id: str, after: int, *, owner_id: str
) -> AsyncIterator[str]:
    cursor = after
    revision = service.store.revision
    while True:
        events = await service.store.list_events(run_id, after=cursor)
        for event in events:
            cursor = event.sequence
            yield _format_sse(event)
        record = await service.get_owned_run(run_id, owner_id=owner_id)
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
