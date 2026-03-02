// src/experience/state/store.ts
import { create } from 'zustand';
import type { KernelStore } from './types';
import { colors } from '@/lib/tokens';

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
  mode: 'idle' as const,
  qualityTier: 'high' as const,
  qualityMode: 'auto' as const,
  reducedMotion: false,
  webglAvailable: true,
  loadProgress: 1,
  preloaderComplete: true,

  // ── Narrative state ─────────────────────
  hudTower: {
    sectors: [
      { id: 'S1', status: 'pending' as const, progress: 0, color: colors.chalk },
      { id: 'S2', status: 'pending' as const, progress: 0, color: colors.chalk },
      { id: 'S3', status: 'pending' as const, progress: 0, color: colors.chalk },
      { id: 'S4', status: 'pending' as const, progress: 0, color: colors.chalk },
      { id: 'S5', status: 'pending' as const, progress: 0, color: colors.chalk },
      { id: 'PIT', status: 'pending' as const, progress: 0, color: colors.chalk },
      { id: 'GAR', status: 'pending' as const, progress: 0, color: colors.chalk },
      { id: 'POD', status: 'pending' as const, progress: 0, color: colors.chalk },
    ],
    activeSectorIndex: 0,
  },
  hudDelta: { value: 0, jitter: 8, settled: false },
  reveal: {
    maskCoverage: 0,
    brushRadius: 80,
    turbulenceLevel: 0,
    smoothedPointer: { x: 0.5, y: 0.5 },
    layerSubject: 'telemetry-truth',
    active: true,
  },
  drs: { active: false, remaining: 0, multiplier: 1.0, trigger: '' },
  trackPath: { heading: 0, headingDelta: 0, isCorner: false, pitMode: false, velocityMultiplier: 1.0 },
  finish: { crossed: false, finalDelta: 0 },

  // ── Background state ──────────────────────
  background: {
    cornerYaw: 0,
    cornerBank: 0,
    streakIntensity: 0,
    ribbonProgress: 0,
  },

  // ── Asset state ────────────────────────────
  assets: {
    loaded: {} as Record<string, boolean>,
    visible: {} as Record<string, boolean>,
  },

  // ── Safety Car state ───────────────────────
  safetyCar: {
    active: false,
    reason: '',
    enteredAt: 0,
  },
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

  // ── Narrative actions ───────────────────
  completeSector: (index) =>
    set((state) => {
      if (index < 0 || index >= state.hudTower.sectors.length) return {};
      const sectors = [...state.hudTower.sectors];
      sectors[index] = { ...sectors[index], status: 'completed', color: colors.racingPurple, progress: 1 };
      const nextActive = Math.min(index + 1, sectors.length - 1);
      if (sectors[nextActive].status === 'pending') {
        sectors[nextActive] = { ...sectors[nextActive], status: 'active' };
      }
      return { hudTower: { sectors, activeSectorIndex: nextActive } };
    }),

  setSectorProgress: (index, progress) =>
    set((state) => {
      const sectors = [...state.hudTower.sectors];
      if (index >= 0 && index < sectors.length) {
        sectors[index] = { ...sectors[index], progress: Math.max(0, Math.min(1, progress)) };
      }
      return { hudTower: { ...state.hudTower, sectors } };
    }),

  setDeltaValue: (value) =>
    set((state) => ({ hudDelta: { ...state.hudDelta, value } })),

  setDeltaJitter: (jitter) =>
    set((state) => ({
      hudDelta: { ...state.hudDelta, jitter: Math.max(0, Math.min(8, jitter)) },
    })),

  settleDelta: () =>
    set((state) => ({ hudDelta: { ...state.hudDelta, settled: true, jitter: 0 } })),

  setMaskCoverage: (coverage) =>
    set((state) => ({
      reveal: { ...state.reveal, maskCoverage: Math.max(0, Math.min(1, coverage)) },
    })),

  setRevealActive: (active) =>
    set((state) => ({ reveal: { ...state.reveal, active } })),

  activateDrs: (trigger) =>
    set({ drs: { active: true, remaining: 2000, multiplier: 1.4, trigger } }),

  deactivateDrs: () =>
    set({ drs: { active: false, remaining: 0, multiplier: 1.0, trigger: '' } }),

  setTrackPath: (path) =>
    set((state) => ({ trackPath: { ...state.trackPath, ...path } })),

  setPitMode: (active) =>
    set((state) => ({
      trackPath: { ...state.trackPath, pitMode: active, velocityMultiplier: active ? 0.3 : 1.0 },
    })),

  crossFinishLine: () =>
    set((state) => ({
      finish: { crossed: true, finalDelta: state.hudDelta.value },
      hudDelta: { ...state.hudDelta, settled: true, jitter: 0 },
    })),

  // ── Background actions ────────────────────
  setCornerYaw: (yaw) =>
    set((state) => ({ background: { ...state.background, cornerYaw: yaw } })),
  setCornerBank: (bank) =>
    set((state) => ({ background: { ...state.background, cornerBank: bank } })),
  setStreakIntensity: (intensity) =>
    set((state) => ({ background: { ...state.background, streakIntensity: Math.max(0, Math.min(1, intensity)) } })),
  setRibbonProgress: (progress) =>
    set((state) => ({ background: { ...state.background, ribbonProgress: Math.max(0, Math.min(1, progress)) } })),

  // ── Asset actions ─────────────────────────
  setAssetLoaded: (id, loaded) =>
    set((state) => ({ assets: { ...state.assets, loaded: { ...state.assets.loaded, [id]: loaded } } })),
  setAssetVisible: (id, visible) =>
    set((state) => ({ assets: { ...state.assets, visible: { ...state.assets.visible, [id]: visible } } })),

  // ── Safety Car actions ────────────────────
  enterSafetyCar: (reason) =>
    set({ safetyCar: { active: true, reason, enteredAt: Date.now() } }),
  exitSafetyCar: () =>
    set({ safetyCar: { active: false, reason: '', enteredAt: 0 } }),
}));
