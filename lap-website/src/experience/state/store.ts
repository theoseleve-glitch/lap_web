// src/experience/state/store.ts
import { create } from 'zustand';
import type { KernelStore } from './types';

const CHAPTER_COUNT = 11;

const initialState = {
  currentChapter: 0,
  chapterProgress: 0,
  globalProgress: 0,
  scrollY: 0,
  scrollVelocity: 0,
  scrollDirection: 'idle' as const,
  pointerX: 0.5,
  pointerY: 0.5,
  pointerMagnetism: { x: 0, y: 0 },
  mode: 'preloading' as const,
  qualityTier: 'high' as const,
  qualityMode: 'auto' as const,
  reducedMotion: false,
  webglAvailable: true,
  loadProgress: 0,
  preloaderComplete: false,
};

export const useKernelStore = create<KernelStore>()((set) => ({
  ...initialState,

  setCurrentChapter: (index) =>
    set({ currentChapter: Math.max(0, Math.min(CHAPTER_COUNT - 1, index)) }),
  setChapterProgress: (progress) =>
    set({ chapterProgress: Math.max(0, Math.min(1, progress)) }),
  setGlobalProgress: (progress) =>
    set({ globalProgress: Math.max(0, Math.min(1, progress)) }),

  setScrollY: (y) => set({ scrollY: y }),
  setScrollVelocity: (v) =>
    set({ scrollVelocity: Math.max(-1, Math.min(1, v)) }),
  setScrollDirection: (dir) => set({ scrollDirection: dir }),

  setPointer: (x, y) => set({ pointerX: x, pointerY: y }),
  setPointerMagnetism: (mx, my) =>
    set({ pointerMagnetism: { x: mx, y: my } }),

  setMode: (mode) => set({ mode }),

  setQualityTier: (tier) => set({ qualityTier: tier }),
  setQualityMode: (mode) => set({ qualityMode: mode }),
  setReducedMotion: (value) => set({ reducedMotion: value }),
  setWebglAvailable: (value) => set({ webglAvailable: value }),

  setLoadProgress: (progress) =>
    set({ loadProgress: Math.max(0, Math.min(1, progress)) }),
  completePreloader: () =>
    set({ preloaderComplete: true, loadProgress: 1, mode: 'idle' }),
}));
