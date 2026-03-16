'use client';

import type { Stint } from './types';
import { DRIVER_COLORS } from './types';

interface StrategyTimelineProps {
  stints: Stint[];
  drivers: string[];
}

export function StrategyTimeline({ stints, drivers }: StrategyTimelineProps) {
  if (stints.length === 0) return null;

  const maxLap = Math.max(...stints.map((s) => s.end_lap));
  const driverColorMap = Object.fromEntries(
    drivers.map((d, i) => [d, DRIVER_COLORS[i % DRIVER_COLORS.length]])
  );

  return (
    <div className="bg-concrete rounded-xl border border-steel/10 p-4">
      <h4 className="text-sm font-monument text-chalk mb-3">Strategy Timeline</h4>

      {/* Legend */}
      <div className="flex flex-wrap gap-3 mb-3">
        {drivers.map((d, i) => (
          <div key={d} className="flex items-center gap-1.5">
            <div
              className="w-3 h-3 rounded-sm"
              style={{ backgroundColor: DRIVER_COLORS[i % DRIVER_COLORS.length] }}
            />
            <span className="text-xs font-body text-steel">{d}</span>
          </div>
        ))}
      </div>

      {/* Timeline bar */}
      <div className="relative h-10 bg-asphalt rounded-lg overflow-hidden">
        {stints.map((stint) => {
          const left = ((stint.start_lap - 1) / maxLap) * 100;
          const width = ((stint.end_lap - stint.start_lap + 1) / maxLap) * 100;
          const color = stint.driver_name ? driverColorMap[stint.driver_name] || '#666' : '#666';

          return (
            <div
              key={stint.stint_number}
              className="absolute top-1 bottom-1 rounded-sm flex items-center justify-center"
              style={{
                left: `${left}%`,
                width: `${Math.max(width, 1)}%`,
                backgroundColor: color,
                opacity: 0.7,
              }}
              title={`Stint ${stint.stint_number}: ${stint.driver_name || '?'} (L${stint.start_lap}–${stint.end_lap})`}
            >
              <span className="text-[9px] font-telemetry text-carbon font-bold truncate px-1">
                S{stint.stint_number}
              </span>
            </div>
          );
        })}
      </div>

      {/* Lap scale */}
      <div className="flex justify-between mt-1">
        <span className="text-[10px] font-telemetry text-steel/50">L1</span>
        <span className="text-[10px] font-telemetry text-steel/50">L{maxLap}</span>
      </div>
    </div>
  );
}
