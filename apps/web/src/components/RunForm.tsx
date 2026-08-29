import { useEffect, useState, type FormEvent } from 'react';
import { getModelProfiles, type CreateRunInput, type ModelProfiles } from '../api';

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
  const [profiles, setProfiles] = useState<ModelProfiles>();
  const [modelProfile, setModelProfile] = useState('');

  useEffect(() => {
    void getModelProfiles()
      .then((configured) => {
        setProfiles(configured);
        setModelProfile(configured.default_profile);
      })
      .catch(() => setProfiles(undefined));
  }, []);

  function submit(event: FormEvent) {
    event.preventDefault();
    onSubmit({
      repository,
      task,
      max_repair_attempts: 2,
      require_approval: true,
      ...(modelProfile ? { model_profile: modelProfile } : {}),
    });
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
      {profiles && (
        <label>
          Model profile
          <select value={modelProfile} onChange={(event) => setModelProfile(event.target.value)}>
            {profiles.profiles.map((profile) => (
              <option key={profile} value={profile}>
                {profile === profiles.default_profile ? `${profile} (default)` : profile}
              </option>
            ))}
          </select>
        </label>
      )}
      <button className="primary" disabled={disabled}>
        {disabled ? 'Starting…' : 'Start workflow'}
      </button>
    </form>
  );
}
