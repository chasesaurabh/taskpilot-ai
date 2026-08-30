"""Configuration models for providers and explicit responsibility routing."""

from __future__ import annotations

import re
from enum import StrEnum
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")


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
    max_tokens: int | None = Field(default=None, ge=1)
    organization_env: str | None = None
    headers_from_env: dict[str, str] = Field(default_factory=dict)
    extra_body: dict[str, JsonValue] = Field(default_factory=dict)
    supports_structured_output: bool = True
    local: bool = False

    @field_validator("api_key_env", "organization_env")
    @classmethod
    def validate_environment_name(cls, value: str | None) -> str | None:
        if value is not None and not _ENVIRONMENT_NAME.fullmatch(value):
            raise ValueError(f"Invalid environment variable name: {value}")
        return value

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is not None:
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("base_url must be an absolute HTTP(S) URL")
        return value

    @field_validator("headers_from_env")
    @classmethod
    def validate_header_environment_map(cls, value: dict[str, str]) -> dict[str, str]:
        for header, environment_name in value.items():
            if not _HEADER_NAME.fullmatch(header):
                raise ValueError(f"Invalid HTTP header name: {header}")
            if not _ENVIRONMENT_NAME.fullmatch(environment_name):
                raise ValueError(f"Invalid environment variable name: {environment_name}")
        return value

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
    profile: str | None = None


class ModelProfile(ConfigModel):
    assignments: dict[ModelRole, str]
    rules: tuple[RoutingRule, ...] = ()


class ModelRoutingPolicy(ConfigModel):
    models: dict[str, ModelConfig]
    profiles: dict[str, ModelProfile]
    default_profile: str = Field(default="default", min_length=1)

    @model_validator(mode="after")
    def validate_references(self) -> ModelRoutingPolicy:
        if self.default_profile not in self.profiles:
            raise ValueError(f"Unknown default model profile: {self.default_profile}")
        references = {
            model_key
            for profile in self.profiles.values()
            for model_key in profile.assignments.values()
        } | {rule.model_key for profile in self.profiles.values() for rule in profile.rules}
        missing = references - self.models.keys()
        if missing:
            raise ValueError(f"Unknown routed model keys: {', '.join(sorted(missing))}")
        return self

    @property
    def referenced_models(self) -> dict[str, ModelConfig]:
        keys = {
            model_key
            for profile in self.profiles.values()
            for model_key in profile.assignments.values()
        } | {rule.model_key for profile in self.profiles.values() for rule in profile.rules}
        return {key: self.models[key] for key in sorted(keys)}
