/**
 * DriverAchievements.tsx — Driver career milestone badges.
 *
 * Fetches and displays earned/in-progress achievement badges.
 */
'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { BadgeHex, AchievementUnlockOverlay, type BadgeIcon } from './gamification';

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

const CATEGORY_ICON: Record<string, BadgeIcon> = {
  laps: 'helmet',
  sessions: 'stopwatch',
  score: 'trophy',
  consistency: 'stopwatch',
  tracks: 'shield',
  pb: 'trophy',
};

function getBadgeIcon(id: string): BadgeIcon {
  if (id.startsWith('laps_')) return 'helmet';
  if (id.startsWith('sessions_')) return 'stopwatch';
  if (id.startsWith('score_')) return 'trophy';
  if (id.startsWith('consistency_')) return 'stopwatch';
  if (id.startsWith('tracks_')) return 'shield';
  if (id.startsWith('pb_')) return 'trophy';
  return 'trophy';
}

export function DriverAchievements() {
  const { data, isLoading } = useQuery<AchievementsResponse>({
    queryKey: ['driver-achievements'],
    queryFn: () => api.get('/driver/achievements'),
    staleTime: 60_000,
  });
  const [selected, setSelected] = useState<{ key: string; label: string; description: string; icon: string; tier: string } | null>(null);

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
      <div className="flex gap-3 flex-wrap">
        {earned.map((a) => {
          const icon = getBadgeIcon(a.id);
          return (
            <button
              type="button"
              key={a.id}
              title={`${a.label}: ${a.description}`}
              className="group relative flex flex-col items-center cursor-pointer"
              onClick={() => setSelected({ key: a.id, label: a.label, description: a.description, icon, tier: 'gold' })}
            >
              <div className="transition-transform group-hover:scale-110">
                <BadgeHex icon={icon} tier="gold" size={48} glow />
              </div>
              {/* Tooltip */}
              <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 px-2 py-1
                bg-zinc-900 border border-zinc-700 rounded text-[10px] text-chalk font-body
                whitespace-nowrap hidden group-hover:block z-10">
                {a.label}
              </div>
            </button>
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
      <AchievementUnlockOverlay achievement={selected} onDismiss={() => setSelected(null)} />
    </div>
  );
}
