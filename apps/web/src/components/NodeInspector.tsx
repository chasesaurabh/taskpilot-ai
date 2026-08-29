import type { RunEvent, WorkflowNodeState } from '../types';
import { NODE_LABELS } from '../workflow';

function duration(state: WorkflowNodeState): string {
  if (!state.startedAt || !state.completedAt) return '—';
  return `${new Date(state.completedAt).getTime() - new Date(state.startedAt).getTime()} ms`;
}

function number(value: unknown): string {
  return typeof value === 'number' ? value.toLocaleString() : '—';
}

function Operation({ event }: { event: RunEvent }) {
  if (event.event_type === 'model.completed') {
    return (
      <div className="operation-card">
        <div className="operation-heading">
          <strong>{String(event.data.role ?? 'model')}</strong>
          <span>{number(event.data.latency_ms)} ms</span>
        </div>
        <p>
          {String(event.data.provider ?? 'provider')} · {String(event.data.model ?? 'model')}
        </p>
        <small>
          {number(event.data.input_tokens)} in · {number(event.data.output_tokens)} out
        </small>
      </div>
    );
  }
  const tool = String(event.data.tool ?? 'repository tool');
  const passed = event.data.passed;
  const changes = event.data.changes;
  return (
    <div className="operation-card">
      <div className="operation-heading">
        <strong>{tool}</strong>
        {typeof passed === 'boolean' && (
          <span className={passed ? 'text-completed' : 'text-failed'}>
            {passed ? 'passed' : 'failed'}
          </span>
        )}
      </div>
      <p>{String(event.data.summary ?? 'Constrained repository operation')}</p>
      <small>
        {Array.isArray(changes) ? `${changes.length} file change(s)` : `event #${event.sequence}`}
      </small>
    </div>
  );
}

export function NodeInspector({
  nodeId,
  state,
  events,
}: {
  nodeId: string;
  state: WorkflowNodeState;
  events: RunEvent[];
}) {
  const update = state.latestEvent?.data ?? {};
  const operations = events.filter(
    (event) =>
      event.node === nodeId && ['model.completed', 'tool.completed'].includes(event.event_type),
  );
  return (
    <aside className="inspector panel">
      <div className="eyebrow">Node inspector</div>
      <h2>{NODE_LABELS[nodeId] ?? nodeId}</h2>
      <div className="inspector-metrics">
        <div>
          <span>Status</span>
          <strong className={`text-${state.status}`}>{state.status}</strong>
        </div>
        <div>
          <span>Duration</span>
          <strong>{duration(state)}</strong>
        </div>
        <div>
          <span>Event</span>
          <strong>#{state.latestEvent?.sequence ?? '—'}</strong>
        </div>
      </div>
      <h3>State update</h3>
      {Object.keys(update).length ? (
        <details>
          <summary>Inspect structured node output</summary>
          <pre>{JSON.stringify(update, null, 2)}</pre>
        </details>
      ) : (
        <p className="muted">Select a completed node to inspect its structured output.</p>
      )}
      <h3>Model and tool calls</h3>
      {operations.length ? (
        <div className="operation-list">
          {operations.map((event) => (
            <Operation key={event.sequence} event={event} />
          ))}
        </div>
      ) : (
        <p className="muted">No model or repository operations recorded for this node.</p>
      )}
      <p className="privacy-note">File content is redacted from public events by the API.</p>
    </aside>
  );
}
