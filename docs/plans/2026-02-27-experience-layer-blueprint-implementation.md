# Experience Layer Blueprint — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade lap-coach.racing's experience layer to museum-grade immersion with liquid cursor reveal, living background, kinetic HUD, and composited transitions — all building on the existing R3F infrastructure.

**Architecture:** Extend `useKernelStore` with new state slices (HUD, reveal, DRS, track path). Add `RevealMaskPipeline` as a new FBO system alongside existing `TransitionCompositor`. Replace `AtmosphereBase` with multi-layer `LivingSurface`. Add DOM-based HUD components (TimingTower, DeltaHud, MiniTrackMap, DrsLabel). All new systems read from the single orchestrator store.

**Tech Stack:** React 18, Next.js 14, TypeScript, React Three Fiber 8 + drei 9, Three.js 0.183, GSAP 3.14 + ScrollTrigger, Zustand 5, Lenis 1.3, Vitest 4, Tailwind CSS 3.4

**Design doc:** `docs/plans/2026-02-27-experience-layer-blueprint-design.md`

---

## Phase Overview

| Phase | Name | Tasks | Dependency |
|-------|------|-------|------------|
| 1 | Foundation — Tokens, Types, Store Extension | 1–5 | None |
| 2 | Narrative Infrastructure — Track Path + Sector Gates | 6–10 | Phase 1 |
| 3 | Reveal Mask Pipeline (Prototype 1) | 11–18 | Phase 1 |
| 4 | Living Surface (Prototype 2) | 19–24 | Phase 1 |
| 5 | HUD Chrome — Timing Tower, Delta, Track Map, DRS | 25–33 | Phase 2 |
| 6 | Section-Specific Choreography — Pit, Finish, Radio Cards, Track Cards | 34–41 | Phases 3-5 |
| 7 | Integration, Polish, Performance Validation | 42–46 | All |

Each phase produces a **working, committable increment**. Phases 3 and 4 can run in parallel after Phase 1.

---

## Phase 1: Foundation — Tokens, Types, Store Extension

### Task 1: Add racing-purple color token and narrative timing tokens

**Files:**
- Modify: `lap-website/src/styles/tokens.css:1-72`
- Modify: `lap-website/src/lib/tokens.ts:1-66`
- Modify: `lap-website/tailwind.config.ts:7-16`
- Test: `lap-website/src/__tests__/tokens.test.ts`

**Step 1: Write the failing tests**

Add to `lap-website/src/__tests__/tokens.test.ts`:

```typescript
it('exports racing-purple color', () => {
  expect(colors.racingPurple).toBe('#D946EF');
});

it('exports narrative timing tokens', () => {
  expect(timing.sectorGate).toBe(0.4);
  expect(timing.drs).toBe(2.0);
  expect(timing.pit).toBe(0.6);
  expect(timing.finish).toBe(0.6);
});
```

**Step 2: Run test to verify it fails**

Run: `cd lap-website && npx vitest run src/__tests__/tokens.test.ts`
Expected: FAIL — `colors.racingPurple` is undefined, `timing.sectorGate` is undefined

**Step 3: Add tokens to CSS, JS, and Tailwind**

In `lap-website/src/styles/tokens.css`, add after line 12 (`--pit-orange`):
```css
  --racing-purple: #D946EF;
```

Add after line 57 (`--duration-monument`):
```css
  --duration-sector-gate: 400ms;
  --duration-drs: 2000ms;
  --duration-pit: 600ms;
  --duration-finish: 600ms;

  /* ── Narrative Easing ─────────────── */
  --ease-sector-gate: cubic-bezier(0.0, 0, 0.2, 1);
  --ease-pit-enter: cubic-bezier(0.8, 0, 1, 1);
  --ease-pit-exit: cubic-bezier(0, 0, 0.2, 1);
```

Add after line 51 (`--z-timecode`):
```css
  --z-hud: 35;
  --z-drs: 36;
  --z-finish-line: 37;
```

Add data-accent rule after line 79:
```css
[data-accent="purple"]  { --accent: var(--racing-purple); }
```

In `lap-website/src/lib/tokens.ts`, add to `colors` object after `pitOrange`:
```typescript
  racingPurple: '#D946EF',
```

Add to `timing` object after `monument`:
```typescript
  sectorGate: 0.4,
  drs: 2.0,
  pit: 0.6,
  finish: 0.6,
```

Add to `easing` object after `anticipate`:
```typescript
  sectorGate: 'power4.out',
  pitEnter: 'power2.in',
  pitExit: 'power4.out',
```

In `lap-website/tailwind.config.ts`, add to `colors` object after `'pit-orange'`:
```typescript
        'racing-purple': '#D946EF',
```

Add to `zIndex` object after `timecode: 50`:
```typescript
        hud: 35,
        drs: 36,
        'finish-line': 37,
```

**Step 4: Run tests to verify they pass**

Run: `cd lap-website && npx vitest run src/__tests__/tokens.test.ts`
Expected: All PASS

**Step 5: Commit**

```bash
git add lap-website/src/styles/tokens.css lap-website/src/lib/tokens.ts lap-website/tailwind.config.ts lap-website/src/__tests__/tokens.test.ts
git commit -m "feat(tokens): add racing-purple, narrative timing, and z-index tokens"
```

---

### Task 2: Add track path data module

**Files:**
- Create: `lap-website/src/experience/narrative/TrackPath.ts`
- Test: `lap-website/src/__tests__/track-path.test.ts`

**Step 1: Write the failing test**

Create `lap-website/src/__tests__/track-path.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';
import {
  TRACK_PATH,
  getChapterPath,
  getHeadingDelta,
  isCornerChapter,
} from '@/experience/narrative/TrackPath';

describe('TrackPath', () => {
  it('defines path for all 11 chapters', () => {
    expect(TRACK_PATH).toHaveLength(11);
    expect(TRACK_PATH[0].chapter).toBe(0);
    expect(TRACK_PATH[10].chapter).toBe(10);
  });

  it('getChapterPath returns config for valid chapter', () => {
    const path = getChapterPath(0);
    expect(path.type).toBe('straight');
    expect(path.heading).toBe(0);
    expect(path.label).toBe('Start Grid');
  });

  it('getChapterPath clamps out-of-range chapters', () => {
    expect(getChapterPath(-1).chapter).toBe(0);
    expect(getChapterPath(99).chapter).toBe(10);
  });

  it('getHeadingDelta computes delta from previous chapter', () => {
    // Chapter 0 (heading 0) → Chapter 1 (heading 35) = delta 35
    expect(getHeadingDelta(1)).toBe(35);
    // Chapter 1 (heading 35) → Chapter 2 (heading 35) = delta 0
    expect(getHeadingDelta(2)).toBe(0);
    // Chapter 2 (heading 35) → Chapter 3 (heading -20) = delta -55
    expect(getHeadingDelta(3)).toBe(-55);
    // Chapter 0 has no previous — delta is 0
    expect(getHeadingDelta(0)).toBe(0);
  });

  it('isCornerChapter identifies corners correctly', () => {
    expect(isCornerChapter(0)).toBe(false);  // straight
    expect(isCornerChapter(1)).toBe(true);   // corner-r
    expect(isCornerChapter(2)).toBe(false);  // straight
    expect(isCornerChapter(3)).toBe(true);   // corner-l
    expect(isCornerChapter(8)).toBe(false);  // pit-lane (not a corner)
  });

  it('pit-lane chapter has heading 0', () => {
    const pit = getChapterPath(8);
    expect(pit.type).toBe('pit-lane');
    expect(pit.heading).toBe(0);
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd lap-website && npx vitest run src/__tests__/track-path.test.ts`
Expected: FAIL — module not found

**Step 3: Write implementation**

Create `lap-website/src/experience/narrative/TrackPath.ts`:

```typescript
// src/experience/narrative/TrackPath.ts
// Track path spline data — defines the "virtual track" the user drives through
// as they scroll the landing page. Corners modulate background behavior.

export type ChapterPathType = 'straight' | 'corner-r' | 'corner-l' | 'pit-lane';

export interface ChapterPathConfig {
  chapter: number;
  heading: number;       // degrees, cumulative track direction
  type: ChapterPathType;
  label: string;
}

export const TRACK_PATH: readonly ChapterPathConfig[] = [
  { chapter: 0,  heading: 0,    type: 'straight',  label: 'Start Grid' },
  { chapter: 1,  heading: 35,   type: 'corner-r',  label: 'S1 Pain' },
  { chapter: 2,  heading: 35,   type: 'straight',  label: 'S1 Deep' },
  { chapter: 3,  heading: -20,  type: 'corner-l',  label: 'S2 Pipeline' },
  { chapter: 4,  heading: -20,  type: 'straight',  label: 'S2 Proof' },
  { chapter: 5,  heading: 25,   type: 'corner-r',  label: 'S3 Product' },
  { chapter: 6,  heading: 25,   type: 'straight',  label: 'S4 Workflows' },
  { chapter: 7,  heading: 40,   type: 'corner-r',  label: 'S5 Personas' },
  { chapter: 8,  heading: 0,    type: 'pit-lane',  label: 'Pit Stop' },
  { chapter: 9,  heading: 0,    type: 'straight',  label: 'Garage' },
  { chapter: 10, heading: 0,    type: 'straight',  label: 'Podium' },
] as const;

export function getChapterPath(chapter: number): ChapterPathConfig {
  const clamped = Math.max(0, Math.min(TRACK_PATH.length - 1, chapter));
  return TRACK_PATH[clamped];
}

export function getHeadingDelta(chapter: number): number {
  if (chapter <= 0) return 0;
  const clamped = Math.max(0, Math.min(TRACK_PATH.length - 1, chapter));
  const prev = TRACK_PATH[clamped - 1];
  const curr = TRACK_PATH[clamped];
  return curr.heading - prev.heading;
}

export function isCornerChapter(chapter: number): boolean {
  const path = getChapterPath(chapter);
  return path.type === 'corner-r' || path.type === 'corner-l';
}
```

