'use client';

import type { TractionBudget } from './types';

interface TractionBudgetVizProps {
  budget?: TractionBudget | null;
}

function arcPath(cx: number, cy: number, r: number, startAngle: number, endAngle: number): string {
  const start = {
    x: cx + r * Math.cos((startAngle * Math.PI) / 180),
    y: cy + r * Math.sin((startAngle * Math.PI) / 180),
  };
  const end = {
    x: cx + r * Math.cos((endAngle * Math.PI) / 180),
    y: cy + r * Math.sin((endAngle * Math.PI) / 180),
  };
  const large = endAngle - startAngle > 180 ? 1 : 0;
  return `M ${start.x} ${start.y} A ${r} ${r} 0 ${large} 1 ${end.x} ${end.y}`;
}

interface ZoneConfig {
  key: 'entry_grip' | 'apex_grip' | 'exit_grip';
  label: string;
  startAngle: number;
  endAngle: number;
  color: string;
}

const ZONES: ZoneConfig[] = [
  { key: 'entry_grip', label: 'Entry', startAngle: 210, endAngle: 330, color: '#f59e0b' },
  { key: 'apex_grip', label: 'Apex', startAngle: 330, endAngle: 90, color: '#3b82f6' },
  { key: 'exit_grip', label: 'Exit', startAngle: 90, endAngle: 210, color: '#10b981' },
];

export default function TractionBudgetViz({ budget }: TractionBudgetVizProps) {
  if (!budget) return null;

  const hasData = ZONES.some((z) => budget[z.key] != null);
  if (!hasData) return null;

  const cx = 40;
  const cy = 40;
  const maxR = 32;

  return (
    <div className="flex flex-col items-center gap-2">
      <span className="text-xs text-steel font-telemetry uppercase tracking-wider">Grip Budget</span>
      <svg width={80} height={80} viewBox="0 0 80 80">
        {/* Background circle */}
        <circle cx={cx} cy={cy} r={maxR} fill="none" stroke="currentColor" className="text-steel/20" strokeWidth={1} />

        {/* Grip arcs */}
        {ZONES.map((zone) => {
          const grip = budget[zone.key];
          if (grip == null) return null;
          const clampedGrip = Math.min(1, Math.max(0, grip));
          const r = maxR * clampedGrip;
          if (r < 2) return null;
          return (
            <path
              key={zone.key}
              d={arcPath(cx, cy, r, zone.startAngle, zone.endAngle)}
              fill="none"
              stroke={zone.color}
              strokeWidth={3}
              strokeLinecap="round"
              opacity={0.8}
            />
          );
        })}

        {/* Center dot */}
        <circle cx={cx} cy={cy} r={1.5} fill="currentColor" className="text-chalk/40" />
      </svg>

      {/* Labels */}
      <div className="flex gap-3">
        {ZONES.map((zone) => {
          const grip = budget[zone.key];
          if (grip == null) return null;
          return (
            <span key={zone.key} className="text-[10px] font-telemetry" style={{ color: zone.color }}>
              {zone.label} {Math.round(grip * 100)}%
            </span>
          );
        })}
      </div>
    </div>
  );
}
