'use client';
import { LivingSurface } from './LivingSurface';
import type { ChapterSceneProps } from '@/experience/state/types';

export function GarageScene(props: ChapterSceneProps) {
  return <LivingSurface {...props} color="#0A0B0E" fogDensity={0.015} />;
}