**Step 4: Run tests to verify they pass**

Run: `cd lap-website && npx vitest run src/__tests__/track-path.test.ts`
Expected: All PASS

**Step 5: Commit**

```bash
git add lap-website/src/experience/narrative/TrackPath.ts lap-website/src/__tests__/track-path.test.ts
git commit -m "feat(narrative): add track path spline data for turn-feel system"
```

---

### Task 3: Extend KernelStore types with HUD, reveal, DRS, and track path state

**Files:**
- Modify: `lap-website/src/experience/state/types.ts:1-83`
- Test: `lap-website/src/__tests__/kernel-store.test.ts`

**Step 1: Write the failing tests**

Add to `lap-website/src/__tests__/kernel-store.test.ts`:

```typescript
import { describe, it, expect, beforeEach } from 'vitest';
import { useKernelStore } from '@/experience/state/store';

// ... existing tests above ...

describe('Extended KernelStore — HUD state', () => {
  beforeEach(() => {
    useKernelStore.setState(useKernelStore.getInitialState());
  });

  it('initializes HUD tower with 8 sectors all pending', () => {
    const { hudTower } = useKernelStore.getState();
    expect(hudTower.sectors).toHaveLength(8);
    expect(hudTower.sectors[0].status).toBe('pending');
    expect(hudTower.activeSectorIndex).toBe(0);
  });

  it('completeSector marks sector completed with purple color', () => {
    const { completeSector } = useKernelStore.getState();
    completeSector(0);
    const { hudTower } = useKernelStore.getState();
    expect(hudTower.sectors[0].status).toBe('completed');
    expect(hudTower.sectors[0].color).toBe('#D946EF');
    expect(hudTower.activeSectorIndex).toBe(1);
  });

  it('setSectorProgress updates progress for active sector', () => {
    const { setSectorProgress } = useKernelStore.getState();
    setSectorProgress(0, 0.5);
    expect(useKernelStore.getState().hudTower.sectors[0].progress).toBe(0.5);
  });

  it('initializes delta HUD state', () => {
    const { hudDelta } = useKernelStore.getState();
    expect(hudDelta.value).toBe(0);
    expect(hudDelta.jitter).toBe(8);
    expect(hudDelta.settled).toBe(false);
  });

  it('setDeltaValue updates delta', () => {
    const { setDeltaValue } = useKernelStore.getState();
    setDeltaValue(-0.15);
    expect(useKernelStore.getState().hudDelta.value).toBe(-0.15);
  });

  it('setDeltaJitter clamps to 0-8', () => {
    const { setDeltaJitter } = useKernelStore.getState();
    setDeltaJitter(4);
    expect(useKernelStore.getState().hudDelta.jitter).toBe(4);
    setDeltaJitter(-1);
    expect(useKernelStore.getState().hudDelta.jitter).toBe(0);
    setDeltaJitter(20);
    expect(useKernelStore.getState().hudDelta.jitter).toBe(8);
  });

  it('settleDelta freezes delta', () => {
    const { setDeltaValue, settleDelta } = useKernelStore.getState();
    setDeltaValue(-0.05);
    settleDelta();
    const { hudDelta } = useKernelStore.getState();
    expect(hudDelta.settled).toBe(true);
    expect(hudDelta.jitter).toBe(0);
  });
});

describe('Extended KernelStore — reveal state', () => {
  beforeEach(() => {
    useKernelStore.setState(useKernelStore.getInitialState());
  });

  it('initializes reveal state', () => {
    const { reveal } = useKernelStore.getState();
    expect(reveal.maskCoverage).toBe(0);
    expect(reveal.brushRadius).toBe(80);
    expect(reveal.active).toBe(true);
  });

  it('setMaskCoverage clamps to 0-1', () => {
    const { setMaskCoverage } = useKernelStore.getState();
    setMaskCoverage(0.5);
    expect(useKernelStore.getState().reveal.maskCoverage).toBe(0.5);
    setMaskCoverage(2.0);
    expect(useKernelStore.getState().reveal.maskCoverage).toBe(1.0);
    setMaskCoverage(-1);
    expect(useKernelStore.getState().reveal.maskCoverage).toBe(0);
  });

  it('setRevealActive toggles reveal', () => {
    const { setRevealActive } = useKernelStore.getState();
    setRevealActive(false);
    expect(useKernelStore.getState().reveal.active).toBe(false);
  });
});

describe('Extended KernelStore — DRS state', () => {
  beforeEach(() => {
    useKernelStore.setState(useKernelStore.getInitialState());
  });

  it('initializes DRS as inactive', () => {
    const { drs } = useKernelStore.getState();
    expect(drs.active).toBe(false);
    expect(drs.multiplier).toBe(1.0);
  });

  it('activateDrs sets active state with trigger', () => {
    const { activateDrs } = useKernelStore.getState();
    activateDrs('sector-gate');
    const { drs } = useKernelStore.getState();
    expect(drs.active).toBe(true);
    expect(drs.remaining).toBe(2000);
    expect(drs.multiplier).toBe(1.4);
    expect(drs.trigger).toBe('sector-gate');
  });

  it('deactivateDrs resets to baseline', () => {
    const { activateDrs, deactivateDrs } = useKernelStore.getState();
    activateDrs('test');
    deactivateDrs();
    const { drs } = useKernelStore.getState();
    expect(drs.active).toBe(false);
    expect(drs.multiplier).toBe(1.0);
    expect(drs.remaining).toBe(0);
  });
});

describe('Extended KernelStore — track path state', () => {
  beforeEach(() => {
    useKernelStore.setState(useKernelStore.getInitialState());
  });

  it('initializes track path', () => {
    const { trackPath } = useKernelStore.getState();
    expect(trackPath.heading).toBe(0);
    expect(trackPath.headingDelta).toBe(0);
    expect(trackPath.isCorner).toBe(false);
    expect(trackPath.pitMode).toBe(false);
    expect(trackPath.velocityMultiplier).toBe(1.0);
  });

  it('setTrackPath updates all path fields', () => {
    const { setTrackPath } = useKernelStore.getState();
    setTrackPath({ heading: 35, headingDelta: 35, isCorner: true });
    const { trackPath } = useKernelStore.getState();
    expect(trackPath.heading).toBe(35);
    expect(trackPath.headingDelta).toBe(35);
    expect(trackPath.isCorner).toBe(true);
  });

  it('setPitMode toggles pit limiter', () => {
    const { setPitMode } = useKernelStore.getState();
    setPitMode(true);
    const { trackPath } = useKernelStore.getState();
    expect(trackPath.pitMode).toBe(true);
    expect(trackPath.velocityMultiplier).toBe(0.3);
  });

  it('setPitMode false restores velocity multiplier', () => {
    const { setPitMode } = useKernelStore.getState();
    setPitMode(true);
    setPitMode(false);
    expect(useKernelStore.getState().trackPath.velocityMultiplier).toBe(1.0);
  });
});

describe('Extended KernelStore — finish state', () => {
  beforeEach(() => {
    useKernelStore.setState(useKernelStore.getInitialState());
  });

  it('initializes finish state', () => {
    const { finish } = useKernelStore.getState();
    expect(finish.crossed).toBe(false);
    expect(finish.finalDelta).toBe(0);
  });

  it('crossFinishLine sets crossed and freezes delta', () => {
    const { setDeltaValue, crossFinishLine } = useKernelStore.getState();
    setDeltaValue(-0.23);
    crossFinishLine();
    const { finish, hudDelta } = useKernelStore.getState();
    expect(finish.crossed).toBe(true);
    expect(finish.finalDelta).toBe(-0.23);
    expect(hudDelta.settled).toBe(true);
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd lap-website && npx vitest run src/__tests__/kernel-store.test.ts`
Expected: FAIL — `hudTower`, `reveal`, `drs`, `trackPath`, `finish` are undefined on store

**Step 3: Extend types**

Modify `lap-website/src/experience/state/types.ts` — add after line 10 (after `'transitioning'`):

```typescript
  | 'pit';
```

And add new interfaces after the `KernelActions` interface (after line 81):

```typescript
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
```

Remove the old `KernelStore` type alias on line 83.

**Step 4: Extend store implementation**

Modify `lap-website/src/experience/state/store.ts`. The new initial state and actions extend the existing store. Add after line 23 (`preloaderComplete: false,`):

