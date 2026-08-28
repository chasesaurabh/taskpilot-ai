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

        running = await store.transition(
            run_id,
            expected={RunStatus.QUEUED},
            target=RunStatus.RUNNING,
        )
        assert running.status == RunStatus.RUNNING
        assert len(await store.list_events(run_id)) == 1
    finally:
        await store.close()
