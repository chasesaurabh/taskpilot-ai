# ADR 004: Add a capability-aware model gateway over LangChain

- Status: Accepted
- Date: 2026-08-28

## Context

Planning, coding, and review have different cost and quality needs. Providers expose a common core but differ in structured output, tools, usage data, and local endpoint behavior.

## Decision

Use LangChain chat-model interfaces behind a TaskPilot `ModelGateway`. Configure models by responsibility, record every routing decision, validate required capabilities, and normalize structured responses and usage. Provide deterministic demo, OpenAI, Anthropic, and OpenAI-compatible factories.

## Alternatives considered

- Direct provider SDKs offer maximum feature access but duplicate orchestration-facing interfaces.
- One global model is easy to configure but prevents intentional cost, latency, privacy, and quality choices.
- A magical runtime router reduces configuration but makes behavior and spend hard to explain.

## Consequences

Nodes are provider-neutral and routing is observable. Provider-specific capabilities require adapters and tests. OpenAI-compatible does not imply identical behavior, so configurations must declare and validate capabilities.
