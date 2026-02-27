'use client';
import { LivingSurface } from './LivingSurface';
import type { ChapterSceneProps } from '@/experience/state/types';

export function PitStopScene(props: ChapterSceneProps) {
  return <LivingSurface {...props} color="#0B0C0F" fogDensity={0.02} />;
}
