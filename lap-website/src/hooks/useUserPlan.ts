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
    retry: (failureCount, error) => {
      // Don't retry auth failures — the user isn't logged in.
      if (error && typeof error === 'object' && 'status' in error && (error as any).status === 401) {
        return false;
      }
      return failureCount < 1;
    },
    refetchOnWindowFocus: false,
  });

  const plan = query.data;

  // Unlimited iff the backend sends null (the contract) or -1 (legacy
  // sentinel). A limit of 0 is NOT unlimited — that's the zero-access
  // 'locked' floor, which should correctly read as "0 remaining".
  const rawLimit = plan?.analyses.limit;
  const unlimited = plan != null && (rawLimit === null || rawLimit === -1);
  const normalizedLimit = rawLimit === -1 ? null : (rawLimit ?? null);

  return {
    ...query,
    plan,
    tier: plan?.plan_tier ?? 'locked',
    isUnlimited: unlimited,
    analysesRemaining: unlimited
      ? Infinity
      : normalizedLimit != null
        ? Math.max(0, normalizedLimit - (plan?.analyses.used ?? 0))
        : Infinity,
    analysesUsed: plan?.analyses.used ?? 0,
    analysesLimit: normalizedLimit,
    hasFeature: (feature: string) => plan?.features?.[feature] ?? false,
  };
}
