"""SQLite run projection and replayable event log."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite
from pydantic import BaseModel, ConfigDict, Field

from taskpilot.domain.models import FinalReport, RunStatus, WorkflowPolicy

TERMINAL_STATUSES = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.REJECTED}


class PersistenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)


class RunRecord(PersistenceModel):
    run_id: str
    owner_id: str = "local"
    task: str
    repository: str
    policy: WorkflowPolicy
    status: RunStatus
    created_at: datetime
    updated_at: datetime
    approval: dict[str, Any] | None = None
    final_report: FinalReport | None = None


class RunEvent(PersistenceModel):
    run_id: str
    sequence: int = Field(ge=1)
    event_type: str
    node: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class RunStoreError(RuntimeError):
    """Base error for run lifecycle persistence."""


class RunNotFoundError(RunStoreError):
    """The requested run does not exist."""


class RunConflictError(RunStoreError):
    """A run status transition lost a concurrency race."""


class SqliteRunStore:
    """One-connection local store with serialized writes and live notifications."""

    def __init__(self, connection: aiosqlite.Connection) -> None:
        self._connection = connection
        self._write_lock = asyncio.Lock()
        self._condition = asyncio.Condition()
        self._revision = 0

    @classmethod
    async def open(cls, path: Path) -> SqliteRunStore:
        resolved = path.resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        connection = await aiosqlite.connect(str(resolved))
        connection.row_factory = aiosqlite.Row
        store = cls(connection)
        await store.setup()
        return store

    async def setup(self) -> None:
        await self._connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL DEFAULT 'local',
                task TEXT NOT NULL,
                repository TEXT NOT NULL,
                policy_json TEXT NOT NULL,
                status TEXT NOT NULL,
                approval_json TEXT,
                final_report_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS run_events (
                run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                sequence INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                node TEXT,
                data_json TEXT NOT NULL,
                idempotency_key TEXT,
                created_at TEXT NOT NULL,
                PRIMARY KEY (run_id, sequence),
                UNIQUE (run_id, idempotency_key)
            );
            """
        )
        columns = await self._connection.execute_fetchall("PRAGMA table_info(runs)")
        if not any(row[1] == "owner_id" for row in columns):
            await self._connection.execute(
                "ALTER TABLE runs ADD COLUMN owner_id TEXT NOT NULL DEFAULT 'local'"
            )
        await self._connection.commit()

    async def close(self) -> None:
        await self._connection.close()

    async def create_run(
        self,
        *,
        run_id: str,
        task: str,
        repository: str,
        policy: WorkflowPolicy,
        owner_id: str = "local",
    ) -> RunRecord:
        now = datetime.now(UTC)
        async with self._write_lock:
            await self._connection.execute(
                """
                INSERT INTO runs (
                    run_id, owner_id, task, repository, policy_json, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    owner_id,
                    task,
                    repository,
                    policy.model_dump_json(),
                    RunStatus.QUEUED,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            await self._connection.commit()
        return await self.get_run(run_id)

    async def get_run(self, run_id: str) -> RunRecord:
        cursor = await self._connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            raise RunNotFoundError(f"Run not found: {run_id}")
        return _run_from_row(row)

    async def list_runs(self, *, owner_id: str, limit: int = 100) -> tuple[RunRecord, ...]:
        cursor = await self._connection.execute(
            "SELECT * FROM runs WHERE owner_id = ? ORDER BY created_at DESC LIMIT ?",
            (owner_id, limit),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return tuple(_run_from_row(row) for row in rows)

    async def transition(
        self,
        run_id: str,
        *,
        expected: set[RunStatus],
        target: RunStatus,
        approval: dict[str, Any] | None = None,
        final_report: FinalReport | None = None,
    ) -> RunRecord:
        now = datetime.now(UTC).isoformat()
        expected_values = tuple(status.value for status in expected)
        placeholders = ",".join("?" for _ in expected_values)
        assignments = ["status = ?", "updated_at = ?"]
        parameters: list[Any] = [target.value, now]
        if approval is not None:
            assignments.append("approval_json = ?")
            parameters.append(json.dumps(approval))
        if final_report is not None:
            assignments.append("final_report_json = ?")
            parameters.append(final_report.model_dump_json())
        parameters.extend((run_id, *expected_values))
        async with self._write_lock:
            cursor = await self._connection.execute(
                f"UPDATE runs SET {', '.join(assignments)} "
                f"WHERE run_id = ? AND status IN ({placeholders})",
                parameters,
            )
            await self._connection.commit()
            changed = cursor.rowcount
            await cursor.close()
        if changed != 1:
            try:
                current = await self.get_run(run_id)
            except RunNotFoundError:
                raise
            raise RunConflictError(
                f"Run '{run_id}' is '{current.status}', expected one of {sorted(expected_values)}"
            )
        return await self.get_run(run_id)

    async def append_event(
        self,
        run_id: str,
        event_type: str,
        *,
        node: str | None = None,
        data: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> RunEvent:
        now = datetime.now(UTC)
        payload = json.dumps(data or {}, separators=(",", ":"))
        async with self._write_lock:
            cursor = await self._connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM run_events WHERE run_id = ?",
                (run_id,),
            )
            row = await cursor.fetchone()
            await cursor.close()
            if row is None:
                raise RunStoreError("Could not allocate an event sequence")
            sequence = int(row[0])
            await self._connection.execute(
                """
                INSERT OR IGNORE INTO run_events (
                    run_id, sequence, event_type, node, data_json, idempotency_key, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    sequence,
                    event_type,
                    node,
                    payload,
                    idempotency_key,
                    now.isoformat(),
                ),
            )
            await self._connection.commit()
            if idempotency_key is not None:
                cursor = await self._connection.execute(
                    "SELECT * FROM run_events WHERE run_id = ? AND idempotency_key = ?",
                    (run_id, idempotency_key),
                )
            else:
                cursor = await self._connection.execute(
                    "SELECT * FROM run_events WHERE run_id = ? AND sequence = ?",
                    (run_id, sequence),
                )
            inserted = await cursor.fetchone()
            await cursor.close()
        if inserted is None:
            raise RunStoreError("Event insert did not produce a readable row")
        async with self._condition:
            self._revision += 1
            self._condition.notify_all()
        return _event_from_row(inserted)

    async def list_events(self, run_id: str, *, after: int = 0) -> tuple[RunEvent, ...]:
        await self.get_run(run_id)
        cursor = await self._connection.execute(
            "SELECT * FROM run_events WHERE run_id = ? AND sequence > ? ORDER BY sequence",
            (run_id, after),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return tuple(_event_from_row(row) for row in rows)

    async def wait_for_change(self, observed_revision: int, *, timeout: float = 15) -> int:
        async with self._condition:
            if self._revision == observed_revision:
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._condition.wait(), timeout=timeout)
            return self._revision

    @property
    def revision(self) -> int:
        return self._revision


def _run_from_row(row: aiosqlite.Row) -> RunRecord:
    approval = json.loads(row["approval_json"]) if row["approval_json"] else None
    final_report = (
        FinalReport.model_validate_json(row["final_report_json"])
        if row["final_report_json"]
        else None
    )
    return RunRecord(
        run_id=row["run_id"],
        owner_id=row["owner_id"],
        task=row["task"],
        repository=row["repository"],
        policy=WorkflowPolicy.model_validate_json(row["policy_json"]),
        status=RunStatus(row["status"]),
        approval=approval,
        final_report=final_report,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _event_from_row(row: aiosqlite.Row) -> RunEvent:
    return RunEvent(
        run_id=row["run_id"],
        sequence=row["sequence"],
        event_type=row["event_type"],
        node=row["node"],
        data=json.loads(row["data_json"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )
