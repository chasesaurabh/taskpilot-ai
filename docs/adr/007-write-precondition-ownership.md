# ADR 007: Keep write preconditions outside the model

- Status: Accepted
- Date: 2026-08-29

## Context

Repository writes need optimistic concurrency protection, but a language model cannot reliably
calculate a SHA-256 digest for prompt content. Requiring `expected_sha256` in structured model
output made the deterministic demo work while causing realistic provider output to fail guarded
writes.

## Decision

The model describes intent: path, create-or-replace operation, complete content, and rationale.
Immediately before model invocation, the engineering node captures a bounded repository context
and its hashes. The application validates that operations agree with that snapshot and supplies the
captured hash to the repository capability when it applies each change.

Proposals are bounded to 25 files and duplicate paths are rejected before the first write. A file
outside the bounded proposal context cannot be replaced; it must first be made visible through a
future context-selection improvement.

## Alternatives considered

- Asking the model for a digest is not dependable and confuses intent generation with concurrency
  control.
- Reading the hash only after model invocation would permit a concurrent edit during inference to
  become the model's accidental write baseline.
- Removing preconditions would make external edits vulnerable to silent overwrite.

## Consequences

Hosted and local providers use the same proposal schema as the deterministic demo. Concurrent edits
between context capture and write are rejected. Multi-file application is not transactional: an
error on a later file can still leave earlier validated writes applied, so review and disposable
worktrees remain important for consequential changes.
