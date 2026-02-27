'use client';

import { useRef, useEffect, useState, useCallback } from 'react';
import { useKernelStore } from '@/experience/state/store';
import { colors } from '@/lib/tokens';

export function DeltaHud() {
  const value = useKernelStore((s) => s.hudDelta.value);
  const jitter = useKernelStore((s) => s.hudDelta.jitter);
  const settled = useKernelStore((s) => s.hudDelta.settled);

  const isGain = value < 0;
  const formatted = `${value >= 0 ? '+' : ''}${value.toFixed(2)}s`;
  const deltaColor = isGain ? colors.acidGreen : colors.safetyRed;

  // Time-based jitter using RAF for visual tremor even at constant values
  const [jitterOffset, setJitterOffset] = useState({ x: 0, y: 0 });
  const rafRef = useRef<number>(0);

  const tick = useCallback(() => {
    const { reducedMotion } = useKernelStore.getState();
    if (settled || jitter === 0 || reducedMotion) {
      setJitterOffset({ x: 0, y: 0 });
      return;
    }
    const t = performance.now() * 0.01;
    setJitterOffset({
      x: Math.sin(t * 1.7) * jitter * 0.5,
      y: Math.cos(t * 2.3) * jitter * 0.5,
    });
    rafRef.current = requestAnimationFrame(tick);
  }, [jitter, settled]);

  useEffect(() => {
    if (!settled && jitter > 0) {
      rafRef.current = requestAnimationFrame(tick);
    }
    return () => { cancelAnimationFrame(rafRef.current); };
  }, [tick, jitter, settled]);

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
