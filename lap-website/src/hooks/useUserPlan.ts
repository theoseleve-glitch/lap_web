/**
 * useUserPlan — cached hook for plan tier + usage/quota info.
 *
 * Fetches /account/usage once, caches via TanStack React Query with a
 * 60-second stale time. Every component that needs plan/quota info
 * (upload page, dashboard, session header, feature gates) shares this
 * single cached fetch — no repeated API calls.
 */

'use client';

import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api-client';

export interface UsageMetric {
  used: number;
  limit: number | null;  // null = unlimited
  resets: string | null;  // ISO date of next reset
}

export interface UserPlan {
  plan_tier: string;
  subscription_status: string;
  analyses: UsageMetric;
  upload_volume_mb?: UsageMetric;
  features: Record<string, boolean>;
}

async function fetchUsage(): Promise<UserPlan> {
  return apiFetch<UserPlan>('/account/usage');
}

export function useUserPlan() {
  const query = useQuery({
    queryKey: ['user-plan'],
    queryFn: fetchUsage,
    staleTime: 60_000,        // 60s — re-fetch at most once per minute
    gcTime: 5 * 60_000,       // keep in cache 5 min after last subscriber
    retry: 1,
    refetchOnWindowFocus: false,
  });

  const plan = query.data;

  return {
    ...query,
    plan,
    tier: plan?.plan_tier ?? 'demo',
    isUnlimited: (plan?.analyses.limit ?? 0) === 0 && plan?.plan_tier !== 'demo',
    analysesRemaining:
      plan?.analyses.limit != null
        ? Math.max(0, plan.analyses.limit - plan.analyses.used)
        : Infinity,
    analysesUsed: plan?.analyses.used ?? 0,
    analysesLimit: plan?.analyses.limit ?? null,
    hasFeature: (feature: string) => plan?.features?.[feature] ?? false,
  };
}
