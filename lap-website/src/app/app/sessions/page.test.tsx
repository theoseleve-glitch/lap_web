import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactElement } from 'react';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => '/app/sessions',
}));

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) =>
    // eslint-disable-next-line @next/next/no-html-link-for-pages
    <a href={href}>{children}</a>,
}));

import SessionsPage from './page';

function renderWithClient(ui: ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const envelope = (data: unknown) => ({ ok: true, data, error: null, meta: {} });

const listResponse = envelope({
  sessions: [
    {
      session_id: 's1',
      session_date: '2026-04-01T12:00:00Z',
      track_name: 'Franciacorta',
      driver_name: 'Demo',
      n_laps: 10,
      best_lap_time_s: 52.1,
      mean_lap_time_s: 52.8,
      total_score: 80,
      grade: 'A',
      session_type: 'practice',
      track_state: 'dry',
      source: 'real_life',
    },
  ],
  total: 1,
  limit: 25,
  offset: 0,
});

describe('SessionsPage header', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const body = url.includes('filter-options')
          ? envelope({ drivers: [], tracks: [], session_types: [], track_states: [] })
          : listResponse;
        return new Response(JSON.stringify(body), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        });
      }),
    );
  });

  it('renders the Upload button and a Source column header', async () => {
    renderWithClient(<SessionsPage />);
    expect(screen.getAllByRole('link', { name: /upload session/i }).length).toBeGreaterThan(0);
    const header = await screen.findByRole('columnheader', { name: /source/i });
    expect(header).toBeInTheDocument();
  });
});
