'use client';
import { useKernelStore } from '@/experience/state/store';

export function useKernel() {
  return useKernelStore();
}

export function useKernelState() {
  return useKernelStore((s) => ({
    currentChapter: s.currentChapter,
    chapterProgress: s.chapterProgress,
    globalProgress: s.globalProgress,
    mode: s.mode,
    scrollVelocity: s.scrollVelocity,
    pointerX: s.pointerX,
    pointerY: s.pointerY,
    qualityTier: s.qualityTier,
    reducedMotion: s.reducedMotion,
    preloaderComplete: s.preloaderComplete,
  }));
}
