# Security policy

## Reporting a vulnerability

Please report vulnerabilities through GitHub's private **Report a vulnerability** flow under the repository Security tab. Do not open a public issue for path-escape, command-execution, secret-disclosure, checkpoint-deserialization, or authorization weaknesses. Include the affected version, reproduction steps, impact, and any suggested mitigation. You should receive an acknowledgement within seven days.

## Supported versions

Until the first stable release, security fixes are applied to the latest commit on `main` only.

## Threat model

TaskPilot AI is designed for a trusted developer operating on explicitly allowed repositories. It is not a sandbox for hostile source trees and is not currently a multi-tenant service.

Implemented safeguards include canonical repository roots, traversal and symlink-escape rejection, bounded file/context/output sizes, hash-preconditioned atomic writes, fixed Git inspection commands, shell-free allowlisted process execution, stripped child-process environments, timeouts, explicit plan approval, redacted public events, strict checkpoint type allowlisting, and non-root containers.

Important deployment responsibilities:

- The API has no built-in authentication or authorization. Keep it on a trusted network or place it behind an authenticated reverse proxy.
- Treat allowed commands as code execution. Review the allowlist and use disposable workers for untrusted repositories.
- Keep provider keys in environment-backed secret storage; never place them in YAML policy files or repository content.
- Protect and back up PostgreSQL because checkpoints can contain source proposals and operational metadata.
- Rotate the demonstration PostgreSQL password before adapting Compose to a shared environment.

See the [architecture security boundary](docs/architecture.md#repository-tool-security) and [repository tool ADR](docs/adr/005-repository-tool-security.md) for design details.
