# Live-model validation

The ordinary suite never makes paid model calls. Live validation is an explicit, provider-neutral
test of the same API, LangGraph, LangChain gateway, repository capabilities, approval interrupt,
validation commands, review, and final report used by the product.

## Configure a provider

Copy `config.live.example.yaml` to an ignored local file and select one provider configuration.
Never put a key value in YAML; `api_key_env` names the environment variable to read.

The committed example uses OpenAI. Equivalent model entries are:

```yaml
# Anthropic
provider: anthropic
model: <structured-output-capable-model>
api_key_env: ANTHROPIC_API_KEY

# Hosted OpenAI-compatible endpoint
provider: openai-compatible
model: <endpoint-model-name>
base_url: https://provider.example/v1
api_key_env: COMPATIBLE_API_KEY

# Local OpenAI-compatible inference
provider: local
model: <local-model-name>
base_url: http://localhost:11434/v1
local: true
```

All roles may point to one model for a reproducible first run. Role-specific assignments and ordered
routing rules can then be introduced without changing the graph. Put assignments under a named
profile and select it per run:

```yaml
routing:
  default_profile: primary
  profiles:
    primary:
      assignments:
        analyst: primary
        planner: primary
        architect: primary
        coder: primary
        reviewer: primary
        reporter: primary
```

TaskPilot validates every configured profile and required environment variable during startup. An
OpenAI-compatible endpoint may also use `max_tokens`, `organization_env`, `headers_from_env`, and a
non-secret `extra_body`. Set `structured_output_method` to `json_schema`, `function_calling`, or
`json_mode` when an endpoint requires a specific LangChain strategy. Header names are validated and
header values containing newlines are rejected. Do not put credentials inside `extra_body`.

For a compatible endpoint that cannot consume the OpenAI SDK's rewritten schema, set
`structured_output_method: json_schema` and set `structured_output_strict` explicitly. TaskPilot
then sends its standard JSON Schema unchanged and validates the returned object locally with
Pydantic. Use `true` when the server supports strict constrained decoding; use `false` only when it
accepts the schema but does not support strict mode.

Set `repository.validation_commands` to the safe commands TaskPilot should run when a planner does
not select commands. Every default command must match an `allowed_commands` argument prefix; an
invalid policy is rejected during startup.

## Run the opt-in scenarios

```bash
uv sync --all-extras
export OPENAI_API_KEY=...
export TASKPILOT_RUN_LIVE_TESTS=true
export TASKPILOT_LIVE_POLICY_FILE=./config.live.local.yaml
uv run pytest tests/live/test_live_workflow.py -m live -s
```

PowerShell uses `$env:NAME="value"`. Set `TASKPILOT_LIVE_SCENARIO=a` or `b` to run only one case.

- **Scenario A — straightforward:** add a product-by-ID endpoint, 404 behavior, and focused tests.
- **Scenario B — multi-file / repair-prone:** combine category filtering with bounded pagination and
  cover interactions, invalid parameters, empty results, and regression behavior.

Each successful test prints a `TASKPILOT_LIVE_RESULT` JSON record containing the selected models,
graph path, approval, repository tools, changed files, validation result, repair count, token usage
when reported by the provider, and total duration. Preserve that output with the release evidence;
do not commit credentials or raw provider requests.

## Validation status for v0.1.0 preparation

The harness is implemented and ordinary CI verifies that it remains collected but skipped. No live
provider run was executed during the repository audit because this environment had neither
`OPENAI_API_KEY` nor `ANTHROPIC_API_KEY`. A release candidate should record at least Scenario A on
the intended provider; Scenario B is strongly recommended.
