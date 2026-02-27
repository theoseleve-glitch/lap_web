'use client';

import { useEffect, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { useKernelStore } from '@/experience/state/store';
import { computeMaskResolution } from './useRevealState';
import { revealBlendVertex, revealBlendFragment } from './shaders/reveal-blend';

interface RevealBlendMeshProps {
  maskTexture: THREE.Texture | null;
}

/**
 * RevealBlendMesh — full-screen quad that composites Layer A and Layer B
 * using the reveal mask texture. Renders at renderOrder 998.
 *
 * For Prototype 1: Layer A = transparent (scene shows through),
 * Layer B = telemetry overlay texture (initially a simple tinted grid).
 *
 * DEFERRED: Not mounted in ExperienceCanvas. The mask pipeline writes to
 * internal FBOs and only feeds maskCoverage back to the store. To activate,
 * RevealMaskPipeline must expose its mask FBO texture (via ref or store),
 * and layer content textures (tLayerA / tLayerB) must be authored.
 * Tracked for a future phase when telemetry overlay content is ready.
 */
export function RevealBlendMesh({ maskTexture }: RevealBlendMeshProps) {
  const active = useKernelStore((s) => s.reveal.active);
  const qualityTier = useKernelStore((s) => s.qualityTier);
  const resolution = computeMaskResolution(qualityTier);

  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: revealBlendVertex,
        fragmentShader: revealBlendFragment,
        uniforms: {
          tLayerA: { value: null },  // placeholder: clean surface
          tLayerB: { value: null },  // placeholder: truth layer
          tMask: { value: null },
        },
        transparent: true,
        depthTest: false,
        depthWrite: false,
      }),
    [],
  );

  useEffect(() => {
    return () => { material.dispose(); };
  }, [material]);

  useFrame(() => {
    if (!active || resolution === 0 || !maskTexture) return;
    material.uniforms.tMask.value = maskTexture;
  });

  if (!active || resolution === 0) return null;

  return (
    <mesh renderOrder={998}>
      <planeGeometry args={[2, 2]} />
      <primitive object={material} attach="material" />
    </mesh>
  );
}
