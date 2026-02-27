'use client';
import { LivingSurface } from './LivingSurface';
import type { ChapterSceneProps } from '@/experience/state/types';

export function S2Scene(props: ChapterSceneProps) {
  return <LivingSurface {...props} color="#0D0E12" fogDensity={0.03} />;
}
