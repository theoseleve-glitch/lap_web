'use client';

import { Canvas } from '@react-three/fiber';
import { useKernelStore } from '@/experience/state/store';
import { BackgroundScene } from './BackgroundScene';

export function BackgroundCanvas() {
  const qualityTier = useKernelStore((s) => s.qualityTier);
  const preloaderComplete = useKernelStore((s) => s.preloaderComplete);

  const dpr: [number, number] =
    qualityTier === 'high' ? [1, 2] :
    qualityTier === 'balanced' ? [1, 1.5] :
    [1, 1];

  if (!preloaderComplete) return null;

  return (
    <div
      className="fixed inset-0 z-0 pointer-events-none"
      aria-hidden="true"
    >
      <Canvas
        gl={{
          alpha: false,
          stencil: false,
          depth: true,
          antialias: qualityTier !== 'low',
          powerPreference: 'high-performance',
        }}
        dpr={dpr}
        orthographic
        camera={{
          near: -100,
          far: 100,
          position: [0, 0, 10],
        }}
        style={{ background: '#000000' }}
        onCreated={({ gl }) => {
          gl.setClearColor('#000000', 1);
        }}
      >
        <BackgroundScene />
      </Canvas>
    </div>
  );
}
