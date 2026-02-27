'use client';

import { useMemo, useEffect } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { useKernelStore } from '@/experience/state/store';
import { TRACK_PATH } from '@/experience/narrative/TrackPath';
import { background } from '@/experience/motion/springs';
import { colors } from '@/lib/tokens';
import { buildRibbonCurve, extrudeRibbonGeometry } from './TrackRibbonGeometry';
import { trackRibbonVertex, trackRibbonFragment } from './shaders/track-ribbon';

const edgeColor = new THREE.Color(colors.chalk);
const sectorColor = new THREE.Color(colors.racingPurple);

export function TrackRibbon() {
  const qualityTier = useKernelStore((s) => s.qualityTier);

  const segments = qualityTier === 'high' ? 300 : qualityTier === 'balanced' ? 150 : 80;

  const curve = useMemo(() => buildRibbonCurve(TRACK_PATH), []);

  const geometry = useMemo(
    () => extrudeRibbonGeometry(curve, background.ribbonWidth, segments),
    [curve, segments],
  );

  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: trackRibbonVertex,
        fragmentShader: trackRibbonFragment,
        uniforms: {
          uCameraProgress: { value: 0 },
          uEdgeEmissive: { value: background.ribbonEdgeEmissive },
          uForwardGlow: { value: background.ribbonForwardGlow },
          uEdgeColor: { value: edgeColor },
          uSectorColor: { value: sectorColor },
          uSectorGlow: { value: background.ribbonSegmentGlow },
          uSectorStart: { value: 0 },
          uSectorEnd: { value: 0 },
        },
        transparent: true,
        depthWrite: false,
        depthTest: false,
        side: THREE.DoubleSide,
      }),
    [],
  );

  useEffect(() => {
    return () => {
      geometry.dispose();
      material.dispose();
    };
  }, [geometry, material]);

  useFrame(() => {
    const { globalProgress, hudTower } = useKernelStore.getState();
    material.uniforms.uCameraProgress.value = globalProgress;

    // Find the furthest completed sector for highlight
    let sectorEnd = 0;
    for (let i = 0; i < hudTower.sectors.length; i++) {
      if (hudTower.sectors[i].status === 'completed') {
        sectorEnd = (i + 1) / hudTower.sectors.length;
      }
    }
    material.uniforms.uSectorEnd.value = sectorEnd;
  });

  return (
    <mesh geometry={geometry} material={material} renderOrder={-98} />
  );
}
