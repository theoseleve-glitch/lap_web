'use client';

import { useMemo } from 'react';
import { useKernelStore } from '@/experience/state/store';
import { colors } from '@/lib/tokens';

export function DeltaHud() {
  const value = useKernelStore((s) => s.hudDelta.value);
  const jitter = useKernelStore((s) => s.hudDelta.jitter);
  const settled = useKernelStore((s) => s.hudDelta.settled);

  const isGain = value < 0;
  const formatted = `${value >= 0 ? '+' : ''}${value.toFixed(2)}s`;
  const deltaColor = isGain ? colors.acidGreen : colors.safetyRed;

  // Compute jitter offset — random-ish but deterministic per render
  const jitterOffset = useMemo(() => {
    if (settled || jitter === 0) return { x: 0, y: 0 };
    // Use value as a seed for pseudo-random offset
    const seed = Math.abs(value * 1000) % 1;
    return {
      x: (seed - 0.5) * jitter,
      y: ((seed * 7.3) % 1 - 0.5) * jitter,
    };
  }, [value, jitter, settled]);

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
          transform: `translate(${jitterOffset.x}px, ${jitterOffset.y}px)`,
          display: 'inline-block',
        }}
      >
        {formatted}
      </span>
    </div>
  );
}
