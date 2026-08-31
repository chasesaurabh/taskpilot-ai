import type { RunEvent, WorkflowViewState } from './types';

export const NODE_IDS = [
  'repository_context',
  'task_analysis',
  'planning',
  'architecture_review',
  'repository_analysis',
  'approval',
  'implementation',
  'write_approval',
  'apply_changes',
  'command_approval',
  'testing',
  'failure_analysis',
  'repair',
  'code_review',
  'final_report',
] as const;

export const NODE_LABELS: Record<string, string> = {
  repository_context: 'Context',
  task_analysis: 'Analysis',
  planning: 'Plan',
  architecture_review: 'Architecture',
  repository_analysis: 'Repo impact',
  approval: 'Approval',
  implementation: 'Implement',
  write_approval: 'Approve write',
  apply_changes: 'Apply patch',
  command_approval: 'Approve command',
  testing: 'Validate',
  failure_analysis: 'Diagnose',
  repair: 'Repair',
  code_review: 'Review',
  final_report: 'Complete',
};

export function initialWorkflowState(): WorkflowViewState {
  return {
    nodes: Object.fromEntries(NODE_IDS.map((id) => [id, { status: 'pending' }])),
    events: [],
    selectedNode: 'repository_context',
  };
}

export function reduceWorkflowEvent(state: WorkflowViewState, event: RunEvent): WorkflowViewState {
  if (event.event_type === 'ui.selection') {
    return { ...state, selectedNode: event.node ?? state.selectedNode };
  }
  const nodes = { ...state.nodes };
  const nodeId = event.node;
  if (nodeId && nodes[nodeId]) {
    const previous = nodes[nodeId];
    if (event.event_type === 'node.started') {
      nodes[nodeId] = {
        ...previous,
        status: 'running',
        startedAt: event.created_at,
        latestEvent: event,
      };
    } else if (event.event_type === 'node.completed') {
      nodes[nodeId] = {
        ...previous,
        status: 'completed',
        completedAt: event.created_at,
        latestEvent: event,
      };
    } else if (event.event_type === 'node.failed') {
      nodes[nodeId] = { ...previous, status: 'failed', latestEvent: event };
    }
  }

  let approvalPayload = state.approvalPayload;
  if (event.event_type === 'approval.required') {
    const approvalNode = event.node ?? 'approval';
    nodes[approvalNode] = { ...nodes[approvalNode], status: 'waiting', latestEvent: event };
    approvalPayload = event.data;
  } else if (event.event_type === 'approval.decided') {
    const approvalNode = event.node ?? 'approval';
    nodes[approvalNode] = {
      ...nodes[approvalNode],
      status: 'completed',
      completedAt: event.created_at,
      latestEvent: event,
    };
    approvalPayload = undefined;
  } else if (event.event_type === 'run.failed') {
    const runningNode = Object.entries(nodes).find(([, value]) => value.status === 'running');
    if (runningNode) nodes[runningNode[0]] = { ...runningNode[1], status: 'failed' };
  } else if (['run.completed', 'run.stopped'].includes(event.event_type)) {
    for (const [id, node] of Object.entries(nodes)) {
      if (node.status === 'pending') nodes[id] = { ...node, status: 'skipped' };
    }
  }

  return { ...state, nodes, approvalPayload, events: [...state.events, event] };
}

export function modelUsage(events: RunEvent[]): { calls: number; input: number; output: number } {
  let calls = 0;
  let input = 0;
  let output = 0;
  for (const event of events) {
    const decisions = event.data.model_decisions;
    if (!Array.isArray(decisions)) continue;
    for (const decision of decisions) {
      if (!decision || typeof decision !== 'object') continue;
      calls += 1;
      const usage = decision as { input_tokens?: number; output_tokens?: number };
      input += usage.input_tokens ?? 0;
      output += usage.output_tokens ?? 0;
    }
  }
  return { calls, input, output };
}
