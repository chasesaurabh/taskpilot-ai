# Principal Engineer interview guide

This document describes the v0.1.0 implementation on the
`release/v0.1.0-credibility` branch. It is technical preparation, not a scale or adoption claim.

## 30-second explanation

TaskPilot AI is a human-governed software-delivery orchestrator. LangGraph makes the workflow
explicit—parallel analysis, approval, implementation, validation, bounded repair, review, and
durable resume—while LangChain provides provider-neutral structured model calls. Repository access
is constrained behind application-owned capabilities, and a separate run/event projection makes
the execution observable through SSE, a CLI, and a graph-first UI.

## Two-minute architecture explanation

FastAPI accepts a repository-scoped task and creates a run whose ID is also the LangGraph
`thread_id`. The graph collects bounded context, asks typed models for analysis and a plan, runs
architecture and repository-impact reviews in parallel, then joins at a native `interrupt()`.
Approval resumes the saved thread with `Command(resume=…)`. The coder returns structured full-file
intent; TaskPilot attaches repository hashes captured before inference and applies atomic guarded
writes. Allowlisted validation commands run without a shell. Failures route through diagnosis and a
bounded repair loop; a blocking review can use the same budget. LangGraph checkpoints own execution
position and state. SQLite or PostgreSQL run/event stores own queryable lifecycle and replayable SSE.

## Why LangGraph instead of a simple agent loop?

The important decisions are policy decisions, not model decisions. `StateGraph` exposes the two-way
fan-out/join, the approval boundary, deterministic pass/fail routes, and the repair budget in code.
Native interrupts and checkpoints avoid rebuilding durable pause/resume semantics around a prompt
loop.

## Why LangChain?

LangChain supplies a common chat-model constructor, prompt/runnable composition, structured Pydantic
output, and usage metadata across OpenAI, Anthropic, and OpenAI-compatible endpoints. TaskPilot keeps
that dependency behind `ModelGateway`; provider SDK details never enter graph topology.

## Why deterministic routing?

Approval status, validation evidence, blocking findings, and retry counts are already typed facts.
Asking another model where to route would add cost and uncertainty to a policy decision. Model
routing is also explicit configuration, so quality/cost/privacy choices are inspectable.

## Why human-in-the-loop?

The graph discloses the plan, affected files, commands, risks, and parallel findings before the first
write or command. One meaningful gate avoids both blind autonomy and approval fatigue. v0.1.0 does
not pretend to implement separate per-write or per-command gates.

## Why checkpoints separate from the run/event projection?

LangGraph checkpoints contain framework execution state needed for resume. API consumers need stable
run status and ordered events without coupling to checkpoint internals. The projection can evolve
for queries and SSE while checkpoints remain the execution authority.

## How does crash recovery work?

At approval, the checkpoint stores the graph position and typed state. The packaged restart test
closes the application, reopens the same SQLite databases, and resumes the original thread. A crash
inside a side-effecting node is a known limitation: v0.1.0 does not claim general exactly-once worker
execution or automatic recovery of arbitrary `RUNNING` projections.

## How is duplicate resume prevented?

The run store performs a compare-and-set transition from `waiting_for_approval` to `running` before
calling `Command(resume=…)`. A competing or repeated decision sees the changed status and receives a
409 rather than starting a second resume.

## How do side effects remain idempotent?

They are guarded, not universally exactly-once. The application snapshots hashes before inference,
rejects stale replacements, writes through an atomic temporary-file swap, and deduplicates public
events with idempotency keys. Commands may still run twice after a precisely timed crash; an
enterprise worker would need persisted operation leases/results or a durable workflow runtime.

## How does the repair loop work?

A failed allowlisted command creates typed `ValidationResult`; deterministic routing checks the
shared repair budget. A coder model receives the change set and bounded output, returns a typed
diagnosis, and proposes a focused repair against a fresh hash snapshot. The graph retests. Blocking
review findings create a review-specific diagnosis and use the same bounded loop.

## Why SSE rather than WebSockets?

Workflow observation is server-to-client; approval is an ordinary HTTP command. SSE gives browser
reconnection and `Last-Event-ID` replay without a bidirectional connection protocol. Horizontal
instances would need PostgreSQL notifications or a broker because v0.1.0 wakeups are process-local.

## Why is arbitrary shell access prohibited?

Model-produced strings and repository content are untrusted. TaskPilot executes argument vectors
with `shell=False`, a configured prefix allowlist, a stripped environment, timeout, and output cap.
Allowed test/build commands still execute repository code, so hostile repositories require external
container/VM isolation.

## How does model routing work?

Each role resolves through ordered rules and then a required default assignment. Rules can inspect
complexity, privacy requirement, and repository file count. Every selection records role, provider,
model, reason, latency, and token usage when reported.

## How can local models be used?

Configure `provider: local`, an OpenAI-compatible `base_url`, a model name, and `local: true`. The
factory uses LangChain's OpenAI-compatible client and a non-secret placeholder key when the endpoint
does not require one. The endpoint must support the structured-output behavior used by the selected
model integration.

## What happens when structured output fails?

`ModelGateway` checks the LangChain `include_raw` envelope, rejects parsing errors or the wrong
Pydantic type, and normalizes provider exceptions without exposing raw error detail. The run service
records a failed lifecycle event. v0.1.0 does not retry malformed provider responses independently
of the engineering repair loop.

## What changes for enterprise multi-tenancy?

Add authenticated tenant identity, authorization on repositories/runs, tenant-scoped encryption and
retention, isolated workers, secret brokering, quotas, audit export, policy administration, and
separate control/data planes. None belongs in the trusted single-developer v0.1.0 process.

## What changes for horizontally scaled workers?

Replace in-process background tasks and condition variables with a durable queue/lease protocol;
persist operation attempts/results; use cross-process event notification; fence repository
worktrees; and define checkpoint/run-projection reconciliation. PostgreSQL storage alone is not that
worker architecture.

## Current limitations

No authentication, hostile-repository sandbox, general crash recovery, transactional multi-file
writes, artifact store, automatic context retrieval for large repositories, or proven live-provider
run in the credential-free build environment. The live harness is opt-in and must be run before the
release candidate is tagged.

## What would be revisited at 100× scale?

The first changes would be isolated per-run worktrees, queued/fenced workers, an outbox-backed event
stream, object storage for patches/logs, relevance-based context selection, provider rate limiting,
and explicit reconciliation between checkpoint and lifecycle state. The graph topology and
provider/tool boundaries can remain; the single-process composition cannot.
