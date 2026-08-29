"""Configuration models for providers and explicit responsibility routing."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelRole(StrEnum):
    ANALYST = "analyst"
    PLANNER = "planner"
    ARCHITECT = "architect"
    CODER = "coder"
    REVIEWER = "reviewer"
    REPORTER = "reporter"


class TaskComplexity(StrEnum):
    SIMPLE = "simple"
    STANDARD = "standard"
    COMPLEX = "complex"


class ModelConfig(ConfigModel):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    base_url: str | None = None
    api_key_env: str | None = None
    temperature: float = Field(default=0, ge=0, le=2)
    timeout_seconds: float = Field(default=120, gt=0, le=3_600)
    supports_structured_output: bool = True
    local: bool = False

    @model_validator(mode="after")
    def validate_compatible_endpoint(self) -> ModelConfig:
        if self.provider in {"openai-compatible", "local"} and not self.base_url:
            raise ValueError(f"provider '{self.provider}' requires base_url")
        return self


class RoutingRule(ConfigModel):
    name: str = Field(min_length=1)
    role: ModelRole
    model_key: str = Field(min_length=1)
    complexity: TaskComplexity | None = None
    privacy_required: bool | None = None
    max_repository_files: int | None = Field(default=None, ge=0)


class RoutingContext(ConfigModel):
    complexity: TaskComplexity = TaskComplexity.STANDARD
    privacy_required: bool = False
    repository_file_count: int = Field(default=0, ge=0)


class ModelRoutingPolicy(ConfigModel):
    models: dict[str, ModelConfig]
    assignments: dict[ModelRole, str]
    rules: tuple[RoutingRule, ...] = ()

    @model_validator(mode="after")
    def validate_references(self) -> ModelRoutingPolicy:
        references = set(self.assignments.values()) | {rule.model_key for rule in self.rules}
        missing = references - self.models.keys()
        if missing:
            raise ValueError(f"Unknown routed model keys: {', '.join(sorted(missing))}")
        return self
