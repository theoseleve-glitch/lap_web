'use client';

import {
  ResponsiveContainer, RadarChart, Radar, PolarGrid,
  PolarAngleAxis, PolarRadiusAxis,
} from 'recharts';
import type { DriverStyleEntry } from '@/lib/api-types';

const STYLE_COLORS: Record<string, string> = {
  Aggressive: 'bg-safety-red/10 text-safety-red',
  Smooth: 'bg-acid-green/10 text-acid-green',
  Balanced: 'bg-marshal-yellow/10 text-marshal-yellow',
  Conservative: 'bg-blue-400/10 text-blue-400',
};

interface Props {
  latest: DriverStyleEntry | null;
  history: DriverStyleEntry[];
}

const AXES: Array<{ key: keyof DriverStyleEntry; label: string }> = [
  { key: 'trail_braking_depth', label: 'Trail Braking' },
  { key: 'brake_point_consistency', label: 'Brake Consistency' },
  { key: 'apex_speed_ratio', label: 'Apex Speed' },
  { key: 'turn_in_aggressiveness', label: 'Turn-In' },
  { key: 'exit_acceleration_efficiency', label: 'Exit Accel' },
  { key: 'smoothness_composite', label: 'Smoothness' },
  { key: 'line_variation_index', label: 'Line Variation' },
  { key: 'early_vs_late_stint_pace', label: 'Stint Pace' },
];

export function StyleRadar({ latest, history }: Props) {
  if (!latest) {
    return (
      <p className="text-steel font-body text-sm text-center py-8">
        No driving style data yet.
      </p>
    );
  }

  const radarData = AXES.map(({ key, label }) => ({
    axis: label,
    value: Math.min(1, Math.max(0, (latest[key] as number) ?? 0)),
  }));

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div>
        <div className="flex items-center gap-3 mb-3">
          <h4 className="font-telemetry text-xs text-steel/60 uppercase">Style Profile</h4>
          {latest.style_label && (
            <span className={`px-2 py-0.5 rounded text-[10px] font-telemetry uppercase ${
              STYLE_COLORS[latest.style_label] ?? 'bg-steel/10 text-steel'
            }`}>
              {latest.style_label}
            </span>
          )}
        </div>
        <ResponsiveContainer width="100%" height={280}>
          <RadarChart data={radarData}>
            <PolarGrid stroke="rgba(148,163,184,0.15)" />
            <PolarAngleAxis dataKey="axis" tick={{ fill: '#94a3b8', fontSize: 9 }} />
            <PolarRadiusAxis domain={[0, 1]} tick={false} axisLine={false} />
            <Radar dataKey="value" stroke="#a3e635" fill="#a3e635" fillOpacity={0.15} strokeWidth={2} />
          </RadarChart>
        </ResponsiveContainer>
      </div>
      <div className="space-y-4">
        {latest.strengths.length > 0 && (
          <div>
            <h4 className="font-telemetry text-xs text-steel/60 uppercase mb-2">Strengths</h4>
            <ul className="space-y-1">
              {latest.strengths.map((s, i) => (
                <li key={i} className="text-acid-green font-body text-sm flex items-center gap-2">
                  <span className="w-1 h-1 bg-acid-green rounded-full flex-shrink-0" />
                  {s}
                </li>
              ))}
            </ul>
          </div>
        )}
        {latest.weaknesses.length > 0 && (
          <div>
            <h4 className="font-telemetry text-xs text-steel/60 uppercase mb-2">Areas to Improve</h4>
            <ul className="space-y-1">
              {latest.weaknesses.map((w, i) => (
                <li key={i} className="text-pit-orange font-body text-sm flex items-center gap-2">
                  <span className="w-1 h-1 bg-pit-orange rounded-full flex-shrink-0" />
                  {w}
                </li>
              ))}
            </ul>
          </div>
        )}
        {history.length > 1 && (
          <div>
            <h4 className="font-telemetry text-xs text-steel/60 uppercase mb-2">Style History</h4>
            <div className="flex flex-wrap gap-2">
              {history.map((h, i) => (
                <span key={i} className={`px-2 py-0.5 rounded text-[10px] font-telemetry ${
                  STYLE_COLORS[h.style_label ?? ''] ?? 'bg-steel/10 text-steel'
                }`}>
                  {h.style_label ?? 'Unknown'}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
