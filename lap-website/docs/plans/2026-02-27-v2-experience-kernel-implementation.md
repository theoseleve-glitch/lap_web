# V2 Experience Kernel Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Evolve the marketing homepage into an immersive installation experience with a centralized Experience Kernel orchestrating WebGL atmosphere, virtual scroll, composited transitions, pointer magnetism, and quality management — while preserving all V1 content, copy, CTAs, and routes.

**Architecture:** Kernel-First Rewrite. A Zustand store is the single source of truth for scroll, pointer, chapter, quality, and interaction mode. R3F canvas (Layer 1) renders atmosphere behind DOM rooms (Layer 2). Lenis provides damped virtual scroll feeding GSAP ScrollTrigger. Four GLSL shader transitions composite between chapter scenes. All rooms refactored to export registration configs; the kernel orchestrates their enter/exit/scrub timelines.

**Tech Stack:** Next.js 14, React 18, Three.js + R3F (already installed), @react-three/postprocessing (new), Zustand (new), Lenis (new), GSAP + ScrollTrigger (existing), Tailwind (existing), Howler (existing).

**New dependencies:** `zustand`, `lenis`, `@react-three/postprocessing`

---

## Phase 1: Foundation — Store, Types, Hooks

### Task 1: Install Dependencies

**Files:**
- Modify: `package.json`

**Step 1: Install new packages**

Run:
```bash
npm install zustand lenis @react-three/postprocessing
```

Expected: 3 packages added to dependencies in package.json.

**Step 2: Verify build still works**

Run:
```bash
npm run build 2>&1 | tail -5
```

Expected: Build succeeds (exit 0).

**Step 3: Commit**

```bash
git add package.json package-lock.json
git commit -m "deps: add zustand, lenis, @react-three/postprocessing"
```

---

### Task 2: Kernel State Types

**Files:**
- Create: `src/experience/state/types.ts`

**Step 1: Create the types file**

```typescript
// src/experience/state/types.ts

import type { ComponentType } from 'react';

// ── Interaction Modes ────────────────────────
export type InteractionMode =
  | 'preloading'
  | 'idle'
  | 'scrolling'
  | 'dragging'
  | 'transitioning';

export type ScrollDirection = 'up' | 'down' | 'idle';

// ── Quality ──────────────────────────────────
export type QualityTier = 'high' | 'balanced' | 'low';
export type QualityMode = 'auto' | 'manual';

// ── Transition Types ─────────────────────────
export type TransitionType =
  | 'crossfade-blur'
  | 'mask-wipe'
  | 'velocity-warp'
  | 'refraction'
  | 'preloader-unlock'
  | 'none';

// ── Chapter Config ───────────────────────────
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
  progress: number;        // 0..1 within this chapter
  scrollVelocity: number;  // -1..1 normalized
  pointerX: number;        // 0..1
  pointerY: number;        // 0..1
  qualityTier: QualityTier;
  active: boolean;
}

// ── Kernel State ─────────────────────────────
export interface KernelState {
  // Chapter system
  currentChapter: number;
  chapterProgress: number;
  globalProgress: number;

  // Scroll
  scrollY: number;
  scrollVelocity: number;
  scrollDirection: ScrollDirection;

  // Pointer
  pointerX: number;
  pointerY: number;
  pointerMagnetism: { x: number; y: number };

  // Mode
  mode: InteractionMode;

  // Quality
  qualityTier: QualityTier;
  qualityMode: QualityMode;
  reducedMotion: boolean;
  webglAvailable: boolean;

  // Preloader
  loadProgress: number;
  preloaderComplete: boolean;
}

// ── Kernel Actions ───────────────────────────
export interface KernelActions {
  // Chapter
  setCurrentChapter: (index: number) => void;
  setChapterProgress: (progress: number) => void;
  setGlobalProgress: (progress: number) => void;

  // Scroll
  setScrollY: (y: number) => void;
  setScrollVelocity: (v: number) => void;
  setScrollDirection: (dir: ScrollDirection) => void;

  // Pointer
  setPointer: (x: number, y: number) => void;
  setPointerMagnetism: (mx: number, my: number) => void;

  // Mode
  setMode: (mode: InteractionMode) => void;

  // Quality
  setQualityTier: (tier: QualityTier) => void;
  setQualityMode: (mode: QualityMode) => void;
  setReducedMotion: (value: boolean) => void;
  setWebglAvailable: (value: boolean) => void;

  // Preloader
  setLoadProgress: (progress: number) => void;
  completePreloader: () => void;
}

export type KernelStore = KernelState & KernelActions;
```

**Step 2: Verify types compile**

Run:
```bash
npx tsc --noEmit src/experience/state/types.ts 2>&1 | head -5
```

