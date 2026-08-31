# Publishing releases

The `Publish release` workflow publishes the Python package to PyPI with OpenID Connect (OIDC)
Trusted Publishing and publishes two container images to GitHub Container Registry (GHCR):

- `ghcr.io/chasesaurabh/taskpilot-ai` for the API;
- `ghcr.io/chasesaurabh/taskpilot-ai-web` for the web UI.

No long-lived PyPI or registry tokens are required. The workflow builds from the immutable release
tag, checks that the Python and web versions match that tag, publishes the distributions, pushes
semantic-versioned container tags, and records GitHub artifact attestations for both images.

## Current publication

Release `v0.1.0` is published on [PyPI](https://pypi.org/project/taskpilot-ai/0.1.0/) and GHCR. Its
[publishing run](https://github.com/chasesaurabh/taskpilot-ai/actions/runs/33351719786) completed all
package, image, and attestation jobs successfully. The PyPI publisher is active for `release.yml`
and the `pypi` GitHub environment.

## One-time configuration

1. In the GitHub repository, create an environment named exactly `pypi` under **Settings →
   Environments**. Add a required reviewer if releases should require a final approval.
2. In PyPI, add a
   [pending Trusted Publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
   for the first release of `taskpilot-ai`. Use these exact values:

   | PyPI field | Value |
   | --- | --- |
   | PyPI project name | `taskpilot-ai` |
   | Owner | `chasesaurabh` |
   | Repository name | `taskpilot-ai` |
   | Workflow name | `release.yml` |
   | Environment name | `pypi` |

   If the PyPI project already exists, add the same publisher under the project's **Publishing**
   settings instead.
3. Protect release tags matching `v*` with a GitHub repository ruleset. PyPI treats the authorized
   workflow as a credential, so tag creation and workflow changes should remain maintainer-only.

The workflow grants `id-token: write` only to the PyPI publishing job. Its only steps download the
already-built distributions and invoke PyPA's publishing action. The container jobs use the
repository-scoped `GITHUB_TOKEN`, with `packages: write`, and do not require a registry secret.

## v0.1.0 publication record

The GitHub Release for `v0.1.0` predates the workflow, so publishing the workflow file cannot
retroactively trigger its `release.published` event. It was published through the guarded manual
path with `v0.1.0` as the input. That path checked out `refs/tags/v0.1.0` explicitly and performed
the same version checks and publishing jobs as an automatic release. Both GHCR packages are public,
and the GitHub Release text links to PyPI and the versioned images.

## Publish future releases

1. Update both `project.version` in `pyproject.toml` and `version` in
   `apps/web/package.json`.
2. Complete the release checks and merge the release commit.
3. Create and push a `v<version>` tag on that commit.
4. Publish the matching GitHub Release. Publishing the release starts the workflow automatically.

Stable releases receive container tags for the full version, the major/minor line, and `latest`.
Pre-releases receive version tags but do not move `latest`.

## Verify published artifacts

Replace `0.1.0` below with the released version:

```bash
python -m pip install "taskpilot-ai==0.1.0"
docker pull ghcr.io/chasesaurabh/taskpilot-ai:0.1.0
docker pull ghcr.io/chasesaurabh/taskpilot-ai-web:0.1.0
gh attestation verify \
  oci://ghcr.io/chasesaurabh/taskpilot-ai:0.1.0 \
  --repo chasesaurabh/taskpilot-ai
gh attestation verify \
  oci://ghcr.io/chasesaurabh/taskpilot-ai-web:0.1.0 \
  --repo chasesaurabh/taskpilot-ai
```

Publishing the same Python version twice is intentionally not supported. A failed or partially
completed run should be inspected before retrying; PyPI distributions are immutable once uploaded.
