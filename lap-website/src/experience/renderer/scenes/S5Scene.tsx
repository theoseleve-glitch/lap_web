'use client';
import { AtmosphereBase } from './AtmosphereBase';
import type { ChapterSceneProps } from '@/experience/state/types';

export function S5Scene(props: ChapterSceneProps) {
  return <AtmosphereBase {...props} color="#0D0E12" fogDensity={0.03} particleCount={200} />;
}
