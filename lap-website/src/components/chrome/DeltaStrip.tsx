'use client';

import { useDelta } from '@/hooks/useDelta';
import { colors } from '@/lib/tokens';

export function DeltaStrip() {
  const { delta, totalDelta } = useDelta();
  const active = delta !== 0;
  const isGain = totalDelta < 0;

  return (
    <div
      className="fixed bottom-0 left-0 right-0 transition-all duration-[420ms]"
      style={{
        height: active ? '32px' : '4px',
        zIndex: 'var(--z-delta)' as unknown as number,
        background: colors.concrete,
      }}
    >
      {active && (
        <div className="relative h-full flex items-center justify-center">
          {/* Fill bar from center */}
          <div
            className="absolute top-0 h-full transition-all duration-[420ms]"
            style={{
              left: isGain ? `${50 - Math.min(Math.abs(totalDelta) * 50, 50)}%` : '50%',
              right: isGain ? '50%' : `${50 - Math.min(Math.abs(totalDelta) * 50, 50)}%`,
              background: isGain ? colors.acidGreen : colors.safetyRed,
              opacity: 0.6,
            }}
          />
          <span className="relative font-telemetry text-[11px] tracking-[0.12em]" aria-live="polite">
            {totalDelta >= 0 ? '+' : ''}{totalDelta.toFixed(2)}s
          </span>
        </div>
      )}
    </div>
  );
}
