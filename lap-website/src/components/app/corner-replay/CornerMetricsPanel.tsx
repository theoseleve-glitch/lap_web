'use client';

import type { CornerMetric, CornerReplayCorner } from '@/types/corner-replay';

interface CornerMetricsPanelProps {
  corner: CornerReplayCorner;
  metrics: CornerMetric[];
  selectedLap: number;
}

function mpsToKph(mps: number | null): string {
  if (mps == null) return '--';
  return `${(mps * 3.6).toFixed(1)} km/h`;
}

export function CornerMetricsPanel({ corner, metrics, selectedLap }: CornerMetricsPanelProps) {
  const lapMetric = metrics.find((m) => m.lap_number === selectedLap);

  return (
    <div className="rounded-lg border border-steel/20 bg-concrete p-4">
      <h3 className="font-telemetry text-xs font-bold text-chalk mb-3">
        {corner.label || `Corner ${corner.corner_id}`}
      </h3>

      {!lapMetric ? (
        <p className="text-steel text-xs font-telemetry">No metrics for this lap</p>
      ) : (
        <div className="space-y-3">
          {/* Speed metrics */}
          <div className="grid grid-cols-3 gap-2">
            <div>
              <p className="text-steel font-telemetry text-[10px] uppercase tracking-wider">Entry</p>
              <p className="text-chalk font-telemetry text-sm">{mpsToKph(lapMetric.entry_speed_mps)}</p>
            </div>
            <div>
              <p className="text-steel font-telemetry text-[10px] uppercase tracking-wider">Apex</p>
              <p className="text-chalk font-telemetry text-sm">{mpsToKph(lapMetric.apex_speed_mps)}</p>
            </div>
            <div>
              <p className="text-steel font-telemetry text-[10px] uppercase tracking-wider">Exit</p>
              <p className="text-chalk font-telemetry text-sm">{mpsToKph(lapMetric.exit_speed_mps)}</p>
            </div>
          </div>

          {/* Brake point + time loss */}
          <div className="grid grid-cols-2 gap-2">
            <div>
              <p className="text-steel font-telemetry text-[10px] uppercase tracking-wider">Brake</p>
              <p className="text-chalk font-telemetry text-sm">
                {lapMetric.brake_point_m != null ? `${lapMetric.brake_point_m.toFixed(0)}m` : '--'}
              </p>
            </div>
            <div>
              <p className="text-steel font-telemetry text-[10px] uppercase tracking-wider">Time Loss</p>
              <p className={`font-telemetry text-sm ${
                (lapMetric.time_loss_ms ?? 0) > 100 ? 'text-safety-red' :
                (lapMetric.time_loss_ms ?? 0) > 50 ? 'text-amber-400' : 'text-acid-green'
              }`}>
                {lapMetric.time_loss_ms != null ? `+${lapMetric.time_loss_ms.toFixed(0)}ms` : '--'}
              </p>
            </div>
          </div>

          {/* Coaching hint */}
          {lapMetric.coaching_hint && (
            <div className="mt-2 rounded bg-acid-green/5 border border-acid-green/20 px-3 py-2">
              <p className="text-acid-green font-telemetry text-xs">{lapMetric.coaching_hint}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
