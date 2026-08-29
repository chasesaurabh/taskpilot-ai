# ADR 005: Expose repository capabilities, never a general shell

- Status: Accepted
- Date: 2026-08-28

## Context

An engineering orchestrator needs source access and validation commands. Repository content and model-produced paths or arguments may be malicious or simply wrong.

## Decision

Expose distinct read, write, and execute capabilities. Canonicalize every path under an allowed root, reject traversal and symlink escape, bound data, write atomically with hash preconditions, and execute argument arrays only when they match configured command prefixes. Never expose shell interpolation.

The application captures write preconditions from the repository context; models describe change
intent but never supply trust-sensitive hashes. See [ADR 007](007-write-precondition-ownership.md).

## Alternatives considered

- Unrestricted shell access is powerful but creates an unacceptable default blast radius.
- Read-only operation cannot deliver useful changes.
- Container-only execution is stronger isolation but would make the local quick start materially heavier; it remains an optional boundary.

## Consequences

Common engineering tasks remain possible with understandable controls. Some repository-specific commands require explicit configuration. These controls reduce accidental harm but do not make host execution safe for hostile repositories.
