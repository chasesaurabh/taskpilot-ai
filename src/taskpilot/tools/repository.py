"""Safe repository operations without a general-purpose shell."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

from taskpilot.tools.errors import (
    CapabilityDeniedError,
    CommandDeniedError,
    FileConflictError,
    FileLimitError,
    RepositoryBoundaryError,
    RepositoryToolError,
)
from taskpilot.tools.types import (
    CommandResult,
    FileContent,
    FileEntry,
    RepositoryToolPolicy,
    SearchMatch,
    WriteResult,
)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class RepositoryWorkspace:
    """A capability-scoped view of one repository inside configured roots."""

    def __init__(self, root: Path, policy: RepositoryToolPolicy) -> None:
        if not policy.allowed_roots:
            raise RepositoryBoundaryError("At least one allowed repository root is required")
        resolved_root = root.resolve(strict=True)
        if not resolved_root.is_dir():
            raise RepositoryBoundaryError(f"Repository is not a directory: {root}")
        allowed_roots = tuple(path.resolve(strict=True) for path in policy.allowed_roots)
        if not any(resolved_root.is_relative_to(allowed) for allowed in allowed_roots):
            raise RepositoryBoundaryError("Repository is outside the configured allowed roots")
        self._root = resolved_root
        self._policy = policy

    @property
    def root(self) -> Path:
        return self._root

    def _resolve(self, relative_path: str, *, must_exist: bool = True) -> Path:
        if not relative_path or "\x00" in relative_path:
            raise RepositoryBoundaryError("A non-empty relative path is required")
        candidate_input = Path(relative_path)
        if candidate_input.is_absolute() or candidate_input.drive:
            raise RepositoryBoundaryError("Absolute paths are not allowed")
        try:
            candidate = (self._root / candidate_input).resolve(strict=must_exist)
        except (FileNotFoundError, OSError) as exc:
            raise RepositoryToolError(f"Repository path is unavailable: {relative_path}") from exc
        if not candidate.is_relative_to(self._root):
            raise RepositoryBoundaryError("Path escapes the repository root")
        return candidate

    def _relative(self, path: Path) -> str:
        return path.relative_to(self._root).as_posix()

    def list_files(self) -> tuple[FileEntry, ...]:
        """List regular files without descending into known generated directories."""

        entries: list[FileEntry] = []
        ignored = set(self._policy.ignored_directories)
        for directory, directory_names, file_names in os.walk(self._root, followlinks=False):
            directory_names[:] = [name for name in directory_names if name not in ignored]
            base = Path(directory)
            for name in sorted(file_names):
                path = base / name
                if path.is_symlink() or not path.is_file():
                    continue
                entries.append(FileEntry(path=self._relative(path), size_bytes=path.stat().st_size))
                if len(entries) >= self._policy.max_list_entries:
                    return tuple(entries)
        return tuple(sorted(entries, key=lambda entry: entry.path))

    def read_file(self, relative_path: str) -> FileContent:
        """Read one UTF-8 text file within the configured byte budget."""

        path = self._resolve(relative_path)
        if not path.is_file():
            raise RepositoryToolError(f"Repository path is not a file: {relative_path}")
        size = path.stat().st_size
        if size > self._policy.max_file_bytes:
            raise FileLimitError(f"File exceeds {self._policy.max_file_bytes} byte limit")
        content = path.read_bytes()
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RepositoryToolError(f"File is not UTF-8 text: {relative_path}") from exc
        return FileContent(
            path=self._relative(path),
            content=text,
            size_bytes=len(content),
            sha256=_sha256(content),
        )

    def search_code(
        self,
        query: str,
        *,
        use_regex: bool = False,
        case_sensitive: bool = False,
    ) -> tuple[SearchMatch, ...]:
        """Search bounded UTF-8 files; binary and oversized files are skipped."""

        if not query:
            raise RepositoryToolError("Search query cannot be empty")
        flags = 0 if case_sensitive else re.IGNORECASE
        expression = query if use_regex else re.escape(query)
        try:
            pattern = re.compile(expression, flags)
        except re.error as exc:
            raise RepositoryToolError(f"Invalid search expression: {exc}") from exc

        matches: list[SearchMatch] = []
        for entry in self.list_files():
            if entry.size_bytes > self._policy.max_file_bytes:
                continue
            try:
                file_content = self.read_file(entry.path)
            except RepositoryToolError:
                continue
            for line_number, line in enumerate(file_content.content.splitlines(), start=1):
                if pattern.search(line):
                    matches.append(SearchMatch(path=entry.path, line=line_number, text=line))
                    if len(matches) >= self._policy.max_search_matches:
                        return tuple(matches)
        return tuple(matches)

    def write_file(
        self,
        relative_path: str,
        content: str,
        *,
        expected_sha256: str | None = None,
    ) -> WriteResult:
        """Atomically create or replace a file with an optional hash precondition."""

        if not self._policy.allow_writes:
            raise CapabilityDeniedError("Repository writes are disabled")
        encoded = content.encode("utf-8")
        if len(encoded) > self._policy.max_file_bytes:
            raise FileLimitError(f"Write exceeds {self._policy.max_file_bytes} byte limit")
        path = self._resolve(relative_path, must_exist=False)
        parent = path.parent
        if not parent.exists() or not parent.is_dir():
            raise RepositoryToolError("Parent directory must already exist")
        if path.exists() and (path.is_symlink() or not path.is_file()):
            raise RepositoryBoundaryError("Write target must be a regular file")

        created = not path.exists()
        previous = path.read_bytes() if path.exists() else None
        previous_hash = _sha256(previous) if previous is not None else None
        if expected_sha256 != previous_hash:
            raise FileConflictError("File changed since the proposed update was created")

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=parent, delete=False) as temporary:
                temporary.write(encoded)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

        return WriteResult(
            path=self._relative(path),
            created=created,
            previous_sha256=previous_hash,
            sha256=_sha256(encoded),
            size_bytes=len(encoded),
        )

    def git_status(self) -> CommandResult:
        """Inspect concise Git status through a fixed, read-only command."""

        return self._execute(("git", "status", "--short"), require_allowlist=False)

    def git_diff(self) -> CommandResult:
        """Inspect the current unstaged diff through a fixed, read-only command."""

        return self._execute(("git", "diff", "--no-ext-diff", "--"), require_allowlist=False)

    def execute(self, command: Sequence[str]) -> CommandResult:
        """Run a configured command argument vector without invoking a shell."""

        if not self._policy.allow_commands:
            raise CapabilityDeniedError("Repository command execution is disabled")
        return self._execute(tuple(command), require_allowlist=True)

    def _execute(self, command: tuple[str, ...], *, require_allowlist: bool) -> CommandResult:
        if not command or any(not argument or "\x00" in argument for argument in command):
            raise CommandDeniedError("Command arguments must be non-empty")
        executable_name = command[0]
        if Path(executable_name).name != executable_name:
            raise CommandDeniedError("Executable paths are not accepted")
        if require_allowlist and not any(
            command[: len(prefix)] == prefix for prefix in self._policy.allowed_commands
        ):
            raise CommandDeniedError("Command does not match an allowed argument prefix")

        executable = shutil.which(executable_name)
        if executable is None:
            raise RepositoryToolError(f"Executable was not found: {executable_name}")
        safe_environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {"PATH", "PATHEXT", "SYSTEMROOT", "TEMP", "TMP", "WINDIR"}
        }
        started = time.monotonic()
        timed_out = False
        output_truncated = False
        with tempfile.TemporaryFile() as output_file:
            process = subprocess.Popen(
                (executable, *command[1:]),
                cwd=self._root,
                env=safe_environment,
                stdin=subprocess.DEVNULL,
                stdout=output_file,
                stderr=subprocess.STDOUT,
                shell=False,
            )
            deadline = started + self._policy.command_timeout_seconds
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    timed_out = True
                    process.kill()
                    break
                if os.fstat(output_file.fileno()).st_size > self._policy.max_command_output_bytes:
                    output_truncated = True
                    process.kill()
                    break
                time.sleep(0.02)
            process.wait()
            output_file.seek(0)
            output_bytes = output_file.read(self._policy.max_command_output_bytes)
            if output_file.read(1):
                output_truncated = True

        duration_ms = round((time.monotonic() - started) * 1_000)
        output = output_bytes.decode("utf-8", errors="replace")
        return CommandResult(
            command=command,
            exit_code=None if timed_out else process.returncode,
            output=output,
            duration_ms=duration_ms,
            timed_out=timed_out,
            output_truncated=output_truncated,
        )
