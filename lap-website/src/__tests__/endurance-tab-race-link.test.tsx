/**
 * Tests for the "Create Race Strategy from this Session" action wired into
 * EnduranceTab — the endurance session → race-strategy bridge entry point.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { EnduranceTab } from '@/components/app/endurance/EnduranceTab';

const mockPush = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}));

const mockGet = vi.fn();
const mockPost = vi.fn();
vi.mock('@/lib/api-client', () => ({
  api: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
  },
}));

function renderWithClient(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe('EnduranceTab — create race from session', () => {
  beforeEach(() => {
    mockPush.mockReset();
    mockPost.mockReset();
    mockGet.mockReset();
  });

  it('shows the "Create Race Strategy" button once all stints have a driver assigned', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.includes('/stints')) {
        return Promise.resolve({
          stints: [
            { stint_number: 1, start_lap: 1, end_lap: 5, lap_count: 5, driver_name: 'Alice' },
            { stint_number: 2, start_lap: 7, end_lap: 11, lap_count: 5, driver_name: 'Bob' },
          ],
          pit_threshold_s: 120,
        });
      }
      return Promise.resolve(null);
    });

    renderWithClient(<EnduranceTab sessionId="sess-1" />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /create race strategy from this session/i })).toBeInTheDocument();
    });
  });

  it('posts the driver map built from stints and navigates to the new race on success', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.includes('/stints')) {
        return Promise.resolve({
          stints: [
            { stint_number: 1, start_lap: 1, end_lap: 5, lap_count: 5, driver_name: 'Alice' },
            { stint_number: 2, start_lap: 7, end_lap: 11, lap_count: 5, driver_name: 'Bob' },
          ],
          pit_threshold_s: 120,
        });
      }
      return Promise.resolve(null);
    });
    mockPost.mockResolvedValue({ race_id: 55 });

    renderWithClient(<EnduranceTab sessionId="sess-1" />);

    const button = await screen.findByRole('button', { name: /create race strategy from this session/i });
    fireEvent.click(button);

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        '/sessions/sess-1/endurance-race',
        expect.objectContaining({
          driver_map: { 1: 'Alice', 2: 'Bob' },
        }),
      );
    });
    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith('/app/race-strategy/55');
    });
  });
});
