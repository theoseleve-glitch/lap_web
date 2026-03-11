'use client';

interface CornerTrendChartProps {
  apex_speed_history?: number[] | null;
  sessions_tracked?: number | null;
  trend_direction?: 'improving' | 'declining' | 'stable' | null;
}

const TREND_BADGE: Record<string, { label: string; className: string }> = {
  improving: { label: 'Improving', className: 'text-acid-green bg-acid-green/10' },
  declining: { label: 'Declining', className: 'text-safety-red bg-safety-red/10' },
  stable: { label: 'Stable', className: 'text-steel bg-steel/10' },
};

export default function CornerTrendChart({ apex_speed_history, sessions_tracked, trend_direction }: CornerTrendChartProps) {
  if (!apex_speed_history || apex_speed_history.length < 2) return null;

  const data = apex_speed_history;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const w = 120;
  const h = 32;
  const pad = 2;

  // Build sparkline path
  const points = data.map((v, i) => {
    const x = pad + (i / (data.length - 1)) * (w - 2 * pad);
    const y = h - pad - ((v - min) / range) * (h - 2 * pad);
    return `${x},${y}`;
  });
  const pathD = `M ${points.join(' L ')}`;

  // Trend line (first to last)
  const firstVal = data.length > 0 ? data[0]! : 0;
  const lastVal = data.length > 0 ? data[data.length - 1]! : 0;
  const trendStart = { x: pad, y: h - pad - ((firstVal - min) / range) * (h - 2 * pad) };
  const trendEnd = { x: w - pad, y: h - pad - ((lastVal - min) / range) * (h - 2 * pad) };

  const badge = trend_direction ? TREND_BADGE[trend_direction] : null;

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="text-xs text-steel font-telemetry uppercase tracking-wider">Apex Trend</span>
        <div className="flex items-center gap-2">
          {sessions_tracked != null && (
            <span className="text-[10px] text-chalk/40 font-telemetry">{sessions_tracked} sessions</span>
          )}
          {badge && (
            <span className={`text-[10px] font-telemetry px-1.5 py-0.5 rounded ${badge.className}`}>
              {badge.label}
            </span>
          )}
        </div>
      </div>

      <svg width={w} height={h} className="w-full" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
        {/* Trend line */}
        <line
          x1={trendStart.x} y1={trendStart.y}
          x2={trendEnd.x} y2={trendEnd.y}
          stroke="currentColor" className="text-steel/30"
          strokeWidth={1} strokeDasharray="3 2"
        />
        {/* Sparkline */}
        <path d={pathD} fill="none" stroke="currentColor" className="text-acid-green" strokeWidth={1.5} />
      </svg>
    </div>
  );
}
