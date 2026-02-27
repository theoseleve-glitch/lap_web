'use client';
import { AtmosphereBase } from './AtmosphereBase';
import type { ChapterSceneProps } from '@/experience/state/types';

export function S4Scene(props: ChapterSceneProps) {
  return <AtmosphereBase {...props} color="#0C0D10" fogDensity={0.025} particleCount={180} />;
}
