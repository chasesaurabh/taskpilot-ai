"""Stable public HTTP request models."""

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateRunRequest(ApiModel):
    repository: str = Field(min_length=1)
    task: str = Field(min_length=1, max_length=20_000)
    max_repair_attempts: int = Field(default=2, ge=0, le=10)
    require_approval: bool = True
    require_write_approval: bool = False
    require_command_approval: bool = False
    model_profile: str | None = Field(default=None, min_length=1, max_length=100)


class ModelProfilesResponse(ApiModel):
    default_profile: str
    profiles: tuple[str, ...]


class ApprovalRequestBody(ApiModel):
    actor: str | None = Field(default=None, min_length=1, max_length=320)
    reason: str | None = Field(default=None, max_length=4_000)
