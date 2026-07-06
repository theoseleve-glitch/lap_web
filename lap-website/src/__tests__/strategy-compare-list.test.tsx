/**
 * Tests for StrategyCompareList — surfaces optimizer.multi_strategy's ranked
 * strategy comparison at the pre-race planning stage (draft/ready races),
 * not just inside the live-race rain-scenario modal.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StrategyCompareList } from '@/components/app/race-strategy/StrategyCompareList';

const mockPost = vi.fn();
vi.mock('@/lib/api-client', () => ({
  api: {
    post: (...args: unknown[]) => mockPost(...args),
  },
}));

function renderWithClient(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const MOCK_STRATEGIES = {
  strategies: [
    {
      name: 'Stay Out',
      description: 'Ignore rain — keep driving the original plan',
      approach: 'stay_out',
      score: 42.5,
      stints: [{ stint_order: 1, driver_id: 1, driver_name: 'Alice', start_s: 0, duration_s: 3600 }],
      metrics: {
        pits_in_rain: 0, pits_in_dry: 2, rain_drive_s: 0, dry_drive_s: 10800,
        driver_transitions: 1, min_stint_s: 3000, max_stint_s: 3600,
        flexibility_score: 0.8, risk_score: 0.2, total_pit_s: 240,
      },
    },
  ],
};

describe('StrategyCompareList', () => {
  beforeEach(() => {
    mockPost.mockReset();
  });

  it('shows the Compare Strategies button initially', () => {
    renderWithClient(<StrategyCompareList raceId={7} />);
    expect(screen.getByRole('button', { name: /compare strategies/i })).toBeInTheDocument();
  });

  it('fetches and renders ranked strategies on click', async () => {
    mockPost.mockResolvedValueOnce(MOCK_STRATEGIES);
    renderWithClient(<StrategyCompareList raceId={7} />);

    fireEvent.click(screen.getByRole('button', { name: /compare strategies/i }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/race-strategy/7/strategies', {});
    });
    await waitFor(() => {
      expect(screen.getByText('Stay Out')).toBeInTheDocument();
      expect(screen.getByText(/score: 42.5/i)).toBeInTheDocument();
    });
  });

  it('applies the selected strategy', async () => {
    mockPost.mockResolvedValueOnce(MOCK_STRATEGIES);
    mockPost.mockResolvedValueOnce({ ok: true });
    renderWithClient(<StrategyCompareList raceId={7} />);

    fireEvent.click(screen.getByRole('button', { name: /compare strategies/i }));
    await screen.findByText('Stay Out');

    fireEvent.click(screen.getByRole('button', { name: /apply this strategy/i }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/race-strategy/7/apply-strategy', {
        stints: MOCK_STRATEGIES.strategies[0].stints,
      });
    });
  });
});
