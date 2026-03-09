/**
 * DriverAchievements.tsx — Driver career milestone badges.
 *
 * Fetches and displays earned/in-progress achievement badges.
 */
'use client';

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';

interface Achievement {
  id: string;
  label: string;
  description: string;
  threshold: number;
  current_value: number;
  earned: boolean;
  progress_pct: number;
}

interface AchievementsResponse {
  achievements: Achievement[];
  earned_count: number;
  total_count: number;
  in_progress: Achievement[];
}

const TIER_ICONS: Record<string, string> = {
  laps: 'L',
  sessions: 'S',
  score: 'P',
  consistency: 'C',
  tracks: 'T',
  pb: 'R',
};

function getBadgeCategory(id: string): string {
  if (id.startsWith('laps_')) return 'laps';
  if (id.startsWith('sessions_')) return 'sessions';
  if (id.startsWith('score_')) return 'score';
  if (id.startsWith('consistency_')) return 'consistency';
  if (id.startsWith('tracks_')) return 'tracks';
  if (id.startsWith('pb_')) return 'pb';
  return 'laps';
}

export function DriverAchievements() {
  const { data, isLoading } = useQuery<AchievementsResponse>({
    queryKey: ['driver-achievements'],
    queryFn: () => api.get('/driver/achievements'),
    staleTime: 60_000,
  });

  if (isLoading) {
    return (
      <div className="flex gap-2">
        {[1, 2, 3].map((i) => (
          <div key={i} className="w-14 h-14 rounded-lg bg-steel/10 animate-pulse" />
        ))}
      </div>
    );
  }

  if (!data || data.earned_count === 0) {
    return (
      <div className="text-steel/60 text-xs font-body">
        Complete sessions to earn achievement badges
      </div>
    );
  }

  const earned = data.achievements.filter((a) => a.earned);
  const nextUp = data.in_progress.slice(0, 3);

  return (
    <div className="space-y-3">
      {/* Earned badges */}
      <div className="flex gap-2 flex-wrap">
        {earned.map((a) => {
          const cat = getBadgeCategory(a.id);
          return (
            <div
              key={a.id}
              title={`${a.label}: ${a.description}`}
              className="group relative w-12 h-12 rounded-lg bg-acid-green/10 border border-acid-green/30
                flex items-center justify-center cursor-default hover:bg-acid-green/20 transition-colors"
            >
              <span className="font-telemetry text-acid-green text-lg font-bold">
                {TIER_ICONS[cat] || '?'}
              </span>
              {/* Tooltip */}
              <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 px-2 py-1
                bg-zinc-900 border border-zinc-700 rounded text-xs text-chalk font-body
                whitespace-nowrap hidden group-hover:block z-10">
                {a.label}
              </div>
            </div>
          );
        })}
      </div>

      {/* Next achievements */}
      {nextUp.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs text-steel font-body">Next up:</p>
          {nextUp.map((a) => (
            <div key={a.id} className="flex items-center gap-2">
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between text-xs font-body">
                  <span className="text-chalk truncate">{a.label}</span>
                  <span className="text-steel shrink-0 ml-2">{a.progress_pct}%</span>
                </div>
                <div className="w-full h-1 bg-steel/10 rounded-full mt-0.5">
                  <div
                    className="h-full bg-acid-green/50 rounded-full transition-all"
                    style={{ width: `${a.progress_pct}%` }}
                  />
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
