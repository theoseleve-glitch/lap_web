# Experience Layer Hardening — Lando-Level Immersion

**Date**: 2026-02-27
**Status**: Design — pending approval
**Approach**: B — Renderer Rewrite with single persistent scene
**Scope**: Rewrite renderer/visual pipeline + 3D asset integration. Keep orchestrator/state/narrative logic.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Phase 0 — Evidence Pack](#2-phase-0--evidence-pack)
3. [Rewrite Scope Boundary](#3-rewrite-scope-boundary)
4. [Architecture — Single Persistent Scene](#4-architecture--single-persistent-scene)
5. [Narrative System — Track Ribbon](#5-narrative-system--track-ribbon)
6. [Experience Features](#6-experience-features)
7. [Orchestrator Contract Extension](#7-orchestrator-contract-extension)
8. [3D Asset Pipeline](#8-3d-asset-pipeline)
9. [Parameter Tables & Budgets](#9-parameter-tables--budgets)
10. [Prototype Plan](#10-prototype-plan)
11. [Risk Register & Fallbacks](#11-risk-register--fallbacks)
12. [Traceability Matrix](#12-traceability-matrix)

---

## 1. Executive Summary

### Mission

Complete + harden the V2 experience layer so lap-coach.racing reaches Lando-level immersion: liquid cursor reveal, living track-ribbon background with corner-feel, integrated 3D assets, and premium visual quality throughout.

### What Exists (V2 baseline — live, feature-flagged ON)

- Zustand KernelStore orchestrator with 11-chapter progression, HUD state, DRS, reveal, track path
- R3F canvas with per-chapter SceneManager, LivingSurface (5 procedural layers), RevealMaskPipeline (FBO ping-pong)
- 14 HUD chrome components (TimingTower, DeltaHud, MiniTrackMap, DrsLabel, SectorGateSweep, FinishLine, PitWheel, etc.)
- Narrative controllers (SectorGateController, DrsController, DeltaTickController)
- Quality manager with adaptive tier detection + FPS monitoring
- 90 tests passing, clean build, 0 lint errors

### What's Wrong (Visual Quality Gaps)

1. **Background is generic** — procedural contour lines + grain look "templated". No track shape visible.
2. **Reveal is invisible** — RevealMaskPipeline runs but RevealBlendMesh is unmounted. User sees nothing.
3. **No 3D assets** — 5 web-ready GLBs in `/3d_assets` are unused. PitWheel is a flat SVG.
4. **No corner-feel** — scrolling through corners vs straights feels identical.
5. **RadioCard doesn't match SVG** — current design is a simple accordion, not the F1 broadcast card.
6. **Scene thrashing** — per-chapter mount/unmount causes GPU resource churn.

### Signature Moments (Unchanged from V1 Design)

1. **Telemetry Truth Reveal** — Cursor mask reveals hidden track map (hero) and telemetry overlays (sections)
2. **Turn-Feel Background** — Track ribbon in background; corners induce yaw + lateral drift
3. **Timing Tower + Sector Gates** — Purple completion sweep
4. **DRS OPEN** — Functional boost (reveal radius + streak intensity)
5. **Pit Limiter** — Pricing section dampens velocity response
6. **Finish Line Crossing** — Podium CTA with finalized timing tower

### Success Metrics

| Metric | Target |
|--------|--------|
| Desktop FPS (high tier) | ≥ 55 fps sustained |
| Mobile FPS (balanced tier) | ≥ 30 fps sustained |
| LCP regression | < 200ms |
| Background reads as "track" | 7/10 testers identify track shape |
| Reveal felt as "liquid" | 8/10 testers describe trail/persistence |
| Corner-feel detected | 6/10 testers mention direction change |
| CTA click-through | No regression |
| 3D assets visible and tasteful | All 5 placed, none distracting |

---

## 2. Phase 0 — Evidence Pack

### 2.1 Current-State Interaction Inventory

| # | Interaction | Section | Trigger | Feedback | Duration | Purpose |
|---|------------|---------|---------|----------|----------|---------|
| 1 | Hold-to-start | Start Grid | pointerDown 2s | 5 lights fill + white flash | 2120ms | Race start ritual |
| 2 | Skip to scroll | Start Grid | Scroll 220px | Same as hold complete | Immediate | Impatient escape |
| 3 | Corner drag | S1 Pain | Drag control points | Bezier + delta update | Continuous | Racing line tactile |
| 4 | Trace hover | S1 Deep | mouseMove zones | Opacity + lineWidth | 420ms | Channel exploration |
| 5 | Pipeline scroll | S2 Pipeline | Scroll in 200vh sticky | Block heights fill | Continuous | Pipeline viz |
| 6 | Flip cards (Placard) | Scrutineering | Click REVEAL | rotateY(180°) | 900ms | Progressive disclosure |
| 7 | Flip cards (Reversible) | S1 Deep | Click | rotateY(180°) | 620ms | Feature reveal |
| 8 | B2C/B2B toggle | S3 Product | Click toggle | Opacity crossfade | 420ms | Audience pivot |
| 9 | Report scrubber | S3 Product | Range drag | Screenshot crossfade | Continuous | Product preview |
| 10 | Pricing toggles | Pit Stop | Click billing/audience | Knob animation | 420ms | Plan selection |
| 11 | FAQ accordion | Pit Stop | Click / keyboard | Grid row expand | 420ms | Info reveal |
| 12 | Garage accordion | Garage | Click | Grid row + rotate | 420ms | Technical details |
| 13 | Pointer magnetism | Global | Passive RAF | Cursor deflects to interactive | Continuous | Affordance |
| 14 | Custom cursor | Global | mousemove | 8px→24px + glow | Continuous | Brand presence |

### 2.2 Visual Quality Diagnosis (from live audit)

**Background issues:**
- Contour lines are procedural rings — no relation to a track shape
- Grain is flat uniform noise — no depth variation
- Particles are randomly placed dots — no flow direction
- No visible response when scrolling through corner chapters vs straight chapters
- Speed streaks exist but only on "high" quality tier — most users won't see them

**HUD issues:**
- Mini track map is 50×50px — too small to register
- DRS label position is off-screen on many viewports
- Flip card borders nearly invisible (dark on dark)

**Missing features:**
- Reveal effect: mask pipeline runs → output not composited → user sees nothing
- No 3D assets loaded anywhere
- RadioCard is generic accordion, not F1 broadcast card
- No Safety Car Mode fallback

### 2.3 Console Issues (Live)

| Issue | Severity | Root Cause |
|-------|----------|------------|
| `readPixels INVALID_OPERATION` (1 probe) | Low | HalfFloat FBO readback not supported; detection fires once then disables |
| `THREE.Clock deprecated` | Low | Three.js internal; migrate to Timer in rewrite |
| 404 for /product, /contact, /privacy, /terms, /dpa chunks | High | Stale Cloudflare deployment; chunk hashes mismatch |
| `#s5-personas` element not found | Medium | S5 section nav target missing from DOM |

### 2.4 Reference Deconstruction (Lando Primitives)

| Primitive | Lando Behavior | Lap Coach Translation |
|-----------|---------------|----------------------|
| Continuous input-driven reveal | Mouse movement reveals helmet image under clean surface via persistent mask | Mouse reveals track map (hero) / telemetry overlays (sections) via FBO mask |
| Mode switching | Scroll locked during helmet interaction; unlock to continue | DRIVE mode (scroll) vs CONTROL mode (drag interactions) |
| Living depth background | Multi-layer parallax with subtle grain + blur depth | Track ribbon + 5 atmosphere layers + corner-feel physics |
| Composited transitions | Smooth scene blends on section change | CSS DOM transitions + WebGL crossfade background shift |
| Authored kinetic HUD | None (Lando doesn't have HUD) | TimingTower + DeltaHud + MiniTrackMap + DrsLabel (our unique addition) |

---

## 3. Rewrite Scope Boundary

### KEEP (proven, well-tested)

| System | Files | Reason |
|--------|-------|--------|
| KernelStore | `experience/state/store.ts`, `types.ts`, `chapters.ts` | State shape is solid; extend for new systems |
| Tokens | `lib/tokens.ts` | Colors, timing, easing are finalized |
| Feature flags | `lib/feature-flags.ts` | Gating mechanism stays |
| Narrative controllers | `narrative/SectorGateController.tsx`, `DrsController.tsx`, `DeltaTickController.tsx`, `TrackPath.ts` | Pure logic, well-tested |
| Quality manager | `quality/QualityManager.tsx` | Adaptive tier detection works |
| Input system | `input/InputManager.tsx`, `PointerField.tsx`, `ScrollController.tsx` | Foundations are sound |
| DOM rooms | `rooms/*.tsx` | Content stays |
| HUD chrome | `chrome/*.tsx` | Keep and polish |
| Motion orchestrator | `motion/MotionOrchestrator.tsx`, `springs.ts` | GSAP + ScrollTrigger wiring |

### REWRITE (renderer + visual pipeline)

| System | Current Files | New Files |
|--------|--------------|-----------|
| Scene management | `renderer/SceneManager.tsx` + 9 scene files | `renderer/PersistentScene.tsx` (single scene) |
| Background | `renderer/scenes/LivingSurface.tsx` + shaders | `renderer/TrackRibbon.tsx` + `renderer/Atmosphere.tsx` + new shaders |
| Reveal compositing | `reveal/RevealBlendMesh.tsx` (scaffolded, unmounted) | `reveal/RevealBlendMesh.tsx` (rewritten, mounted) + truth layer rendering |
| Post-processing | `renderer/PostStack.tsx` | `renderer/PostPipeline.tsx` (unified) |
| Transitions | `transitions/TransitionCompositor.tsx` + shaders | Simplify to CSS+WebGL crossfade; remove FBO capture |

### NEW (doesn't exist)

| System | Files |
|--------|-------|
| Track ribbon geometry | `renderer/TrackRibbonGeometry.ts` |
| 3D asset manager | `renderer/AssetManager.tsx` |
| Truth layer authoring | `reveal/TruthLayerTrackMap.tsx`, `reveal/TruthLayerTelemetry.tsx` |
| Safety Car fallback | `quality/SafetyCarMode.tsx` |
| RadioCard redesign | `components/ui/RadioCard.tsx` (full rewrite to match SVG) |
| Optimized GLBs | `public/models/*.glb` (5 Draco-compressed files) |

---

## 4. Architecture — Single Persistent Scene

### Scene Graph

```
<Canvas>
  <PersistentScene>
    ├── <Atmosphere>                    // L1-L5 background layers
    │   ├── GrainQuad                   // L1: film grain (always)
    │   ├── TrackRibbon                 // L2: procedural spline mesh
    │   ├── ParticleField               // L3: velocity-reactive drift
    │   ├── SpeedStreaks                 // L4: scroll-velocity accents
    │   └── VignetteQuad                // L5: readability shield
    │
    ├── <AssetManager>                  // 3D GLBs placed along track
    │   ├── HelmetAsset (progress=0.0)
    │   ├── HaloAsset (progress=0.45)
    │   ├── SteeringWheelAsset (progress=0.55)
    │   ├── PitWallAsset (progress=0.75)
    │   └── TireAsset (progress=0.78)
    │
    ├── <RevealMaskPipeline />          // FBO ping-pong (existing, kept)
    ├── <RevealBlendMesh />             // Composites mask (rewritten, mounted)
    └── <PostPipeline />                // Grain → vignette → color grade
  </PersistentScene>
</Canvas>
```

### Camera System

The camera is an orthographic camera positioned above the track ribbon. On scroll:
- Camera position advances along the spline (driven by `globalProgress`)
- On corner chapters: camera yaws toward apex (±2-4°) and banks slightly (±1-2°)
- On straight chapters: camera returns to neutral
- Transition between corner/straight: lerp with `background.cornerLerp` damping

### Track Ribbon Geometry

Generated from `TrackPath.ts` chapter headings:

```typescript
// Pseudocode for TrackRibbonGeometry
function buildTrackRibbon(chapters: ChapterPath[]): BufferGeometry {
  const points: Vector3[] = [];
  let x = 0, z = 0;

  for (const chapter of chapters) {
    const segmentLength = chapter.weight * TOTAL_LENGTH;
    const heading = chapter.heading * DEG2RAD;
    const steps = Math.ceil(segmentLength / STEP_SIZE);

    for (let i = 0; i < steps; i++) {
      x += Math.sin(heading) * STEP_SIZE;
      z += Math.cos(heading) * STEP_SIZE;
      points.push(new Vector3(x, 0, z));
    }
  }

  // Extrude ribbon width + catmull-rom smoothing
  return extrudeRibbon(new CatmullRomCurve3(points), RIBBON_WIDTH);
}
```

The ribbon is rendered with:
- Base: very dark emissive material (barely visible, just perceptible)
- Edges: thin bright emissive lines (the "track outline" look)
- Sector segments: colored by accent color on completion (purple for completed sectors)
- Progress indicator: brighter emission ahead of current position, fading behind

---

## 5. Narrative System — Track Ribbon

### Story Beat Map

| Chapter | Progress | Track Type | Corner Feel | Assets | Reveal Layer |
|---------|----------|-----------|-------------|--------|-------------|
| 0: Start Grid | 0.00-0.09 | straight | None — entry | Helmet (floating) | Track map overlay |
| 1: S1 Pain | 0.09-0.18 | corner-r (15°) | Yaw +2°, drift right | — | Track map overlay |
| 2: S1 Deep | 0.18-0.27 | corner-r (45°) | Yaw +4°, bank +1° | — | Track map overlay |
| 3: S2 Pipeline | 0.27-0.36 | straight (90°) | Calm, high readability | — | Telemetry overlay |
| 4: S2 Proof | 0.36-0.45 | straight (120°) | Calm | — | Telemetry overlay |
| 5: S3 Product | 0.45-0.55 | corner-l (150°) | Yaw -3°, drift left | Halo | Telemetry overlay |
| 6: S4 Workflow | 0.55-0.64 | straight (180°) | Calm | Steering Wheel | Telemetry overlay |
| 7: S5 Personas | 0.64-0.73 | corner-r (225°) | Yaw +2° | — | Telemetry overlay |
| 8: Pit Stop | 0.73-0.82 | pit-lane | Pit limiter active | Pit Wall + Tire | None (pit mode) |
| 9: Garage | 0.82-0.91 | straight (315°) | Calm | — | Telemetry overlay |
| 10: Podium | 0.91-1.00 | straight (350°) | Finish line crossing | — | None (celebration) |

### Mode Switching

| Mode | Trigger | Behavior |
|------|---------|----------|
| DRIVE | Default | Scroll drives progress; pointer is steering influence |
| CONTROL | CornerDrag, ReportScrubber | Damp scroll response; pointer is primary control; background calms |
| PIT | Enter chapter 8 | Velocity capped; pit limiter active; wheel rotation damped |

---

## 6. Experience Features

### 6.1 Track Layout Background

The track ribbon is the primary background geometry. It replaces the procedural contour lines.

**Visual treatment:**
- Dark asphalt base (#0B0C0F) with very subtle noise
- Track ribbon edges glow with a thin emissive line (chalk color, 0.08 opacity)
- Completed sector segments pulse with racing purple at low intensity
- Forward progress glow: 20% brighter ahead, 80% dimmer behind
- Vignette/halo intensifies behind text (readability shield)

**Anti-pattern prevention:**
- No tiling: ribbon is a single continuous mesh, no repeating textures
- No banding: use half-float precision for gradients, dither if needed
- No noise scale issues: grain shader uses screen-space UVs, not world-space
- No aliasing: MSAA 4x on high tier, FXAA on balanced

### 6.2 Liquid Cursor Reveal (Completed Pipeline)

**Existing (keep):** RevealMaskPipeline — stamp → decay → blur. Works correctly.

**New (rewrite):**
- **RevealBlendMesh** — mounted in scene at renderOrder 998. Receives `maskFboB.texture` via ref.
- **Truth layer switching** — two pre-rendered FBO textures:
  - `TruthLayerTrackMap`: renders track ribbon in "blueprint" mode (bright lines, sector colors, apex markers, braking zones)
  - `TruthLayerTelemetry`: renders data overlay (trace waveforms, delta numbers, grid lines, timing data)
- Hero (chapters 0-2): track map truth layer
- Sections (chapters 3-9): telemetry truth layer
- Pit + Podium: reveal disabled (pit mode / celebration)

**Reveal subject details:**

| Subject | Layer A (covered) | Layer B (revealed) | Narrative value |
|---------|------------------|-------------------|-----------------|
| Track Map (hero) | Clean dark surface with faint grain | Track ribbon in bright blueprint style with sector highlights, apex markers, braking zones | "The track is there — you just can't see it yet" |
| Telemetry (sections) | Clean dark surface | Data overlay with traces, deltas, grid, timing labels | "The data is always there — you reveal it" |

### 6.3 Timing Tower

Existing component, polish only:
- Increase mini track map from 50×50px to 80×80px
- Add `aria-label` descriptions for each sector status
- Ensure DRS label is within viewport on all common widths

### 6.4 DRS OPEN Moments

Existing DrsController stays. Functional boost:
- Reveal: brush radius × 1.4 for 2000ms (already implemented in `useRevealState`)
- Background: speed streak spawn threshold reduced by 40% during DRS
- Timing tower: brief glow pulse on DRS trigger

### 6.5 Radio Message Cards (Redesigned)

Match `Design Portfolio.svg`:

```
┌──────────────────────────────────────┐
│ ■ ENGINEER → DRIVER  [accent color]  │  ← header bar
├──────────────────────────────────────┤
│ ┃  "Entry speed is 2.3 km/h too     │  ← quoted message
│ ┃   high. Brake 5m later."          │
│ ┃                                    │
│ ┃  ║║║ ║║║║║ ║║ ║║║║ ║║║ ║║║       │  ← waveform bars
└──────────────────────────────────────┘
```

- Compact whisper: 1 line, accent left border, "RADIO" badge
- Expanded: full card with header bar + accent banner + quoted message + waveform
- Card background: `#231f20` (from SVG)
- Accent colors: per-section from `roomAccents` token

### 6.6 Track Cards (3D/Animated)

Existing TrackCard component stays. Add:
- Sector highlight strip that matches current chapter accent color
- On hover: 3D tilt already works (±8°)
- On click: transition to expanded radio-card debrief

### 6.7 Pit Stop Wheel (3D)

Replace SVG PitWheel with actual `pneu_F1.glb`:
- 3D tire model rendered in R3F scene at pit stop section position
- Rotation driven by scroll velocity (same physics as SVG version)
- Pit limiter caps rotation velocity
- Reduced motion: static tire with subtle ambient rotation

### 6.8 Finish Line + Podium

Existing FinishLine component stays. Add:
- Track ribbon "finish line" marker (checkered pattern at progress=0.95)
- Timing tower finalizes all sectors to purple
- Delta freezes and settles
- Podium CTA framed with subtle celebration particle burst

---

## 7. Orchestrator Contract Extension

### New State Additions (KernelStore)

```typescript
// Add to ExtendedKernelState
background: {
  cornerYaw: number;       // current yaw offset in degrees
  cornerBank: number;      // current bank offset in degrees
  streakIntensity: number; // 0-1, modulated by DRS + velocity
  ribbonProgress: number;  // 0-1, where camera is on ribbon
};

assets: {
  loaded: Record<string, boolean>;  // per-asset load state
  visible: Record<string, boolean>; // per-asset visibility (viewport proximity)
};

safetyCar: {
  active: boolean;
  reason: string;
  enteredAt: number;
};
```

### New Events

| Event | Trigger | Effect |
|-------|---------|--------|
| `safety_car_enter` | FPS < 24 for 3s | Disable canvas, show CSS fallback, badge |
| `safety_car_exit` | FPS > 40 for 5s (after recovery) | Re-enable canvas, remove badge |
| `asset_loaded(id)` | GLB decode complete | Update `assets.loaded[id]` |
| `truth_layer_switch(subject)` | Chapter change crosses threshold | Crossfade reveal truth layer |

---

## 8. 3D Asset Pipeline

### Asset Manifest

| # | Source File | Size | Vertices | Tris | Web Target | Optimization |
|---|------------|------|----------|------|------------|-------------|
| 1 | `F1_Helmet_--_STL.glb` | 3.32 MB | 124,265 | 41,760 | 300 KB | Decimate to 15K tris + Draco |
| 2 | `halo_ferrari.glb` | 966 KB | 37,852 | 13,354 | 200 KB | Draco only |
| 3 | `Ferrari_f1-75_steering_wheel.glb` | 1.16 MB | multi-mesh (11+) | ~8K | 150 KB | Merge meshes + Draco |
| 4 | `Muretto_Box.glb` | 1.27 MB | 49,100 | ~25K | 250 KB | Draco only |
| 5 | `pneu_F1.glb` | 7.52 MB | 273,786 | 109,736 | 400 KB | Decimate to 20K tris + Draco |

**Total compressed: ~1.3 MB** (loaded progressively, not blocking)

### Optimization Pipeline

```bash
# For each asset:
npx gltf-transform dedup <input>.glb <temp>.glb
npx gltf-transform simplify <temp>.glb <temp2>.glb --ratio 0.15  # for heavy assets
npx gltf-transform draco <temp2>.glb <output>.glb
```

### Loading Strategy

- Assets loaded on-demand when within 2 chapters of target position
- `useGLTF.preload()` for assets in the next chapter
- Failed loads degrade gracefully (section renders without 3D asset)
- Total draw calls per visible asset: target ≤ 3 (merge sub-meshes)

---

## 9. Parameter Tables & Budgets

### 9.1 Reveal System

| Parameter | Default | Range | Rationale |
|-----------|---------|-------|-----------|
| Mask resolution (high) | 1024 | 512-1024 | Full FBO per tier |
| Mask resolution (balanced) | 768 | 512-768 | Mobile needs lower |
| Mask resolution (low) | 512 | 256-512 | Minimum useful |
| Brush radius | 80px | 40-160px | Visible but not overwhelming |
| DRS brush multiplier | 1.4× | 1.2-1.6× | Noticeable boost |
| Decay factor (active) | 0.985 | 0.97-0.995 | Trail persistence |
| Decay factor (idle) | 0.95 | 0.90-0.97 | Faster cleanup on idle |
| Blur sigma (high) | 3.0 | 1.0-5.0 | Soft edges |
| Blur passes | 1 (high only) | 0-2 | GPU cost: 1 pass per FBO |
| Inertia time constant | 120ms | 60-200ms | Lag feel |
| Turbulence toggle | ON (high only) | ON/OFF | Premium feel; skip on balanced/low |
| Mobile burst radius | 120px | 80-160px | Larger for finger tap |
| Truth layer crossfade | 600ms | 300-1000ms | Smooth subject switch |

### 9.2 Background + Track Ribbon

| Parameter | Default | Range | Rationale |
|-----------|---------|-------|-----------|
| Track ribbon width | 8 world units | 4-12 | Visible but not overwhelming |
| Ribbon edge emissive | 0.08 opacity | 0.04-0.15 | Perceptible, not glaring |
| Ribbon segment glow (completed) | 0.12 opacity | 0.08-0.20 | Purple sectors visible |
| Corner yaw range | ±2-4° | ±1-6° | Subtle, not nauseating |
| Corner bank range | ±1-2° | ±0.5-3° | Barely perceptible |
| Corner transition lerp | 0.05/frame | 0.02-0.10 | Smooth, not jerky |
| Particle count (high) | 200 | 100-400 | Background density |
| Particle count (balanced) | 100 | 50-200 | Mobile budget |
| Particle count (low) | 0 | 0 | Disabled |
| Particle drift X (corner) | 2.0× base | 1.5-3.0× | Lateral feel |
| Speed streak spawn threshold | 0.3 velocity | 0.1-0.5 | When streaks appear |
| Speed streak lifetime | 180ms | 100-300ms | Brief accent |
| Grain intensity | 0.06 | 0.03-0.10 | Subtle texture |
| Vignette radius | 0.65 | 0.5-0.8 | Text readability shield |
| Vignette shift (corner) | 0.08 | 0.04-0.15 | Corner-apex focus |

### 9.3 HUD System

| Parameter | Default | Range | Rationale |
|-----------|---------|-------|-----------|
| Tower update cadence | On chapter change | — | Not time-based |
| Sector gate sweep duration | 400ms | 200-600ms | power4.out |
| Delta jitter (max) | 8px | 4-12px | Initial uncertainty |
| Delta jitter (settled) | 0px | — | Full reveal = calm |
| Delta jitter mapping | `jitter = 8 × (1 - maskCoverage)` | — | Linear decrease |
| Delta settle damping | 0.92/frame | 0.85-0.96 | Smooth settle |
| DRS label fade-in | 300ms | 200-500ms | Quick appear |
| DRS label fade-out | 200ms | 100-400ms | Slightly faster exit |
| DRS functional duration | 2000ms | 1000-3000ms | Noticeable but not lingering |
| Mini track map size | 80×80px | 60-100px | Increased from 50 |

### 9.4 Motion Grammar

| Token | Value | Easing | Use |
|-------|-------|--------|-----|
| `timing.micro` | 420ms | `--ease-inertia` | Hover states, toggles, small reveals |
| `timing.room` | 900ms | `--ease-overshoot` | Section enter/exit |
| `timing.monument` | 1400ms | `--ease-spring` | Headline reveals |
| `timing.sectorGate` | 400ms | `power4.out` | Sector sweep |
| `timing.drs` | 2000ms | `--ease-anticipate` | DRS active window |
| `timing.pit` | 600ms | `--ease-snap` | Pit enter/exit |
| `timing.finish` | 600ms | `power2.inOut` | Finish line band |
| Hover response | 0ms (instant start) | ease-out | Button/card hover |
| Press response | 50ms | ease-in | Active state |
| Corner yaw lerp | 50ms/frame | linear | Camera corner transition |
| Particle attraction | 20ms radius | quadratic | Pointer proximity |

### 9.5 Performance Budgets

| Tier | Target FPS | Max Frame Time p95 | Max Draw Calls | Max Triangles | Memory Budget |
|------|-----------|-------------------|---------------|--------------|--------------|
| High desktop | 60 fps | 16.6ms | 30 | 100K | 256 MB |
| Balanced desktop | 45 fps | 22ms | 20 | 60K | 192 MB |
| Balanced mobile | 30 fps | 33ms | 12 | 30K | 128 MB |
| Low / fallback | 24 fps | 41ms | 0 (no WebGL) | 0 | 64 MB |

| Asset | Budget | Loaded |
|-------|--------|--------|
| Critical JS (above fold) | < 200 KB gzipped | Initial |
| 3D assets (total) | < 1.5 MB Draco-compressed | Progressive |
| Shader programs | < 15 total | Compile on init |
| FBO render targets | < 6 active | Always |
| Texture memory | < 32 MB | Per quality tier |

---

## 10. Prototype Plan

### Prototype 1: Track Ribbon + Atmosphere + Corner Feel

**Goal:** Replace LivingSurface with the track ribbon background. Prove corner-feel works.

**Scope:**
- `TrackRibbonGeometry.ts` — generate ribbon from TrackPath data
- `Atmosphere.tsx` — new 5-layer system (grain, ribbon, particles, streaks, vignette)
- `PersistentScene.tsx` — single scene with camera following ribbon
- Corner feel: yaw/bank on corner chapters

**Acceptance criteria:**
- Track shape visible in background (not contour lines)
- Corner chapters feel different from straight chapters
- Text remains readable (vignette works)
- FPS meets budget on all tiers
- Reduced motion: static background with grain only (no particles, no yaw)

**Evidence artifacts:**
- Desktop recording (30s scroll-through)
- Mobile recording (30s scroll-through)
- Reduced-motion recording
- FPS trace per tier
- Screenshot comparison: old background vs new

### Prototype 2: Reveal Pipeline + Truth Layers + 3D Assets

**Goal:** Complete the reveal pipeline. Mount RevealBlendMesh with truth layers. Load and place 3D assets.

**Scope:**
- Expose mask FBO texture from RevealMaskPipeline via ref
- Rewrite + mount RevealBlendMesh
- Author TruthLayerTrackMap (track blueprint overlay)
- Author TruthLayerTelemetry (data overlay)
- Optimize 5 GLBs (Draco + decimation)
- AssetManager with progressive loading + placement along ribbon

**Acceptance criteria:**
- Moving cursor reveals truth layer underneath
- Reveal has persistence (trail), decay, blur — feels "liquid"
- Truth layer switches from track map (hero) to telemetry (sections)
- DRS boost visibly increases reveal radius
- 5 3D assets visible at correct sections
- Mobile: finger-drag reveal + tap burst
- Reduced motion: simplified reveal (no trail) still elegant
- Total 3D asset load < 1.5 MB

**Evidence artifacts:**
- Desktop reveal recording (60s with DRS trigger)
- Mobile reveal recording (touch)
- Asset manifest with final sizes
- Draw call trace
- Memory profile

### Prototype 3: RadioCard + Pit Wheel 3D + Finish Line + Safety Car

**Goal:** Complete remaining features. Full integration test.

**Scope:**
- RadioCard redesign matching Design Portfolio.svg
- Replace SVG PitWheel with 3D tire model
- Finish line checkered marker on ribbon
- Safety Car Mode (automatic fallback)
- Fix: `#s5-personas` missing element
- Fix: stale Cloudflare chunk 404s

**Acceptance criteria:**
- RadioCards match SVG reference design
- 3D tire rotates with scroll velocity in pit stop section
- Pit limiter caps rotation
- Finish line band + timing tower finalization
- Safety Car activates on forced low FPS (throttle CPU test)
- All console errors resolved
- Full page scroll-through with 0 visual bugs

**Evidence artifacts:**
- RadioCard screenshot vs SVG reference
- Pit wheel recording (scroll + idle)
- Finish line recording
- Safety Car activation recording
- Full QA checklist pass
- Performance comparison: before vs after rewrite

---

## 11. Risk Register & Fallbacks

| # | Risk | Trigger | Impact | Likelihood | Mitigation | Fallback |
|---|------|---------|--------|-----------|------------|----------|
| R1 | Track ribbon looks "video game" | Too bright, too detailed | Readability, aesthetic | Medium | Intensity caps; edge-only glow; test with users | Reduce to faint outline (0.04 opacity) |
| R2 | Corner yaw causes nausea | Yaw > 4° or too fast | UX, accessibility | Low | Cap at 4°; lerp over 500ms; disable in reduced motion | Disable yaw entirely; corner feel via particles only |
| R3 | Reveal feels like circular spotlight | No persistence, hard edges | Premium feel | Medium | Ensure decay + blur + inertia all active; test continuously | Increase blur sigma; add advection noise |
| R4 | 3D assets too heavy | Load time > 3s on mobile | Performance, bounce rate | Medium | Progressive loading; Draco compression; skip on low tier | Don't load on balanced/low; show section without 3D |
| R5 | Reveal truth layer looks cheap | Flat colors, no detail | Premium feel | Medium | Author detailed FBO textures; iterate on visual quality | Simplify to tinted overlay (single color + opacity) |
| R6 | FPS drops below 24 on mobile | Complex scene + particles + reveal | Performance | High | Safety Car Mode auto-activates; reduce quality tier | CSS-only fallback (static gradient + noise texture) |
| R7 | WebGL not available | Old browser, disabled GPU | Functionality | Low | FallbackShell already exists | CSS-only site with no experience layer (still readable) |
| R8 | RadioCard redesign breaks layout | Complex CSS for broadcast card | Layout regression | Low | Test across viewports before merge | Keep current simple accordion |
| R9 | Stale chunk 404s persist | Cloudflare cache inconsistency | Navigation broken | High | Full cache purge + revalidation after deploy | Add `cache-control: no-cache` headers for HTML |
| R10 | readPixels spam returns | New browsers change behavior | Console noise | Low | Detection already in place (fires once) | Silent catch; coverage stays at default |
| R11 | Reduced motion feels degraded | Too many effects disabled | Accessibility, premium | Medium | Design reduced motion explicitly (static grain + ribbon outline + instant reveals) | Test with reduced motion users |
| R12 | 3D tire clashes with pricing UI | Z-index or overlap issues | Readability | Medium | Place tire behind pricing cards (z-order); opacity cap | Fall back to SVG PitWheel |

### Safety Car Mode

| Condition | Action |
|-----------|--------|
| FPS < 24 for 3+ seconds | Enter Safety Car: disable canvas; CSS fallback; badge in tower |
| FPS < 30 for 5+ seconds | Reduce quality tier by one step |
| FPS > 40 for 5+ seconds (after Safety Car) | Attempt recovery: re-enable canvas at lower tier |
| WebGL context lost | Enter Safety Car permanently until page refresh |

### Reduced Motion Behavior (All Features)

| Feature | Full Motion | Reduced Motion |
|---------|------------|----------------|
| Track ribbon | Animated glow, camera yaw/bank | Static outline, no camera motion |
| Particles | Velocity-reactive drift | Disabled |
| Speed streaks | Scroll-driven accents | Disabled |
| Grain | Animated | Static (frozen frame) |
| Reveal | Persistent trail, decay, blur | Instant reveal (no trail), still premium |
| Sector gate sweep | GSAP scaleX animation | Instant flash (already implemented) |
| Finish line | GSAP sweep animation | Instant show (already implemented) |
| DRS label | Opacity transition | Instant show/hide |
| 3D assets | Subtle rotation/float | Static pose |
| Corner feel | Yaw + bank + drift | None |
| PitWheel/Tire | Scroll-driven rotation | Static |
| Delta jitter | RAF sine/cosine | None (settled) |

---

## 12. Traceability Matrix

| # | Requirement | Design Decision | QA Proof |
|---|------------|----------------|----------|
| T1 | Track layout used in background, supports corner/straight feel | TrackRibbonGeometry from TrackPath data; corner yaw/bank in camera; particle drift amplified on corners | Record scroll-through; visible track shape; measurable yaw in corner sections |
| T2 | Timing tower exists; sectors turn racing purple on completion | Existing TimingTower + SectorGateController; completeSector → purple color | Screenshot tower before/after sector gate; purple visible |
| T3 | DRS OPEN is functional | DrsController × 1.4 brush multiplier + streak threshold reduction | Record DRS moment; measure reveal radius increase; streak spawn change |
| T4 | Liquid reveal is not a circular spotlight | FBO mask with decay + blur + inertia; organic trail shape | Record cursor movement; trail visible; edges soft; not circular |
| T5 | Background never looks cheap (no tiling/banding) | Single continuous ribbon mesh; half-float precision; screen-space grain; no repeating textures | Screenshot at 5 scroll positions; no visible tiling; no banding artifacts |
| T6 | Critical CTAs remain DOM and readable | All CTAs in DOM layer (z-10); WebGL canvas at z-0 with pointer-events-none; vignette behind text | Screenshot CTA regions; contrast ratio ≥ 4.5:1; click test |
| T7 | Reduced motion remains premium | Explicit reduced-motion design for every feature (see table above); grain + ribbon outline preserved | Record reduced-motion scroll-through; qualitative review; not degraded |
| T8 | No material perf regression | FPS budgets per tier; Safety Car fallback; progressive loading | Lighthouse before/after; FPS traces per tier; LCP comparison |
| T9 | Reveal truth layer tied to track | TruthLayerTrackMap renders ribbon in blueprint mode with sectors/apex | Screenshot reveal in hero; track elements visible in truth layer |
| T10 | 3D assets integrated (all 5) | AssetManager loads Draco-compressed GLBs; placed along ribbon | Screenshot each asset in its section; total load < 1.5 MB |
| T11 | RadioCard matches Design Portfolio.svg | Full redesign with header bar, accent banner, quoted message, waveform | Side-by-side comparison with SVG reference |
| T12 | 3D tire replaces SVG in pit stop | pneu_F1.glb decimated + Draco; scroll-driven rotation; pit limiter | Record pit section scroll; tire rotates; caps on idle |
| T13 | Finish line crossing moment | Checkered marker on ribbon at progress=0.95; tower finalization | Record reaching end; finish band visible; tower all purple |
| T14 | Safety Car Mode works | FPS monitor → canvas disable → CSS fallback → badge | Throttle CPU; verify fallback activates; verify readable |
| T15 | Mini track map progress correct | MiniTrackMap reads globalProgress; dot position matches scroll | Record full scroll; dot starts at 0, ends at 1.0 |
| T16 | Delta responds to reveal + settles | DeltaTickController maps maskCoverage → jitter; settles on idle | Record reveal interaction; jitter reduces; idle = settled |
| T17 | No console errors in production | Fix #s5-personas, stale chunks, deprecation warnings | Console screenshot after full scroll; 0 errors |
| T18 | 3D assets ≤ 1.5 MB total compressed | Draco + decimation pipeline | `ls -la` optimized GLBs; total ≤ 1.5 MB |
| T19 | Draw calls within budget | Merge sub-meshes; ≤ 3 calls per asset | Spector.js trace; total draw calls ≤ 30 (high tier) |
| T20 | Dual reveal: track map hero + telemetry sections | TruthLayerTrackMap for ch0-2; TruthLayerTelemetry for ch3-9 | Record cursor in hero vs section; different content revealed |
