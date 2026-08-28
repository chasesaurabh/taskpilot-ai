"""Lifecycle helpers for durable LangGraph checkpointers."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

import aiosqlite
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from taskpilot.domain import models as domain_models


@contextmanager
def open_sqlite_checkpointer(path: Path) -> Iterator[SqliteSaver]:
    """Open and initialize a local durable checkpointer for one application process."""

    resolved = path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(resolved)) as checkpointer:
        checkpointer.setup()
        yield checkpointer


@asynccontextmanager
async def open_async_checkpointer(url: str) -> AsyncIterator[object]:
    """Open the async SQLite or PostgreSQL checkpointer selected by configuration."""

    if url.startswith(("postgres://", "postgresql://")):
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        except ImportError as exc:  # pragma: no cover - depends on optional install
            raise RuntimeError("Install taskpilot-ai[postgres] for PostgreSQL checkpoints") from exc
        async with AsyncPostgresSaver.from_conn_string(
            url,
            serde=_checkpoint_serializer(),
        ) as postgres_checkpointer:
            await postgres_checkpointer.setup()
            yield postgres_checkpointer
        return

    path = Path(url.removeprefix("sqlite+aiosqlite:///").removeprefix("sqlite:///"))
    resolved = path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    connection = await aiosqlite.connect(str(resolved))
    sqlite_checkpointer = AsyncSqliteSaver(connection, serde=_checkpoint_serializer())
    try:
        await sqlite_checkpointer.setup()
        yield sqlite_checkpointer
    finally:
        await connection.close()


def _checkpoint_serializer() -> JsonPlusSerializer:
    allowed = tuple(
        (value.__module__, value.__name__)
        for value in vars(domain_models).values()
        if isinstance(value, type) and value.__module__ == domain_models.__name__
    )
    return JsonPlusSerializer(allowed_msgpack_modules=allowed)
