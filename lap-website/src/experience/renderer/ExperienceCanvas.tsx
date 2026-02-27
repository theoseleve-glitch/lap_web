'use client';

import { Suspense } from 'react';
import { Canvas } from '@react-three/fiber';
import { useKernelStore } from '@/experience/state/store';
import { SceneManager } from './SceneManager';
import { PostStack } from './PostStack';

export function ExperienceCanvas() {
  const webglAvailable = useKernelStore((s) => s.webglAvailable);
  const reducedMotion = useKernelStore((s) => s.reducedMotion);
  const qualityTier = useKernelStore((s) => s.qualityTier);

  if (!webglAvailable) return null;

  const dpr = qualityTier === 'high' ? [1, 2] : qualityTier === 'balanced' ? [0.75, 1.5] : [0.5, 1];

  return (
    <div
      className="fixed inset-0 z-0 pointer-events-none"
      aria-hidden="true"
    >
      <Canvas
        dpr={dpr as [number, number]}
        gl={{
          antialias: qualityTier === 'high',
          alpha: true,
          powerPreference: 'high-performance',
        }}
        camera={{ position: [0, 0, 5], fov: 50 }}
        style={{ background: 'transparent' }}
      >
        <Suspense fallback={null}>
          <SceneManager />
          {!reducedMotion && qualityTier !== 'low' && <PostStack />}
        </Suspense>
      </Canvas>
    </div>
  );
}
