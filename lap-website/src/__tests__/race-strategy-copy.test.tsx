/**
 * Regression guard against stale pre-one-membership-migration entitlement
 * copy. The 'demo' tier / '4h_basic' limit no longer exist — the locked
 * floor is 0 hours (no access), racer is 24h, world-class is unlimited.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { useEntitlementsStore } from '@/lib/entitlements-store';

vi.mock('@tanstack/react-query', () => ({
  useQuery: () => ({ data: { races: [] }, isLoading: false, error: null, refetch: vi.fn() }),
  useMutation: () => ({ mutate: vi.fn(), isPending: false }),
  useQueryClient: () => ({ cancelQueries: vi.fn(), getQueryData: vi.fn(), setQueryData: vi.fn(), invalidateQueries: vi.fn() }),
}));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

import RaceStrategyListPage from '@/app/app/race-strategy/page';

describe('race-strategy list page — entitlement copy', () => {
  beforeEach(() => {
    useEntitlementsStore.getState().clear();
  });

  it('does not say "Demo plan" for a zero-access (raceStrategyLimit=none) user', () => {
    // Note: 'demo' is the frontend's declared backward-compat alias for the
    // backend's zero-access 'locked' floor (see entitlements-store.ts's
    // planTier type — 'locked' itself isn't declared there; that is a
    // separate, out-of-scope staleness this task does not touch). What this
    // test actually exercises is raceStrategyLimit, not planTier.
    useEntitlementsStore.getState().setEntitlements({
      planTier: 'demo',
      subscriptionStatus: 'active',
      analysesPerMonth: 10, analysesUsed: 0, analysesRemaining: 10,
      uploadVolumeMbPerMonth: 2500, uploadVolumeMbUsed: 0, uploadVolumeMbRemaining: 2500,
      apiAccess: false, comparisonEnabled: true, coachingPlansEnabled: true,
      visualizationEnabled: true, badgeShareCard: true, gamification: true,
      raceStrategyLimit: 'none',
      raceStrategyMaxDurationS: 0,
      raceStrategyParams: 'basic',
      optimizerModes: [],
      liveMonitoring: true,
      exportFormats: ['csv'],
      telemetryRetentionDays: 90,
      maxUploadSizeMb: 2500,
      maxSessionDataMb: 2500,
      maxConcurrentJobs: 1,
      rateMultiplier: 1,
      deviceSync: true,
      autoAnalyzeOnSync: false,
      maxLinkedDevices: 2,
    });

    render(<RaceStrategyListPage />);

    expect(screen.queryByText(/demo plan/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/4 hours/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/4h max/i)).not.toBeInTheDocument();
  });
});
