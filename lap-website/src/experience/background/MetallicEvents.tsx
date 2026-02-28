'use client';

import { useEffect, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import type { Mesh, MeshBasicMaterial } from 'three';
import { useKernelStore } from '@/experience/state/store';
import { background as bgTokens } from '@/experience/motion/springs';

interface ActiveEvent {
  type: 'sector' | 'drs' | 'finish' | 'guidance';
  startTime: number;
  duration: number;
}

const DURATIONS = bgTokens.metallicFlashDuration;

/**
 * Headless R3F component — detects narrative events and modulates
 * the edge material and light intensity for visual feedback.
 */
export function MetallicEvents() {
  const eventsRef = useRef<ActiveEvent[]>([]);
  const prevSectorRef = useRef(-1);
  const prevDrsRef = useRef(false);
  const prevFinishRef = useRef(false);
  const prevScrollDirRef = useRef<string>('idle');

  useEffect(() => {
    const init = useKernelStore.getState();
    prevSectorRef.current = init.hudTower.activeSectorIndex;
    prevDrsRef.current = init.drs.active;
    prevFinishRef.current = init.finish.crossed;
    prevScrollDirRef.current = init.scrollDirection;

    const unsub = useKernelStore.subscribe((state) => {
      const sectorIdx = state.hudTower.activeSectorIndex;
      if (sectorIdx > prevSectorRef.current && prevSectorRef.current >= 0) {
        eventsRef.current.push({
          type: 'sector', startTime: performance.now(), duration: DURATIONS.sector,
        });
      }
      prevSectorRef.current = sectorIdx;

      if (state.drs.active && !prevDrsRef.current) {
        eventsRef.current.push({
          type: 'drs', startTime: performance.now(), duration: DURATIONS.drs,
        });
      }
      prevDrsRef.current = state.drs.active;

      if (state.finish.crossed && !prevFinishRef.current) {
        eventsRef.current.push({
          type: 'finish', startTime: performance.now(), duration: DURATIONS.finish,
        });
      }
      prevFinishRef.current = state.finish.crossed;

      if (state.scrollDirection === 'down' && prevScrollDirRef.current !== 'down') {
        eventsRef.current.push({
          type: 'guidance', startTime: performance.now(), duration: DURATIONS.guidance,
        });
      }
      prevScrollDirRef.current = state.scrollDirection;
    });

    return unsub;
  }, []);

  useFrame(({ scene }) => {
    const state = useKernelStore.getState();
    if (state.reducedMotion) {
      eventsRef.current = [];
      return;
    }

    const now = performance.now();
    const events = eventsRef.current;
    let eventIntensity = 0;

    // Compute max intensity from active events
    for (let i = events.length - 1; i >= 0; i--) {
      const evt = events[i];
      const elapsed = now - evt.startTime;
      if (elapsed >= evt.duration) {
        events.splice(i, 1);
        continue;
      }
      const progress = elapsed / evt.duration;
      const fade = 1 - progress;
      eventIntensity = Math.max(eventIntensity, fade);
    }

    // Boost edge material opacity during events
    scene.traverse((child) => {
      const m = child as Mesh;
      if (!m.isMesh || !m.material) return;
      const mat = m.material as MeshBasicMaterial;
      if (mat.blending === 2 && mat.color) { // AdditiveBlending = 2
        // Brighten additive materials during events
        const boost = 1 + eventIntensity * 0.5;
        mat.opacity = Math.min(mat.opacity * boost, 0.9);
      }
    });
  });

  return null;
}
