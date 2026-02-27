'use client';
import { AtmosphereBase } from './AtmosphereBase';
import type { ChapterSceneProps } from '@/experience/state/types';

export function StartGridScene(props: ChapterSceneProps) {
  return <AtmosphereBase {...props} color="#0B0C0F" fogDensity={0.05} particleCount={300} />;
}
