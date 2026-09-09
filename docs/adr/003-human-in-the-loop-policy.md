# ADR 003: Require plan approval by default

- Status: Accepted
- Date: 2026-08-28

## Context

Repository writes and command execution can be consequential, but asking for approval before every action creates fatigue and encourages blind acceptance.

## Decision

Interrupt once after planning, architecture review, and repository-impact analysis and before implementation. The payload must disclose files, commands, risks, and assumptions. Persist and audit every decision.

## Alternatives considered

- Fully autonomous execution improves speed but removes meaningful oversight.
- Approval for every tool call offers control but produces a poor default experience.
- Approval after implementation occurs too late to prevent unwanted writes.

## Consequences

The default has a useful safety/flow balance and resumes through a framework-native interrupt. Plans
must be sufficiently structured for informed approval. Deployments that need more control can enable
the independent write and command gates described in [ADR 009](009-multi-stage-approvals.md).