```typescript
  // ── Narrative state ─────────────────────
  hudTower: {
    sectors: [
      { id: 'S1', status: 'pending' as const, progress: 0, color: '#F3F0E8' },
      { id: 'S2', status: 'pending' as const, progress: 0, color: '#F3F0E8' },
      { id: 'S3', status: 'pending' as const, progress: 0, color: '#F3F0E8' },
      { id: 'S4', status: 'pending' as const, progress: 0, color: '#F3F0E8' },
      { id: 'S5', status: 'pending' as const, progress: 0, color: '#F3F0E8' },
      { id: 'PIT', status: 'pending' as const, progress: 0, color: '#F3F0E8' },
      { id: 'GAR', status: 'pending' as const, progress: 0, color: '#F3F0E8' },
      { id: 'POD', status: 'pending' as const, progress: 0, color: '#F3F0E8' },
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
```

Add new actions after line 55 (`completePreloader` action, before the closing `}));`):

```typescript
  // ── Narrative actions ───────────────────
  completeSector: (index) =>
    set((state) => {
      const sectors = [...state.hudTower.sectors];
      if (index >= 0 && index < sectors.length) {
        sectors[index] = { ...sectors[index], status: 'completed', color: '#D946EF', progress: 1 };
      }
      const nextActive = Math.min(index + 1, sectors.length - 1);
      if (nextActive < sectors.length && sectors[nextActive].status === 'pending') {
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
```

**Step 5: Run tests**

Run: `cd lap-website && npx vitest run src/__tests__/kernel-store.test.ts`
Expected: All PASS (original + new tests)

**Step 6: Commit**

```bash
git add lap-website/src/experience/state/types.ts lap-website/src/experience/state/store.ts lap-website/src/__tests__/kernel-store.test.ts
git commit -m "feat(store): extend kernel store with HUD, reveal, DRS, track path, and finish state"
```

---

### Task 4: Add sector gate mapping to tokens

**Files:**
- Modify: `lap-website/src/lib/tokens.ts:42-66`
- Test: `lap-website/src/__tests__/tokens.test.ts`

**Step 1: Write the failing test**

Add to `lap-website/src/__tests__/tokens.test.ts`:

```typescript
import { sectorGates } from '@/lib/tokens';

it('defines sector gates mapping chapters to sector IDs', () => {
  expect(sectorGates[1]).toBe('S1');
  expect(sectorGates[3]).toBe('S2');
  expect(sectorGates[5]).toBe('S3');
  expect(sectorGates[8]).toBe('PIT');
  expect(sectorGates[10]).toBe('FINISH');
});

it('sector gate chapters are valid room indices', () => {
  Object.keys(sectorGates).forEach((key) => {
    const idx = Number(key);
    expect(idx).toBeGreaterThanOrEqual(0);
    expect(idx).toBeLessThanOrEqual(10);
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd lap-website && npx vitest run src/__tests__/tokens.test.ts`
Expected: FAIL — `sectorGates` not exported

**Step 3: Write implementation**

Add to `lap-website/src/lib/tokens.ts` after `sectorTabs`:

```typescript
// Sector gate triggers: chapter index → sector ID completed
export const sectorGates: Record<number, string> = {
  1: 'S1',     // Start Grid → S1 Pain
  3: 'S2',     // S1 Deep → S2 Pipeline
  5: 'S3',     // S2 Proof → S3 Product
  8: 'PIT',    // S5 Personas → Pit Stop
  10: 'FINISH', // Garage → Podium
} as const;
```

**Step 4: Run tests**

Run: `cd lap-website && npx vitest run src/__tests__/tokens.test.ts`
Expected: All PASS

**Step 5: Commit**

```bash
git add lap-website/src/lib/tokens.ts lap-website/src/__tests__/tokens.test.ts
git commit -m "feat(tokens): add sector gate mapping for narrative system"
```

---

### Task 5: Add spring/physics constants for new systems

**Files:**
- Modify: `lap-website/src/experience/motion/springs.ts:1-13`
- Test: `lap-website/src/__tests__/springs.test.ts`

**Step 1: Write the failing test**

Create `lap-website/src/__tests__/springs.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';
import { physics, reveal, background } from '@/experience/motion/springs';

describe('Physics constants', () => {
  it('has existing scroll physics', () => {
    expect(physics.scrollLerp).toBe(0.08);
    expect(physics.magnetismRadius).toBe(120);
  });
});

describe('Reveal constants', () => {
  it('defines brush and decay parameters', () => {
    expect(reveal.brushRadius).toBe(80);
    expect(reveal.brushSoftness).toBe(0.6);
    expect(reveal.decayFactor).toBe(0.985);
    expect(reveal.inertiaLerp).toBe(0.08);
    expect(reveal.drsRadiusMultiplier).toBe(1.4);
    expect(reveal.idleDecayRate).toBe(0.97);
    expect(reveal.mobileBurstRadius).toBe(120);
  });
});

describe('Background constants', () => {
  it('defines turn-feel parameters', () => {
    expect(background.yawDamping).toBe(0.04);
    expect(background.particleDriftX).toBe(2.0);
    expect(background.particleDriftY).toBe(2.0);
    expect(background.streakSpawnThreshold).toBe(0.4);
    expect(background.streakLifetime).toBe(300);
    expect(background.wheelFriction).toBe(0.95);
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd lap-website && npx vitest run src/__tests__/springs.test.ts`
Expected: FAIL — `reveal` and `background` not exported

**Step 3: Write implementation**

Modify `lap-website/src/experience/motion/springs.ts`:

```typescript
export const physics = {
  scrollLerp: 0.08,
  scrollDuration: 1.2,
  scrollSnapForce: 0.4,
  magnetismRadius: 120,
  magnetismStrength: 0.15,
  magnetismDecay: 2.0,
  dragFriction: 0.92,
  dragOvershoot: 0.04,
  velocitySmoothing: 0.12,
  velocityMax: 1.0,
  snapVelocityThreshold: 0.05,
} as const;

export const reveal = {
  brushRadius: 80,
  brushSoftness: 0.6,
  decayFactor: 0.985,
  blurKernelSize: 5,
  blurSigma: 2.0,
  inertiaLerp: 0.08,
  turbulenceStrength: 0.3,
  turbulenceScale: 4.0,
  drsRadiusMultiplier: 1.4,
  idleDecayRate: 0.97,
  idleTimeout: 2000,
  mobileBurstRadius: 120,
  mobileBurstDecay: 0.96,
} as const;

export const background = {
  grainIntensity: 0.04,
  contourCount: 30,
  contourDriftSpeed: 0.001,
  contourPointerInfluence: 0.03,
  particleDriftX: 2.0,
  particleDriftY: 2.0,
  particlePointerRadius: 100,
  streakCount: 15,
  streakSpawnThreshold: 0.4,
  streakLifetime: 300,
  streakLength: 40,
  vignetteRadius: 0.7,
  vignetteShift: 0.05,
  yawDamping: 0.04,
  cornerParallaxFactor: 0.02,
  wheelFriction: 0.95,
} as const;
```

**Step 4: Run tests**

Run: `cd lap-website && npx vitest run src/__tests__/springs.test.ts`
Expected: All PASS

**Step 5: Commit**

```bash
git add lap-website/src/experience/motion/springs.ts lap-website/src/__tests__/springs.test.ts
git commit -m "feat(springs): add reveal and background physics constants"
```

---

## Phase 2: Narrative Infrastructure — Sector Gates + Controllers

### Task 6: Create SectorGateController

**Files:**
- Create: `lap-website/src/experience/narrative/SectorGateController.tsx`
- Test: `lap-website/src/__tests__/sector-gate.test.ts`

**Step 1: Write the failing test**

Create `lap-website/src/__tests__/sector-gate.test.ts`:

```typescript
import { describe, it, expect, beforeEach } from 'vitest';
import { useKernelStore } from '@/experience/state/store';
import { getSectorIndexForGate, shouldTriggerGate } from '@/experience/narrative/SectorGateController';

describe('Sector gate logic', () => {
  beforeEach(() => {
    useKernelStore.setState(useKernelStore.getInitialState());
  });

  it('getSectorIndexForGate maps chapter to sector tower index', () => {
    // S1 = index 0 in tower, S2 = 1, S3 = 2, PIT = 5
    expect(getSectorIndexForGate(1)).toBe(0);   // chapter 1 → S1 completed → tower idx 0
    expect(getSectorIndexForGate(3)).toBe(1);   // chapter 3 → S2 completed → tower idx 1
    expect(getSectorIndexForGate(5)).toBe(2);   // chapter 5 → S3 completed → tower idx 2
    expect(getSectorIndexForGate(8)).toBe(5);   // chapter 8 → PIT completed → tower idx 5
    expect(getSectorIndexForGate(10)).toBeNull();  // FINISH is special
    expect(getSectorIndexForGate(2)).toBeNull();   // no gate at chapter 2
  });

  it('shouldTriggerGate returns true only on first entry', () => {
    // Chapter 1 is a gate, never triggered before
    expect(shouldTriggerGate(1, new Set())).toBe(true);
    // Already triggered
    expect(shouldTriggerGate(1, new Set([1]))).toBe(false);
    // Chapter 2 is not a gate
    expect(shouldTriggerGate(2, new Set())).toBe(false);
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd lap-website && npx vitest run src/__tests__/sector-gate.test.ts`
Expected: FAIL — module not found

