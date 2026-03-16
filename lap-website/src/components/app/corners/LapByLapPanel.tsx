'use client';

import { useMemo } from 'react';
import type { CornerMetricRow } from './useCornerData';

interface LapByLapPanelProps {
  metrics: CornerMetricRow[];
}

function timeLossColor(ms: number | null): string {
  if (ms == null) return 'text-steel';
  if (ms < 50) return 'text-acid-green';
  if (ms < 150) return 'text-marshal-yellow';
  if (ms <= 300) return 'text-pit-orange';
  return 'text-safety-red';
}

export function LapByLapPanel({ metrics }: LapByLapPanelProps) {
  if (metrics.length === 0) {
    return <p className="text-steel text-sm font-body">Lap data not available for this corner</p>;
  }

  const sorted = useMemo(() => [...metrics].sort((a, b) => a.lap_number - b.lap_number), [metrics]);

  const { bestIdx, worstIdx, improving } = useMemo(() => {
    let bIdx = 0;
    let wIdx = 0;
    for (let i = 1; i < sorted.length; i++) {
      const tl = sorted[i].time_loss_ms;
      if (tl != null && (sorted[bIdx].time_loss_ms == null || tl < sorted[bIdx].time_loss_ms!)) bIdx = i;
      if (tl != null && (sorted[wIdx].time_loss_ms == null || tl > sorted[wIdx].time_loss_ms!)) wIdx = i;
    }
    // Check if apex speed is improving (first half avg vs second half avg)
    const half = Math.floor(sorted.length / 2);
    const firstHalf = sorted.slice(0, half).filter((m) => m.apex_speed_mps != null);
    const secondHalf = sorted.slice(half).filter((m) => m.apex_speed_mps != null);
    const avgFirst = firstHalf.length > 0 ? firstHalf.reduce((s, m) => s + m.apex_speed_mps!, 0) / firstHalf.length : 0;
    const avgSecond = secondHalf.length > 0 ? secondHalf.reduce((s, m) => s + m.apex_speed_mps!, 0) / secondHalf.length : 0;
    return { bestIdx: bIdx, worstIdx: wIdx, improving: avgSecond > avgFirst + 0.1 };
  }, [sorted]);

  return (
    <div>
      {improving && (
        <div className="flex items-center gap-1.5 mb-3">
          <span className="text-acid-green text-xs">↗</span>
          <span className="text-acid-green text-xs font-telemetry">Apex speed improving through session</span>
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-xs font-telemetry">
          <thead>
            <tr className="text-steel text-[10px] uppercase tracking-wider">
              <th className="text-left py-1.5 pr-3">Lap</th>
              <th className="text-right py-1.5 px-3">Brake</th>
              <th className="text-right py-1.5 px-3">Apex</th>
              <th className="text-right py-1.5 px-3">Exit</th>
              <th className="text-right py-1.5 pl-3">Loss</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((m, i) => {
              const borderClass =
                i === bestIdx
                  ? 'border-l-2 border-l-acid-green'
                  : i === worstIdx
                    ? 'border-l-2 border-l-safety-red'
                    : 'border-l-2 border-l-transparent';
              return (
                <tr key={m.lap_number} className={`${borderClass} hover:bg-white/5 transition-colors`}>
                  <td className="text-left py-1.5 pr-3 text-chalk pl-1">{m.lap_number}</td>
                  <td className="text-right py-1.5 px-3 text-chalk/70">
                    {m.brake_point_m != null ? `${m.brake_point_m.toFixed(0)}m` : '—'}
                  </td>
                  <td className="text-right py-1.5 px-3 text-chalk/70">
                    {m.apex_speed_mps != null ? `${(m.apex_speed_mps * 3.6).toFixed(1)}` : '—'}
                  </td>
                  <td className="text-right py-1.5 px-3 text-chalk/70">
                    {m.exit_speed_mps != null ? `${(m.exit_speed_mps * 3.6).toFixed(1)}` : '—'}
                  </td>
                  <td className={`text-right py-1.5 pl-3 ${timeLossColor(m.time_loss_ms)}`}>
                    {m.time_loss_ms != null ? `${m.time_loss_ms.toFixed(0)}ms` : '—'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
