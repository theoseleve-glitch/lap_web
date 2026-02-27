'use client';

import { useKernelStore } from '@/experience/state/store';
import { colors } from '@/lib/tokens';

export function DeltaHud() {
  const value = useKernelStore((s) => s.hudDelta.value);

  const isGain = value < 0;
  const formatted = `${value >= 0 ? '+' : ''}${value.toFixed(2)}s`;
  const deltaColor = isGain ? colors.acidGreen : colors.safetyRed;

  return (
    <div
      className="fixed bottom-6 right-6 pointer-events-none"
      style={{ zIndex: 'var(--z-delta)' as unknown as number }}
      aria-hidden="true"
    >
      <span
        className="font-telemetry text-[13px] tracking-[0.12em] tabular-nums transition-colors duration-[420ms]"
        style={{
          color: value === 0 ? 'var(--steel)' : deltaColor,
          display: 'inline-block',
        }}
      >
        {formatted}
      </span>
    </div>
  );
}
