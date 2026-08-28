# ADR 002: Separate graph checkpoints, run projections, and artifacts

- Status: Accepted
- Date: 2026-08-28

## Context

Graph execution needs complete resumable state, while APIs need efficient run queries and engineering outputs can be large. Storing every source file and command transcript in every checkpoint would grow rapidly.

## Decision

Use a versioned typed graph state and LangGraph checkpointer as the execution authority. Maintain a run projection and append-only event log for product queries. Store bulky content in an artifact store and reference it by immutable identifier and hash.

## Alternatives considered

- Checkpoints only couple the public API to framework internals and make event replay awkward.
- One relational document per run loses step-level durability and concurrency control.
- Full payloads in state simplify reads but create avoidable serialization, privacy, and retention costs.

## Consequences

Resume semantics stay native to LangGraph and public contracts stay stable. Operators must back up and retain checkpoint, run/event, and artifact data consistently. State migrations require explicit schema-version handling.
