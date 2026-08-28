import type { RunEvent, WorkflowNodeState } from '../types';
import { NODE_LABELS } from '../workflow';

function duration(state: WorkflowNodeState): string {
  if (!state.startedAt || !state.completedAt) return '—';
  return `${new Date(state.completedAt).getTime() - new Date(state.startedAt).getTime()} ms`;
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
        <pre>{JSON.stringify(update, null, 2)}</pre>
      ) : (
        <p className="muted">Select a completed node to inspect its structured output.</p>
      )}
      <h3>Model and tool calls</h3>
      {operations.length ? (
        <div className="operation-list">
          {operations.map((event) => (
            <div key={event.sequence}>
              <strong>
                {event.event_type === 'tool.completed'
                  ? String(event.data.tool)
                  : String(event.data.model)}
              </strong>
              <span>{event.event_type.replace('.', ' · ')}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="muted">No model or repository operations recorded for this node.</p>
      )}
      <p className="privacy-note">File content is redacted from public events by the API.</p>
    </aside>
  );
}
