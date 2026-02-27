'use client';

import { useMemo, useEffect } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import { useFBO } from '@react-three/drei';
import * as THREE from 'three';
import { useKernelStore } from '@/experience/state/store';
import { colors } from '@/lib/tokens';
import { truthTrackMapVertex, truthTrackMapFragment } from './shaders/truth-trackmap';

const edgeColor = new THREE.Color(colors.chalk);
const sectorColor = new THREE.Color(colors.racingPurple);

interface TruthLayerTrackMapProps {
  onTextureReady: (texture: THREE.Texture) => void;
}

export function TruthLayerTrackMap({ onTextureReady }: TruthLayerTrackMapProps) {
  const { gl } = useThree();
  const qualityTier = useKernelStore((s) => s.qualityTier);
  const resolution = qualityTier === 'high' ? 1024 : 512;

  const fbo = useFBO(resolution, resolution, {
    minFilter: THREE.LinearFilter,
    magFilter: THREE.LinearFilter,
    type: THREE.HalfFloatType,
  });

  const scene = useMemo(() => new THREE.Scene(), []);
  const camera = useMemo(() => new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1), []);

  const material = useMemo(() => new THREE.ShaderMaterial({
    vertexShader: truthTrackMapVertex,
    fragmentShader: truthTrackMapFragment,
    uniforms: {
      uTime: { value: 0 },
      uProgress: { value: 0 },
      uEdgeColor: { value: edgeColor },
      uSectorColor: { value: sectorColor },
      uSectorEnd: { value: 0 },
    },
    transparent: true,
  }), []);

  const mesh = useMemo(() => {
    const geo = new THREE.PlaneGeometry(2, 2);
    const m = new THREE.Mesh(geo, material);
    scene.add(m);
    return m;
  }, [material, scene]);

  useEffect(() => {
    onTextureReady(fbo.texture);
  }, [fbo.texture, onTextureReady]);

  useEffect(() => {
    return () => {
      material.dispose();
      mesh.geometry.dispose();
    };
  }, [material, mesh]);

  useFrame((_, delta) => {
    const { globalProgress, hudTower } = useKernelStore.getState();
    material.uniforms.uTime.value += delta;
    material.uniforms.uProgress.value = globalProgress;

    let sectorEnd = 0;
    for (let i = 0; i < hudTower.sectors.length; i++) {
      if (hudTower.sectors[i].status === 'completed') {
        sectorEnd = (i + 1) / hudTower.sectors.length;
      }
    }
    material.uniforms.uSectorEnd.value = sectorEnd;

    gl.setRenderTarget(fbo);
    gl.render(scene, camera);
    gl.setRenderTarget(null);
  });

  return null;
}
