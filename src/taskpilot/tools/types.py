"""Typed inputs and results for repository capabilities."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class ToolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RepositoryToolPolicy(ToolModel):
    allowed_roots: tuple[Path, ...]
    allow_writes: bool = False
    allow_commands: bool = False
    max_file_bytes: int = Field(default=262_144, ge=1)
    max_list_entries: int = Field(default=5_000, ge=1)
    max_search_matches: int = Field(default=500, ge=1)
    command_timeout_seconds: float = Field(default=120, gt=0, le=3_600)
    max_command_output_bytes: int = Field(default=1_048_576, ge=1)
    allowed_commands: tuple[tuple[str, ...], ...] = ()
    ignored_directories: tuple[str, ...] = (
        ".git",
        ".taskpilot",
        ".venv",
        "node_modules",
        "dist",
        "build",
        "__pycache__",
    )


class FileEntry(ToolModel):
    path: str
    size_bytes: int = Field(ge=0)


class FileContent(ToolModel):
    path: str
    content: str
    size_bytes: int = Field(ge=0)
    sha256: str


class SearchMatch(ToolModel):
    path: str
    line: int = Field(ge=1)
    text: str


class WriteResult(ToolModel):
    path: str
    created: bool
    previous_sha256: str | None
    sha256: str
    size_bytes: int = Field(ge=0)


class CommandResult(ToolModel):
    command: tuple[str, ...]
    exit_code: int | None
    output: str
    duration_ms: int = Field(ge=0)
    timed_out: bool = False
    output_truncated: bool = False
