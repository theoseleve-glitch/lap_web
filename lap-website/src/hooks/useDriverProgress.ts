/**
 * useDriverProgress — cached hook for gamification state (XP, level, streak, achievements).
 *
 * Fetches /account/progress once, caches 60s via TanStack React Query.
 * Used by the sidebar XP ring, dashboard gamification section, and any
 * component that needs to know the driver's level/streak/achievements.
 *
 * Separate from useUserPlan (which handles billing/quota) because
 * gamification data comes from a different backend table and can be
 * fetched independently.
 */

'use client';

import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api-client';

export interface DriverProgress {
  total_xp: number;
  level: number;
  xp_for_current_level: number;
  xp_for_next_level: number;
  current_streak: number;
  longest_streak: number;
  achievements: Array<{
    key: string;
    unlocked_at: string | null;
    session_id: string | null;
  }>;
  achievement_count: number;
}

async function fetchProgress(): Promise<DriverProgress> {
  return apiFetch<DriverProgress>('/account/progress');
}

export function useDriverProgress() {
  const query = useQuery({
    queryKey: ['driver-progress'],
    queryFn: fetchProgress,
    staleTime: 60_000,
    gcTime: 5 * 60_000,
    retry: (failureCount, error) => {
      if (error && typeof error === 'object' && 'status' in error && (error as any).status === 401) {
        return false;
      }
      return failureCount < 1;
    },
    refetchOnWindowFocus: false,
  });

  const p = query.data;

  return {
    ...query,
    progress: p,
    level: p?.level ?? 0,
    totalXp: p?.total_xp ?? 0,
    xpForCurrentLevel: p?.xp_for_current_level ?? 0,
    xpForNextLevel: p?.xp_for_next_level ?? 100,
    currentStreak: p?.current_streak ?? 0,
    longestStreak: p?.longest_streak ?? 0,
    achievementCount: p?.achievement_count ?? 0,
  };
}
