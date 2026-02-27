'use client';

import { useEffect, useRef } from 'react';
import { useKernelStore } from '@/experience/state/store';

const DRS_DECAY_WINDOW = 500;
const DRS_MAX_MULTIPLIER = 1.4;

/** Store-coupled tick function — exported for testing */
export function tickDrs(dtMs: number) {
  const { drs } = useKernelStore.getState();
  if (!drs.active) return;

  const newRemaining = Math.max(0, drs.remaining - dtMs);

  if (newRemaining <= 0) {
    useKernelStore.getState().deactivateDrs();
    return;
  }

  // Decay multiplier in final 500ms
  let multiplier = DRS_MAX_MULTIPLIER;
  if (newRemaining < DRS_DECAY_WINDOW) {
    const t = newRemaining / DRS_DECAY_WINDOW; // 1→0
    multiplier = 1.0 + (DRS_MAX_MULTIPLIER - 1.0) * t;
  }

  useKernelStore.setState({
    drs: { ...drs, remaining: newRemaining, multiplier },
  });
}

export function DrsController() {
  const drsActive = useKernelStore((s) => s.drs.active);
  const rafRef = useRef<number>(0);
  const lastTimeRef = useRef(0);

  useEffect(() => {
    if (!drsActive) {
      lastTimeRef.current = 0;
      return;
    }

    function tick(time: number) {
      if (lastTimeRef.current === 0) {
        lastTimeRef.current = time;
      }
      const dt = time - lastTimeRef.current;
      lastTimeRef.current = time;

      tickDrs(dt);

      if (useKernelStore.getState().drs.active) {
        rafRef.current = requestAnimationFrame(tick);
      }
    }

    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [drsActive]);

  return null;
}
