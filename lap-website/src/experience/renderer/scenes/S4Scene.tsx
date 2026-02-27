'use client';
import { LivingSurface } from './LivingSurface';
import type { ChapterSceneProps } from '@/experience/state/types';

export function S4Scene(props: ChapterSceneProps) {
  return <LivingSurface {...props} color="#0C0D10" fogDensity={0.025} />;
}