**Step 3: Write implementation**

Create `lap-website/src/experience/narrative/SectorGateController.tsx`:

```typescript
'use client';

import { useEffect, useRef } from 'react';
import { useKernelStore } from '@/experience/state/store';
import { sectorGates } from '@/lib/tokens';
import { getChapterPath, getHeadingDelta, isCornerChapter } from './TrackPath';

// Map sector gate chapter → tower sector index
const GATE_TO_TOWER_INDEX: Record<number, number> = {
  1: 0,   // S1
  3: 1,   // S2
  5: 2,   // S3
  8: 5,   // PIT (skipping S4=3, S5=4 which don't have gates)
};

export function getSectorIndexForGate(chapter: number): number | null {
  if (chapter === 10) return null; // FINISH is handled separately
  return GATE_TO_TOWER_INDEX[chapter] ?? null;
}

export function shouldTriggerGate(chapter: number, triggered: Set<number>): boolean {
  if (!sectorGates[chapter]) return false;
  return !triggered.has(chapter);
}

export function SectorGateController() {
  const currentChapter = useKernelStore((s) => s.currentChapter);
  const completeSector = useKernelStore((s) => s.completeSector);
  const activateDrs = useKernelStore((s) => s.activateDrs);
  const setTrackPath = useKernelStore((s) => s.setTrackPath);
  const setPitMode = useKernelStore((s) => s.setPitMode);
  const crossFinishLine = useKernelStore((s) => s.crossFinishLine);
  const triggeredRef = useRef<Set<number>>(new Set());
  const prevChapterRef = useRef(currentChapter);

  // Update track path on every chapter change
  useEffect(() => {
    const path = getChapterPath(currentChapter);
    const headingDelta = getHeadingDelta(currentChapter);
    const isCorner = isCornerChapter(currentChapter);

    setTrackPath({ heading: path.heading, headingDelta, isCorner });

    // Pit mode
    if (path.type === 'pit-lane') {
      setPitMode(true);
    } else if (prevChapterRef.current === 8 && currentChapter !== 8) {
      setPitMode(false);
    }

    // Sector gate check
    if (shouldTriggerGate(currentChapter, triggeredRef.current)) {
      triggeredRef.current.add(currentChapter);

      const towerIndex = getSectorIndexForGate(currentChapter);
      if (towerIndex !== null) {
        completeSector(towerIndex);
        activateDrs('sector-gate');
      }
    }

    // Finish line
    if (currentChapter === 10 && !triggeredRef.current.has(10)) {
      triggeredRef.current.add(10);
      // Complete all remaining sectors
      const state = useKernelStore.getState();
      state.hudTower.sectors.forEach((s, i) => {
        if (s.status !== 'completed') completeSector(i);
      });
      crossFinishLine();
    }

    prevChapterRef.current = currentChapter;
  }, [currentChapter, completeSector, activateDrs, setTrackPath, setPitMode, crossFinishLine]);

  return null;
}
```

**Step 4: Run tests**

Run: `cd lap-website && npx vitest run src/__tests__/sector-gate.test.ts`
Expected: All PASS

**Step 5: Commit**

```bash
git add lap-website/src/experience/narrative/SectorGateController.tsx lap-website/src/__tests__/sector-gate.test.ts
git commit -m "feat(narrative): add SectorGateController with gate detection and track path updates"
```

---

### Task 7: Create DrsController

**Files:**
- Create: `lap-website/src/experience/narrative/DrsController.tsx`
- Test: `lap-website/src/__tests__/drs-controller.test.ts`

**Step 1: Write the failing test**

Create `lap-website/src/__tests__/drs-controller.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { useKernelStore } from '@/experience/state/store';
import { tickDrs } from '@/experience/narrative/DrsController';

describe('DRS tick logic', () => {
  beforeEach(() => {
    useKernelStore.setState(useKernelStore.getInitialState());
  });

  it('tickDrs does nothing when DRS inactive', () => {
    tickDrs(16); // 16ms frame
    expect(useKernelStore.getState().drs.active).toBe(false);
  });

  it('tickDrs decrements remaining time', () => {
    useKernelStore.getState().activateDrs('test');
    tickDrs(100);
    expect(useKernelStore.getState().drs.remaining).toBe(1900);
    expect(useKernelStore.getState().drs.active).toBe(true);
  });

  it('tickDrs deactivates when remaining reaches 0', () => {
    useKernelStore.getState().activateDrs('test');
    tickDrs(2000);
    expect(useKernelStore.getState().drs.active).toBe(false);
    expect(useKernelStore.getState().drs.multiplier).toBe(1.0);
  });

  it('tickDrs decays multiplier in final 500ms', () => {
    useKernelStore.getState().activateDrs('test');
    // Skip to 400ms remaining (1600ms elapsed)
    tickDrs(1600);
    const drs = useKernelStore.getState().drs;
    expect(drs.remaining).toBe(400);
    // Multiplier should be decaying: < 1.4 but > 1.0
    expect(drs.multiplier).toBeLessThan(1.4);
    expect(drs.multiplier).toBeGreaterThan(1.0);
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd lap-website && npx vitest run src/__tests__/drs-controller.test.ts`
Expected: FAIL — module not found

**Step 3: Write implementation**

Create `lap-website/src/experience/narrative/DrsController.tsx`:

```typescript
'use client';

import { useEffect, useRef } from 'react';
import { useKernelStore } from '@/experience/state/store';

const DRS_DURATION = 2000;
const DRS_DECAY_WINDOW = 500;
const DRS_MAX_MULTIPLIER = 1.4;

/** Pure tick function — exported for testing */
export function tickDrs(dtMs: number) {
  const { drs } = useKernelStore.getState();
  if (!drs.active) return;

  const newRemaining = Math.max(0, drs.remaining - dtMs);

  if (newRemaining <= 0) {
    useKernelStore.getState().deactivateDrs();
    return;
  }

  // Decay multiplier in final 500ms
  let multiplier = DRS_MAX_MULTIPLIER;
  if (newRemaining < DRS_DECAY_WINDOW) {
    const t = newRemaining / DRS_DECAY_WINDOW; // 1→0
    multiplier = 1.0 + (DRS_MAX_MULTIPLIER - 1.0) * t;
  }

  useKernelStore.setState({
    drs: { ...drs, remaining: newRemaining, multiplier },
  });
}

export function DrsController() {
  const drsActive = useKernelStore((s) => s.drs.active);
  const rafRef = useRef<number>(0);
  const lastTimeRef = useRef(0);

  useEffect(() => {
    if (!drsActive) {
      lastTimeRef.current = 0;
      return;
    }

    function tick(time: number) {
      if (lastTimeRef.current === 0) {
        lastTimeRef.current = time;
      }
      const dt = time - lastTimeRef.current;
      lastTimeRef.current = time;

      tickDrs(dt);

      if (useKernelStore.getState().drs.active) {
        rafRef.current = requestAnimationFrame(tick);
      }
    }

    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [drsActive]);

  return null;
}
```

**Step 4: Run tests**

Run: `cd lap-website && npx vitest run src/__tests__/drs-controller.test.ts`
Expected: All PASS

**Step 5: Commit**

```bash
git add lap-website/src/experience/narrative/DrsController.tsx lap-website/src/__tests__/drs-controller.test.ts
git commit -m "feat(narrative): add DrsController with timer tick and multiplier decay"
```

---

### Task 8: Wire narrative controllers into ExperienceKernel

**Files:**
- Modify: `lap-website/src/experience/ExperienceKernel.tsx:1-28`

**Step 1: Add imports and mount controllers**

In `lap-website/src/experience/ExperienceKernel.tsx`, add imports:

```typescript
import { SectorGateController } from './narrative/SectorGateController';
import { DrsController } from './narrative/DrsController';
```

Add inside the `ExperienceKernel` return, after `<MotionOrchestrator />`:

```typescript
      <SectorGateController />
      <DrsController />
```

**Step 2: Run existing tests to verify no regression**

Run: `cd lap-website && npx vitest run`
Expected: All existing tests PASS

**Step 3: Commit**

```bash
git add lap-website/src/experience/ExperienceKernel.tsx
git commit -m "feat(kernel): wire SectorGateController and DrsController into experience kernel"
```

---

### Task 9: Create delta jitter tick logic

**Files:**
- Create: `lap-website/src/experience/narrative/DeltaTickController.tsx`
- Test: `lap-website/src/__tests__/delta-tick.test.ts`

**Step 1: Write the failing test**

Create `lap-website/src/__tests__/delta-tick.test.ts`:

