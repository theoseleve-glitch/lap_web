import { useRef, useCallback } from 'react';
import { useKernelStore } from '@/experience/state/store';
import { reveal as revealPhysics } from '@/experience/motion/springs';
import type { QualityTier } from '@/experience/state/types';

interface Vec2 {
  x: number;
  y: number;
}

/** Linear interpolation for pointer with inertia */
export function lerpPointer(current: Vec2, target: Vec2, factor: number): Vec2 {
  return {
    x: current.x + (target.x - current.x) * factor,
    y: current.y + (target.y - current.y) * factor,
  };
}

/** Mask FBO resolution per quality tier */
export function computeMaskResolution(tier: QualityTier): number {
  switch (tier) {
    case 'high': return 1024;
    case 'balanced': return 512;
    case 'low': return 0; // no FBO, fallback to simple radial
  }
}

/** Hook providing smoothed pointer and brush parameters for the reveal pipeline */
export function useRevealState() {
  const smoothedRef = useRef<Vec2>({ x: 0.5, y: 0.5 });
  const lastMoveRef = useRef(Date.now());

  const getSmoothedPointer = useCallback((rawX: number, rawY: number): Vec2 => {
    lastMoveRef.current = Date.now();
    smoothedRef.current = lerpPointer(
      smoothedRef.current,
      { x: rawX, y: rawY },
      revealPhysics.inertiaLerp,
    );
    return smoothedRef.current;
  }, []);

  const isIdle = useCallback((): boolean => {
    return Date.now() - lastMoveRef.current > revealPhysics.idleTimeout;
  }, []);

  const getDecayFactor = useCallback((): number => {
    return isIdle() ? revealPhysics.idleDecayRate : revealPhysics.decayFactor;
  }, [isIdle]);

  const getBrushRadius = useCallback((): number => {
    const drsMultiplier = useKernelStore.getState().drs.multiplier;
    return revealPhysics.brushRadius * drsMultiplier;
  }, []);

  return {
    getSmoothedPointer,
    isIdle,
    getDecayFactor,
    getBrushRadius,
    smoothedRef,
  };
}
