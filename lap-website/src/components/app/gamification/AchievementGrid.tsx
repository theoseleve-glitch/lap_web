'use client';

import type { Achievement } from './types';

interface AchievementGridProps {
  achievements: Achievement[];
  className?: string;
}

const ICON_MAP: Record<string, string> = {
  flag: '\u{1F3C1}',       // flag
  calendar: '\u{1F4C5}',   // calendar
  star: '\u2B50',           // star
  trophy: '\u{1F3C6}',     // trophy
  medal: '\u{1F3C5}',      // medal
  shield: '\u{1F6E1}\uFE0F', // shield
  crown: '\u{1F451}',      // crown
  fire: '\u{1F525}',       // fire
  'check-circle': '\u2705', // check-circle
  'list-check': '\u{1F4CB}', // list-check
  zap: '\u26A1',            // zap
  'trending-up': '\u{1F4C8}', // trending-up
};

function resolveIcon(icon: string): string {
  return ICON_MAP[icon] ?? icon;
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
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
      {/* Counter */}
      <p className="font-telemetry text-sm text-steel mb-4">
        {unlockedCount} / {totalCount} Achievements
      </p>

      {/* Grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
        {achievements.map((ach) => (
          <div
            key={ach.key}
            className="rounded-lg p-3 text-center transition-opacity"
            style={{
              backgroundColor: 'rgba(30, 30, 50, 0.6)',
              border: ach.unlocked
                ? '1px solid rgba(163, 230, 53, 0.5)'
                : '1px solid rgba(148, 163, 184, 0.2)',
              opacity: ach.unlocked ? 1 : 0.3,
              filter: ach.unlocked ? 'none' : 'grayscale(1)',
            }}
          >
            {/* Icon */}
            <div className="text-3xl mb-2" role="img" aria-label={ach.label}>
              {resolveIcon(ach.icon)}
            </div>

            {/* Label */}
            <p className="font-monument text-xs font-semibold text-chalk truncate">
              {ach.label}
            </p>

            {/* Description or locked placeholder */}
            {ach.unlocked ? (
              <>
                <p className="text-xs text-steel mt-1 line-clamp-2">
                  {ach.description}
                </p>
                {ach.unlocked_at && (
                  <p
                    className="text-[10px] mt-1.5 font-telemetry"
                    style={{ color: '#a3e635' }}
                  >
                    {formatDate(ach.unlocked_at)}
                  </p>
                )}
              </>
            ) : (
              <p className="text-xs text-steel mt-1">???</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
