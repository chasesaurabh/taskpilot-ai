# v0.1.0 release readiness

Review date: 2026-08-29  
Branch: `release/v0.1.0-credibility`

## Decision

The implementation, deterministic evaluation, security review, documentation, package, and Docker
demo milestones are complete. The repository is a **release candidate**, not yet an unconditional
tag recommendation: the opt-in credentialed live-provider scenarios have not run in this
credential-free environment. Execute at least the two documented live scenarios and review their
trace files before creating `v0.1.0` if real-provider proof is part of the release bar.

## Verification results

| Gate | Result |
| --- | --- |
| Ruff formatting and lint | Passed; 78 files formatted, no lint findings |
| mypy | Passed in strict mode; 40 source files |
| Backend tests | 49 passed, 4 skipped; 83.87% coverage |
| Bundled sample API | 2 passed |
| Frontend | Prettier and ESLint passed; 3 Vitest tests passed; production build passed |
| Python package | Source distribution and wheel built successfully |
| Pre-commit | All configured hooks passed |
| Dependency audits | `pip-audit` and `pnpm audit --prod --audit-level high`: no known vulnerabilities |
| CI configuration | GitHub Actions YAML parsed; Compose configuration valid |
| Secret check | No known live-token patterns or tracked credential/database files found |
| Browser review | 1440×900 Docker UI reviewed; no browser warnings or errors |

The four local skips are explicit: two credentialed live-provider scenarios, one PostgreSQL adapter
test without a host-exposed test URL, and one Windows symlink test where the host denies symlink
creation. CI configures the PostgreSQL adapter test. The actual Docker sample run below exercises the
PostgreSQL run store and LangGraph checkpointer.

## Docker evidence

`docker compose up --build` built the API and nginx 1.31 web images and started PostgreSQL 17. The
API health endpoint returned `{"status":"ok"}`. Run
`a0dfd6c6-668b-4da4-ae1b-fcdaad4f0a76` completed against the bundled repository with persisted
evidence for:

- approval required, decision, and resume;
- 10 node starts and 10 node completions;
- 7 model completions and 3 repository-tool completions;
- 2 changed files, a passing three-test validation command, and a terminal completion event;
- 2,254 reported tokens and 35.9 seconds of end-to-end elapsed time.

The captured [completed graph](assets/taskpilot-hero.png) and
[approval state](assets/taskpilot-approval.png) came from this run.

## Remaining pre-tag action

Follow [live-model validation](live-model-validation.md) with provider credentials and archive the
two JSON trace files as release evidence. This is an external validation action, not missing product
code. Do not enable these paid/probabilistic tests in ordinary CI.

## Known release limitations

- One trusted developer; no authentication, tenant isolation, or horizontally scaled workers.
- Approved repository commands execute repository code; hostile inputs require external isolation.
- Restart/resume is proven across the approval boundary, not as general exactly-once side effects.
- One approval gate precedes writes and commands; no per-operation approvals.
- Context is bounded rather than retrieval-based, and large outputs have no external artifact store.
- Live structured-output behavior remains dependent on the configured provider and model.
