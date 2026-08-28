import type { RunRecord } from './types';

const API_ROOT = import.meta.env.VITE_TASKPILOT_API_URL ?? '/api';

export interface CreateRunInput {
  repository: string;
  task: string;
  max_repair_attempts: number;
  require_approval: boolean;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(payload.detail ?? `TaskPilot API returned ${response.status}`);
  }
  return (await response.json()) as T;
}

export function createRun(input: CreateRunInput): Promise<RunRecord> {
  return request('/runs', { method: 'POST', body: JSON.stringify(input) });
}

export function getRun(runId: string): Promise<RunRecord> {
  return request(`/runs/${runId}`);
}

export function decideRun(
  runId: string,
  action: 'approve' | 'reject',
  actor: string,
  reason?: string,
): Promise<RunRecord> {
  return request(`/runs/${runId}/${action}`, {
    method: 'POST',
    body: JSON.stringify({ actor, reason }),
  });
}

export function eventsUrl(runId: string): string {
  return `${API_ROOT}/runs/${runId}/events`;
}
