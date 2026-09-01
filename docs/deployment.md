# Authentication, artifacts, and isolated execution

## Owner authentication

Authentication is disabled when `TASKPILOT_AUTH_TOKENS` is empty, preserving the single-user local
experience. For a shared deployment, configure a JSON object whose keys are stable principal IDs.
Values may be long random bearer tokens or token/role objects:

```text
TASKPILOT_AUTH_TOKENS={"alice":{"token":"replace-with-random-secret","roles":["approver","admin"]},"build-bot":"replace-too"}
```

Send the selected value as `Authorization: Bearer <token>` or set `TASKPILOT_API_TOKEN` for the CLI.
The web client reads `taskpilot.apiToken` from browser local storage. Run creation records the owner;
listing, lookup, SSE, approval/rejection, and artifact downloads return only that owner's data.
Authenticated principals override user-supplied approval actor strings.

For production federation, install the `auth` extra and configure OIDC directly:

```text
TASKPILOT_OIDC_ISSUER=https://identity.example.com/
TASKPILOT_OIDC_AUDIENCE=taskpilot-api
TASKPILOT_OIDC_JWKS_URL=https://identity.example.com/.well-known/jwks.json
TASKPILOT_OIDC_ROLES_CLAIM=roles
TASKPILOT_APPROVAL_ROLE=approver
TASKPILOT_ADMIN_ROLE=admin
```

The API accepts only signed RS256 or ES256 access tokens, validates issuer, audience, `exp`, `iat`,
and `sub`, and refreshes signing keys through JWKS. The configured approval role is required for
approval decisions; the admin role grants `/admin/runs` and `/admin/runs/{run_id}/events`. Approval
authorization is written to the durable event log. Terminate TLS before the API and keep role
assignment in the identity provider.

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

## Separate API and graph workers

PostgreSQL deployments can queue work in API processes and claim it from independent workers. Use
the same database, checkpoint database, artifact store, policy, operation root, and repository mount
in every process:

```text
# API replicas
TASKPILOT_EXECUTION_MODE=api

# Worker replicas
TASKPILOT_EXECUTION_MODE=worker
TASKPILOT_WORKER_ID=worker-a
TASKPILOT_WORKER_LEASE_SECONDS=300
TASKPILOT_WORKER_POLL_SECONDS=0.5
taskpilot-worker
```

Run API replicas with `taskpilot-api` and worker replicas with `taskpilot-worker`. The worker entry
point does not open an HTTP listener. `all` combines a queue-producing API and a worker in one
`taskpilot-api` process. Workers claim one queued or
expired-running run under a database lease, renew the lease while the graph advances, and resume an
expired run from its durable checkpoint. PostgreSQL claims use row locking with skip-locked behavior;
SSE readers refresh from the durable event table so events created by another process become visible.
Run only one worker loop per process and give each worker a stable, unique ID.
