/** Tests the /admin/overview cockpit renders the 4 lenses from /admin/overview. */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const apiFetchMock = vi.fn();
vi.mock('@/lib/api-client', () => ({ apiFetch: (...a: unknown[]) => apiFetchMock(...a) }));

import AdminOverviewPage from '@/app/admin/overview/page';

function renderWithQuery(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe('Admin Overview cockpit', () => {
  it('renders the four lens headings and key metrics from the API', async () => {
    apiFetchMock.mockResolvedValue({
      business: { signups_total: 42, signups_7d: 4, active_subscribers: 7, trial_active: 3,
        founding_50_used: 7, churned_30d: 1, upload_volume_30d: 90 },
      product: { dau_today: 5, wau_7d: 11, total_events_30d: 300, unique_features_30d: 8,
        funnel: { upload: 6, analyze: 5, export: 2 } },
      live_ops: { jobs_active: 3, jobs_failed_24h: 0, jobs_completed_24h: 12, queue_backlog: 1,
        error_rate_5xx_pct: 0.0, p95_latency_ms: null },
      growth: { marketing_pageviews_7d: 1200, signup_clicked_7d: 30, pricing_viewed_7d: 80,
        demo_viewed_7d: 40, waitlist_submitted_7d: 10, waitlist_confirmed_7d: 6, download_clicked_7d: 0 },
      generated_at: '2026-06-08T00:00:00Z', cached: false,
    });

    renderWithQuery(<AdminOverviewPage />);

    expect(await screen.findByText(/Business Health/i)).toBeInTheDocument();
    expect(screen.getByText(/Product Usage/i)).toBeInTheDocument();
    expect(screen.getByText(/Live Ops/i)).toBeInTheDocument();
    expect(screen.getByText(/Growth/i)).toBeInTheDocument();
    // active_subscribers (7) and founding_50_used (7) both render "7";
    // findAllByText avoids the ambiguity while still asserting the value renders.
    expect((await screen.findAllByText('7')).length).toBeGreaterThan(0); // active_subscribers
    expect(await screen.findByText('1200')).toBeInTheDocument();     // marketing_pageviews_7d
    expect(apiFetchMock).toHaveBeenCalledWith('/admin/overview');
  });

  it('uses the lap_web token system (no forbidden text-white / bg-white)', () => {
    // Static guard: the source must not reintroduce the non-token classes that
    // page.tsx uses; lap_web/CLAUDE.md mandates concrete/steel/chalk tokens.
    const fs = require('node:fs');
    const path = require('node:path');
    const src = fs.readFileSync(
      path.join(process.cwd(), 'src', 'app', 'admin', 'overview', 'page.tsx'), 'utf8');
    expect(src).not.toMatch(/\btext-white\b/);
    expect(src).not.toMatch(/\bbg-white\//);
    expect(src).toMatch(/bg-concrete/);
    expect(src).toMatch(/text-chalk/);
  });
});
