# Repeatable evaluation scenarios

TaskPilot's evaluation suite uses deterministic models and temporary repositories. It does not require credentials or make network calls.

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
