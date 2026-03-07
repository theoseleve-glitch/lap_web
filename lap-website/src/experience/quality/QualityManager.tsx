'use client';

import { useEffect, useRef } from 'react';
import { useKernelStore } from '@/experience/state/store';
import type { QualityTier } from '@/experience/state/types';

const TIER_ORDER: QualityTier[] = ['high', 'balanced', 'low'];

export function QualityManager() {
  const setQualityTier = useKernelStore((s) => s.setQualityTier);
  const setReducedMotion = useKernelStore((s) => s.setReducedMotion);
  const setWebglAvailable = useKernelStore((s) => s.setWebglAvailable);
  const qualityMode = useKernelStore((s) => s.qualityMode);
  const framesRef = useRef<number[]>([]);
  const initialTierRef = useRef<QualityTier>('high');
  const currentTierRef = useRef<QualityTier>('high');
  const lowStartRef = useRef(0);
  const highStartRef = useRef(0);

  useEffect(() => {
    try {
      const canvas = document.createElement('canvas');
      const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
      setWebglAvailable(!!gl);
    } catch {
      setWebglAvailable(false);
    }

    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    setReducedMotion(mq.matches);
    const handler = (e: MediaQueryListEvent) => setReducedMotion(e.matches);
    mq.addEventListener('change', handler);

    if (window.matchMedia('(max-width: 767px)').matches) {
      initialTierRef.current = 'balanced';
      currentTierRef.current = 'balanced';
      setQualityTier('balanced');
    }

    return () => mq.removeEventListener('change', handler);
  }, [setReducedMotion, setWebglAvailable, setQualityTier]);

  useEffect(() => {
    if (qualityMode !== 'auto') return;

    let rafId: number;
    let lastTime = performance.now();

    function tick() {
      const now = performance.now();
      const dt = now - lastTime;
      lastTime = now;

      if (dt > 0) {
        framesRef.current.push(1000 / dt);
        if (framesRef.current.length > 120) framesRef.current.shift();
      }

      if (framesRef.current.length >= 30) {
        const avg =
          framesRef.current.reduce((a, b) => a + b, 0) /
          framesRef.current.length;

        const tierIdx = TIER_ORDER.indexOf(currentTierRef.current);

        if (avg < 30 && now - lowStartRef.current > 1000) {
          if (currentTierRef.current !== 'low') {
            currentTierRef.current = 'low';
            setQualityTier('low');
          }
          lowStartRef.current = now;
          highStartRef.current = 0;
        } else if (avg < 45) {
          if (lowStartRef.current === 0) lowStartRef.current = now;
          if (now - lowStartRef.current > 2000 && tierIdx < 2) {
            currentTierRef.current = TIER_ORDER[tierIdx + 1] ?? currentTierRef.current;
            setQualityTier(currentTierRef.current);
            lowStartRef.current = 0;
          }
          highStartRef.current = 0;
        } else if (avg > 55) {
          lowStartRef.current = 0;
          if (highStartRef.current === 0) highStartRef.current = now;
          const initialIdx = TIER_ORDER.indexOf(initialTierRef.current);
          if (now - highStartRef.current > 5000 && tierIdx > initialIdx) {
            currentTierRef.current = TIER_ORDER[tierIdx - 1] ?? currentTierRef.current;
            setQualityTier(currentTierRef.current);
            highStartRef.current = 0;
          }
        } else {
          lowStartRef.current = 0;
          highStartRef.current = 0;
        }
      }

      rafId = requestAnimationFrame(tick);
    }

    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, [qualityMode, setQualityTier]);

  return null;
}
