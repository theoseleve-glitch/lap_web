# Experience Layer Hardening — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rewrite the V2 experience layer renderer to achieve Lando-level immersion: track ribbon background with corner-feel, completed reveal pipeline with dual truth layers, 5 integrated Draco-compressed 3D assets, RadioCard redesign, and Safety Car fallback.

**Architecture:** Single persistent R3F scene replaces per-chapter SceneManager. Track ribbon geometry generated from TrackPath data drives camera yaw/bank on corners. RevealBlendMesh mounted with FBO mask compositing dual truth layers (track map + telemetry). Progressive 3D asset loading along ribbon spline.

**Tech Stack:** Next.js 14, React 18, Three.js 0.183, React Three Fiber 8, @react-three/drei 9, GSAP 3.14, Zustand 5, gltf-transform (asset pipeline), Vitest (unit tests)

---

## Pre-Requisites

Before starting any prototype task, the 5 GLB assets must be optimized. This is a manual CLI step using `gltf-transform`.

### Task 0: Optimize 3D Assets with gltf-transform

**Files:**
- Source: `3d_assets/F1_Helmet_--_STL.glb`, `3d_assets/halo_ferrari.glb`, `3d_assets/Ferrari_f1-75_steering_wheel.glb`, `3d_assets/Muretto_Box.glb`, `3d_assets/pneu_F1.glb`
- Output: `lap-website/public/models/helmet.glb`, `lap-website/public/models/halo.glb`, `lap-website/public/models/steering-wheel.glb`, `lap-website/public/models/pit-wall.glb`, `lap-website/public/models/tire.glb`

**Step 1: Install gltf-transform CLI**

Run: `cd lap-website && npm install --save-dev @gltf-transform/cli`

**Step 2: Create output directory**

Run: `mkdir -p lap-website/public/models`

**Step 3: Optimize each asset**

```bash
cd lap-website

# Helmet: heavy (3.32MB, 124K verts) → decimate + Draco → target 300KB
npx gltf-transform dedup ../3d_assets/F1_Helmet_--_STL.glb /tmp/helmet-dedup.glb
npx gltf-transform simplify /tmp/helmet-dedup.glb /tmp/helmet-simple.glb --ratio 0.12
npx gltf-transform draco /tmp/helmet-simple.glb public/models/helmet.glb

# Halo: moderate (966KB, 37K verts) → Draco only → target 200KB
npx gltf-transform dedup ../3d_assets/halo_ferrari.glb /tmp/halo-dedup.glb
npx gltf-transform draco /tmp/halo-dedup.glb public/models/halo.glb

# Steering wheel: multi-mesh (1.16MB, 11+ meshes) → merge + Draco → target 150KB
npx gltf-transform dedup ../3d_assets/Ferrari_f1-75_steering_wheel.glb /tmp/wheel-dedup.glb
npx gltf-transform join /tmp/wheel-dedup.glb /tmp/wheel-joined.glb
npx gltf-transform draco /tmp/wheel-joined.glb public/models/steering-wheel.glb

# Pit wall: moderate (1.27MB, 49K verts) → Draco only → target 250KB
npx gltf-transform dedup ../3d_assets/Muretto_Box.glb /tmp/pitwall-dedup.glb
npx gltf-transform draco /tmp/pitwall-dedup.glb public/models/pit-wall.glb

# Tire: heavy (7.52MB, 273K verts) → decimate + Draco → target 400KB
npx gltf-transform dedup ../3d_assets/pneu_F1.glb /tmp/tire-dedup.glb
npx gltf-transform simplify /tmp/tire-dedup.glb /tmp/tire-simple.glb --ratio 0.07
npx gltf-transform draco /tmp/tire-simple.glb public/models/tire.glb
```

**Step 4: Verify total size < 1.5MB**

Run: `ls -la lap-website/public/models/*.glb`
Expected: Total of all 5 files < 1.5MB

**Step 5: Commit**

```bash
git add lap-website/public/models/
git commit -m "feat(assets): add 5 Draco-compressed 3D models for experience layer"
```

> **Note**: If `simplify` produces artifacts (faceted normals, holes), adjust `--ratio` upward. If an asset exceeds budget, try `--error 0.01` for better quality at slightly larger size. The tire is the most at-risk for visual degradation — inspect it in https://gltf-viewer.donmccurdy.com/ before committing.

---

## Prototype 1: Track Ribbon + Atmosphere + Corner Feel

**Goal:** Replace the generic LivingSurface background with a track ribbon that makes the user feel like they're navigating a circuit. Corner chapters induce camera yaw/bank. Text remains readable.

---

### Task 1: Extend KernelStore Types

**Files:**
- Modify: `lap-website/src/experience/state/types.ts`

**Step 1: Add new state interfaces**

Add after the `FinishState` interface (line 131):

```typescript
export interface BackgroundState {
  cornerYaw: number;       // current yaw offset in degrees
  cornerBank: number;      // current bank offset in degrees
  streakIntensity: number; // 0-1, modulated by DRS + velocity
  ribbonProgress: number;  // 0-1, where camera is on ribbon
}

export interface AssetState {
  loaded: Record<string, boolean>;   // per-asset load state
  visible: Record<string, boolean>;  // per-asset visibility
}

export interface SafetyCarState {
  active: boolean;
  reason: string;
  enteredAt: number;
}
```

**Step 2: Add new action interfaces**

Add after `ExtendedKernelActions` (before the `KernelStore` type):

```typescript
export interface BackgroundActions {
  setCornerYaw: (yaw: number) => void;
  setCornerBank: (bank: number) => void;
  setStreakIntensity: (intensity: number) => void;
  setRibbonProgress: (progress: number) => void;
}

export interface AssetActions {
  setAssetLoaded: (id: string, loaded: boolean) => void;
  setAssetVisible: (id: string, visible: boolean) => void;
}

export interface SafetyCarActions {
  enterSafetyCar: (reason: string) => void;
  exitSafetyCar: () => void;
}
```

**Step 3: Update KernelStore type**

Replace the existing `KernelStore` type:

```typescript
export type KernelStore = KernelState & KernelActions
  & ExtendedKernelState & ExtendedKernelActions
  & { background: BackgroundState } & BackgroundActions
  & { assets: AssetState } & AssetActions
  & { safetyCar: SafetyCarState } & SafetyCarActions;
```

**Step 4: Verify build**

Run: `cd lap-website && npx tsc --noEmit`
Expected: Type errors in store.ts (new properties not yet implemented — expected)

**Step 5: Commit**

```bash
git add lap-website/src/experience/state/types.ts
git commit -m "feat(types): add background, assets, safetyCar state interfaces"
```

---

### Task 2: Implement New Store Slices

**Files:**
- Modify: `lap-website/src/experience/state/store.ts`

**Step 1: Add initial state for new slices**

Add to `initialState` after the `finish` property:

```typescript
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
```

**Step 2: Add actions inside the create() call**

Add after `crossFinishLine`:

```typescript
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
```

**Step 3: Verify types compile**

Run: `cd lap-website && npx tsc --noEmit`
Expected: 0 errors

**Step 4: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds

**Step 5: Commit**

```bash
git add lap-website/src/experience/state/store.ts
git commit -m "feat(store): implement background, assets, safetyCar slices"
```

---

### Task 3: Add Ribbon Spring Constants

**Files:**
- Modify: `lap-website/src/experience/motion/springs.ts`

**Step 1: Add ribbon constants to background object**

Replace the `background` export:

```typescript
export const background = {
  // Existing
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

  // New: Track ribbon
  ribbonWidth: 8,                  // world units
  ribbonEdgeEmissive: 0.08,        // edge glow opacity
  ribbonSegmentGlow: 0.12,         // completed sector glow opacity
  ribbonForwardGlow: 0.20,         // brighter emission ahead of camera
  ribbonStepSize: 0.5,             // world units per ribbon segment

  // New: Corner feel
  cornerYawRange: 3.0,             // max degrees (±3°)
  cornerBankRange: 1.5,            // max degrees (±1.5°)
  cornerLerp: 0.05,               // per-frame lerp toward target yaw/bank
  cornerParticleDriftMultiplier: 2.0, // lateral drift amplifier in corners

  // New: Streak DRS modulation
  streakDrsThresholdReduction: 0.4, // spawn threshold × (1 - this) during DRS
} as const;
```

**Step 2: Verify build**

Run: `cd lap-website && npx tsc --noEmit`
Expected: 0 errors

**Step 3: Commit**

```bash
git add lap-website/src/experience/motion/springs.ts
git commit -m "feat(springs): add track ribbon and corner-feel constants"
```

---

### Task 4: Write TrackRibbonGeometry (Pure Function)

**Files:**
- Create: `lap-website/src/experience/renderer/TrackRibbonGeometry.ts`
- Create: `lap-website/src/experience/__tests__/TrackRibbonGeometry.test.ts`

**Step 1: Write the failing test**

```typescript
// lap-website/src/experience/__tests__/TrackRibbonGeometry.test.ts
import { describe, it, expect } from 'vitest';
import { buildRibbonPoints, TOTAL_LENGTH } from '../renderer/TrackRibbonGeometry';
import { TRACK_PATH } from '../narrative/TrackPath';

describe('buildRibbonPoints', () => {
  it('generates points from TRACK_PATH', () => {
    const points = buildRibbonPoints(TRACK_PATH);
    expect(points.length).toBeGreaterThan(0);
  });

  it('starts near origin', () => {
    const points = buildRibbonPoints(TRACK_PATH);
    expect(Math.abs(points[0].x)).toBeLessThan(1);
    expect(Math.abs(points[0].z)).toBeLessThan(1);
  });

  it('generates at least one point per chapter', () => {
    const points = buildRibbonPoints(TRACK_PATH);
    expect(points.length).toBeGreaterThanOrEqual(TRACK_PATH.length);
  });

  it('TOTAL_LENGTH is positive', () => {
    expect(TOTAL_LENGTH).toBeGreaterThan(0);
  });

  it('generates consistent output for same input', () => {
    const a = buildRibbonPoints(TRACK_PATH);
    const b = buildRibbonPoints(TRACK_PATH);
    expect(a.length).toBe(b.length);
    expect(a[0].x).toBe(b[0].x);
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd lap-website && npx vitest run src/experience/__tests__/TrackRibbonGeometry.test.ts`
Expected: FAIL — module not found

**Step 3: Write implementation**

