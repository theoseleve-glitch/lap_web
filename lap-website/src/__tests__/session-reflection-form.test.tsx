import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const postMock = vi.fn();
vi.mock('@/lib/api-client', () => ({
  api: { post: (...args: unknown[]) => postMock(...args) },
}));

import { SessionReflectionForm } from '@/components/app/SessionReflectionForm';

beforeEach(() => postMock.mockReset().mockResolvedValue({ saved: true, competitors: 0 }));

describe('SessionReflectionForm', () => {
  it('submits selected tags and rating to the reflection endpoint', async () => {
    render(<SessionReflectionForm sessionId="s1" initial={null} onSaved={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: /traffic/i }));
    fireEvent.click(screen.getByRole('button', { name: /save reflection/i }));
    await waitFor(() => expect(postMock).toHaveBeenCalledTimes(1));
    const [path, payload] = postMock.mock.calls[0];
    expect(path).toBe('/sessions/s1/reflection');
    expect((payload as { result_tags: string[] }).result_tags).toContain('traffic');
  });

  it('prefills from initial reflection', () => {
    render(
      <SessionReflectionForm
        sessionId="s1"
        initial={{ result_tags: ['dnf'], felt_performance_rating: 6,
                   driver_perceived_conditions: 'damp', competitors: [] }}
        onSaved={() => {}}
      />,
    );
    expect(screen.getByRole('button', { name: /dnf/i })).toHaveAttribute('aria-pressed', 'true');
  });
});
