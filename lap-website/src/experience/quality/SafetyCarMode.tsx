'use client';

import { useEffect, useRef } from 'react';
import { useKernelStore } from '@/experience/state/store';

const LOW_FPS_THRESHOLD = 24;
const LOW_FPS_DURATION = 3000;  // 3 seconds
const RECOVERY_FPS = 40;
const RECOVERY_DURATION = 5000; // 5 seconds

/**
 * SafetyCarMode — monitors FPS and automatically disables canvas
 * when performance is too low. Shows CSS fallback + badge.
 *
 * - FPS < 24 for 3s → enter Safety Car (disable canvas)
 * - FPS > 40 for 5s (after Safety Car) → attempt recovery at lower tier
 * - WebGL context lost → permanent Safety Car
 */
export function SafetyCarMode() {
  const enterSafetyCar = useKernelStore((s) => s.enterSafetyCar);
  const exitSafetyCar = useKernelStore((s) => s.exitSafetyCar);
  const setQualityTier = useKernelStore((s) => s.setQualityTier);

  const framesRef = useRef<number[]>([]);
  const lowStartRef = useRef(0);
  const recoveryStartRef = useRef(0);

  useEffect(() => {
    let rafId: number;
    let lastTime = performance.now();

    function tick() {
      const now = performance.now();
      const dt = now - lastTime;
      lastTime = now;

      if (dt > 0) {
        framesRef.current.push(1000 / dt);
        if (framesRef.current.length > 60) framesRef.current.shift();
      }

      if (framesRef.current.length >= 30) {
        const avg = framesRef.current.reduce((a, b) => a + b, 0) / framesRef.current.length;
        const { safetyCar } = useKernelStore.getState();

        if (!safetyCar.active) {
          if (avg < LOW_FPS_THRESHOLD) {
            if (lowStartRef.current === 0) lowStartRef.current = now;
            if (now - lowStartRef.current > LOW_FPS_DURATION) {
              enterSafetyCar('sustained-low-fps');
              lowStartRef.current = 0;
            }
          } else {
            lowStartRef.current = 0;
          }
        } else {
          if (avg > RECOVERY_FPS) {
            if (recoveryStartRef.current === 0) recoveryStartRef.current = now;
            if (now - recoveryStartRef.current > RECOVERY_DURATION) {
              setQualityTier('low');
              exitSafetyCar();
              recoveryStartRef.current = 0;
            }
          } else {
            recoveryStartRef.current = 0;
          }
        }
      }

      rafId = requestAnimationFrame(tick);
    }

    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, [enterSafetyCar, exitSafetyCar, setQualityTier]);

  // Listen for WebGL context loss
  useEffect(() => {
    const handler = () => {
      enterSafetyCar('webgl-context-lost');
    };
    const canvas = document.querySelector('canvas');
    if (canvas) {
      canvas.addEventListener('webglcontextlost', handler);
      return () => canvas.removeEventListener('webglcontextlost', handler);
    }
  }, [enterSafetyCar]);

  return null;
}
