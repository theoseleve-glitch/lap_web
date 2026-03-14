'use client';

import type { CornerData, CornerActionable } from './useCornerData';

interface VerdictSectionProps {
  corner: CornerData;
}

const PHASE_COLORS: Record<string, string> = {
  entry: 'bg-pit-orange/20 text-pit-orange',
  mid: 'bg-marshal-yellow/20 text-marshal-yellow',
  exit: 'bg-acid-green/20 text-acid-green',
};

export function VerdictSection({ corner }: VerdictSectionProps) {
  const hasData = corner.available && corner.time_loss_total_s != null;
  const timeLoss = corner.time_loss_total_s ?? 0;
  const isGain = timeLoss < 0;
  const actionables = corner.actionables?.filter((a) => a.impact_ms > 0) ?? [];

  return (
    <div className="flex gap-6 items-start py-5 border-b border-steel/20">
      {/* Time loss badge */}
      <div className="text-center min-w-[100px] shrink-0">
        {hasData ? (
          <>
            <div className={`text-4xl font-bold font-telemetry ${isGain ? 'text-acid-green' : 'text-safety-red'}`}>
              {isGain ? '+' : '-'}{Math.abs(timeLoss).toFixed(3)}s
            </div>
            <div className="text-[10px] text-steel uppercase tracking-widest mt-1 font-telemetry">
              Time {isGain ? 'Gained' : 'Lost'}
            </div>
          </>
        ) : (
          <>
            <div className="text-4xl font-bold font-telemetry text-steel">—</div>
            <div className="text-[10px] text-steel uppercase tracking-widest mt-1 font-telemetry">
              No theoretical data
            </div>
          </>
        )}
      </div>

      {/* Actionables or fallback */}
      <div className="flex-1 min-w-0">
        {actionables.length > 0 ? (
          <ol className="space-y-2.5">
            {actionables.map((a) => (
              <li key={a.rank} className="flex items-start gap-3">
                <span className={`shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-xs font-telemetry font-bold ${
                  a.rank === 1 ? 'bg-safety-red/20 text-safety-red' :
                  a.rank === 2 ? 'bg-pit-orange/20 text-pit-orange' :
                  'bg-steel/20 text-steel'
                }`}>
                  {a.rank}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-chalk text-sm font-body leading-snug">{a.action}</p>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className={`text-[10px] font-telemetry px-1.5 py-0.5 rounded ${PHASE_COLORS[a.phase] ?? 'bg-steel/20 text-steel'}`}>
                      {a.phase}
                    </span>
                    <span className="text-safety-red text-[10px] font-telemetry">
                      -{a.impact_ms.toFixed(0)}ms
                    </span>
                  </div>
                </div>
              </li>
            ))}
          </ol>
        ) : hasData && corner.coaching_hint ? (
          <>
            {corner.primary_cause && (
              <div className="flex items-center gap-2 mb-2">
                <span className="bg-safety-red/20 text-safety-red text-[11px] font-telemetry font-semibold px-2.5 py-0.5 rounded">
                  {corner.primary_cause.replace(/_/g, ' ').toUpperCase()}
                </span>
              </div>
            )}
            <p className="text-chalk/80 text-sm font-body leading-relaxed">
              {corner.coaching_hint}
            </p>
          </>
        ) : (
          <p className="text-steel text-sm font-body">
            No coaching data available for this corner.
          </p>
        )}
      </div>
    </div>
  );
}
