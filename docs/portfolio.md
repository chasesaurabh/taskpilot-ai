# Portfolio description

## One line

TaskPilot AI is a human-governed, LangGraph-based software-delivery orchestrator with durable
approval, constrained repository tools, observable model routing, and bounded validation/repair.

## Resume bullet options

- Built a typed LangGraph delivery workflow that coordinates parallel architecture/repository
  analysis, native human interrupts, durable SQLite/PostgreSQL checkpoints, conditional validation
  and review routing, and bounded repair across a FastAPI/SSE control plane.
- Designed a provider-neutral LangChain gateway and constrained repository capability layer with
  structured Pydantic outputs, observable model/token routing, application-owned optimistic write
  guards, shell-free command allowlists, restart-safe approval, and deterministic evaluation suites.

## LinkedIn project description

TaskPilot AI explores how to put deterministic governance around probabilistic software-engineering
models. An explicit LangGraph workflow moves a repository-scoped request through context, planning,
parallel reviews, human approval, implementation, validation, bounded repair, code review, and a
final report. LangChain keeps OpenAI, Anthropic, and OpenAI-compatible model plumbing outside the
graph. A FastAPI lifecycle API, replayable SSE, CLI, React Flow UI, SQLite/PostgreSQL persistence,
Docker demo, and security-focused repository tools make the workflow inspectable and defensible.
The project is a v0.1 portfolio system for one trusted developer—not a claim of production adoption
or hostile-code isolation.

## Core technologies

Python 3.12, LangGraph, LangChain, Pydantic, FastAPI, SQLite, PostgreSQL, SSE, Typer, React 19,
TypeScript, React Flow, Docker Compose, Ruff, mypy, pytest, Vitest, CodeQL, and GitHub Actions.

## Five interview talking points

1. Deterministic graph routing around probabilistic structured model calls.
2. Native `interrupt()`/`Command(resume=…)` with a tested full application restart.
3. Parallel analysis joined before an informed approval checkpoint.
4. A real repository-tool repair loop with bounded retries and no general shell.
5. Separation of checkpoint execution authority from the query/event projection used for SSE.
