# ADR 001: Use LangGraph for workflow orchestration

- Status: Accepted
- Date: 2026-08-28

## Context

The product needs explicit stages, parallel analysis, conditional routes, bounded repair loops, human pauses, durable state, and streaming. A free-running agent loop would hide control flow and make recovery difficult.

## Decision

Use LangGraph `StateGraph` as the orchestration runtime. Keep routing functions deterministic and put model/tool abstractions in LangChain-backed components.

## Alternatives considered

- A hand-written workflow engine offers control but would recreate checkpoint, interrupt, and stream semantics.
- A generic durable workflow platform such as Temporal is operationally strong but does not provide model-native graph state and would obscure the portfolio focus.
- A single LangChain agent loop is simpler but cannot make delivery policy and bounded recovery sufficiently explicit.

## Consequences

The execution graph is inspectable and testable, and durable AI-specific workflows use framework-native mechanisms. The project accepts LangGraph API evolution and still needs an application-level run/event model around graph checkpoints.
