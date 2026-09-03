# v0.2.0 release readiness

## Decision

**Ready for release.** The code, migrations, deterministic scenario, provider-backed multi-file
scenario, S3-compatible boundary, container boundary, production images, and static security
analysis have passed locally and in hosted CI. Scenario B ran with private, ignored configuration;
the repository retains only this sanitized outcome and no provider-specific configuration or raw
request data.

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
| Live Scenario B | Pass | Provider-backed run completed approval, multi-file writes, command execution, and validation on 2026-09-02 |
| Hosted PostgreSQL/CI matrix | Pass | [CI run 33500751038](https://github.com/chasesaurabh/taskpilot-ai/actions/runs/33500751038) passed backend, frontend, audits, services, and image builds |
| CodeQL | Pass | [CodeQL run 33500751410](https://github.com/chasesaurabh/taskpilot-ai/actions/runs/33500751410) passed Python and JavaScript/TypeScript analysis |

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

1. Require green hosted CI, including PostgreSQL, MinIO, container execution, audits, CodeQL, and
   container builds.
2. Confirm the working tree contains only the intended release commit, then publish the matching
   GitHub release so trusted publishing builds the package and provenance-attested images.
