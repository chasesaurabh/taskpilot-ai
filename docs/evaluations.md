# Repeatable evaluation scenarios

TaskPilot's deterministic evaluation suite uses temporary repositories. It does not require
credentials or make network calls.

Run all five required scenarios:

```bash
uv run pytest \
  tests/graph/test_workflow.py \
  tests/nodes/test_engineering_workflow.py \
  tests/persistence/test_checkpoint_resume.py
```

| Scenario | Assertion | Automated test |
| --- | --- | --- |
| Simple successful change | Implementation validates and reaches review/report | `test_graph_runs_parallel_analysis_and_success_path` |
| Test failure and repair | A real file fails a real process check, is repaired, and passes | `test_real_nodes_apply_repair_retest_review_and_report` |
| Human rejects plan | Resume routes directly to report without implementation | `test_rejected_resume_routes_to_report_without_implementation` |
| Restart and resume | SQLite is closed, reopened, and resumes the same thread exactly once | `test_run_survives_checkpointer_close_and_resumes_exact_thread` |
| Retry exhaustion | Repair budget ends deterministically with a failed report | `test_real_nodes_stop_safely_when_repairs_never_pass` |

These are behavioral tests rather than mocked screenshots: graph routes, checkpoints, repository writes, subprocess validation, and terminal reports are asserted directly.

The packaged no-key product path has an additional API-level evaluation:

```bash
uv run pytest tests/runtime/test_runtime.py
```

It copies the bundled sample repository, starts the lifespan-managed SQLite runtime, waits for the real LangGraph interrupt, approves the run over HTTP, applies pagination, executes the sample tests as a subprocess, and asserts model/tool telemetry plus event redaction. PostgreSQL parity is covered by `tests/persistence/test_postgres_store.py` when `TASKPILOT_TEST_POSTGRES_URL` is set; CI supplies a disposable PostgreSQL service automatically.

## Headline repair-loop evaluation

`test_real_nodes_apply_repair_retest_review_and_report` uses the production graph and
`RepositoryWorkspace`, not fabricated events. Its first implementation writes a value that causes
the allowlisted validation subprocess to fail. The observed path is:

```text
implementation → testing (failed) → failure_analysis → repair → testing (passed)
→ code_review → final_report
```

The test asserts the actual repository content, validation outcome, repair count, model decisions,
and terminal report. A second case proves retry exhaustion, and a third proves that blocking review
findings can drive a new repair without reusing a stale validation diagnosis.

## Durable application restart

`test_packaged_runtime_resumes_after_application_restart` starts the packaged API, reaches the native
approval interrupt, closes the entire application lifespan, opens a new application against the same
SQLite run and checkpoint databases, approves the original run ID, and completes it. It asserts one
`run.started`, one `run.resumed`, and no repository write before approval.

SQLite is the local adapter. PostgreSQL provides the same logical checkpoint and run/event contracts,
database-backed worker leases, skip-locked claims, and cross-process SSE refresh. Repository writes
use persisted operation identities and batch rollback; completed operations replay safely. A command
left in the uncertain state is not repeated automatically and requires operator resolution.

## Live-provider evaluation

See [Live-model validation](live-model-validation.md). Two opt-in scenarios execute the complete API
and graph using the configured LangChain provider; they are always skipped in ordinary CI.

## Dataset runner

`taskpilot evaluate <dataset.yaml>` runs declarative cases through the public API and therefore uses
the server's selected model profile, persistence, approvals, repository tools, and artifact path.
Cases can assert an outcome, changed-file subset, required graph-path subsequence, and minimum/maximum
repair count. The bundled `evaluations/datasets/demo-pagination.yaml` documents the schema and runs
against deterministic demo mode. By default each case operates on an isolated copy, so the referenced
fixture is never modified. Private datasets can select live profiles without committing credentials
or provider-specific request data.

Release integration checks also exercise SQLite schema upgrades, an actual S3-compatible service,
and a real container runtime. The paid multi-file Scenario B remains an explicit manual gate because
it needs operator-supplied provider credentials and policy.
