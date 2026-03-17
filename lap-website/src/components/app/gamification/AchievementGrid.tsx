'use client';

import type { Achievement } from './types';
import { BadgeHex, type BadgeIcon } from './BadgeHex';

interface AchievementGridProps {
  achievements: Achievement[];
  className?: string;
}

const ICON_TO_BADGE: Record<string, BadgeIcon> = {
  flag: 'trophy',
  calendar: 'stopwatch',
  star: 'trophy',
  trophy: 'trophy',
  medal: 'trophy',
  shield: 'shield',
  crown: 'trophy',
  fire: 'helmet',
  'check-circle': 'shield',
  'list-check': 'shield',
  zap: 'helmet',
  'trending-up': 'helmet',
};

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  } catch {
    return iso;
  }
}

export default function AchievementGrid({
  achievements,
  className = '',
}: AchievementGridProps) {
  const totalCount = achievements.length;
  const unlockedCount = achievements.filter((a) => a.unlocked).length;

  return (
    <div className={className}>
      <div className="flex items-center gap-3 mb-4">
        <span className="font-telemetry text-sm text-steel">
          {unlockedCount} / {totalCount}
        </span>
        <span className="text-xs text-steel/50">Achievements</span>
      </div>

      <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 gap-3">
        {achievements.map((ach) => {
          const badgeIcon = ICON_TO_BADGE[ach.icon] || 'trophy';
          return (
            <div
              key={ach.key}
              className={`flex flex-col items-center text-center p-3 rounded-xl border transition-all ${
                ach.unlocked
                  ? 'border-acid-green/20 bg-acid-green/[0.03] hover:scale-105 cursor-default'
                  : 'border-steel/10 bg-asphalt/30 opacity-35'
              }`}
              title={ach.unlocked ? ach.description : '???'}
            >
              <BadgeHex
                icon={ach.unlocked ? badgeIcon : 'lock'}
                tier={ach.unlocked ? 'gold' : 'locked'}
                size={48}
                glow={ach.unlocked}
              />
              <p className="font-body text-[10px] text-chalk font-medium mt-2 leading-tight">
                {ach.unlocked ? ach.label : '???'}
              </p>
              {ach.unlocked && ach.unlocked_at && (
                <p className="text-[9px] font-telemetry text-acid-green/60 mt-0.5">
                  {formatDate(ach.unlocked_at)}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
