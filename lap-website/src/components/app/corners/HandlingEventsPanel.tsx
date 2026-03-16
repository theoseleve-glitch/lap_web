'use client';

import type { HandlingEvent } from './useCornerData';

interface HandlingEventsPanelProps {
  events: HandlingEvent[];
}

const SEVERITY_COLORS: Record<string, string> = {
  mild: 'bg-acid-green/20 text-acid-green',
  moderate: 'bg-marshal-yellow/20 text-marshal-yellow',
  severe: 'bg-safety-red/20 text-safety-red',
};

const TYPE_COLORS: Record<string, string> = {
  understeer: 'bg-blue-500/20 text-blue-400',
  oversteer: 'bg-pit-orange/20 text-pit-orange',
};

export function HandlingEventsPanel({ events }: HandlingEventsPanelProps) {
  if (events.length === 0) {
    return (
      <div className="flex items-center gap-2 py-2">
        <span className="text-acid-green text-lg">✓</span>
        <span className="text-steel text-sm font-body">No handling events detected — clean driving through this corner</span>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {events.map((ev, i) => (
        <div key={i} className="flex items-start gap-3 bg-concrete/50 rounded-lg p-3">
          <div className="flex flex-wrap gap-1.5 shrink-0">
            <span className={`text-[10px] font-telemetry font-semibold px-2 py-0.5 rounded ${TYPE_COLORS[ev.event_type] ?? 'bg-steel/20 text-steel'}`}>
              {ev.event_type.toUpperCase()}
            </span>
            <span className={`text-[10px] font-telemetry px-2 py-0.5 rounded ${SEVERITY_COLORS[ev.severity] ?? 'bg-steel/20 text-steel'}`}>
              {ev.severity}
            </span>
            <span className="text-[10px] font-telemetry px-2 py-0.5 rounded bg-steel/10 text-steel">
              {ev.corner_phase}
            </span>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-chalk/80 text-sm font-body">{ev.cause_detail || ev.cause}</p>
            {ev.time_cost_s != null && (
              <p className="text-safety-red text-xs font-telemetry mt-1">
                {(ev.time_cost_s * 1000).toFixed(0)}ms cost
              </p>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
