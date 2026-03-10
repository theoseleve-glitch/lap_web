'use client';

import type { DriverBadge } from '@/lib/api-types';

const LEVEL_COLORS: Record<string, string> = {
  bronze: 'text-amber-600',
  silver: 'text-gray-300',
  gold: 'text-yellow-400',
  platinum: 'text-cyan-300',
};

interface Props {
  badges: DriverBadge[];
}

export function BadgeGrid({ badges }: Props) {
  if (badges.length === 0) {
    return (
      <p className="text-steel font-body text-sm text-center py-6">
        No badges earned yet.
      </p>
    );
  }

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
      {badges.map((b) => (
        <div
          key={b.id}
          className="bg-carbon rounded-lg border border-steel/15 p-3 text-center"
        >
          <div className={`text-2xl mb-1 ${LEVEL_COLORS[b.badge_level ?? ''] ?? 'text-steel'}`}>
            &#x1F3C6;
          </div>
          <p className="font-telemetry text-xs text-chalk truncate">{b.badge_name}</p>
          <p className="font-telemetry text-[10px] text-steel/60 uppercase mt-0.5">
            {b.badge_level ?? b.badge_type}
          </p>
          <p className="font-telemetry text-[10px] text-steel/40 mt-1">
            {new Date(b.earned_at).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: '2-digit' })}
          </p>
        </div>
      ))}
    </div>
  );
}
