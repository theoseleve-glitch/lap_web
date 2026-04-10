'use client';

type Props = {
  label: string;
  used: number;
  limit: number;
  formatValue: (n: number) => string;
};

function barColor(pct: number): string {
  if (pct < 60) return '#22c55e';
  if (pct < 80) return '#C9A84C';
  return '#FF2A2A';
}

export default function StorageBar({ label, used, limit, formatValue }: Props) {
  const pct = limit > 0 ? (used / limit) * 100 : 0;
  const color = barColor(pct);

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs">
        <span className="text-white/50">{label}</span>
        <span className="tabular-nums text-white/70">
          {formatValue(used)} / {formatValue(limit)}{' '}
          <span className="text-white/40">({pct.toFixed(0)}%)</span>
        </span>
      </div>

      <div
        className="overflow-hidden rounded-full"
        style={{ height: 8, backgroundColor: 'rgba(255,255,255,0.08)' }}
      >
        <div
          className="h-full rounded-full transition-all"
          style={{
            width: `${Math.min(pct, 100)}%`,
            backgroundColor: color,
          }}
        />
      </div>

      <p className="text-xs text-white/30">{formatValue(limit - used)} remaining</p>
    </div>
  );
}
