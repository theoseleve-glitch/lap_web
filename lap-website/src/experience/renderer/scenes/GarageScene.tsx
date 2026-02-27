'use client';
import { AtmosphereBase } from './AtmosphereBase';
import type { ChapterSceneProps } from '@/experience/state/types';

export function GarageScene(props: ChapterSceneProps) {
  return <AtmosphereBase {...props} color="#0A0B0E" fogDensity={0.015} particleCount={80} />;
}
