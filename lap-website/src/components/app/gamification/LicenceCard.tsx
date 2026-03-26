'use client';

const TIER_COLORS: Record<string, string> = {
  rookie: '#949494',
  club: '#B6FF2E',
  national: '#00d4ff',
  pro: '#D946EF',
  elite: '#FFD400',
  legend: '#FF3B6B',
};

const ALL_TIERS = [
  { tier: 'rookie', color: '#949494' },
  { tier: 'club', color: '#B6FF2E' },
  { tier: 'national', color: '#00d4ff' },
  { tier: 'pro', color: '#D946EF' },
  { tier: 'elite', color: '#FFD400' },
  { tier: 'legend', color: '#FF3B6B' },
];

interface ProgressPair {
  current: number;
  required: number;
}

interface LicenceCardProps {
  tier: string;
  color: string;
  nextTier?: string | null;
  nextColor?: string | null;
  progress?: {
    laps?: ProgressPair;
    score?: ProgressPair;
  };
  allTiers?: { tier: string; color: string }[];
  className?: string;
}

function clamp(v: number, min: number, max: number) {
  return Math.max(min, Math.min(max, v));
}

export function LicenceCard({
  tier,
  color,
  nextTier,
  nextColor,
  progress,
  allTiers,
  className,
}: LicenceCardProps) {
  const tierColor = TIER_COLORS[tier] ?? color;
  const nColor = nextColor ?? (nextTier ? TIER_COLORS[nextTier] ?? '#ffffff' : '#ffffff');
  const tiers = allTiers ?? ALL_TIERS;
  const letter = tier.charAt(0).toUpperCase();

  const currentIdx = tiers.findIndex(
    (t) => t.tier.toLowerCase() === tier.toLowerCase(),
  );

  return (
    <div
      className={`relative rounded-lg border-l-4 overflow-hidden ${className ?? ''}`}
      style={{
        borderLeftColor: tierColor,
        background: `linear-gradient(135deg, rgba(${hexToRgb(tierColor)}, 0.08) 0%, rgba(26,26,46,1) 60%)`,
      }}
    >
      <div className="p-4 space-y-4">
        {/* Top row */}
        <div className="flex items-start justify-between">
          <div>
            <p
              className="font-mono text-[10px] uppercase tracking-widest"
              style={{ color: tierColor }}
            >
              Current Licence
            </p>
            <p className="text-2xl font-black text-white capitalize mt-0.5">
              {tier}
            </p>
          </div>
          <div
            className="w-14 h-14 rounded-lg flex items-center justify-center shrink-0"
            style={{
              background: `linear-gradient(135deg, ${tierColor}, ${adjustBrightness(tierColor, -40)})`,
            }}
          >
            <span className="text-white text-2xl font-black leading-none">
              {letter}
            </span>
          </div>
        </div>

        {/* Progress section */}
        {nextTier && progress && (
          <div className="space-y-2">
            <p className="font-mono text-[10px] uppercase tracking-wider text-steel/60">
              Progress to{' '}
              <span className="capitalize" style={{ color: nColor }}>
                {nextTier}
              </span>
            </p>

            {progress.laps && (
              <ProgressRow
                label="Laps"
                current={progress.laps.current}
                required={progress.laps.required}
                unit="laps"
                fromColor={tierColor}
                toColor={nColor}
              />
            )}

            {progress.score && (
              <ProgressRow
                label="Score"
                current={progress.score.current}
                required={progress.score.required}
                unit="needed"
                fromColor={tierColor}
                toColor={nColor}
              />
            )}
          </div>
        )}

        {/* Tier ladder */}
        <div className="flex gap-1">
          {tiers.map((t, i) => {
            const isCurrent = i === currentIdx;
            const isLocked = i > currentIdx;
            const tColor = TIER_COLORS[t.tier] ?? t.color;
            return (
              <div
                key={t.tier}
                className={`flex-1 text-center py-1 rounded-sm border-b-2 ${
                  isCurrent ? 'font-bold' : ''
                } ${isLocked ? 'opacity-30' : ''}`}
                style={{
                  borderBottomColor: tColor,
                  backgroundColor: isCurrent
                    ? `rgba(${hexToRgb(tColor)}, 0.15)`
                    : 'transparent',
                }}
              >
                <span
                  className="font-mono capitalize block"
                  style={{
                    fontSize: '8px',
                    lineHeight: '12px',
                    color: isCurrent ? tColor : 'rgba(160,160,180,0.6)',
                  }}
                >
                  {t.tier}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/* ── Internal helpers ─────────────────────────────────────── */

function ProgressRow({
  label,
  current,
  required,
  unit,
  fromColor,
  toColor,
}: {
  label: string;
  current: number;
  required: number;
  unit: string;
  fromColor: string;
  toColor: string;
}) {
  const pct = clamp((current / Math.max(required, 1)) * 100, 0, 100);
  return (
    <div className="space-y-0.5">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10px] text-steel/50 uppercase">
          {label}
        </span>
        <span className="font-mono text-[10px] text-steel/70">
          {current} / {required} {unit}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-white/5 overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{
            width: `${pct}%`,
            background: `linear-gradient(90deg, ${fromColor}, ${toColor})`,
          }}
        />
      </div>
    </div>
  );
}

function hexToRgb(hex: string): string {
  const h = hex.replace('#', '');
  const n = parseInt(h, 16);
  return `${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}`;
}

function adjustBrightness(hex: string, amount: number): string {
  const h = hex.replace('#', '');
  const n = parseInt(h, 16);
  const r = clamp(((n >> 16) & 255) + amount, 0, 255);
  const g = clamp(((n >> 8) & 255) + amount, 0, 255);
  const b = clamp((n & 255) + amount, 0, 255);
  return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, '0')}`;
}

export default LicenceCard;
