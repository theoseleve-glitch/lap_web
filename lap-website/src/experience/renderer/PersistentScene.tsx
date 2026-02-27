'use client';

import { useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { useKernelStore } from '@/experience/state/store';
import { background } from '@/experience/motion/springs';
import { isCornerChapter, getChapterPath } from '@/experience/narrative/TrackPath';
import { Atmosphere } from './Atmosphere';
import { TrackRibbon } from './TrackRibbon';

function lerpAngle(current: number, target: number, factor: number): number {
  return current + (target - current) * factor;
}

/**
 * PersistentScene — single persistent R3F scene.
 *
 * Contains:
 * - Atmosphere (grain + particles + streaks + vignette)
 * - TrackRibbon (the track layout mesh)
 * - Camera corner-feel (yaw + bank on corner chapters)
 *
 * AssetManager and RevealBlendMesh will be added as children in Prototype 2.
 */
export function PersistentScene() {
  const groupRef = useRef<THREE.Group>(null);
  const yawRef = useRef(0);
  const bankRef = useRef(0);

  useFrame(() => {
    const state = useKernelStore.getState();
    const { currentChapter, reducedMotion } = state;

    if (!groupRef.current) return;

    if (reducedMotion) {
      yawRef.current = 0;
      bankRef.current = 0;
    } else {
      const path = getChapterPath(currentChapter);
      const isCorner = isCornerChapter(currentChapter);

      if (isCorner) {
        const direction = path.heading > 0 ? 1 : -1;
        const yawTarget = direction * background.cornerYawRange;
        const bankTarget = direction * background.cornerBankRange;
        yawRef.current = lerpAngle(yawRef.current, yawTarget, background.cornerLerp);
        bankRef.current = lerpAngle(bankRef.current, bankTarget, background.cornerLerp);
      } else {
        yawRef.current = lerpAngle(yawRef.current, 0, background.cornerLerp);
        bankRef.current = lerpAngle(bankRef.current, 0, background.cornerLerp);
      }
    }

    const DEG2RAD = Math.PI / 180;
    groupRef.current.rotation.y = yawRef.current * DEG2RAD;
    groupRef.current.rotation.z = bankRef.current * DEG2RAD;
  });

  return (
    <group ref={groupRef}>
      <ambientLight intensity={0.1} />
      <Atmosphere />
      <TrackRibbon />
    </group>
  );
}
