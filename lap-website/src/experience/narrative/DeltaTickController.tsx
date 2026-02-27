'use client';

import { useEffect, useRef } from 'react';
import { useKernelStore } from '@/experience/state/store';

const MAX_JITTER = 8;
const BASE_DELTA = 0.5; // starting "time loss" in seconds

/** Pure function: map mask coverage (0-1) to jitter amplitude (8-0) */
export function computeDeltaJitter(maskCoverage: number): number {
  return MAX_JITTER * (1 - Math.max(0, Math.min(1, maskCoverage)));
}

/** Pure function: delta trends from base toward 0 as globalProgress increases */
export function computeDeltaValue(base: number, globalProgress: number): number {
  return base * (1 - Math.max(0, Math.min(1, globalProgress)));
}

export function DeltaTickController() {
  const maskCoverage = useKernelStore((s) => s.reveal.maskCoverage);
  const globalProgress = useKernelStore((s) => s.globalProgress);
  const settled = useKernelStore((s) => s.hudDelta.settled);
  const setDeltaJitter = useKernelStore((s) => s.setDeltaJitter);
  const setDeltaValue = useKernelStore((s) => s.setDeltaValue);
  const rafRef = useRef<number>(0);

  useEffect(() => {
    if (settled) return;

    function tick() {
      const jitter = computeDeltaJitter(maskCoverage);
      setDeltaJitter(jitter);

      const value = computeDeltaValue(BASE_DELTA, globalProgress);
      setDeltaValue(value);

      rafRef.current = requestAnimationFrame(tick);
    }

    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [maskCoverage, globalProgress, settled, setDeltaJitter, setDeltaValue]);

  return null;
}
