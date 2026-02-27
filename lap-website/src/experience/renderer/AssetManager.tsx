'use client';

import { Suspense, useMemo, useRef, useEffect } from 'react';
import { useFrame } from '@react-three/fiber';
import { useGLTF } from '@react-three/drei';
import * as THREE from 'three';
import { useKernelStore } from '@/experience/state/store';
import { ASSET_MANIFEST, type AssetEntry } from './assetManifest';

function AssetInstance({ entry }: { entry: AssetEntry }) {
  const { scene } = useGLTF(entry.path);
  const groupRef = useRef<THREE.Group>(null);
  const reducedMotion = useKernelStore((s) => s.reducedMotion);

  // Clone scene for independent transforms + dark emissive override
  const clonedScene = useMemo(() => {
    const clone = scene.clone();
    clone.traverse((child) => {
      if (child instanceof THREE.Mesh && child.material) {
        const mat = (child.material as THREE.MeshStandardMaterial).clone();
        mat.emissive = new THREE.Color(0x111118);
        mat.emissiveIntensity = 0.3;
        mat.metalness = 0.8;
        mat.roughness = 0.3;
        mat.transparent = true;
        mat.opacity = 0.7;
        child.material = mat;
      }
    });
    return clone;
  }, [scene]);

  // Mark loaded in store
  useEffect(() => {
    useKernelStore.getState().setAssetLoaded(entry.id, true);
    return () => {
      useKernelStore.getState().setAssetLoaded(entry.id, false);
    };
  }, [entry.id]);

  // Gentle animation
  useFrame((_, delta) => {
    if (!groupRef.current || reducedMotion) return;

    // Tire gets scroll-driven rotation
    if (entry.id === 'tire') {
      const { scrollVelocity, trackPath } = useKernelStore.getState();
      const rotSpeed = scrollVelocity * trackPath.velocityMultiplier * 3.0;
      groupRef.current.rotation.x += rotSpeed * delta;
    } else {
      // Other assets: subtle Y-axis rotation + gentle float
      groupRef.current.rotation.y += delta * 0.1;
      groupRef.current.position.y = entry.position[1] + Math.sin(Date.now() * 0.001) * 0.05;
    }
  });

  return (
    <group
      ref={groupRef}
      position={entry.position}
      rotation={entry.rotation}
      scale={entry.scale}
    >
      <primitive object={clonedScene} />
    </group>
  );
}

export function AssetManager() {
  const currentChapter = useKernelStore((s) => s.currentChapter);
  const qualityTier = useKernelStore((s) => s.qualityTier);

  // Don't load 3D assets on low quality tier
  if (qualityTier === 'low') return null;

  // Preload assets within 2 chapters
  const nearbyAssets = useMemo(
    () =>
      ASSET_MANIFEST.filter(
        (a) =>
          currentChapter >= a.chapterRange[0] - 2 &&
          currentChapter <= a.chapterRange[1] + 2,
      ),
    [currentChapter],
  );

  for (const asset of nearbyAssets) {
    useGLTF.preload(asset.path);
  }

  const visibleAssets = useMemo(
    () =>
      ASSET_MANIFEST.filter(
        (a) =>
          currentChapter >= a.chapterRange[0] &&
          currentChapter <= a.chapterRange[1],
      ),
    [currentChapter],
  );

  return (
    <group>
      {visibleAssets.map((entry) => (
        <Suspense key={entry.id} fallback={null}>
          <AssetInstance entry={entry} />
        </Suspense>
      ))}
    </group>
  );
}
