"""PostgreSQL run projection and event log."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from taskpilot.domain.models import FinalReport, RunStatus, WorkflowPolicy
from taskpilot.persistence.runs import (
    RunConflictError,
    RunEvent,
    RunNotFoundError,
    RunRecord,
    RunStoreError,
)


class PostgresRunStore:
    """PostgreSQL adapter with transactional sequences and optimistic transitions."""

    def __init__(self, connection: AsyncConnection[Any]) -> None:
        self._connection = connection
        self._write_lock = asyncio.Lock()
        self._condition = asyncio.Condition()
        self._revision = 0

    @classmethod
    async def open(cls, connection_string: str) -> PostgresRunStore:
        connection: AsyncConnection[Any] = await AsyncConnection.connect(
            connection_string,
            row_factory=dict_row,
            autocommit=True,
        )
        store = cls(connection)
        await store.setup()
        return store

    async def setup(self) -> None:
        await self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL DEFAULT 'local',
                task TEXT NOT NULL,
                repository TEXT NOT NULL,
                policy_json JSONB NOT NULL,
                status TEXT NOT NULL,
                approval_json JSONB,
                final_report_json JSONB,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        await self._connection.execute(
            "ALTER TABLE runs ADD COLUMN IF NOT EXISTS owner_id TEXT NOT NULL DEFAULT 'local'"
        )
        await self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS run_events (
                run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                sequence BIGINT NOT NULL,
                event_type TEXT NOT NULL,
                node TEXT,
                data_json JSONB NOT NULL,
                idempotency_key TEXT,
                created_at TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (run_id, sequence),
                UNIQUE (run_id, idempotency_key)
            )
            """
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
        await self._connection.execute(
            """
            INSERT INTO runs (
                run_id, owner_id, task, repository, policy_json, status, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s)
            """,
            (
                run_id,
                owner_id,
                task,
                repository,
                policy.model_dump_json(),
                RunStatus.QUEUED,
                now,
                now,
            ),
        )
        await self._connection.commit()
        return await self.get_run(run_id)

    async def get_run(self, run_id: str) -> RunRecord:
        cursor = await self._connection.execute("SELECT * FROM runs WHERE run_id = %s", (run_id,))
        row = await cursor.fetchone()
        if row is None:
            raise RunNotFoundError(f"Run not found: {run_id}")
        return _run_from_row(row)

    async def list_runs(self, *, owner_id: str, limit: int = 100) -> tuple[RunRecord, ...]:
        cursor = await self._connection.execute(
            "SELECT * FROM runs WHERE owner_id = %s ORDER BY created_at DESC LIMIT %s",
            (owner_id, limit),
        )
        return tuple(_run_from_row(row) for row in await cursor.fetchall())

    async def transition(
        self,
        run_id: str,
        *,
        expected: set[RunStatus],
        target: RunStatus,
        approval: dict[str, Any] | None = None,
        final_report: FinalReport | None = None,
    ) -> RunRecord:
        assignments = ["status = %s", "updated_at = %s"]
        parameters: list[Any] = [target.value, datetime.now(UTC)]
        if approval is not None:
            assignments.append("approval_json = %s::jsonb")
            parameters.append(json.dumps(approval))
        if final_report is not None:
            assignments.append("final_report_json = %s::jsonb")
            parameters.append(final_report.model_dump_json())
        parameters.extend((run_id, [status.value for status in expected]))
        async with self._write_lock:
            cursor = await self._connection.execute(
                f"UPDATE runs SET {', '.join(assignments)} "
                "WHERE run_id = %s AND status = ANY(%s) RETURNING run_id",
                parameters,
            )
            changed = await cursor.fetchone()
            await self._connection.commit()
        if changed is None:
            current = await self.get_run(run_id)
            expected_values = sorted(status.value for status in expected)
            raise RunConflictError(
                f"Run '{run_id}' is '{current.status}', expected one of {expected_values}"
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
        async with self._write_lock, self._connection.transaction():
            await self._connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (run_id,))
            cursor = await self._connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence "
                "FROM run_events WHERE run_id = %s",
                (run_id,),
            )
            sequence_row = await cursor.fetchone()
            if sequence_row is None:
                raise RunStoreError("Could not allocate an event sequence")
            sequence = int(sequence_row["sequence"])
            cursor = await self._connection.execute(
                """
                INSERT INTO run_events (
                    run_id, sequence, event_type, node, data_json, idempotency_key, created_at
                ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)
                ON CONFLICT (run_id, idempotency_key) DO NOTHING
                RETURNING *
                """,
                (
                    run_id,
                    sequence,
                    event_type,
                    node,
                    json.dumps(data or {}),
                    idempotency_key,
                    datetime.now(UTC),
                ),
            )
            row = await cursor.fetchone()
            if row is None and idempotency_key is not None:
                cursor = await self._connection.execute(
                    "SELECT * FROM run_events WHERE run_id = %s AND idempotency_key = %s",
                    (run_id, idempotency_key),
                )
                row = await cursor.fetchone()
        if row is None:
            raise RunStoreError("Event insert did not produce a readable row")
        async with self._condition:
            self._revision += 1
            self._condition.notify_all()
        return _event_from_row(row)

    async def list_events(self, run_id: str, *, after: int = 0) -> tuple[RunEvent, ...]:
        await self.get_run(run_id)
        cursor = await self._connection.execute(
            "SELECT * FROM run_events WHERE run_id = %s AND sequence > %s ORDER BY sequence",
            (run_id, after),
        )
        return tuple(_event_from_row(row) for row in await cursor.fetchall())

    async def wait_for_change(self, observed_revision: int, *, timeout: float = 15) -> int:
        async with self._condition:
            if self._revision == observed_revision:
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._condition.wait(), timeout=timeout)
            return self._revision

    @property
    def revision(self) -> int:
        return self._revision


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _run_from_row(row: dict[str, Any]) -> RunRecord:
    return RunRecord(
        run_id=row["run_id"],
        owner_id=row["owner_id"],
        task=row["task"],
        repository=row["repository"],
        policy=WorkflowPolicy.model_validate(_json_value(row["policy_json"])),
        status=RunStatus(row["status"]),
        approval=_json_value(row["approval_json"]) if row["approval_json"] else None,
        final_report=(
            FinalReport.model_validate(_json_value(row["final_report_json"]))
            if row["final_report_json"]
            else None
        ),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _event_from_row(row: dict[str, Any]) -> RunEvent:
    return RunEvent(
        run_id=row["run_id"],
        sequence=row["sequence"],
        event_type=row["event_type"],
        node=row["node"],
        data=_json_value(row["data_json"]),
        created_at=row["created_at"],
    )
