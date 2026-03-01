'use client';

interface BadgeData {
  id: string;
  label: string;
  tier: 'bronze' | 'silver' | 'gold';
  category: string;
  criteria: string;
}

const TIER_CONFIG = {
  gold:   { icon: 'AU', bg: 'bg-yellow-500/10', border: 'border-yellow-500/30', text: 'text-yellow-400', label: 'Gold' },
  silver: { icon: 'AG', bg: 'bg-zinc-400/10',   border: 'border-zinc-400/30',   text: 'text-zinc-300',   label: 'Silver' },
  bronze: { icon: 'CU', bg: 'bg-orange-600/10', border: 'border-orange-600/30', text: 'text-orange-400', label: 'Bronze' },
} as const;

export function AchievementsBadges({ badges }: { badges?: BadgeData[] }) {
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
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {badges.map((badge) => {
          const tier = TIER_CONFIG[badge.tier] || TIER_CONFIG.bronze;
          return (
            <div
              key={badge.id}
              className={`rounded-lg border p-4 ${tier.bg} ${tier.border}`}
            >
              <div className="flex items-center gap-2 mb-1">
                <span className={`text-xs font-monument ${tier.text}`}>{tier.icon}</span>
                <span className={`text-xs font-body ${tier.text} uppercase tracking-wider`}>
                  {tier.label}
                </span>
              </div>
              <p className="text-sm font-body text-chalk">{badge.label}</p>
              <p className="text-[10px] text-steel font-body mt-1">{badge.criteria}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