```typescript
import { describe, it, expect, beforeEach } from 'vitest';
import { useKernelStore } from '@/experience/state/store';
import { computeDeltaJitter, computeDeltaValue } from '@/experience/narrative/DeltaTickController';

describe('Delta tick logic', () => {
  beforeEach(() => {
    useKernelStore.setState(useKernelStore.getInitialState());
  });

  it('computeDeltaJitter maps mask coverage to jitter', () => {
    expect(computeDeltaJitter(0)).toBe(8);     // no coverage = max jitter
    expect(computeDeltaJitter(0.5)).toBe(4);   // half coverage = half jitter
    expect(computeDeltaJitter(1.0)).toBe(0);   // full coverage = no jitter
  });

  it('computeDeltaValue trends toward 0 with progress', () => {
    const base = 0.5;
    expect(computeDeltaValue(base, 0)).toBeCloseTo(0.5);
    expect(computeDeltaValue(base, 0.5)).toBeCloseTo(0.25);
    expect(computeDeltaValue(base, 1.0)).toBeCloseTo(0);
  });

  it('computeDeltaValue respects settled state', () => {
    // When settled, return current value unchanged
    useKernelStore.getState().settleDelta();
    const { hudDelta } = useKernelStore.getState();
    expect(hudDelta.settled).toBe(true);
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd lap-website && npx vitest run src/__tests__/delta-tick.test.ts`
Expected: FAIL — module not found

**Step 3: Write implementation**

Create `lap-website/src/experience/narrative/DeltaTickController.tsx`:

```typescript
'use client';

import { useEffect, useRef } from 'react';
import { useKernelStore } from '@/experience/state/store';

const MAX_JITTER = 8;
const BASE_DELTA = 0.5; // starting "time loss" in seconds

/** Pure function: map mask coverage (0-1) → jitter amplitude (8-0) */
export function computeDeltaJitter(maskCoverage: number): number {
  return MAX_JITTER * (1 - Math.max(0, Math.min(1, maskCoverage)));
}

/** Pure function: delta trends from base toward 0 as globalProgress increases */
export function computeDeltaValue(base: number, globalProgress: number): number {
  return base * (1 - Math.max(0, Math.min(1, globalProgress)));
}

export function DeltaTickController() {
  const maskCoverage = useKernelStore((s) => s.reveal.maskCoverage);
  const globalProgress = useKernelStore((s) => s.globalProgress);
  const settled = useKernelStore((s) => s.hudDelta.settled);
  const setDeltaJitter = useKernelStore((s) => s.setDeltaJitter);
  const setDeltaValue = useKernelStore((s) => s.setDeltaValue);
  const rafRef = useRef<number>(0);

  useEffect(() => {
    if (settled) return;

    function tick() {
      const jitter = computeDeltaJitter(maskCoverage);
      setDeltaJitter(jitter);

      const value = computeDeltaValue(BASE_DELTA, globalProgress);
      setDeltaValue(value);

      rafRef.current = requestAnimationFrame(tick);
    }

    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [maskCoverage, globalProgress, settled, setDeltaJitter, setDeltaValue]);

  return null;
}
```

**Step 4: Run tests**

Run: `cd lap-website && npx vitest run src/__tests__/delta-tick.test.ts`
Expected: All PASS

**Step 5: Commit**

```bash
git add lap-website/src/experience/narrative/DeltaTickController.tsx lap-website/src/__tests__/delta-tick.test.ts
git commit -m "feat(narrative): add DeltaTickController with jitter-from-coverage and value-from-progress"
```

---

### Task 10: Wire DeltaTickController into kernel and run full test suite

**Files:**
- Modify: `lap-website/src/experience/ExperienceKernel.tsx`

**Step 1: Add import and mount**

```typescript
import { DeltaTickController } from './narrative/DeltaTickController';
```

Add after `<DrsController />`:
```typescript
      <DeltaTickController />
```

**Step 2: Run full test suite**

Run: `cd lap-website && npx vitest run`
Expected: All PASS

**Step 3: Commit**

```bash
git add lap-website/src/experience/ExperienceKernel.tsx
git commit -m "feat(kernel): wire DeltaTickController into experience kernel"
```

---

## Phase 3: Reveal Mask Pipeline (Prototype 1)

### Task 11: Create reveal mask GLSL shaders

**Files:**
- Create: `lap-website/src/experience/reveal/shaders/mask-stamp.ts`
- Create: `lap-website/src/experience/reveal/shaders/mask-decay.ts`
- Create: `lap-website/src/experience/reveal/shaders/mask-blur.ts`
- Create: `lap-website/src/experience/reveal/shaders/reveal-blend.ts`

**Step 1: Create mask-stamp shader**

Create `lap-website/src/experience/reveal/shaders/mask-stamp.ts`:

```typescript
/** Stamps a soft brush at pointer position onto the mask texture */
export const maskStampVertex = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

export const maskStampFragment = /* glsl */ `
uniform sampler2D tPrevMask;
uniform vec2 uPointer;       // normalized screen coords (0-1)
uniform float uRadius;       // brush radius in UV space
uniform float uSoftness;     // Gaussian sigma multiplier (0-1)
uniform float uStrength;     // stamp opacity (0-1)
varying vec2 vUv;

void main() {
  vec4 prev = texture2D(tPrevMask, vUv);

  // Distance from pointer in UV space
  float dist = distance(vUv, uPointer);
  float normalizedDist = dist / max(uRadius, 0.001);

  // Gaussian falloff for soft edge
  float sigma = mix(0.2, 0.8, uSoftness);
  float brush = exp(-0.5 * (normalizedDist * normalizedDist) / (sigma * sigma));
  brush *= uStrength;

  // Additive stamp (max to prevent darkening)
  float mask = max(prev.r, brush);
  gl_FragColor = vec4(mask, mask, mask, 1.0);
}
`;
```

**Step 2: Create mask-decay shader**

Create `lap-website/src/experience/reveal/shaders/mask-decay.ts`:

```typescript
/** Decays mask persistence by multiplying by a factor < 1.0 each frame */
export const maskDecayVertex = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

export const maskDecayFragment = /* glsl */ `
uniform sampler2D tMask;
uniform float uDecay;   // 0.985 = ~3s to 10%
varying vec2 vUv;

void main() {
  float mask = texture2D(tMask, vUv).r;
  mask *= uDecay;
  gl_FragColor = vec4(mask, mask, mask, 1.0);
}
`;
```

**Step 3: Create mask-blur shader**

Create `lap-website/src/experience/reveal/shaders/mask-blur.ts`:

```typescript
/** Separable 5-tap Gaussian blur for mask softening */
export const maskBlurVertex = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

export const maskBlurFragment = /* glsl */ `
uniform sampler2D tMask;
uniform vec2 uDirection;    // (1/width, 0) or (0, 1/height) for separable
uniform float uSigma;
varying vec2 vUv;

void main() {
  // 5-tap kernel weights for Gaussian
  float weights[5];
  weights[0] = 0.227027;
  weights[1] = 0.194596;
  weights[2] = 0.121621;
  weights[3] = 0.054054;
  weights[4] = 0.016216;

  float result = texture2D(tMask, vUv).r * weights[0];

  for (int i = 1; i < 5; i++) {
    vec2 offset = uDirection * float(i) * uSigma;
    result += texture2D(tMask, vUv + offset).r * weights[i];
    result += texture2D(tMask, vUv - offset).r * weights[i];
  }

  gl_FragColor = vec4(result, result, result, 1.0);
}
`;
```

**Step 4: Create reveal-blend shader**

Create `lap-website/src/experience/reveal/shaders/reveal-blend.ts`:

```typescript
/** Blends Layer A and Layer B using the mask texture */
export const revealBlendVertex = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

export const revealBlendFragment = /* glsl */ `
uniform sampler2D tLayerA;   // clean surface (default visible)
uniform sampler2D tLayerB;   // truth layer (revealed by mask)
uniform sampler2D tMask;     // reveal mask (r channel = blend factor)
varying vec2 vUv;

void main() {
  vec4 colorA = texture2D(tLayerA, vUv);
  vec4 colorB = texture2D(tLayerB, vUv);
  float mask = texture2D(tMask, vUv).r;

  gl_FragColor = mix(colorA, colorB, mask);
}
`;
```

**Step 5: Commit**

```bash
git add lap-website/src/experience/reveal/shaders/
git commit -m "feat(reveal): add GLSL shaders for mask stamp, decay, blur, and blend"
```

---

### Task 12: Create useRevealState hook

**Files:**
- Create: `lap-website/src/experience/reveal/useRevealState.ts`
- Test: `lap-website/src/__tests__/reveal-state.test.ts`

**Step 1: Write the failing test**

Create `lap-website/src/__tests__/reveal-state.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';
import { lerpPointer, computeMaskResolution } from '@/experience/reveal/useRevealState';

describe('Reveal state utilities', () => {
  it('lerpPointer applies inertia to pointer position', () => {
    const result = lerpPointer(
      { x: 0, y: 0 },    // current smoothed
      { x: 1, y: 1 },    // target (raw pointer)
      0.1,                // lerp factor
    );
    expect(result.x).toBeCloseTo(0.1);
    expect(result.y).toBeCloseTo(0.1);
  });

  it('lerpPointer converges to target over many steps', () => {
    let smoothed = { x: 0, y: 0 };
    const target = { x: 0.5, y: 0.5 };
    for (let i = 0; i < 100; i++) {
      smoothed = lerpPointer(smoothed, target, 0.1);
    }
    expect(smoothed.x).toBeCloseTo(0.5, 2);
    expect(smoothed.y).toBeCloseTo(0.5, 2);
  });

  it('computeMaskResolution returns correct resolution per quality tier', () => {
    expect(computeMaskResolution('high')).toBe(1024);
    expect(computeMaskResolution('balanced')).toBe(512);
    expect(computeMaskResolution('low')).toBe(0);
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd lap-website && npx vitest run src/__tests__/reveal-state.test.ts`
Expected: FAIL — module not found

