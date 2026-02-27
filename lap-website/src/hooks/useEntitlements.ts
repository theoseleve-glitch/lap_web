'use client';

import { useEffect, useCallback } from 'react';
import { api } from '@/lib/api-client';
import {
  useEntitlementsStore,
  canUseFeature,
  getRemainingQuota,
  getUpgradeInfo,
  type Entitlements,
} from '@/lib/entitlements-store';

/** Shape returned by GET /api/v1/me when entitlements are present. */
interface MeResponse {
  id: number;
  email: string;
  display_name: string;
  entitlements?: {
    plan_tier: string;
    subscription_status: string;
    reports_per_month: number | null;
    reports_used: number;
    reports_remaining: number | null;
    api_access: boolean;
    comparison_enabled: boolean;
    coaching_plans_enabled: boolean;
    visualization_enabled: boolean;
    race_strategy_limit: string | null;
    live_monitoring: boolean;
    export_formats: string[];
    telemetry_retention_days: number;
    max_upload_size_mb: number;
    max_concurrent_jobs: number;
    rate_multiplier: number;
  };
}

/** Convert snake_case API response to camelCase Entitlements. */
function mapEntitlements(raw: NonNullable<MeResponse['entitlements']>): Entitlements {
  return {
    planTier: raw.plan_tier as Entitlements['planTier'],
    subscriptionStatus: raw.subscription_status as Entitlements['subscriptionStatus'],
    reportsPerMonth: raw.reports_per_month,
    reportsUsed: raw.reports_used,
    reportsRemaining: raw.reports_remaining,
    apiAccess: raw.api_access,
    comparisonEnabled: raw.comparison_enabled,
    coachingPlansEnabled: raw.coaching_plans_enabled,
    visualizationEnabled: raw.visualization_enabled,
    raceStrategyLimit: raw.race_strategy_limit as Entitlements['raceStrategyLimit'],
    liveMonitoring: raw.live_monitoring,
    exportFormats: raw.export_formats ?? ['csv'],
    telemetryRetentionDays: raw.telemetry_retention_days ?? 30,
    maxUploadSizeMb: raw.max_upload_size_mb ?? 500,
    maxConcurrentJobs: raw.max_concurrent_jobs ?? 1,
    rateMultiplier: raw.rate_multiplier ?? 1.0,
  };
}

/**
 * Hook to access plan entitlements.
 *
 * Fetches from /api/v1/me on mount and caches in Zustand store.
 * Provides convenience methods for feature gating in components.
 */
export function useEntitlements() {
  const entitlements = useEntitlementsStore((s) => s.entitlements);
  const setEntitlements = useEntitlementsStore((s) => s.setEntitlements);

  useEffect(() => {
    // Only fetch if not already loaded
    if (entitlements) return;

    let cancelled = false;

    api
      .get<MeResponse>('/me')
      .then((data) => {
        if (cancelled) return;
        if (data.entitlements) {
          setEntitlements(mapEntitlements(data.entitlements));
        }
      })
      .catch(() => {
        // Fail silently — user may not be authenticated
      });

    return () => {
      cancelled = true;
    };
  }, [entitlements, setEntitlements]);

  const canUse = useCallback((feature: string) => canUseFeature(feature), []);

  const remainingQuota = useCallback(
    (key: string) => getRemainingQuota(key),
    [],
  );

  const requiresUpgrade = useCallback(
    (feature: string) => getUpgradeInfo(feature),
    [],
  );

  return {
    entitlements,
    isLoading: entitlements === null,
    canUse,
    remainingQuota,
    requiresUpgrade,
  };
}
