'use client';

import { useRef, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import { Effect, EffectAttribute } from 'postprocessing';
import { EffectComposer } from '@react-three/postprocessing';
import * as THREE from 'three';
import { useKernelStore } from '@/experience/state/store';
import { background as bgTokens } from '@/experience/motion/springs';
import { pointerLensFragment } from './shaders/pointer-lens';

// ── Custom postprocessing Effect ───────────────

const TIER_VALUE = { high: 2, balanced: 1, low: 0 } as const;

class PointerLensEffect extends Effect {
  constructor() {
    super('PointerLensEffect', pointerLensFragment, {
      attributes: EffectAttribute.CONVOLUTION,
      uniforms: new Map<string, THREE.Uniform>([
        ['uPointerPos', new THREE.Uniform(new THREE.Vector2(0.5, 0.5))],
        ['uDistortionStrength', new THREE.Uniform(bgTokens.pointerDistortionStrength)],
        ['uRadius', new THREE.Uniform(bgTokens.pointerDistortionRadius)],
        ['uQualityTier', new THREE.Uniform(1)],
      ]),
    });
  }
}

// ── R3F wrapper ────────────────────────────────

function PointerLensPass() {
  const effectRef = useRef<PointerLensEffect>(null);

  const effect = useMemo(() => new PointerLensEffect(), []);

  useFrame(() => {
    if (!effect) return;
    const state = useKernelStore.getState();
    const tier = TIER_VALUE[state.qualityTier] ?? 1;

    const pointerUniform = effect.uniforms.get('uPointerPos');
    if (pointerUniform) {
      (pointerUniform.value as THREE.Vector2).set(state.pointerX, 1 - state.pointerY);
    }

    const tierUniform = effect.uniforms.get('uQualityTier');
    if (tierUniform) {
      tierUniform.value = state.reducedMotion ? 0 : tier;
    }
  });

  return <primitive ref={effectRef} object={effect} />;
}

export function PointerLens() {
  const qualityTier = useKernelStore((s) => s.qualityTier);
  const reducedMotion = useKernelStore((s) => s.reducedMotion);

  // Only active on high + balanced tiers, not on low or reducedMotion
  if (qualityTier === 'low' || reducedMotion) return null;

  return (
    <EffectComposer multisampling={0}>
      <PointerLensPass />
    </EffectComposer>
  );
}
