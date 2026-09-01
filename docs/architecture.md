# Architecture

## System context

TaskPilot AI is a single-installation developer platform that coordinates a software change inside an explicitly allowed Git repository. It separates deterministic workflow and policy from probabilistic model behavior.

```mermaid
flowchart LR
    User --> Web[React web application]
    User --> CLI[Typer CLI]
    Web --> API[FastAPI]
    CLI --> API
    API --> Service[Run application service]
    Service --> Graph[LangGraph StateGraph]
    Graph --> Gateway[LangChain model gateway]
    Graph --> Tools[Repository capability layer]
    Graph --> CP[(LangGraph checkpointer)]
    Service --> Store[(Run and event store)]
    Tools --> Repo[Allowed repository]
    Gateway --> Providers[Hosted or local models]
    Graph -. telemetry .-> Observe[Logs and LangSmith]
```

## Component boundaries

| Component | Owns | Does not own |
| --- | --- | --- |
| API | HTTP validation, lifecycle endpoints, SSE transport | Graph decisions or repository access |
| Application service | Run concurrency, graph invocation/resume, event publication | Prompt logic |
| LangGraph graph | State transitions, parallelism, interrupts, retry routing | Provider SDK details or arbitrary shell execution |
| Nodes | One engineering responsibility and typed state update | Cross-run persistence plumbing |
| Model gateway | Provider construction, structured output, usage normalization, routing | Workflow sequencing |
| Repository tools | Canonical paths, capabilities, bounded reads/writes/commands | Choosing what engineering change to make |
| Persistence | Checkpoints, run projections, append-only events | Business routing |
| Observability | Correlated logs, traces, timings, usage | Authoritative workflow state |

## Workflow

```mermaid
flowchart TD
    Start --> Context[Repository context]
    Context --> Analyze[Task analysis]
    Analyze --> Plan[Implementation plan]
    Plan --> Architecture[Architecture review]
    Plan --> Impact[Repository impact analysis]
    Architecture --> Approval{Human approval}
    Impact --> Approval
    Approval -->|approved| Implement[Propose implementation]
    Approval -->|rejected| Report[Final report]
    Implement --> WriteApproval{Write approval}
    WriteApproval -->|approved| Apply[Apply changes]
    WriteApproval -->|rejected| Report
    Apply --> CommandApproval{Command approval}
    CommandApproval -->|approved| Test[Validation]
    CommandApproval -->|rejected| Report
    Test -->|passed| Review[AI-assisted review]
    Test -->|failed and retry budget remains| Diagnose[Failure analysis]
    Diagnose --> Repair[Propose repair]
    Repair --> WriteApproval
    Test -->|retry budget exhausted| Report
    Review -->|blocking and budget remains| Repair
    Review -->|accepted or exhausted| Report
    Report --> End
```

Architecture and repository-impact analysis run in the same LangGraph superstep. The join waits for both updates before entering approval. Routing functions are deterministic: they inspect typed results, approval status, and counters; they do not ask a model where the graph should go.

## State model

The graph uses a versioned `WorkflowState` schema. Nodes return partial updates rather than mutating shared objects. State areas and owners are:

| State area | Primary writer | Lifecycle |
| --- | --- | --- |
| Run/task metadata and policy snapshot | run service | Immutable after start; lifecycle status lives in the run projection |
| Repository descriptor and context manifest | context node | Replaced when context is refreshed |
| Task analysis and plan | analysis/planning nodes | Stable after approval unless explicitly revised |
| Architecture and impact findings | parallel analysis nodes | Stable after join |
| Approval request and decisions | plan/write/command approval nodes | Append-only decisions |
| Proposed/applied changes | implementation/repair nodes | Replaced per attempt; applied records append |
| Validation and diagnosis | test/diagnosis nodes | Latest result plus bounded attempt summaries |
| Retry counters | deterministic routing nodes | Monotonic and policy bounded |
| Review findings | review node | Latest structured review |
| Model decisions and usage | model gateway | Append-only bounded summaries |
| Terminal outcome | report node | Set once after deterministic outcome evaluation |

