# Compatibility and upgrades

TaskPilot AI 1.0.0 establishes the stable interface for the existing developer workflow. Releases
follow Semantic Versioning: 1.x patch releases contain compatible fixes, minor releases may add
compatible functionality, and intentional breaking public-interface changes require a new major
version. Security fixes may tighten validation or reject previously accepted unsafe input.

## Supported public interface

- The documented HTTP endpoints, request fields, response fields, and public SSE event contracts.
- The documented CLI commands, flags, exit behavior, and machine-readable outputs.
- The documented environment variables, YAML configuration, and evaluation dataset fields.

Clients must tolerate additional response fields and ignore unfamiliar SSE event types. Human-readable
CLI wording, web layouts, model-generated plans and code, token usage, and model-provider behavior
are not fixed contracts. Internal Python modules, database tables, and serialized LangGraph
checkpoints are implementation details; access runs through the documented API and CLI.

## Upgrading

Version 1.0.0 introduces no intentional public-interface or database schema changes from 0.2.0.
The version promotion does not add a new checkpoint format. Back up repositories, databases, and
artifact storage together before an upgrade, and test restoration in a separate environment.

Stop accepting new work, let active runs finish, and resolve waiting approvals before stopping API
and worker processes. Upgrade all TaskPilot processes to the same version and restart them together.
Do not mix versions within a worker fleet. Validate the documented workflow on a disposable repository
before resuming normal work. Resuming in-flight checkpoints across different application or framework
versions is not a supported upgrade path.

Future 1.x releases that change persistent storage must document migration steps. Downgrades are not
guaranteed; restore the matching pre-upgrade backup and application version if rollback is required.

## Scope and support

The stable release supports trusted developer repositories and the documented deployment modes.
Whole-service isolation is still required for hostile repositories; version 1.0.0 does not expand
the security boundary described in [deployment](deployment.md) and the [security policy](../SECURITY.md).
Security maintenance applies to the latest stable 1.x release.
