'use client';

import { useMemo } from 'react';
import { EffectComposer, Bloom, Noise, ChromaticAberration } from '@react-three/postprocessing';
import { BlendFunction } from 'postprocessing';
import { useKernelStore } from '@/experience/state/store';
import { Vector2 } from 'three';

export function PostStack() {
  const qualityTier = useKernelStore((s) => s.qualityTier);
  const scrollVelocity = useKernelStore((s) => s.scrollVelocity);
  const mode = useKernelStore((s) => s.mode);

  // Chromatic aberration only during transitions or fast scroll
  const chromaIntensity =
    mode === 'transitioning'
      ? 0.003
      : Math.abs(scrollVelocity) > 0.3
        ? Math.abs(scrollVelocity) * 0.002
        : 0;

  const chromaOffset = useMemo(
    () => new Vector2(chromaIntensity, chromaIntensity),
    [chromaIntensity],
  );

  return (
    <EffectComposer multisampling={qualityTier === 'high' ? 4 : 0}>
      <Bloom
        intensity={0.15}
        luminanceThreshold={0.8}
        luminanceSmoothing={0.9}
        mipmapBlur
      />
      <Noise
        premultiply
        blendFunction={BlendFunction.SOFT_LIGHT}
        opacity={0.15}
      />
      <ChromaticAberration
        offset={chromaOffset}
        radialModulation={false}
        modulationOffset={0}
      />
    </EffectComposer>
  );
}