**Step 3: Write implementation**

Create `lap-website/src/experience/reveal/useRevealState.ts`:

```typescript
import { useRef, useCallback } from 'react';
import { useKernelStore } from '@/experience/state/store';
import { reveal as revealPhysics } from '@/experience/motion/springs';
import type { QualityTier } from '@/experience/state/types';

interface Vec2 {
  x: number;
  y: number;
}

/** Linear interpolation for pointer with inertia */
export function lerpPointer(current: Vec2, target: Vec2, factor: number): Vec2 {
  return {
    x: current.x + (target.x - current.x) * factor,
    y: current.y + (target.y - current.y) * factor,
  };
}

/** Mask FBO resolution per quality tier */
export function computeMaskResolution(tier: QualityTier): number {
  switch (tier) {
    case 'high': return 1024;
    case 'balanced': return 512;
    case 'low': return 0; // no FBO, fallback to simple radial
  }
}

/** Hook providing smoothed pointer and brush parameters for the reveal pipeline */
export function useRevealState() {
  const smoothedRef = useRef<Vec2>({ x: 0.5, y: 0.5 });
  const lastMoveRef = useRef(Date.now());

  const getSmoothedPointer = useCallback((rawX: number, rawY: number): Vec2 => {
    lastMoveRef.current = Date.now();
    smoothedRef.current = lerpPointer(
      smoothedRef.current,
      { x: rawX, y: rawY },
      revealPhysics.inertiaLerp,
    );
    return smoothedRef.current;
  }, []);

  const isIdle = useCallback((): boolean => {
    return Date.now() - lastMoveRef.current > revealPhysics.idleTimeout;
  }, []);

  const getDecayFactor = useCallback((): number => {
    return isIdle() ? revealPhysics.idleDecayRate : revealPhysics.decayFactor;
  }, [isIdle]);

  const getBrushRadius = useCallback((): number => {
    const drsMultiplier = useKernelStore.getState().drs.multiplier;
    return revealPhysics.brushRadius * drsMultiplier;
  }, []);

  return {
    getSmoothedPointer,
    isIdle,
    getDecayFactor,
    getBrushRadius,
    smoothedRef,
  };
}
```

**Step 4: Run tests**

Run: `cd lap-website && npx vitest run src/__tests__/reveal-state.test.ts`
Expected: All PASS

**Step 5: Commit**

```bash
git add lap-website/src/experience/reveal/useRevealState.ts lap-website/src/__tests__/reveal-state.test.ts
git commit -m "feat(reveal): add useRevealState hook with pointer inertia and quality-adaptive resolution"
```

---

### Task 13: Create RevealMaskPipeline R3F component

**Files:**
- Create: `lap-website/src/experience/reveal/RevealMaskPipeline.tsx`

This is the core FBO ping-pong system. It runs inside the R3F `<Canvas>`.

**Step 1: Write implementation**

Create `lap-website/src/experience/reveal/RevealMaskPipeline.tsx`:

```typescript
'use client';

import { useRef, useMemo } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import { useFBO } from '@react-three/drei';
import * as THREE from 'three';
import { useKernelStore } from '@/experience/state/store';
import { useRevealState, computeMaskResolution } from './useRevealState';
import { reveal as revealPhysics } from '@/experience/motion/springs';
import { maskStampVertex, maskStampFragment } from './shaders/mask-stamp';
import { maskDecayVertex, maskDecayFragment } from './shaders/mask-decay';
import { maskBlurVertex, maskBlurFragment } from './shaders/mask-blur';
import { revealBlendVertex, revealBlendFragment } from './shaders/reveal-blend';

/**
 * RevealMaskPipeline — FBO ping-pong system for persistent cursor reveal.
 *
 * Per-frame pipeline:
 * 1. STAMP: Soft brush at smoothed pointer → maskFBO_A
 * 2. DECAY: maskFBO_A * decayFactor → maskFBO_B
 * 3. BLUR:  separable Gaussian on maskFBO_B → maskFBO_A (high tier only)
 * 4. BLEND: mix(LayerA, LayerB, maskFBO_A) → screen
 */
export function RevealMaskPipeline() {
  const { gl, size } = useThree();
  const qualityTier = useKernelStore((s) => s.qualityTier);
  const pointerX = useKernelStore((s) => s.pointerX);
  const pointerY = useKernelStore((s) => s.pointerY);
  const revealActive = useKernelStore((s) => s.reveal.active);
  const reducedMotion = useKernelStore((s) => s.reducedMotion);
  const setMaskCoverage = useKernelStore((s) => s.setMaskCoverage);
  const { getSmoothedPointer, getDecayFactor, getBrushRadius } = useRevealState();

  const resolution = computeMaskResolution(qualityTier);

  // FBO ping-pong buffers for mask persistence
  const maskFboA = useFBO(resolution || 64, resolution || 64, {
    minFilter: THREE.LinearFilter,
    magFilter: THREE.LinearFilter,
    type: THREE.HalfFloatType,
  });
  const maskFboB = useFBO(resolution || 64, resolution || 64, {
    minFilter: THREE.LinearFilter,
    magFilter: THREE.LinearFilter,
    type: THREE.HalfFloatType,
  });

  // Full-screen quad scene for shader passes
  const quadScene = useMemo(() => new THREE.Scene(), []);
  const quadCamera = useMemo(
    () => new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1),
    [],
  );
  const quadGeo = useMemo(() => new THREE.PlaneGeometry(2, 2), []);

  // Shader materials
  const stampMat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: maskStampVertex,
        fragmentShader: maskStampFragment,
        uniforms: {
          tPrevMask: { value: null },
          uPointer: { value: new THREE.Vector2(0.5, 0.5) },
          uRadius: { value: 0.1 },
          uSoftness: { value: revealPhysics.brushSoftness },
          uStrength: { value: 1.0 },
        },
      }),
    [],
  );

  const decayMat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: maskDecayVertex,
        fragmentShader: maskDecayFragment,
        uniforms: {
          tMask: { value: null },
          uDecay: { value: revealPhysics.decayFactor },
        },
      }),
    [],
  );

  const blurMatH = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: maskBlurVertex,
        fragmentShader: maskBlurFragment,
        uniforms: {
          tMask: { value: null },
          uDirection: { value: new THREE.Vector2(1.0 / (resolution || 512), 0) },
          uSigma: { value: revealPhysics.blurSigma },
        },
      }),
    [resolution],
  );

  const blurMatV = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: maskBlurVertex,
        fragmentShader: maskBlurFragment,
        uniforms: {
          tMask: { value: null },
          uDirection: { value: new THREE.Vector2(0, 1.0 / (resolution || 512)) },
          uSigma: { value: revealPhysics.blurSigma },
        },
      }),
    [resolution],
  );

  const quadMeshRef = useRef<THREE.Mesh>(null);

  // Reusable quad mesh for rendering passes
  const quadMesh = useMemo(() => {
    const mesh = new THREE.Mesh(quadGeo, stampMat);
    quadScene.add(mesh);
    return mesh;
  }, [quadGeo, stampMat, quadScene]);

  // Coverage sampling pixel buffer (1/16 resolution)
  const coveragePixels = useMemo(
    () => new Float32Array(4),
    [],
  );

  useFrame(() => {
    if (!revealActive || resolution === 0) return;

    // 1. STAMP PASS: stamp brush at smoothed pointer
    const smoothed = getSmoothedPointer(pointerX, pointerY);
    const brushRadiusPx = getBrushRadius();
    const brushRadiusUV = brushRadiusPx / Math.max(size.width, size.height);

    stampMat.uniforms.tPrevMask.value = maskFboB.texture;
    stampMat.uniforms.uPointer.value.set(smoothed.x, 1.0 - smoothed.y); // flip Y for UV
    stampMat.uniforms.uRadius.value = brushRadiusUV;
    stampMat.uniforms.uStrength.value = reducedMotion ? 0.8 : 1.0;

    quadMesh.material = stampMat;
    gl.setRenderTarget(maskFboA);
    gl.render(quadScene, quadCamera);

    // 2. DECAY PASS: decay persistence
    decayMat.uniforms.tMask.value = maskFboA.texture;
    decayMat.uniforms.uDecay.value = getDecayFactor();

    quadMesh.material = decayMat;
    gl.setRenderTarget(maskFboB);
    gl.render(quadScene, quadCamera);

    // 3. BLUR PASS (high tier only): separable Gaussian
    if (qualityTier === 'high' && !reducedMotion) {
      // Horizontal
      blurMatH.uniforms.tMask.value = maskFboB.texture;
      quadMesh.material = blurMatH;
      gl.setRenderTarget(maskFboA);
      gl.render(quadScene, quadCamera);

      // Vertical
      blurMatV.uniforms.tMask.value = maskFboA.texture;
      quadMesh.material = blurMatV;
      gl.setRenderTarget(maskFboB);
      gl.render(quadScene, quadCamera);
    }

    gl.setRenderTarget(null);

    // Sample coverage (read single pixel from center for approximation)
    gl.setRenderTarget(maskFboB);
    gl.readRenderTargetPixels(maskFboB, resolution / 2, resolution / 2, 1, 1, coveragePixels);
    gl.setRenderTarget(null);
    setMaskCoverage(Math.min(1, coveragePixels[0] * 2)); // scale up center sample
  });

  // Expose mask texture for the blend pass
  return null; // The pipeline writes to FBOs; blend is done in the PostStack or a separate mesh
}
```

