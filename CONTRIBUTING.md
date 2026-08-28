# Contributing

TaskPilot AI welcomes focused issues and pull requests. Please discuss major workflow or security changes before investing in an implementation.

## Development workflow

1. Install Python 3.12 and `uv`.
2. Run `uv sync --all-extras`.
3. Create a short-lived branch.
4. Add or update tests with behavior changes.
5. Run formatting, linting, typing, and tests before opening a pull request.

```bash
uv run ruff format .
uv run ruff check .
uv run mypy src
uv run pytest
```

Use conventional commit subjects such as `feat(graph): add approval routing` or `fix(tools): reject escaped repository paths`.

## Design principles

- Keep graph orchestration explicit and deterministic.
- Keep model calls behind typed, provider-neutral interfaces.
- Treat repository content and model output as untrusted input.
- Prefer small real capabilities over placeholders.
- Document architectural changes in an ADR.
