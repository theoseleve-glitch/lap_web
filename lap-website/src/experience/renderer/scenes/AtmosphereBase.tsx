'use client';

import { useRef, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import type { ChapterSceneProps } from '@/experience/state/types';

interface AtmosphereBaseProps extends ChapterSceneProps {
  color?: string;
  fogDensity?: number;
  particleCount?: number;
}

export function AtmosphereBase({
  color = '#0B0C0F',
  fogDensity = 0.03,
  particleCount = 200,
  progress,
  scrollVelocity,
  pointerX,
  pointerY,
  qualityTier,
  active,
}: AtmosphereBaseProps) {
  const groupRef = useRef<THREE.Group>(null);
  const particlesRef = useRef<THREE.Points>(null);

  const count = qualityTier === 'low' ? 0 : qualityTier === 'balanced' ? Math.floor(particleCount / 2) : particleCount;

  const positions = useMemo(() => {
    const arr = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      arr[i * 3] = (Math.random() - 0.5) * 20;
      arr[i * 3 + 1] = (Math.random() - 0.5) * 20;
      arr[i * 3 + 2] = (Math.random() - 0.5) * 10;
    }
    return arr;
  }, [count]);

  useFrame((_, delta) => {
    if (!active || !particlesRef.current) return;

    // Subtle drift influenced by pointer
    const px = (pointerX - 0.5) * 0.02;
    const py = (pointerY - 0.5) * 0.02;

    particlesRef.current.rotation.y += (px - particlesRef.current.rotation.y) * 0.05;
    particlesRef.current.rotation.x += (py - particlesRef.current.rotation.x) * 0.05;

    // Velocity-driven drift
    const posArray = particlesRef.current.geometry.attributes.position.array as Float32Array;
    const drift = scrollVelocity * delta * 2;
    for (let i = 1; i < posArray.length; i += 3) {
      posArray[i] += drift;
      if (posArray[i] > 10) posArray[i] = -10;
      if (posArray[i] < -10) posArray[i] = 10;
    }
    particlesRef.current.geometry.attributes.position.needsUpdate = true;
  });

  if (count === 0) return null;

  return (
    <group ref={groupRef} visible={active}>
      <fog attach="fog" args={[color, 5, 25]} />
      <ambientLight intensity={0.1} />

      <points ref={particlesRef}>
        <bufferGeometry>
          <bufferAttribute
            attach="attributes-position"
            args={[positions, 3]}
          />
        </bufferGeometry>
        <pointsMaterial
          size={0.03}
          color="#F3F0E8"
          transparent
          opacity={0.3}
          sizeAttenuation
          depthWrite={false}
        />
      </points>
    </group>
  );
}
