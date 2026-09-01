from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from taskpilot.domain.models import RunStatus, WorkflowPolicy
from taskpilot.persistence.runs import RunConflictError, SqliteRunStore


async def test_v01_database_is_upgraded_with_local_owner(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY,
            task TEXT NOT NULL,
            repository TEXT NOT NULL,
            policy_json TEXT NOT NULL,
            status TEXT NOT NULL,
            approval_json TEXT,
            final_report_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO runs VALUES (
            'legacy-run', 'Legacy task', '/tmp/repository',
            '{"max_repair_attempts":2,"require_plan_approval":true,"model_profile":null}',
            'queued', NULL, NULL, '2026-08-29T00:00:00+00:00', '2026-08-29T00:00:00+00:00'
        );
        """
    )
    connection.commit()
    connection.close()

    store = await SqliteRunStore.open(path)
    try:
        migrated = await store.get_run("legacy-run")
        assert migrated.owner_id == "local"
        assert migrated.policy.require_write_approval is False
        assert migrated.policy.require_command_approval is False
    finally:
        await store.close()


async def test_sqlite_worker_recovers_unleased_run_and_fences_wrong_owner(
    tmp_path: Path,
) -> None:
    store = await SqliteRunStore.open(tmp_path / "leases.sqlite")
    try:
        legacy_run = str(uuid4())
        await store.create_run(
            run_id=legacy_run,
            task="Recover legacy running work",
            repository=str(tmp_path),
            policy=WorkflowPolicy(),
        )
        await store.transition(
            legacy_run,
            expected={RunStatus.QUEUED},
            target=RunStatus.RUNNING,
        )

        recovered = await store.claim_next(worker_id="worker-a", lease_seconds=60)

        assert recovered is not None
        assert recovered.run_id == legacy_run
        assert recovered.lease_recovered is True
        assert recovered.lease_owner == "worker-a"
        with pytest.raises(RunConflictError):
            await store.transition(
                legacy_run,
                expected={RunStatus.RUNNING},
                target=RunStatus.COMPLETED,
                lease_owner="worker-b",
            )
    finally:
        await store.close()
