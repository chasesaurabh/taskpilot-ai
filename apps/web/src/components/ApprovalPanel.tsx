import { useState } from 'react';

export function ApprovalPanel({
  payload,
  onDecision,
}: {
  payload: Record<string, unknown>;
  onDecision: (action: 'approve' | 'reject', reason?: string) => void;
}) {
  const [reason, setReason] = useState('');
  const plan = payload.plan as { summary?: string; proposed_commands?: string[][] } | undefined;
  const kind = typeof payload.kind === 'string' ? payload.kind : 'plan';
  const headings: Record<string, string> = {
    plan: 'Review the implementation plan',
    write: 'Review before repository writes',
    command: 'Review before command execution',
  };
  const files = Array.isArray(payload.proposed_files) ? payload.proposed_files : [];
  const risks = Array.isArray(payload.risks) ? payload.risks : [];
  const commands = Array.isArray(payload.proposed_commands) ? payload.proposed_commands : [];
  return (
    <section className="approval-panel">
      <div className="approval-copy">
        <div className="eyebrow warning">Human checkpoint</div>
        <h2>{headings[kind] ?? 'Review before continuing'}</h2>
        <p>
          {(typeof payload.summary === 'string' && payload.summary) ||
            plan?.summary ||
            'Inspect the proposed action before continuing.'}
        </p>
        <div className="approval-evidence">
          <span>{files.length} proposed file(s)</span>
          <span>{commands.length} validation command(s)</span>
          <span>{risks.length} disclosed risk(s)</span>
        </div>
      </div>
      <input
        aria-label="Decision reason"
        placeholder="Optional decision note"
        value={reason}
        onChange={(event) => setReason(event.target.value)}
      />
      <div className="approval-actions">
        <button
          className="secondary danger"
          onClick={() => onDecision('reject', reason || undefined)}
        >
          Reject
        </button>
        <button className="primary" onClick={() => onDecision('approve', reason || undefined)}>
          Approve & continue
        </button>
      </div>
    </section>
  );
}
