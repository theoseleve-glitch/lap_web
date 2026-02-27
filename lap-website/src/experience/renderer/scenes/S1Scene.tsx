'use client';
import { useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { LivingSurface } from './LivingSurface';
import type { ChapterSceneProps } from '@/experience/state/types';

export function S1Scene(props: ChapterSceneProps) {
  const lightRef = useRef<THREE.PointLight>(null);

  // Distortion light reacts to pointer (stand-in for CornerDrag reactivity)
  useFrame(() => {
    if (!lightRef.current || !props.active) return;
    lightRef.current.position.x = (props.pointerX - 0.5) * 8;
    lightRef.current.position.y = (props.pointerY - 0.5) * 5;
  });

  return (
    <group>
      <LivingSurface {...props} color="#0B0C0F" fogDensity={0.03} />
      {props.active && (
        <pointLight
          ref={lightRef}
          color="#B6FF2E"
          intensity={0.4}
          distance={15}
          decay={2}
        />
      )}
    </group>
  );
}