```typescript
// lap-website/src/experience/renderer/TrackRibbonGeometry.ts
import * as THREE from 'three';
import type { ChapterPathConfig } from '@/experience/narrative/TrackPath';
import { background } from '@/experience/motion/springs';

const DEG2RAD = Math.PI / 180;
const STEP_SIZE = background.ribbonStepSize;

/** Total ribbon length in world units — one unit per "weight" of chapter */
export const TOTAL_LENGTH = 100;

interface RibbonPoint {
  x: number;
  y: number;
  z: number;
}

/**
 * Build an array of 3D points tracing the track ribbon from chapter headings.
 * Each chapter's heading defines the direction of travel in the XZ plane.
 * The ribbon is flat (Y=0).
 */
export function buildRibbonPoints(chapters: readonly ChapterPathConfig[]): RibbonPoint[] {
  const points: RibbonPoint[] = [];
  let x = 0;
  let z = 0;
  let currentHeading = 0; // degrees

  const chapterWeight = TOTAL_LENGTH / chapters.length;

  for (const chapter of chapters) {
    const segmentLength = chapterWeight;
    // Accumulate heading
    currentHeading += chapter.heading;
    const headingRad = currentHeading * DEG2RAD;
    const steps = Math.max(1, Math.ceil(segmentLength / STEP_SIZE));

    for (let i = 0; i < steps; i++) {
      x += Math.sin(headingRad) * STEP_SIZE;
      z += Math.cos(headingRad) * STEP_SIZE;
      points.push({ x, y: 0, z });
    }
  }

  return points;
}

/**
 * Build a Three.js CatmullRomCurve3 from the ribbon points.
 * Used for camera path following + ribbon mesh extrusion.
 */
export function buildRibbonCurve(chapters: readonly ChapterPathConfig[]): THREE.CatmullRomCurve3 {
  const points = buildRibbonPoints(chapters);
  const vectors = points.map((p) => new THREE.Vector3(p.x, p.y, p.z));
  return new THREE.CatmullRomCurve3(vectors, false, 'catmullrom', 0.5);
}

/**
 * Extrude the ribbon curve into a flat mesh with given width.
 * Returns a BufferGeometry suitable for rendering as a track surface.
 */
export function extrudeRibbonGeometry(
  curve: THREE.CatmullRomCurve3,
  width: number,
  segments: number = 200,
): THREE.BufferGeometry {
  const positions: number[] = [];
  const uvs: number[] = [];
  const indices: number[] = [];

  for (let i = 0; i <= segments; i++) {
    const t = i / segments;
    const point = curve.getPointAt(t);
    const tangent = curve.getTangentAt(t).normalize();

    // Normal in XZ plane (perpendicular to tangent, flat)
    const normal = new THREE.Vector3(-tangent.z, 0, tangent.x);
    const halfWidth = width / 2;

    // Left edge
    positions.push(
      point.x - normal.x * halfWidth,
      point.y,
      point.z - normal.z * halfWidth,
    );
    // Right edge
    positions.push(
      point.x + normal.x * halfWidth,
      point.y,
      point.z + normal.z * halfWidth,
    );

    uvs.push(0, t);
    uvs.push(1, t);

    if (i < segments) {
      const base = i * 2;
      indices.push(base, base + 1, base + 2);
      indices.push(base + 1, base + 3, base + 2);
    }
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  return geometry;
}
```

**Step 4: Run test to verify it passes**

Run: `cd lap-website && npx vitest run src/experience/__tests__/TrackRibbonGeometry.test.ts`
Expected: 5 tests PASS

**Step 5: Commit**

```bash
git add lap-website/src/experience/renderer/TrackRibbonGeometry.ts lap-website/src/experience/__tests__/TrackRibbonGeometry.test.ts
git commit -m "feat(ribbon): add TrackRibbonGeometry with curve + extrusion + tests"
```

---

### Task 5: Write Track Ribbon Shaders

**Files:**
- Create: `lap-website/src/experience/renderer/shaders/track-ribbon.ts`

**Step 1: Write ribbon edge + progress shaders**

```typescript
// lap-website/src/experience/renderer/shaders/track-ribbon.ts

/** Track ribbon surface shader — dark base with emissive edges and progress glow */
export const trackRibbonVertex = /* glsl */ `
varying vec2 vUv;
varying float vProgress;

uniform float uCameraProgress; // 0-1, where camera is on ribbon

void main() {
  vUv = uv;
  vProgress = uv.y; // V maps along the ribbon length (0 = start, 1 = end)
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

export const trackRibbonFragment = /* glsl */ `
uniform float uCameraProgress;
uniform float uEdgeEmissive;
uniform float uForwardGlow;
uniform vec3 uEdgeColor;
uniform vec3 uSectorColor;
uniform float uSectorGlow;
uniform float uSectorStart; // 0-1 progress of completed sector start
uniform float uSectorEnd;   // 0-1 progress of completed sector end

varying vec2 vUv;
varying float vProgress;

void main() {
  // Base: very dark, barely visible
  vec3 base = vec3(0.04, 0.045, 0.06);

  // Edge glow: bright thin lines at U=0 and U=1
  float edgeDist = min(vUv.x, 1.0 - vUv.x);
  float edgeMask = smoothstep(0.05, 0.0, edgeDist);
  vec3 edge = uEdgeColor * edgeMask * uEdgeEmissive;

  // Forward progress glow: brighter ahead, dimmer behind
  float progressDelta = vProgress - uCameraProgress;
  float forwardMask = smoothstep(-0.05, 0.1, progressDelta) * smoothstep(0.3, 0.05, progressDelta);
  vec3 forward = uEdgeColor * forwardMask * uForwardGlow;

  // Completed sector highlight
  float sectorMask = step(uSectorStart, vProgress) * step(vProgress, uSectorEnd);
  vec3 sector = uSectorColor * sectorMask * uSectorGlow * edgeMask;

  vec3 color = base + edge + forward + sector;
  float alpha = 0.8 * edgeMask + 0.15 + forwardMask * 0.3 + sectorMask * 0.2;

  gl_FragColor = vec4(color, clamp(alpha, 0.0, 1.0));
}
`;
```

**Step 2: Verify build**

Run: `cd lap-website && npx tsc --noEmit`
Expected: 0 errors

**Step 3: Commit**

```bash
git add lap-website/src/experience/renderer/shaders/track-ribbon.ts
git commit -m "feat(shaders): add track ribbon surface shader with edge glow + progress"
```

---

### Task 6: Write TrackRibbon Component

**Files:**
- Create: `lap-website/src/experience/renderer/TrackRibbon.tsx`

**Step 1: Write the component**

```typescript
// lap-website/src/experience/renderer/TrackRibbon.tsx
'use client';

import { useMemo, useEffect } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { useKernelStore } from '@/experience/state/store';
import { TRACK_PATH } from '@/experience/narrative/TrackPath';
import { background } from '@/experience/motion/springs';
import { colors } from '@/lib/tokens';
import { buildRibbonCurve, extrudeRibbonGeometry } from './TrackRibbonGeometry';
import { trackRibbonVertex, trackRibbonFragment } from './shaders/track-ribbon';

// Parse hex to THREE.Color once
const edgeColor = new THREE.Color(colors.chalk);
const sectorColor = new THREE.Color(colors.racingPurple);

export function TrackRibbon() {
  const qualityTier = useKernelStore((s) => s.qualityTier);

  const segments = qualityTier === 'high' ? 300 : qualityTier === 'balanced' ? 150 : 80;

  const curve = useMemo(() => buildRibbonCurve(TRACK_PATH), []);

  const geometry = useMemo(
    () => extrudeRibbonGeometry(curve, background.ribbonWidth, segments),
    [curve, segments],
  );

  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: trackRibbonVertex,
        fragmentShader: trackRibbonFragment,
        uniforms: {
          uCameraProgress: { value: 0 },
          uEdgeEmissive: { value: background.ribbonEdgeEmissive },
          uForwardGlow: { value: background.ribbonForwardGlow },
          uEdgeColor: { value: edgeColor },
          uSectorColor: { value: sectorColor },
          uSectorGlow: { value: background.ribbonSegmentGlow },
          uSectorStart: { value: 0 },
          uSectorEnd: { value: 0 },
        },
        transparent: true,
        depthWrite: false,
        depthTest: false,
        side: THREE.DoubleSide,
      }),
    [],
  );

  useEffect(() => {
    return () => {
      geometry.dispose();
      material.dispose();
    };
  }, [geometry, material]);

  useFrame(() => {
    const { globalProgress, hudTower } = useKernelStore.getState();
    material.uniforms.uCameraProgress.value = globalProgress;

    // Find the furthest completed sector for highlight
    let sectorEnd = 0;
    for (let i = 0; i < hudTower.sectors.length; i++) {
      if (hudTower.sectors[i].status === 'completed') {
        sectorEnd = (i + 1) / hudTower.sectors.length;
      }
    }
    material.uniforms.uSectorEnd.value = sectorEnd;
  });

  return (
    <mesh geometry={geometry} material={material} renderOrder={-98} />
  );
}
```

**Step 2: Verify build**

Run: `cd lap-website && npx tsc --noEmit`
Expected: 0 errors

**Step 3: Commit**

```bash
git add lap-website/src/experience/renderer/TrackRibbon.tsx
git commit -m "feat(ribbon): add TrackRibbon R3F component with shader material"
```

---

### Task 7: Write Atmosphere Component

**Files:**
- Create: `lap-website/src/experience/renderer/Atmosphere.tsx`

**Step 1: Write the 5-layer atmosphere component**

This replaces the per-chapter LivingSurface. It reuses the existing grain and vignette shaders but removes contour lines (replaced by track ribbon) and keeps particles + streaks.

```typescript
// lap-website/src/experience/renderer/Atmosphere.tsx
'use client';

import { useRef, useMemo, useEffect } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import * as THREE from 'three';
import { useKernelStore } from '@/experience/state/store';
import { background } from '@/experience/motion/springs';
import { grainVertex, grainFragment } from './scenes/shaders/grain';
import { vignetteVertex, vignetteFragment } from './scenes/shaders/vignette';

const PARTICLE_COUNT_HIGH = 200;
const PARTICLE_COUNT_BALANCED = 100;

const _vignetteTarget = new THREE.Vector2();
const _vignetteCenter = new THREE.Vector2(0, 0);

interface Streak {
  alive: boolean;
  age: number;
  x: number;
  y: number;
  heading: number;
}

/**
 * Atmosphere — 5-layer persistent background system.
 * L1: Grain (always)
 * L2: TrackRibbon (separate component, rendered outside)
 * L3: ParticleField (velocity-reactive drift)
 * L4: SpeedStreaks (scroll-velocity accents)
 * L5: Vignette (readability shield)
 */
