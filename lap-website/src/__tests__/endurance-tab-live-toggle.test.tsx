/**
 * Tests that EnduranceTab exposes a toggle for the previously-orphaned
 * EnduranceLivePanel (live elapsed-time tracking during an endurance race).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { EnduranceTab } from '@/components/app/endurance/EnduranceTab';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
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

describe('EnduranceTab — live tracking toggle', () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPost.mockReset();
  });

  it('shows a "Live Tracking" toggle button on the setup-flow (no-report) view', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.includes('/stints')) {
        return Promise.resolve({ stints: [], pit_threshold_s: 120 });
      }
      return Promise.resolve(null);
    });

    renderWithClient(<EnduranceTab sessionId="sess-1" />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /live tracking/i })).toBeInTheDocument();
    });
  });

  it('renders the live panel (race-start form) after clicking the toggle', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.includes('/endurance-live')) {
        return Promise.reject(Object.assign(new Error('not found'), { status: 404 }));
      }
      if (path.includes('/stints')) {
        return Promise.resolve({ stints: [], pit_threshold_s: 120 });
      }
      return Promise.resolve(null);
    });

    renderWithClient(<EnduranceTab sessionId="sess-1" />);

    const toggle = await screen.findByRole('button', { name: /live tracking/i });
    fireEvent.click(toggle);

    await waitFor(() => {
      // The phrase appears twice in the panel (heading + submit button); assert
      // the heading specifically so the matcher is unambiguous.
      expect(screen.getByRole('heading', { name: /start race tracking/i })).toBeInTheDocument();
    });
  });
});
