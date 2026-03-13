'use client';

import { useState } from 'react';
import type { CornerCoachingDetail } from './types';
import SpeedTargets from './SpeedTargets';
import TractionBudgetViz from './TractionBudgetViz';
import TrailBrakeTimeline from './TrailBrakeTimeline';
import ExitCascadeViz from './ExitCascadeViz';
import CornerTrendChart from './CornerTrendChart';

interface CornerCoachingCardProps {
  corner: CornerCoachingDetail;
}

export default function CornerCoachingCard({ corner }: CornerCoachingCardProps) {
  const [expanded, setExpanded] = useState(false);

  const label = corner.corner_name ?? `Corner ${corner.corner_id}`;

  return (
    <div className="bg-concrete rounded-xl border border-steel/10 overflow-hidden">
      {/* Collapsed header */}
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 text-left hover:bg-asphalt/30 transition-colors"
      >
        <div className="flex items-center gap-3 min-w-0">
          <span className="text-sm font-monument text-chalk truncate">{label}</span>
          {corner.primary_cause && (
            <span className="text-xs font-telemetry text-marshal-yellow bg-marshal-yellow/10 px-2 py-0.5 rounded-full shrink-0">
              {corner.primary_cause}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {corner.time_loss_s != null && (
            <span className="text-xs font-telemetry text-safety-red">
              +{corner.time_loss_s.toFixed(3)}s
            </span>
          )}
          <span
            className="text-steel text-xs transition-transform"
            style={{ display: 'inline-block', transform: expanded ? 'rotate(180deg)' : 'none' }}
          >
            v
          </span>
        </div>
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="px-4 pb-4 space-y-4 border-t border-steel/5">
          {/* Coaching tip */}
          {corner.coaching_tip && (
            <p className="text-xs text-chalk/80 font-body leading-relaxed pt-3">
              {corner.coaching_tip}
            </p>
          )}

          {/* Progressive steps */}
          {corner.progressive_steps && corner.progressive_steps.length > 0 && (
            <ol className="space-y-2">
              {corner.progressive_steps.map((step, i) => (
                <li key={i} className="flex gap-3 items-start">
                  <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-acid-green/20 text-acid-green text-xs font-telemetry shrink-0">
                    {i + 1}
                  </span>
                  <span className="text-xs text-chalk/70 font-body leading-relaxed">{step}</span>
                </li>
              ))}
            </ol>
          )}

          {/* Speed targets */}
          <SpeedTargets targets={corner.speed_targets} />

          {/* Traction budget */}
          <TractionBudgetViz budget={corner.traction_budget} />

          {/* Trail brake timeline */}
          <TrailBrakeTimeline data={corner.trail_brake} />

          {/* Exit cascade */}
          <ExitCascadeViz cascade={corner.exit_cascade} />

          {/* Trend chart */}
          <CornerTrendChart
            apex_speed_history={corner.apex_speed_history}
            sessions_tracked={corner.sessions_tracked}
            trend_direction={corner.trend_direction}
          />
        </div>
      )}
    </div>
  );
}
