// src/experience/state/types.ts

import type { ComponentType } from 'react';

export type InteractionMode =
  | 'preloading'
  | 'idle'
  | 'scrolling'
  | 'dragging'
  | 'transitioning'
  | 'pit';

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
  accentColor: 'none' | 'green' | 'red' | 'yellow' | 'orange' | 'purple';
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

// ── Narrative state extensions ────────────────

export interface TowerSector {
  id: string;
  status: 'pending' | 'active' | 'completed';
  progress: number;
  color: string;
}

export interface HudTowerState {
  sectors: TowerSector[];
  activeSectorIndex: number;
}

export interface HudDeltaState {
  value: number;
  jitter: number;
  settled: boolean;
}

export interface RevealState {
  maskCoverage: number;
  brushRadius: number;
  turbulenceLevel: number;
  smoothedPointer: { x: number; y: number };
  layerSubject: string;
  active: boolean;
}

export interface DrsState {
  active: boolean;
  remaining: number;
  multiplier: number;
  trigger: string;
}

export interface TrackPathState {
  heading: number;
  headingDelta: number;
  isCorner: boolean;
  pitMode: boolean;
  velocityMultiplier: number;
}

export interface FinishState {
  crossed: boolean;
  finalDelta: number;
}

export interface ExtendedKernelState {
  hudTower: HudTowerState;
  hudDelta: HudDeltaState;
  reveal: RevealState;
  drs: DrsState;
  trackPath: TrackPathState;
  finish: FinishState;
}

export interface ExtendedKernelActions {
  completeSector: (index: number) => void;
  setSectorProgress: (index: number, progress: number) => void;
  setDeltaValue: (value: number) => void;
  setDeltaJitter: (jitter: number) => void;
  settleDelta: () => void;
  setMaskCoverage: (coverage: number) => void;
  setRevealActive: (active: boolean) => void;
  activateDrs: (trigger: string) => void;
  deactivateDrs: () => void;
  setTrackPath: (path: Partial<Pick<TrackPathState, 'heading' | 'headingDelta' | 'isCorner'>>) => void;
  setPitMode: (active: boolean) => void;
  crossFinishLine: () => void;
}

export type KernelStore = KernelState & KernelActions & ExtendedKernelState & ExtendedKernelActions;
