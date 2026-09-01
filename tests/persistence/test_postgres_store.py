from __future__ import annotations

import os
from uuid import uuid4

import pytest

from taskpilot.domain.models import RunStatus, WorkflowPolicy
from taskpilot.persistence.postgres import PostgresRunStore

POSTGRES_URL = os.getenv("TASKPILOT_TEST_POSTGRES_URL")


@pytest.mark.postgres
@pytest.mark.skipif(POSTGRES_URL is None, reason="PostgreSQL integration URL is not configured")
async def test_postgres_run_store_lifecycle_and_idempotent_events() -> None:
    assert POSTGRES_URL is not None
    store = await PostgresRunStore.open(POSTGRES_URL)
    observer = await PostgresRunStore.open(POSTGRES_URL)
    run_id = str(uuid4())
    try:
        created = await store.create_run(
            run_id=run_id,
            task="Exercise PostgreSQL",
            repository="/tmp/repository",
            policy=WorkflowPolicy(),
        )
        assert created.status == RunStatus.QUEUED

        first = await store.append_event(
            run_id,
            "run.created",
            idempotency_key="run.created",
        )
        duplicate = await store.append_event(
            run_id,
            "run.created",
            idempotency_key="run.created",
        )
        assert duplicate.sequence == first.sequence

        running = await store.claim_next(worker_id="postgres-worker", lease_seconds=60)
        assert running is not None
        assert running.run_id == run_id
        assert running.status == RunStatus.RUNNING
        assert running.lease_owner == "postgres-worker"
        assert len(await store.list_events(run_id)) == 1

        observer_revision = observer.revision
        await store.append_event(run_id, "worker.observed", idempotency_key="worker.observed")
        assert await observer.wait_for_change(observer_revision, timeout=2) == observer_revision
        assert [event.event_type for event in await observer.list_events(run_id)] == [
            "run.created",
            "worker.observed",
        ]
    finally:
        await observer.close()
        await store.close()