export function Atmosphere() {
  const { size } = useThree();
  const qualityTier = useKernelStore((s) => s.qualityTier);
  const reducedMotion = useKernelStore((s) => s.reducedMotion);

  const isHigh = qualityTier === 'high';
  const isLow = qualityTier === 'low';
  const particleCount = isLow ? 0 : isHigh ? PARTICLE_COUNT_HIGH : PARTICLE_COUNT_BALANCED;

  // ── L1: Grain ────────────────────────────────
  const grainUniforms = useMemo(() => ({
    uTime: { value: 0 },
    uIntensity: { value: background.grainIntensity },
  }), []);

  const grainMaterial = useMemo(() => new THREE.ShaderMaterial({
    vertexShader: grainVertex,
    fragmentShader: grainFragment,
    uniforms: grainUniforms,
    transparent: true,
    depthWrite: false,
    depthTest: false,
  }), [grainUniforms]);

  // ── L3: Particles ────────────────────────────
  const particlePositions = useMemo(() => {
    const arr = new Float32Array(particleCount * 3);
    for (let i = 0; i < particleCount; i++) {
      arr[i * 3] = (Math.random() - 0.5) * 20;
      arr[i * 3 + 1] = (Math.random() - 0.5) * 20;
      arr[i * 3 + 2] = (Math.random() - 0.5) * 5;
    }
    return arr;
  }, [particleCount]);

  const particlesRef = useRef<THREE.Points>(null);

  // ── L4: Speed Streaks ────────────────────────
  const streakPoolSize = background.streakCount;
  const streakPool = useRef<Streak[]>(
    Array.from({ length: streakPoolSize }, () => ({
      alive: false, age: 0, x: 0, y: 0, heading: 0,
    })),
  );

  const streakPositions = useMemo(() => new Float32Array(streakPoolSize * 6), [streakPoolSize]);

  const streakGeo = useMemo(() => {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(streakPositions, 3));
    return geo;
  }, [streakPositions]);

  const streakMat = useMemo(() => new THREE.LineBasicMaterial({
    color: '#F3F0E8',
    transparent: true,
    opacity: 0.3,
    depthWrite: false,
  }), []);

  const streakLinesRef = useRef<THREE.LineSegments>(null);

  // ── L5: Vignette ─────────────────────────────
  const vignetteUniforms = useMemo(() => ({
    uRadius: { value: background.vignetteRadius },
    uShift: { value: new THREE.Vector2(0, 0) },
  }), []);

  const vignetteMaterial = useMemo(() => new THREE.ShaderMaterial({
    vertexShader: vignetteVertex,
    fragmentShader: vignetteFragment,
    uniforms: vignetteUniforms,
    transparent: true,
    depthWrite: false,
    depthTest: false,
  }), [vignetteUniforms]);

  // ── Animation ────────────────────────────────
  useFrame((_, delta) => {
    const state = useKernelStore.getState();
    const { trackPath, scrollVelocity, pointerX, pointerY, drs } = state;

    if (reducedMotion) return;

    // Grain time
    grainUniforms.uTime.value += delta;

    // Particles: drift + pointer attraction
    if (particlesRef.current && particleCount > 0) {
      const posArray = particlesRef.current.geometry.attributes.position.array as Float32Array;
      const cornerBoost = trackPath.isCorner ? background.cornerParticleDriftMultiplier : 1.0;
      const lateralDrift = trackPath.headingDelta * background.particleDriftX * delta * cornerBoost;
      const verticalDrift = scrollVelocity * background.particleDriftY * delta;

      const pWorldX = (pointerX - 0.5) * 20;
      const pWorldY = (pointerY - 0.5) * 20;
      const attractRadius = background.particlePointerRadius / (size.width || 1) * 20;

      for (let i = 0; i < particleCount; i++) {
        const ix = i * 3;
        const iy = ix + 1;
        posArray[ix] += lateralDrift;
        posArray[iy] += verticalDrift;

        const dx = pWorldX - posArray[ix];
        const dy = pWorldY - posArray[iy];
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < attractRadius && dist > 0.01) {
          const force = (1 - dist / attractRadius) * 0.02;
          posArray[ix] += dx * force;
          posArray[iy] += dy * force;
        }

        if (posArray[ix] > 10) posArray[ix] = -10;
        if (posArray[ix] < -10) posArray[ix] = 10;
        if (posArray[iy] > 10) posArray[iy] = -10;
        if (posArray[iy] < -10) posArray[iy] = 10;
      }
      particlesRef.current.geometry.attributes.position.needsUpdate = true;
    }

    // Streaks: spawn + age (DRS modulates threshold)
    if (isHigh && streakLinesRef.current) {
      const pool = streakPool.current;
      const lifetime = background.streakLifetime;
      const halfLen = background.streakLength / (size.width || 1) * 10;
      const heading = trackPath.heading;

      // DRS reduces spawn threshold
      const threshold = drs.active
        ? background.streakSpawnThreshold * (1 - background.streakDrsThresholdReduction)
        : background.streakSpawnThreshold;

      if (Math.abs(scrollVelocity) > threshold) {
        for (let i = 0; i < pool.length; i++) {
          if (!pool[i].alive) {
            pool[i].alive = true;
            pool[i].age = 0;
            pool[i].x = (Math.random() - 0.5) * 16;
            pool[i].y = (Math.random() - 0.5) * 16;
            pool[i].heading = heading;
            break;
          }
        }
      }

      for (let i = 0; i < pool.length; i++) {
        const s = pool[i];
        const base = i * 6;
        if (s.alive) {
          s.age += delta * 1000;
          if (s.age > lifetime) s.alive = false;
        }
        if (s.alive) {
          const cosH = Math.cos(s.heading);
          const sinH = Math.sin(s.heading);
          streakPositions[base] = s.x - cosH * halfLen;
          streakPositions[base + 1] = s.y - sinH * halfLen;
          streakPositions[base + 2] = 0;
          streakPositions[base + 3] = s.x + cosH * halfLen;
          streakPositions[base + 4] = s.y + sinH * halfLen;
          streakPositions[base + 5] = 0;
        } else {
          for (let j = 0; j < 6; j++) streakPositions[base + j] = 0;
        }
      }
      streakGeo.attributes.position.needsUpdate = true;
      const vel = Math.abs(scrollVelocity);
      streakMat.opacity = Math.min(0.5, (vel - threshold) * 0.8);
    }

    // Vignette shift toward corner apex
    if (trackPath.isCorner) {
      _vignetteTarget.set(
        Math.sin(trackPath.heading) * background.vignetteShift,
        -Math.cos(trackPath.heading) * background.vignetteShift,
      );
      vignetteUniforms.uShift.value.lerp(_vignetteTarget, 0.05);
    } else {
      vignetteUniforms.uShift.value.lerp(_vignetteCenter, 0.03);
    }
  });

  // ── Cleanup ──────────────────────────────────
  useEffect(() => {
    return () => {
      grainMaterial.dispose();
      vignetteMaterial.dispose();
      streakGeo.dispose();
      streakMat.dispose();
    };
  }, [grainMaterial, vignetteMaterial, streakGeo, streakMat]);

  return (
    <group renderOrder={-100}>
      {/* L1: Grain */}
      <mesh renderOrder={-99}>
        <planeGeometry args={[50, 50]} />
        <primitive object={grainMaterial} attach="material" />
      </mesh>

      {/* L2: TrackRibbon rendered separately (sibling component) */}

      {/* L3: Particles */}
      {particleCount > 0 && (
        <points ref={particlesRef} renderOrder={-97}>
          <bufferGeometry>
            <bufferAttribute attach="attributes-position" args={[particlePositions, 3]} />
          </bufferGeometry>
          <pointsMaterial
            size={0.03}
            color="#F3F0E8"
            transparent
            opacity={0.25}
            sizeAttenuation
            depthWrite={false}
          />
        </points>
      )}

      {/* L4: Speed streaks */}
      {isHigh && (
        <lineSegments
          ref={streakLinesRef}
          geometry={streakGeo}
          material={streakMat}
          renderOrder={-96}
        />
      )}

      {/* L5: Vignette */}
      <mesh renderOrder={-95}>
        <planeGeometry args={[50, 50]} />
        <primitive object={vignetteMaterial} attach="material" />
      </mesh>
    </group>
  );
}
```

**Step 2: Verify build**

Run: `cd lap-website && npx tsc --noEmit`
Expected: 0 errors

**Step 3: Commit**

```bash
git add lap-website/src/experience/renderer/Atmosphere.tsx
git commit -m "feat(atmosphere): add 5-layer persistent background (grain, particles, streaks, vignette)"
```

---

### Task 8: Write PersistentScene Component

**Files:**
- Create: `lap-website/src/experience/renderer/PersistentScene.tsx`

**Step 1: Write the component**

This is the single persistent scene that replaces SceneManager. It holds the Atmosphere + TrackRibbon + a slot for AssetManager and RevealBlendMesh (added in Prototype 2).

```typescript
// lap-website/src/experience/renderer/PersistentScene.tsx
'use client';

import { useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { useKernelStore } from '@/experience/state/store';
import { background } from '@/experience/motion/springs';
import { isCornerChapter, getChapterPath } from '@/experience/narrative/TrackPath';
import { Atmosphere } from './Atmosphere';
import { TrackRibbon } from './TrackRibbon';

/** Lerp utility for smooth transitions */
function lerpAngle(current: number, target: number, factor: number): number {
  return current + (target - current) * factor;
}

/**
 * PersistentScene — single persistent R3F scene.
 *
 * Contains the full visual stack:
 * - Atmosphere (grain + particles + streaks + vignette)
 * - TrackRibbon (the track layout mesh)
 * - Camera corner-feel (yaw + bank on corner chapters)
 *
 * AssetManager and RevealBlendMesh will be added as children in Prototype 2.
 */
export function PersistentScene() {
  const groupRef = useRef<THREE.Group>(null);
  const yawRef = useRef(0);
  const bankRef = useRef(0);

  useFrame(() => {
    const state = useKernelStore.getState();
    const { currentChapter, reducedMotion } = state;

    if (!groupRef.current) return;

    // Corner feel: camera yaw + bank
    if (reducedMotion) {
      // Instant reset under reduced motion
      yawRef.current = 0;
      bankRef.current = 0;
    } else {
      const path = getChapterPath(currentChapter);
      const isCorner = isCornerChapter(currentChapter);

      if (isCorner) {
        // Determine yaw direction from heading sign
        const direction = path.heading > 0 ? 1 : -1;
        const yawTarget = direction * background.cornerYawRange;
        const bankTarget = direction * background.cornerBankRange;
        yawRef.current = lerpAngle(yawRef.current, yawTarget, background.cornerLerp);
        bankRef.current = lerpAngle(bankRef.current, bankTarget, background.cornerLerp);
      } else {
        // Return to neutral on straights
        yawRef.current = lerpAngle(yawRef.current, 0, background.cornerLerp);
        bankRef.current = lerpAngle(bankRef.current, 0, background.cornerLerp);
      }
    }

    // Apply yaw (Y rotation) and bank (Z rotation) to the scene group
    const DEG2RAD = Math.PI / 180;
    groupRef.current.rotation.y = yawRef.current * DEG2RAD;
    groupRef.current.rotation.z = bankRef.current * DEG2RAD;
  });

  return (
    <group ref={groupRef}>
      <ambientLight intensity={0.1} />
      <Atmosphere />
      <TrackRibbon />
      {/* Prototype 2 will add: <AssetManager />, <RevealBlendMesh /> */}
    </group>
  );
}
```

**Step 2: Verify build**

Run: `cd lap-website && npx tsc --noEmit`
Expected: 0 errors

**Step 3: Commit**

```bash
git add lap-website/src/experience/renderer/PersistentScene.tsx
git commit -m "feat(scene): add PersistentScene with corner-feel yaw/bank"
```

---

### Task 9: Wire PersistentScene into ExperienceCanvas

**Files:**
- Modify: `lap-website/src/experience/renderer/ExperienceCanvas.tsx`

**Step 1: Replace SceneManager with PersistentScene**

Replace the full file content:

```typescript
'use client';

import { Suspense } from 'react';
import { Canvas } from '@react-three/fiber';
import { useKernelStore } from '@/experience/state/store';
import { PersistentScene } from './PersistentScene';
import { PostStack } from './PostStack';
import { RevealMaskPipeline } from '@/experience/reveal/RevealMaskPipeline';

export function ExperienceCanvas() {
  const webglAvailable = useKernelStore((s) => s.webglAvailable);
  const reducedMotion = useKernelStore((s) => s.reducedMotion);
  const qualityTier = useKernelStore((s) => s.qualityTier);
  const safetyCarActive = useKernelStore((s) => s.safetyCar.active);

  if (!webglAvailable || safetyCarActive) return null;

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
          <PersistentScene />
          <RevealMaskPipeline />
          {!reducedMotion && qualityTier !== 'low' && <PostStack />}
        </Suspense>
      </Canvas>
    </div>
  );
}
```

**Step 2: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds

**Step 3: Run existing tests**

Run: `cd lap-website && npm run test`
Expected: All existing tests pass (90+)

**Step 4: Commit**

```bash
git add lap-website/src/experience/renderer/ExperienceCanvas.tsx
git commit -m "feat(canvas): replace SceneManager with PersistentScene"
```

> **Note:** The old SceneManager.tsx, chapter scenes (S1Scene, S2Scene, etc.), and LivingSurface.tsx are NOT deleted yet — they are kept for reference and rollback safety. They are no longer imported anywhere. They can be removed after Prototype 1 is validated visually.

---

### Task 10: Visual Verification — Prototype 1

**Files:**
- None (verification only)

**Step 1: Run dev server**

Run: `cd lap-website && npm run dev`
Expected: Server starts on localhost:3000

**Step 2: Open browser and verify**

Open https://localhost:3000 in a browser. Verify:

1. Track ribbon visible in background (thin emissive edge lines, not contour rings)
2. Scroll through all sections — corner chapters (S1 Pain, S1 Deep, S3 Product, S5 Personas) should show subtle yaw/bank
3. Straight chapters should feel calmer
4. Particles still drift (responsive to pointer)
5. Speed streaks appear on fast scroll (high quality)
6. Vignette darkens edges for readability
7. All text and CTAs remain readable
8. Timing tower, delta HUD, mini track map still functional

Take screenshots for comparison.

**Step 3: Check reduced motion**

Enable `prefers-reduced-motion: reduce` in browser settings. Verify:
- No yaw/bank
- No particle animation
- Grain is frozen
- Background is static but still shows ribbon outline

**Step 4: Check mobile viewport**

Resize to 375×812. Verify:
- Quality drops to balanced
- Particles are halved
- No speed streaks
- Still readable

**Step 5: Commit verification notes**

No code changes — just visual inspection.

---

### Task 11: Delete Legacy Scene Files

**Files:**
- Delete: `lap-website/src/experience/renderer/scenes/StartGridScene.tsx`
- Delete: `lap-website/src/experience/renderer/scenes/S1Scene.tsx`
- Delete: `lap-website/src/experience/renderer/scenes/S2Scene.tsx`
- Delete: `lap-website/src/experience/renderer/scenes/S3Scene.tsx`
- Delete: `lap-website/src/experience/renderer/scenes/S4Scene.tsx`
- Delete: `lap-website/src/experience/renderer/scenes/S5Scene.tsx`
- Delete: `lap-website/src/experience/renderer/scenes/PitStopScene.tsx`
- Delete: `lap-website/src/experience/renderer/scenes/GarageScene.tsx`
- Delete: `lap-website/src/experience/renderer/scenes/PodiumScene.tsx`
- Delete: `lap-website/src/experience/renderer/scenes/AtmosphereBase.tsx`
- Delete: `lap-website/src/experience/renderer/scenes/LivingSurface.tsx`
- Modify: `lap-website/src/experience/state/chapters.ts` — set all scene references to `null`

> **Important:** Only do this after Task 10 visual verification passes. Keep `SceneManager.tsx` around for now (unused but harmless).

**Step 1: Update chapters.ts to remove scene imports**

Set all chapter `scene` properties to `null` (since PersistentScene is scene-agnostic now). The chapter configs are still used for narrative tracking.

**Step 2: Delete the scene files**

```bash
rm lap-website/src/experience/renderer/scenes/StartGridScene.tsx
rm lap-website/src/experience/renderer/scenes/S1Scene.tsx
rm lap-website/src/experience/renderer/scenes/S2Scene.tsx
rm lap-website/src/experience/renderer/scenes/S3Scene.tsx
rm lap-website/src/experience/renderer/scenes/S4Scene.tsx
rm lap-website/src/experience/renderer/scenes/S5Scene.tsx
rm lap-website/src/experience/renderer/scenes/PitStopScene.tsx
rm lap-website/src/experience/renderer/scenes/GarageScene.tsx
rm lap-website/src/experience/renderer/scenes/PodiumScene.tsx
rm lap-website/src/experience/renderer/scenes/AtmosphereBase.tsx
rm lap-website/src/experience/renderer/scenes/LivingSurface.tsx
```

**Step 3: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds (no dangling imports)

**Step 4: Commit**

```bash
git add -A
git commit -m "refactor(scenes): remove per-chapter scene files (replaced by PersistentScene)"
```

---

## Prototype 2: Reveal Pipeline + Truth Layers + 3D Assets

**Goal:** Complete the reveal pipeline so the cursor reveals truth content. Mount RevealBlendMesh with dual truth layers. Load and place 5 Draco-compressed 3D assets along the ribbon.

---

### Task 12: Expose Mask FBO from RevealMaskPipeline

**Files:**
- Modify: `lap-website/src/experience/reveal/RevealMaskPipeline.tsx`

**Step 1: Add forwardRef + imperative handle to expose mask texture**

The pipeline already renders to `maskFboB`. We need to expose that texture so RevealBlendMesh can use it.

Add at the top of the file, update the imports:

```typescript
import { useRef, useMemo, useEffect, useImperativeHandle, forwardRef } from 'react';
```

Change the component signature to:

```typescript
export interface RevealMaskPipelineHandle {
  getMaskTexture: () => THREE.Texture | null;
}

export const RevealMaskPipeline = forwardRef<RevealMaskPipelineHandle>(
  function RevealMaskPipeline(_, ref) {
```

Add after `const readbackSupported = useRef<boolean | null>(null);`:

```typescript
    useImperativeHandle(ref, () => ({
      getMaskTexture: () => maskFboB.texture,
    }));
```

Close the component with the forwardRef closing paren:

```typescript
  return null;
});
```

**Step 2: Verify build**

Run: `cd lap-website && npx tsc --noEmit`
Expected: 0 errors (forwardRef is type-compatible)

**Step 3: Commit**

```bash
git add lap-website/src/experience/reveal/RevealMaskPipeline.tsx
git commit -m "feat(reveal): expose mask FBO texture via imperative handle"
```

---

### Task 13: Write Truth Layer — Track Map

**Files:**
- Create: `lap-website/src/experience/reveal/TruthLayerTrackMap.tsx`
- Create: `lap-website/src/experience/reveal/shaders/truth-trackmap.ts`

**Step 1: Write the track map truth layer shader**

```typescript
// lap-website/src/experience/reveal/shaders/truth-trackmap.ts

/** Track map "blueprint" truth layer — bright track outline + sector colors + braking zones */
export const truthTrackMapVertex = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

export const truthTrackMapFragment = /* glsl */ `
uniform float uTime;
uniform float uProgress;
uniform vec3 uEdgeColor;
uniform vec3 uSectorColor;
uniform float uSectorEnd;

varying vec2 vUv;

// Simple hash-based noise
float hash(vec2 p) {
  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

void main() {
  // Grid lines — faint blueprint grid
  float gridX = smoothstep(0.02, 0.0, fract(vUv.x * 20.0));
  float gridY = smoothstep(0.02, 0.0, fract(vUv.y * 20.0));
  float grid = max(gridX, gridY) * 0.15;

  // Track centerline — bright when revealed
  float centerDist = abs(vUv.x - 0.5);
  float centerLine = smoothstep(0.02, 0.0, centerDist) * 0.8;

  // Sector highlight band
  float sectorMask = step(0.0, vUv.y) * step(vUv.y, uSectorEnd);
  float sectorBand = sectorMask * smoothstep(0.15, 0.1, centerDist) * 0.3;

  // Braking zone markers (periodic dashes along the track)
  float brakeDash = step(0.7, fract(vUv.y * 40.0)) * smoothstep(0.08, 0.05, centerDist) * 0.4;

  // Apex markers (small dots at specific V positions)
  float apexDot = 0.0;
  for (int i = 0; i < 5; i++) {
    float apexY = float(i) * 0.2 + 0.1;
    float dist = length(vUv - vec2(0.5, apexY));
    apexDot += smoothstep(0.015, 0.005, dist) * 0.6;
  }

  // Compose
  vec3 color = uEdgeColor * (grid + centerLine + brakeDash + apexDot)
             + uSectorColor * sectorBand;

  // Subtle noise for texture
  float n = hash(vUv * 100.0 + uTime) * 0.02;

  float alpha = grid + centerLine + sectorBand + brakeDash + apexDot + n;
  gl_FragColor = vec4(color, clamp(alpha, 0.0, 0.9));
}
`;
```

**Step 2: Write the truth layer component**

```typescript
// lap-website/src/experience/reveal/TruthLayerTrackMap.tsx
'use client';

