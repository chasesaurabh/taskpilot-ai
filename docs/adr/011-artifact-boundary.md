# ADR 011: Store full evidence as immutable artifacts

## Status

Accepted for v0.2.0.

## Decision

Keep checkpoints and SSE payloads bounded while writing full patches and validation logs to an
artifact adapter. Local files support development; S3-compatible storage supports durable shared
deployments. Graph state and events contain immutable references with media type, size, and SHA-256.
Downloads pass through the run-owner authorization boundary.

## Consequences

Operators own encryption and lifecycle policy for sensitive source evidence. Artifact failure is a
visible workflow failure rather than silent evidence loss. The adapter is synchronous because graph
nodes are synchronous today; a separate worker boundary can absorb object-store latency later.
