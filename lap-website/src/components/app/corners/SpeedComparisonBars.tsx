'use client';

import { useEffect, useState } from 'react';
import type { CornerData } from './useCornerData';

interface SpeedBarRow {
  label: string;
  actual: number | null | undefined;
  theory: number | null | undefined;
  delay: number;
}

function toKmh(mps: number): number {
  return mps * 3.6;
}

function formatSpeed(kmh: number): string {
  return kmh.toFixed(1);
}

export function SpeedComparisonBars({ corner }: { corner: CornerData }) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const rows: SpeedBarRow[] = [
    { label: 'Entry', actual: corner.entry_speed_actual, theory: corner.entry_speed_theory, delay: 0 },
    { label: 'Apex', actual: corner.apex_speed_actual, theory: corner.apex_speed_theory, delay: 100 },
    { label: 'Exit', actual: corner.exit_speed_actual, theory: corner.exit_speed_theory, delay: 200 },
  ];

  return (
    <div className="border-b border-steel/20 py-5 space-y-3">
      {rows.map((row) => {
        const hasActual = row.actual != null;
        const hasTheory = row.theory != null;

        if (!hasActual) return null;

        const actualKmh = toKmh(row.actual!);
        const theoryKmh = hasTheory ? toKmh(row.theory!) : null;
        const maxSpeed = Math.max(actualKmh, theoryKmh ?? 0) * 1.15;
        const actualPct = (actualKmh / maxSpeed) * 100;
        const theoryPct = theoryKmh != null ? (theoryKmh / maxSpeed) * 100 : null;
        const delta = theoryKmh != null ? actualKmh - theoryKmh : null;

        return (
          <div key={row.label} className="flex items-center gap-3">
            {/* Label */}
            <span className="text-steel text-xs font-telemetry uppercase w-10 shrink-0">
              {row.label}
            </span>

            {/* Bar track */}
            <div className="relative h-6 flex-1 bg-concrete rounded" style={{ borderRadius: 4 }}>
              {/* Filled bar */}
              <div
                className="absolute inset-y-0 left-0 rounded"
                style={{
                  width: mounted ? `${actualPct}%` : '0%',
                  background: 'linear-gradient(90deg, rgba(163,230,53,0.25), rgba(163,230,53,0.45))',
                  borderRadius: 4,
                  transition: `width 300ms ease-out`,
                  transitionDelay: `${row.delay}ms`,
                }}
              />

              {/* Theoretical dashed line */}
              {theoryPct != null && (
                <div
                  className="absolute top-0 bottom-0 border-l-2 border-dashed border-chalk/50"
                  style={{ left: `${theoryPct}%` }}
                />
              )}

              {/* Actual speed label inside bar */}
              <span className="absolute left-2 top-1/2 -translate-y-1/2 text-chalk text-xs font-mono leading-none">
                {formatSpeed(actualKmh)}
              </span>
            </div>

            {/* Right-side values */}
            {hasTheory ? (
              <>
                <span className="text-acid-green text-xs font-mono w-14 text-right shrink-0">
                  {formatSpeed(theoryKmh!)}
                </span>
                <span
                  className={`text-xs font-telemetry w-14 text-right shrink-0 ${
                    delta! >= 0 ? 'text-green-400' : 'text-red-400'
                  }`}
                >
                  {delta! >= 0 ? '+' : ''}{formatSpeed(delta!)}
                </span>
              </>
            ) : (
              <span className="text-steel text-xs font-telemetry italic w-28 text-right shrink-0">
                actual only
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
