/**
 * Tests for the session delete button and confirmation dialog.
 *
 * Covers:
 * - Delete button renders on the session detail page
 * - Confirmation dialog appears when delete is clicked
 * - Dialog can be cancelled
 * - API call fires on confirm
 * - Redirect to /app/sessions on success
 * - Error is shown on API failure
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { fireEvent, render, screen, waitFor, act, within } from '@testing-library/react';
import type { ReactNode } from 'react';

/* ── Mocks ────────────────────────────────────────────────────────── */

const pushMock = vi.fn();

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
  useParams: () => ({ id: '42' }),
  usePathname: () => '/app/sessions/42',
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock('next/link', () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string;
    children: ReactNode;
    [key: string]: unknown;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

// Mock auth-store so api-client's buildHeaders doesn't fail
vi.mock('@/lib/auth-store', () => ({
  getAccessToken: () => 'test-token',
  getWorkspaceId: () => null,
  setAccessToken: vi.fn(),
  setWorkspaceId: vi.fn(),
}));

// Track API calls made via the api helper
const deleteMock = vi.fn();
const getMock = vi.fn();

vi.mock('@/lib/api-client', () => ({
  api: {
    get: (...args: unknown[]) => getMock(...args),
    delete: (...args: unknown[]) => deleteMock(...args),
    post: vi.fn(),
    put: vi.fn(),
  },
  apiFetch: vi.fn(),
  BACKEND_URL: 'http://localhost:5000',
}));

// Mock TanStack React Query
vi.mock('@tanstack/react-query', () => {
  return {
    useQuery: ({ queryKey }: { queryKey: string[] }) => {
      // Return mock data for the session detail query
      if (queryKey[0] === 'session' && queryKey[1] === '42' && !queryKey[2]) {
        return {
          data: {
            id: '42',
            date: '2026-02-28',
            track_name: 'Monza',
            driver_name: 'Max Test',
            laps: 10,
            best_time: 62.345,
            mean_time: 63.012,
            score: 85,
            grade: 'A',
            consistency_score: 22,
            pace_score: 21,
            execution_score: 20,
            robustness_score: 22,
            session_type: 'Practice',
            condition: 'Dry',
            kart_name: null,
          },
          isLoading: false,
          error: null,
          refetch: vi.fn(),
        };
      }
      // Return mock laps data
      if (queryKey[2] === 'laps') {
        return {
          data: {
            laps: [
              { lap_number: 1, time: 63.5, speed_avg: 80, speed_max: 120, max_braking: 1.2, max_accel: 0.8, line_length: 5000, valid: true, is_best: false, phase_id: null },
              { lap_number: 2, time: 62.345, speed_avg: 82, speed_max: 122, max_braking: 1.3, max_accel: 0.9, line_length: 4980, valid: true, is_best: true, phase_id: null },
            ],
          },
          isLoading: false,
          error: null,
        };
      }
      // Return empty data for other queries
      return { data: null, isLoading: false, error: null };
    },
    QueryClient: vi.fn(),
    QueryClientProvider: ({ children }: { children: ReactNode }) => children,
  };
});

// Mock all chart components to prevent rendering complex SVGs in tests
vi.mock('@/components/app/charts', () => {
  const stub = () => null;
  return {
    SpeedTrace: stub,
    GGDiagram: stub,
    TrackMap: stub,
    DrivingStyle: stub,
    LapProgress: stub,
    SectorChart: stub,
    LapDistribution: stub,
    LapOverlay: stub,
    Fingerprint: stub,
    ConsistencyHeatmap: stub,
    BrakeScatter: stub,
    CornerMastery: stub,
    EnergyBalance: stub,
    FatigueChart: stub,
    SpeedProfile: stub,
    ThrottleHeatmap: stub,
    WorkloadChart: stub,
    TyreChart: stub,
    WeatherChart: stub,
    TrendChart: stub,
    StintChart: stub,
    PitWindowChart: stub,
    RivalChart: stub,
    ComparisonMatrix: stub,
  };
});

vi.mock('@/components/app/corner-replay', () => ({
  CornerReplay: () => null,
}));

vi.mock('@/components/app/focus-mode', () => ({
  FocusMode: () => null,
}));

/* ── Import page after mocks ──────────────────────────────────────── */

import SessionDetailPage from '@/app/app/sessions/[id]/page';

/* ── Tests ────────────────────────────────────────────────────────── */

describe('Session Delete', () => {
  beforeEach(() => {
    pushMock.mockReset();
    deleteMock.mockReset();
    getMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the delete button on the session detail page', () => {
    render(<SessionDetailPage />);
    const deleteBtn = screen.getByRole('button', { name: /delete session/i });
    expect(deleteBtn).toBeInTheDocument();
  });

  it('shows confirmation dialog when delete button is clicked', () => {
    render(<SessionDetailPage />);

    // Dialog should not be visible initially
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    // Click delete button
    const deleteBtn = screen.getByRole('button', { name: /delete session/i });
    fireEvent.click(deleteBtn);

    // Dialog should appear
    const dialog = screen.getByRole('dialog');
    expect(dialog).toBeInTheDocument();
    expect(screen.getByText(/are you sure you want to delete this session/i)).toBeInTheDocument();
    expect(screen.getByText(/this action cannot be undone/i)).toBeInTheDocument();
  });

  it('closes the dialog when cancel is clicked', () => {
    render(<SessionDetailPage />);

    // Open dialog
    fireEvent.click(screen.getByRole('button', { name: /delete session/i }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    // Click Cancel
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));

    // Dialog should close
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('calls api.delete with the correct session ID on confirm', async () => {
    deleteMock.mockResolvedValueOnce({ ok: true });

    render(<SessionDetailPage />);

    // Open dialog
    fireEvent.click(screen.getByLabelText('Delete session'));

    // Click the confirm button inside the dialog
    const dialog = screen.getByRole('dialog');
    const confirmBtn = within(dialog).getByRole('button', { name: /delete session/i });
    await act(async () => {
      fireEvent.click(confirmBtn);
    });

    expect(deleteMock).toHaveBeenCalledWith('/sessions/42');
  });

  it('redirects to /app/sessions on successful deletion', async () => {
    deleteMock.mockResolvedValueOnce({ ok: true });

    render(<SessionDetailPage />);

    // Open dialog and confirm
    fireEvent.click(screen.getByLabelText('Delete session'));
    const dialog = screen.getByRole('dialog');
    const confirmBtn = within(dialog).getByRole('button', { name: /delete session/i });
    await act(async () => {
      fireEvent.click(confirmBtn);
    });

    await waitFor(() => {
      expect(pushMock).toHaveBeenCalledWith('/app/sessions');
    });
  });

  it('shows error message when deletion fails', async () => {
    deleteMock.mockRejectedValueOnce(new Error('Permission denied'));

    render(<SessionDetailPage />);

    // Open dialog and confirm
    fireEvent.click(screen.getByLabelText('Delete session'));
    const dialog = screen.getByRole('dialog');
    const confirmBtn = within(dialog).getByRole('button', { name: /delete session/i });
    await act(async () => {
      fireEvent.click(confirmBtn);
    });

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
      expect(screen.getByText('Permission denied')).toBeInTheDocument();
    });

    // Dialog should close on error
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    // Should NOT redirect on failure
    expect(pushMock).not.toHaveBeenCalled();
  });

  it('shows "Deleting..." text while delete is in progress', async () => {
    // Create a promise we can control
    let resolveDelete: (value: unknown) => void;
    const deletePromise = new Promise((resolve) => {
      resolveDelete = resolve;
    });
    deleteMock.mockReturnValueOnce(deletePromise);

    render(<SessionDetailPage />);

    // Open dialog and confirm
    fireEvent.click(screen.getByLabelText('Delete session'));
    const dialog = screen.getByRole('dialog');
    const confirmBtn = within(dialog).getByRole('button', { name: /delete session/i });

    await act(async () => {
      fireEvent.click(confirmBtn);
    });

    // Should show "Deleting..." while in progress
    expect(screen.getByText('Deleting...')).toBeInTheDocument();

    // Resolve the delete
    await act(async () => {
      resolveDelete!({ ok: true });
    });
  });

  it('dismisses error alert when close button is clicked', async () => {
    deleteMock.mockRejectedValueOnce(new Error('Server error'));

    render(<SessionDetailPage />);

    // Trigger error
    fireEvent.click(screen.getByLabelText('Delete session'));
    const dialog = screen.getByRole('dialog');
    const confirmBtn = within(dialog).getByRole('button', { name: /delete session/i });
    await act(async () => {
      fireEvent.click(confirmBtn);
    });

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });

    // Dismiss the error
    const closeAlertBtn = screen.getByRole('alert').querySelector('button');
    expect(closeAlertBtn).toBeTruthy();
    fireEvent.click(closeAlertBtn!);

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
