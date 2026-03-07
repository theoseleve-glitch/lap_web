'use client';

import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { useKernelStore } from '@/experience/state/store';
import { background as bgTokens } from '@/experience/motion/springs';
import { buildTrackCurve } from './trackGeometry';

interface Streak {
  alive: boolean;
  age: number;
  lifetime: number;
  position: THREE.Vector3;
  velocity: THREE.Vector3;
}

const MAX_STREAKS_BY_TIER = { high: 15, balanced: 8, low: 0 } as const;

export function SpeedStreaks() {
  const meshRef = useRef<THREE.InstancedMesh>(null);
  const streaksRef = useRef<Streak[]>([]);
  const qualityTier = useKernelStore((s) => s.qualityTier);
  const reducedMotion = useKernelStore((s) => s.reducedMotion);

  const maxStreaks = MAX_STREAKS_BY_TIER[qualityTier] ?? 0;

  const curve = useMemo(() => buildTrackCurve(), []);

  const streakGeo = useMemo(() => new THREE.PlaneGeometry(0.6, 0.04), []);

  const streakMat = useMemo(() => new THREE.MeshBasicMaterial({
    color: 0xD946EF,
    transparent: true,
    opacity: 0.5,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    side: THREE.DoubleSide,
  }), []);

  const tempMatrix = useMemo(() => new THREE.Matrix4(), []);
  const zeroMatrix = useMemo(() => new THREE.Matrix4().makeScale(0, 0, 0), []);
  const tempQuat = useMemo(() => new THREE.Quaternion(), []);
  const tempScale = useMemo(() => new THREE.Vector3(), []);

  useFrame((_, delta) => {
    const mesh = meshRef.current;
    if (!mesh || maxStreaks === 0 || reducedMotion) return;

    const state = useKernelStore.getState();
    const { background, scrollVelocity, drs } = state;
    const { streakIntensity, ribbonProgress, cornerYaw } = background;

    while (streaksRef.current.length < maxStreaks) {
      streaksRef.current.push({
        alive: false, age: 0, lifetime: 0,
        position: new THREE.Vector3(),
        velocity: new THREE.Vector3(),
      });
    }

    const streaks = streaksRef.current;
    const spawnThreshold = drs.active
      ? bgTokens.streakSpawnThreshold * (1 - bgTokens.streakDrsThresholdReduction)
      : bgTokens.streakSpawnThreshold;

    for (let i = 0; i < maxStreaks; i++) {
      const s = streaks[i]!;
      if (!s.alive) {
        mesh.setMatrixAt(i, zeroMatrix);
        continue;
      }

      s.age += delta * 1000;
      if (s.age >= s.lifetime) {
        s.alive = false;
        mesh.setMatrixAt(i, zeroMatrix);
        continue;
      }

      s.position.addScaledVector(s.velocity, delta);

      // Fade out over lifetime
      const life = 1 - s.age / s.lifetime;
      const speed = s.velocity.length();

      // Orient streak along its velocity direction
      const angle = Math.atan2(s.velocity.y, s.velocity.x);
      tempQuat.setFromAxisAngle(new THREE.Vector3(0, 0, 1), angle);
      tempScale.set(1 + speed * 2, life, 1);

      tempMatrix.compose(s.position, tempQuat, tempScale);
      mesh.setMatrixAt(i, tempMatrix);
    }

    // Spawn new streaks
    if (streakIntensity > spawnThreshold) {
      const spawnChance = (streakIntensity - spawnThreshold) * 2;
      if (Math.random() < spawnChance * delta * 60) {
        for (let i = 0; i < maxStreaks; i++) {
          const s = streaks[i]!;
          if (s.alive) continue;
          s.alive = true;
          s.age = 0;
          s.lifetime = bgTokens.streakLifetime + Math.random() * 400;

          const t = Math.max(0, Math.min(0.999, ribbonProgress + (Math.random() - 0.5) * 0.05));
          const trackPos = curve.getPointAt(t);
          const tangent = curve.getTangentAt(t).normalize();
          const lateral = new THREE.Vector3(-tangent.y, tangent.x, 0);

          s.position.copy(trackPos);
          s.position.addScaledVector(lateral, (Math.random() - 0.5) * 6);
          s.position.z = 0.5;

          const baseSpeed = 2 + Math.abs(scrollVelocity) * 4;
          s.velocity.copy(tangent).multiplyScalar(baseSpeed * Math.sign(scrollVelocity || 1));
          s.velocity.addScaledVector(lateral, cornerYaw * 0.3);
          break;
        }
      }
    }

    mesh.instanceMatrix.needsUpdate = true;
  });

  if (maxStreaks === 0 || reducedMotion) return null;

  return (
    <instancedMesh
      ref={meshRef}
      args={[streakGeo, streakMat, maxStreaks]}
      frustumCulled={false}
    />
  );
}
