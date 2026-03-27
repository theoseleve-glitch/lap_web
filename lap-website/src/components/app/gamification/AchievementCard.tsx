'use client';

/* ── Types ────────────────────────────────────────────────── */

interface AchievementCardProps {
  title: string;
  description: string;
  /** SVG icon as JSX, or omit for default star icon */
  icon?: React.ReactNode;
  unlocked: boolean;
  progress?: number;
  maxProgress?: number;
  points: number;
  rarity: 'common' | 'rare' | 'epic' | 'legendary';
  className?: string;
}

const rarityColors: Record<string, { gradient: string; border: string; label: string }> = {
  common: { gradient: 'from-steel to-steel/80', border: 'border-steel/30', label: 'Common' },
  rare: { gradient: 'from-acid-green to-acid-green/80', border: 'border-acid-green/30', label: 'Rare' },
  epic: { gradient: 'from-racing-purple to-racing-purple/80', border: 'border-racing-purple/30', label: 'Epic' },
  legendary: { gradient: 'from-marshal-yellow to-gold', border: 'border-marshal-yellow/30', label: 'Legendary' },
};

/* ── Default Icon ─────────────────────────────────────────── */

function DefaultAchievementIcon({ unlocked }: { unlocked: boolean }) {
  return (
    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke={unlocked ? 'white' : '#949494'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
    </svg>
  );
}

/* ── Component ────────────────────────────────────────────── */

export function AchievementCard({
  title,
  description,
  icon,
  unlocked,
  progress,
  maxProgress,
  points,
  rarity,
  className,
}: AchievementCardProps) {
  const r = rarityColors[rarity];

  return (
    <div
      className={`p-4 rounded-xl border transition-all duration-300 ${
        unlocked ? r.border : 'border-steel/10'
      } ${
        unlocked ? 'bg-gradient-to-br from-white/5 to-white/10' : 'bg-asphalt/20'
      } ${unlocked ? 'hover:scale-105 hover:-translate-y-1' : ''} ${className ?? ''}`}
    >
      <div className="flex flex-col items-center text-center space-y-3">
        {/* Icon circle */}
        <div
          className={`p-4 rounded-full ${
            unlocked ? `bg-gradient-to-br ${r.gradient}` : 'bg-steel/10'
          } ${unlocked ? '' : 'opacity-30'}`}
        >
          {icon ?? <DefaultAchievementIcon unlocked={unlocked} />}
        </div>

        {/* Text */}
        <div className="space-y-1">
          <h3 className={`font-monument font-semibold text-chalk ${unlocked ? '' : 'opacity-50'}`}>
            {title}
          </h3>
          <p className={`text-sm font-body text-steel ${unlocked ? '' : 'opacity-50'}`}>
            {description}
          </p>
        </div>

        {/* Progress (locked only) */}
        {progress !== undefined && maxProgress !== undefined && !unlocked && (
          <div className="w-full">
            <div className="text-xs font-telemetry text-steel mb-1">
              {progress} / {maxProgress}
            </div>
            <div className="w-full h-2 bg-steel/10 rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-racing-purple to-acid-green transition-all duration-300"
                style={{ width: `${(progress / Math.max(maxProgress, 1)) * 100}%` }}
              />
            </div>
          </div>
        )}

        {/* Points badge */}
        <span
          className={`inline-flex items-center px-3 py-1 rounded-full font-telemetry text-xs uppercase tracking-wider ${
            unlocked
              ? `bg-gradient-to-r ${r.gradient} text-white`
              : 'border border-steel/20 text-steel opacity-50'
          }`}
        >
          {points} pts
        </span>
      </div>
    </div>
  );
}
