"""Human-friendly CLI for creating and controlling TaskPilot runs."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.json import JSON
from rich.table import Table

from taskpilot.cli.client import ApiClientError, SseEvent, TaskPilotClient

app = typer.Typer(
    name="taskpilot",
    no_args_is_help=True,
    help="Run observable, human-governed software engineering workflows.",
)
console = Console()

DEFAULT_API_URL = "http://127.0.0.1:8000"
TERMINAL_EVENTS = {"run.completed", "run.stopped", "run.failed"}


class ApprovalMode(StrEnum):
    ASK = "ask"
    APPROVE = "approve"
    STOP = "stop"


@app.command()
def run(
    repository: Annotated[
        Path,
        typer.Option("--repo", exists=True, file_okay=False, resolve_path=True),
    ],
    task: Annotated[str, typer.Option("--task", help="Engineering outcome to deliver.")],
    api_url: Annotated[str, typer.Option(envvar="TASKPILOT_API_URL")] = DEFAULT_API_URL,
    max_repairs: Annotated[int, typer.Option(min=0, max=10)] = 2,
    approval: Annotated[ApprovalMode, typer.Option()] = ApprovalMode.ASK,
    actor: Annotated[str, typer.Option(envvar="TASKPILOT_ACTOR")] = "local-developer",
) -> None:
    """Start a workflow and follow its replayable event stream."""

    try:
        with TaskPilotClient(api_url) as client:
            record = client.create_run(
                repository=str(repository),
                task=task,
                max_repair_attempts=max_repairs,
                require_approval=True,
            )
            run_id = str(record["run_id"])
            console.print(f"[bold]TaskPilot run[/bold] {run_id}")
            exit_code = _watch(client, run_id, approval=approval, actor=actor)
    except ApiClientError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    raise typer.Exit(exit_code)


@app.command()
def status(
    run_id: str,
    api_url: Annotated[str, typer.Option(envvar="TASKPILOT_API_URL")] = DEFAULT_API_URL,
) -> None:
    """Show the current durable run projection."""

    try:
        with TaskPilotClient(api_url) as client:
            record = client.get_run(run_id)
    except ApiClientError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    table = Table(show_header=False)
    for key in ("run_id", "status", "task", "repository", "created_at", "updated_at"):
        table.add_row(key.replace("_", " ").title(), str(record.get(key, "")))
    console.print(table)
    if record.get("final_report"):
        console.print(JSON.from_data(record["final_report"]))


@app.command()
def approve(
    run_id: str,
    actor: Annotated[str, typer.Option(envvar="TASKPILOT_ACTOR")] = "local-developer",
    reason: str | None = None,
    api_url: Annotated[str, typer.Option(envvar="TASKPILOT_API_URL")] = DEFAULT_API_URL,
) -> None:
    """Approve a waiting workflow and resume its saved graph thread."""

    _decision_command(run_id, "approve", actor, reason, api_url)


@app.command()
def reject(
    run_id: str,
    actor: Annotated[str, typer.Option(envvar="TASKPILOT_ACTOR")] = "local-developer",
    reason: Annotated[str | None, typer.Option(help="Why the plan was rejected.")] = None,
    api_url: Annotated[str, typer.Option(envvar="TASKPILOT_API_URL")] = DEFAULT_API_URL,
) -> None:
    """Reject a waiting workflow and produce a terminal engineering report."""

    _decision_command(run_id, "reject", actor, reason, api_url)


@app.command("events")
def events_command(
    run_id: str,
    after: Annotated[int, typer.Option(min=0)] = 0,
    api_url: Annotated[str, typer.Option(envvar="TASKPILOT_API_URL")] = DEFAULT_API_URL,
) -> None:
    """Follow persisted events, optionally from a known sequence."""

    try:
        with TaskPilotClient(api_url) as client:
            for event in client.events(run_id, after=after):
                _render_event(event)
    except ApiClientError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc


def _decision_command(
    run_id: str,
    action: str,
    actor: str,
    reason: str | None,
    api_url: str,
) -> None:
    try:
        with TaskPilotClient(api_url) as client:
            record = client.decide(
                run_id,
                action=action,
                actor=actor,
                reason=reason,
            )
    except ApiClientError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"[green]{action.title()} accepted.[/green] Run status: {record['status']}")


def _watch(
    client: TaskPilotClient,
    run_id: str,
    *,
    approval: ApprovalMode,
    actor: str,
) -> int:
    sequence = 0
    while True:
        reconnect = False
        for event in client.events(run_id, after=sequence):
            sequence = event.sequence
            _render_event(event)
            if event.event_type == "approval.required":
                if approval == ApprovalMode.STOP:
                    console.print(f"Resume with: taskpilot approve {run_id}")
                    return 0
                approved = approval == ApprovalMode.APPROVE or typer.confirm("Approve this plan?")
                action = "approve" if approved else "reject"
                reason = (
                    None if approved else typer.prompt("Rejection reason", default="Not approved")
                )
                client.decide(run_id, action=action, actor=actor, reason=reason)
                reconnect = True
                break
            if event.event_type in TERMINAL_EVENTS:
                outcome = str(event.data.get("data", {}).get("outcome", "failed"))
                return 0 if outcome in {"completed", "rejected"} else 1
        if not reconnect:
            record = client.get_run(run_id)
            return 0 if record.get("status") in {"completed", "rejected"} else 1


def _render_event(event: SseEvent) -> None:
    envelope = event.data
    node = envelope.get("node")
    data = envelope.get("data", {})
    if event.event_type == "node.started":
        console.print(f"[cyan]…[/cyan] {_label(str(node))}")
    elif event.event_type == "node.completed":
        console.print(f"[green]✓[/green] {_label(str(node))}")
    elif event.event_type in {"node.failed", "run.failed"}:
        console.print(f"[red]✗[/red] {_label(str(node or 'workflow'))}")
    elif event.event_type == "approval.required":
        console.print("\n[yellow]⏸ Human approval required[/yellow]")
        if isinstance(data, dict) and data.get("plan"):
            console.print(f"Plan: {data['plan'].get('summary', '')}")
    elif event.event_type in TERMINAL_EVENTS:
        outcome = data.get("outcome", event.event_type)
        console.print(f"[bold]Workflow {outcome}[/bold]")


def _label(node: str) -> str:
    labels = {
        "repository_context": "Repository context gathered",
        "task_analysis": "Change analyzed",
        "planning": "Implementation plan created",
        "architecture_review": "Architecture review completed",
        "repository_analysis": "Repository impact analyzed",
        "approval": "Approval recorded",
        "implementation": "Implementation completed",
        "testing": "Validation completed",
        "failure_analysis": "Failure analyzed",
        "repair": "Repair completed",
        "code_review": "Code review completed",
        "final_report": "Final report generated",
    }
    return labels.get(node, node.replace("_", " ").title())


if __name__ == "__main__":
    app()
