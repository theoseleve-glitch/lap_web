'use client';

import { useEffect, useRef } from 'react';
import { useKernelStore } from '@/experience/state/store';
import { background as bgTokens } from '@/experience/motion/springs';
import {
  buildTrackCurve,
  sampleTrack,
  scrollToTrackT,
  curvatureAtT,
  computeCornerValues,
} from './trackGeometry';

// Pre-compute track data once at module level (pure math, no side effects)
const curve = buildTrackCurve();
const samples = sampleTrack(curve, 300);

/**
 * Headless controller that bridges scroll state → background store state.
 * Lives in the DOM (inside ExperienceKernel), not inside R3F.
 * Runs every animation frame to lerp corner values and compute streak intensity.
 */
export function BackgroundController() {
  const rafRef = useRef<number>(0);
  const yawRef = useRef(0);
  const bankRef = useRef(0);
  const sweepAngleRef = useRef(0);

  useEffect(() => {
    let lastTime = performance.now();

    function tick() {
      const now = performance.now();
      const dt = Math.min((now - lastTime) / 1000, 0.05); // cap at 50ms
      lastTime = now;

      const state = useKernelStore.getState();
      const { globalProgress, scrollVelocity, currentChapter, reducedMotion } = state;

      // 1. Compute trackT from scroll position
      const trackT = scrollToTrackT(globalProgress, currentChapter);

      // 2. Look up curvature at current trackT
      const curvature = curvatureAtT(samples, trackT);
      const targets = computeCornerValues(curvature);

      // 3. Lerp corner yaw/bank toward target
      if (reducedMotion) {
        yawRef.current = 0;
        bankRef.current = 0;
      } else {
        const lerp = bgTokens.cornerLerp;
        yawRef.current += (targets.yaw - yawRef.current) * lerp;
        bankRef.current += (targets.bank - bankRef.current) * lerp;
      }

      // 4. Compute streak intensity from scroll velocity
      const absVel = Math.abs(scrollVelocity);
      const streakIntensity = reducedMotion
        ? 0
        : Math.max(0, (absVel - bgTokens.streakSpawnThreshold) / (1 - bgTokens.streakSpawnThreshold));

      // 5. Advance light sweep angle
      if (!reducedMotion) {
        sweepAngleRef.current += bgTokens.lightSweepSpeed * dt;
      }

      // 6. Write to store
      const store = useKernelStore.getState();
      const bg = store.background;
      const needsUpdate =
        Math.abs(bg.cornerYaw - yawRef.current) > 0.001 ||
        Math.abs(bg.cornerBank - bankRef.current) > 0.001 ||
        Math.abs(bg.streakIntensity - streakIntensity) > 0.001 ||
        Math.abs(bg.ribbonProgress - trackT) > 0.001 ||
        Math.abs(bg.lightSweepAngle - sweepAngleRef.current) > 0.01;

      if (needsUpdate) {
        store.setCornerYaw(yawRef.current);
        store.setCornerBank(bankRef.current);
        store.setStreakIntensity(streakIntensity);
        store.setRibbonProgress(trackT);
        store.setLightSweepAngle(sweepAngleRef.current);
      }

      rafRef.current = requestAnimationFrame(tick);
    }

    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, []);

  return null; // headless
}
