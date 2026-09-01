# ADR 012: Isolate repository commands in ephemeral containers

## Status

Accepted for v0.2.0.

## Decision

Preserve host execution for the local quick start and add an opt-in container backend for allowlisted
validation commands. The backend invokes the runtime without a shell, disables networking, drops
capabilities, enables `no-new-privileges`, limits CPU, memory, and PIDs, supplies a bounded temporary
filesystem, and mounts only the repository at `/workspace`.

## Consequences

Project-specific images must contain every allowed executable and should be digest-pinned. This
isolates repository processes, not graph orchestration, model calls, or guarded writes. Deployments
with hostile control-plane tenants still require separate graph workers or VMs.
