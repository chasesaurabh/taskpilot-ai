# ADR 010: Scope runs to authenticated principals

## Status

Accepted for v0.2.0.

## Decision

Persist a stable owner ID on every run and enforce it for listing, lookup, SSE, decisions, and
artifact downloads. Local mode uses an unauthenticated `local` principal. Shared deployments may use
opaque bearer tokens or OIDC; authenticated identity, rather than request content, owns approval
actor attribution. Missing another owner's run returns not found to avoid identifier disclosure.

## Consequences

The persistence schema requires an additive owner migration with a `local` default for v0.1 data.
Authentication is a control-plane boundary and must be paired with TLS. Role and issuer configuration
can evolve without changing run ownership or workflow state.
