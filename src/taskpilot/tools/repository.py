"""Safe repository operations without a general-purpose shell."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from taskpilot.tools.errors import (
    CapabilityDeniedError,
    CommandDeniedError,
    FileConflictError,
    FileLimitError,
    OperationUncertainError,
    RepositoryBoundaryError,
    RepositoryToolError,
)
from taskpilot.tools.types import (
    CommandResult,
    FileContent,
    FileEntry,
    RepositoryToolPolicy,
    SearchMatch,
    WriteRequest,
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

    def select_files(
        self,
        query: str,
        *,
        max_files: int,
        max_bytes: int,
    ) -> tuple[FileEntry, ...]:
        """Rank repository files by deterministic lexical relevance within a byte budget."""

        stop_words = {
            "about",
            "after",
            "before",
            "change",
            "from",
            "into",
            "repository",
            "should",
            "task",
            "that",
            "the",
            "this",
            "with",
        }
        terms = tuple(
            dict.fromkeys(
                token
                for token in re.findall(r"[a-zA-Z0-9_.-]+", query.lower())
                if len(token) >= 3 and token not in stop_words
            )
        )
        ranked: list[tuple[int, FileEntry]] = []
        for entry in self.list_files():
            path_text = entry.path.lower()
            score = sum(12 for term in terms if term in path_text)
            if Path(entry.path).name.lower() in {"readme.md", "pyproject.toml", "package.json"}:
                score += 1
            ranked.append((score, entry))
        ranked.sort(key=lambda item: (-item[0], item[1].path))

        scan_budget = max(max_bytes * 4, self._policy.max_file_bytes)
        scanned = 0
        rescored: list[tuple[int, FileEntry]] = []
        for score, entry in ranked:
            if (
                entry.size_bytes <= self._policy.max_file_bytes
                and scanned + entry.size_bytes <= scan_budget
                and terms
            ):
                try:
                    content = self.read_file(entry.path).content.lower()
                except RepositoryToolError:
                    content = ""
                scanned += entry.size_bytes
                score += sum(min(content.count(term), 8) for term in terms)
            rescored.append((score, entry))
        rescored.sort(key=lambda item: (-item[0], item[1].path))

        selected: list[FileEntry] = []
        consumed = 0
        for _, entry in rescored:
            if len(selected) >= max_files:
                break
            if consumed + entry.size_bytes > max_bytes:
                continue
            selected.append(entry)
            consumed += entry.size_bytes
        return tuple(selected)

    def write_file(
        self,
        relative_path: str,
        content: str,
        *,
        expected_sha256: str | None = None,
    ) -> WriteResult:
        """Atomically create or replace a file with an optional hash precondition."""

        return self.write_files(
            (WriteRequest(path=relative_path, content=content, expected_sha256=expected_sha256),)
        )[0]

    def write_files(
        self,
        requests: Sequence[WriteRequest],
        *,
        operation_id: str | None = None,
    ) -> tuple[WriteResult, ...]:
        """Apply a prevalidated batch with rollback and retry-safe desired-content detection."""

        if not self._policy.allow_writes:
            raise CapabilityDeniedError("Repository writes are disabled")
        if not requests:
            return ()
        operation_spec = [
            {
                "path": request.path,
                "expected_sha256": request.expected_sha256,
                "desired_sha256": _sha256(request.content.encode("utf-8")),
            }
            for request in requests
        ]
        if operation_id is not None:
            completed = self._completed_write(operation_id, operation_spec)
            if completed is not None:
                return completed

        prepared: list[tuple[WriteRequest, Path, bytes, bytes | None, str | None, str]] = []
        seen: set[Path] = set()
        for request in requests:
            encoded = request.content.encode("utf-8")
            if len(encoded) > self._policy.max_file_bytes:
                raise FileLimitError(f"Write exceeds {self._policy.max_file_bytes} byte limit")
            path = self._resolve(request.path, must_exist=False)
            if path in seen:
                raise RepositoryToolError(f"Write batch repeats repository path: {request.path}")
            seen.add(path)
            if not path.parent.exists() or not path.parent.is_dir():
                raise RepositoryToolError("Parent directory must already exist")
            if path.exists() and (path.is_symlink() or not path.is_file()):
                raise RepositoryBoundaryError("Write target must be a regular file")
            previous = path.read_bytes() if path.exists() else None
            previous_hash = _sha256(previous) if previous is not None else None
            desired_hash = _sha256(encoded)
            if previous_hash != desired_hash and request.expected_sha256 != previous_hash:
                raise FileConflictError("File changed since the proposed update was created")
            prepared.append((request, path, encoded, previous, previous_hash, desired_hash))

        if operation_id is not None:
            started = {
                "kind": "write",
                "status": "started",
                "spec": operation_spec,
            }
            if not self._create_operation(operation_id, started):
                completed = self._completed_write(operation_id, operation_spec)
                if completed is not None:
                    return completed
                raise OperationUncertainError(
                    "A prior write attempt may be active or incomplete; "
                    "operator recovery is required"
                )

        staged: dict[Path, Path] = {}
        backups: dict[Path, Path] = {}
        applied: list[Path] = []
        try:
            for _, path, encoded, previous, previous_hash, desired_hash in prepared:
                if previous_hash == desired_hash:
                    continue
                with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
                    temporary.write(encoded)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                    staged[path] = Path(temporary.name)
                if previous is not None:
                    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as backup:
                        backup.write(previous)
                        backup.flush()
                        os.fsync(backup.fileno())
                        backups[path] = Path(backup.name)
            for path, staged_path in staged.items():
                os.replace(staged_path, path)
                applied.append(path)
        except Exception:
            rollback_errors: list[OSError] = []
            for path in reversed(applied):
                try:
                    backup_path = backups.get(path)
                    if backup_path is None:
                        path.unlink(missing_ok=True)
                    else:
                        os.replace(backup_path, path)
                except OSError as rollback_error:
                    rollback_errors.append(rollback_error)
            if rollback_errors:
                raise RepositoryToolError(
                    "Write batch failed and rollback was incomplete"
                ) from rollback_errors[0]
            raise
        finally:
            for temporary_path in (*staged.values(), *backups.values()):
                temporary_path.unlink(missing_ok=True)

        results = tuple(
            WriteResult(
                path=self._relative(path),
                created=previous is None,
                previous_sha256=previous_hash,
                sha256=desired_hash,
                size_bytes=len(encoded),
            )
            for _, path, encoded, previous, previous_hash, desired_hash in prepared
        )
        if operation_id is not None:
            self._store_operation(
                operation_id,
                {
                    "kind": "write",
                    "status": "completed",
                    "spec": operation_spec,
                    "results": [result.model_dump(mode="json") for result in results],
                },
            )
        return results

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

    def execute_once(self, command: Sequence[str], *, operation_id: str) -> CommandResult:
        """Return a completed command result once, and refuse an uncertain duplicate."""

        previous = self._load_operation(operation_id)
        normalized = tuple(command)
        if previous is not None:
            if (
                previous.get("kind") != "command"
                or tuple(previous.get("command", ())) != normalized
            ):
                raise RepositoryToolError("Operation ID was reused for a different command")
            if previous.get("status") == "completed":
                return CommandResult.model_validate(previous["result"])
            raise OperationUncertainError(
                "A prior command attempt may have completed; explicit operator recovery is required"
            )
        started = {"kind": "command", "status": "started", "command": normalized}
        if not self._create_operation(operation_id, started):
            return self.execute_once(normalized, operation_id=operation_id)
        result = self._execute(normalized, require_allowlist=True)
        self._store_operation(
            operation_id,
            {
                "kind": "command",
                "status": "completed",
                "command": normalized,
                "result": result.model_dump(mode="json"),
            },
        )
        return result

    def _completed_write(
        self,
        operation_id: str,
        operation_spec: list[dict[str, str | None]],
    ) -> tuple[WriteResult, ...] | None:
        previous = self._load_operation(operation_id)
        if previous is None:
            return None
        if previous.get("kind") != "write":
            raise RepositoryToolError("Operation ID was reused for a different operation")
        if previous.get("spec") != operation_spec:
            raise RepositoryToolError("Operation ID was reused for different write content")
        if previous.get("status") != "completed":
            raise OperationUncertainError(
                "A prior write attempt may be active or incomplete; operator recovery is required"
            )
        results = tuple(WriteResult.model_validate(item) for item in previous.get("results", ()))
        for result in results:
            path = self._resolve(result.path, must_exist=False)
            if not path.is_file() or _sha256(path.read_bytes()) != result.sha256:
                raise FileConflictError(
                    "Completed write operation no longer matches the repository"
                )
        return results

    def _operation_path(self, operation_id: str) -> Path | None:
        root = self._policy.operation_root
        if root is None:
            return None
        repository_key = hashlib.sha256(str(self._root).encode()).hexdigest()
        operation_key = hashlib.sha256(operation_id.encode()).hexdigest()
        directory = root.resolve() / repository_key
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{operation_key}.json"

    def _load_operation(self, operation_id: str) -> dict[str, Any] | None:
        path = self._operation_path(operation_id)
        if path is None or not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise OperationUncertainError(
                "Operation record is incomplete; operator recovery is required"
            ) from exc
        if not isinstance(payload, dict):
            raise RepositoryToolError("Operation record is invalid")
        return payload

    def _store_operation(self, operation_id: str, payload: dict[str, Any]) -> None:
        path = self._operation_path(operation_id)
        if path is None:
            return
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
                temporary.write(json.dumps(payload, separators=(",", ":")).encode())
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _create_operation(self, operation_id: str, payload: dict[str, Any]) -> bool:
        path = self._operation_path(operation_id)
        if path is None:
            return True
        try:
            with path.open("x", encoding="utf-8") as stream:
                json.dump(payload, stream, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            return False
        return True

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

        containerized = require_allowlist and self._policy.execution_backend == "container"
        host_executable = self._policy.container_runtime if containerized else executable_name
        executable = shutil.which(host_executable)
        if executable is None:
            raise RepositoryToolError(f"Executable was not found: {host_executable}")
        safe_environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {"PATH", "PATHEXT", "SYSTEMROOT", "TEMP", "TMP", "WINDIR"}
        }
        started = time.monotonic()
        timed_out = False
        output_truncated = False
        with tempfile.TemporaryFile() as output_file:
            process_arguments = (
                self._container_arguments(executable, command)
                if containerized
                else (executable, *command[1:])
            )
            process = subprocess.Popen(
                process_arguments,
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

    def _container_arguments(self, runtime: str, command: tuple[str, ...]) -> tuple[str, ...]:
        image = self._policy.container_image
        if image is None:
            raise RepositoryToolError("Container execution requires a configured image")
        return (
            runtime,
            "run",
            "--rm",
            "--network",
            "none",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "256",
            "--memory",
            self._policy.container_memory,
            "--cpus",
            str(self._policy.container_cpus),
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=256m",
            "--workdir",
            "/workspace",
            "--mount",
            f"type=bind,source={self._root},target=/workspace",
            image,
            *command,
        )
