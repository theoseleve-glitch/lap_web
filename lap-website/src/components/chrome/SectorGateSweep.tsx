'use client';

import { useEffect, useRef } from 'react';
import gsap from 'gsap';
import { useKernelStore } from '@/experience/state/store';
import { timing, easing, colors } from '@/lib/tokens';

export function SectorGateSweep() {
  const sectors = useKernelStore((s) => s.hudTower.sectors);
  const lineRef = useRef<HTMLDivElement>(null);
  const prevCompletedRef = useRef<number>(0);

  useEffect(() => {
    const completedCount = sectors.filter((s) => s.status === 'completed').length;

    // Only trigger on new completions
    if (completedCount > prevCompletedRef.current && lineRef.current) {
      const el = lineRef.current;
      el.style.opacity = '1';

      gsap.fromTo(
        el,
        { scaleX: 0, transformOrigin: 'left center' },
        {
          scaleX: 1,
          duration: timing.sectorGate,
          ease: easing.sectorGate,
          onComplete: () => {
            el.style.opacity = '0';
          },
        },
      );
    }

    prevCompletedRef.current = completedCount;
  }, [sectors]);

  return (
    <div
      ref={lineRef}
      className="fixed top-0 left-0 w-full pointer-events-none"
      style={{
        height: '2px',
        background: colors.racingPurple,
        opacity: 0,
        zIndex: 'var(--z-hud)' as unknown as number,
      }}
      aria-hidden="true"
    />
  );
}