**Step 2: Commit**

```bash
git add lap-website/src/experience/reveal/RevealMaskPipeline.tsx
git commit -m "feat(reveal): add RevealMaskPipeline with FBO ping-pong stamp/decay/blur passes"
```

---

### Task 14: Create RevealBlendMesh for final compositing

**Files:**
- Create: `lap-website/src/experience/reveal/RevealBlendMesh.tsx`

**Step 1: Write implementation**

This mesh sits at `renderOrder: 998` (just below the transition compositor at 999) and blends Layer A/B using the mask. For now, Layer A = scene render and Layer B = a solid telemetry-tinted overlay. The actual telemetry content will be added in a later task.

Create `lap-website/src/experience/reveal/RevealBlendMesh.tsx`:

```typescript
'use client';

import { useMemo } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import { useFBO } from '@react-three/drei';
import * as THREE from 'three';
import { useKernelStore } from '@/experience/state/store';
import { computeMaskResolution } from './useRevealState';
import { revealBlendVertex, revealBlendFragment } from './shaders/reveal-blend';

interface RevealBlendMeshProps {
  maskTexture: THREE.Texture | null;
}

/**
 * RevealBlendMesh — full-screen quad that composites Layer A and Layer B
 * using the reveal mask texture. Renders at renderOrder 998.
 *
 * For Prototype 1: Layer A = transparent (scene shows through),
 * Layer B = telemetry overlay texture (initially a simple tinted grid).
 */
export function RevealBlendMesh({ maskTexture }: RevealBlendMeshProps) {
  const active = useKernelStore((s) => s.reveal.active);
  const qualityTier = useKernelStore((s) => s.qualityTier);
  const resolution = computeMaskResolution(qualityTier);

  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: revealBlendVertex,
        fragmentShader: revealBlendFragment,
        uniforms: {
          tLayerA: { value: null },  // placeholder: clean surface
          tLayerB: { value: null },  // placeholder: truth layer
          tMask: { value: null },
        },
        transparent: true,
        depthTest: false,
        depthWrite: false,
      }),
    [],
  );

  useFrame(() => {
    if (!active || resolution === 0 || !maskTexture) return;
    material.uniforms.tMask.value = maskTexture;
  });

  if (!active || resolution === 0) return null;

  return (
    <mesh renderOrder={998}>
      <planeGeometry args={[2, 2]} />
      <primitive object={material} attach="material" />
    </mesh>
  );
}
```

**Step 2: Commit**

```bash
git add lap-website/src/experience/reveal/RevealBlendMesh.tsx
git commit -m "feat(reveal): add RevealBlendMesh for final Layer A/B compositing"
```

---

### Task 15: Wire reveal pipeline into ExperienceCanvas

**Files:**
- Modify: `lap-website/src/experience/renderer/ExperienceCanvas.tsx:1-40`

**Step 1: Add reveal pipeline to canvas**

Add imports:
```typescript
import { RevealMaskPipeline } from '@/experience/reveal/RevealMaskPipeline';
```

Add inside the `<Suspense>` block, after `<SceneManager />`:
```typescript
          <RevealMaskPipeline />
```

**Step 2: Run full test suite**

Run: `cd lap-website && npx vitest run`
Expected: All PASS

**Step 3: Commit**

```bash
git add lap-website/src/experience/renderer/ExperienceCanvas.tsx
git commit -m "feat(canvas): wire RevealMaskPipeline into ExperienceCanvas"
```

---

### Task 16: Add mobile touch burst support to reveal

**Files:**
- Modify: `lap-website/src/experience/reveal/RevealMaskPipeline.tsx`

**Step 1: Add touch detection and burst behavior**

In `RevealMaskPipeline.tsx`, add touch state tracking:

```typescript
const isTouchRef = useRef(false);
const burstRef = useRef(false);

useEffect(() => {
  const handleTouch = () => { isTouchRef.current = true; };
  window.addEventListener('touchstart', handleTouch, { once: true, passive: true });
  return () => window.removeEventListener('touchstart', handleTouch);
}, []);
```

In the stamp pass, adjust radius for mobile burst:
```typescript
// Mobile: use burst radius on first touch, then decay faster
const radiusPx = burstRef.current
  ? revealPhysics.mobileBurstRadius
  : brushRadiusPx;
```

Add pointer down detection for burst:
```typescript
useEffect(() => {
  if (!isTouchRef.current) return;
  const handlePointerDown = () => { burstRef.current = true; };
  const handlePointerUp = () => {
    setTimeout(() => { burstRef.current = false; }, 100);
  };
  window.addEventListener('pointerdown', handlePointerDown, { passive: true });
  window.addEventListener('pointerup', handlePointerUp, { passive: true });
  return () => {
    window.removeEventListener('pointerdown', handlePointerDown);
    window.removeEventListener('pointerup', handlePointerUp);
  };
}, []);
```

**Step 2: Run tests**

Run: `cd lap-website && npx vitest run`
Expected: All PASS

**Step 3: Commit**

```bash
git add lap-website/src/experience/reveal/RevealMaskPipeline.tsx
git commit -m "feat(reveal): add mobile touch burst support with larger radius and faster decay"
```

---

### Task 17: Add reduced motion fallback for reveal

**Files:**
- Modify: `lap-website/src/experience/reveal/RevealMaskPipeline.tsx`

**Step 1: Add reduced motion path**

When `reducedMotion` is true, skip decay/blur passes. The stamp writes at full opacity with no persistence — effectively an instant blend at pointer position that doesn't trail.

In the `useFrame` callback, wrap the decay and blur passes:

```typescript
if (!reducedMotion) {
  // 2. DECAY PASS
  // ... existing decay code ...
  // 3. BLUR PASS
  // ... existing blur code ...
} else {
  // Reduced motion: stamp only, no persistence
  // Copy stamp result directly to output FBO
  decayMat.uniforms.tMask.value = maskFboA.texture;
  decayMat.uniforms.uDecay.value = 0.0; // instant clear — no trail
  quadMesh.material = decayMat;
  gl.setRenderTarget(maskFboB);
  gl.render(quadScene, quadCamera);
}
```

**Step 2: Run tests**

Run: `cd lap-website && npx vitest run`
Expected: All PASS

**Step 3: Commit**

```bash
git add lap-website/src/experience/reveal/RevealMaskPipeline.tsx
git commit -m "feat(reveal): add reduced motion fallback — instant blend, no trail persistence"
```

---

### Task 18: Add CSS fallback for no-WebGL reveal

**Files:**
- Modify: `lap-website/src/experience/quality/FallbackShell.tsx`

**Step 1: Read current FallbackShell**

Read the existing `FallbackShell.tsx` to understand the current fallback structure, then add a CSS radial-gradient mask effect that follows pointer via a CSS custom property.

The CSS fallback uses `--pointer-x` and `--pointer-y` custom properties set by the existing `PointerField` (or a simple `mousemove` listener). A `radial-gradient` mask creates a soft reveal circle.

Add to `FallbackShell` children wrapper:
```typescript
<div
  className="pointer-events-none fixed inset-0 z-0 transition-opacity duration-1000"
  style={{
    background: `radial-gradient(circle 120px at var(--pointer-x, 50%) var(--pointer-y, 50%), rgba(217, 70, 239, 0.08) 0%, transparent 100%)`,
  }}
/>
```

**Step 2: Run tests**

Run: `cd lap-website && npx vitest run`
Expected: All PASS

**Step 3: Commit**

```bash
git add lap-website/src/experience/quality/FallbackShell.tsx
git commit -m "feat(fallback): add CSS radial-gradient reveal for no-WebGL devices"
```

---

## Phase 4: Living Surface (Prototype 2)

> **Note:** Phase 4 tasks follow the same pattern. Each task creates one layer of the Living Surface, replacing `AtmosphereBase`. The full implementation details are in the design doc section 5.2.2.

### Task 19: Create LivingSurface base component with grain layer

Replace `AtmosphereBase` pattern with a new multi-layer component. Start with just the noise/grain layer.

**Files:**
- Create: `lap-website/src/experience/renderer/scenes/LivingSurface.tsx`
- Create: `lap-website/src/experience/renderer/scenes/shaders/grain.ts`

### Task 20: Add contour field layer to LivingSurface

Add `THREE.Line` contour curves that drift toward pointer and react to track heading.

**Files:**
- Modify: `lap-website/src/experience/renderer/scenes/LivingSurface.tsx`

### Task 21: Add enhanced particle drift layer with turn-feel

