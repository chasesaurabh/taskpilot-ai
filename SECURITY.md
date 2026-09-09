# Security policy

## Reporting a vulnerability

Please report vulnerabilities through GitHub's private **Report a vulnerability** flow under the repository Security tab. Do not open a public issue for path-escape, command-execution, secret-disclosure, checkpoint-deserialization, or authorization weaknesses. Include the affected version, reproduction steps, impact, and any suggested mitigation. You should receive an acknowledgement within seven days.

## Supported versions

Until the first stable release, security fixes are applied to the latest commit on `main` only.

## Threat model

TaskPilot AI is a developer tool for explicitly allowed repositories. Owner-scoped authentication
supports shared deployments, but the service is not a hostile multi-tenant sandbox: graph workers
and guarded writes still have repository access.

Implemented safeguards include canonical repository roots, traversal and symlink-escape rejection,
bounded file/context/output sizes, hash-preconditioned transactional writes, persisted operation
identities, shell-free allowlisted process execution, stripped child-process environments, timeouts,
independent plan/write/command approval gates, owner-scoped opaque-token or OIDC authentication,
redacted public events, strict checkpoint type allowlisting, and optional isolated command containers.

Important deployment responsibilities:

- Keep unauthenticated local mode on a trusted interface. Shared deployments must enable opaque-token
  or OIDC authentication, terminate TLS, and restrict approval and administrator roles.
- Treat allowed commands as code execution. Review the allowlist, use the container backend where
  appropriate, and isolate the whole service from hostile repositories or tenants.
- Keep provider keys in environment-backed secret storage; never place them in YAML policy files or repository content.
- Protect and back up checkpoints, run/event data, operation journals, repositories, and artifact
  storage as one recovery boundary. Checkpoints can contain source proposals.
- Rotate the demonstration PostgreSQL password before adapting Compose to a shared environment.
- Inspect an interrupted command marked uncertain before retrying it; TaskPilot deliberately does
  not repeat an effect whose completion cannot be proven.

See [deployment and isolation](docs/deployment.md), the
[architecture security boundary](docs/architecture.md#repository-tool-security), and the
[repository tool ADR](docs/adr/005-repository-tool-security.md) for design details.

The current adversarial review and test coverage are recorded in
[docs/security-review.md](docs/security-review.md).