Repository context stores file metadata and hashes rather than a full source snapshot. Proposed file contents and application-owned hash preconditions remain in the checkpoint so a write approval can resume safely, while the API redacts contents and exposes byte counts. Full patches and validation logs cross an artifact boundary into immutable local or S3-compatible objects; graph state and events retain only bounded summaries plus artifact references and digests.

## Execution lifecycle

```mermaid
sequenceDiagram
    actor User
    participant Client as CLI / Web
    participant API
    participant Runs as Run service
    participant Graph as LangGraph
    participant DB as Checkpoint + event stores
    participant Repo as Repository tools
    participant Model as Model gateway

    User->>Client: Submit repository and task
    Client->>API: POST /runs
    API->>Runs: Create run and start graph
    Runs->>Graph: astream(input, thread_id=run_id)
    Graph->>Repo: Gather bounded context
    Graph->>Model: Analyze and plan
    Graph->>DB: Checkpoint each superstep
    Graph-->>Runs: Interrupt with approval payload
    Runs->>DB: Persist waiting event
    API-->>Client: SSE waiting_for_approval
    User->>Client: Approve
    Client->>API: POST /runs/{id}/approve
    API->>Graph: Command(resume=decision)
    Graph->>Repo: Apply validated changes and run allowed tests
    alt tests fail and retries remain
        Graph->>Model: Diagnose failure and propose repair
        Graph->>Repo: Apply repair and retest
    end
    Graph->>Model: Review resulting diff
    Graph->>DB: Persist final checkpoint and events
    API-->>Client: SSE completed
```

## Persistence and resume

LangGraph checkpoints are authoritative for graph position and workflow state. The run store is a query-optimized projection for API status, timestamps, owner identity, and terminal outcome. The event store is append-only and provides monotonic sequence numbers for replayable SSE. Public event payloads are bounded and redact file content; immutable artifact objects retain full patches and command logs outside the checkpoint database.

Local mode uses async SQLite adapters. Production mode uses PostgreSQL implementations for LangGraph checkpoints, run projections, and the event log while retaining their logical separation. PostgreSQL event sequences are allocated under a transaction-scoped advisory lock; lifecycle transitions remain compare-and-set operations. Queue claims use row locking with skip-locked semantics and renewable leases. The run ID is also the LangGraph `thread_id`. Approval queues a resume of the same thread with `Command(resume=...)`, so duplicate approvals or competing workers cannot resume a graph twice.

The application captures file hashes before model invocation and supplies them to batch writes; the model never owns concurrency preconditions. A write operation preflights every change, stages replacements and rollback copies, and records a deterministic operation identity outside the repository before committing. A completed operation replays its stored result, while an interrupted command is marked uncertain and is never repeated automatically. Event publication uses idempotency keys, approval resume is guarded by a compare-and-set transition, and an expired graph-worker lease resumes from the durable checkpoint. A host failure during rollback or an uncertain external command remains an explicit operator-recovery case rather than an unsafe automatic retry.

## Model abstraction and routing

LangChain chat-model interfaces provide prompt composition, invocation, and structured output. TaskPilot adds a small `ModelGateway` around those interfaces to normalize provider construction, routing, token usage, and response errors. A configuration registry maps roles (`analyst`, `planner`, `architect`, `coder`, `reviewer`, `reporter`) to provider definitions. Repository capabilities are deliberately application-owned and are not exposed as model-selected LangChain tools.

Routing is explicit policy, not hidden model selection. Named profiles group a complete set of role assignments and ordered routing rules. The API validates an optional profile at run creation and stores the resolved name inside `WorkflowPolicy`, so the choice is checkpointed and cannot drift when an approval resumes. Each model decision records the profile, reason, provider, model, latency, and usage. Existing single-assignment configuration is normalized into a `default` profile.

The provider factory covers deterministic demo, OpenAI, Anthropic, and OpenAI-compatible endpoints. Local services can use the same compatible adapter when they implement the required chat and structured-output behavior. Credentials, organization identifiers, and custom header values are resolved from named environment variables. Static non-secret compatible-provider request fields may use bounded configuration fields such as `max_tokens` and `extra_body`. At startup, TaskPilot validates complete role coverage, model references, provider integration availability, required environment values, and the structured-model interface before accepting runs.

