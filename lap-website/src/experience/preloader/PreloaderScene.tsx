'use client';

import { useRef, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';

export function PreloaderScene() {
  const lightRef = useRef<THREE.PointLight>(null);

  const positions = useMemo(() => {
    const arr = new Float32Array(300 * 3);
    for (let i = 0; i < 300; i++) {
      arr[i * 3] = (Math.random() - 0.5) * 15;
      arr[i * 3 + 1] = (Math.random() - 0.5) * 15;
      arr[i * 3 + 2] = (Math.random() - 0.5) * 8;
    }
    return arr;
  }, []);

  useFrame((state) => {
    if (!lightRef.current) return;
    lightRef.current.intensity = 0.2 + Math.sin(state.clock.elapsedTime * 1.5) * 0.1;
  });

  return (
    <group>
      <ambientLight intensity={0.05} />
      <pointLight ref={lightRef} color="#F3F0E8" intensity={0.2} position={[0, 0, 3]} />
      <points>
        <bufferGeometry>
          <bufferAttribute
            attach="attributes-position"
            args={[positions, 3]}
          />
        </bufferGeometry>
        <pointsMaterial size={0.02} color="#F3F0E8" transparent opacity={0.15} depthWrite={false} />
      </points>
    </group>
  );
}
