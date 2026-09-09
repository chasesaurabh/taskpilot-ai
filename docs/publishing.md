# Publishing releases

The `Publish release` workflow publishes the Python package to PyPI with OpenID Connect (OIDC)
Trusted Publishing and publishes two container images to GitHub Container Registry (GHCR):

- `ghcr.io/chasesaurabh/taskpilot-ai` for the API;
- `ghcr.io/chasesaurabh/taskpilot-ai-web` for the web UI.

No long-lived PyPI or registry tokens are required. The workflow builds from the immutable release
tag, checks that the Python and web versions match that tag, publishes the distributions, pushes
semantic-versioned container tags, and records GitHub artifact attestations for both images.

The repository's `pypi` GitHub environment and PyPI Trusted Publisher must remain restricted to
`release.yml`. Protect release tags and workflow changes as publishing credentials. The workflow
grants `id-token: write` to the PyPI publishing and container provenance jobs. Container jobs use
the repository-scoped `GITHUB_TOKEN` to push images and require no registry secret.

## Publish a release

1. Update `project.version` in `pyproject.toml`, `version` in `apps/web/package.json`,
   `__version__` in `src/taskpilot/__init__.py`, the FastAPI version in
   `src/taskpilot/api/app.py`, and the package-version test. Refresh `uv.lock` and the changelog.
2. Complete the release checks and merge the release commit.
3. Create and push a `v<version>` tag on that commit.
4. Publish the matching GitHub Release. Publishing the release starts the workflow automatically.

Stable releases receive container tags for the full version, the major/minor line, and `latest`.
Pre-releases receive version tags but do not move `latest`.

## Verify published artifacts

Replace `<version>` below with the release version, without a leading `v`:

```bash
python -m pip install "taskpilot-ai==<version>"
docker pull "ghcr.io/chasesaurabh/taskpilot-ai:<version>"
docker pull "ghcr.io/chasesaurabh/taskpilot-ai-web:<version>"
gh attestation verify \
  "oci://ghcr.io/chasesaurabh/taskpilot-ai:<version>" \
  --repo chasesaurabh/taskpilot-ai
gh attestation verify \
  "oci://ghcr.io/chasesaurabh/taskpilot-ai-web:<version>" \
  --repo chasesaurabh/taskpilot-ai
```

Publishing the same Python version twice is intentionally not supported. A failed or partially
completed run should be inspected before retrying; PyPI distributions are immutable once uploaded.