Expected: No errors (may warn about isolated modules — that's OK).

**Step 3: Commit**

```bash
git add src/experience/state/types.ts
git commit -m "feat(kernel): add state types — KernelState, ChapterConfig, actions"
```

---

### Task 3: Zustand Store

**Files:**
- Create: `src/experience/state/store.ts`
- Test: `src/__tests__/kernel-store.test.ts`

**Step 1: Write the failing test**

```typescript
// src/__tests__/kernel-store.test.ts
import { describe, it, expect, beforeEach } from 'vitest';
import { useKernelStore } from '@/experience/state/store';

describe('KernelStore', () => {
  beforeEach(() => {
    // Reset store between tests
    useKernelStore.setState(useKernelStore.getInitialState());
  });

  it('initializes with default state', () => {
    const state = useKernelStore.getState();
    expect(state.currentChapter).toBe(0);
    expect(state.mode).toBe('preloading');
    expect(state.qualityTier).toBe('high');
    expect(state.preloaderComplete).toBe(false);
    expect(state.scrollVelocity).toBe(0);
    expect(state.pointerX).toBe(0.5);
    expect(state.pointerY).toBe(0.5);
  });

  it('setCurrentChapter clamps to valid range', () => {
    const { setCurrentChapter } = useKernelStore.getState();
    setCurrentChapter(5);
    expect(useKernelStore.getState().currentChapter).toBe(5);
    setCurrentChapter(-1);
    expect(useKernelStore.getState().currentChapter).toBe(0);
    setCurrentChapter(99);
    expect(useKernelStore.getState().currentChapter).toBe(10);
  });

  it('setMode transitions correctly', () => {
    const { setMode } = useKernelStore.getState();
    setMode('idle');
    expect(useKernelStore.getState().mode).toBe('idle');
    setMode('scrolling');
    expect(useKernelStore.getState().mode).toBe('scrolling');
  });

  it('completePreloader sets flag and mode', () => {
    const { completePreloader } = useKernelStore.getState();
    completePreloader();
    const state = useKernelStore.getState();
    expect(state.preloaderComplete).toBe(true);
    expect(state.loadProgress).toBe(1);
    expect(state.mode).toBe('idle');
  });

  it('setQualityTier updates tier', () => {
    const { setQualityTier } = useKernelStore.getState();
    setQualityTier('balanced');
    expect(useKernelStore.getState().qualityTier).toBe('balanced');
    setQualityTier('low');
    expect(useKernelStore.getState().qualityTier).toBe('low');
  });

  it('setPointer normalizes coordinates', () => {
    const { setPointer } = useKernelStore.getState();
    setPointer(0.3, 0.7);
    const state = useKernelStore.getState();
    expect(state.pointerX).toBe(0.3);
    expect(state.pointerY).toBe(0.7);
  });

  it('setScrollVelocity clamps to -1..1', () => {
    const { setScrollVelocity } = useKernelStore.getState();
    setScrollVelocity(0.5);
    expect(useKernelStore.getState().scrollVelocity).toBe(0.5);
    setScrollVelocity(3.0);
    expect(useKernelStore.getState().scrollVelocity).toBe(1.0);
    setScrollVelocity(-5.0);
    expect(useKernelStore.getState().scrollVelocity).toBe(-1.0);
  });
});
```

**Step 2: Run test — verify it fails**

Run: `npx vitest run src/__tests__/kernel-store.test.ts`
Expected: FAIL — module not found.

**Step 3: Create the store**

```typescript
// src/experience/state/store.ts
import { create } from 'zustand';
import type { KernelStore } from './types';

const CHAPTER_COUNT = 11; // 0..10

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
```

**Step 4: Run test — verify it passes**

Run: `npx vitest run src/__tests__/kernel-store.test.ts`
Expected: All 7 tests PASS.

**Step 5: Commit**

```bash
git add src/experience/state/store.ts src/__tests__/kernel-store.test.ts
git commit -m "feat(kernel): zustand store with clamped setters + tests"
```

---

### Task 4: Physics Constants & Extended Tokens

**Files:**
- Create: `src/experience/motion/springs.ts`
- Modify: `src/lib/tokens.ts` (add `anticipate` easing)
- Modify: `src/lib/easing.ts` (add `anticipate`)

**Step 1: Create springs.ts**

```typescript
// src/experience/motion/springs.ts
export const physics = {
  // Lenis scroll
  scrollLerp: 0.08,
  scrollDuration: 1.2,
  scrollSnapForce: 0.4,

  // Pointer magnetism
  magnetismRadius: 120,
  magnetismStrength: 0.15,
  magnetismDecay: 2.0,

  // Drag / instrument
  dragFriction: 0.92,
  dragOvershoot: 0.04,

  // Scroll velocity → shader uniforms
  velocitySmoothing: 0.12,
  velocityMax: 1.0,

  // Snap
  snapVelocityThreshold: 0.05,
} as const;
```

**Step 2: Add `anticipate` to tokens.ts**

In `src/lib/tokens.ts`, add to the `easing` object:
```typescript
anticipate: 'power2.inOut',
```

**Step 3: Add `anticipate` to easing.ts**

In `src/lib/easing.ts`, add to the `ease` object:
```typescript
anticipate: 'power2.inOut',
```

**Step 4: Add `anticipate` CSS easing to tokens.css**

In `src/styles/tokens.css`, add in the `/* ── Easing ── */` section:
```css
--ease-anticipate: cubic-bezier(0.45, 0, 0.55, 1);
```

**Step 5: Commit**

```bash
git add src/experience/motion/springs.ts src/lib/tokens.ts src/lib/easing.ts src/styles/tokens.css
git commit -m "feat(kernel): physics constants + anticipate easing token"
```

---

### Task 5: Kernel Hooks

**Files:**
- Create: `src/experience/hooks/useKernel.ts`
- Create: `src/experience/hooks/useChapter.ts`
- Create: `src/experience/hooks/useScrollVelocity.ts`
- Create: `src/experience/hooks/usePointerInfluence.ts`
- Create: `src/experience/hooks/useQuality.ts`

**Step 1: Create all hooks**

```typescript
// src/experience/hooks/useKernel.ts
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
```

```typescript
// src/experience/hooks/useChapter.ts
'use client';
import { useKernelStore } from '@/experience/state/store';
import { rooms } from '@/lib/tokens';

export function useChapter() {
  const currentChapter = useKernelStore((s) => s.currentChapter);
  const chapterProgress = useKernelStore((s) => s.chapterProgress);
  const room = rooms[currentChapter] ?? rooms[0];

  return {
    index: currentChapter,
    id: room.id,
    label: room.label,
    sector: room.sector,
    progress: chapterProgress,
  };
}
```

```typescript
// src/experience/hooks/useScrollVelocity.ts
'use client';
import { useKernelStore } from '@/experience/state/store';

export function useScrollVelocity() {
  const scrollVelocity = useKernelStore((s) => s.scrollVelocity);
  const scrollDirection = useKernelStore((s) => s.scrollDirection);
  return { scrollVelocity, scrollDirection };
}
```

```typescript
// src/experience/hooks/usePointerInfluence.ts
'use client';
import { useKernelStore } from '@/experience/state/store';

export function usePointerInfluence() {
  const pointerX = useKernelStore((s) => s.pointerX);
  const pointerY = useKernelStore((s) => s.pointerY);
  const magnetism = useKernelStore((s) => s.pointerMagnetism);
  return { pointerX, pointerY, magnetism };
}
```

```typescript
// src/experience/hooks/useQuality.ts
'use client';
import { useKernelStore } from '@/experience/state/store';

export function useQuality() {
  const qualityTier = useKernelStore((s) => s.qualityTier);
  const qualityMode = useKernelStore((s) => s.qualityMode);
  const reducedMotion = useKernelStore((s) => s.reducedMotion);
  const webglAvailable = useKernelStore((s) => s.webglAvailable);

  return {
    qualityTier,
    qualityMode,
    reducedMotion,
    webglAvailable,
    isHigh: qualityTier === 'high',
    isLow: qualityTier === 'low',
    canUseWebgl: webglAvailable && !reducedMotion,
    canUsePost: qualityTier !== 'low' && !reducedMotion,
  };
}
```

**Step 2: Verify types compile**

Run: `npx tsc --noEmit`
Expected: No new errors.

**Step 3: Commit**

```bash
git add src/experience/hooks/
git commit -m "feat(kernel): kernel hooks — useKernel, useChapter, useScrollVelocity, usePointerInfluence, useQuality"
```

---

## Phase 2: Input Layer

### Task 6: Scroll Controller (Lenis + ScrollTrigger)

**Files:**
- Create: `src/experience/input/ScrollController.tsx`

**Step 1: Create the component**

```typescript
// src/experience/input/ScrollController.tsx
'use client';

import { useEffect, useRef } from 'react';
import Lenis from 'lenis';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { useKernelStore } from '@/experience/state/store';
import { rooms } from '@/lib/tokens';
import { physics } from '@/experience/motion/springs';

gsap.registerPlugin(ScrollTrigger);

export function ScrollController() {
  const lenisRef = useRef<Lenis | null>(null);
  const velocityRef = useRef(0);
  const setScrollY = useKernelStore((s) => s.setScrollY);
  const setScrollVelocity = useKernelStore((s) => s.setScrollVelocity);
  const setScrollDirection = useKernelStore((s) => s.setScrollDirection);
  const setGlobalProgress = useKernelStore((s) => s.setGlobalProgress);
  const setCurrentChapter = useKernelStore((s) => s.setCurrentChapter);
  const setChapterProgress = useKernelStore((s) => s.setChapterProgress);
  const setMode = useKernelStore((s) => s.setMode);
  const reducedMotion = useKernelStore((s) => s.reducedMotion);

  useEffect(() => {
    const lenis = new Lenis({
      lerp: reducedMotion ? 0.9 : physics.scrollLerp,
      duration: physics.scrollDuration,
      smoothWheel: true,
      touchMultiplier: 1.5,
    });

    lenisRef.current = lenis;

    // Bridge Lenis → ScrollTrigger
    lenis.on('scroll', ScrollTrigger.update);
    gsap.ticker.add((time) => lenis.raf(time * 1000));
    gsap.ticker.lagSmoothing(0);

    // Feed scroll data into kernel store
    lenis.on('scroll', ({ scroll, velocity, direction }: {
      scroll: number;
      velocity: number;
      direction: number;
    }) => {
      setScrollY(scroll);

      // Damp velocity for shader use
      const normalized = Math.max(-1, Math.min(1, velocity / 1000));
      velocityRef.current += (normalized - velocityRef.current) * physics.velocitySmoothing;
      setScrollVelocity(velocityRef.current);

      setScrollDirection(direction > 0 ? 'down' : direction < 0 ? 'up' : 'idle');

      // Global progress
      const docHeight = document.documentElement.scrollHeight - window.innerHeight;
      if (docHeight > 0) {
        setGlobalProgress(scroll / docHeight);
      }
    });

    // Set up per-chapter ScrollTriggers
    rooms.forEach((room, index) => {
      ScrollTrigger.create({
        trigger: `#${room.id}`,
        start: 'top center',
        end: 'bottom center',
        onEnter: () => setCurrentChapter(index),
        onEnterBack: () => setCurrentChapter(index),
        onUpdate: (self) => setChapterProgress(self.progress),
      });
    });

    // Mode detection: scrolling vs idle
    let idleTimer: ReturnType<typeof setTimeout>;
    lenis.on('scroll', () => {
      const currentMode = useKernelStore.getState().mode;
      if (currentMode === 'preloading' || currentMode === 'transitioning') return;

      setMode('scrolling');
      clearTimeout(idleTimer);
      idleTimer = setTimeout(() => {
        if (useKernelStore.getState().mode === 'scrolling') {
          setMode('idle');
        }
      }, 150);
    });

    return () => {
      lenis.destroy();
      ScrollTrigger.getAll().forEach((st) => st.kill());
      clearTimeout(idleTimer);
    };
  }, [
    reducedMotion, setScrollY, setScrollVelocity, setScrollDirection,
    setGlobalProgress, setCurrentChapter, setChapterProgress, setMode,
  ]);

  return null; // Headless component
}
```

**Step 2: Verify types compile**

Run: `npx tsc --noEmit`
Expected: No errors from this file.

**Step 3: Commit**

```bash
git add src/experience/input/ScrollController.tsx
git commit -m "feat(kernel): scroll controller — Lenis + ScrollTrigger bridge feeding Zustand store"
```

---

### Task 7: Pointer Field

**Files:**
- Create: `src/experience/input/PointerField.tsx`

**Step 1: Create the component**

```typescript
// src/experience/input/PointerField.tsx
'use client';

import { useEffect, useRef } from 'react';
import { useKernelStore } from '@/experience/state/store';
import { physics } from '@/experience/motion/springs';

export function PointerField() {
  const setPointer = useKernelStore((s) => s.setPointer);
  const setPointerMagnetism = useKernelStore((s) => s.setPointerMagnetism);
  const reducedMotion = useKernelStore((s) => s.reducedMotion);
  const rafRef = useRef(0);

  useEffect(() => {
    if (reducedMotion) return;

    let rawX = 0.5;
    let rawY = 0.5;

    const handleMove = (e: PointerEvent) => {
      rawX = e.clientX / window.innerWidth;
      rawY = e.clientY / window.innerHeight;
      setPointer(rawX, rawY);
    };

    const computeMagnetism = () => {
      // Find nearest interactive element
      const interactives = document.querySelectorAll(
        'a, button, [role="button"], input, [data-magnetic]'
      );

      let nearestDist = Infinity;
      let pullX = 0;
      let pullY = 0;

      const px = rawX * window.innerWidth;
      const py = rawY * window.innerHeight;

      interactives.forEach((el) => {
        const rect = el.getBoundingClientRect();
        const cx = rect.left + rect.width / 2;
        const cy = rect.top + rect.height / 2;
        const dx = cx - px;
        const dy = cy - py;
        const dist = Math.sqrt(dx * dx + dy * dy);

        if (dist < physics.magnetismRadius && dist < nearestDist) {
          nearestDist = dist;
          const falloff = Math.pow(
            1 - dist / physics.magnetismRadius,
            physics.magnetismDecay
          );
          pullX = (dx / dist) * falloff * physics.magnetismStrength;
          pullY = (dy / dist) * falloff * physics.magnetismStrength;
        }
      });

      setPointerMagnetism(pullX, pullY);
      rafRef.current = requestAnimationFrame(computeMagnetism);
    };

    window.addEventListener('pointermove', handleMove, { passive: true });
    rafRef.current = requestAnimationFrame(computeMagnetism);

    return () => {
      window.removeEventListener('pointermove', handleMove);
      cancelAnimationFrame(rafRef.current);
    };
  }, [reducedMotion, setPointer, setPointerMagnetism]);

  return null;
}
```

**Step 2: Commit**

```bash
git add src/experience/input/PointerField.tsx
git commit -m "feat(kernel): pointer field — position tracking + proximity magnetism"
```

---

### Task 8: Input Manager

**Files:**
- Create: `src/experience/input/InputManager.tsx`

**Step 1: Create the unified component**

```typescript
// src/experience/input/InputManager.tsx
'use client';

import { ScrollController } from './ScrollController';
import { PointerField } from './PointerField';

export function InputManager() {
  return (
    <>
      <ScrollController />
      <PointerField />
    </>
  );
}
```

**Step 2: Commit**

```bash
git add src/experience/input/InputManager.tsx
git commit -m "feat(kernel): input manager — unified scroll + pointer"
```

---

## Phase 3: Quality System

### Task 9: Quality Manager

**Files:**
- Create: `src/experience/quality/QualityManager.tsx`

**Step 1: Create the component**

```typescript
// src/experience/quality/QualityManager.tsx
'use client';

