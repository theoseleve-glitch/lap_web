'use client';

import type { CornerReplayLap } from './types';

interface AnalyzerLapSelectorProps {
  laps: CornerReplayLap[];
  primaryLap: number;
  overlayLap: number | null;
  onPrimaryChange: (lap: number) => void;
  onOverlayChange: (lap: number | null) => void;
}

function fmtTime(s: number | null): string {
  if (s == null) return '';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return ` (${m}:${sec.toFixed(3).padStart(6, '0')})`;
}

export function AnalyzerLapSelector({
  laps,
  primaryLap,
  overlayLap,
  onPrimaryChange,
  onOverlayChange,
}: AnalyzerLapSelectorProps) {
  if (laps.length === 0) return null;

  return (
    <div className="flex items-center gap-2 text-xs">
      <label className="flex items-center gap-1 text-steel">
        <span className="font-telemetry text-[10px] uppercase tracking-wider">Lap</span>
        <select
          value={primaryLap}
          onChange={(e) => onPrimaryChange(Number(e.target.value))}
          className="bg-asphalt text-chalk text-xs font-telemetry rounded px-1.5 py-1 border border-steel/20 focus:border-acid-green focus:outline-none"
        >
          {laps.map((l) => (
            <option key={l.lap_number} value={l.lap_number}>
              {l.lap_number}{fmtTime(l.lap_time_s)}
            </option>
          ))}
        </select>
      </label>

      <label className="flex items-center gap-1 text-steel">
        <span className="font-telemetry text-[10px] uppercase tracking-wider">vs</span>
        <select
          value={overlayLap ?? ''}
          onChange={(e) => {
            const v = e.target.value;
            onOverlayChange(v === '' ? null : Number(v));
          }}
          className="bg-asphalt text-pit-orange text-xs font-telemetry rounded px-1.5 py-1 border border-steel/20 focus:border-pit-orange focus:outline-none"
        >
          <option value="">None</option>
          {laps
            .filter((l) => l.lap_number !== primaryLap)
            .map((l) => (
              <option key={l.lap_number} value={l.lap_number}>
                {l.lap_number}{fmtTime(l.lap_time_s)}
              </option>
            ))}
        </select>
      </label>
    </div>
  );
}
