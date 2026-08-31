import { describe, expect, it } from 'vitest';
import type { RunEvent } from './types';
import { initialWorkflowState, modelUsage, reduceWorkflowEvent } from './workflow';

function event(event_type: string, node?: string, data: Record<string, unknown> = {}): RunEvent {
  return {
    run_id: 'run-1',
    sequence: 1,
    event_type,
    node,
    data,
    created_at: '2026-08-28T12:00:00Z',
  };
}

describe('workflow event projection', () => {
  it('projects node lifecycle and approval waiting state', () => {
    let state = initialWorkflowState();
    state = reduceWorkflowEvent(state, event('node.started', 'planning'));
    expect(state.nodes.planning.status).toBe('running');

    state = reduceWorkflowEvent(state, event('node.completed', 'planning', { plan: {} }));
    expect(state.nodes.planning.status).toBe('completed');

    state = reduceWorkflowEvent(state, event('approval.required', 'approval', { plan: {} }));
    expect(state.nodes.approval.status).toBe('waiting');
    expect(state.approvalPayload).toEqual({ plan: {} });

    state = reduceWorkflowEvent(
      state,
      event('approval.required', 'write_approval', { kind: 'write' }),
    );
    expect(state.nodes.write_approval.status).toBe('waiting');
  });

  it('aggregates normalized model usage from node updates', () => {
    const usage = modelUsage([
      event('node.completed', 'planning', {
        model_decisions: [{ input_tokens: 120, output_tokens: 40 }],
      }),
      event('node.completed', 'code_review', {
        model_decisions: [{ input_tokens: 80, output_tokens: 20 }],
      }),
    ]);

    expect(usage).toEqual({ calls: 2, input: 200, output: 60 });
  });

  it('marks unvisited branches as skipped when a run completes', () => {
    let state = initialWorkflowState();
    state = reduceWorkflowEvent(state, event('node.completed', 'testing'));
    state = reduceWorkflowEvent(state, event('node.completed', 'code_review'));
    state = reduceWorkflowEvent(state, event('node.completed', 'final_report'));
    state = reduceWorkflowEvent(state, event('run.completed'));

    expect(state.nodes.failure_analysis.status).toBe('skipped');
    expect(state.nodes.repair.status).toBe('skipped');
    expect(state.nodes.final_report.status).toBe('completed');
  });
});