import { useMemo, useEffect } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import { useFBO } from '@react-three/drei';
import * as THREE from 'three';
import { useKernelStore } from '@/experience/state/store';
import { colors } from '@/lib/tokens';
import { truthTrackMapVertex, truthTrackMapFragment } from './shaders/truth-trackmap';

const edgeColor = new THREE.Color(colors.chalk);
const sectorColor = new THREE.Color(colors.racingPurple);

interface TruthLayerTrackMapProps {
  onTextureReady: (texture: THREE.Texture) => void;
}

/**
 * Renders the "track map blueprint" truth layer to an FBO.
 * Used as Layer B (revealed content) for hero chapters 0-2.
 */
export function TruthLayerTrackMap({ onTextureReady }: TruthLayerTrackMapProps) {
  const { gl } = useThree();
  const qualityTier = useKernelStore((s) => s.qualityTier);
  const resolution = qualityTier === 'high' ? 1024 : 512;

  const fbo = useFBO(resolution, resolution, {
    minFilter: THREE.LinearFilter,
    magFilter: THREE.LinearFilter,
    type: THREE.HalfFloatType,
  });

  const scene = useMemo(() => new THREE.Scene(), []);
  const camera = useMemo(() => new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1), []);

  const material = useMemo(() => new THREE.ShaderMaterial({
    vertexShader: truthTrackMapVertex,
    fragmentShader: truthTrackMapFragment,
    uniforms: {
      uTime: { value: 0 },
      uProgress: { value: 0 },
      uEdgeColor: { value: edgeColor },
      uSectorColor: { value: sectorColor },
      uSectorEnd: { value: 0 },
    },
    transparent: true,
  }), []);

  const mesh = useMemo(() => {
    const geo = new THREE.PlaneGeometry(2, 2);
    const m = new THREE.Mesh(geo, material);
    scene.add(m);
    return m;
  }, [material, scene]);

  useEffect(() => {
    onTextureReady(fbo.texture);
  }, [fbo.texture, onTextureReady]);

  useEffect(() => {
    return () => {
      material.dispose();
      mesh.geometry.dispose();
    };
  }, [material, mesh]);

  useFrame((_, delta) => {
    const { globalProgress, hudTower } = useKernelStore.getState();
    material.uniforms.uTime.value += delta;
    material.uniforms.uProgress.value = globalProgress;

    let sectorEnd = 0;
    for (let i = 0; i < hudTower.sectors.length; i++) {
      if (hudTower.sectors[i].status === 'completed') {
        sectorEnd = (i + 1) / hudTower.sectors.length;
      }
    }
    material.uniforms.uSectorEnd.value = sectorEnd;

    gl.setRenderTarget(fbo);
    gl.render(scene, camera);
    gl.setRenderTarget(null);
  });

  return null;
}
```

**Step 3: Verify build**

Run: `cd lap-website && npx tsc --noEmit`
Expected: 0 errors

**Step 4: Commit**

```bash
git add lap-website/src/experience/reveal/TruthLayerTrackMap.tsx lap-website/src/experience/reveal/shaders/truth-trackmap.ts
git commit -m "feat(truth): add TruthLayerTrackMap — blueprint overlay FBO"
```

---

### Task 14: Write Truth Layer — Telemetry

**Files:**
- Create: `lap-website/src/experience/reveal/TruthLayerTelemetry.tsx`
- Create: `lap-website/src/experience/reveal/shaders/truth-telemetry.ts`

**Step 1: Write the telemetry truth layer shader**

```typescript
// lap-website/src/experience/reveal/shaders/truth-telemetry.ts

/** Telemetry data overlay — trace waveforms, delta numbers, grid, timing labels */
export const truthTelemetryVertex = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

export const truthTelemetryFragment = /* glsl */ `
uniform float uTime;
uniform float uProgress;
uniform vec3 uTraceColor;
uniform vec3 uGridColor;

varying vec2 vUv;

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

void main() {
  // Fine grid
  float gridX = smoothstep(0.015, 0.0, fract(vUv.x * 30.0));
  float gridY = smoothstep(0.015, 0.0, fract(vUv.y * 30.0));
  float grid = max(gridX, gridY) * 0.1;

  // Simulated trace waveforms — 3 horizontal channels
  float trace = 0.0;
  for (int i = 0; i < 3; i++) {
    float yBase = 0.25 + float(i) * 0.25;
    float wave = sin(vUv.x * 40.0 + uTime * 2.0 + float(i) * 1.5) * 0.03;
    float dist = abs(vUv.y - yBase - wave);
    trace += smoothstep(0.008, 0.0, dist) * 0.6;
  }

  // Delta bar — horizontal bar at bottom
  float deltaBar = smoothstep(0.06, 0.04, vUv.y)
                 * smoothstep(0.0, 0.02, vUv.y);
  float deltaFill = step(vUv.x, uProgress) * deltaBar * 0.4;

  // Timing labels (tiny dashes along top)
  float timingDash = step(0.92, vUv.y) * smoothstep(0.02, 0.0, fract(vUv.x * 15.0)) * 0.3;

  vec3 color = uGridColor * grid + uTraceColor * trace + uTraceColor * deltaFill + uGridColor * timingDash;

  float n = hash(vUv * 200.0 + uTime) * 0.015;
  float alpha = grid + trace + deltaFill + timingDash + n;

  gl_FragColor = vec4(color, clamp(alpha, 0.0, 0.85));
}
`;
```

**Step 2: Write the telemetry truth layer component**

```typescript
// lap-website/src/experience/reveal/TruthLayerTelemetry.tsx
'use client';

import { useMemo, useEffect } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import { useFBO } from '@react-three/drei';
import * as THREE from 'three';
import { useKernelStore } from '@/experience/state/store';
import { colors } from '@/lib/tokens';
import { truthTelemetryVertex, truthTelemetryFragment } from './shaders/truth-telemetry';

const traceColor = new THREE.Color(colors.acidGreen);
const gridColor = new THREE.Color(colors.steel);

interface TruthLayerTelemetryProps {
  onTextureReady: (texture: THREE.Texture) => void;
}

/**
 * Renders the "telemetry data" truth layer to an FBO.
 * Used as Layer B (revealed content) for section chapters 3-9.
 */
export function TruthLayerTelemetry({ onTextureReady }: TruthLayerTelemetryProps) {
  const { gl } = useThree();
  const qualityTier = useKernelStore((s) => s.qualityTier);
  const resolution = qualityTier === 'high' ? 1024 : 512;

  const fbo = useFBO(resolution, resolution, {
    minFilter: THREE.LinearFilter,
    magFilter: THREE.LinearFilter,
    type: THREE.HalfFloatType,
  });

  const scene = useMemo(() => new THREE.Scene(), []);
  const camera = useMemo(() => new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1), []);

  const material = useMemo(() => new THREE.ShaderMaterial({
    vertexShader: truthTelemetryVertex,
    fragmentShader: truthTelemetryFragment,
    uniforms: {
      uTime: { value: 0 },
      uProgress: { value: 0 },
      uTraceColor: { value: traceColor },
      uGridColor: { value: gridColor },
    },
    transparent: true,
  }), []);

  const mesh = useMemo(() => {
    const geo = new THREE.PlaneGeometry(2, 2);
    const m = new THREE.Mesh(geo, material);
    scene.add(m);
    return m;
  }, [material, scene]);

  useEffect(() => {
    onTextureReady(fbo.texture);
  }, [fbo.texture, onTextureReady]);

  useEffect(() => {
    return () => {
      material.dispose();
      mesh.geometry.dispose();
    };
  }, [material, mesh]);

  useFrame((_, delta) => {
    const { globalProgress } = useKernelStore.getState();
    material.uniforms.uTime.value += delta;
    material.uniforms.uProgress.value = globalProgress;

    gl.setRenderTarget(fbo);
    gl.render(scene, camera);
    gl.setRenderTarget(null);
  });

  return null;
}
```

**Step 3: Verify build**

Run: `cd lap-website && npx tsc --noEmit`
Expected: 0 errors

**Step 4: Commit**

```bash
git add lap-website/src/experience/reveal/TruthLayerTelemetry.tsx lap-website/src/experience/reveal/shaders/truth-telemetry.ts
git commit -m "feat(truth): add TruthLayerTelemetry — data overlay FBO"
```

---

### Task 15: Rewrite RevealBlendMesh with Truth Layer Switching

**Files:**
- Modify: `lap-website/src/experience/reveal/RevealBlendMesh.tsx`

**Step 1: Rewrite to accept truth layer textures and mask ref**

```typescript
// lap-website/src/experience/reveal/RevealBlendMesh.tsx
'use client';

import { useEffect, useMemo, useRef, useCallback } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { useKernelStore } from '@/experience/state/store';
import { computeMaskResolution } from './useRevealState';
import { revealBlendVertex, revealBlendFragment } from './shaders/reveal-blend';
import { TruthLayerTrackMap } from './TruthLayerTrackMap';
import { TruthLayerTelemetry } from './TruthLayerTelemetry';
import type { RevealMaskPipelineHandle } from './RevealMaskPipeline';

interface RevealBlendMeshProps {
  maskPipelineRef: React.RefObject<RevealMaskPipelineHandle | null>;
}

/**
 * RevealBlendMesh — full-screen quad that composites truth content using the
 * reveal mask. Renders at renderOrder 998.
 *
 * - Hero (chapters 0-2): Layer B = track map blueprint
 * - Sections (chapters 3-9): Layer B = telemetry data overlay
 * - Pit + Podium (chapters 8, 10): reveal disabled
 *
 * Layer A is transparent (scene shows through), so `colorA` = vec4(0).
 * The blend shader mixes Layer A and Layer B by the mask's R channel.
 */
