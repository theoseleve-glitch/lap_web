'use client';

import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { useKernelStore } from '@/experience/state/store';
import { background as bgTokens } from '@/experience/motion/springs';
import { buildTrackCurve, sampleTrack, buildRibbonGeometry } from './trackGeometry';

const SEGMENTS_BY_TIER = { high: 300, balanced: 200, low: 100 } as const;

// Purple metallic color (#D946EF)
const PURPLE = new THREE.Color(0xD946EF);
const PURPLE_DIM = new THREE.Color(0x6B21A8);

export function TrackRibbon() {
  const ribbonRef = useRef<THREE.Mesh>(null);
  const edgeRef = useRef<THREE.Mesh>(null);
  const glowLightRef = useRef<THREE.PointLight>(null);
  const qualityTier = useKernelStore((s) => s.qualityTier);

  const segments = SEGMENTS_BY_TIER[qualityTier] ?? 200;

  const { curve, ribbonGeo, edgeGeo } = useMemo(() => {
    const c = buildTrackCurve();
    const s = sampleTrack(c, segments);

    // Main ribbon body — wide, dark
    const body = buildRibbonGeometry(s, bgTokens.ribbonWidth);

    // Edge glow — slightly wider, bright purple additive
    const edge = buildRibbonGeometry(s, bgTokens.ribbonWidth + 0.3);

    return { curve: c, ribbonGeo: body, edgeGeo: edge };
  }, [segments]);

  // Materials (created once)
  const ribbonMat = useMemo(() => new THREE.MeshBasicMaterial({
    color: new THREE.Color(0x0a0a0f),
    transparent: true,
    opacity: 0.85,
    depthWrite: false,
    side: THREE.DoubleSide,
  }), []);

  const edgeMat = useMemo(() => new THREE.MeshBasicMaterial({
    color: PURPLE_DIM,
    transparent: true,
    opacity: 0.4,
    depthWrite: false,
    side: THREE.DoubleSide,
    blending: THREE.AdditiveBlending,
  }), []);

  useFrame(({ clock }) => {
    const state = useKernelStore.getState();
    const bg = state.background;
    const t = clock.elapsedTime;

    // Pulse the edge glow with a slow breathe + scroll velocity boost
    const breathe = 0.3 + Math.sin(t * 0.8) * 0.1;
    const velocityBoost = Math.abs(state.scrollVelocity) * 0.3;
    edgeMat.opacity = Math.min(breathe + velocityBoost, 0.7);

    // Shift edge color between purple and brighter purple based on progress
    const intensity = 0.4 + Math.sin(t * 0.5) * 0.15;
    edgeMat.color.copy(PURPLE_DIM).lerp(PURPLE, intensity);

    // Move the glow light along the track
    if (glowLightRef.current) {
      const trackT = Math.max(0, Math.min(0.999, bg.ribbonProgress));
      const pos = curve.getPointAt(trackT);
      glowLightRef.current.position.set(pos.x, pos.y, pos.z + 2);

      // Glow brighter during fast scroll
      glowLightRef.current.intensity = 0.6 + Math.abs(state.scrollVelocity) * 1.5;
    }
  });

  return (
    <>
      {/* Dark ribbon body */}
      <mesh ref={ribbonRef} frustumCulled={false}>
        <primitive object={ribbonGeo} attach="geometry" />
        <primitive object={ribbonMat} attach="material" />
      </mesh>

      {/* Bright purple edges (additive glow) */}
      <mesh ref={edgeRef} frustumCulled={false}>
        <primitive object={edgeGeo} attach="geometry" />
        <primitive object={edgeMat} attach="material" />
      </mesh>

      {/* Point light that follows progress along the track */}
      <pointLight
        ref={glowLightRef}
        color="#D946EF"
        intensity={0.6}
        distance={6}
        decay={2}
      />

      {/* Ambient purple fill so the scene isn't pure black */}
      <ambientLight color="#1a0a2e" intensity={0.3} />
    </>
  );
}
