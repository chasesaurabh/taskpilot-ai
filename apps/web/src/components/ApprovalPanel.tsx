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
  return (
    <section className="approval-panel">
      <div>
        <div className="eyebrow warning">Human checkpoint</div>
        <h2>Review before repository writes</h2>
        <p>{plan?.summary ?? 'Inspect the plan and node findings before continuing.'}</p>
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
