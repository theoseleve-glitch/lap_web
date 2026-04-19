'use client';

import { useState } from 'react';
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
  understeer: 'bg-safety-red/20 text-safety-red',
  oversteer: 'bg-racing-purple/20 text-racing-purple',
};

export function HandlingEventsPanel({ events }: HandlingEventsPanelProps) {
  // Only show confirmed (>85%) and likely (60-85%) events
  const visible = events.filter(ev => (ev.confidence ?? ev.magnitude ?? 0) >= 0.60);

  if (visible.length === 0) {
    return (
      <div className="flex items-center gap-2 py-2">
        <span className="text-acid-green text-lg">&#10003;</span>
        <span className="text-steel text-sm font-body">No significant handling events detected</span>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {visible.map((ev, i) => (
        <HandlingEventCard key={i} event={ev} />
      ))}
    </div>
  );
}

function HandlingEventCard({ event: ev }: { event: HandlingEvent }) {
  const [expanded, setExpanded] = useState(false);
  const confidence = ev.confidence ?? ev.magnitude ?? 0;
  const hasVotes = ev.detector_votes && Object.keys(ev.detector_votes).length > 0;

  return (
    <div className="bg-concrete/50 rounded-lg p-3">
      {/* Header row: type + severity + phase + confidence */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className={`text-[10px] font-telemetry font-semibold px-2 py-0.5 rounded ${TYPE_COLORS[ev.event_type] ?? 'bg-steel/20 text-steel'}`}>
          {ev.event_type.toUpperCase()}
        </span>
        <span className={`text-[10px] font-telemetry px-2 py-0.5 rounded ${SEVERITY_COLORS[ev.severity] ?? 'bg-steel/20 text-steel'}`}>
          {ev.severity}
        </span>
        <span className="text-[10px] font-telemetry px-2 py-0.5 rounded bg-steel/10 text-steel">
          {ev.corner_phase}
        </span>
        {confidence >= 0.85 && (
          <span className="text-[9px] font-telemetry px-1.5 py-0.5 rounded bg-acid-green/15 text-acid-green ml-auto">
            CONFIRMED
          </span>
        )}
      </div>

      {/* Cause text */}
      {(ev.cause_detail || ev.cause) && (
        <p className="text-chalk/70 text-sm font-body mt-1.5">{ev.cause_detail || ev.cause}</p>
      )}

      {/* Expandable detector votes */}
      {hasVotes && (
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="text-[10px] font-telemetry text-steel hover:text-chalk mt-2 transition-colors"
        >
          {expanded ? 'Hide' : 'Show'} detector votes
        </button>
      )}

      {expanded && ev.detector_votes && (
        <div className="mt-2 space-y-1">
          {Object.entries(ev.detector_votes)
            .sort(([, a], [, b]) => Math.abs(b.direction) - Math.abs(a.direction))
            .map(([name, vote]) => (
              <div key={name} className="flex items-center gap-2">
                <span className="text-[9px] font-telemetry text-steel w-28 truncate">{name}</span>
                <div className="flex-1 h-1 bg-steel/10 rounded-full relative">
                  <div
                    className={`absolute h-full rounded-full ${vote.direction > 0 ? 'bg-safety-red/60' : 'bg-racing-purple/60'}`}
                    style={{
                      width: `${Math.abs(vote.direction) * 50}%`,
                      left: vote.direction > 0 ? '50%' : `${50 - Math.abs(vote.direction) * 50}%`,
                    }}
                  />
                  <div className="absolute w-px h-full bg-steel/30 left-1/2" />
                </div>
                <span className="text-[9px] font-telemetry text-steel/60 w-8 text-right">
                  {(vote.direction > 0 ? '+' : '') + vote.direction.toFixed(1)}
                </span>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}
