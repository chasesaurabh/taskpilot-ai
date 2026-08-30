# ADR 008: Persist named model profiles and constrain provider options

- Status: Accepted
- Date: 2026-08-29

## Context

A single process-level role map can connect TaskPilot to several providers, but it cannot express
repeatable cost, quality, or privacy configurations that a caller can select for one run. Allowing
callers to submit raw model URLs, keys, headers, or arbitrary constructor arguments would make
secrets and provider behavior part of the public API and weaken operational control.

## Decision

Keep provider definitions and secrets under operator-owned YAML/environment configuration. Group
complete role assignments and deterministic rules into named profiles. Expose only a profile name
at run creation, validate it against the server catalog, and persist the resolved profile in the
workflow policy so checkpoint resume uses the same routing decision.

Support native OpenAI and Anthropic integrations plus an OpenAI-compatible adapter. Permit common
operator-controlled options: endpoint URL, model, timeout, temperature, maximum tokens, static
non-secret extra request body, and organization/custom-header values resolved from environment
variables. Validate every referenced provider and complete role map at process startup. Never make
API keys or raw provider constructor arguments part of the run API.

## Alternatives considered

- Per-run URLs and API keys maximize caller flexibility but expand the secret, SSRF, billing, and
  audit boundary.
- One role map is simpler but forces separate TaskPilot deployments for every routing strategy.
- Arbitrary `provider_kwargs` in the run request exposes unstable SDK details and defeats schema
  validation.
- Inferring a model automatically hides cost and privacy policy and makes checkpoint resume harder
  to explain.

## Consequences

Operators can configure native or compatible providers once and expose safe, auditable choices to
the UI, CLI, and API. Runs remain reproducible across pause/restart, and telemetry identifies the
profile used. All configured profiles must be usable at startup; optional providers whose packages
or credentials are absent must be removed from active configuration. Provider-specific behavior
beyond the constrained fields still requires a deliberate adapter change.