export function RevealBlendMesh({ maskPipelineRef }: RevealBlendMeshProps) {
  const active = useKernelStore((s) => s.reveal.active);
  const qualityTier = useKernelStore((s) => s.qualityTier);
  const resolution = computeMaskResolution(qualityTier);

  const trackMapTextureRef = useRef<THREE.Texture | null>(null);
  const telemetryTextureRef = useRef<THREE.Texture | null>(null);

  const onTrackMapReady = useCallback((tex: THREE.Texture) => {
    trackMapTextureRef.current = tex;
  }, []);

  const onTelemetryReady = useCallback((tex: THREE.Texture) => {
    telemetryTextureRef.current = tex;
  }, []);

  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: revealBlendVertex,
        fragmentShader: revealBlendFragment,
        uniforms: {
          tLayerA: { value: null },
          tLayerB: { value: null },
          tMask: { value: null },
        },
        transparent: true,
        depthTest: false,
        depthWrite: false,
      }),
    [],
  );

  useEffect(() => {
    return () => { material.dispose(); };
  }, [material]);

  useFrame(() => {
    if (!active || resolution === 0) return;

    const maskTexture = maskPipelineRef.current?.getMaskTexture() ?? null;
    if (!maskTexture) return;

    const { currentChapter } = useKernelStore.getState();

    // Select truth layer based on chapter
    let truthTexture: THREE.Texture | null = null;
    if (currentChapter <= 2) {
      truthTexture = trackMapTextureRef.current;
    } else if (currentChapter <= 9 && currentChapter !== 8) {
      truthTexture = telemetryTextureRef.current;
    }
    // Chapters 8 (pit) and 10 (podium): no reveal

    material.uniforms.tMask.value = maskTexture;
    material.uniforms.tLayerB.value = truthTexture;
    // tLayerA stays null (transparent — scene shows through)
  });

  if (!active || resolution === 0) return null;

  return (
    <>
      <TruthLayerTrackMap onTextureReady={onTrackMapReady} />
      <TruthLayerTelemetry onTextureReady={onTelemetryReady} />
      <mesh renderOrder={998}>
        <planeGeometry args={[2, 2]} />
        <primitive object={material} attach="material" />
      </mesh>
    </>
  );
}
```

**Step 2: Verify build**

Run: `cd lap-website && npx tsc --noEmit`
Expected: 0 errors

**Step 3: Commit**

```bash
git add lap-website/src/experience/reveal/RevealBlendMesh.tsx
git commit -m "feat(reveal): rewrite RevealBlendMesh with dual truth layers + mask compositing"
```

---

### Task 16: Mount Reveal System in PersistentScene

**Files:**
- Modify: `lap-website/src/experience/renderer/PersistentScene.tsx`
- Modify: `lap-website/src/experience/renderer/ExperienceCanvas.tsx`

**Step 1: Update ExperienceCanvas to pass mask ref**

In `ExperienceCanvas.tsx`, add a ref for RevealMaskPipeline and pass it to PersistentScene:

```typescript
'use client';

import { Suspense, useRef } from 'react';
import { Canvas } from '@react-three/fiber';
import { useKernelStore } from '@/experience/state/store';
import { PersistentScene } from './PersistentScene';
import { PostStack } from './PostStack';
import { RevealMaskPipeline } from '@/experience/reveal/RevealMaskPipeline';
import type { RevealMaskPipelineHandle } from '@/experience/reveal/RevealMaskPipeline';
import { RevealBlendMesh } from '@/experience/reveal/RevealBlendMesh';

export function ExperienceCanvas() {
  const webglAvailable = useKernelStore((s) => s.webglAvailable);
  const reducedMotion = useKernelStore((s) => s.reducedMotion);
  const qualityTier = useKernelStore((s) => s.qualityTier);
  const safetyCarActive = useKernelStore((s) => s.safetyCar.active);
  const maskPipelineRef = useRef<RevealMaskPipelineHandle>(null);

  if (!webglAvailable || safetyCarActive) return null;

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
          <PersistentScene />
          <RevealMaskPipeline ref={maskPipelineRef} />
          <RevealBlendMesh maskPipelineRef={maskPipelineRef} />
          {!reducedMotion && qualityTier !== 'low' && <PostStack />}
        </Suspense>
      </Canvas>
    </div>
  );
}
```

**Step 2: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds

**Step 3: Commit**

```bash
git add lap-website/src/experience/renderer/ExperienceCanvas.tsx
git commit -m "feat(canvas): mount RevealBlendMesh with mask pipeline ref"
```

---

### Task 17: Write AssetManager + Asset Manifest

**Files:**
- Create: `lap-website/src/experience/renderer/AssetManager.tsx`
- Create: `lap-website/src/experience/renderer/assetManifest.ts`

**Step 1: Write the asset manifest**

```typescript
// lap-website/src/experience/renderer/assetManifest.ts

export interface AssetEntry {
  id: string;
  path: string;
  progress: number;     // 0-1 position along the narrative
  position: [number, number, number]; // world-space offset
  rotation: [number, number, number]; // euler angles
  scale: number;
  chapterRange: [number, number]; // visible when chapter is in this range
}

export const ASSET_MANIFEST: readonly AssetEntry[] = [
  {
    id: 'helmet',
    path: '/models/helmet.glb',
    progress: 0.0,
    position: [3, 0.5, -2],
    rotation: [0, -0.3, 0],
    scale: 0.8,
    chapterRange: [0, 2],
  },
  {
    id: 'halo',
    path: '/models/halo.glb',
    progress: 0.45,
    position: [-3, 0.3, -1.5],
    rotation: [0.1, 0.5, 0],
    scale: 0.6,
    chapterRange: [4, 6],
  },
  {
    id: 'steering-wheel',
    path: '/models/steering-wheel.glb',
    progress: 0.55,
    position: [2.5, 0, -1],
    rotation: [0.3, -0.2, 0.1],
    scale: 0.5,
    chapterRange: [5, 7],
  },
  {
    id: 'pit-wall',
    path: '/models/pit-wall.glb',
    progress: 0.75,
    position: [-2, -0.5, -2],
    rotation: [0, 0.4, 0],
    scale: 0.4,
    chapterRange: [7, 9],
  },
  {
    id: 'tire',
    path: '/models/tire.glb',
    progress: 0.78,
    position: [2, -0.3, -1.5],
    rotation: [0, 0, 0],
    scale: 0.7,
    chapterRange: [8, 9],
  },
] as const;
```

**Step 2: Write the AssetManager component**

```typescript
// lap-website/src/experience/renderer/AssetManager.tsx
'use client';

