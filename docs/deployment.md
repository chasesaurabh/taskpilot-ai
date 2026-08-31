# Authentication, artifacts, and isolated execution

## Owner authentication

Authentication is disabled when `TASKPILOT_AUTH_TOKENS` is empty, preserving the single-user local
experience. For a shared deployment, configure a JSON object whose keys are stable principal IDs and
whose values are long random bearer tokens:

```text
TASKPILOT_AUTH_TOKENS={"alice":"replace-with-random-secret","build-bot":"replace-too"}
```

Send the selected value as `Authorization: Bearer <token>` or set `TASKPILOT_API_TOKEN` for the CLI.
The web client reads `taskpilot.apiToken` from browser local storage. Run creation records the owner;
listing, lookup, SSE, approval/rejection, and artifact downloads return only that owner's data.
Authenticated principals override user-supplied approval actor strings.

Opaque tokens are deliberately a compact self-hosted primitive, not an identity provider. Terminate
TLS before the API, inject values from a secret manager, rotate them operationally, and prefer an
OIDC-aware gateway when federation, expiry, revocation, or organization policy is required.

## Patch and validation artifacts

The default local backend writes immutable blob/metadata pairs below `.taskpilot/artifacts`:

```text
TASKPILOT_ARTIFACT_BACKEND=local
TASKPILOT_ARTIFACT_ROOT=.taskpilot/artifacts
```

For S3 or a compatible service, install the `artifacts` extra and configure:

```text
TASKPILOT_ARTIFACT_BACKEND=s3
TASKPILOT_ARTIFACT_S3_BUCKET=taskpilot-artifacts
TASKPILOT_ARTIFACT_S3_PREFIX=production
TASKPILOT_ARTIFACT_S3_ENDPOINT_URL=https://s3.example.com
TASKPILOT_ARTIFACT_S3_REGION=us-east-1
```

The standard AWS credential chain is used. Apply bucket encryption, retention, access logging, and
lifecycle rules appropriate for source patches and validation output. Each artifact event includes
its media type, size, SHA-256 digest, and owner-protected download path.

## Container command worker

Set the repository policy to container mode to keep validation processes off the API host:

```yaml
repository:
  execution_backend: container
  container_runtime: docker
  container_image: ghcr.io/example/project-validation:sha256-pinned-tag
  container_memory: 2g
  container_cpus: 2
```

TaskPilot invokes the runtime without a shell and preserves the configured command-prefix allowlist.
Each command gets a fresh container with networking disabled, all capabilities dropped,
`no-new-privileges`, PID/CPU/memory limits, a bounded temporary filesystem, and the repository mounted
at `/workspace`. The image must contain every allowlisted executable. Pin images by digest and treat
the writable repository mount as the only intended persistence boundary.

Container mode isolates repository commands. Graph orchestration, model calls, and guarded file writes
remain in the API process; deployments requiring hostile multi-tenant control-plane isolation should
add separate graph workers or VMs around the whole service.
