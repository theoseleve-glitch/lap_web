'use client';

import { useState } from 'react';
import { RacingBadge, AchievementUnlockOverlay } from './gamification';

interface BadgeData {
  id: string;
  label: string;
  tier: 'bronze' | 'silver' | 'gold';
  category: string;
  criteria: string;
}

const CATEGORY_MAP: Record<string, 'progress' | 'technique' | 'consistency' | 'learning' | 'endurance'> = {
  pace: 'technique',
  consistency: 'consistency',
  execution: 'technique',
  robustness: 'endurance',
  adaptation: 'learning',
  total: 'progress',
};

const TIER_COLORS: Record<string, string> = {
  gold: '#FACC15',
  silver: '#949494',
  bronze: '#C9A84C',
};

export function AchievementsBadges({ badges }: { badges?: BadgeData[] }) {
  const [selected, setSelected] = useState<{ key: string; label: string; description: string; icon: string; tier: string } | null>(null);

  if (!badges || badges.length === 0) {
    return (
      <div className="bg-concrete rounded-xl border border-steel/10 p-6">
        <h2 className="text-lg font-monument text-chalk mb-2">Achievements</h2>
        <p className="text-steel text-sm font-body">
          Keep pushing — badges unlock at 60%+ category scores.
        </p>
      </div>
    );
  }

  return (
    <div className="bg-concrete rounded-xl border border-steel/10 p-6">
      <h2 className="text-lg font-monument text-chalk mb-4">Achievements</h2>
      <div className="flex flex-wrap gap-4">
        {badges.map((badge) => {
          const category = CATEGORY_MAP[badge.category] || 'progress';
          const color = TIER_COLORS[badge.tier] || '#888';
          return (
            <button
              type="button"
              key={badge.id}
              className="flex flex-col items-center gap-1.5 group cursor-pointer"
              onClick={() => setSelected({
                key: badge.id,
                label: badge.label,
                description: badge.criteria,
                icon: badge.category,
                tier: badge.tier,
              })}
            >
              <div className="transition-transform group-hover:scale-110">
                <RacingBadge
                  title={badge.label}
                  description={badge.criteria}
                  unlocked
                  category={category}
                />
              </div>
              <span className="text-[10px] font-body text-chalk font-medium text-center w-[70px] leading-tight truncate">
                {badge.label}
              </span>
              <span className="text-[9px] font-telemetry uppercase" style={{ color }}>
                {badge.tier}
              </span>
            </button>
          );
        })}
      </div>
      <AchievementUnlockOverlay achievement={selected} onDismiss={() => setSelected(null)} />
    </div>
  );
}