import { Suspense, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import { useGLTF } from '@react-three/drei';
import * as THREE from 'three';
import { useKernelStore } from '@/experience/state/store';
import { ASSET_MANIFEST, type AssetEntry } from './assetManifest';

/** Preload assets that are within 2 chapters of current */
function useAssetPreload(currentChapter: number) {
  const nearbyAssets = useMemo(
    () =>
      ASSET_MANIFEST.filter(
        (a) =>
          currentChapter >= a.chapterRange[0] - 2 &&
          currentChapter <= a.chapterRange[1] + 2,
      ),
    [currentChapter],
  );

  // Preload next-up assets
  for (const asset of nearbyAssets) {
    useGLTF.preload(asset.path);
  }

  return nearbyAssets;
}

function AssetInstance({ entry }: { entry: AssetEntry }) {
  const { scene } = useGLTF(entry.path);
  const reducedMotion = useKernelStore((s) => s.reducedMotion);
  const setAssetLoaded = useKernelStore((s) => s.setAssetLoaded);

  // Mark loaded
  useMemo(() => {
    setAssetLoaded(entry.id, true);
  }, [entry.id, setAssetLoaded]);

  // Clone scene for independent transforms
  const clonedScene = useMemo(() => {
    const clone = scene.clone();
    // Apply dark emissive material override for consistency
    clone.traverse((child) => {
      if (child instanceof THREE.Mesh && child.material) {
        const mat = (child.material as THREE.MeshStandardMaterial).clone();
        mat.emissive = new THREE.Color(0x111118);
        mat.emissiveIntensity = 0.3;
        mat.metalness = 0.8;
        mat.roughness = 0.3;
        mat.transparent = true;
        mat.opacity = 0.7;
        child.material = mat;
      }
    });
    return clone;
  }, [scene]);

  // Gentle float/rotation animation
  const groupRef = useMemo(() => {
    const group = new THREE.Group();
    group.position.set(...entry.position);
    group.rotation.set(...entry.rotation);
    group.scale.setScalar(entry.scale);
    return group;
  }, [entry]);

  useFrame((_, delta) => {
    if (reducedMotion) return;
    // Subtle Y-axis rotation
    groupRef.rotation.y += delta * 0.1;
    // Gentle float
    groupRef.position.y = entry.position[1] + Math.sin(Date.now() * 0.001) * 0.05;
  });

  return <primitive object={groupRef} ref={(ref: THREE.Group | null) => {
    if (ref && !ref.children.length) ref.add(clonedScene);
  }} />;
}

export function AssetManager() {
  const currentChapter = useKernelStore((s) => s.currentChapter);
  const qualityTier = useKernelStore((s) => s.qualityTier);

  // Don't load 3D assets on low quality tier
  if (qualityTier === 'low') return null;

  const nearbyAssets = useAssetPreload(currentChapter);

  const visibleAssets = useMemo(
    () =>
      nearbyAssets.filter(
        (a) =>
          currentChapter >= a.chapterRange[0] &&
          currentChapter <= a.chapterRange[1],
      ),
    [nearbyAssets, currentChapter],
  );

  return (
    <group>
      {visibleAssets.map((entry) => (
        <Suspense key={entry.id} fallback={null}>
          <AssetInstance entry={entry} />
        </Suspense>
      ))}
    </group>
  );
}
```

**Step 3: Verify build**

Run: `cd lap-website && npx tsc --noEmit`
Expected: 0 errors

**Step 4: Commit**

```bash
git add lap-website/src/experience/renderer/AssetManager.tsx lap-website/src/experience/renderer/assetManifest.ts
git commit -m "feat(assets): add AssetManager with manifest, progressive loading, visibility gating"
```

---

### Task 18: Mount AssetManager in PersistentScene

**Files:**
- Modify: `lap-website/src/experience/renderer/PersistentScene.tsx`

**Step 1: Import and add AssetManager**

Add import:
```typescript
import { AssetManager } from './AssetManager';
```

Add `<AssetManager />` inside the `<group ref={groupRef}>`, after `<TrackRibbon />`:

```typescript
    <group ref={groupRef}>
      <ambientLight intensity={0.1} />
      <Atmosphere />
      <TrackRibbon />
      <AssetManager />
    </group>
```

**Step 2: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds

**Step 3: Run tests**

Run: `cd lap-website && npm run test`
Expected: All tests pass

**Step 4: Commit**

```bash
git add lap-website/src/experience/renderer/PersistentScene.tsx
git commit -m "feat(scene): mount AssetManager in PersistentScene"
```

---

### Task 19: Visual Verification — Prototype 2

**Files:**
- None (verification only)

**Step 1: Run dev server**

Run: `cd lap-website && npm run dev`

**Step 2: Verify reveal pipeline**

1. Move cursor around hero section — should see track map blueprint revealed under cursor
2. Verify trail persistence (move fast, then stop — trail should linger and decay)
3. Verify soft edges (no hard circle spotlight)
4. Scroll to section chapters (3-9) — truth layer switches to telemetry overlay (green traces, grid lines)
5. Scroll to pit stop (chapter 8) — reveal should be disabled
6. Verify DRS boost: when DRS triggers, brush radius should visibly increase

**Step 3: Verify 3D assets**

1. Helmet visible in hero (chapters 0-2), floating subtly
2. Halo visible around chapters 4-6
3. Steering wheel visible around chapters 5-7
4. Pit wall visible around chapters 7-9
5. Tire visible around chapters 8-9
6. All assets have dark emissive treatment (not brightly lit)
7. Reduced motion: assets are static

**Step 4: Verify performance**

Open DevTools Performance tab, record a 30s scroll-through:
- Desktop high tier: target ≥ 55 fps
- Check draw call count: target ≤ 30

---

## Prototype 3: RadioCard + Pit Wheel 3D + Finish Line + Safety Car

**Goal:** Complete remaining features. Full integration. Fix all console errors. Safety Car fallback.

---

### Task 20: Write Safety Car Mode

**Files:**
- Create: `lap-website/src/experience/quality/SafetyCarMode.tsx`
- Modify: `lap-website/src/experience/ExperienceKernel.tsx`

**Step 1: Write SafetyCarMode component**

```typescript
// lap-website/src/experience/quality/SafetyCarMode.tsx
'use client';

import { useEffect, useRef } from 'react';
import { useKernelStore } from '@/experience/state/store';

const LOW_FPS_THRESHOLD = 24;
const LOW_FPS_DURATION = 3000;  // 3 seconds
const RECOVERY_FPS = 40;
const RECOVERY_DURATION = 5000; // 5 seconds

/**
 * SafetyCarMode — monitors FPS and automatically disables canvas
 * when performance is too low. Shows CSS fallback + badge.
 *
 * - FPS < 24 for 3s → enter Safety Car (disable canvas)
 * - FPS > 40 for 5s (after Safety Car) → attempt recovery at lower tier
 * - WebGL context lost → permanent Safety Car
 */
export function SafetyCarMode() {
  const enterSafetyCar = useKernelStore((s) => s.enterSafetyCar);
  const exitSafetyCar = useKernelStore((s) => s.exitSafetyCar);
  const setQualityTier = useKernelStore((s) => s.setQualityTier);

  const framesRef = useRef<number[]>([]);
  const lowStartRef = useRef(0);
  const recoveryStartRef = useRef(0);

  useEffect(() => {
    let rafId: number;
    let lastTime = performance.now();

    function tick() {
      const now = performance.now();
      const dt = now - lastTime;
      lastTime = now;

      if (dt > 0) {
        framesRef.current.push(1000 / dt);
        if (framesRef.current.length > 60) framesRef.current.shift();
      }

      if (framesRef.current.length >= 30) {
        const avg = framesRef.current.reduce((a, b) => a + b, 0) / framesRef.current.length;
        const { safetyCar } = useKernelStore.getState();

        if (!safetyCar.active) {
          // Check for low FPS
          if (avg < LOW_FPS_THRESHOLD) {
            if (lowStartRef.current === 0) lowStartRef.current = now;
            if (now - lowStartRef.current > LOW_FPS_DURATION) {
              enterSafetyCar('sustained-low-fps');
              lowStartRef.current = 0;
            }
          } else {
            lowStartRef.current = 0;
          }
        } else {
          // In Safety Car — check for recovery
          if (avg > RECOVERY_FPS) {
            if (recoveryStartRef.current === 0) recoveryStartRef.current = now;
            if (now - recoveryStartRef.current > RECOVERY_DURATION) {
              setQualityTier('low'); // recover at lowest tier
              exitSafetyCar();
              recoveryStartRef.current = 0;
            }
          } else {
            recoveryStartRef.current = 0;
          }
        }
      }

      rafId = requestAnimationFrame(tick);
    }

    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, [enterSafetyCar, exitSafetyCar, setQualityTier]);

  // Listen for WebGL context loss
  useEffect(() => {
    const handler = () => {
      enterSafetyCar('webgl-context-lost');
    };
    const canvas = document.querySelector('canvas');
    if (canvas) {
      canvas.addEventListener('webglcontextlost', handler);
      return () => canvas.removeEventListener('webglcontextlost', handler);
    }
  }, [enterSafetyCar]);

  return null;
}
```

**Step 2: Mount in ExperienceKernel**

Add import and component in `ExperienceKernel.tsx`:

```typescript
import { SafetyCarMode } from './quality/SafetyCarMode';
```

Add `<SafetyCarMode />` after `<QualityManager />`.

**Step 3: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds

**Step 4: Commit**

```bash
git add lap-website/src/experience/quality/SafetyCarMode.tsx lap-website/src/experience/ExperienceKernel.tsx
git commit -m "feat(safety-car): add SafetyCarMode FPS monitor with auto-fallback"
```

---

### Task 21: Add Safety Car CSS Fallback Badge

**Files:**
- Modify: `lap-website/src/experience/quality/FallbackShell.tsx`
- Modify: `lap-website/src/components/chrome/TimingTower.tsx`

**Step 1: Update FallbackShell to show Safety Car badge**

The FallbackShell already exists for no-WebGL. Extend it to also show when Safety Car is active.

Add a "SAFETY CAR" badge div that renders when `safetyCar.active` is true:

```typescript
const safetyCarActive = useKernelStore((s) => s.safetyCar.active);
// ... in the return:
{safetyCarActive && (
  <div className="fixed top-4 left-1/2 -translate-x-1/2 z-50 font-telemetry text-[11px] tracking-[0.3em] uppercase text-marshalYellow bg-asphalt/80 px-4 py-1.5 rounded-full border border-marshalYellow/30">
    Safety Car
  </div>
)}
```

**Step 2: Update TimingTower to show Safety Car indicator**

Add a small "SC" badge in the timing tower when Safety Car is active.

**Step 3: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds

**Step 4: Commit**

```bash
git add lap-website/src/experience/quality/FallbackShell.tsx lap-website/src/components/chrome/TimingTower.tsx
git commit -m "feat(safety-car): add Safety Car badge in FallbackShell and TimingTower"
```

---

### Task 22: Redesign RadioCard Component

**Files:**
- Create: `lap-website/src/components/ui/RadioCard.tsx`

**Step 1: Write the F1 broadcast card component**

Match the `Design Portfolio.svg` reference: dark card (#231f20), header bar with accent color, quoted message, waveform bars.

```typescript
// lap-website/src/components/ui/RadioCard.tsx
'use client';

import { useState, useMemo } from 'react';

interface RadioCardProps {
  message: string;
  accentColor?: string;
  sender?: string;
  receiver?: string;
  compact?: boolean;
}

/** Generate random waveform bar heights (deterministic per message) */
function generateWaveform(message: string, bars: number): number[] {
  let seed = 0;
  for (let i = 0; i < message.length; i++) {
    seed = ((seed << 5) - seed + message.charCodeAt(i)) | 0;
  }
  const heights: number[] = [];
  for (let i = 0; i < bars; i++) {
    seed = ((seed * 1103515245 + 12345) & 0x7fffffff);
    heights.push(0.2 + (seed % 100) / 125);
  }
  return heights;
}

/**
 * RadioCard — F1 broadcast-style explanation card.
 *
 * Compact mode: single line with accent left border + "RADIO" badge.
 * Expanded mode: full card with header bar, quoted message, waveform bars.
 *
 * Matches Design Portfolio.svg color spec:
 * - Card background: #231f20
 * - Header bar: accent color
 * - Text: white
 */
export function RadioCard({
  message,
  accentColor = '#D946EF',
  sender = 'ENGINEER',
  receiver = 'DRIVER',
  compact: initialCompact = true,
}: RadioCardProps) {
  const [expanded, setExpanded] = useState(!initialCompact);
  const waveform = useMemo(() => generateWaveform(message, 24), [message]);

  if (!expanded) {
    return (
      <button
        onClick={() => setExpanded(true)}
        className="group flex items-center gap-2 py-1.5 px-3 rounded text-left transition-colors hover:bg-white/5"
        style={{ borderLeft: `2px solid ${accentColor}` }}
      >
        <span
          className="font-telemetry text-[9px] tracking-[0.15em] uppercase px-1.5 py-0.5 rounded-sm"
          style={{ backgroundColor: accentColor, color: '#231f20' }}
        >
          RADIO
        </span>
        <span className="text-chalk/70 text-sm truncate">{message}</span>
      </button>
    );
  }

  return (
    <div
      className="rounded-lg overflow-hidden max-w-sm"
      style={{ backgroundColor: '#231f20' }}
    >
      {/* Header bar */}
      <div
        className="flex items-center justify-between px-3 py-1.5"
        style={{ backgroundColor: accentColor }}
      >
        <span className="font-telemetry text-[10px] tracking-[0.15em] uppercase text-white/90">
          {sender} → {receiver}
        </span>
        <button
          onClick={() => setExpanded(false)}
          className="text-white/60 hover:text-white text-xs"
          aria-label="Collapse radio card"
        >
          ✕
        </button>
      </div>

      {/* Message body */}
      <div className="px-3 py-2.5">
        <p
          className="text-chalk text-sm leading-relaxed"
          style={{ borderLeft: `2px solid ${accentColor}40`, paddingLeft: '10px' }}
        >
          &ldquo;{message}&rdquo;
        </p>

        {/* Waveform bars */}
        <div className="flex items-end gap-[2px] mt-3 h-4">
          {waveform.map((h, i) => (
            <div
              key={i}
              className="flex-1 rounded-sm"
              style={{
                height: `${h * 100}%`,
                backgroundColor: `${accentColor}60`,
              }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
```

**Step 2: Verify build**

Run: `cd lap-website && npx tsc --noEmit`
Expected: 0 errors

**Step 3: Commit**

```bash
git add lap-website/src/components/ui/RadioCard.tsx
git commit -m "feat(radio-card): add F1 broadcast-style RadioCard matching SVG reference"
```

---

### Task 23: Replace SVG PitWheel with 3D Tire

**Files:**
- Modify: `lap-website/src/components/chrome/PitWheel.tsx`

**Step 1: Replace SVG with a reference to the 3D tire in the scene**

Rather than embedding a separate R3F canvas in the PitWheel chrome component (which would create a second WebGL context), the 3D tire is already loaded by AssetManager at chapters 8-9. The PitWheel chrome component should enhance the existing scroll-velocity animation to also drive the 3D tire's rotation via the store.

Update the existing PitWheel to set a store value that the AssetManager can read:

Add to store (in the existing `trackPath` state or a new field):

In `PitWheel.tsx`, keep the SVG as a fallback for when 3D assets aren't loaded, but also drive the 3D tire rotation speed via a ref that the AssetManager reads.

The simplest approach: PitWheel already drives its SVG rotation via scroll velocity × velocityMultiplier. The 3D tire in AssetManager already has gentle rotation. We make the tire's rotation speed match the PitWheel's by reading `scrollVelocity * trackPath.velocityMultiplier` in the AssetManager's tire-specific `useFrame`.

**Approach:** Modify `AssetManager.tsx` to give the tire special scroll-driven rotation (not the generic gentle rotation). Keep PitWheel.tsx SVG as-is for the chrome overlay.

In `AssetManager.tsx`, add special handling for the tire asset:

```typescript
// Inside AssetInstance, check if this is the tire:
if (entry.id === 'tire') {
  const { scrollVelocity, trackPath } = useKernelStore.getState();
  const rotSpeed = scrollVelocity * trackPath.velocityMultiplier * 3.0;
  groupRef.rotation.x += rotSpeed * delta;
}
```

**Step 2: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds

**Step 3: Commit**

```bash
git add lap-website/src/experience/renderer/AssetManager.tsx
git commit -m "feat(pit-wheel): add scroll-driven 3D tire rotation with pit limiter"
```

---

### Task 24: Add Finish Line Checkered Marker on Ribbon

**Files:**
- Modify: `lap-website/src/experience/renderer/shaders/track-ribbon.ts`

**Step 1: Add checkered pattern at finish line position**

Add a `uFinishProgress` uniform and checkered pattern in the fragment shader at that position:

```glsl
uniform float uFinishProgress; // 0-1 position of finish line on ribbon (0.95)

// In main():
// Finish line checkered pattern
float finishDist = abs(vProgress - uFinishProgress);
float finishMask = smoothstep(0.01, 0.0, finishDist);
float checkerX = step(0.5, fract(vUv.x * 8.0));
float checkerY = step(0.5, fract(vProgress * 200.0));
float checker = abs(checkerX - checkerY); // XOR pattern
vec3 finishColor = mix(vec3(1.0), vec3(0.0), checker) * finishMask;
```

Add the finish color to the final composition.

**Step 2: Update TrackRibbon.tsx to set uFinishProgress**

Add the uniform to the material and set it to `0.95`.

**Step 3: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds

**Step 4: Commit**

```bash
git add lap-website/src/experience/renderer/shaders/track-ribbon.ts lap-website/src/experience/renderer/TrackRibbon.tsx
git commit -m "feat(ribbon): add checkered finish line marker at progress=0.95"
```

---

### Task 25: Fix Missing #s5-personas Element

**Files:**
- Check: `lap-website/src/experience/rooms/` for the S5 room definition
- Modify: the relevant room file to add `id="s5-personas"`

**Step 1: Find the S5 room and add the missing ID**

Search for the room component that renders the S5 Personas section. Add `id="s5-personas"` to its root element so the timing tower navigation link works.

**Step 2: Verify the element exists**

Run dev server, inspect DOM for `#s5-personas` — should exist.

**Step 3: Commit**

```bash
git add <modified-file>
git commit -m "fix(nav): add missing #s5-personas element for timing tower navigation"
```

---

### Task 26: Write Unit Tests for New Pure Functions

**Files:**
- Create: `lap-website/src/experience/__tests__/store-slices.test.ts`

**Step 1: Write tests for new store slices**

```typescript
import { describe, it, expect, beforeEach } from 'vitest';
import { useKernelStore } from '../state/store';

describe('Background slice', () => {
  beforeEach(() => {
    // Reset store
    useKernelStore.setState({
      background: { cornerYaw: 0, cornerBank: 0, streakIntensity: 0, ribbonProgress: 0 },
    });
  });

  it('setCornerYaw updates yaw', () => {
    useKernelStore.getState().setCornerYaw(3.5);
    expect(useKernelStore.getState().background.cornerYaw).toBe(3.5);
  });

  it('setStreakIntensity clamps to 0-1', () => {
    useKernelStore.getState().setStreakIntensity(1.5);
    expect(useKernelStore.getState().background.streakIntensity).toBe(1);
    useKernelStore.getState().setStreakIntensity(-0.5);
    expect(useKernelStore.getState().background.streakIntensity).toBe(0);
  });
});

describe('SafetyCar slice', () => {
  beforeEach(() => {
    useKernelStore.setState({
      safetyCar: { active: false, reason: '', enteredAt: 0 },
    });
  });

  it('enterSafetyCar sets active + reason', () => {
    useKernelStore.getState().enterSafetyCar('low-fps');
    const sc = useKernelStore.getState().safetyCar;
    expect(sc.active).toBe(true);
    expect(sc.reason).toBe('low-fps');
    expect(sc.enteredAt).toBeGreaterThan(0);
  });

  it('exitSafetyCar clears state', () => {
    useKernelStore.getState().enterSafetyCar('test');
    useKernelStore.getState().exitSafetyCar();
    const sc = useKernelStore.getState().safetyCar;
    expect(sc.active).toBe(false);
    expect(sc.reason).toBe('');
  });
});

describe('Asset slice', () => {
  it('setAssetLoaded tracks individual assets', () => {
    useKernelStore.getState().setAssetLoaded('helmet', true);
    expect(useKernelStore.getState().assets.loaded['helmet']).toBe(true);
    expect(useKernelStore.getState().assets.loaded['tire']).toBeUndefined();
  });
});
```

**Step 2: Run tests**

Run: `cd lap-website && npx vitest run src/experience/__tests__/store-slices.test.ts`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add lap-website/src/experience/__tests__/store-slices.test.ts
git commit -m "test(store): add unit tests for background, safetyCar, asset slices"
```

---

### Task 27: Full Build + Lint + Test Verification

**Files:**
- None (verification only)

**Step 1: Run lint**

Run: `cd lap-website && npm run lint`
Expected: 0 errors

**Step 2: Run all tests**

Run: `cd lap-website && npm run test`
Expected: All tests pass (original 90+ plus new ones)

**Step 3: Run build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds

**Step 4: Commit any fixes**

If lint/test/build reveals issues, fix them and commit.

---

### Task 28: Visual QA — Full Integration

**Files:**
- None (verification only)

**Step 1: Full scroll-through on desktop**

Run dev server and do a complete slow scroll from top to bottom. Verify:

1. **Start Grid**: track ribbon visible, helmet floating nearby, reveal shows track map blueprint
2. **S1 Pain**: corner feel — subtle yaw right, particles drift laterally
3. **S1 Deep**: continued corner, track ribbon turning
4. **S2 Pipeline**: straight — calm, readability high, reveal switches to telemetry overlay
5. **S2 Proof**: straight, telemetry traces visible in reveal
6. **S3 Product**: corner left, halo asset visible
7. **S4 Workflows**: straight, steering wheel asset
8. **S5 Personas**: corner right, `#s5-personas` element exists
9. **Pit Stop**: pit limiter active, 3D tire rotates with scroll, reveal disabled
10. **Garage**: straight, calm
11. **Podium**: finish line checkered marker, timing tower all purple, delta settled

2. **DRS moments**: when sector gate triggers DRS, reveal brush radius increases visibly
3. **Reduced motion**: everything degrades gracefully, grain + ribbon outline preserved
4. **Console**: 0 errors, ≤ 2 warnings
5. **Performance**: 55+ fps on desktop high tier

**Step 2: Mobile viewport test**

Resize to 375×812:
- Quality drops to balanced
- 3D assets hidden (low tier) or simplified
- Touch burst reveal works
- Pit wheel SVG fallback visible (if assets not loaded)
- All text readable

**Step 3: Take screenshots for comparison**

Before vs after screenshots at 5 scroll positions.

---

### Task 29: Deploy to Cloudflare

**Files:**
- None (deployment only)

**Step 1: Push to remote**

Run: `git push origin main`

**Step 2: Deploy to Cloudflare**

Run: `cd lap-website && npm run cf:deploy`
Expected: Deployment succeeds

**Step 3: Verify live site**

Open https://www.lap-coach.racing/ and repeat the quick visual QA from Task 28 Step 1.

---

## Post-Prototype Tasks (Polish)

These are optional follow-up tasks to be done after all 3 prototypes pass QA.

### Task 30: Remove Dead Code

- Delete `lap-website/src/experience/renderer/SceneManager.tsx` (no longer imported)
- Delete `lap-website/src/experience/transitions/TransitionCompositor.tsx` (replaced by CSS transitions)
- Delete transition shader files if not used
- Verify no dangling imports

### Task 31: Update Memory + Documentation

- Update `MEMORY.md` with new architecture notes
- Update design doc status from "pending approval" to "implemented"

---

## Summary

| Prototype | Tasks | Key Deliverables |
|-----------|-------|-----------------|
| Pre-req | 0 | 5 optimized GLBs in public/models/ |
| P1: Track Ribbon | 1-11 | PersistentScene, Atmosphere, TrackRibbon, corner-feel, legacy cleanup |
| P2: Reveal + Assets | 12-19 | Mask FBO exposure, truth layers, RevealBlendMesh, AssetManager |
| P3: Safety + Polish | 20-29 | SafetyCarMode, RadioCard, 3D tire rotation, finish line, bug fixes, deploy |
| Post | 30-31 | Dead code removal, documentation |

**Total: 32 tasks (~80-100 bite-sized steps when counting sub-steps)**

Each prototype is independently deployable and testable. If a prototype fails QA, the previous prototype's work still functions correctly.
