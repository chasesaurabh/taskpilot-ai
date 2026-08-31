"""Persistence contracts used by the application layer."""

from __future__ import annotations

from typing import Any, Protocol

from taskpilot.domain.models import FinalReport, RunStatus, WorkflowPolicy
from taskpilot.persistence.runs import RunEvent, RunRecord


class RunStore(Protocol):
    async def create_run(
        self,
        *,
        run_id: str,
        task: str,
        repository: str,
        policy: WorkflowPolicy,
        owner_id: str = "local",
    ) -> RunRecord: ...

    async def get_run(self, run_id: str) -> RunRecord: ...

    async def list_runs(self, *, owner_id: str, limit: int = 100) -> tuple[RunRecord, ...]: ...

    async def transition(
        self,
        run_id: str,
        *,
        expected: set[RunStatus],
        target: RunStatus,
        approval: dict[str, Any] | None = None,
        final_report: FinalReport | None = None,
    ) -> RunRecord: ...

    async def append_event(
        self,
        run_id: str,
        event_type: str,
        *,
        node: str | None = None,
        data: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> RunEvent: ...

    async def list_events(self, run_id: str, *, after: int = 0) -> tuple[RunEvent, ...]: ...

    async def wait_for_change(self, observed_revision: int, *, timeout: float = 15) -> int: ...

    @property
    def revision(self) -> int: ...


class ClosableRunStore(RunStore, Protocol):
    async def close(self) -> None: ...
