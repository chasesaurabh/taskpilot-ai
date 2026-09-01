from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from taskpilot.tools.errors import (
    CapabilityDeniedError,
    CommandDeniedError,
    FileConflictError,
    FileLimitError,
    OperationUncertainError,
    RepositoryBoundaryError,
    RepositoryToolError,
)
from taskpilot.tools.repository import RepositoryWorkspace
from taskpilot.tools.types import RepositoryToolPolicy, WriteRequest


def _policy(root: Path, **overrides: object) -> RepositoryToolPolicy:
    return RepositoryToolPolicy(allowed_roots=(root,), **overrides)


def test_repository_must_be_inside_an_allowed_root(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    repository = tmp_path / "elsewhere" / "repo"
    allowed.mkdir()
    repository.mkdir(parents=True)

    with pytest.raises(RepositoryBoundaryError, match="outside"):
        RepositoryWorkspace(repository, _policy(allowed))


def test_read_list_and_search_are_bounded(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "app.py").write_text("def health():\n    return 'healthy'\n", encoding="utf-8")
    (repository / "large.txt").write_text("x" * 100, encoding="utf-8")
    (repository / ".git").mkdir()
    (repository / ".git" / "ignored").write_text("secret", encoding="utf-8")
    workspace = RepositoryWorkspace(repository, _policy(tmp_path, max_file_bytes=64))

    assert [entry.path for entry in workspace.list_files()] == ["app.py", "large.txt"]
    content = workspace.read_file("app.py")
    assert content.sha256 == hashlib.sha256(content.content.encode()).hexdigest()
    assert [(match.path, match.line) for match in workspace.search_code("HEALTH")] == [
        ("app.py", 1),
        ("app.py", 2),
    ]
    with pytest.raises(FileLimitError):
        workspace.read_file("large.txt")


def test_relevance_selection_prefers_task_terms_over_alphabetical_order(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "aaa.py").write_text("def unrelated(): pass\n", encoding="utf-8")
    (repository / "orders.py").write_text(
        "def paginate_customer_orders(): pass\n", encoding="utf-8"
    )
    (repository / "zzz.py").write_text("def other(): pass\n", encoding="utf-8")
    workspace = RepositoryWorkspace(repository, _policy(tmp_path))

    selected = workspace.select_files(
        "Add pagination to customer orders", max_files=1, max_bytes=10_000
    )

    assert [entry.path for entry in selected] == ["orders.py"]


def test_paths_cannot_escape_repository(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    workspace = RepositoryWorkspace(repository, _policy(tmp_path))

    with pytest.raises(RepositoryBoundaryError, match="escapes"):
        workspace.read_file("../outside.txt")
    with pytest.raises(RepositoryBoundaryError, match="Absolute"):
        workspace.read_file(str(outside.resolve()))


def test_write_requires_capability_and_matching_precondition(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    target = repository / "app.py"
    target.write_bytes(b"old\n")
    read_only = RepositoryWorkspace(repository, _policy(tmp_path))

    with pytest.raises(CapabilityDeniedError):
        read_only.write_file("app.py", "new\n")

    writable = RepositoryWorkspace(repository, _policy(tmp_path, allow_writes=True))
    with pytest.raises(FileConflictError):
        writable.write_file("app.py", "new\n", expected_sha256="stale")

    previous_hash = hashlib.sha256(b"old\n").hexdigest()
    result = writable.write_file("app.py", "new\n", expected_sha256=previous_hash)

    assert result.previous_sha256 == previous_hash
    assert target.read_text(encoding="utf-8") == "new\n"


def test_new_file_requires_explicit_absence_precondition(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    workspace = RepositoryWorkspace(repository, _policy(tmp_path, allow_writes=True))

    result = workspace.write_file("new.py", "value = 1\n", expected_sha256=None)

    assert result.created is True
    with pytest.raises(FileConflictError):
        workspace.write_file("new.py", "value = 2\n", expected_sha256=None)


def test_commands_require_capability_and_argument_prefix(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    disabled = RepositoryWorkspace(
        repository,
        _policy(tmp_path, allowed_commands=(("git", "--version"),)),
    )
    with pytest.raises(CapabilityDeniedError):
        disabled.execute(("git", "--version"))

    enabled = RepositoryWorkspace(
        repository,
        _policy(
            tmp_path,
            allow_commands=True,
            allowed_commands=(("git", "--version"),),
        ),
    )
    with pytest.raises(CommandDeniedError):
        enabled.execute(("git", "status"))
    with pytest.raises(CommandDeniedError, match="paths"):
        enabled.execute((str(Path(subprocess.__file__)),))

    result = enabled.execute(("git", "--version"))
    assert result.exit_code == 0
    assert result.output.startswith("git version")


def test_fixed_git_inspection_does_not_require_execute_capability(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(("git", "init", "--quiet"), cwd=repository, check=True)
    (repository / "new.txt").write_text("new", encoding="utf-8")
    workspace = RepositoryWorkspace(repository, _policy(tmp_path))

    result = workspace.git_status()

    assert result.exit_code == 0
    assert "?? new.txt" in result.output


def test_command_timeout_and_output_limit_are_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    executable_name = Path(sys.executable).name
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent))
    workspace = RepositoryWorkspace(
        repository,
        _policy(
            tmp_path,
            allow_commands=True,
            allowed_commands=((executable_name, "-c"),),
            command_timeout_seconds=0.1,
            max_command_output_bytes=128,
        ),
    )

    oversized = workspace.execute((executable_name, "-c", "print('x' * 10000)"))
    timed_out = workspace.execute(
        (executable_name, "-c", "import time; time.sleep(1)"),
    )

    assert oversized.output_truncated is True
    assert len(oversized.output.encode()) <= 128
    assert timed_out.timed_out is True
    assert timed_out.exit_code is None


def test_invalid_regex_is_reported_as_tool_error(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    workspace = RepositoryWorkspace(repository, _policy(tmp_path))

    with pytest.raises(RepositoryToolError, match="Invalid search expression"):
        workspace.search_code("(", use_regex=True)


def test_invalid_utf8_is_rejected_without_lossy_decoding(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "binary.dat").write_bytes(b"\xff\xfe\x00")
    workspace = RepositoryWorkspace(repository, _policy(tmp_path))

    with pytest.raises(RepositoryToolError, match="not UTF-8"):
        workspace.read_file("binary.dat")


def test_symlink_escape_is_rejected_when_platform_allows_symlinks(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    link = repository / "linked.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("creating symlinks is not permitted on this host")
    workspace = RepositoryWorkspace(repository, _policy(tmp_path))

    with pytest.raises(RepositoryBoundaryError, match="escapes"):
        workspace.read_file("linked.txt")
    assert "linked.txt" not in {entry.path for entry in workspace.list_files()}


def test_commands_do_not_receive_provider_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    script = repository / "inspect_env.py"
    script.write_text(
        "import os\nprint(os.getenv('OPENAI_API_KEY', 'missing'))\n",
        encoding="utf-8",
    )
    executable = Path(sys.executable).name
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-command")
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent))
    workspace = RepositoryWorkspace(
        repository,
        _policy(
            tmp_path,
            allow_commands=True,
            allowed_commands=((executable, "inspect_env.py"),),
        ),
    )

    result = workspace.execute((executable, "inspect_env.py"))

    assert result.exit_code == 0
    assert result.output.strip() == "missing"
    assert "must-not-reach-command" not in result.output


def test_container_backend_builds_a_networkless_least_privilege_worker(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    workspace = RepositoryWorkspace(
        repository,
        _policy(
            tmp_path,
            allow_commands=True,
            allowed_commands=(("pytest",),),
            execution_backend="container",
            container_image="python:3.12-slim",
        ),
    )

    arguments = workspace._container_arguments("docker", ("pytest", "-q"))

    assert arguments[:3] == ("docker", "run", "--rm")
    assert arguments[3:5] == ("--network", "none")
    assert "ALL" in arguments
    assert "no-new-privileges" in arguments
    assert f"type=bind,source={repository.resolve()},target=/workspace" in arguments
    assert arguments[-3:] == ("python:3.12-slim", "pytest", "-q")


def test_multi_file_write_rolls_back_if_commit_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    first = repository / "first.txt"
    second = repository / "second.txt"
    first.write_text("before-first", encoding="utf-8")
    second.write_text("before-second", encoding="utf-8")
    workspace = RepositoryWorkspace(repository, _policy(tmp_path, allow_writes=True))
    real_replace = os.replace
    calls = 0

    def fail_second_commit(source: str | Path, target: str | Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated commit failure")
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", fail_second_commit)

    with pytest.raises(OSError, match="simulated"):
        workspace.write_files(
            (
                WriteRequest(
                    path="first.txt",
                    content="after-first",
                    expected_sha256=hashlib.sha256(b"before-first").hexdigest(),
                ),
                WriteRequest(
                    path="second.txt",
                    content="after-second",
                    expected_sha256=hashlib.sha256(b"before-second").hexdigest(),
                ),
            )
        )

    assert first.read_text(encoding="utf-8") == "before-first"
    assert second.read_text(encoding="utf-8") == "before-second"


def test_write_operation_replays_completed_result_without_rewriting(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    target = repository / "value.txt"
    target.write_text("before", encoding="utf-8")
    workspace = RepositoryWorkspace(
        repository,
        _policy(tmp_path, allow_writes=True, operation_root=tmp_path / "operations"),
    )
    request = WriteRequest(
        path="value.txt",
        content="after",
        expected_sha256=hashlib.sha256(b"before").hexdigest(),
    )

    first = workspace.write_files((request,), operation_id="run:write:0")
    second = workspace.write_files((request,), operation_id="run:write:0")

    assert second == first
    assert target.read_text(encoding="utf-8") == "after"

    with pytest.raises(RepositoryToolError, match="different write content"):
        workspace.write_files(
            (
                WriteRequest(
                    path="value.txt",
                    content="unexpected",
                    expected_sha256=first[0].sha256,
                ),
            ),
            operation_id="run:write:0",
        )


def test_uncertain_command_is_not_repeated(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    workspace = RepositoryWorkspace(
        repository,
        _policy(
            tmp_path,
            allow_commands=True,
            allowed_commands=(("missing-taskpilot-command",),),
            operation_root=tmp_path / "operations",
        ),
    )

    with pytest.raises(RepositoryToolError, match="Executable was not found"):
        workspace.execute_once(("missing-taskpilot-command",), operation_id="run:command:0")
    with pytest.raises(OperationUncertainError, match="may have completed"):
        workspace.execute_once(("missing-taskpilot-command",), operation_id="run:command:0")
