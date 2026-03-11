'use client';

import type { SpeedTarget } from './types';

interface SpeedTargetsProps {
  targets?: SpeedTarget[] | null;
}

const PHASE_ORDER = ['entry', 'apex', 'exit'] as const;

export default function SpeedTargets({ targets }: SpeedTargetsProps) {
  if (!targets || targets.length === 0) return null;

  const sorted = PHASE_ORDER
    .map((phase) => targets.find((t) => t.phase === phase))
    .filter(Boolean) as SpeedTarget[];

  if (sorted.length === 0) return null;

  const maxSpeed = Math.max(...sorted.map((t) => Math.max(t.actual_kph, t.target_kph)));

  return (
    <div className="space-y-2">
      <span className="text-xs text-steel font-telemetry uppercase tracking-wider">Speed Targets</span>
      {sorted.map((t) => {
        const actualPct = maxSpeed > 0 ? (t.actual_kph / maxSpeed) * 100 : 0;
        const targetPct = maxSpeed > 0 ? (t.target_kph / maxSpeed) * 100 : 0;
        const gap = t.target_kph - t.actual_kph;

        return (
          <div key={t.phase} className="space-y-1">
            <div className="flex items-center justify-between text-xs font-telemetry">
              <span className="text-chalk/60 capitalize">{t.phase}</span>
              <span className="text-steel">
                {t.actual_kph.toFixed(0)} / {t.target_kph.toFixed(0)} kph
                {gap > 0 && <span className="text-safety-red ml-1">(-{gap.toFixed(1)})</span>}
              </span>
            </div>
            <div className="relative h-3 bg-asphalt rounded-full overflow-hidden">
              <div
                className="absolute inset-y-0 left-0 bg-acid-green/60 rounded-full"
                style={{ width: `${actualPct}%` }}
              />
              <div
                className="absolute inset-y-0 left-0 border-r-2 border-chalk/40"
                style={{ width: `${targetPct}%` }}
              />
              {gap > 0 && (
                <div
                  className="absolute inset-y-0 bg-safety-red/30 rounded-r-full"
                  style={{ left: `${actualPct}%`, width: `${targetPct - actualPct}%` }}
                />
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
