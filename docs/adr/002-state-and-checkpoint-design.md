# ADR 002: Separate graph checkpoints and query projections

- Status: Accepted
- Date: 2026-08-28

## Context

Graph execution needs complete resumable state, while APIs need efficient run queries and engineering outputs can be large. Storing every source file and command transcript in every checkpoint would grow rapidly.

## Decision

Use a versioned typed graph state and LangGraph checkpointer as the execution authority. Maintain a run projection and append-only event log for product queries. Keep repository context and command output bounded; reserve immutable artifact identifiers in domain models for a later object-store adapter.

## Alternatives considered

- Checkpoints only couple the public API to framework internals and make event replay awkward.
- One relational document per run loses step-level durability and concurrency control.
- Full payloads in state simplify reads but create avoidable serialization, privacy, and retention costs.

## Consequences

Resume semantics stay native to LangGraph and public contracts stay stable. Operators must back up checkpoint and run/event data consistently. Proposed file content remains in trusted checkpoints for durable hash-guarded resume but is redacted from public events; long-term patch and full-log retention awaits the artifact adapter. State migrations require explicit schema-version handling.