Repository context is selected with a deterministic lexical relevance score over paths and bounded
file content, using the task, objective, plan, or repair diagnosis as the query. Stable tie-breaking
keeps evaluations repeatable while avoiding the blind spots of alphabetical truncation. This is a
local retrieval layer, not an embedding service, so very large or semantically indirect codebases
may still benefit from a future indexed hybrid retriever.

## Repository tool security

Repository input and model output are untrusted. Every operation resolves paths against a canonical configured repository root and rejects absolute paths, traversal, escape through symlinks, oversized input, and unsupported encodings. Capabilities are separate:

- read: list, bounded file read, literal/regex search, Git status/diff;
- write: transactional create/replace batches of explicitly named files with precondition hashes;
- execute: argument-vector commands matched against configured prefixes.

There is no general shell tool. Commands do not use shell interpolation, inherit only an allowlisted environment, and have time and output limits. Independent policy flags can interrupt before each patch application and each validation-command batch. The optional container backend executes validation with no network, dropped capabilities, PID/CPU/memory limits, a temporary filesystem, and only the repository bind mount. Host execution remains the local default.

## Human approval

The default policy requires one approval after the plan and parallel architecture/impact analysis. Optional write and command policies add persisted interrupts after proposal generation but before patch application, and after patch application but before validation. Repairs pass through the same gates. Each request has a deterministic approval ID; decisions append to history, duplicate resumes lose a compare-and-set transition, and rejection terminates with an auditable report.

## Streaming

The graph emits typed internal events. The application service normalizes them into stable public events and persists each event before live publication. `GET /runs/{id}/events` uses Server-Sent Events and `Last-Event-ID` supports replay; bounded durable-store refresh makes events visible when another process writes them. Mutations remain ordinary HTTP requests. Opaque bearer tokens or OIDC identities owner-scope run lookup/listing, SSE, approvals, and artifact downloads. The authenticated subject becomes the approval actor, optional roles authorize approvals, and the admin role enables fleet-wide run/event inspection. A future `/v1` API will version the public schema before backward-incompatible changes are introduced.

## Failure recovery

Validation is deterministic: exit code, timeout, output truncation, and configured required commands determine pass or fail. A failed result enters diagnosis, then repair, then validation. The retry counter increments once per repair attempt and cannot exceed the policy snapshot. Exhaustion routes to a terminal `failed` report with the bounded final validation summary and stop reason. Unexpected node exceptions fail the run visibly and emit a typed error event. Independent workers recover expired leases from checkpoints; uncertain commands fail closed instead of being retried.

## Observability

Structured JSON logs bind request IDs at the HTTP boundary and run IDs around graph execution. Node start/completion/failure, normalized model decisions, repository operations, latency, token usage when reported, and terminal errors are also durable public events. LangSmith tracing is opt-in through configuration and complements rather than replaces application logs and state. Secrets and full proposed file contents are excluded from public events.

## Deployment model

Local development runs graph orchestration and SQLite in the API process, plus the Vite frontend. Docker Compose adds PostgreSQL and independently runnable API/web services. Production can split queue-producing API replicas from lease-based graph workers, with PostgreSQL checkpoints/events and shared artifact/operation storage. Opaque or OIDC principals isolate run metadata and artifacts; OIDC roles protect approval and administrative operations. Validation commands can additionally run in fresh, network-disabled containers.

## Major tradeoffs

- **Custom API over LangGraph Agent Server:** demonstrates and controls the application lifecycle, event schema, and security boundary; requires more persistence plumbing.
- **SSE over WebSockets:** simpler replay and operations for one-way progress; interactive token-by-token bidirectional sessions are out of scope.
- **Artifact references in state:** checkpoints and SSE remain bounded while local/S3 objects retain full evidence; operators must apply object-store lifecycle and encryption policy.
- **Embedded or leased orchestration:** embedded mode keeps local setup small; API/worker modes add durable queue claims and operational lease tuning for horizontal execution.
- **Allowlisted host processes:** practical for trusted development; hostile repositories require external isolation.
