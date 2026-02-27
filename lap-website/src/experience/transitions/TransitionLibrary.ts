import type { TransitionType } from '@/experience/state/types';

export const transitionMap: Record<string, TransitionType> = {
  'start-grid→s1-pain': 'refraction',
  's1-pain→s1-deep': 'crossfade-blur',
  's1-deep→s2-pipeline': 'mask-wipe',
  's2-pipeline→s2-proof': 'crossfade-blur',
  's2-proof→s3-product': 'mask-wipe',
  's3-product→s4-workflows': 'crossfade-blur',
  's4-workflows→s5-personas': 'velocity-warp',
  's5-personas→pit-stop': 'mask-wipe',
  'pit-stop→garage': 'crossfade-blur',
  'garage→podium': 'refraction',
};

export function getTransitionType(fromId: string, toId: string): TransitionType {
  const key = `${fromId}→${toId}`;
  return transitionMap[key] ?? 'crossfade-blur';
}
