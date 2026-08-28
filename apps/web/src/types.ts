export type RunStatus =
  'queued' | 'running' | 'waiting_for_approval' | 'completed' | 'failed' | 'rejected';

export type NodeStatus = 'pending' | 'running' | 'completed' | 'failed' | 'waiting' | 'skipped';

export interface FinalReport {
  outcome: RunStatus;
  summary: string;
  changed_files: string[];
  validation_summary?: string;
  review_summary?: string;
  stop_reason?: string;
}

export interface RunRecord {
  run_id: string;
  task: string;
  repository: string;
  status: RunStatus;
  created_at: string;
  updated_at: string;
  approval?: Record<string, unknown>;
  final_report?: FinalReport;
}

export interface RunEvent {
  run_id: string;
  sequence: number;
  event_type: string;
  node?: string;
  data: Record<string, unknown>;
  created_at: string;
}

export interface WorkflowNodeState {
  status: NodeStatus;
  latestEvent?: RunEvent;
  startedAt?: string;
  completedAt?: string;
}

export interface WorkflowViewState {
  nodes: Record<string, WorkflowNodeState>;
  events: RunEvent[];
  selectedNode: string;
  approvalPayload?: Record<string, unknown>;
}
