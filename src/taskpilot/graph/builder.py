"""Construction of the TaskPilot LangGraph topology."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from taskpilot.graph.routing import (
    route_after_approval,
    route_after_command_approval,
    route_after_review,
    route_after_validation,
    route_after_write_approval,
)
from taskpilot.graph.state import WorkflowState, WorkflowUpdate

NodeFunction = Callable[[WorkflowState], WorkflowUpdate]


@dataclass(frozen=True, slots=True)
class WorkflowNodes:
    """Concrete node functions supplied by the application composition root."""

    repository_context: NodeFunction
    task_analysis: NodeFunction
    planning: NodeFunction
    architecture_review: NodeFunction
    repository_analysis: NodeFunction
    approval: NodeFunction
    implementation: NodeFunction
    testing: NodeFunction
    failure_analysis: NodeFunction
    repair: NodeFunction
    code_review: NodeFunction
    final_report: NodeFunction
    write_approval: NodeFunction | None = None
    apply_changes: NodeFunction | None = None
    command_approval: NodeFunction | None = None


def build_workflow(
    nodes: WorkflowNodes,
    *,
    checkpointer: Any | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Build the complete graph without coupling it to node implementations."""

    graph = StateGraph(WorkflowState)
    registered_nodes: tuple[tuple[str, NodeFunction], ...] = (
        ("repository_context", nodes.repository_context),
        ("task_analysis", nodes.task_analysis),
        ("planning", nodes.planning),
        ("architecture_review", nodes.architecture_review),
        ("repository_analysis", nodes.repository_analysis),
        ("approval", nodes.approval),
        ("implementation", nodes.implementation),
        ("testing", nodes.testing),
        ("failure_analysis", nodes.failure_analysis),
        ("repair", nodes.repair),
        ("code_review", nodes.code_review),
        ("final_report", nodes.final_report),
    )
    extended = all(
        node is not None
        for node in (nodes.write_approval, nodes.apply_changes, nodes.command_approval)
    )
    if extended:
        registered_nodes += (
            ("write_approval", cast(NodeFunction, nodes.write_approval)),
            ("apply_changes", cast(NodeFunction, nodes.apply_changes)),
            ("command_approval", cast(NodeFunction, nodes.command_approval)),
        )
    for name, node in registered_nodes:
        # LangGraph accepts partial state mappings at runtime, while its overload
        # currently expects a callable with a broader return type.
        graph.add_node(name, cast(Any, node))

    graph.add_edge(START, "repository_context")
    graph.add_edge("repository_context", "task_analysis")
    graph.add_edge("task_analysis", "planning")
    graph.add_edge("planning", "architecture_review")
    graph.add_edge("planning", "repository_analysis")
    graph.add_edge(["architecture_review", "repository_analysis"], "approval")
    graph.add_conditional_edges("approval", route_after_approval)
    if extended:
        graph.add_edge("implementation", "write_approval")
        graph.add_conditional_edges("write_approval", route_after_write_approval)
        graph.add_edge("apply_changes", "command_approval")
        graph.add_conditional_edges("command_approval", route_after_command_approval)
    else:
        graph.add_edge("implementation", "testing")
    graph.add_conditional_edges("testing", route_after_validation)
    graph.add_edge("failure_analysis", "repair")
    graph.add_edge("repair", "write_approval" if extended else "testing")
    graph.add_conditional_edges("code_review", route_after_review)
    graph.add_edge("final_report", END)
    return graph.compile(checkpointer=checkpointer)
