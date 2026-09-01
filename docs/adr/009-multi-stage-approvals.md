# ADR 009: Gate plans, writes, and commands independently

## Status

Accepted for v0.2.0.

## Decision

Keep plan approval as the default checkpoint and add independently configurable write and command
interrupts. Proposal generation is separated from patch application so the write gate occurs before
repository mutation. Repairs traverse the same write and command gates. Every request carries a
deterministic approval ID and every decision is append-only in graph state and the event log.

## Consequences

Operators can match review friction to risk without approving every tool call. Repeated repair cycles
produce multiple durable pauses, so resume and event idempotency keys include approval kind and repair
attempt. Rejecting command execution after an approved write leaves the reviewed patch present and
terminates with an explicit report.
