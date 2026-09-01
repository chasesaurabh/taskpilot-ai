# v0.2.0 security review

## Boundary

TaskPilot is for one trusted developer operating on explicitly allowed repositories. It is not a
sandbox, tenant boundary, or safe way to execute a hostile repository. Validation commands execute
with the TaskPilot operating-system identity; containers or disposable VMs are required for hostile
code.

## Adversarial findings

| Threat | Implemented control | Residual risk |
| --- | --- | --- |
| Traversal, absolute paths, symlink escape | Canonical root checks on repository construction and every path operation; no symlink following during listing | Filesystem races are not defended as a hostile multi-user boundary. |
| Model-generated writes | Application-owned snapshot hashes, whole-batch preflight, staged replacements, rollback backups, persisted operation IDs, size limits, at most 25 files, duplicate-path rejection | A host failure during rollback can still require operator inspection of the affected files and operation journal. |
| Command or shell injection | Argument-vector subprocesses, executable basename requirement, configured prefix matching, `shell=False`, no stdin | An allowed test/build tool executes repository code and may accept consequential arguments. Treat the allowlist as code execution. |
| Environment/secret leakage | Child environment is reduced to process/runtime path variables; provider keys are excluded and tested | Repository code can still read files accessible to the OS user. Use external isolation for untrusted code. |
| Oversized input/output | Task, file, context, proposal-count, file-write, command-output, and timeout limits | Provider SDKs may allocate a response before Pydantic rejects an oversized structured field. Provider-side output limits remain deployment configuration. |
| Invalid/binary source | UTF-8-only reads and bounded binary-safe hashing | Non-UTF-8 source files are skipped and cannot be edited in v0.1.0. |
| Secret exposure through events | Proposed content is redacted before durable public events; exception normalization omits raw provider failures | Checkpoints intentionally contain proposed source content and must be protected as sensitive data. |
| Unsafe checkpoint deserialization | LangGraph serializer allowlists TaskPilot domain types | Database access remains a trusted administrative boundary. |
| Duplicate approval | Compare-and-set lifecycle transition before queueing/resuming, role authorization, durable audit event | A compromised identity-provider role assignment remains authoritative. |
| Crash during commands | Persist `started` before execution and replay only a persisted completed result | An uncertain command deliberately blocks automatic retry and requires operator resolution. |
| Competing graph workers | PostgreSQL skip-locked claims, renewable leases, expired-lease checkpoint recovery | Repository and operation storage must be shared consistently by all workers. |
| OIDC token forgery/replay | RS256/ES256 signature, JWKS rotation, exact issuer/audience, required expiry/issued-at/subject | Token revocation latency follows identity-provider and JWKS/cache policy. |

## Evidence

`tests/tools/test_repository.py` covers repository roots, traversal, absolute paths, symlinks when the
host permits them, UTF-8 rejection, file limits, guarded writes, command denial, timeout, output
limits, and provider-secret stripping. `tests/models/test_models.py` covers missing credentials,
malformed structured output, and sanitized provider failures. API tests cover duplicate decisions,
event replay, and proposal-content redaction.

Dependency audits run in CI for Python and production npm packages. CodeQL analyzes Python and
JavaScript/TypeScript. S3 and container boundaries run against real services in CI. These checks
supplement rather than replace the explicit threat-model tests.
