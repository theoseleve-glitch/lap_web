'use client';

import { useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { useKernelStore } from '@/experience/state/store';

export function StudioLight() {
  const lightRef = useRef<THREE.DirectionalLight>(null);
  const fillRef = useRef<THREE.DirectionalLight>(null);

  useFrame(() => {
    const light = lightRef.current;
    const fill = fillRef.current;
    if (!light) return;

    const state = useKernelStore.getState();
    const { globalProgress, scrollVelocity, qualityTier, reducedMotion } = state;

    if (qualityTier === 'low' || reducedMotion) {
      light.position.set(0, 5, 8);
      light.intensity = 0.4;
      return;
    }

    // Sweep arc — follows global scroll progress
    const theta = globalProgress * Math.PI * 0.6 - Math.PI * 0.3;
    light.position.set(
      Math.sin(theta) * 5,
      Math.cos(theta) * 5,
      8
    );

    // Velocity-modulated intensity
    light.intensity = 0.5 + Math.abs(scrollVelocity) * 0.8;

    // Counter-fill from opposite side
    if (fill) {
      fill.position.set(
        -Math.sin(theta) * 4,
        -Math.cos(theta) * 4,
        6
      );
      fill.intensity = 0.15 + Math.abs(scrollVelocity) * 0.2;
    }
  });

  return (
    <>
      {/* Neutral key light */}
      <directionalLight
        ref={lightRef}
        color="#FFFFFF"
        intensity={0.5}
        position={[0, 5, 8]}
      />
      {/* Soft fill from opposite side */}
      <directionalLight
        ref={fillRef}
        color="#CCCCCC"
        intensity={0.15}
        position={[0, -5, 6]}
      />
    </>
  );
}
