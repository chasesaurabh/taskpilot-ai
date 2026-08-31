# v0.1.0 release readiness

Review date: 2026-08-30

Branch: `main`

## Decision

The implementation, deterministic evaluation, security review, documentation, package, Docker
demo, and required live-provider validation milestones are complete. The repository is ready to tag
as `v0.1.0`. Scenario A completed successfully through approval, implementation, real validation,
one bounded repair, review, and final reporting. Scenario B remains strongly recommended after the
release but is not a release gate.

## Verification results

| Gate | Result |
| --- | --- |
| Ruff formatting and lint | Passed; formatting clean, no lint findings |
| mypy | Passed in strict mode; 40 source files |
| Backend tests | 65 passed, 4 skipped; 85.35% coverage |
| Bundled sample API | 2 passed |
| Frontend | Prettier and ESLint passed; 4 Vitest tests passed; production build passed |
| Python package | Source distribution and wheel built successfully |
| Pre-commit | All configured hooks passed |
| Dependency audits | `pip-audit` and `pnpm audit --prod --audit-level high`: no known vulnerabilities |
| CI configuration | GitHub Actions YAML parsed; Compose configuration valid |
| Secret check | No known live-token patterns or tracked credential/database files found |
| Browser review | 1440×900 Docker UI reviewed; no browser warnings or errors |
| Live provider | Scenario A completed; 5 generated-repository tests passed after one bounded repair |

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

## Live-provider evidence

The sanitized [Scenario A trace](evidence/v0.1.0-scenario-a.json) records 9 model completions, the
approval and resume boundary, two write/validate cycles, 2 changed files, one repair, 5 passing
generated-repository tests, code review, and final reporting. Provider-specific identifiers and raw
requests are intentionally excluded. Do not enable paid or probabilistic live tests in ordinary CI.

## Publication status

Release `v0.1.0` was tagged from validated commit `21f4a50` and published on 2026-08-30. The Python
wheel and source distribution are available from
[PyPI](https://pypi.org/project/taskpilot-ai/0.1.0/). Public, provenance-attested API and web images
are available from GHCR as `ghcr.io/chasesaurabh/taskpilot-ai:0.1.0` and
`ghcr.io/chasesaurabh/taskpilot-ai-web:0.1.0`. The
[publishing workflow](https://github.com/chasesaurabh/taskpilot-ai/actions/runs/33351719786)
completed successfully using PyPI Trusted Publishing and the repository-scoped GitHub token.

## Known release limitations

- One trusted developer; no authentication, tenant isolation, or horizontally scaled workers.
- Approved repository commands execute repository code; hostile inputs require external isolation.
- Restart/resume is proven across the approval boundary, not as general exactly-once side effects.
- One approval gate precedes writes and commands; no per-operation approvals.
- Context is bounded rather than retrieval-based, and large outputs have no external artifact store.
- Live structured-output behavior remains dependent on the configured provider and model.
