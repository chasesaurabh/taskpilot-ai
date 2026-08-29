import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { RunForm } from './RunForm';

describe('RunForm model profiles', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('loads server profiles and submits the selected profile', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          default_profile: 'balanced',
          profiles: ['balanced', 'private'],
        }),
      }),
    );
    const onSubmit = vi.fn();
    render(<RunForm onSubmit={onSubmit} disabled={false} />);

    const profile = await screen.findByLabelText('Model profile');
    fireEvent.change(profile, { target: { value: 'private' } });
    fireEvent.click(screen.getByRole('button', { name: 'Start workflow' }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ model_profile: 'private' }));
  });
});
