// src/experience/state/types.ts

import type { ComponentType } from 'react';

export type InteractionMode =
  | 'preloading'
  | 'idle'
  | 'scrolling'
  | 'dragging'
  | 'transitioning';

export type ScrollDirection = 'up' | 'down' | 'idle';

export type QualityTier = 'high' | 'balanced' | 'low';
export type QualityMode = 'auto' | 'manual';

export type TransitionType =
  | 'crossfade-blur'
  | 'mask-wipe'
  | 'velocity-warp'
  | 'refraction'
  | 'preloader-unlock'
  | 'none';

export interface ChapterConfig {
  id: string;
  index: number;
  scene: ComponentType<ChapterSceneProps> | null;
  transition: {
    enter: TransitionType;
    exit: TransitionType;
  };
  snapWeight: number;
  accentColor: 'none' | 'green' | 'red' | 'yellow' | 'orange';
}

export interface ChapterSceneProps {
  progress: number;
  scrollVelocity: number;
  pointerX: number;
  pointerY: number;
  qualityTier: QualityTier;
  active: boolean;
}

export interface KernelState {
  currentChapter: number;
  chapterProgress: number;
  globalProgress: number;
  scrollY: number;
  scrollVelocity: number;
  scrollDirection: ScrollDirection;
  pointerX: number;
  pointerY: number;
  pointerMagnetism: { x: number; y: number };
  mode: InteractionMode;
  qualityTier: QualityTier;
  qualityMode: QualityMode;
  reducedMotion: boolean;
  webglAvailable: boolean;
  loadProgress: number;
  preloaderComplete: boolean;
}

export interface KernelActions {
  setCurrentChapter: (index: number) => void;
  setChapterProgress: (progress: number) => void;
  setGlobalProgress: (progress: number) => void;
  setScrollY: (y: number) => void;
  setScrollVelocity: (v: number) => void;
  setScrollDirection: (dir: ScrollDirection) => void;
  setPointer: (x: number, y: number) => void;
  setPointerMagnetism: (mx: number, my: number) => void;
  setMode: (mode: InteractionMode) => void;
  setQualityTier: (tier: QualityTier) => void;
  setQualityMode: (mode: QualityMode) => void;
  setReducedMotion: (value: boolean) => void;
  setWebglAvailable: (value: boolean) => void;
  setLoadProgress: (progress: number) => void;
  completePreloader: () => void;
}

export type KernelStore = KernelState & KernelActions;
