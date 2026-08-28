"""Lifecycle helpers for durable LangGraph checkpointers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver


@contextmanager
def open_sqlite_checkpointer(path: Path) -> Iterator[SqliteSaver]:
    """Open and initialize a local durable checkpointer for one application process."""

    resolved = path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(resolved)) as checkpointer:
        checkpointer.setup()
        yield checkpointer
