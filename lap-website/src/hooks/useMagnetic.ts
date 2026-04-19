'use client';

import { useEffect, useRef, useCallback } from 'react';
import { gsap } from 'gsap';

interface MagneticOptions {
  radius?: number;
  strength?: number;
  disabled?: boolean;
}

export function useMagnetic<T extends HTMLElement>(options: MagneticOptions = {}) {
  const ref = useRef<T>(null);
  const { radius = 80, strength = 0.3, disabled = false } = options;

  const handleMove = useCallback(
    (e: MouseEvent) => {
      if (!ref.current) return;
      const rect = ref.current.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      const dx = e.clientX - cx;
      const dy = e.clientY - cy;
      const dist = Math.sqrt(dx * dx + dy * dy);

      if (dist < radius) {
        const pull = (1 - dist / radius) * strength;
        gsap.to(ref.current, {
          x: dx * pull,
          y: dy * pull,
          duration: 0.4,
          ease: 'power3.out',
        });
      } else {
        gsap.to(ref.current, {
          x: 0,
          y: 0,
          duration: 0.6,
          ease: 'elastic.out(1, 0.5)',
        });
      }
    },
    [radius, strength],
  );

  const handleLeave = useCallback(() => {
    if (!ref.current) return;
    gsap.to(ref.current, {
      x: 0,
      y: 0,
      duration: 0.6,
      ease: 'elastic.out(1, 0.5)',
    });
  }, []);

  useEffect(() => {
    if (disabled || typeof window === 'undefined') return;
    if (window.matchMedia('(pointer: coarse)').matches) return;

    const el = ref.current;
    window.addEventListener('mousemove', handleMove);
    el?.addEventListener('mouseleave', handleLeave);

    return () => {
      window.removeEventListener('mousemove', handleMove);
      el?.removeEventListener('mouseleave', handleLeave);
    };
  }, [disabled, handleMove, handleLeave]);

  return ref;
}
