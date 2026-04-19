'use client';

import { useThree } from '@react-three/fiber';
import { useEffect } from 'react';
import type { OrthographicCamera } from 'three';
import { TrackRibbon } from './TrackRibbon';
import { StudioLight } from './StudioLight';
import { SpeedStreaks } from './SpeedStreaks';
import { MetallicEvents } from './MetallicEvents';

export function BackgroundScene() {
  const { camera, size } = useThree();

  useEffect(() => {
    const cam = camera as OrthographicCamera;
    const aspect = size.width / size.height;
    const halfH = 5.5;
    const halfW = halfH * aspect;

    cam.left   = -halfW + 0.8;
    cam.right  =  halfW + 0.8;
    cam.top    =  halfH;
    cam.bottom = -halfH;
    cam.updateProjectionMatrix();
  }, [camera, size]);

  return (
    <>
      <TrackRibbon />
      <SpeedStreaks />
    </>
  );
}
