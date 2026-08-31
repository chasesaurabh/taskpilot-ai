"""Packaged FastAPI composition root and executable entry point."""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
import uvicorn
from fastapi import FastAPI

from taskpilot.api.app import create_app
from taskpilot.application.runs import RunService
from taskpilot.artifacts import ArtifactStore, LocalArtifactStore, S3ArtifactStore
from taskpilot.auth import TokenAuthenticator
from taskpilot.configuration import AppSettings, load_policy, model_policy, repository_policy
from taskpilot.graph.builder import build_workflow
from taskpilot.models.demo import DeterministicModelFactory
from taskpilot.models.factory import LangChainModelFactory, ModelFactory
from taskpilot.models.gateway import ModelGateway
from taskpilot.models.routing import ModelRouter
from taskpilot.models.scenario import pagination_demo_model
from taskpilot.nodes.engineering import EngineeringNodes, EngineeringNodesConfig
from taskpilot.observability import configure_observability
from taskpilot.persistence.checkpoints import open_async_checkpointer
from taskpilot.persistence.protocols import ClosableRunStore
from taskpilot.persistence.runs import SqliteRunStore


def create_runtime_app(settings: AppSettings | None = None) -> FastAPI:
    resolved_settings = settings or AppSettings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        _ensure_runtime_bin_on_path()
        policy = load_policy(resolved_settings.policy_file)
        configure_observability(
            log_level=resolved_settings.log_level or policy.observability.log_level,
            langsmith_enabled=(
                resolved_settings.langsmith_enabled or policy.observability.langsmith_enabled
            ),
        )
        tools = repository_policy(resolved_settings, policy)
        if resolved_settings.demo_mode:
            demo_command = (Path(sys.executable).name, "-m", "pytest")
            tools = tools.model_copy(
                update={"allowed_commands": (*tools.allowed_commands, demo_command)}
            )
        routing = model_policy(policy, demo_mode=resolved_settings.demo_mode)
        factory: ModelFactory = (
            DeterministicModelFactory(pagination_demo_model())
            if resolved_settings.demo_mode
            else LangChainModelFactory()
        )
        router = ModelRouter(routing)
        gateway = ModelGateway(router, factory)
        gateway.validate_configuration()
        artifacts = _open_artifact_store(resolved_settings)
        nodes = EngineeringNodes(
            models=gateway,
            repository_policy=tools,
            config=EngineeringNodesConfig(
                max_context_bytes=policy.repository.max_context_bytes,
                default_validation_commands=policy.repository.validation_commands,
            ),
            artifact_store=artifacts,
        )
        store = await _open_store(resolved_settings.database_url)
        try:
            async with open_async_checkpointer(resolved_settings.checkpoint_url) as checkpointer:
                graph = build_workflow(nodes.as_workflow_nodes(), checkpointer=checkpointer)
                service = RunService(
                    graph=graph,
                    store=store,
                    repository_policy=tools,
                    model_profiles=router.profiles,
                    default_model_profile=router.default_profile,
                    artifacts=artifacts,
                )
                application.state.run_service = service
                structlog.get_logger(__name__).info(
                    "runtime_ready",
                    environment=resolved_settings.environment,
                    demo_mode=resolved_settings.demo_mode,
                    repository_roots=[str(root) for root in tools.allowed_roots],
                )
                yield
                await service.wait_for_background_tasks()
        finally:
            await store.close()

    return create_app(
        lifespan=lifespan,
        authenticator=TokenAuthenticator.from_json(resolved_settings.auth_tokens),
    )


def _ensure_runtime_bin_on_path() -> None:
    runtime_bin = str(Path(sys.executable).parent)
    current = os.environ.get("PATH", "")
    normalized_runtime = os.path.normcase(os.path.abspath(runtime_bin))
    normalized_entries = {
        os.path.normcase(os.path.abspath(entry)) for entry in current.split(os.pathsep) if entry
    }
    if normalized_runtime not in normalized_entries:
        os.environ["PATH"] = f"{runtime_bin}{os.pathsep}{current}"


async def _open_store(database_url: str) -> ClosableRunStore:
    if database_url.startswith(("postgres://", "postgresql://")):
        try:
            from taskpilot.persistence.postgres import PostgresRunStore
        except ImportError as exc:  # pragma: no cover - depends on optional install
            raise RuntimeError("Install taskpilot-ai[postgres] for PostgreSQL storage") from exc
        return await PostgresRunStore.open(database_url)
    raw_path = database_url.removeprefix("sqlite+aiosqlite:///").removeprefix("sqlite:///")
    return await SqliteRunStore.open(Path(raw_path))


def _open_artifact_store(settings: AppSettings) -> ArtifactStore:
    if settings.artifact_backend == "local":
        return LocalArtifactStore(settings.artifact_root)
    if settings.artifact_backend == "s3":
        if not settings.artifact_s3_bucket:
            raise ValueError("TASKPILOT_ARTIFACT_S3_BUCKET is required for S3 artifacts")
        options = {
            key: value
            for key, value in {
                "endpoint_url": settings.artifact_s3_endpoint_url,
                "region_name": settings.artifact_s3_region,
            }.items()
            if value is not None
        }
        return S3ArtifactStore(
            bucket=settings.artifact_s3_bucket,
            prefix=settings.artifact_s3_prefix,
            **options,
        )
    raise ValueError("TASKPILOT_ARTIFACT_BACKEND must be 'local' or 's3'")


app = create_runtime_app()


def main() -> None:
    settings = AppSettings()
    uvicorn.run("taskpilot.runtime:app", host=settings.host, port=settings.port, reload=False)
