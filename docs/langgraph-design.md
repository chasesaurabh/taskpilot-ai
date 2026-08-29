# LangGraph and LangChain design

This document maps framework concepts to executable TaskPilot behavior. It is intentionally a
reviewer's guide, not a list of features added for demonstration.

## Why a graph

Software delivery has policy-visible phases, a parallel review join, a human pause, and two bounded
feedback routes. A free-running agent loop would hide these decisions inside prompts. TaskPilot uses
LangGraph for durable control flow and LangChain for provider-neutral model calls.

| Capability | Where | Why it is used |
| --- | --- | --- |
| `StateGraph` | `src/taskpilot/graph/builder.py` | Makes delivery stages and allowed transitions inspectable. |
| Typed state | `src/taskpilot/graph/state.py` | Gives every node a shared, versioned contract. |
| Partial updates | every function in `src/taskpilot/nodes/engineering.py` | Nodes return only the state they own instead of mutating a shared object. |
| Reducers | `model_decisions` and `node_history` in `graph/state.py` | Safely combine append-only updates, including one parallel superstep. |
| Conditional edges | `src/taskpilot/graph/routing.py` | Approval, validation, and review outcomes route deterministically. |
| Parallel execution | planning fan-out in `graph/builder.py` | Architecture and repository impact are independent reviews of one approved plan candidate. |
| Graph join | the two-source edge into `approval` | Approval is not offered until both parallel findings exist. |
| Loop | validation/review → diagnosis or repair → validation | Failed evidence returns to implementation without restarting planning. |
| Bounded retries | `repair_attempts` plus `WorkflowPolicy` | Prevents an unbounded probabilistic repair loop. |
| `interrupt()` | `EngineeringNodes.approval` | Persists an informed human checkpoint before repository writes or commands. |
| `Command(resume=…)` | `RunService.resume` | Continues the same saved graph thread with an audited decision. |
| Checkpoints and `thread_id` | `persistence/checkpoints.py`, `application/runs.py` | The run ID identifies the durable LangGraph execution across process restarts. |
| Streaming | `RunService._drive` | `updates` expose state transitions and `tasks` expose start/failure timing without leaking raw framework events to clients. |
| Failure handling | `RunService._drive`, graph routing | Provider/tool exceptions become terminal lifecycle events; validation failures use the repair graph. |

The parallel-execution test uses a two-party barrier, so it fails if the architecture and repository
branches run sequentially. The packaged restart test closes the API lifespan at approval, opens a
new application with the same SQLite run/checkpoint files, resumes the same run, and verifies that
pre-approval nodes are not repeated.

## LangChain boundary

LangChain owns prompt composition (`src/taskpilot/prompts/catalog.py`), chat-model construction
(`models/factory.py`), structured Pydantic output, runnable invocation, and provider usage metadata.
`ModelGateway` adds explicit TaskPilot role routing and a normalized decision record.

LangChain does **not** choose graph transitions. LangGraph does **not** know OpenAI, Anthropic, or
OpenAI-compatible constructor details. Repository capabilities are not model-selected LangChain
tools: TaskPilot applies structured change intent and validation commands through its own constrained
security boundary after deterministic policy checks.

## Durable-execution boundary

Checkpoints are authoritative for graph position and state; the run/event store is an API projection
and replay log. Compare-and-set status prevents duplicate approval from starting two resumes.
Approval-boundary restart/resume is proven for the packaged runtime.

This is not an exactly-once workflow engine. A crash inside a write-capable or command node can occur
after a side effect but before the next checkpoint. Hash preconditions, atomic replacement, bounded
commands, and event idempotency reduce risk, but hostile or horizontally scaled execution needs an
external isolated durable worker design.
