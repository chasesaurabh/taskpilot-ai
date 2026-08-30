# Use TaskPilot on your repository

The default `docker compose up --build` experience is a deterministic demo operating on the sample
repository copied into the API image. Use the repository overlay when you want TaskPilot to work on
one Git repository from your machine with a configured model provider.

## Prerequisites

- Docker Engine or Docker Desktop with Compose.
- A trusted Git repository on a clean branch. The bind mount is writable.
- A model endpoint that supports the structured-output strategy configured in the policy.

## Configure

Create local files under `.taskpilot/`; the directory and `.env` are ignored by Git.

### macOS or Linux

```bash
mkdir -p .taskpilot
cp config.live.example.yaml .taskpilot/config.yaml
cp .env.example .env
```

Set these values in `.env`:

```dotenv
TASKPILOT_REPOSITORY_PATH=/absolute/path/to/your/repository
TASKPILOT_POLICY_PATH=./.taskpilot/config.yaml
OPENAI_API_KEY=replace-in-your-local-env-file
```

On Linux, also set `TASKPILOT_HOST_UID` and `TASKPILOT_HOST_GID` to the output of `id -u` and
`id -g`. The API image uses those IDs so files written through the bind mount remain owned by you.

### PowerShell

```powershell
New-Item -ItemType Directory -Force .taskpilot
Copy-Item config.live.example.yaml .taskpilot/config.yaml
Copy-Item .env.example .env
```

Set `TASKPILOT_REPOSITORY_PATH` in `.env` to the absolute Windows path shared with Docker Desktop,
then add the provider key used by `.taskpilot/config.yaml`.

Edit `.taskpilot/config.yaml` before starting:

- route all six roles to models available from the chosen provider;
- select the provider's supported `structured_output_method`;
- keep `allowed_commands` narrow; and
- set `validation_commands` to commands installed in the API image and valid for the repository.

The environment-provided repository root overrides `repository.allowed_roots` from the policy. Keys
remain in `.env`; `api_key_env` in YAML contains only the environment-variable name.

## Run

```bash
docker compose -f docker-compose.yml -f docker-compose.repository.yml up --build
```

Open `http://localhost:5173`. The repository field is prefilled with
`/workspace/repository`, the stable path inside the API container. Submit a task, review the plan,
files, commands, risks, and analysis, then approve or reject it. Stop the stack with `Ctrl+C` and
inspect the host repository with `git status` and `git diff`.

## Safety and toolchains

The overlay mounts exactly the configured repository, not its parent directory. A misspelled or
missing source path is rejected instead of being created automatically. After approval, file writes
are immediately reflected on the host.

Validation commands execute inside the API container. The standard image includes Python and the
dependencies used by the bundled sample. Repositories requiring Node.js, Java, Go, system packages,
or project-specific services need a derived API image or a Compose override that installs that
toolchain. An allowlisted test or build command still executes repository code; use only trusted
repositories or add external container/VM isolation.

## Troubleshooting

- **Permission denied on Linux:** set `TASKPILOT_HOST_UID=$(id -u)` and
  `TASKPILOT_HOST_GID=$(id -g)` in `.env`, then rebuild the API image.
- **Provider startup failure:** confirm the selected profile assigns every role and each
  `api_key_env` variable exists in `.env`.
- **Local endpoint is unreachable:** `localhost` inside the API container is the container itself.
  Use a host address reachable from Docker or put the inference service on the same Compose network.
- **Validation executable not found:** add the tool to a derived API image and keep the configured
  command prefix as narrow as possible.
- **Return to the demo:** run only `docker compose up --build`; the base stack does not mount the host
  repository or use the local provider policy.
