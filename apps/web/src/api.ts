import type { RunEvent, RunRecord } from './types';

const API_ROOT = import.meta.env.VITE_TASKPILOT_API_URL ?? '/api';

function apiToken(): string | null {
  try {
    return window.localStorage.getItem('taskpilot.apiToken');
  } catch {
    return null;
  }
}

export interface CreateRunInput {
  repository: string;
  task: string;
  max_repair_attempts: number;
  require_approval: boolean;
  require_write_approval: boolean;
  require_command_approval: boolean;
  model_profile?: string;
}

export interface ModelProfiles {
  default_profile: string;
  profiles: string[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = apiToken();
  const response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
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

export function getModelProfiles(): Promise<ModelProfiles> {
  return request('/model-profiles');
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

export async function streamEvents(
  runId: string,
  onEvent: (event: RunEvent) => void,
  signal: AbortSignal,
  after = 0,
): Promise<void> {
  const token = apiToken();
  const response = await fetch(`${API_ROOT}/runs/${runId}/events`, {
    signal,
    headers: {
      Accept: 'text/event-stream',
      ...(after ? { 'Last-Event-ID': String(after) } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
  if (!response.ok || !response.body) throw new Error(`Event stream returned ${response.status}`);
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = '';
  while (!signal.aborted) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += value;
    const frames = buffer.split('\n\n');
    buffer = frames.pop() ?? '';
    for (const frame of frames) {
      const data = frame
        .split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trimStart())
        .join('\n');
      if (data) onEvent(JSON.parse(data) as RunEvent);
    }
  }
}
