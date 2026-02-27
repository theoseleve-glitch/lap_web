'use client';

import { useEffect, useMemo, useRef, useCallback } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { useKernelStore } from '@/experience/state/store';
import { computeMaskResolution } from './useRevealState';
import { revealBlendVertex, revealBlendFragment } from './shaders/reveal-blend';
import { TruthLayerTrackMap } from './TruthLayerTrackMap';
import { TruthLayerTelemetry } from './TruthLayerTelemetry';
import type { RevealMaskPipelineHandle } from './RevealMaskPipeline';

interface RevealBlendMeshProps {
  maskPipelineRef: React.RefObject<RevealMaskPipelineHandle | null>;
}

/**
 * RevealBlendMesh — full-screen quad that composites truth content using the
 * reveal mask. Renders at renderOrder 998.
 *
 * - Hero (chapters 0-2): Layer B = track map blueprint
 * - Sections (chapters 3-9): Layer B = telemetry data overlay
 * - Pit (chapter 8) + Podium (chapter 10): reveal disabled
 */
export function RevealBlendMesh({ maskPipelineRef }: RevealBlendMeshProps) {
  const active = useKernelStore((s) => s.reveal.active);
  const qualityTier = useKernelStore((s) => s.qualityTier);
  const resolution = computeMaskResolution(qualityTier);

  const trackMapTextureRef = useRef<THREE.Texture | null>(null);
  const telemetryTextureRef = useRef<THREE.Texture | null>(null);

  const onTrackMapReady = useCallback((tex: THREE.Texture) => {
    trackMapTextureRef.current = tex;
  }, []);

  const onTelemetryReady = useCallback((tex: THREE.Texture) => {
    telemetryTextureRef.current = tex;
  }, []);

  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: revealBlendVertex,
        fragmentShader: revealBlendFragment,
        uniforms: {
          tLayerA: { value: null },
          tLayerB: { value: null },
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
    if (!active || resolution === 0) return;

    const maskTexture = maskPipelineRef.current?.getMaskTexture() ?? null;
    if (!maskTexture) return;

    const { currentChapter } = useKernelStore.getState();

    // Select truth layer based on chapter
    let truthTexture: THREE.Texture | null = null;
    if (currentChapter <= 2) {
      truthTexture = trackMapTextureRef.current;
    } else if (currentChapter <= 9 && currentChapter !== 8) {
      truthTexture = telemetryTextureRef.current;
    }
    // Chapters 8 (pit) and 10 (podium): no reveal

    material.uniforms.tMask.value = maskTexture;
    material.uniforms.tLayerB.value = truthTexture;
  });

  if (!active || resolution === 0) return null;

  return (
    <>
      <TruthLayerTrackMap onTextureReady={onTrackMapReady} />
      <TruthLayerTelemetry onTextureReady={onTelemetryReady} />
      <mesh renderOrder={998}>
        <planeGeometry args={[2, 2]} />
        <primitive object={material} attach="material" />
      </mesh>
    </>
  );
}
