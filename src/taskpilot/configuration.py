"""Central application and policy configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from taskpilot.domain.models import WorkflowPolicy
from taskpilot.models.config import (
    ModelConfig,
    ModelProfile,
    ModelRole,
    ModelRoutingPolicy,
    RoutingRule,
)
from taskpilot.tools.types import RepositoryToolPolicy


class AppSettings(BaseSettings):
    """Process settings sourced from `TASKPILOT_*` environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="TASKPILOT_",
        env_file=".env",
        extra="ignore",
    )

    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65_535)
    database_url: str = "sqlite+aiosqlite:///./.taskpilot/taskpilot.db"
    checkpoint_url: str = ".taskpilot/checkpoints.db"
    allowed_repository_roots: str | None = None
    policy_file: Path = Path("config.example.yaml")
    log_level: str = "INFO"
    langsmith_enabled: bool = False
    demo_mode: bool = True

    @property
    def repository_roots(self) -> tuple[Path, ...]:
        if self.allowed_repository_roots is None:
            return ()
        roots = tuple(
            Path(value.strip()).resolve()
            for value in self.allowed_repository_roots.split(",")
            if value.strip()
        )
        if not roots:
            raise ValueError("At least one allowed repository root must be configured")
        return roots


class RepositoryPolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed_roots: tuple[Path, ...] = ()
    max_file_bytes: int = Field(default=262_144, ge=1)
    max_context_bytes: int = Field(default=1_048_576, ge=1)
    allow_writes: bool = True
    allow_commands: bool = True
    command_timeout_seconds: float = Field(default=120, gt=0, le=3_600)
    max_command_output_bytes: int = Field(default=1_048_576, ge=1)
    allowed_commands: tuple[tuple[str, ...], ...] = ()
    validation_commands: tuple[tuple[str, ...], ...] = ()

    @model_validator(mode="after")
    def validate_default_commands(self) -> RepositoryPolicyConfig:
        if self.validation_commands and not self.allow_commands:
            raise ValueError("validation_commands require repository command execution")
        for prefix in self.allowed_commands:
            if not prefix or any(not argument or "\x00" in argument for argument in prefix):
                raise ValueError("allowed_commands must contain non-empty argument prefixes")
        for command in self.validation_commands:
            if not command or any(not argument or "\x00" in argument for argument in command):
                raise ValueError("validation_commands must contain non-empty arguments")
            if not any(command[: len(prefix)] == prefix for prefix in self.allowed_commands):
                raise ValueError(
                    "Each validation command must match an allowed_commands argument prefix"
                )
        return self


class ObservabilityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    langsmith_enabled: bool = False
    log_level: str = "INFO"


class PolicyConfig(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    models: dict[str, ModelConfig]
    assignments: dict[ModelRole, str] = Field(default_factory=dict)
    routing_rules: tuple[RoutingRule, ...] = ()
    model_profiles: dict[str, ModelProfile] = Field(default_factory=dict)
    default_model_profile: str = Field(default="default", min_length=1)
    repository: RepositoryPolicyConfig
    workflow: WorkflowPolicy = WorkflowPolicy()
    observability: ObservabilityConfig = ObservabilityConfig()


def load_policy(path: Path) -> PolicyConfig:
    """Load the human-readable policy file without evaluating arbitrary YAML tags."""

    with path.resolve().open(encoding="utf-8") as stream:
        raw = yaml.safe_load(stream) or {}
    if not isinstance(raw, dict):
        raise ValueError("The policy file must contain a YAML mapping")
    normalized = _normalize_policy(raw)
    return PolicyConfig.model_validate(normalized)


def repository_policy(settings: AppSettings, policy: PolicyConfig) -> RepositoryToolPolicy:
    configured = tuple(path.resolve() for path in policy.repository.allowed_roots)
    allowed_roots = settings.repository_roots or configured
    if not allowed_roots:
        raise ValueError("At least one allowed repository root must be configured")
    return RepositoryToolPolicy(
        allowed_roots=allowed_roots,
        allow_writes=policy.repository.allow_writes,
        allow_commands=policy.repository.allow_commands,
        max_file_bytes=policy.repository.max_file_bytes,
        command_timeout_seconds=policy.repository.command_timeout_seconds,
        max_command_output_bytes=policy.repository.max_command_output_bytes,
        allowed_commands=policy.repository.allowed_commands,
    )


def model_policy(policy: PolicyConfig, *, demo_mode: bool) -> ModelRoutingPolicy:
    if demo_mode:
        demo = ModelConfig(provider="demo", model="deterministic-pagination-v1", local=True)
        return ModelRoutingPolicy(
            models={"demo": demo},
            profiles={"default": ModelProfile(assignments={role: "demo" for role in ModelRole})},
        )
    assignments = policy.assignments or _default_assignments(policy.models)
    profiles = policy.model_profiles or {
        policy.default_model_profile: ModelProfile(
            assignments=assignments,
            rules=policy.routing_rules,
        )
    }
    return ModelRoutingPolicy(
        models=policy.models,
        profiles=profiles,
        default_profile=policy.default_model_profile,
    )


def _default_assignments(models: dict[str, ModelConfig]) -> dict[ModelRole, str]:
    default = "default" if "default" in models else next(iter(models))
    preferred = {
        ModelRole.PLANNER: "planner",
        ModelRole.ARCHITECT: "planner",
        ModelRole.CODER: "coder",
        ModelRole.REVIEWER: "reviewer",
    }
    return {
        role: preferred.get(role, default) if preferred.get(role, default) in models else default
        for role in ModelRole
    }


def _normalize_policy(raw: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(raw)
    routing = normalized.pop("routing", {})
    if isinstance(routing, dict):
        normalized.setdefault("assignments", routing.get("assignments", {}))
        normalized.setdefault("routing_rules", routing.get("rules", ()))
        normalized.setdefault("model_profiles", routing.get("profiles", {}))
        normalized.setdefault("default_model_profile", routing.get("default_profile", "default"))
    return normalized
