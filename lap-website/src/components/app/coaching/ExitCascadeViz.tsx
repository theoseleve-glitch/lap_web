'use client';

import type { ExitCascade } from './types';

interface ExitCascadeVizProps {
  cascade?: ExitCascade | null;
}

export default function ExitCascadeViz({ cascade }: ExitCascadeVizProps) {
  if (!cascade) return null;

  const hasDelta = cascade.exit_speed_delta_kph != null;
  const hasLoss = cascade.straight_time_loss_s != null;
  const hasTotal = cascade.total_cascade_s != null;

  if (!hasDelta && !hasLoss && !hasTotal) return null;

  return (
    <div className="space-y-2">
      <span className="text-xs text-steel font-telemetry uppercase tracking-wider">Exit Cascade</span>

      <div className="flex items-center gap-2 flex-wrap">
        {hasDelta && (
          <>
            <div className="bg-asphalt rounded-lg px-3 py-2 text-center">
              <div className="text-xs text-steel font-telemetry">Exit Speed</div>
              <div className="text-sm font-monument text-marshal-yellow">
                {cascade.exit_speed_delta_kph! > 0 ? '+' : ''}
                {cascade.exit_speed_delta_kph!.toFixed(1)} kph
              </div>
            </div>
            <span className="text-steel text-xs font-telemetry">&rarr;</span>
          </>
        )}

        {hasLoss && (
          <>
            <div className="bg-asphalt rounded-lg px-3 py-2 text-center">
              <div className="text-xs text-steel font-telemetry">Straight Loss</div>
              <div className="text-sm font-monument text-safety-red">
                +{cascade.straight_time_loss_s!.toFixed(3)}s
              </div>
            </div>
            {hasTotal && <span className="text-steel text-xs font-telemetry">&rarr;</span>}
          </>
        )}

        {hasTotal && (
          <div className="bg-safety-red/10 border border-safety-red/20 rounded-lg px-3 py-2 text-center">
            <div className="text-xs text-steel font-telemetry">Total</div>
            <div className="text-sm font-monument text-safety-red">
              +{cascade.total_cascade_s!.toFixed(3)}s
            </div>
          </div>
        )}
      </div>

      {cascade.corner_name && (
        <span className="text-xs text-chalk/40 font-body">{cascade.corner_name}</span>
      )}
    </div>
  );
}