Extend existing particle pattern with lateral drift from `headingDelta`.

**Files:**
- Modify: `lap-website/src/experience/renderer/scenes/LivingSurface.tsx`

### Task 22: Add speed streak layer

Spawn short line segments on high scroll velocity, oriented to track heading.

**Files:**
- Modify: `lap-website/src/experience/renderer/scenes/LivingSurface.tsx`

### Task 23: Add vignette layer with turn-aware offset

Full-screen radial gradient that shifts toward corner apex.

**Files:**
- Modify: `lap-website/src/experience/renderer/scenes/LivingSurface.tsx`
- Create: `lap-website/src/experience/renderer/scenes/shaders/vignette.ts`

### Task 24: Replace AtmosphereBase with LivingSurface in all scenes

Update chapter scene configs to use LivingSurface. Keep AtmosphereBase as the `low` tier fallback.

**Files:**
- Modify: `lap-website/src/experience/renderer/scenes/StartGridScene.tsx` (and all 8 other scene files)
- Modify: `lap-website/src/experience/state/chapters.ts`

---

## Phase 5: HUD Chrome

### Task 25: Create TimingTower component (replaces SectorTabs)

**Files:**
- Create: `lap-website/src/components/chrome/TimingTower.tsx`
- Test: `lap-website/src/__tests__/timing-tower.test.tsx`

The TimingTower reads from `useKernelStore.hudTower`, renders 8 sector labels with progress rings, handles purple completion flash, and preserves the existing `scrollIntoView` navigation. Desktop: vertical left rail. Mobile: hidden (existing dot nav stays).

### Task 26: Create sector gate sweep line animation

GSAP animation triggered by `SectorGateController` — thin purple line sweeps left→right in 400ms.

**Files:**
- Create: `lap-website/src/components/chrome/SectorGateSweep.tsx`

### Task 27: Create DeltaHud component (extends DeltaStrip)

**Files:**
- Create: `lap-website/src/components/chrome/DeltaHud.tsx`
- Test: `lap-website/src/__tests__/delta-hud.test.tsx`

Reads `hudDelta` from store. Shows value with RAF jitter animation. Green when negative, red when positive. Settles on finish.

### Task 28: Create MiniTrackMap component

**Files:**
- Create: `lap-website/src/components/chrome/MiniTrackMap.tsx`

SVG track silhouette (80x80px) with animated dot at `globalProgress`. Corner zones highlight on entry. Hidden on mobile.

### Task 29: Create DrsLabel component

**Files:**
- Create: `lap-website/src/components/chrome/DrsLabel.tsx`

Animated "DRS" text that fades in/out during DRS active window. Positioned near Timing Tower.

### Task 30: Create FinishLine component

**Files:**
- Create: `lap-website/src/components/chrome/FinishLine.tsx`

Checkered band (CSS pattern) that sweeps across viewport on `finish.crossed`. GSAP animation.

### Task 31: Wire all HUD components into ExperienceShell

**Files:**
- Modify: `lap-website/src/experience/ExperienceShell.tsx:21-50`

Replace `<SectorTabs />` with `<TimingTower />`. Replace `<DeltaStrip />` with `<DeltaHud />`. Add `<MiniTrackMap />`, `<DrsLabel />`, `<SectorGateSweep />`, `<FinishLine />`.

### Task 32: Add HUD aria-hidden and accessibility attributes

All HUD elements are decorative — add `aria-hidden="true"` and ensure `role="presentation"`. Except TimingTower navigation buttons which keep `aria-label`.

### Task 33: Run full test suite and commit Phase 5

Run: `cd lap-website && npx vitest run && npm run lint`
Commit all Phase 5 work.

---

## Phase 6: Section-Specific Choreography

### Task 34: Create RadioCard component

**Files:**
- Create: `lap-website/src/components/ui/RadioCard.tsx`

Compact (1-line) on hover, expanded (waveform + content) on click. CSS transitions + waveform bars keyframe.

### Task 35: Create TrackCard component (3D tilt)

**Files:**
- Create: `lap-website/src/components/ui/TrackCard.tsx`

CSS `perspective: 1200px`, `transform: rotateX/Y` from pointer position. Max ±8° tilt. Parallax inner layers.

### Task 36: Create PitWheel background component

**Files:**
- Create: `lap-website/src/components/chrome/PitWheel.tsx`

SVG wheel that rotates proportional to `scrollVelocity * velocityMultiplier`. Decelerates with `wheelFriction`.

### Task 37: Add pit limiter behavior to PitStop section

When chapter 8 is active, `pitMode` is true. Velocity multiplier dampens all motion. PitWheel shows behind pricing.

**Files:**
- Modify: `lap-website/src/components/rooms/PitStop.tsx`

### Task 38: Integrate RadioCards into existing flip-card sections

Replace Placard/ReversibleCard content patterns with RadioCard where appropriate (S1, S2, S4).

**Files:**
- Modify: `lap-website/src/components/rooms/S1Pain.tsx`
- Modify: `lap-website/src/components/rooms/S2Pipeline.tsx`
- Modify: `lap-website/src/components/rooms/S4WorkflowCoverage.tsx`

### Task 39: Integrate TrackCards into S4 and S5

Replace flat grid cards with TrackCard components in workflows and personas sections.

**Files:**
- Modify: `lap-website/src/components/rooms/S4WorkflowCoverage.tsx`
- Modify: `lap-website/src/components/rooms/S5Personas.tsx`

### Task 40: Add DRS triggers to interaction components

Fire `activateDrs` on first flip-card reveal in each section, on pipeline completion, on persona card expand.

**Files:**
- Modify: `lap-website/src/components/ui/Placard.tsx`
- Modify: `lap-website/src/components/rooms/S2Pipeline.tsx`
- Modify: `lap-website/src/components/rooms/S5Personas.tsx`

### Task 41: Run full test suite and commit Phase 6

Run: `cd lap-website && npx vitest run && npm run lint && npm run build`
Commit all Phase 6 work.

---

## Phase 7: Integration, Polish, Performance Validation

### Task 42: Add feature flag for experience layer v2

**Files:**
- Create: `lap-website/src/lib/feature-flags.ts`
- Modify: `lap-website/src/experience/ExperienceKernel.tsx`

Environment variable `NEXT_PUBLIC_EXPERIENCE_V2=1` gates all new systems. When off, existing behavior is unchanged.

### Task 43: Performance profiling and quality tier validation

Run Lighthouse on desktop and mobile. Verify:
- LCP < previous + 200ms
- CLS < previous + 0.01
- Desktop FPS ≥ 50 fps (high tier)
- Mobile FPS ≥ 28 fps (balanced tier)
- No CTA obscured by HUD

Adjust quality tier thresholds in `QualityManager` if needed.

### Task 44: Reduced motion audit

Enable `prefers-reduced-motion: reduce`. Navigate full page. Verify every component has a premium fallback. No animation except instant state changes.

### Task 45: Keyboard and screen reader audit

Tab through full page. Verify:
- All CTAs reachable via keyboard
- TimingTower buttons accessible
- All decorative elements `aria-hidden`
- No focus traps
- NVDA/VoiceOver reads content correctly

### Task 46: Final integration test and commit

Run: `cd lap-website && npm run ci`

This runs: `npm run lint && npm run test && npm run build && npm run qa:content`

If all pass, create final commit:

```bash
git add -A
git commit -m "feat(experience): complete experience layer v2 — reveal, living surface, HUD, narrative system"
```

---

## Appendix: Quick Reference

### Test commands
```bash
cd lap-website
npx vitest run                                    # all tests
npx vitest run src/__tests__/kernel-store.test.ts  # store tests
npx vitest run src/__tests__/track-path.test.ts    # track path tests
npx vitest run src/__tests__/tokens.test.ts        # token tests
npm run lint                                       # ESLint
npm run build                                      # Next.js build
npm run ci                                         # full CI pipeline
```

### Key file paths
| Module | Path |
|--------|------|
| Kernel store | `lap-website/src/experience/state/store.ts` |
| Store types | `lap-website/src/experience/state/types.ts` |
| Chapters | `lap-website/src/experience/state/chapters.ts` |
| Canvas | `lap-website/src/experience/renderer/ExperienceCanvas.tsx` |
| Shell | `lap-website/src/experience/ExperienceShell.tsx` |
| Kernel | `lap-website/src/experience/ExperienceKernel.tsx` |
| Post-processing | `lap-website/src/experience/renderer/PostStack.tsx` |
| Transitions | `lap-website/src/experience/transitions/TransitionCompositor.tsx` |
| Scenes | `lap-website/src/experience/renderer/scenes/` |
| Chrome/HUD | `lap-website/src/components/chrome/` |
| UI primitives | `lap-website/src/components/ui/` |
| Rooms | `lap-website/src/components/rooms/` |
| CSS tokens | `lap-website/src/styles/tokens.css` |
| JS tokens | `lap-website/src/lib/tokens.ts` |
| Tailwind | `lap-website/tailwind.config.ts` |
| Physics | `lap-website/src/experience/motion/springs.ts` |
| Tests | `lap-website/src/__tests__/` |

### Design doc
`docs/plans/2026-02-27-experience-layer-blueprint-design.md`
