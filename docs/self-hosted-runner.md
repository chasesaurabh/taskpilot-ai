# Self-hosted GitHub Actions runner

TaskPilot's CI and CodeQL workflows target the repository runner with these labels:

```text
self-hosted, Linux, X64
```

The runner must remain online and provide Git, Docker with Compose, and the system libraries needed
by GitHub's JavaScript actions. Python, `uv`, Node.js, and project dependencies are provisioned by
the workflows. The backend job uses a PostgreSQL service container, so the runner must be Linux and
the runner account must be able to access the Docker daemon.

## Security boundary

This is a public repository. Workflow jobs explicitly skip pull requests whose source repository is
a fork, preventing untrusted fork code from executing on the self-hosted machine. Pushes, scheduled
CodeQL scans, manual dispatches, and pull requests from branches in this repository may use the
runner. Review who can create repository branches and manually dispatch workflows accordingly.

Use an isolated, non-privileged runner account; do not store unrelated credentials or personal data
on the runner host. Keep the GitHub runner current and use an ephemeral or disposable host when the
threat model requires stronger isolation.

## Maintenance

- Keep the standard `self-hosted`, `Linux`, and `X64` labels on the intended runner.
- Keep Docker running and periodically prune build cache according to host capacity.
- Confirm runner availability under repository **Settings → Actions → Runners**.
- Use the CI workflow's manual dispatch after runner maintenance to verify all capabilities.
