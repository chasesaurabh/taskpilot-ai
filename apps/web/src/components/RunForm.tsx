import { useState, type FormEvent } from 'react';
import type { CreateRunInput } from '../api';

const DEMO_REPOSITORY = import.meta.env.VITE_TASKPILOT_DEMO_REPOSITORY ?? './examples/sample-api';

export function RunForm({
  onSubmit,
  disabled,
}: {
  onSubmit: (value: CreateRunInput) => void;
  disabled: boolean;
}) {
  const [repository, setRepository] = useState(DEMO_REPOSITORY);
  const [task, setTask] = useState('Add pagination to the products endpoint and update tests');

  function submit(event: FormEvent) {
    event.preventDefault();
    onSubmit({ repository, task, max_repair_attempts: 2, require_approval: true });
  }

  return (
    <form className="run-form panel" onSubmit={submit}>
      <div>
        <div className="eyebrow">New engineering run</div>
        <h1>Move a change through delivery</h1>
      </div>
      <label>
        Repository
        <input
          value={repository}
          onChange={(event) => setRepository(event.target.value)}
          required
        />
      </label>
      <label className="task-field">
        Task
        <textarea
          value={task}
          onChange={(event) => setTask(event.target.value)}
          rows={3}
          required
        />
      </label>
      <button className="primary" disabled={disabled}>
        {disabled ? 'Starting…' : 'Start workflow'}
      </button>
    </form>
  );
}
