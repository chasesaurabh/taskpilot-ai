# v0.2.0 release readiness

## Decision

**Release candidate, pending the paid live-provider Scenario B and hosted CI.** The code, migrations,
deterministic scenario, S3-compatible boundary, and container boundary have been exercised locally.
No provider credential or private live policy was present during this review, so the paid multi-file
scenario was not run and the release must not be tagged or published yet.

## Gate record

| Gate | Result | Evidence |
| --- | --- | --- |
| Package/API/web metadata | Pass | Python package, FastAPI metadata, and web package identify `0.2.0` |
| Static analysis | Pass | Ruff lint and mypy over `src` |
| Backend deterministic suite | Pass | 78 passed; 6 credential/service-gated tests skipped locally |
| Frontend quality/build | Pass | Prettier, ESLint, 4 Vitest tests, TypeScript, and production Vite build |
| SQLite v0.1 schema upgrade | Pass | `tests/persistence/test_sqlite_migrations.py` opens and upgrades a legacy database |
| S3-compatible artifact boundary | Pass | Real MinIO round trip through `S3ArtifactStore` |
| Container command boundary | Pass | Real Docker execution with network/capability/resource restrictions |
| Bundled dataset | Pass | `taskpilot evaluate evaluations/datasets/demo-pagination.yaml` completed `add-pagination` |
| Python artifacts/dependency audit | Pass | Wheel and sdist built as 0.2.0; pip-audit found no known dependency vulnerabilities |
| Compose image build | Pass | API and web production images built locally, including the OIDC extra |
| Paid live Scenario B | **Blocked external gate** | No live provider credentials or private live policy were available |
| Hosted PostgreSQL/CI matrix | Pending | Runs in the repository's self-hosted CI service matrix |

## Migration scope

The run stores add `lease_owner`, `lease_expires_at`, and `execution_attempts` columns using idempotent
startup migrations. Legacy SQLite rows remain readable with their existing workflow policy and owner
defaults. LangGraph continues to use the run ID as its checkpoint thread ID; the workflow state
metadata advances to schema version 2. Existing approval-boundary checkpoints use fields with safe
defaults and resume through the same stable approval node names.

## Integration setup

CI starts a pinned S3-compatible MinIO service and uses the standard AWS test credential chain. The
container test uses `python:3.12-slim`; production policies should pin their validation image by digest.
The PostgreSQL job supplies `TASKPILOT_TEST_POSTGRES_URL`, while the S3 and container tests are enabled
only when their explicit test environment variables are present.

## Before publishing

1. Run Scenario B with an approved paid provider, sanitize and retain its trace, and record provider,
   model, token usage, repair count, duration, and outcome.
2. Require green hosted CI, including PostgreSQL, MinIO, container execution, audits, CodeQL, and
   container builds.
3. Confirm the working tree contains only the intended release commit, then publish the matching
   GitHub release so trusted publishing builds the package and provenance-attested images.
