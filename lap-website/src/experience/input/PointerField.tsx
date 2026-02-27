'use client';

import { useEffect, useRef } from 'react';
import { useKernelStore } from '@/experience/state/store';
import { physics } from '@/experience/motion/springs';

export function PointerField() {
  const setPointer = useKernelStore((s) => s.setPointer);
  const setPointerMagnetism = useKernelStore((s) => s.setPointerMagnetism);
  const reducedMotion = useKernelStore((s) => s.reducedMotion);
  const rafRef = useRef(0);

  useEffect(() => {
    if (reducedMotion) return;

    let rawX = 0.5;
    let rawY = 0.5;

    const handleMove = (e: PointerEvent) => {
      rawX = e.clientX / window.innerWidth;
      rawY = e.clientY / window.innerHeight;
      setPointer(rawX, rawY);
    };

    const computeMagnetism = () => {
      const interactives = document.querySelectorAll(
        'a, button, [role="button"], input, [data-magnetic]'
      );

      let nearestDist = Infinity;
      let pullX = 0;
      let pullY = 0;

      const px = rawX * window.innerWidth;
      const py = rawY * window.innerHeight;

      interactives.forEach((el) => {
        const rect = el.getBoundingClientRect();
        const cx = rect.left + rect.width / 2;
        const cy = rect.top + rect.height / 2;
        const dx = cx - px;
        const dy = cy - py;
        const dist = Math.sqrt(dx * dx + dy * dy);

        if (dist < physics.magnetismRadius && dist < nearestDist) {
          nearestDist = dist;
          const falloff = Math.pow(
            1 - dist / physics.magnetismRadius,
            physics.magnetismDecay
          );
          pullX = (dx / dist) * falloff * physics.magnetismStrength;
          pullY = (dy / dist) * falloff * physics.magnetismStrength;
        }
      });

      setPointerMagnetism(pullX, pullY);
      rafRef.current = requestAnimationFrame(computeMagnetism);
    };

    window.addEventListener('pointermove', handleMove, { passive: true });
    rafRef.current = requestAnimationFrame(computeMagnetism);

    return () => {
      window.removeEventListener('pointermove', handleMove);
      cancelAnimationFrame(rafRef.current);
    };
  }, [reducedMotion, setPointer, setPointerMagnetism]);

  return null;
}
