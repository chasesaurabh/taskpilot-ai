# Changelog

All notable changes to TaskPilot AI are documented in this file. The project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Independent durable plan, repository-write, and validation-command approval gates, including
  graph, API, CLI, and web UI support across repeated repair cycles.
- Owner-scoped bearer authentication, authenticated approval actors, and per-user run listing.
- Local and S3-compatible artifact stores for immutable full patches and validation logs, with
  integrity metadata, durable events, and an owner-protected download endpoint.
- Opt-in ephemeral container execution for allowlisted validation commands with no network,
  dropped capabilities, resource limits, and a constrained repository mount.
- YAML model-backed evaluation datasets and a `taskpilot evaluate` runner that asserts outcomes,
  files, graph paths, and repair bounds through the public API.
- Crash-safe multi-file repository transactions, persisted operation identities, replay of completed
  effects, and fail-closed recovery for commands whose completion is uncertain.
- Database-backed graph-worker leasing with expired-lease recovery and cross-process event refresh,
  allowing API and worker processes to scale independently.
- OIDC JWT validation with rotating JWKS keys, issuer/audience/expiry enforcement, role-gated
  approvals, admin run/event inspection, and durable approval authorization audits.
- Deterministic relevance-ranked repository context instead of alphabetical truncation.
- SQLite upgrade coverage plus release-gated S3-compatible artifact and container execution tests.

### Changed

- Package, API, and web metadata now identify the v0.2.0 release line.
- Dataset evaluation runs against an isolated repository copy, preserving source fixtures.
- CLI evaluation results use Windows-safe status labels.

## [0.1.0] - 2026-08-29

### Added

- Named model-routing profiles selectable through the API, CLI, and web UI, persisted with durable
  workflow policy and included in model-decision telemetry.
- Startup validation for profile completeness, provider integrations, structured-output capability,
  and required environment-backed credentials and headers.
- Safe compatible-provider options for maximum tokens, organization, custom headers, and extra
  request bodies; Docker images now include OpenAI and Anthropic integrations.
- OIDC-based PyPI Trusted Publishing and public, provenance-attested GHCR release images for the
  API and web UI.

- Typed LangGraph software-delivery workflow with parallel analysis, deterministic conditional
  routing, native approval interrupts, bounded diagnosis/repair loops, and final reporting.
- SQLite and PostgreSQL checkpoints plus separate run/event projections for restart-safe approval
  resume and replayable SSE.
- Provider-neutral LangChain model gateway for OpenAI, Anthropic, OpenAI-compatible, and local
  OpenAI-compatible endpoints, with structured output, routing evidence, latency, and usage data.
- Constrained repository reads, searches, Git inspection, hash-guarded atomic writes, and
  shell-free allowlisted validation commands.
- FastAPI lifecycle API, installable CLI, graph-first React interface, deterministic no-key demo,
  Docker Compose stack, and bundled sample repository.
- Deterministic architecture tests, opt-in live-provider scenarios, security regression tests,
  dependency audits, CodeQL analysis, and reviewer-focused architecture documentation.

### Security

- Validate all proposed changes before the first write and keep optimistic write preconditions
  application-owned rather than model-owned.
- Enforce canonical repository boundaries, reject traversal and symlink escapes, strip command
  environments, cap command time/output, and normalize provider errors without raw secret details.

### Known limitations

- The runtime assumes one trusted developer and has no built-in authentication or multi-tenancy.
- Allowed validation commands execute repository code on the host; hostile repositories require an
  external disposable container or VM.
- Approval resume survives a full application restart, but side effects inside an interrupted
  write/command node are not generally exactly-once.
- Live-provider scenarios are opt-in and require the operator's credentials; they are not ordinary
  CI gates.

[0.1.0]: https://github.com/chasesaurabh/taskpilot-ai/releases/tag/v0.1.0