import { useEffect, useRef } from 'react';
import { useKernelStore } from '@/experience/state/store';
import type { QualityTier } from '@/experience/state/types';

const TIER_ORDER: QualityTier[] = ['high', 'balanced', 'low'];

export function QualityManager() {
  const setQualityTier = useKernelStore((s) => s.setQualityTier);
  const setReducedMotion = useKernelStore((s) => s.setReducedMotion);
  const setWebglAvailable = useKernelStore((s) => s.setWebglAvailable);
  const qualityMode = useKernelStore((s) => s.qualityMode);
  const framesRef = useRef<number[]>([]);
  const initialTierRef = useRef<QualityTier>('high');
  const currentTierRef = useRef<QualityTier>('high');
  const lowStartRef = useRef(0);
  const highStartRef = useRef(0);

  // Detect WebGL + reduced motion on mount
  useEffect(() => {
    // WebGL detection
    try {
      const canvas = document.createElement('canvas');
      const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
      setWebglAvailable(!!gl);
    } catch {
      setWebglAvailable(false);
    }

    // Reduced motion
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    setReducedMotion(mq.matches);
    const handler = (e: MediaQueryListEvent) => setReducedMotion(e.matches);
    mq.addEventListener('change', handler);

    // Initial tier: mobile → balanced
    if (window.matchMedia('(max-width: 767px)').matches) {
      initialTierRef.current = 'balanced';
      currentTierRef.current = 'balanced';
      setQualityTier('balanced');
    }

    return () => mq.removeEventListener('change', handler);
  }, [setReducedMotion, setWebglAvailable, setQualityTier]);

  // FPS monitoring + auto-degrade
  useEffect(() => {
    if (qualityMode !== 'auto') return;

    let rafId: number;
    let lastTime = performance.now();

    function tick() {
      const now = performance.now();
      const dt = now - lastTime;
      lastTime = now;

      if (dt > 0) {
        framesRef.current.push(1000 / dt);
        if (framesRef.current.length > 120) framesRef.current.shift();
      }

      if (framesRef.current.length >= 30) {
        const avg =
          framesRef.current.reduce((a, b) => a + b, 0) /
          framesRef.current.length;

        const tierIdx = TIER_ORDER.indexOf(currentTierRef.current);

        // Drop to Low immediately if very bad
        if (avg < 30 && now - lowStartRef.current > 1000) {
          if (currentTierRef.current !== 'low') {
            currentTierRef.current = 'low';
            setQualityTier('low');
          }
          lowStartRef.current = now;
          highStartRef.current = 0;
        }
        // Drop one tier if under 45fps for 2s
        else if (avg < 45) {
          if (lowStartRef.current === 0) lowStartRef.current = now;
          if (now - lowStartRef.current > 2000 && tierIdx < 2) {
            currentTierRef.current = TIER_ORDER[tierIdx + 1];
            setQualityTier(currentTierRef.current);
            lowStartRef.current = 0;
          }
          highStartRef.current = 0;
        }
        // Promote if sustained 55+ fps for 5s
        else if (avg > 55) {
          lowStartRef.current = 0;
          if (highStartRef.current === 0) highStartRef.current = now;
          const initialIdx = TIER_ORDER.indexOf(initialTierRef.current);
          if (now - highStartRef.current > 5000 && tierIdx > initialIdx) {
            currentTierRef.current = TIER_ORDER[tierIdx - 1];
            setQualityTier(currentTierRef.current);
            highStartRef.current = 0;
          }
        } else {
          lowStartRef.current = 0;
          highStartRef.current = 0;
        }
      }

      rafId = requestAnimationFrame(tick);
    }

    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, [qualityMode, setQualityTier]);

  return null;
}
```

**Step 2: Commit**

```bash
git add src/experience/quality/QualityManager.tsx
git commit -m "feat(kernel): quality manager — auto-degrade/promote based on FPS"
```

---

### Task 10: Debug HUD

**Files:**
- Create: `src/experience/quality/DebugHUD.tsx`

**Step 1: Create the component**

```typescript
// src/experience/quality/DebugHUD.tsx
'use client';

import { useState, useEffect, useRef } from 'react';
import { useKernelStore } from '@/experience/state/store';
import { rooms } from '@/lib/tokens';

export function DebugHUD() {
  const [visible, setVisible] = useState(false);
  const [fps, setFps] = useState(0);
  const framesRef = useRef<number[]>([]);

  const state = useKernelStore();

  // Toggle with Ctrl+Shift+D
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key === 'D') {
        e.preventDefault();
        setVisible((v) => !v);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  // FPS counter
  useEffect(() => {
    if (!visible) return;
    let rafId: number;
    let lastTime = performance.now();

    function tick() {
      const now = performance.now();
      const dt = now - lastTime;
      lastTime = now;
      if (dt > 0) {
        framesRef.current.push(1000 / dt);
        if (framesRef.current.length > 60) framesRef.current.shift();
        const avg = framesRef.current.reduce((a, b) => a + b, 0) / framesRef.current.length;
        setFps(Math.round(avg));
      }
      rafId = requestAnimationFrame(tick);
    }

    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, [visible]);

  if (!visible) return null;

  const room = rooms[state.currentChapter] ?? rooms[0];

  return (
    <div
      className="fixed top-20 right-4 z-[9999] bg-asphalt/95 border border-steel/40 p-3 font-telemetry text-[10px] leading-relaxed pointer-events-none select-none"
      style={{ minWidth: 200 }}
      aria-hidden="true"
    >
      <div className="text-acid-green mb-1">DEBUG HUD</div>
      <div>FPS: <span className={fps < 40 ? 'text-safety-red' : 'text-chalk'}>{fps}</span></div>
      <div>Quality: {state.qualityTier} ({state.qualityMode})</div>
      <div>Chapter: {room.id} [{state.currentChapter}]</div>
      <div>Progress: {state.globalProgress.toFixed(3)}</div>
      <div>Ch.Progress: {state.chapterProgress.toFixed(3)}</div>
      <div>Velocity: {state.scrollVelocity.toFixed(3)}</div>
      <div>Pointer: {state.pointerX.toFixed(2)}, {state.pointerY.toFixed(2)}</div>
      <div>Mode: {state.mode}</div>
      <div>WebGL: {state.webglAvailable ? 'yes' : 'no'}</div>
      <div>ReducedMotion: {state.reducedMotion ? 'yes' : 'no'}</div>
      <div>Preloader: {state.preloaderComplete ? 'done' : `${(state.loadProgress * 100).toFixed(0)}%`}</div>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add src/experience/quality/DebugHUD.tsx
git commit -m "feat(kernel): debug HUD — Ctrl+Shift+D toggles FPS/state overlay"
```

---

### Task 11: Fallback Shell

**Files:**
- Create: `src/experience/quality/FallbackShell.tsx`

**Step 1: Create the component**

```typescript
// src/experience/quality/FallbackShell.tsx
'use client';

import type { ReactNode } from 'react';

interface FallbackShellProps {
  children: ReactNode;
}

/**
 * DOM-only fallback when WebGL is unavailable.
 * Wraps content with CSS-only atmosphere (grain, radial gradients).
 * All content, interactions, and Lenis scroll still work.
 */
export function FallbackShell({ children }: FallbackShellProps) {
  return (
    <div className="texture-grain min-h-screen">
      {children}
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add src/experience/quality/FallbackShell.tsx
git commit -m "feat(kernel): fallback shell — CSS-only atmosphere for no-WebGL"
```

---

## Phase 4: Renderer

### Task 12: Experience Canvas (R3F)

**Files:**
- Create: `src/experience/renderer/ExperienceCanvas.tsx`

**Step 1: Create the component**

```typescript
// src/experience/renderer/ExperienceCanvas.tsx
'use client';

import { Suspense } from 'react';
import { Canvas } from '@react-three/fiber';
import { useKernelStore } from '@/experience/state/store';
import { SceneManager } from './SceneManager';
import { PostStack } from './PostStack';

export function ExperienceCanvas() {
  const webglAvailable = useKernelStore((s) => s.webglAvailable);
  const reducedMotion = useKernelStore((s) => s.reducedMotion);
  const qualityTier = useKernelStore((s) => s.qualityTier);

  if (!webglAvailable) return null;

  const dpr = qualityTier === 'high' ? [1, 2] : qualityTier === 'balanced' ? [0.75, 1.5] : [0.5, 1];

  return (
    <div
      className="fixed inset-0 z-0 pointer-events-none"
      aria-hidden="true"
    >
      <Canvas
        dpr={dpr as [number, number]}
        gl={{
          antialias: qualityTier === 'high',
          alpha: true,
          powerPreference: 'high-performance',
        }}
        camera={{ position: [0, 0, 5], fov: 50 }}
        style={{ background: 'transparent' }}
      >
        <Suspense fallback={null}>
          <SceneManager />
          {!reducedMotion && qualityTier !== 'low' && <PostStack />}
        </Suspense>
      </Canvas>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add src/experience/renderer/ExperienceCanvas.tsx
git commit -m "feat(kernel): R3F canvas — fixed fullscreen behind DOM, quality-aware DPR"
```

---

### Task 13: Post-Processing Stack

**Files:**
- Create: `src/experience/renderer/PostStack.tsx`

**Step 1: Create the component**

```typescript
// src/experience/renderer/PostStack.tsx
'use client';

import { EffectComposer, Bloom, Noise, ChromaticAberration } from '@react-three/postprocessing';
import { BlendFunction } from 'postprocessing';
import { useKernelStore } from '@/experience/state/store';
import { Vector2 } from 'three';

export function PostStack() {
  const qualityTier = useKernelStore((s) => s.qualityTier);
  const scrollVelocity = useKernelStore((s) => s.scrollVelocity);
  const mode = useKernelStore((s) => s.mode);

  // Chromatic aberration only during transitions or fast scroll
  const chromaIntensity =
    mode === 'transitioning'
      ? 0.003
      : Math.abs(scrollVelocity) > 0.3
        ? Math.abs(scrollVelocity) * 0.002
        : 0;

  return (
    <EffectComposer multisampling={qualityTier === 'high' ? 4 : 0}>
      <Bloom
        intensity={0.15}
        luminanceThreshold={0.8}
        luminanceSmoothing={0.9}
        mipmapBlur
      />
      <Noise
        premultiply
        blendFunction={BlendFunction.SOFT_LIGHT}
        opacity={0.15}
      />
      {chromaIntensity > 0 && (
        <ChromaticAberration
          offset={new Vector2(chromaIntensity, chromaIntensity)}
          radialModulation={false}
          modulationOffset={0}
        />
      )}
    </EffectComposer>
  );
}
```

**Step 2: Commit**

```bash
git add src/experience/renderer/PostStack.tsx
git commit -m "feat(kernel): post-processing stack — bloom, grain, chromatic aberration"
```

---

### Task 14: Scene Manager

**Files:**
- Create: `src/experience/renderer/SceneManager.tsx`

**Step 1: Create the component**

```typescript
// src/experience/renderer/SceneManager.tsx
'use client';

import { useMemo } from 'react';
import { useKernelStore } from '@/experience/state/store';
import type { ChapterConfig, ChapterSceneProps } from '@/experience/state/types';

// Chapter configs will be registered here
const chapterRegistry: ChapterConfig[] = [];

export function registerChapter(config: ChapterConfig) {
  const existing = chapterRegistry.findIndex((c) => c.id === config.id);
  if (existing >= 0) {
    chapterRegistry[existing] = config;
  } else {
    chapterRegistry.push(config);
    chapterRegistry.sort((a, b) => a.index - b.index);
  }
}

export function getChapterConfigs(): readonly ChapterConfig[] {
  return chapterRegistry;
}

export function SceneManager() {
  const currentChapter = useKernelStore((s) => s.currentChapter);
  const chapterProgress = useKernelStore((s) => s.chapterProgress);
  const scrollVelocity = useKernelStore((s) => s.scrollVelocity);
  const pointerX = useKernelStore((s) => s.pointerX);
  const pointerY = useKernelStore((s) => s.pointerY);
  const qualityTier = useKernelStore((s) => s.qualityTier);

  // Render current + adjacent scenes for transition readiness
  const visibleIndices = useMemo(() => {
    const indices = new Set<number>();
    indices.add(currentChapter);
    if (currentChapter > 0) indices.add(currentChapter - 1);
    if (currentChapter < chapterRegistry.length - 1) indices.add(currentChapter + 1);
    return indices;
  }, [currentChapter]);

  const sceneProps: Omit<ChapterSceneProps, 'active'> = {
    progress: chapterProgress,
    scrollVelocity,
    pointerX,
    pointerY,
    qualityTier,
  };

  return (
    <group>
      {chapterRegistry.map((config) => {
        if (!config.scene) return null;
        const isVisible = visibleIndices.has(config.index);
        if (!isVisible) return null;

        const Scene = config.scene;
        return (
          <Scene
            key={config.id}
            {...sceneProps}
            active={config.index === currentChapter}
          />
        );
      })}
    </group>
  );
}
```

**Step 2: Commit**

```bash
git add src/experience/renderer/SceneManager.tsx
git commit -m "feat(kernel): scene manager — chapter registry + visible scene rendering"
```

---

### Task 15: Base Atmosphere Scene

**Files:**
- Create: `src/experience/renderer/scenes/AtmosphereBase.tsx`

This is a shared base scene that all chapter scenes extend. It provides the persistent fog/particles/noise.

**Step 1: Create the component**

```typescript
// src/experience/renderer/scenes/AtmosphereBase.tsx
'use client';

import { useRef, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import type { ChapterSceneProps } from '@/experience/state/types';

interface AtmosphereBaseProps extends ChapterSceneProps {
  color?: string;
  fogDensity?: number;
  particleCount?: number;
}

export function AtmosphereBase({
  color = '#0B0C0F',
  fogDensity = 0.03,
  particleCount = 200,
  progress,
  scrollVelocity,
  pointerX,
  pointerY,
  qualityTier,
  active,
}: AtmosphereBaseProps) {
  const groupRef = useRef<THREE.Group>(null);
  const particlesRef = useRef<THREE.Points>(null);

  const count = qualityTier === 'low' ? 0 : qualityTier === 'balanced' ? Math.floor(particleCount / 2) : particleCount;

  const positions = useMemo(() => {
    const arr = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      arr[i * 3] = (Math.random() - 0.5) * 20;
      arr[i * 3 + 1] = (Math.random() - 0.5) * 20;
      arr[i * 3 + 2] = (Math.random() - 0.5) * 10;
    }
    return arr;
  }, [count]);

  useFrame((_, delta) => {
    if (!active || !particlesRef.current) return;

    // Subtle drift influenced by pointer
    const px = (pointerX - 0.5) * 0.02;
    const py = (pointerY - 0.5) * 0.02;

    particlesRef.current.rotation.y += (px - particlesRef.current.rotation.y) * 0.05;
    particlesRef.current.rotation.x += (py - particlesRef.current.rotation.x) * 0.05;

    // Velocity-driven drift
    const posArray = particlesRef.current.geometry.attributes.position.array as Float32Array;
    const drift = scrollVelocity * delta * 2;
    for (let i = 1; i < posArray.length; i += 3) {
      posArray[i] += drift;
      if (posArray[i] > 10) posArray[i] = -10;
      if (posArray[i] < -10) posArray[i] = 10;
    }
    particlesRef.current.geometry.attributes.position.needsUpdate = true;
  });

  if (count === 0) return null;

  return (
    <group ref={groupRef} visible={active}>
      <fog attach="fog" args={[color, 5, 25]} />
      <ambientLight intensity={0.1} />

      <points ref={particlesRef}>
        <bufferGeometry>
          <bufferAttribute
            attach="attributes-position"
            args={[positions, 3]}
          />
        </bufferGeometry>
        <pointsMaterial
          size={0.03}
          color="#F3F0E8"
          transparent
          opacity={0.3}
          sizeAttenuation
          depthWrite={false}
        />
      </points>
    </group>
  );
}
```

**Step 2: Commit**

```bash
git add src/experience/renderer/scenes/AtmosphereBase.tsx
git commit -m "feat(kernel): atmosphere base scene — fog, particles, pointer-reactive drift"
```

---

### Task 16: Per-Chapter Scenes (9 scenes)

**Files:**
- Create: `src/experience/renderer/scenes/StartGridScene.tsx`
- Create: `src/experience/renderer/scenes/S1Scene.tsx`
- Create: `src/experience/renderer/scenes/S2Scene.tsx`
- Create: `src/experience/renderer/scenes/S3Scene.tsx`
- Create: `src/experience/renderer/scenes/S4Scene.tsx`
- Create: `src/experience/renderer/scenes/S5Scene.tsx`
- Create: `src/experience/renderer/scenes/PitStopScene.tsx`
- Create: `src/experience/renderer/scenes/GarageScene.tsx`
- Create: `src/experience/renderer/scenes/PodiumScene.tsx`

Each scene wraps `AtmosphereBase` with chapter-specific color/density. The S1Scene also includes the distortion field for CornerDrag reactivity.

**Step 1: Create all scene files**

```typescript
// src/experience/renderer/scenes/StartGridScene.tsx
'use client';
import { AtmosphereBase } from './AtmosphereBase';
import type { ChapterSceneProps } from '@/experience/state/types';

export function StartGridScene(props: ChapterSceneProps) {
  return <AtmosphereBase {...props} color="#0B0C0F" fogDensity={0.05} particleCount={300} />;
}
```

```typescript
// src/experience/renderer/scenes/S1Scene.tsx
'use client';
import { useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { AtmosphereBase } from './AtmosphereBase';
import type { ChapterSceneProps } from '@/experience/state/types';

export function S1Scene(props: ChapterSceneProps) {
  const lightRef = useRef<THREE.PointLight>(null);

  // Distortion light reacts to pointer (stand-in for CornerDrag reactivity)
  useFrame(() => {
    if (!lightRef.current || !props.active) return;
    lightRef.current.position.x = (props.pointerX - 0.5) * 8;
    lightRef.current.position.y = (props.pointerY - 0.5) * 5;
  });

  return (
    <group>
      <AtmosphereBase {...props} color="#0B0C0F" fogDensity={0.03} particleCount={250} />
      {props.active && (
        <pointLight
          ref={lightRef}
          color="#B6FF2E"
          intensity={0.4}
          distance={15}
          decay={2}
        />
      )}
    </group>
  );
}
```

```typescript
// src/experience/renderer/scenes/S2Scene.tsx
'use client';
import { AtmosphereBase } from './AtmosphereBase';
import type { ChapterSceneProps } from '@/experience/state/types';

export function S2Scene(props: ChapterSceneProps) {
  return <AtmosphereBase {...props} color="#0D0E12" fogDensity={0.03} particleCount={200} />;
}
```

```typescript
// src/experience/renderer/scenes/S3Scene.tsx
'use client';
import { AtmosphereBase } from './AtmosphereBase';
import type { ChapterSceneProps } from '@/experience/state/types';

export function S3Scene(props: ChapterSceneProps) {
  return <AtmosphereBase {...props} color="#0B0C0F" fogDensity={0.02} particleCount={150} />;
}
```

```typescript
// src/experience/renderer/scenes/S4Scene.tsx
'use client';
import { AtmosphereBase } from './AtmosphereBase';
import type { ChapterSceneProps } from '@/experience/state/types';

export function S4Scene(props: ChapterSceneProps) {
  return <AtmosphereBase {...props} color="#0C0D10" fogDensity={0.025} particleCount={180} />;
}
```

```typescript
// src/experience/renderer/scenes/S5Scene.tsx
'use client';
import { AtmosphereBase } from './AtmosphereBase';
import type { ChapterSceneProps } from '@/experience/state/types';

export function S5Scene(props: ChapterSceneProps) {
  return <AtmosphereBase {...props} color="#0D0E12" fogDensity={0.03} particleCount={200} />;
}
```

```typescript
// src/experience/renderer/scenes/PitStopScene.tsx
'use client';
import { AtmosphereBase } from './AtmosphereBase';
import type { ChapterSceneProps } from '@/experience/state/types';

export function PitStopScene(props: ChapterSceneProps) {
  return <AtmosphereBase {...props} color="#0B0C0F" fogDensity={0.02} particleCount={120} />;
}
```

```typescript
// src/experience/renderer/scenes/GarageScene.tsx
'use client';
import { AtmosphereBase } from './AtmosphereBase';
import type { ChapterSceneProps } from '@/experience/state/types';

export function GarageScene(props: ChapterSceneProps) {
  return <AtmosphereBase {...props} color="#0A0B0E" fogDensity={0.015} particleCount={80} />;
}
```

```typescript
// src/experience/renderer/scenes/PodiumScene.tsx
'use client';
import { useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { AtmosphereBase } from './AtmosphereBase';
import type { ChapterSceneProps } from '@/experience/state/types';

export function PodiumScene(props: ChapterSceneProps) {
  const lightRef = useRef<THREE.PointLight>(null);

  useFrame((state) => {
    if (!lightRef.current || !props.active) return;
    // Breathing glow
    lightRef.current.intensity = 0.3 + Math.sin(state.clock.elapsedTime * 0.8) * 0.15;
  });

  return (
    <group>
      <AtmosphereBase {...props} color="#0B0C0F" fogDensity={0.04} particleCount={300} />
      {props.active && (
        <pointLight
          ref={lightRef}
          color="#FF6A00"
          intensity={0.3}
          distance={20}
          decay={2}
          position={[0, 3, 2]}
        />
      )}
    </group>
  );
}
```

**Step 2: Commit**

```bash
git add src/experience/renderer/scenes/
git commit -m "feat(kernel): 9 per-chapter atmosphere scenes with pointer/velocity reactivity"
```

---

### Task 17: Chapter Configs & Registration

**Files:**
- Create: `src/experience/state/chapters.ts`

**Step 1: Create chapter config registry**

```typescript
// src/experience/state/chapters.ts
import type { ChapterConfig } from './types';
import { StartGridScene } from '@/experience/renderer/scenes/StartGridScene';
import { S1Scene } from '@/experience/renderer/scenes/S1Scene';
import { S2Scene } from '@/experience/renderer/scenes/S2Scene';
import { S3Scene } from '@/experience/renderer/scenes/S3Scene';
import { S4Scene } from '@/experience/renderer/scenes/S4Scene';
import { S5Scene } from '@/experience/renderer/scenes/S5Scene';
import { PitStopScene } from '@/experience/renderer/scenes/PitStopScene';
import { GarageScene } from '@/experience/renderer/scenes/GarageScene';
import { PodiumScene } from '@/experience/renderer/scenes/PodiumScene';

export const chapters: ChapterConfig[] = [
  {
    id: 'start-grid',
    index: 0,
    scene: StartGridScene,
    transition: { enter: 'preloader-unlock', exit: 'refraction' },
    snapWeight: 1.0,
    accentColor: 'none',
  },
  {
    id: 's1-pain',
    index: 1,
    scene: S1Scene,
    transition: { enter: 'refraction', exit: 'crossfade-blur' },
    snapWeight: 1.0,
    accentColor: 'green',
  },
  {
    id: 's1-deep',
    index: 2,
    scene: S1Scene,
    transition: { enter: 'crossfade-blur', exit: 'mask-wipe' },
    snapWeight: 1.0,
    accentColor: 'green',
  },
  {
    id: 's2-pipeline',
    index: 3,
    scene: S2Scene,
    transition: { enter: 'mask-wipe', exit: 'crossfade-blur' },
    snapWeight: 1.0,
    accentColor: 'yellow',
  },
  {
    id: 's2-proof',
    index: 4,
    scene: S2Scene,
    transition: { enter: 'crossfade-blur', exit: 'mask-wipe' },
    snapWeight: 1.0,
    accentColor: 'yellow',
  },
  {
    id: 's3-product',
    index: 5,
    scene: S3Scene,
    transition: { enter: 'mask-wipe', exit: 'crossfade-blur' },
    snapWeight: 1.0,
    accentColor: 'green',
  },
  {
    id: 's4-workflows',
    index: 6,
    scene: S4Scene,
    transition: { enter: 'crossfade-blur', exit: 'velocity-warp' },
    snapWeight: 1.0,
    accentColor: 'yellow',
  },
  {
    id: 's5-personas',
    index: 7,
    scene: S5Scene,
    transition: { enter: 'velocity-warp', exit: 'mask-wipe' },
    snapWeight: 1.0,
    accentColor: 'orange',
  },
  {
    id: 'pit-stop',
    index: 8,
    scene: PitStopScene,
    transition: { enter: 'mask-wipe', exit: 'crossfade-blur' },
    snapWeight: 1.0,
    accentColor: 'orange',
  },
  {
    id: 'garage',
    index: 9,
    scene: GarageScene,
    transition: { enter: 'crossfade-blur', exit: 'refraction' },
    snapWeight: 1.0,
    accentColor: 'none',
  },
  {
    id: 'podium',
    index: 10,
    scene: PodiumScene,
    transition: { enter: 'refraction', exit: 'none' },
    snapWeight: 1.0,
    accentColor: 'orange',
  },
];
```

**Step 2: Commit**

```bash
git add src/experience/state/chapters.ts
git commit -m "feat(kernel): chapter configs — all 11 rooms registered with scenes + transitions"
```

---

## Phase 5: Transitions

### Task 18: Transition Shaders (GLSL as TS strings)

**Files:**
- Create: `src/experience/transitions/shaders/crossfade-blur.ts`
- Create: `src/experience/transitions/shaders/mask-wipe.ts`
- Create: `src/experience/transitions/shaders/velocity-warp.ts`
- Create: `src/experience/transitions/shaders/refraction.ts`

Since Next.js doesn't natively import .glsl files without extra config, we'll store shaders as exported strings.

**Step 1: Create all 4 shader files**

```typescript
// src/experience/transitions/shaders/crossfade-blur.ts
export const crossfadeBlurFragment = /* glsl */ `
uniform sampler2D tFrom;
uniform sampler2D tTo;
uniform float uProgress;
varying vec2 vUv;

void main() {
  float p = smoothstep(0.0, 1.0, uProgress);
  float blurAmount = 8.0 * (1.0 - abs(p - 0.5) * 2.0); // Peak blur at midpoint

  // Simplified directional blur via offset samples
  vec2 dir = vec2(blurAmount / 1000.0, 0.0);
  vec4 fromColor = vec4(0.0);
  vec4 toColor = vec4(0.0);

  for (int i = -4; i <= 4; i++) {
    vec2 offset = dir * float(i);
    fromColor += texture2D(tFrom, vUv + offset);
    toColor += texture2D(tTo, vUv + offset);
  }
  fromColor /= 9.0;
  toColor /= 9.0;

  gl_FragColor = mix(fromColor, toColor, p);
}
`;

export const crossfadeBlurVertex = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;
```

```typescript
// src/experience/transitions/shaders/mask-wipe.ts
export const maskWipeFragment = /* glsl */ `
uniform sampler2D tFrom;
uniform sampler2D tTo;
uniform float uProgress;
uniform vec3 uAccentColor;
varying vec2 vUv;

void main() {
  float edge = smoothstep(uProgress - 0.005, uProgress + 0.005, vUv.x);
  vec4 fromColor = texture2D(tFrom, vUv);
  vec4 toColor = texture2D(tTo, vUv);

  // Accent-colored leading edge (2px feather)
  float edgeGlow = smoothstep(uProgress - 0.01, uProgress, vUv.x)
                 * smoothstep(uProgress + 0.01, uProgress, vUv.x);
  vec4 accent = vec4(uAccentColor, 1.0) * edgeGlow * 2.0;

  gl_FragColor = mix(toColor, fromColor, edge) + accent;
}
`;

export const maskWipeVertex = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;
```

```typescript
// src/experience/transitions/shaders/velocity-warp.ts
export const velocityWarpFragment = /* glsl */ `
uniform sampler2D tFrom;
uniform sampler2D tTo;
uniform float uProgress;
uniform float uVelocity;
varying vec2 vUv;

void main() {
  float p = smoothstep(0.0, 1.0, uProgress);

  // Warp UV based on velocity and progress
  float warpStrength = abs(uVelocity) * 0.3 * sin(p * 3.14159);
  vec2 warpedUv = vUv;
  warpedUv.y += warpStrength * sign(uVelocity) * sin(vUv.x * 6.28318);

  vec4 fromColor = texture2D(tFrom, warpedUv);
  vec4 toColor = texture2D(tTo, vUv);

  gl_FragColor = mix(fromColor, toColor, p);
}
`;

export const velocityWarpVertex = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;
```

```typescript
// src/experience/transitions/shaders/refraction.ts
export const refractionFragment = /* glsl */ `
uniform sampler2D tFrom;
uniform sampler2D tTo;
uniform float uProgress;
uniform float uTime;
varying vec2 vUv;

void main() {
  float p = smoothstep(0.0, 1.0, uProgress);

  // Glass-like refraction distortion that clears over time
  float distortion = (1.0 - p) * 0.05;
  vec2 offset = vec2(
    sin(vUv.y * 20.0 + uTime * 2.0) * distortion,
    cos(vUv.x * 20.0 + uTime * 2.0) * distortion
  );

  vec4 fromColor = texture2D(tFrom, vUv + offset);
  vec4 toColor = texture2D(tTo, vUv);

  // Fresnel-like edge brightening during transition
  float fresnel = pow(1.0 - abs(dot(normalize(vec3(vUv - 0.5, 1.0)), vec3(0.0, 0.0, 1.0))), 3.0);
  float glow = fresnel * (1.0 - p) * 0.3;

  gl_FragColor = mix(fromColor, toColor, p) + vec4(glow);
}
`;

export const refractionVertex = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;
```

**Step 2: Commit**

```bash
git add src/experience/transitions/shaders/
git commit -m "feat(kernel): 4 transition shaders — crossfade-blur, mask-wipe, velocity-warp, refraction"
```

---

### Task 19: Transition Library

**Files:**
- Create: `src/experience/transitions/TransitionLibrary.ts`

**Step 1: Create the registry**

```typescript
// src/experience/transitions/TransitionLibrary.ts
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
```

**Step 2: Commit**

```bash
git add src/experience/transitions/TransitionLibrary.ts
git commit -m "feat(kernel): transition library — chapter pair → transition type mapping"
```

---

### Task 20: Transition Compositor

**Files:**
- Create: `src/experience/transitions/TransitionCompositor.tsx`

**Step 1: Create the component**

This component uses `useFBO` from drei to capture the outgoing scene to a render target, then composites with the incoming scene via a shader material on a fullscreen quad.

```typescript
// src/experience/transitions/TransitionCompositor.tsx
'use client';

import { useRef, useEffect, useState, useCallback } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import { useFBO } from '@react-three/drei';
import * as THREE from 'three';
import { useKernelStore } from '@/experience/state/store';
import { getTransitionType } from './TransitionLibrary';
import { crossfadeBlurFragment, crossfadeBlurVertex } from './shaders/crossfade-blur';
import { maskWipeFragment, maskWipeVertex } from './shaders/mask-wipe';
import { velocityWarpFragment, velocityWarpVertex } from './shaders/velocity-warp';
import { refractionFragment, refractionVertex } from './shaders/refraction';
import { rooms } from '@/lib/tokens';
import { timing } from '@/lib/tokens';

const SHADERS: Record<string, { vertex: string; fragment: string }> = {
  'crossfade-blur': { vertex: crossfadeBlurVertex, fragment: crossfadeBlurFragment },
  'mask-wipe': { vertex: maskWipeVertex, fragment: maskWipeFragment },
  'velocity-warp': { vertex: velocityWarpVertex, fragment: velocityWarpFragment },
  'refraction': { vertex: refractionVertex, fragment: refractionFragment },
};

export function TransitionCompositor() {
  const { gl, scene, camera } = useThree();
  const fboFrom = useFBO();
  const [transitioning, setTransitioning] = useState(false);
  const progressRef = useRef(0);
  const prevChapterRef = useRef(0);
  const materialRef = useRef<THREE.ShaderMaterial | null>(null);

  const currentChapter = useKernelStore((s) => s.currentChapter);
  const scrollVelocity = useKernelStore((s) => s.scrollVelocity);
  const setMode = useKernelStore((s) => s.setMode);

  const startTransition = useCallback(() => {
    // Capture current scene to FBO
    gl.setRenderTarget(fboFrom);
    gl.render(scene, camera);
    gl.setRenderTarget(null);

    progressRef.current = 0;
    setTransitioning(true);
    setMode('transitioning');
  }, [gl, scene, camera, fboFrom, setMode]);

  // Detect chapter changes
  useEffect(() => {
    if (currentChapter !== prevChapterRef.current) {
      startTransition();
      prevChapterRef.current = currentChapter;
    }
  }, [currentChapter, startTransition]);

  useFrame((_, delta) => {
    if (!transitioning || !materialRef.current) return;

    progressRef.current += delta / timing.room;

    if (progressRef.current >= 1) {
      progressRef.current = 1;
      setTransitioning(false);
      setMode('idle');
    }

    materialRef.current.uniforms.uProgress.value = progressRef.current;
    materialRef.current.uniforms.uTime.value += delta;
    if (materialRef.current.uniforms.uVelocity) {
      materialRef.current.uniforms.uVelocity.value = scrollVelocity;
    }
  });

  if (!transitioning) return null;

  const fromId = rooms[prevChapterRef.current]?.id ?? 'start-grid';
  const toId = rooms[currentChapter]?.id ?? 'start-grid';
  const type = getTransitionType(fromId, toId);
  const shader = SHADERS[type] ?? SHADERS['crossfade-blur'];

  return (
    <mesh renderOrder={999}>
      <planeGeometry args={[2, 2]} />
      <shaderMaterial
        ref={materialRef}
        vertexShader={shader.vertex}
        fragmentShader={shader.fragment}
        uniforms={{
          tFrom: { value: fboFrom.texture },
          tTo: { value: null }, // Current scene renders naturally behind
          uProgress: { value: 0 },
          uVelocity: { value: 0 },
          uTime: { value: 0 },
          uAccentColor: { value: new THREE.Color('#F3F0E8') },
        }}
        transparent
        depthTest={false}
        depthWrite={false}
      />
    </mesh>
  );
}
```

**Step 2: Commit**

```bash
git add src/experience/transitions/TransitionCompositor.tsx
git commit -m "feat(kernel): transition compositor — FBO capture + shader bridge between chapters"
```

---

## Phase 6: Motion & Preloader

### Task 21: Motion Orchestrator & Timeline Factory

**Files:**
- Create: `src/experience/motion/timeline.ts`
- Create: `src/experience/motion/MotionOrchestrator.tsx`

**Step 1: Create timeline factory**

```typescript
// src/experience/motion/timeline.ts
import { gsap } from 'gsap';
import { timing, easing } from '@/lib/tokens';

export type TimelineType = 'enter' | 'exit' | 'scrub';

interface TimelineOptions {
  target: Element | string;
  type: TimelineType;
  delay?: number;
  onComplete?: () => void;
}

export function createRoomTimeline({ target, type, delay = 0, onComplete }: TimelineOptions) {
  const tl = gsap.timeline({ delay, onComplete });

  switch (type) {
    case 'enter':
      tl.fromTo(target, {
        opacity: 0,
        y: 30,
        filter: 'blur(8px)',
      }, {
        opacity: 1,
        y: 0,
        filter: 'blur(0px)',
        duration: timing.room,
        ease: easing.inertia,
      });
      break;

    case 'exit':
      tl.to(target, {
        opacity: 0,
        y: -20,
        filter: 'blur(8px)',
        duration: timing.room,
        ease: easing.snap,
      });
      break;

    case 'scrub':
      // Returns a timeline meant to be scrubbed via ScrollTrigger
      tl.fromTo(target, {
        opacity: 0.3,
        y: 40,
      }, {
        opacity: 1,
        y: 0,
        duration: 1, // Normalized for scrub
        ease: 'none',
      });
      break;
  }

  return tl;
}
```

```typescript
// src/experience/motion/MotionOrchestrator.tsx
'use client';

import { useEffect, useRef } from 'react';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { useKernelStore } from '@/experience/state/store';
import { rooms, timing, easing } from '@/lib/tokens';

gsap.registerPlugin(ScrollTrigger);

export function MotionOrchestrator() {
  const prevChapterRef = useRef(0);
  const currentChapter = useKernelStore((s) => s.currentChapter);
  const reducedMotion = useKernelStore((s) => s.reducedMotion);

  // DOM room enter/exit synchronized with WebGL transitions
  useEffect(() => {
    if (reducedMotion) return;

    const prevIdx = prevChapterRef.current;
    if (currentChapter === prevIdx) return;
    prevChapterRef.current = currentChapter;

    const prevRoom = rooms[prevIdx];
    const nextRoom = rooms[currentChapter];

    const prevEl = prevRoom ? document.getElementById(prevRoom.id) : null;
    const nextEl = nextRoom ? document.getElementById(nextRoom.id) : null;

    // Exit previous
    if (prevEl) {
      gsap.to(prevEl, {
        opacity: 0,
        filter: 'blur(6px)',
        y: -15,
        duration: timing.room * 0.6,
        ease: easing.snap,
      });
    }

    // Enter next
    if (nextEl) {
      gsap.fromTo(nextEl, {
        opacity: 0,
        filter: 'blur(6px)',
        y: 20,
      }, {
        opacity: 1,
        filter: 'blur(0px)',
        y: 0,
        duration: timing.room,
        ease: easing.inertia,
        delay: timing.room * 0.3,
      });
    }
  }, [currentChapter, reducedMotion]);

  // MonumentText reveal via ScrollTrigger (replaces per-component GSAP)
  useEffect(() => {
    if (reducedMotion) return;

    const monuments = document.querySelectorAll('[data-monument-reveal]');
    monuments.forEach((el) => {
      gsap.fromTo(el, {
        clipPath: 'inset(0 100% 0 0)',
      }, {
        clipPath: 'inset(0 0% 0 0)',
        duration: timing.monument,
        ease: easing.inertia,
        scrollTrigger: {
          trigger: el,
          start: 'top 80%',
          toggleActions: 'play none none none',
        },
      });
    });

    return () => ScrollTrigger.getAll().forEach((st) => st.kill());
  }, [reducedMotion]);

  return null;
}
```

**Step 2: Commit**

```bash
git add src/experience/motion/timeline.ts src/experience/motion/MotionOrchestrator.tsx
git commit -m "feat(kernel): motion orchestrator — DOM enter/exit sync + monument reveals via ScrollTrigger"
```

---

### Task 22: Preloader

**Files:**
- Create: `src/experience/preloader/PreloaderTimeline.ts`
- Create: `src/experience/preloader/PreloaderScene.tsx`
- Create: `src/experience/preloader/Preloader.tsx`

**Step 1: Create PreloaderTimeline**

```typescript
// src/experience/preloader/PreloaderTimeline.ts
export interface PreloaderStage {
  label: string;
  weight: number; // Fraction of total progress this stage represents
}

export const PRELOADER_STAGES: PreloaderStage[] = [
  { label: 'LOADING CORE', weight: 0.4 },
  { label: 'BUILDING SCENES', weight: 0.4 },
  { label: 'PREPARING', weight: 0.2 },
];

export const PRELOADER_AUTO_UNLOCK_MS = 3000;
export const PRELOADER_BLACK_MS = 300;
export const PRELOADER_WORDMARK_MS = 1400;
```

**Step 2: Create PreloaderScene**

```typescript
// src/experience/preloader/PreloaderScene.tsx
'use client';

import { useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';

export function PreloaderScene() {
  const lightRef = useRef<THREE.PointLight>(null);

  useFrame((state) => {
    if (!lightRef.current) return;
    // Gentle breathing pulse
    lightRef.current.intensity = 0.2 + Math.sin(state.clock.elapsedTime * 1.5) * 0.1;
  });

  return (
    <group>
      <ambientLight intensity={0.05} />
      <pointLight ref={lightRef} color="#F3F0E8" intensity={0.2} position={[0, 0, 3]} />
      {/* Subtle noise grain particles */}
      <points>
        <bufferGeometry>
          <bufferAttribute
            attach="attributes-position"
            args={[new Float32Array(
              Array.from({ length: 300 }, () => [(Math.random() - 0.5) * 15, (Math.random() - 0.5) * 15, (Math.random() - 0.5) * 8]).flat()
            ), 3]}
          />
        </bufferGeometry>
        <pointsMaterial size={0.02} color="#F3F0E8" transparent opacity={0.15} depthWrite={false} />
      </points>
    </group>
  );
}
```

**Step 3: Create Preloader**

```typescript
// src/experience/preloader/Preloader.tsx
'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useKernelStore } from '@/experience/state/store';
import { PRELOADER_AUTO_UNLOCK_MS, PRELOADER_BLACK_MS, PRELOADER_WORDMARK_MS } from './PreloaderTimeline';
import { timing } from '@/lib/tokens';

export function Preloader() {
  const [phase, setPhase] = useState<'black' | 'wordmark' | 'loading' | 'ready' | 'unlocking' | 'done'>('black');
  const loadProgress = useKernelStore((s) => s.loadProgress);
  const setLoadProgress = useKernelStore((s) => s.setLoadProgress);
  const completePreloader = useKernelStore((s) => s.completePreloader);
  const preloaderComplete = useKernelStore((s) => s.preloaderComplete);
  const autoUnlockRef = useRef<ReturnType<typeof setTimeout>>();

  // Phase progression
  useEffect(() => {
    const t1 = setTimeout(() => setPhase('wordmark'), PRELOADER_BLACK_MS);
    const t2 = setTimeout(() => {
      setPhase('loading');
      // Simulate staged loading (in production, hook into real asset loading)
      let progress = 0;
      const interval = setInterval(() => {
        progress += 0.02 + Math.random() * 0.03;
        if (progress >= 1) {
          progress = 1;
          clearInterval(interval);
          setPhase('ready');
        }
        setLoadProgress(Math.min(1, progress));
      }, 50);
    }, PRELOADER_BLACK_MS + PRELOADER_WORDMARK_MS);

    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, [setLoadProgress]);

  // Auto-unlock after timeout if user doesn't interact
  useEffect(() => {
    if (phase !== 'ready') return;
    autoUnlockRef.current = setTimeout(() => unlock(), PRELOADER_AUTO_UNLOCK_MS);
    return () => clearTimeout(autoUnlockRef.current);
  }, [phase]);

  const unlock = useCallback(() => {
    if (phase !== 'ready' && phase !== 'loading') return;
    clearTimeout(autoUnlockRef.current);
    setPhase('unlocking');
    // Transition duration then complete
    setTimeout(() => {
      setPhase('done');
      completePreloader();
    }, timing.monument * 1000);
  }, [phase, completePreloader]);

  // Handle user interaction to unlock
  useEffect(() => {
    if (phase !== 'ready') return;

    const handler = () => unlock();
    window.addEventListener('click', handler);
    window.addEventListener('touchstart', handler);
    window.addEventListener('wheel', handler);
    window.addEventListener('keydown', handler);

    return () => {
      window.removeEventListener('click', handler);
      window.removeEventListener('touchstart', handler);
      window.removeEventListener('wheel', handler);
      window.removeEventListener('keydown', handler);
    };
  }, [phase, unlock]);

  if (preloaderComplete || phase === 'done') return null;

  return (
    <div
      className="fixed inset-0 z-[9999] flex flex-col items-center justify-center bg-asphalt"
      style={{
        opacity: phase === 'unlocking' ? 0 : 1,
        transition: `opacity ${timing.monument}s var(--ease-inertia)`,
      }}
    >
      {/* Wordmark */}
      <div
        className="font-monument text-chalk transition-opacity"
        style={{
          fontSize: 'clamp(48px, 8vw, 120px)',
          opacity: phase === 'black' ? 0 : 1,
          transitionDuration: `${timing.monument}s`,
          transitionTimingFunction: 'var(--ease-inertia)',
        }}
      >
        LAP
      </div>

      {/* Progress bar */}
      {(phase === 'loading' || phase === 'ready') && (
        <div className="w-48 h-px bg-steel/30 mt-8 overflow-hidden">
          <div
            className="h-full bg-chalk transition-all"
            style={{
              width: `${loadProgress * 100}%`,
              transitionDuration: '100ms',
            }}
          />
        </div>
      )}

      {/* Ready text */}
      {phase === 'ready' && (
        <p
          className="font-telemetry text-steel mt-6 animate-pulse"
          style={{
            animationDuration: '2s',
          }}
        >
          READY — CLICK TO BEGIN
        </p>
      )}
    </div>
  );
}
```

**Step 4: Commit**

```bash
git add src/experience/preloader/
git commit -m "feat(kernel): preloader ritual — staged load, wordmark, progress, unlock sequence"
```

---

## Phase 7: Shell Integration

### Task 23: Experience Kernel Provider

**Files:**
- Create: `src/experience/ExperienceKernel.tsx`

**Step 1: Create the root provider**

```typescript
// src/experience/ExperienceKernel.tsx
'use client';

import type { ReactNode } from 'react';
import { InputManager } from './input/InputManager';
import { QualityManager } from './quality/QualityManager';
import { DebugHUD } from './quality/DebugHUD';
import { MotionOrchestrator } from './motion/MotionOrchestrator';
import { chapters } from './state/chapters';
import { registerChapter } from './renderer/SceneManager';

// Register all chapters on module load
chapters.forEach(registerChapter);

interface ExperienceKernelProps {
  children: ReactNode;
}

export function ExperienceKernel({ children }: ExperienceKernelProps) {
  return (
    <>
      <QualityManager />
      <InputManager />
      <MotionOrchestrator />
      <DebugHUD />
      {children}
    </>
  );
}
```

**Step 2: Commit**

```bash
git add src/experience/ExperienceKernel.tsx
git commit -m "feat(kernel): ExperienceKernel provider — registers chapters, composes all kernel modules"
```

---

### Task 24: Experience Shell (replaces ChromeLayout for home)

**Files:**
- Create: `src/experience/ExperienceShell.tsx`
- Modify: `src/app/(marketing)/layout.tsx`
- Modify: `src/components/chrome/ChromeLayout.tsx`

**Step 1: Create ExperienceShell**

```typescript
// src/experience/ExperienceShell.tsx
'use client';

import { type ReactNode } from 'react';
import { usePathname } from 'next/navigation';
import { ExperienceKernel } from './ExperienceKernel';
import { ExperienceCanvas } from './renderer/ExperienceCanvas';
import { TransitionCompositor } from './transitions/TransitionCompositor';
import { Preloader } from './preloader/Preloader';
import { FallbackShell } from './quality/FallbackShell';
import { useKernelStore } from './state/store';
import { CustomCursor } from '@/components/chrome/CustomCursor';
import { DeltaStrip } from '@/components/chrome/DeltaStrip';
import { SectorTabs } from '@/components/chrome/SectorTabs';
import { TimecodeCounter } from '@/components/chrome/TimecodeCounter';
import { IndexOverlay } from '@/components/chrome/IndexOverlay';
import { SiteHeader } from '@/components/site/SiteHeader';
import { SiteFooter } from '@/components/site/SiteFooter';
import { useState, useCallback } from 'react';
import { useChapter } from './hooks/useChapter';

function ExperienceContent({ children }: { children: ReactNode }) {
  const [overlayOpen, setOverlayOpen] = useState(false);
  const { id: activeRoom } = useChapter();
  const webglAvailable = useKernelStore((s) => s.webglAvailable);

  const toggleOverlay = useCallback(() => setOverlayOpen((prev) => !prev), []);
  const closeOverlay = useCallback(() => setOverlayOpen(false), []);

  const content = (
    <>
      <SiteHeader showIndexToggle onIndexToggle={toggleOverlay} />
      <CustomCursor />
      <TimecodeCounter />
      <SectorTabs />
      <DeltaStrip />
      <IndexOverlay isOpen={overlayOpen} onClose={closeOverlay} fromSection={activeRoom} />

      {/* Layer 1: WebGL */}
      {webglAvailable && (
        <ExperienceCanvas />
      )}

      {/* Layer 2: DOM content */}
      <div className="relative z-10">
        {children}
      </div>

      <SiteFooter />
    </>
  );

  return webglAvailable ? content : <FallbackShell>{content}</FallbackShell>;
}

export function ExperienceShell({ children }: { children: ReactNode }) {
  return (
    <ExperienceKernel>
      <Preloader />
      <ExperienceContent>{children}</ExperienceContent>
    </ExperienceKernel>
  );
}
```

**Step 2: Update marketing layout to use ExperienceShell on homepage**

Modify `src/app/(marketing)/layout.tsx`:

```typescript
import type { ReactNode } from 'react';
import { ExperienceShell } from '@/experience/ExperienceShell';
import { ChromeLayout } from '@/components/chrome/ChromeLayout';
import { CookieConsentBanner } from '@/components/site/CookieConsentBanner';

export default function MarketingLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <a
        href="/pricing"
        className="sr-only focus:not-sr-only focus:fixed focus:top-4 focus:left-1/2 focus:-translate-x-1/2 focus:z-[200] font-telemetry bg-asphalt text-chalk px-4 py-2 border-2 border-chalk"
      >
        Skip to pricing
      </a>
      <ExperienceShell>{children}</ExperienceShell>
      <CookieConsentBanner />
    </>
  );
}
```

Note: This applies ExperienceShell to ALL marketing pages. The ExperienceShell detects homepage vs subpage internally and adapts. For non-home marketing pages, the WebGL canvas and chrome elements are still available but chapter navigation is disabled.

**Step 3: Verify build**

Run: `npm run build 2>&1 | tail -10`
Expected: Build succeeds.

**Step 4: Commit**

```bash
git add src/experience/ExperienceShell.tsx src/app/\(marketing\)/layout.tsx
git commit -m "feat(kernel): ExperienceShell replaces ChromeLayout — WebGL + DOM layered architecture"
```

---

## Phase 8: Room Refactoring

### Task 25: Refactor MonumentText for Kernel

**Files:**
- Modify: `src/components/ui/MonumentText.tsx`

Remove the self-managed GSAP reveal animation. Instead, add a `data-monument-reveal` attribute that the MotionOrchestrator picks up.

**Step 1: Simplify MonumentText**

Replace the current GSAP useEffect with a data attribute:

```typescript
// src/components/ui/MonumentText.tsx
'use client';

import type { ReactNode } from 'react';

interface MonumentTextProps {
  children: ReactNode;
  size?: 'xl' | 'h1' | 'h2' | 'h3';
  as?: 'h1' | 'h2' | 'h3' | 'p' | 'span';
  className?: string;
  reveal?: boolean;
}

const sizeMap = {
  xl: 'var(--text-monument-xl)',
  h1: 'var(--text-h1)',
  h2: 'var(--text-h2)',
  h3: 'var(--text-h3)',
};

export function MonumentText({
  children,
  size = 'h1',
  as: Tag = 'h2',
  className = '',
  reveal = false,
}: MonumentTextProps) {
  return (
    <Tag
      className={`font-monument ${className}`}
      style={{ fontSize: sizeMap[size] }}
      {...(reveal ? { 'data-monument-reveal': '' } : {})}
    >
      {children}
    </Tag>
  );
}
```

**Step 2: Verify existing tests still pass**

Run: `npx vitest run`
Expected: All tests pass.

**Step 3: Commit**

```bash
git add src/components/ui/MonumentText.tsx
git commit -m "refactor(ui): MonumentText delegates reveal to kernel MotionOrchestrator via data attribute"
```

---

### Task 26: Refactor Room Components

Each room component needs minimal changes:
1. Remove self-managed GSAP imports (if any)
2. Keep all content, copy, CTAs, state, and interactions
3. The kernel handles enter/exit via MotionOrchestrator observing section IDs

The rooms that need changes are **StartGrid** (remove ScrollToPlugin self-management) and **Podium** (same). All other rooms already use section IDs and data-accent — they work as-is with the kernel.

**Files:**
- Modify: `src/components/rooms/StartGrid.tsx`
- Modify: `src/components/rooms/Podium.tsx`

**Step 1: Refactor StartGrid — use kernel for scroll**

Replace the inline `gsap.to(window, { scrollTo: '#s1-pain' })` with the kernel's Lenis instance. The simplest approach: keep the existing logic but import lenis scroll-to.

```typescript
// In StartGrid.tsx, replace the handleComplete scrollTo block:
// OLD:
//   const { gsap } = await import('gsap');
//   const { ScrollToPlugin } = await import('gsap/ScrollToPlugin');
//   gsap.registerPlugin(ScrollToPlugin);
//   gsap.to(window, { scrollTo: '#s1-pain', duration: 0.9, ease: 'power3.out' });
//
// NEW:
    const target = document.getElementById('s1-pain');
    if (target) {
      target.scrollIntoView({ behavior: 'smooth' });
    }
```

Similarly for Podium's restart scroll. The Lenis instance intercepts native scrollIntoView and applies damping.

**Step 2: Refactor Podium — same pattern**

Replace `gsap.to(window, { scrollTo: 0 })` with `window.scrollTo({ top: 0, behavior: 'smooth' })`.

**Step 3: Verify build + tests**

Run: `npm run build && npx vitest run`
Expected: Pass.

**Step 4: Commit**

```bash
git add src/components/rooms/StartGrid.tsx src/components/rooms/Podium.tsx
git commit -m "refactor(rooms): StartGrid + Podium use native scroll (Lenis intercepts) instead of gsap ScrollToPlugin"
```

---

## Phase 9: Microinteractions

### Task 27: Link Underline Animation CSS

**Files:**
- Modify: `src/app/globals.css`

**Step 1: Add animated underline styles**

Append to globals.css:

```css
/* ── Microinteractions ─────────────────── */

/* Animated underline on links */
.room a:not(.no-underline):not([class*="pit-"]):not([class*="stamp-"]) {
  position: relative;
  text-decoration: none;
}

.room a:not(.no-underline):not([class*="pit-"]):not([class*="stamp-"])::after {
  content: '';
  position: absolute;
  bottom: -2px;
  left: 0;
  width: 0;
  height: 1px;
  background: var(--accent);
  transition: width var(--duration-micro) var(--ease-inertia);
}

.room a:not(.no-underline):not([class*="pit-"]):not([class*="stamp-"]):hover::after {
  width: 100%;
}
```

**Step 2: Commit**

```bash
git add src/app/globals.css
git commit -m "feat(micro): animated underline on room links — left-to-right reveal on hover"
```

---

### Task 28: Button Physics CSS

**Files:**
- Modify: `src/app/globals.css`

**Step 1: Add button interaction styles**

Append to globals.css:

```css
/* Button press depth + rebound */
.room button,
.room [role="button"] {
  transition: transform var(--duration-micro) var(--ease-spring);
}

.room button:hover,
.room [role="button"]:hover {
  transform: scale(1.02);
}

.room button:active,
.room [role="button"]:active {
  transform: scale(0.97);
  transition-duration: 60ms;
}
```

**Step 2: Commit**

```bash
git add src/app/globals.css
git commit -m "feat(micro): button press depth + rebound physics via CSS transitions"
```

---

### Task 29: DOM Transition Classes

**Files:**
- Modify: `src/app/globals.css`

**Step 1: Add room transition classes used by MotionOrchestrator**

Append to globals.css:

```css
/* ── Room Transitions (kernel-driven) ──── */
.room {
  transition: opacity var(--duration-room) var(--ease-inertia),
              filter var(--duration-room) var(--ease-inertia),
              transform var(--duration-room) var(--ease-inertia);
}

.room-exiting {
  opacity: 0;
  filter: blur(8px);
  transform: translateY(-20px);
}

.room-entering {
  opacity: 1;
  filter: blur(0);
  transform: translateY(0);
}
```

**Step 2: Commit**

```bash
git add src/app/globals.css
git commit -m "feat(micro): DOM room transition classes — exit blur/fade, enter resolve"
```

---

## Phase 10: Integration Testing

### Task 30: Integration Test — Kernel Store + Chapters

**Files:**
- Create: `src/__tests__/kernel-integration.test.ts`

**Step 1: Write integration test**

```typescript
// src/__tests__/kernel-integration.test.ts
import { describe, it, expect, beforeEach } from 'vitest';
import { useKernelStore } from '@/experience/state/store';
import { chapters } from '@/experience/state/chapters';
import { getTransitionType } from '@/experience/transitions/TransitionLibrary';

describe('Kernel Integration', () => {
  beforeEach(() => {
    useKernelStore.setState(useKernelStore.getInitialState());
  });

  it('has 11 chapter configs matching rooms', () => {
    expect(chapters).toHaveLength(11);
    expect(chapters[0].id).toBe('start-grid');
    expect(chapters[10].id).toBe('podium');
  });

  it('all chapters have scenes assigned', () => {
    chapters.forEach((ch) => {
      expect(ch.scene).toBeTruthy();
    });
  });

  it('transition map covers all adjacent chapter pairs', () => {
    for (let i = 0; i < chapters.length - 1; i++) {
      const from = chapters[i].id;
      const to = chapters[i + 1].id;
      const type = getTransitionType(from, to);
      expect(type).not.toBe('none');
      expect(['crossfade-blur', 'mask-wipe', 'velocity-warp', 'refraction']).toContain(type);
    }
  });

  it('preloader complete transitions to idle mode', () => {
    expect(useKernelStore.getState().mode).toBe('preloading');
    useKernelStore.getState().completePreloader();
    expect(useKernelStore.getState().mode).toBe('idle');
    expect(useKernelStore.getState().preloaderComplete).toBe(true);
  });

  it('quality tier cascades correctly', () => {
    const { setQualityTier } = useKernelStore.getState();
    setQualityTier('balanced');
    expect(useKernelStore.getState().qualityTier).toBe('balanced');
    setQualityTier('low');
    expect(useKernelStore.getState().qualityTier).toBe('low');
  });

  it('chapter navigation updates current chapter', () => {
    const { setCurrentChapter, setChapterProgress } = useKernelStore.getState();
    setCurrentChapter(5);
    setChapterProgress(0.75);
    expect(useKernelStore.getState().currentChapter).toBe(5);
    expect(useKernelStore.getState().chapterProgress).toBe(0.75);
  });
});
```

**Step 2: Run tests**

Run: `npx vitest run src/__tests__/kernel-integration.test.ts`
Expected: All 6 tests PASS.

**Step 3: Run full test suite**

Run: `npx vitest run`
Expected: All tests pass (existing + new).

**Step 4: Commit**

```bash
git add src/__tests__/kernel-integration.test.ts
git commit -m "test(kernel): integration tests — chapters, transitions, store, quality cascade"
```

---

### Task 31: Build Verification

**Step 1: Run full build**

Run: `npm run build`
Expected: Build succeeds with no errors.

**Step 2: Run lint**

Run: `npm run lint`
Expected: No new lint errors (or only pre-existing ones).

**Step 3: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: resolve build/lint issues from kernel integration"
```

---

## Phase 11: Acceptance Criteria Verification

After all phases are complete, verify each acceptance criterion:

1. **Chapter transitions**: Navigate between chapters — each has authored WebGL + DOM transition
2. **No default interactions**: Click links (animated underline), buttons (press depth), scroll (damped)
3. **Alive cursor**: Stop scrolling, move cursor — particles drift, distortion responds
4. **CTAs readable**: Check all PitButton/StampButton links at all quality tiers
5. **Reduced motion**: Enable `prefers-reduced-motion` — transitions instant, no WebGL effects
6. **WebGL fallback**: Block WebGL in devtools — site renders with CSS-only atmosphere
7. **Preloader**: Hard refresh — see black → LAP → progress → READY → unlock
8. **CornerDrag instrument**: Drag points in S1Pain — WebGL distortion/light reacts
9. **Performance**: Check FPS in Debug HUD (Ctrl+Shift+D) — 60fps desktop, 40+ mobile
10. **Auto degrade**: Throttle CPU in devtools — quality tier drops automatically
11. **Debug HUD**: Ctrl+Shift+D shows FPS, chapter, progress, velocity, quality
12. **V1 content preserved**: All text, routes, CTAs unchanged
13. **Keyboard nav**: Tab through CTAs — focus states visible, skip link works

---

## Summary: File Count

| Phase | New Files | Modified Files |
|-------|-----------|----------------|
| 1. Foundation | 7 | 3 |
| 2. Input | 3 | 0 |
| 3. Quality | 3 | 0 |
| 4. Renderer | 13 | 0 |
| 5. Transitions | 6 | 0 |
| 6. Motion/Preloader | 6 | 0 |
| 7. Shell | 2 | 1 |
| 8. Room Refactor | 0 | 3 |
| 9. Microinteractions | 0 | 1 |
| 10. Testing | 1 | 0 |
| **Total** | **41 new** | **8 modified** |
