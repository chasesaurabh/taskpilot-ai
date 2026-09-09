# ADR 006: Persist events and stream them with SSE

- Status: Accepted
- Date: 2026-08-28

## Context

CLI and web clients need live node state, tool calls, usage, approvals, and terminal results. Clients also need to reconnect without losing events.

## Decision

Normalize internal graph callbacks into a stable append-only event representation. Persist before publishing. Expose replay plus tailing through Server-Sent Events and accept approval/rejection through ordinary HTTP. Honor `Last-Event-ID`. Introduce an explicit API version before making incompatible schema changes.

## Alternatives considered

- WebSockets support bidirectional traffic but add connection state and replay complexity that this request/response control plane does not need.
- Polling is simple but increases latency and load and provides a poorer CLI experience.
- Streaming raw LangGraph events couples clients to internal framework and state details.

## Consequences

Browsers and CLI clients get a simple reconnectable feed and the public schema can evolve
independently. In multi-process deployments, bounded refresh from the durable event table makes
events written by another worker visible without changing the API contract.
