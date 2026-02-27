'use client';
import { useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { AtmosphereBase } from './AtmosphereBase';
import type { ChapterSceneProps } from '@/experience/state/types';

export function PodiumScene(props: ChapterSceneProps) {
  const lightRef = useRef<THREE.PointLight>(null);

  useFrame((state) => {
    if (!lightRef.current || !props.active) return;
    // Breathing glow
    lightRef.current.intensity = 0.3 + Math.sin(state.clock.elapsedTime * 0.8) * 0.15;
  });

  return (
    <group>
      <AtmosphereBase {...props} color="#0B0C0F" fogDensity={0.04} particleCount={300} />
      {props.active && (
        <pointLight
          ref={lightRef}
          color="#FF6A00"
          intensity={0.3}
          distance={20}
          decay={2}
          position={[0, 3, 2]}
        />
      )}
    </group>
  );
}
