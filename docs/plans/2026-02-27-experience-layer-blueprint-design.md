# Experience Layer Blueprint — Lando-Level Immersion for Lap Coach

**Date**: 2026-02-27
**Status**: Design — pending approval
**Approach**: Option A — Extend existing R3F architecture
**Scope**: Analysis + blueprint only. No code changes.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Phase 0 — Evidence Pack](#2-phase-0--evidence-pack)
3. [Narrative System](#3-narrative-system)
4. [Experience Spec](#4-experience-spec)
5. [Technical Architecture](#5-technical-architecture)
6. [Orchestrator Contract](#6-orchestrator-contract)
7. [Parameter Tables & Budgets](#7-parameter-tables--budgets)
8. [Prototype Plan](#8-prototype-plan)
9. [Performance & QA Plan](#9-performance--qa-plan)
10. [Risk Register & Fallbacks](#10-risk-register--fallbacks)
11. [Traceability Matrix](#11-traceability-matrix)

---

## 1. Executive Summary

### Mission

Transform lap-coach.racing from a well-structured marketing site with WebGL atmosphere into a **museum-grade motorsport installation** — an experience where the user *drives* the page, revealing telemetry truth through their cursor, feeling corners through the background, and reading their "lap" through a persistent race-broadcast HUD.

### Signature Moments

1. **Telemetry Truth Reveal** — Hero cursor-mask reveals hidden telemetry dashboard (traces, deltas, apex markers) underneath a clean surface. Persistent trail with organic decay. The flagship "wow" moment.
2. **Turn-Feel Background** — Background reacts to scroll path: corners induce lateral drift + yaw, straights calm. The user *feels* the track topology as they scroll through sections.
3. **Timing Tower + Sector Gates** — Persistent compact HUD shows sector progress. Sections turning neon-purple (#D946EF) on completion, with a thin sweep-line "sector gate" moment at each boundary.
4. **DRS OPEN** — Major reveal interactions trigger a "DRS OPEN" label that functionally boosts reveal radius and background intensity for 2 seconds, then decays smoothly.
5. **Pit Limiter** — Pricing section dampens all velocity-driven effects, like entering pit lane. Scroll response becomes controlled and deliberate.
6. **Finish Line Crossing** — Final CTA framed as podium with timing tower finalizing and delta freezing.

### Success Definition

| Metric | Target |
|--------|--------|
| Desktop FPS (high tier) | ≥ 55 fps sustained |
| Mobile FPS (balanced tier) | ≥ 30 fps sustained |
| LCP regression | < 200ms |
| CLS regression | < 0.01 |
| Hero reveal felt as "liquid" | Qualitative: 8/10 testers describe trail/persistence |
| Turn-feel detected | Qualitative: 6/10 testers mention "corners" or "direction" |
| CTA click-through | No regression (A/B test required) |
| Reduced motion | Premium, not degraded (qualitative review) |

---

## 2. Phase 0 — Evidence Pack

### 2.1 Capture Plan

| Tool | Purpose |
|------|---------|
| Chrome DevTools Performance | Frame timing, long tasks, layout thrash |
| Chrome DevTools Layers | Compositing layers, paint regions |
| WebGL Inspector / Spector.js | Draw calls, shader programs, FBO count |
| Lighthouse (desktop + mobile) | LCP, CLS, FID, accessibility, SEO |
| `chrome://gpu` | WebGL tier, driver, feature flags |
| `navigator.hardwareConcurrency` | Core count for adaptive quality |
| `navigator.deviceMemory` | RAM budget |
| Battery API | Low-power mode detection (already implemented) |
| `prefers-reduced-motion` | Media query (already implemented) |
| Network throttle profiles | 3G/4G simulation for asset loading |

**Device tiers:**

| Tier | Representative | Target FPS | Quality |
|------|---------------|------------|---------|
| High desktop | MacBook Pro M2, RTX 3060 | 60 fps | All effects, full particles, high DPR |
| Mid desktop | Intel UHD 620, GTX 1050 | 45 fps | Reduced particles, no advection, balanced DPR |
| Low desktop / tablet | iPad Air 5, Surface Go | 30 fps | Minimal particles, no blur pass, low DPR |
| Mobile (high) | iPhone 15 Pro, Pixel 8 | 30 fps | Balanced preset, touch-optimized reveal |
| Mobile (low) | iPhone SE 3, budget Android | 24 fps | Fallback: CSS-only, no WebGL reveal |

### 2.2 Current-State Interaction Inventory (Lap Coach)

| # | Interaction | Component | Trigger | Feedback | Duration | Easing | State | Purpose |
|---|-------------|-----------|---------|----------|----------|--------|-------|---------|
| 1 | Hold-to-start | `StartLights` | `pointerDown` 2s hold | 5 lights fill sequentially 400ms each; white flash 120ms | 2000ms + 120ms | Linear fill + instant flash | `preloading → idle` | Commitment ritual, race start |
| 2 | Skip to scroll | `StartGrid` | Scroll 220px | Same as hold complete | Immediate on threshold | — | `preloading → idle` | Impatient user escape |
| 3 | Corner drag | `CornerDrag` (Canvas 2D) | `pointerDown` on control point, drag | Bezier updates, delta recalculates | Continuous | `dragFriction: 0.92` | Local state, 3 points | Tactile racing-line interaction |
| 4 | Trace hover | `TelemetryTracesCanvas` | `mouseMove` over invisible DOM zones | Opacity + lineWidth change on hovered trace | 420ms | `--ease-inertia` | Local `hoveredTrace` | Channel exploration |
| 5 | Pipeline blocks (scroll-driven) | `PipelineBlocks` | Scroll in 200vh sticky | Block heights fill progressively | Continuous (scroll-bound) | Linear to scroll | Local `progress` | Pipeline visualization |
| 6 | Flip cards (Placard) | `Placard` | Click "REVEAL" / "CLOSE" | `rotateY(180deg)`, `perspective: 900px` | 900ms | CSS ease | Local `isFlipped` | Progressive disclosure |
| 7 | Flip cards (Reversible) | `ReversibleCard` | Click | `rotateY(180deg)`, `perspective: 900px` | 620ms | CSS ease | Local `flipped` | Feature reveal |
| 8 | B2C/B2B toggle | `ModeSelector` | Click toggle | Opacity crossfade between panels | 420ms | `--ease-inertia` | Local `mode` | Audience pivot |
| 9 | Report scrubber | `ReportScrubber` | `<input type="range">` drag | Screenshot panel crossfade + grayscale filter | Continuous | Linear to input | Local `value` (0-2) | Product preview |
| 10 | Pricing toggles | `PitStop` | Click billing/audience buttons | Toggle knob animates `left` CSS, cards swap | 420ms | CSS ease | Local `billingPeriod`, `audience` | Plan selection |
| 11 | FAQ accordion | `FaqAccordion` | Click, keyboard (arrows) | `gridTemplateRows: 0fr→1fr` | 420ms | CSS ease | Local `openIndex` | Information reveal |
| 12 | Garage accordion | `Garage` | Click | Same + `+` rotates 45° | 420ms | CSS ease | Local `openPanel` | Technical details |
| 13 | Pointer magnetism | `PointerField` | Passive (RAF) | Cursor deflects toward nearest interactive | Continuous | `magnetismStrength: 0.15`, `magnetismDecay: 2.0` | Via `useKernelStore` | Tactile affordance |
| 14 | Custom cursor | `CustomCursor` | `mousemove` | 8px→24px on interactive hover + glow | Continuous | CSS transition 420ms | Via store `pointerX/Y` | Brand presence |
| 15 | Section nav (SectorTabs) | `SectorTabs` | Click | `scrollIntoView({ behavior: 'smooth' })` | Browser-native | Smooth | Via chapter detection | Navigation |
| 16 | Timecode counter | `TimecodeCounter` | Scroll (passive) | `T+ MM:SS.cc` + `D km` based on globalProgress | Continuous | — | Via `useKernelStore` | Lap immersion |
| 17 | Delta strip | `DeltaStrip` | State change from S1Pain drag | Expands 10px→48px, fills from center | CSS transition | — | Via delta value | Delta feedback |
| 18 | Monument text reveal | `MonumentText` | ScrollTrigger enter | `clipPath: inset(0 100% 0 0) → inset(0 0% 0 0)` | 1400ms | `power3.out` | GSAP ScrollTrigger | Headline drama |
| 19 | Scene transitions | `TransitionCompositor` | Chapter change | FBO capture → GLSL shader blend (4 types) | 900ms (`timing.room`) | Per-shader (smoothstep) | `mode: transitioning` | Section ambiance shift |
| 20 | Scrutineering stamp | `ScrutineeringStamp` | ScrollTrigger enter | Scale 1.8→1 | 420ms | `back.out(1.7)` | GSAP dynamic import | Trust proof stamp |
| 21 | Index overlay | `IndexOverlay` | Click "INDEX" nav | Full-screen `backdrop-filter: blur(8px)`, focus trap | 420ms | `--ease-inertia` | Local `isOpen` | Site map |
| 22 | Podium restart | `Podium` | Appears after 3s | `scrollTo(0)` smooth | Browser-native | — | Timer | Lap loop |
| 23 | Post-processing | `PostStack` | Passive | Bloom, Noise, ChromaticAberration (velocity-driven) | Continuous | — | Via store velocity + mode | Cinematic feel |

**Identified issues:**

| Issue | Symptom | Severity |
|-------|---------|----------|
| Telemetry traces static | S1b traces are Canvas 2D with basic hover — not animated waveforms | Medium: misses the "data as sculpture" promise |
| S4/S5 lack visual differentiation | Both are content grids on identical dark backgrounds | Low: functional but flat |
| Pipeline blocks fill feel disconnected | Block heights change but no feedback connects them to the pipeline narrative | Low: works but misses drama |
| Garage section sparse | Nearly empty canvas with 4 accordions on a huge viewport | Low: feels abandoned |
| DeltaStrip visibility | Only activates from S1Pain drag — invisible for 90% of the visit | Medium: HUD element wasted |
| Sound integration partial | `useSound` exists but no room uses `play()` | Low: infrastructure unused |
| No persistent progress feedback | User can't tell how far through the "lap" they are (timecode is not obvious enough) | Medium: missed immersion opportunity |

### 2.3 Reference Deconstruction — landonorris.com

| Primitive | Observable Behavior | Inferred Mechanism (confidence) | Performance Impact |
|-----------|--------------------|---------------------------------|-------------------|
| **Cursor reveal** | Soft-edged radial window reveals face photo under hero; position-only, no trail; snaps back when cursor moves away | Three.js r174 fragment shader: `smoothstep()` radial blend from pointer uniform. Two textures blended by radial mask. No FBO persistence needed because no trail. (HIGH confidence) | Low — single texture lookup + smoothstep per fragment. ~0.1ms/frame |
| **Living background (contours)** | Topographic blob contour lines drift toward cursor, always subtly alive | Three.js geometry or custom shader drawing parametric curves. Pointer position as attractor uniform. Slow lerp update. (MEDIUM confidence) | Low-Medium — depends on contour count. Likely <50 line segments |
| **Background color transitions** | Section changes cause background to dissolve from white to dark-green to lime | `data-gl-change-to`/`data-gl-change-from` attributes read by custom JS. Color lerp in Three.js render loop, not CSS. (HIGH confidence) | Negligible — single uniform lerp |
| **Horizontal scroll section** | 3143px vertical → 4582px horizontal translation | GSAP ScrollTrigger `scrub` on a sticky container. Vertical scroll budget converted to `transform: translateX()`. (HIGH confidence) | Negligible — GPU-composited transform |
| **Visor-wipe reveal** | Ellipse clip-path grows from center-top to fill viewport | CSS `clip-path: ellipse()` animated by GSAP ScrollTrigger. (HIGH confidence) | Low — clip-path is GPU-composited |
| **Helmet card hover** | Image revealed via expanding ellipse + scale de-zoom on hover | CSS `:hover` → `clip-path: ellipse(100% 120% at 50% 0%)` + `transform: scale(1.0)`. Transition 0.75s `cubic-bezier(0.65, 0.05, 0, 1)`. (HIGH confidence) | Negligible |
| **Rive animations (15 canvases)** | Interactive helmets, signature draw, circuit maps, button arrows, hamburger | Rive state machines with hover/scroll triggers. Separate canvas per instance. (HIGH confidence) | Medium cumulative — 15 canvases, but most are small |
| **Page transitions (Taxi.js + Rive)** | Lime-green Rive wipe overlay covers screen during SPA navigation | `data-taxi` SPA router. Rive canvas at z-index 9999 plays state machine on link click. (HIGH confidence) | Medium spike during transition |
| **Text highlight reveals** | Lime/dark-green bar sweeps across text, revealing it line by line | `data-anim-high` + `.high-line-reveal` divs with GSAP `scaleX(1→0)` + stagger on split text. (HIGH confidence) | Negligible |
| **Touch hero lock/unlock** | Mobile: toggle button switches between scroll mode and swipe-reveal mode | `.home-hero-touch-controls-w` visibility toggle. Event listener swap between Lenis scroll and touch-position input to GL. (MEDIUM confidence) | Negligible |

### 2.4 Secondary Reference Primitives

**thei.care:**
- Spring-inertia mouse-tracking on a 3D object — **transferable** for track map geometry
- Character-by-character text reveal with stagger — **transferable** for MonumentText enhancement
- Glow bloom emanating from a central object — **transferable** for scoring arc / delta visualization
- Blur-as-depth layering — **transferable** for visor metaphor if used later

**activetheory.net:**
- Data-reactive tendrils radiating from a central object — **transferable** for telemetry channel visualization (throttle/brake/G as line thickness)
- Audio-tempo cadence (replaced by sector-pacing) — **transferable** for sector gate pulse timing
- Camera fly as navigation — **deferred** (too radical for current structure)

**tamber.music:**
- Drag-mapped parameter (drag distance → audio energy) — **transferable** for reveal radius control
- Audio gate pattern (opt-in before audio) — **transferable** for sector beep / delta sonification
- Rotating ticker for contextual callouts — **transferable** for ambient telemetry data marquee

**boxbox-radio.com:**
- SVG track map as card hero — **transferable** for track cards
- Semantic circuit color grammar (braking/gain/loss) — **transferable** for delta visualization
- DRS zone annotation layer — **transferable** for track map breadcrumb

### 2.5 Gap Map

| Section | Current State | Stays DOM-Only | Gets WebGL Augmentation | Gets New Motion Grammar | Gets Composited Transition |
|---------|--------------|----------------|-------------------------|------------------------|---------------------------|
| **Start Grid (hero)** | Hold-to-start + flash + particles | CTAs, headline text, start button | **REVEAL MASK SYSTEM** (flagship) | Start ritual enhanced with sector-gate entry | Preloader-unlock (existing) + reveal mask entry |
| **S1 Pain (corner drag)** | Canvas 2D drag + flip card | Drag canvas, flip card, text | Particle enhancement in drag zone | Sector 1 gate on entry | crossfade-blur (existing) |
| **S1 Deep (traces)** | Static Canvas 2D traces + hover | Trace labels, hover zones | **Animated trace waveforms** (R3F tubes or enhanced Canvas 2D) | Trace hover → glow pulse | crossfade-blur (existing) |
| **S2 Pipeline** | Sticky scroll blocks | Block labels, flip card | Speed streak accents during pipeline fill | Block fill → momentum ease | mask-wipe (existing) |
| **S2 Proof (scrutineering)** | Flip cards + stamp | Card content, stamps | Stamp impact particle burst | Stamp slam → camera shake | crossfade-blur (existing) |
| **S3 Product** | B2C/B2B toggle + scrubber | All (product content is sacred) | Subtle background shift on toggle | Mode toggle → crossfade with blur | mask-wipe (existing) |
| **S4 Workflows** | Feature grid + status pills | All cards, pills, content | **Track Cards (3D tilt/parallax)** | Card hover → magnetic float | velocity-warp (existing) |
| **S5 Personas** | Persona grid + CTAs | Card content, CTAs | **Track Cards** + accent shift | Card focus → zoom-in | velocity-warp (existing) |
| **Pit Stop (pricing)** | Toggles + cards + FAQ | All pricing content, CTAs | **Pit limiter** (velocity damping) + wheel rotation | Pricing hover → compound color shift | mask-wipe (existing) |
| **Garage** | Sparse accordions | All | Minimal (grid lines only) | Accordion open → data-drawer slide | crossfade-blur (existing) |
| **Podium** | Final CTA + restart | CTA buttons, text | **Finish-line band** + tower finalize | Delta freeze + checkered pattern | refraction (existing) |

**Persistent overlays (NEW):**

| Component | Layer | Purpose |
|-----------|-------|---------|
| Timing Tower | DOM overlay (positioned by orchestrator) | Sector progress, purple completion |
| Delta HUD | DOM overlay | Interaction-quality feedback |
| Mini Track Map | DOM overlay (SVG) | Scroll progress breadcrumb |
| DRS OPEN label | DOM overlay (animated) | Boost moment indicator |
| Radio Message Cards | DOM overlay | Diegetic tooltips |

**Risk mitigations for gap items:**

| Risk | Impact | Mitigation |
|------|--------|------------|
| Reveal mask tanks FPS on mid/low GPUs | Performance, conversion | Adaptive mask resolution; fallback to Lando-simple radial; ultimate fallback: CSS filter |
| Turn-feel too subtle to notice | Wasted dev effort | Prototype early, user-test "do you feel corners?" before full build |
| HUD elements distract from CTAs | Conversion regression | HUD is minimal + positioned in margins; A/B test with/without |
| Track Cards add weight to S4/S5 | Performance | Lazy-mount only when section visible; shared geometry |
| Pit limiter feels "broken" | User confusion | Clear "PIT LANE" label; speed resumes on exit |
| DRS OPEN unclear to non-F1 fans | Comprehension | Functional only (radius boost), label is flavor text; works without understanding |

---

## 3. Narrative System

### 3.1 Story Beat Map — "The Website Is a Lap"

```
START GRID (chapter 0) ─── "Every Lap Has a Secret"
│  Lights out ritual. Cursor reveals telemetry truth.
│  The user is on the grid. They must commit (hold) to start.
│  SECTOR GATE → S1 ENTRY
│
├── SECTOR 1 (chapters 1-2) ─── "Where Time Is Lost"
│   │  S1a: Corner drag — feel the racing line
│   │  S1b: Telemetry traces — see the data shape
│   │  DRS OPEN on first flip-card reveal
│   │  SECTOR GATE → S2 ENTRY (Timing Tower: S1 turns purple)
│   │
├── SECTOR 2 (chapters 3-4) ─── "How It Works"
│   │  S2a: Pipeline — watch the engine process
│   │  S2b: Scrutineering — verify the proof
│   │  DRS OPEN on pipeline completion
│   │  SECTOR GATE → S3 ENTRY (Timing Tower: S2 turns purple)
│   │
├── SECTOR 3 (chapters 5-7) ─── "What You Get"
│   │  S3: Product preview — scrub the outcomes
│   │  S4: Workflow coverage — explore the modules (Track Cards)
│   │  S5: Persona pages — find your path (Track Cards)
│   │  DRS OPEN on persona card expand
│   │  SECTOR GATE → PIT ENTRY (Timing Tower: S3 turns purple)
│   │
├── PIT STOP (chapter 8) ─── "Service Window"
│   │  Pit limiter engages: velocity-driven effects damped
│   │  Wheel rotation synced to scroll
│   │  Pricing decision point
│   │  Timing Tower: PIT illuminated
│   │  PIT EXIT → velocity resumes
│   │
├── GARAGE (chapter 9) ─── "Technical Debrief"
│   │  Minimal effects. Data-drawer aesthetic.
│   │  The calm after the pit stop.
│   │
└── PODIUM (chapter 10) ─── "Cross the Line"
    Finish-line band crosses viewport
    Timing Tower finalizes (all sectors purple)
    Delta HUD freezes to settled value
    "READY TO RUN A CLEAN LAP?" — podium CTA
    "RESTART LAP" loops back to Start Grid
```

### 3.2 Track Path Plan

The background "track spline" is a virtual path the camera progresses along as the user scrolls. It is NOT literally rendered as a visible track — it's a mathematical curve that modulates background behavior.

**Spline definition (11 control points, one per chapter):**

```
Chapter 0  (Start Grid):     Straight  — heading 0°,  calm
Chapter 1  (S1 Pain):        Corner R  — heading +35°, medium turbulence
Chapter 2  (S1 Deep):        Straight  — heading 35°,  reading zone, calm
Chapter 3  (S2 Pipeline):    Corner L  — heading -20°, slow sweeper
Chapter 4  (S2 Proof):       Straight  — heading -20°, trust zone, calm
Chapter 5  (S3 Product):     Corner R  — heading +25°, medium
Chapter 6  (S4 Workflows):   Straight  — heading 25°,  browsing zone
Chapter 7  (S5 Personas):    Corner R  — heading +40°, tight turn
Chapter 8  (Pit Stop):       Pit Lane  — heading 0°,   PIT LIMITER active
Chapter 9  (Garage):         Straight  — heading 0°,   calm
Chapter 10 (Podium):         Straight  — heading 0°,   FINISH LINE
```

**Corner vs Straight behavior:**

| Attribute | Straight | Corner |
|-----------|----------|--------|
| Background yaw | 0° | 1–4° (proportional to heading delta) |
| Particle lateral drift | 0 | ±0.5–2.0 px/frame in turn direction |
| Speed streaks | Minimal | Enhanced during entry, decay through apex |
| Contour distortion | Baseline | Increased shear in turn direction |
| Vignette | Centered | Shifts toward turn apex |
| Reveal mask | Normal | Slight stretch in lateral axis |

### 3.3 Mode Switching Rules

**DRIVE MODE** (default):
- Scroll drives `globalProgress` and `chapterProgress`
- Pointer position feeds reveal mask, parallax, and particle attractors
- Velocity feeds speed streaks, chromatic aberration, particle drift
- All HUD elements active and updating

**CONTROL MODE** (temporary):
- Triggered by: `CornerDrag` pointerDown, `ReportScrubber` active drag, `IndexOverlay` open
- Scroll is **not locked** (Lenis continues) but velocity influence on WebGL is **damped to 0.1x**
- Pointer position feeds the interactive element exclusively (via `setPointerCapture`)
- HUD continues updating but delta widget shows interaction-specific feedback
- Exit: `pointerUp` / overlay close → DRIVE MODE resumes with 300ms lerp

**TRANSITION MODE** (existing):
- Chapter change triggers `TransitionCompositor` FBO capture + shader blend
- During transition, mode is `transitioning`; scroll input continues accumulating but WebGL composites
- On complete, returns to DRIVE MODE

**New: PIT MODE** (special case of DRIVE MODE):
- Active only in chapter 8 (Pit Stop)
- Velocity multiplier: `0.3x` (pit limiter)
- Particle drift: capped at `0.5 px/frame`
- Speed streaks: disabled
- Wheel rotation responds to scroll at `0.3x` speed
- Exit on chapter 9 entry: velocity multiplier lerps back to `1.0x` over 600ms

### 3.4 Diegetic UI Component Library

#### 3.4.1 Timing Tower

**Position**: Fixed, left rail, replaces current `SectorTabs` but keeps navigation function.

**Visual design:**
```
┌─────────┐
│ S1      │ ← text + progress ring (existing pattern)
│ ●───    │ ← when active: ring animates, text bright
│ S2      │
│ ○       │ ← when pending: dim, ring empty
│ S3      │
│ ○       │
│ PIT     │
│ ○       │
│ GAR     │
│ ○       │
│ POD     │
│ ○       │
└─────────┘
```

**Sector completion behavior:**
- When user scrolls past a sector gate (first pixel of next chapter enters viewport):
  1. Completed sector label transitions to `#D946EF` (neon magenta-purple)
  2. Progress ring fills to 100% and changes to purple
  3. A thin horizontal line (1px, purple) sweeps across the viewport from left to right (400ms, `power2.out`)
  4. Tower label text flashes brightness 1.0→1.5→1.0 over 300ms
  5. Next sector becomes "active" (bright, ring starts from 0%)

**Tower state schema:**
```typescript
interface TimingTowerState {
  sectors: Array<{
    id: string;          // 'S1' | 'S2' | 'S3' | 'PIT' | 'GAR' | 'POD'
    status: 'pending' | 'active' | 'completed';
    progress: number;    // 0..1 within this sector's chapter range
    color: string;       // chalk when pending/active, #D946EF when completed
  }>;
  activeSectorIndex: number;
}
```

**Fallback (reduced motion):** Instant color change, no sweep line. Ring jumps to 100%.
**Fallback (no WebGL):** Pure CSS animation on the tower elements.

#### 3.4.2 Delta HUD

**Position**: Fixed, bottom-center, evolution of existing `DeltaStrip`.

**Behavior:**
- Normally displays a delta value that reacts to "interaction quality":
  - Jitter amplitude = `lerp(8, 0, maskCoverage)` — as the user reveals more telemetry truth, delta stabilizes
  - Base value trends from `+0.XXX` toward `0.000` as globalProgress increases (metaphor: the user is "improving their lap")
- On sector gate: delta flashes and resets to a new sector-specific value
- On DRS OPEN: delta briefly drops sharply (metaphor: "gaining time")
- On finish line: delta freezes at final value with a smooth damping settle (500ms)

**Visual:** Monospaced, `font-telemetry`, tiny (14px). Green when negative (gaining), red when positive (losing). Animates via `requestAnimationFrame` jitter, not CSS.

**Fallback (reduced motion):** Static value, no jitter. Updates on section change only.

#### 3.4.3 Mini Track Map Breadcrumb

**Position**: Fixed, bottom-right corner, 80x80px.

**Visual:** SVG silhouette of a generic racing circuit (not a real track — a stylized oval-with-chicane that maps to 11 chapters). A small dot (4px, accent color) moves along the path proportional to `globalProgress`.

**Corner zones:** Highlighted with a brighter stroke when the user enters a "corner" chapter (1, 3, 5, 7). The highlight modulates background behavior via the orchestrator.

**Fallback (reduced motion):** Static map, dot jumps between sections.
**Fallback (small viewport < 768px):** Hidden.

#### 3.4.4 DRS OPEN Moments

**Triggers:**
1. First flip-card reveal in any section
2. Sector gate crossing
3. Pipeline completion animation in S2
4. Persona card expand in S5

**Behavior:**
1. "DRS" label appears in `font-telemetry`, uppercase, positioned near the Timing Tower (below active sector)
2. Label fades in 200ms, holds 1800ms, fades out 500ms
3. During DRS active (2000ms total):
   - Reveal mask `brushRadius` multiplied by `1.4x`
   - Background `streakIntensity` multiplied by `1.3x`
   - Post-processing ChromaticAberration adds `0.001` baseline
4. After DRS, all multipliers lerp back to `1.0x` over 500ms

**State:**
```typescript
interface DrsState {
  active: boolean;
  remaining: number;     // ms
  multiplier: number;    // 1.0 → 1.4 → decay back
  trigger: string;       // which event caused it
}
```

**Fallback (reduced motion):** Label appears/disappears instantly. No radius/intensity boost.

#### 3.4.5 Radio Message Cards

**Purpose:** Replace generic flip-card reveal content with F1-style "Engineer → Driver" radio messages.

**Visual design (compact, on hover):**
```
┌────────────────────────────────────┐
│ 📻 ENGINEER  "Box this lap..."    │
└────────────────────────────────────┘
```

**Visual design (expanded, on click):**
```
┌────────────────────────────────────┐
│ 📻 ENGINEER → DRIVER              │
│ ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄ │
│ ▓▓░░▓░▓▓▓░░░▓▓░▓░░▓▓▓░░▓░▓░░   │ ← waveform
│                                    │
│ "Your braking point at Turn 4 is   │
│  15 metres too early. Trail the    │
│  brake to the apex — you'll find   │
│  three tenths."                    │
│                                    │
│ [ COPY IT DOWN ]                   │
└────────────────────────────────────┘
```

**Behavior:**
- Compact state appears on hover with 120ms delay (prevents flash on pass-through)
- Expanded on click: waveform animates (CSS keyframe, bars randomize heights)
- Content uses generic motorsport engineering language
- "COPY IT DOWN" is the action CTA (replaced per context: could be "REVEAL", "LEARN MORE", etc.)
- Proximity magnetism: card edge pulls cursor slightly when within 40px (via existing `PointerField`)

**Parameters:**
| Param | Default | Range |
|-------|---------|-------|
| `hoverDelay` | 120ms | 0–300ms |
| `expandDuration` | 420ms | 300–600ms |
| `waveformBars` | 24 | 12–48 |
| `waveformSpeed` | 800ms/cycle | 400–1200ms |
| `magnetismRadius` | 40px | 0–80px |

**Fallback:** Standard tooltip. No waveform animation.

#### 3.4.6 Track Cards (3D/animated)

**Used in:** S4 Workflows, S5 Personas.

**Visual:** Dark card (`concrete` background) with:
- Top: SVG track silhouette (per-persona or per-module) OR abstract geometric pattern
- Middle: Title + description in `font-monument` / `font-body`
- Bottom: Status pill + CTA
- Border: 1px `steel`, transitions to accent color on hover

**3D behavior:**
- Pointer position within card bounds → `rotateX` and `rotateY` (max ±8°)
- Parallax: inner content layers shift 2–4px opposite to tilt direction
- `perspective: 1200px` on parent, `transform-style: preserve-3d` on card
- On hover: border glows accent color, SVG track highlights relevant sector
- On click: card "pushes in" (scale 0.98, 80ms) then expands into a Radio Message Card debrief

**Parameters:**
| Param | Default | Range |
|-------|---------|-------|
| `maxTiltDeg` | 8° | 4–12° |
| `parallaxShift` | 3px | 1–6px |
| `perspective` | 1200px | 800–1600px |
| `hoverGlowOpacity` | 0.4 | 0.2–0.6 |
| `clickScaleDown` | 0.98 | 0.95–0.99 |
| `clickDuration` | 80ms | 50–120ms |

**Fallback (reduced motion):** No tilt/parallax. Hover state is flat color change only.
**Fallback (low quality tier):** `will-change: auto` removed. No GPU-layer promotion. Static card.

#### 3.4.7 Pit Stop Wheel

**Position:** Background of Pit Stop section, centered, large (40vw diameter), low opacity (0.08).

**Behavior:**
- Wheel SVG (simplified F1 wheel — 5 spokes, minimal) rotates proportional to scroll velocity
- Rotation speed = `scrollVelocity * 60 deg/frame` (capped at 360 deg/s by pit limiter)
- On idle: wheel rotation decelerates with `friction: 0.95` per frame
- Wheel opacity pulses slightly with `sin(time * 0.5) * 0.02 + 0.08`

**Compound styling (optional, stretch goal):**
| Tier | Compound Color | Treatment |
|------|---------------|-----------|
| Starter (Free) | White (hard) | `chalk` stroke |
| Performance | Yellow (medium) | `marshal-yellow` stroke |
| Pro Racer | Red (soft) | `safety-red` stroke |

**Fallback:** Static wheel silhouette, no rotation. CSS only.

#### 3.4.8 Finish Line

**Position:** Full-width band that crosses the viewport when Podium section enters.

**Behavior:**
1. As Podium chapter enters (chapter 10, first 20% of progress):
   - A checkered-pattern band (black + chalk, 8px squares) animates from right to left across the viewport (600ms, `power2.inOut`)
   - Band is 4px tall, positioned at vertical center
2. On band completion:
   - Timing Tower: all sectors flash to purple simultaneously
   - Delta HUD: value settles to `0.000` with 500ms damping
   - Mini Track Map: dot reaches finish marker, glows
3. CTA ("READY TO RUN A CLEAN LAP?") fades in over 900ms

**Fallback (reduced motion):** Band appears instantly (no animation). Tower updates instantly.

---

## 4. Experience Spec

### 4.1 Motion Grammar

All motion in the system follows a unified grammar derived from motorsport physics.

**Duration tiers (extending existing tokens):**

| Token | Duration | Usage | Motorsport metaphor |
|-------|----------|-------|-------------------|
| `--duration-micro` | 420ms | Hovers, toggles, small state changes | Gear shift |
| `--duration-room` | 900ms | Section transitions, card flips | Sector transit |
| `--duration-monument` | 1400ms | Headline reveals, major composition changes | Straight-line buildup |
| `--duration-sector-gate` | 400ms | **NEW** Sector completion sweep | Crossing a timing line |
| `--duration-drs` | 2000ms | **NEW** DRS boost window | DRS activation zone |
| `--duration-pit` | 600ms | **NEW** Pit limiter engage/disengage | Pit lane transition |
| `--duration-finish` | 600ms | **NEW** Finish line crossing | Checkered flag |

**Easing presets (extending existing tokens):**

| Token | Curve | Usage |
|-------|-------|-------|
| `--ease-inertia` | `cubic-bezier(0.16, 1, 0.3, 1)` | Default deceleration (existing) |
| `--ease-overshoot` | `cubic-bezier(0.34, 1.56, 0.64, 1)` | Spring bounce (existing) |
| `--ease-spring` | `cubic-bezier(0.22, 1.2, 0.36, 1)` | Softer spring (existing) |
| `--ease-snap` | `cubic-bezier(0.7, 0, 0.84, 0)` | Snap acceleration (existing) |
| `--ease-anticipate` | `cubic-bezier(0.45, 0, 0.55, 1)` | Symmetric (existing) |
| `--ease-sector-gate` | `cubic-bezier(0.0, 0, 0.2, 1)` | **NEW** Fast start, long settle (sweep line) |
| `--ease-reveal-decay` | `exponential decay (e^-kt)` | **NEW** Mask persistence fade (shader, not CSS) |
| `--ease-pit-enter` | `cubic-bezier(0.8, 0, 1, 1)` | **NEW** Velocity damping onset |
| `--ease-pit-exit` | `cubic-bezier(0, 0, 0.2, 1)` | **NEW** Velocity recovery |

**Damping constants:**

| Constant | Value | Usage |
|----------|-------|-------|
| `pointerInertia` | 0.08 | Reveal mask follows pointer with lag |
| `scrollSmoothing` | 0.12 (existing `velocitySmoothing`) | Scroll velocity signal smoothing |
| `backgroundYawDamping` | 0.04 | Background responds slowly to turn-feel |
| `particleDriftDamping` | 0.06 | Particle lateral drift eases |
| `deltaJitterDamping` | 0.10 | Delta value noise settles on idle |
| `wheelFriction` | 0.95 | Pit wheel rotation deceleration |
| `drsDecay` | 0.002 | DRS multiplier return-to-baseline per ms |

### 4.2 Section Choreography

Each section gets an **entry choreography** (what happens as the user scrolls in) and an **ambient state** (what happens while the user is reading).

#### Chapter 0: Start Grid

**Entry:** Preloader → lights → white flash → reveal mask appears
**Ambient:**
- Reveal mask active: user explores telemetry truth layer
- Particles drift slowly upward (grid-to-start feeling)
- Timecode counter begins from T+00:00.00
- Background at maximum calm (straight zone)

**Section-specific:**
- Hold-to-start button gains subtle pulse ring (existing but enhanced: ring uses `--ease-sector-gate`)
- On lights completion: reveal mask "bursts" outward from center (initial brush stamp at center, radius 2x normal, decays normally)

#### Chapter 1: S1 Pain (Corner R)

**Entry (Sector Gate S1):**
1. Purple sweep line crosses viewport (400ms)
2. Timing Tower S1 turns active
3. Background enters first corner: yaw +2°, particles drift right
4. Speed streaks flash briefly on the corner entry

**Ambient:**
- Corner drag interaction with enhanced feedback (drag point glow, delta text animates)
- Background corner feel: sustained lateral drift during reading
- DRS OPEN triggers on first flip-card reveal in this section

#### Chapter 2: S1 Deep (Straight)

**Entry:** crossfade-blur transition (existing)
**Ambient:**
- Return to straight: yaw returns to 0°, particles calm
- Trace hover triggers localized particle attraction around the hovered channel
- This is a reading zone: background at maximum legibility

#### Chapter 3: S2 Pipeline (Corner L)

**Entry (Sector Gate S2):**
1. Timing Tower: S1 turns purple (#D946EF)
2. Purple sweep line
3. Background enters left corner: yaw -1.5° (slow sweeper)

**Ambient:**
- Pipeline blocks fill with scroll progress (existing, enhanced with momentum easing)
- Speed streaks activate during fast scroll through the blocks
- DRS OPEN on pipeline completion (all 5 blocks filled)

#### Chapter 4: S2 Proof (Straight)

**Entry:** crossfade-blur (existing)
**Ambient:**
- Scrutineering stamps slam with enhanced particle burst (small radial emission, 20 particles, 300ms lifetime)
- Reading zone: background calm
- Stamp "VERIFIED" text gets monument-reveal treatment

#### Chapter 5: S3 Product (Corner R)

**Entry (Sector Gate S3):**
1. Timing Tower: S2 turns purple
2. Purple sweep line
3. Background: yaw +2°, medium corner

**Ambient:**
- Mode toggle (B2C/B2B) triggers background accent shift
- Scrubber interaction in CONTROL MODE (subtle velocity damping)
- Product screenshots sacred — no WebGL overlay on them

#### Chapter 6: S4 Workflows (Straight)

**Entry:** velocity-warp (existing)
**Ambient:**
- Track Cards with 3D tilt replace current flat grid cards
- Background: calm straight, maximum legibility
- Card hover triggers localized particle attraction

#### Chapter 7: S5 Personas (Corner R)

**Entry:** velocity-warp (existing) — tightest corner heading
**Ambient:**
- Track Cards for personas
- Background: yaw +3° (tightest turn), strong lateral drift
- DRS OPEN on persona card expand
- This is the "fastest corner" — most dramatic background response

#### Chapter 8: Pit Stop (Pit Lane)

**Entry:**
1. Timing Tower: S3 turns purple, PIT illuminates
2. **PIT MODE engages**: velocity multiplier drops to 0.3x over 600ms
3. Wheel appears in background, begins rotating

**Ambient:**
- Pit limiter active: all velocity effects damped
- Wheel rotation synced to (damped) scroll velocity
- Pricing cards are purely DOM — no WebGL overlay
- FAQ accordion unchanged
- Background: calm, no corner feel, maximum readability

**Exit (chapter 9 entry):**
- PIT MODE disengages: velocity multiplier returns to 1.0x over 600ms
- Wheel rotation decelerates and fades out

#### Chapter 9: Garage (Straight)

**Entry:** crossfade-blur (existing)
**Ambient:**
- Minimal effects. Technical section.
- Background: static grain + scanlines only (existing CSS textures)
- No particles, no speed streaks
- This is the "cool-down lap" before the finish

#### Chapter 10: Podium (Finish Line)

**Entry:**
1. Timing Tower: all remaining sectors turn purple simultaneously
2. Finish-line checkered band sweeps across viewport
3. Delta HUD settles to 0.000

**Ambient:**
- CTA is dominant: "READY TO RUN A CLEAN LAP?"
- Background: gentle breathing (existing PodiumScene sin-wave light)
- Reveal mask continues working but radius is at maximum (user has "full vision")
- "RESTART LAP" scrolls to top and resets tower

---

## 5. Technical Architecture

### 5.1 Three-Layer Model

```
┌──────────────────────────────────────────────────┐
│                   DOM Layer                       │
│  ┌───────────┐ ┌──────────┐ ┌────────────────┐  │
│  │TimingTower│ │ DeltaHUD │ │ Radio Cards    │  │
│  │(fixed DOM)│ │(fixed DOM)│ │(positioned DOM)│  │
│  └───────────┘ └──────────┘ └────────────────┘  │
│  ┌────────────────────────────────────────────┐  │
│  │           Room Content (existing)           │  │
│  │   CTAs, headlines, flip cards, pricing...   │  │
│  └────────────────────────────────────────────┘  │
│  ┌──────────┐ ┌──────────────┐                   │
│  │TrackMap  │ │ DRS Label    │                   │
│  │(SVG, DOM)│ │ (animated DOM)│                   │
│  └──────────┘ └──────────────┘                   │
├──────────────────────────────────────────────────┤
│               WebGL Layer (z-index: 0)           │
│  ┌────────────────────────────────────────────┐  │
│  │         ExperienceCanvas (R3F)              │  │
│  │  ┌──────────────────────────────────────┐  │  │
│  │  │     RevealMask Pipeline (NEW)        │  │  │
│  │  │  ┌──────────┐  ┌───────────────┐    │  │  │
│  │  │  │ Layer A   │  │  Layer B      │    │  │  │
│  │  │  │ (clean)   │  │  (telemetry)  │    │  │  │
│  │  │  └──────────┘  └───────────────┘    │  │  │
│  │  │  ┌────────────────────────────────┐  │  │  │
│  │  │  │     Mask FBO (ping-pong)       │  │  │  │
│  │  │  │  stamp → decay → blur → blend  │  │  │  │
│  │  │  └────────────────────────────────┘  │  │  │
│  │  └──────────────────────────────────────┘  │  │
│  │  ┌──────────────────────────────────────┐  │  │
│  │  │    LivingSurface (extended Atmo.)    │  │  │
│  │  │  grain | contours | particles |      │  │  │
│  │  │  speed streaks | vignette            │  │  │
│  │  └──────────────────────────────────────┘  │  │
│  │  ┌──────────────────────────────────────┐  │  │
│  │  │    PostStack (existing, extended)     │  │  │
│  │  │  Bloom | Noise | ChromaticAberration │  │  │
│  │  └──────────────────────────────────────┘  │  │
│  │  ┌──────────────────────────────────────┐  │  │
│  │  │  TransitionCompositor (existing)      │  │  │
│  │  └──────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────┘  │
├──────────────────────────────────────────────────┤
│              Orchestrator Layer                   │
│  ┌────────────────────────────────────────────┐  │
│  │         useKernelStore (extended)           │  │
│  │  existing: chapter, progress, scroll,       │  │
│  │           pointer, mode, quality            │  │
│  │  NEW: hudState, revealState, drsState,      │  │
│  │       trackPath, pitMode, finishState       │  │
│  └────────────────────────────────────────────┘  │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
│  │ScrollCtrl│  │PointerFld│  │QualityManager │  │
│  │(existing)│  │(existing) │  │(existing)     │  │
│  └──────────┘  └──────────┘  └───────────────┘  │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
│  │MotionOrc │  │SectorGate│  │LivingSurface  │  │
│  │(existing)│  │Ctrl (NEW)│  │Ctrl (NEW)     │  │
│  └──────────┘  └──────────┘  └───────────────┘  │
└──────────────────────────────────────────────────┘
```

### 5.2 New Modules

#### 5.2.1 RevealMask Pipeline

**Location:** `src/experience/reveal/`

**Files:**
- `RevealMaskPipeline.tsx` — R3F component managing the FBO ping-pong, decay, blur, and blend passes
- `useRevealState.ts` — Hook exposing `maskCoverage`, `brushRadius`, `turbulenceLevel` to orchestrator
- `shaders/mask-stamp.glsl` — Soft brush stamp shader (Gaussian falloff)
- `shaders/mask-decay.glsl` — Persistence decay pass (multiply by decay factor)
- `shaders/mask-blur.glsl` — Cheap 5-tap blur (separable, two passes)
- `shaders/reveal-blend.glsl` — Final composite: `mix(layerA, layerB, mask.r)`
- `RevealSubjects.tsx` — Renders Layer A and Layer B content for the hero (chapter 0)

**Pipeline per frame:**

```
1. Read pointer from useKernelStore → apply inertia → get smoothed position
2. STAMP PASS: render soft brush at smoothed position into Mask FBO [A]
3. DECAY PASS: read Mask FBO [A], multiply by decayFactor, write to Mask FBO [B]
4. BLUR PASS: read Mask FBO [B], separable Gaussian blur, write back to Mask FBO [A]
5. BLEND PASS: sample Layer A texture, Layer B texture, Mask FBO [A] → final output
6. Swap ping-pong designation (A↔B) for next frame
7. Update maskCoverage in store (average of mask texture, sampled at 1/16 resolution)
```

**Adaptive behavior:**
- `high` tier: Full pipeline (stamp + decay + blur), mask at `1024x1024`
- `balanced` tier: Stamp + decay only (no blur pass), mask at `512x512`
- `low` tier: Lando-simple radial smoothstep (no FBO, no persistence)
- No WebGL: CSS `radial-gradient` mask on pointer move, 60% opacity blend

**Chapter activation:**
- Chapter 0 (Start Grid): Full reveal with telemetry truth subject
- Chapters 1-9: Reveal mask continues but Layer B changes per section (or disables and reverts to atmosphere only)
- Chapter 10 (Podium): Mask at maximum coverage (full truth revealed)

#### 5.2.2 LivingSurface

**Location:** `src/experience/renderer/scenes/LivingSurface.tsx`

Replaces `AtmosphereBase` for all chapters (AtmosphereBase becomes a simplified fallback).

**Depth layers:**

| Layer | Rendering | Behavior |
|-------|-----------|----------|
| 1: Base grain | Full-screen quad + noise shader | Always-on, subtle. Replaces CSS `.texture-grain`. |
| 2: Contour field | `THREE.Line` segments (20–40 curves) | Slow drift, attracted toward pointer, parallax on scroll |
| 3: Particle drift | `THREE.Points` (existing, enhanced) | Velocity-driven Y drift + turn-feel lateral drift |
| 4: Speed streaks | `THREE.Line` segments (10–20, dynamic spawn) | Spawn on high scroll velocity, fade over 300ms, direction follows track heading |
| 5: Vignette | Full-screen quad + radial gradient shader | Centers on content zone, shifts toward turn apex in corners |

**Turn-feel implementation:**
- Track path spline provides `heading` and `headingDelta` per chapter
- `headingDelta` drives:
  - Contour field lateral shear: `shear = headingDelta * 0.03`
  - Particle lateral drift: `driftX = headingDelta * scrollVelocity * 2.0`
  - Speed streak direction: `angle = heading * DEG2RAD`
  - Vignette center offset: `offsetX = headingDelta * 0.05`
  - Canvas slight CSS rotation: `rotate(headingDelta * 0.5deg)` — creates the "yaw" sensation

**Pointer influence:**
- Contour field: curves deflect toward pointer within 200px radius
- Particles: weak attraction within 100px radius
- Vignette: shifts slightly toward pointer (parallax effect)

#### 5.2.3 SectorGateController

**Location:** `src/experience/narrative/SectorGateController.tsx`

Listens to `currentChapter` changes and orchestrates sector gate moments.

**Sector gate mapping:**
```typescript
const SECTOR_GATES: Record<number, string> = {
  1: 'S1',   // Start Grid → S1 Pain
  3: 'S2',   // S1 Deep → S2 Pipeline
  5: 'S3',   // S2 Proof → S3 Product
  8: 'PIT',  // S5 Personas → Pit Stop
  10: 'FINISH', // Garage → Podium
};
```

On gate trigger:
1. Update `hudState.sectors[sectorId].status = 'completed'`
2. Update `hudState.sectors[sectorId].color = '#D946EF'`
3. Dispatch `sector_gate` event (consumed by sweep-line GSAP animation)
4. If applicable, trigger DRS OPEN

#### 5.2.4 HUD Components

**Location:** `src/components/chrome/` (extending existing pattern)

All HUD components are **DOM elements** positioned via CSS `position: fixed`. They read from `useKernelStore` and animate via GSAP or `requestAnimationFrame`. They do NOT render inside the R3F canvas.

**New files:**
- `TimingTower.tsx` — replaces `SectorTabs.tsx` (keeps navigation function)
- `DeltaHud.tsx` — extends `DeltaStrip.tsx` with jitter + settle behavior
- `MiniTrackMap.tsx` — SVG track + animated dot
- `DrsLabel.tsx` — animated DRS indicator
- `FinishLine.tsx` — checkered band animation (GSAP)

### 5.3 Module Dependency Graph

```
useKernelStore (state)
  ├── ScrollController (input → store)
  ├── PointerField (input → store)
  ├── QualityManager (perf → store)
  │
  ├── SectorGateController (store → HUD events)
  │   ├── TimingTower (DOM, reads store)
  │   ├── DrsLabel (DOM, reads store)
  │   └── FinishLine (DOM, reads store)
  │
  ├── DeltaHud (DOM, reads store)
  ├── MiniTrackMap (DOM, reads store)
  │
  ├── ExperienceCanvas (R3F)
  │   ├── RevealMaskPipeline (FBO, reads store pointer/quality)
  │   │   └── RevealSubjects (Layer A + B content)
  │   ├── LivingSurface (replaces AtmosphereBase)
  │   │   └── TrackPath (heading data per chapter)
  │   ├── PostStack (existing)
  │   └── TransitionCompositor (existing)
  │
  └── MotionOrchestrator (GSAP, reads store for room enter/exit)
```

---

## 6. Orchestrator Contract

### 6.1 Event Schema (Inputs)

All events flow into `useKernelStore` via dedicated controllers.

```typescript
// Events (conceptual — implemented as store actions)

// Pointer events (from PointerField)
pointer_move(x: number, y: number, vx: number, vy: number, t: number)
pointer_down(x: number, y: number, t: number)
pointer_up(x: number, y: number, t: number)

// Scroll events (from ScrollController / Lenis)
scroll(progress: number, velocity: number, direction: 'up' | 'down' | 'idle', t: number)

// Viewport events (from QualityManager / resize observer)
resize(viewport_w: number, viewport_h: number, dpr: number)
visibility_change(is_visible: boolean)

// Capability events (from QualityManager, once on mount)
prefers_reduced_motion(is_on: boolean)
webgl_capability(tier: 'high' | 'balanced' | 'low' | 'none')

// Narrative events (from SectorGateController / MotionOrchestrator)
section_enter(section_id: string)
section_exit(section_id: string)
sector_gate(sector_id: string, gate_type: 'entry' | 'completion')

// Mode events (from interaction components)
mode_switch(mode: 'drive' | 'control' | 'pit', reason: string)

// DRS events (from SectorGateController / interaction components)
drs_activate(trigger: string)
drs_deactivate()
```

### 6.2 State Schema (Extended KernelStore)

```typescript
// Existing state (preserved exactly as-is)
interface KernelState {
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

// NEW state slices
interface HudState {
  tower: {
    sectors: Array<{
      id: string;
      status: 'pending' | 'active' | 'completed';
      progress: number;
      color: string;  // chalk or #D946EF
    }>;
    activeSectorIndex: number;
  };
  delta: {
    value: number;         // current delta display value
    jitter: number;        // current jitter amplitude (0-8)
    settled: boolean;      // true after finish line
  };
  trackMap: {
    dotProgress: number;   // 0..1 along the SVG path
    activeCorner: string | null;  // chapter id if in a corner zone
  };
}

interface RevealState {
  maskCoverage: number;    // 0..1, average of mask texture
  brushRadius: number;     // current radius (px, screen-space)
  turbulenceLevel: number; // 0..1, advection intensity
  smoothedPointer: { x: number; y: number }; // after inertia
  layerSubject: string;    // 'telemetry-truth' | 'racing-line' | etc.
  active: boolean;         // false when chapter doesn't use reveal
}

interface DrsState {
  active: boolean;
  remaining: number;       // ms remaining
  multiplier: number;      // current boost multiplier (1.0 = none)
  trigger: string;         // what caused activation
}

interface TrackPathState {
  heading: number;         // current heading in degrees
  headingDelta: number;    // delta from previous chapter heading
  isCorner: boolean;       // true if current chapter is a corner
  pitMode: boolean;        // true in pit stop
  velocityMultiplier: number; // 1.0 normally, 0.3 in pit
}

interface FinishState {
  crossed: boolean;        // true after finish line animation
  finalDelta: number;      // frozen delta value
}

// Extended mode type
type InteractionMode =
  | 'preloading'
  | 'idle'
  | 'scrolling'
  | 'dragging'
  | 'transitioning'
  | 'pit';  // NEW

// Full extended store
type ExtendedKernelStore = KernelState & HudState & RevealState & DrsState & TrackPathState & FinishState & KernelActions & ExtendedActions;
```

### 6.3 Update Loop Contract

The orchestrator follows a strict per-frame update order:

```
tick(dt: number):
  1. INPUT PHASE
     a. Read raw pointer position → apply inertia → store smoothedPointer
     b. Read scroll position → compute velocity → store scrollVelocity
     c. Detect chapter boundaries → fire section_enter/exit
     d. Check sector gates → fire sector_gate events

  2. STATE PHASE
     a. Update trackPath (heading, headingDelta, isCorner) from chapter config
     b. Update velocityMultiplier (pit mode lerp)
     c. Update DRS timer (decrement remaining, compute multiplier)
     d. Update HUD state:
        - tower sector statuses
        - delta value (with jitter = lerp(8, 0, maskCoverage))
        - trackMap dot position
     e. Update reveal state (maskCoverage from FBO readback)

  3. RENDER PHASE (WebGL)
     a. RevealMask pipeline: stamp → decay → blur → blend
     b. LivingSurface: update all 5 layers with turn-feel + pointer + velocity
     c. PostStack: update ChromaticAberration from velocity + DRS
     d. TransitionCompositor: if transitioning, run shader blend

  4. PUBLISH PHASE (DOM)
     a. TimingTower reads tower state → updates DOM
     b. DeltaHud reads delta state → updates display with jitter
     c. MiniTrackMap reads trackMap state → updates SVG dot position
     d. DrsLabel reads DRS state → shows/hides label
     e. FinishLine reads finish state → triggers animation
```

**Performance guarantees:**
- Input phase: < 0.5ms (pure math, no DOM reads)
- State phase: < 0.5ms (store updates, no DOM)
- Render phase: < 8ms target (GPU-bound, quality-adaptive)
- Publish phase: < 1ms (batched DOM writes via `requestAnimationFrame`)
- **Total frame budget: 16.6ms (60fps) or 33.3ms (30fps on balanced)**

---

## 7. Parameter Tables & Budgets

### 7.1 Reveal System Parameters

| Parameter | Default | Min | Max | Per-Tier | Rationale |
|-----------|---------|-----|-----|----------|-----------|
| `maskResolution` | 1024 | 256 | 2048 | high=1024, balanced=512, low=N/A | Balance mask quality vs fill-rate cost |
| `brushRadius` | 80px | 40px | 160px | Same all tiers | Radius in screen pixels; DRS scales by 1.4x |
| `brushSoftness` | 0.6 | 0.3 | 0.9 | Same | Gaussian sigma multiplier; 1.0 = hard edge |
| `decayFactor` | 0.985 | 0.95 | 0.999 | Same | Per-frame multiply; 0.985 ≈ 3s to 10% opacity |
| `blurKernelSize` | 5 | 3 | 9 | high=5, balanced=0 (skip), low=0 | Separable Gaussian; 0 means no blur pass |
| `blurSigma` | 2.0 | 0.5 | 4.0 | — | Only applies when blur enabled |
| `inertiaTimeConstant` | 0.08 | 0.03 | 0.15 | Same | Lerp factor: lower = more lag |
| `turbulenceEnabled` | true | — | — | high=true, balanced=false, low=false | Fluid advection |
| `turbulenceStrength` | 0.3 | 0.1 | 0.8 | — | Only when enabled |
| `turbulenceScale` | 4.0 | 2.0 | 8.0 | — | Noise frequency for advection field |
| `drsRadiusMultiplier` | 1.4 | 1.2 | 1.8 | Same | Brush radius scale during DRS |
| `idleDecayRate` | 0.97 | 0.93 | 0.99 | Same | Faster decay when pointer is idle > 2s |
| `mobileBurstRadius` | 120px | 80px | 200px | — | Tap-to-burst radius on touch devices |
| `mobileBurstDecay` | 0.96 | 0.93 | 0.99 | — | Faster decay for burst reveals |

### 7.2 Living Surface Parameters

| Parameter | Default | Min | Max | Per-Tier | Rationale |
|-----------|---------|-----|-----|----------|-----------|
| `grainIntensity` | 0.04 | 0.01 | 0.08 | Same | Noise overlay opacity |
| `contourCount` | 30 | 10 | 50 | high=30, balanced=15, low=0 | Line segment count |
| `contourDriftSpeed` | 0.001 | 0.0005 | 0.003 | Same | Base drift velocity |
| `contourPointerInfluence` | 0.03 | 0.01 | 0.06 | Same | Deflection strength toward pointer |
| `particleCount` | 200 | 0 | 400 | high=200, balanced=100, low=0 | Point count (existing pattern) |
| `particleDriftY` | 2.0 | 0.5 | 4.0 | Same | Scroll-velocity multiplier for Y drift |
| `particleDriftX` | 2.0 | 0.5 | 4.0 | Same | headingDelta multiplier for X drift (turn-feel) |
| `particlePointerRadius` | 100px | 50px | 200px | Same | Attraction/repulsion radius |
| `streakCount` | 15 | 5 | 25 | high=15, balanced=8, low=0 | Max simultaneous speed streaks |
| `streakSpawnThreshold` | 0.4 | 0.2 | 0.6 | Same | `abs(scrollVelocity)` above which streaks spawn |
| `streakLifetime` | 300ms | 150ms | 500ms | Same | Individual streak fade time |
| `streakLength` | 40px | 20px | 80px | Same | Streak line length |
| `vignetteRadius` | 0.7 | 0.5 | 0.9 | Same | Radial gradient inner radius (normalized) |
| `vignetteShift` | 0.05 | 0.02 | 0.10 | Same | Max shift toward turn apex (normalized) |
| `yawRange` | 1–4° | 0° | 6° | Same | CSS rotation applied to canvas in corners |
| `cornerParallaxFactor` | 0.02 | 0.01 | 0.04 | Same | Contour shift multiplier in corners |

### 7.3 HUD System Parameters

| Parameter | Default | Min | Max | Rationale |
|-----------|---------|-----|-----|-----------|
| `towerUpdateCadence` | Per-frame (RAF) | — | — | Progress ring updates smoothly |
| `sectorGateSweepDuration` | 400ms | 200ms | 600ms | Purple line sweep speed |
| `sectorGateFlashDuration` | 300ms | 150ms | 500ms | Label brightness flash |
| `sectorGateFlashIntensity` | 1.5x | 1.2x | 2.0x | Brightness multiplier |
| `deltaJitterBase` | 8px | 4px | 12px | Maximum jitter amplitude at maskCoverage=0 |
| `deltaJitterMapping` | `lerp(base, 0, coverage)` | — | — | Linear mapping from mask coverage |
| `deltaSettleDuration` | 500ms | 300ms | 800ms | Damping time on finish |
| `deltaFlashOnGate` | ±0.050 | ±0.020 | ±0.100 | Delta jump on sector gate |
| `drsLabelHoldDuration` | 1800ms | 1000ms | 2500ms | How long "DRS" label stays visible |
| `drsBoostMultiplier` | 1.4x | 1.2x | 1.8x | Applied to reveal + streaks |
| `drsDecayDuration` | 500ms | 300ms | 800ms | Return-to-baseline time |
| `trackMapDotSize` | 4px | 2px | 6px | Breadcrumb dot size |
| `trackMapCornerHighlight` | accent color | — | — | Stroke color when in corner zone |
| `finishBandDuration` | 600ms | 400ms | 800ms | Checkered pattern sweep time |
| `finishBandHeight` | 4px | 2px | 8px | Band thickness |
| `finishBandSquareSize` | 8px | 4px | 12px | Checkered pattern square size |

### 7.4 Motion Grammar Parameters

| Category | Parameter | Default | Rationale |
|----------|-----------|---------|-----------|
| **Hover response** | Delay | 0ms | Immediate for buttons/links |
| **Hover response** | Scale | 1.02x | Subtle interactive feedback |
| **Hover response** | Duration | 200ms | Quick but perceptible |
| **Press response** | Scale | 0.98x | "Push in" feedback |
| **Press response** | Duration | 80ms | Snappy tactile feel |
| **Tooltip/radio card** | Hover delay | 120ms | Prevent flash on pass-through |
| **Tooltip/radio card** | Open duration | 420ms | `--duration-micro` |
| **Flip card** | Duration | 900ms | `--duration-room` (existing) |
| **Monument reveal** | Duration | 1400ms | `--duration-monument` (existing) |
| **Section enter fade** | Duration | 900ms | `--duration-room` (existing) |
| **Section enter blur** | From | `blur(6px)` | Existing pattern |
| **Sector gate sweep** | Duration | 400ms | `--duration-sector-gate` |
| **DRS window** | Duration | 2000ms | `--duration-drs` |
| **Pit mode transition** | Duration | 600ms | `--duration-pit` |
| **Finish line sweep** | Duration | 600ms | `--duration-finish` |
| **Pointer inertia** | Lerp | 0.08 | `physics.scrollLerp` (matched) |
| **Magnetism** | Radius | 120px | `physics.magnetismRadius` (existing) |
| **Magnetism** | Strength | 0.15 | `physics.magnetismStrength` (existing) |

### 7.5 Performance Budgets

| Metric | High (desktop) | Balanced (mid/mobile) | Low (weak) | Fallback (no WebGL) |
|--------|---------------|----------------------|------------|-------------------|
| **Target FPS** | 60 fps | 30 fps | 24 fps | 60 fps (CSS only) |
| **Max frame time p95** | 16.6ms | 33.3ms | 41.6ms | 16.6ms |
| **Max draw calls** | 40 | 20 | 10 | 0 |
| **Max triangles** | 50k | 20k | 5k | 0 |
| **WebGL memory** | 128 MB | 64 MB | 32 MB | 0 |
| **JS heap (experience layer)** | 32 MB | 16 MB | 8 MB | 4 MB |
| **FBO count** | 4 (2 mask + 2 transition) | 2 (1 mask + 1 transition) | 0 | 0 |
| **Mask resolution** | 1024x1024 (4MB) | 512x512 (1MB) | 0 | 0 |
| **Particle count** | 200 | 100 | 0 | 0 |
| **Contour lines** | 30 | 15 | 0 | 0 |
| **Speed streaks** | 15 | 8 | 0 | 0 |
| **Blur passes/frame** | 2 (separable) | 0 | 0 | 0 |

**Network / loading budgets:**

| Asset | Budget | Strategy |
|-------|--------|----------|
| R3F + Three.js bundle | 180 KB gzip (existing) | Tree-shaken, lazy-loaded |
| Reveal shader code | < 5 KB | Inline GLSL template literals |
| LivingSurface shaders | < 8 KB | Inline GLSL |
| Track map SVG | < 3 KB | Inlined in component |
| Pit wheel SVG | < 2 KB | Inlined in component |
| HUD fonts | 0 KB (reuses existing) | IBM Plex Mono already loaded |
| Total experience layer addition | < 25 KB gzip | Above R3F baseline |
| LCP budget (regression) | < 200ms | Reveal mask lazy-initializes after LCP |
| TTI budget (regression) | < 500ms | FBO allocation deferred to `requestIdleCallback` |

---

## 8. Prototype Plan

### Prototype 1: Liquid Reveal Hero

**Goal:** Validate the flagship moment — cursor reveal with persistence, trail, decay.

**Scope:**
- Hero section only (chapter 0)
- Layer A: clean hero (existing StartGrid content)
- Layer B: pre-rendered telemetry truth composition (static image initially, dynamic later)
- Full mask pipeline: stamp → decay → blur → blend
- Desktop + mobile (touch burst) + reduced motion
- Adaptive quality: 3 tiers

**Metrics:**

| Metric | Target | Measurement |
|--------|--------|-------------|
| Trail persistence visible | Yes, 3s decay to 10% | Visual: record screen, measure trail visible duration |
| Blob shape organic (not circular spotlight) | Yes | Visual: screenshot at various pointer velocities |
| Desktop FPS with mask pipeline | ≥ 55 fps | Chrome Performance tab, 10s recording |
| Mobile FPS (balanced) | ≥ 28 fps | Safari Performance on iPhone 15 |
| Reduced motion: still premium | Yes | Visual review, no trail/advection but clean blend |
| LCP regression | < 200ms | Lighthouse before/after |
| Mask texture memory | ≤ 4MB (high), ≤ 1MB (balanced) | WebGL Inspector |

**Acceptance tests:**
1. Move cursor slowly across hero → smooth trail with soft edges, no hard boundary
2. Move cursor quickly → trail stretches, demonstrates inertia lag
3. Stop moving → trail decays to baseline over ~3s
4. Tap on mobile → burst reveal at tap point, decays
5. Drag on mobile → continuous reveal along finger path
6. Enable reduced motion → instant blend at pointer, no trail/persistence
7. Force `low` quality tier → Lando-simple radial blend, no FBO
8. Force no WebGL → CSS radial-gradient fallback, content readable

### Prototype 2: Living Background + HUD

**Goal:** Validate turn-feel and persistent HUD integration.

**Scope:**
- Full-page scroll through all 11 chapters
- LivingSurface replaces AtmosphereBase
- All 5 depth layers: grain, contours, particles, speed streaks, vignette
- Turn-feel: corners vs straights modulate background behavior
- Timing Tower with sector completion (purple)
- Delta HUD with jitter
- Mini Track Map with moving dot

**Metrics:**

| Metric | Target | Measurement |
|--------|--------|-------------|
| Turn-feel noticeable | 6/10 testers detect "corners" | User testing: "describe what happens to the background" |
| Sector completion visible | Purple flash noticed by 8/10 | User testing: "what color did the sidebar turn?" |
| Desktop FPS with all layers | ≥ 50 fps | Chrome Performance, full scroll |
| No CTA obscured by HUD | 0 overlaps | Visual audit at all breakpoints |
| Speed streaks on fast scroll | Visible, not distracting | Visual review |
| Background calm on straights | Yes | Visual comparison: corner vs straight screenshots |

**Acceptance tests:**
1. Scroll from chapter 0 to chapter 10 → background yaws in corners, calms on straights
2. Enter S1 Pain (corner R) → particles drift right, vignette shifts
3. Enter S2 Pipeline (corner L) → particles drift left, direction change obvious
4. Fast scroll → speed streaks appear, oriented to track heading
5. Slow scroll → no streaks, calm particle drift only
6. Timing Tower: enter S2 → S1 label turns purple with sweep line
7. Delta HUD: jitter reduces as user explores (reveals mask coverage)
8. Mini Track Map: dot moves proportionally to globalProgress

### Prototype 3: Sector Transition + DRS

**Goal:** Validate one complete "sector gate" moment with DRS and composited transition.

**Scope:**
- Chapters 2→3 transition (S1 Deep → S2 Pipeline) — includes sector gate S2
- Full sector gate choreography: sweep line, tower update, DRS activation
- DRS OPEN: label appears, reveal radius boosts, streak intensity boosts
- Existing `TransitionCompositor` mask-wipe shader used for scene transition
- All effects combined: reveal mask + living surface + HUD + DRS + transition

**Metrics:**

| Metric | Target | Measurement |
|--------|--------|-------------|
| Sector gate feels "momentous" | 7/10 testers notice transition | User testing: "what happened when you reached section 3?" |
| DRS label visible | Yes, for 2s | Screen recording |
| DRS boost perceptible | Reveal radius visibly increases | Screen recording: compare radius before/during/after |
| No frame drop during gate | ≥ 45 fps through transition | Chrome Performance |
| All effects combine without conflict | No visual glitches | Visual review |

**Acceptance tests:**
1. Scroll from chapter 2 into chapter 3 → sector gate fires
2. Purple sweep line crosses viewport in 400ms
3. Timing Tower S1 turns #D946EF
4. "DRS" label appears for 2s
5. During DRS: reveal brush radius visibly larger, speed streaks more intense
6. After DRS: effects return to baseline smoothly
7. Transition shader (mask-wipe) plays simultaneously without conflicting with reveal mask
8. Combined FPS stays above 45 fps

---

## 9. Performance & QA Plan

### 9.1 Device Test Matrix

| Device | OS | Browser | Tier | Priority |
|--------|-----|---------|------|----------|
| MacBook Pro M2 | macOS 15 | Chrome 132 | High | P0 |
| MacBook Pro M2 | macOS 15 | Safari 18 | High | P0 |
| ThinkPad X1 (Intel UHD 620) | Windows 11 | Chrome 132 | Balanced | P0 |
| iPhone 15 Pro | iOS 18 | Safari | Mobile-balanced | P0 |
| iPhone SE 3 | iOS 18 | Safari | Mobile-low | P1 |
| iPad Air 5 | iPadOS 18 | Safari | Balanced | P1 |
| Pixel 8 | Android 15 | Chrome | Mobile-balanced | P1 |
| Samsung Galaxy A54 | Android 14 | Chrome | Mobile-low | P2 |
| Surface Go 3 | Windows 11 | Edge | Low | P2 |
| Samsung Galaxy Tab S9 | Android 14 | Chrome | Balanced | P2 |

### 9.2 QA Tools & Process

| Tool | Purpose | When |
|------|---------|------|
| Chrome Performance tab | Frame timing, long tasks | Every prototype |
| Chrome Layers tab | Compositing layer count | Layout changes |
| Spector.js | WebGL draw calls, FBO inspection | Prototype 1 |
| Lighthouse CI | LCP, CLS, FID regression | Every merge to main |
| `window.performance.memory` | JS heap usage | Every prototype |
| Custom FPS counter (existing `QualityManager`) | Runtime quality degradation | Always-on |
| Screen recording (OBS) | Visual artifact detection | Every prototype |
| `prefers-reduced-motion` simulation | Reduced motion UX quality | Every prototype |
| axe DevTools | Accessibility regression | Every prototype |
| NVDA / VoiceOver | Screen reader compatibility | After HUD implementation |

### 9.3 Regression Checklist

Before merging any experience layer work:

- [ ] **LCP** < previous + 200ms on desktop and mobile
- [ ] **CLS** < previous + 0.01
- [ ] **FID** < previous + 50ms
- [ ] **Desktop FPS** ≥ 50 fps sustained (high tier), ≥ 30 fps (balanced)
- [ ] **Mobile FPS** ≥ 28 fps (balanced tier)
- [ ] **No layout shift** from HUD elements (all `position: fixed`)
- [ ] **All CTAs clickable** — no WebGL overlay blocking pointer events
- [ ] **All text readable** — contrast ratio ≥ 4.5:1 over background
- [ ] **Reduced motion** — no animation except instant state changes
- [ ] **No WebGL fallback** — site fully functional, beautiful, readable
- [ ] **Keyboard navigation** — Tab to CTAs, Enter to activate, Escape to dismiss overlays
- [ ] **Screen reader** — all CTAs have accessible labels, HUD is `aria-hidden` (decorative)
- [ ] **SEO** — no content in WebGL canvas, all text in DOM
- [ ] **A/B test safe** — CTA click-through measured before/after with feature flag

---

## 10. Risk Register & Fallbacks

### 10.1 Risk Table

| # | Risk | Trigger/Symptom | Impact | Likelihood | Mitigation | Fallback |
|---|------|----------------|--------|------------|------------|----------|
| R01 | Reveal mask tanks FPS | FPS < 30 on mid-tier, dropped frames visible | Performance, conversion (slow = bounce) | Medium | Adaptive mask resolution; QualityManager auto-degrades | `balanced`: no blur pass, 512 mask. `low`: Lando-simple radial. `none`: CSS radial-gradient |
| R02 | Reveal looks like circular spotlight | Hard edges, no organic feel, "magnifying glass" | Experience quality, brand (feels cheap) | Low (if pipeline built correctly) | Require brush softness > 0.5, blur pass on high, decay creates organic trail shape | Prototype 1 acceptance test explicitly validates "not a spotlight" |
| R03 | Turn-feel imperceptible | Users don't notice corners vs straights | Wasted effort (no harm, no gain) | Medium | Prototype 2 user testing. If <4/10 detect it, increase yaw range and particle drift | Reduce scope: remove yaw, keep only particle drift direction changes |
| R04 | HUD elements distract from CTAs | Click-through regression in A/B test | Conversion (direct revenue impact) | Low-Medium | HUD positioned in margins, tiny type, low contrast. A/B test feature flag | Hide HUD entirely if A/B shows regression. Timing Tower reverts to SectorTabs |
| R05 | DRS OPEN confuses non-F1 fans | Users confused by "DRS" label | Comprehension | Low | DRS is purely flavor text over a functional boost. Works without understanding. Label optional. | Remove label, keep functional boost. Or replace with "BOOST" |
| R06 | Pit limiter feels "broken" | Users think scroll is stuck in pricing | UX confusion, pricing bounce | Low-Medium | Clear "PIT LANE" label with speed icon. Velocity only damped 0.3x, not locked. | Remove pit limiter entirely if testing shows confusion. Pricing section works fine without it |
| R07 | LivingSurface overdraws GPU | Fill-rate bottleneck from 5 full-screen layers | Performance on mobile/Intel | Medium | Layers are alpha-composited (one draw call via shader). Not 5 separate quads. | `balanced`: 3 layers (grain + particles + vignette). `low`: CSS texture only (existing) |
| R08 | FBO allocation fails | WebGL context loss, out-of-memory on mobile Safari | Crash, white screen | Low | Try/catch FBO creation. Test on 2GB devices. Deferred allocation via `requestIdleCallback`. | Graceful fallback to Lando-simple (no FBO). `FallbackShell` catches and renders CSS-only |
| R09 | Reduced motion feels degraded | Users with `prefers-reduced-motion` get a "broken" experience | Accessibility, brand perception | Low (if designed well) | Spec reduced motion for every component. Prototype 1 validates "premium without motion" | Every effect has an instant-state fallback that still looks intentional |
| R10 | SEO regression from WebGL | Content indexed incorrectly, LCP regression | Organic traffic | Very Low | All content is DOM. Canvas is `aria-hidden`. Lazy-loaded after LCP. | Feature flag to disable entire experience layer for bot user agents |
| R11 | Timing Tower blocks content on mobile | Fixed sidebar covers CTAs on small viewports | Conversion on mobile | Low-Medium | Tower hidden on viewport < 768px. Only Delta HUD (bottom) shown on mobile | Tower auto-hides on mobile. Delta strip (existing) is the only persistent element |
| R12 | Speed streaks cause motion sickness | Rapid line movement triggers vestibular response | Accessibility, health | Low | Streaks are brief (300ms), low contrast, sparse. `prefers-reduced-motion` disables them entirely | Remove streaks if user complaints arise. Background works without them |
| R13 | Checkered finish line misread | Users think it's a progress bar or loading indicator | UX confusion | Very Low | Clearly checkered pattern (F1-universal), paired with "FINISH" label on tower | Remove if confusing. CTA still works without it |
| R14 | Multiple concurrent DRS activations stack | Radius grows uncontrollably if triggers fire rapidly | Visual glitch, performance | Low | DRS state is single-instance. New activation resets timer, doesn't stack multiplier | Cap multiplier at max 1.8x regardless of trigger count |

### 10.2 Fallback Behavior Summary by Quality Tier

| Feature | High | Balanced | Low | No WebGL | Reduced Motion |
|---------|------|----------|-----|----------|---------------|
| Reveal mask | Full pipeline (stamp+decay+blur+advection) | Stamp+decay (no blur, no advection) | Lando-simple radial | CSS radial-gradient | Instant blend, no trail |
| Living surface grain | WebGL noise shader | WebGL noise shader | CSS `.texture-grain` | CSS `.texture-grain` | CSS `.texture-grain` (static) |
| Living surface contours | 30 animated lines | 15 animated lines | None | None | None |
| Living surface particles | 200, drift+attract | 100, drift only | None | None | None |
| Speed streaks | 15, velocity-driven | 8, velocity-driven | None | None | None |
| Vignette | WebGL radial shader | WebGL radial shader | CSS radial-gradient | CSS radial-gradient | CSS radial-gradient |
| Turn-feel (yaw) | CSS rotation 1-4° | CSS rotation 1-2° | None | None | None |
| Post-processing (bloom/noise/chroma) | All three | Bloom + noise only | None | None | None |
| Scene transitions | GLSL shader compositing | Crossfade only | CSS opacity crossfade | CSS opacity crossfade | Instant cut |
| Timing Tower | Animated progress + sweep | Animated progress + sweep | Animated progress (no sweep) | Animated progress (no sweep) | Instant state changes |
| Delta HUD | Jitter + settle animation | Jitter + settle animation | Static value, updates on section | Static value | Static value |
| DRS label | Animated appear/disappear | Animated appear/disappear | Animated appear/disappear | Animated appear/disappear | Instant appear/disappear |
| Track map | Smooth dot movement | Smooth dot movement | Dot jumps between sections | Dot jumps between sections | Dot jumps |
| Pit wheel | Rotation + friction | Rotation + friction | Static wheel | None | Static wheel |
| Finish line | Animated sweep | Animated sweep | Instant appear | Instant appear | Instant appear |
| Safety Car label | — | — | — | "SAFETY CAR MODE" text in corner | — |

---

## 11. Traceability Matrix

| # | Requirement | Design Decision | QA Validation |
|---|------------|-----------------|---------------|
| T01 | "Reveal must not resemble a basic circular spotlight" | Persistence buffer (decay factor 0.985 creates organic trailing shape), blur pass softens edges, brush softness 0.6 default. Inertia lag causes brush stamps to overlap and create elongated blobs on movement. | **Test**: Move cursor in a circle. Screenshot. Compare to a circular spotlight image. Trail must be visible and shape must be non-circular/organic. **Metric**: Trail persistence visible for ≥ 2s. **Artifact**: Before/after screenshot comparison. |
| T02 | "Sectors turn racing purple (#D946EF) on completion" | `SectorGateController` sets `tower.sectors[i].color = '#D946EF'` on gate trigger. CSS transition on tower label elements. | **Test**: Scroll past chapter 2 into chapter 3. Observe Timing Tower. **Metric**: S1 label is #D946EF within 400ms. **Artifact**: Screen recording with color picker overlay. |
| T03 | "DRS OPEN does something functional" | `drsRadiusMultiplier: 1.4x` applied to reveal brush radius. `streakIntensity` multiplied by 1.3x. ChromaticAberration adds 0.001 baseline. All measurable changes to visual output. | **Test**: Trigger DRS (flip a card in S1). Measure reveal radius before/during/after. **Metric**: Radius ≥ 1.3x baseline during DRS. **Artifact**: Screen recording with radius measurement overlay. |
| T04 | "Background feels like taking turns" | Track path spline assigns headings per chapter. Corners (chapters 1,3,5,7) get headingDelta > 0 which drives: particle lateral drift, CSS yaw rotation (1-4°), vignette shift, speed streak direction. | **Test**: Scroll slowly from chapter 2 (straight) into chapter 3 (corner L). Observe particle drift direction + canvas yaw. **Metric**: 6/10 users describe directional change when asked "what did you notice about the background?" **Artifact**: User test recordings + survey responses. |
| T05 | "Critical CTAs remain readable and DOM" | All CTAs render as DOM `<button>` or `<a>` elements. WebGL canvas has `pointer-events: none`. All text uses contrast ratio ≥ 4.5:1 (verified by existing palette). HUD uses `z-index` lower than overlay/nav. | **Test**: Tab through page. All CTAs receive focus. Click every CTA — all respond. **Metric**: 0 CTAs obscured or unclickable. **Artifact**: axe DevTools report + manual focus audit recording. |
| T06 | "Reduced motion remains premium" | Every component specifies explicit reduced motion behavior. Reveal: instant blend (no trail but still reveals truth). Tower: instant color change. Delta: static. Background: CSS grain only (still textured, not blank). | **Test**: Enable `prefers-reduced-motion: reduce`. Navigate full page. **Metric**: 7/10 testers rate experience as "polished" (not "broken" or "basic"). **Artifact**: User test survey + screen recording of reduced motion path. |
| T07 | "No material SEO/performance regression" | All content in DOM. Canvas is `aria-hidden`. Experience layer lazy-loaded after LCP. Feature flag `EXPERIENCE_LAYER_V2` for A/B testing. | **Test**: Lighthouse before/after. Googlebot rendering check. **Metric**: LCP < +200ms, CLS < +0.01, no content missing from Googlebot render. **Artifact**: Lighthouse CI reports (before/after comparison). |
| T08 | "Preserve existing funnel structure and CTAs" | All 11 rooms preserved in exact order. No room removed, split, or reordered. CTAs unchanged. Only augmented with WebGL layer behind and HUD chrome around. | **Test**: Compare section order and CTA text/links before/after. **Metric**: Identical section count, identical CTA destinations. **Artifact**: Diff of marketing page.tsx room list. |
| T09 | "Mobile: finger-drag reveal + tap burst reveal" | `RevealMaskPipeline` detects `ontouchstart`. Touch: continuous drag stamps mask at finger position. Tap: burst stamp at `mobileBurstRadius: 120px` with `mobileBurstDecay: 0.96`. | **Test**: On iPhone 15 Pro: (1) tap hero → burst circle appears and fades. (2) Drag across hero → trail follows finger. **Metric**: Reveal visible on both gestures. FPS ≥ 28. **Artifact**: iOS screen recording. |
| T10 | "Timing Tower persistent and minimal" | `position: fixed`, left rail, replaces `SectorTabs`. Width ≤ 60px. `font-telemetry` at 12px. Hidden on viewport < 768px. | **Test**: Scroll full page. Tower visible at all times on desktop. Hidden on iPhone. **Metric**: Tower never overlaps room content by > 10px. **Artifact**: Screenshot at each section + responsive check. |
| T11 | "Delta HUD jitter reduces as truth revealed" | `deltaJitter = lerp(8, 0, maskCoverage)`. `maskCoverage` updated per frame from FBO readback (sampled at 1/16 resolution). | **Test**: (1) Idle on hero without moving cursor → jitter at maximum (8px). (2) Reveal 50% of hero → jitter at ~4px. (3) Reveal 90% → jitter near 0. **Metric**: Jitter amplitude correlates with mask coverage. **Artifact**: Screen recording + overlay showing maskCoverage value. |
| T12 | "Pit limiter caps scroll velocity response" | `velocityMultiplier: 0.3` in chapter 8. Applied in LivingSurface and PostStack. Wheel rotation capped. | **Test**: Fast scroll through chapters 7→8. Observe: particle drift, speed streaks, chroma aberration all reduce when entering pit stop. **Metric**: Visible reduction in motion intensity. **Artifact**: Side-by-side recording of chapter 7 vs chapter 8 at same scroll speed. |
| T13 | "Finish line simulates crossing" | Checkered band animates across viewport in 600ms. Tower sectors all turn purple. Delta settles to 0.000. | **Test**: Scroll into chapter 10. Observe: band, tower, delta. **Metric**: All three events fire within 600ms window. **Artifact**: Screen recording of finish sequence. |
| T14 | "Radio message cards replace generic tooltips" | `RadioCard` component with compact/expanded states. Engineer→Driver framing. Waveform animation. Generic motorsport language. | **Test**: Hover a feature explanation → compact radio card. Click → expanded with waveform. **Metric**: Card appears within 120ms of hover, expands within 420ms of click. **Artifact**: Interaction recording. |
| T15 | "Track cards with 3D tilt/parallax" | CSS `perspective: 1200px`, `transform: rotateX(Ydeg) rotateY(Xdeg)`. Max ±8°. Parallax shift 3px. | **Test**: Move cursor across a track card in S4. Observe tilt direction. **Metric**: Tilt follows pointer, max 8°, smooth (no jank). **Artifact**: Recording + DevTools performance trace during hover. |
| T16 | "Orchestrator is single source of truth" | All state flows through `useKernelStore` (extended). No component reads raw DOM scroll or pointer directly (all through controllers). | **Test**: Add console.log in store actions. Verify all input flows through store, not direct event handlers. **Metric**: 0 direct `addEventListener('scroll')` or `addEventListener('mousemove')` outside controllers. **Artifact**: Grep for raw event listeners (should find only in controller files). |
| T17 | "WebGL is experience layer behind/around DOM, not replacement" | Canvas has `pointer-events: none`, `z-index: 0`. All text, buttons, inputs are DOM. HUD is DOM. | **Test**: Disable WebGL (block canvas creation). All content and CTAs still visible and functional. **Metric**: 100% functional without WebGL. **Artifact**: Recording of site with WebGL disabled. |
| T18 | "Accessibility first-class: keyboard navigation" | All CTAs focusable. `SectorTabs`/`TimingTower` buttons keyboard-accessible. Focus trap on overlays (existing). `aria-hidden` on decorative elements. | **Test**: Navigate entire page using only keyboard (Tab, Enter, Escape, arrow keys). **Metric**: All CTAs reachable, all overlays dismissable, no focus trap escapes. **Artifact**: Keyboard navigation recording + axe report. |
| T19 | "Conversion strength sacred" | A/B test with feature flag `EXPERIENCE_LAYER_V2`. Measure CTA click-through, pricing engagement, bounce rate. | **Test**: Run A/B test for 2 weeks (minimum 1000 visitors per variant). **Metric**: Experience variant CTR ≥ control variant CTR (95% confidence). **Artifact**: Analytics dashboard screenshot. |

---

## Appendices

### A. Color Token Addition

Add to `tailwind.config.ts` and `tokens.css`:

```
racing-purple: #D946EF
```

Usage: Timing Tower sector completion, personal-best indicators, sector gate sweep line.

### B. New Design Tokens (CSS Custom Properties)

```css
/* Narrative timing */
--duration-sector-gate: 400ms;
--duration-drs: 2000ms;
--duration-pit: 600ms;
--duration-finish: 600ms;

/* Narrative easing */
--ease-sector-gate: cubic-bezier(0.0, 0, 0.2, 1);
--ease-pit-enter: cubic-bezier(0.8, 0, 1, 1);
--ease-pit-exit: cubic-bezier(0, 0, 0.2, 1);

/* Z-index extensions */
--z-hud: 35;        /* between stamps(20) and delta(30) — or redefine */
--z-drs: 36;
--z-finish-line: 37;
```

### C. Track Path Spline Data

```typescript
const TRACK_PATH: ChapterPathConfig[] = [
  { chapter: 0,  heading: 0,    type: 'straight', label: 'Start Grid' },
  { chapter: 1,  heading: 35,   type: 'corner-r', label: 'S1 Pain' },
  { chapter: 2,  heading: 35,   type: 'straight', label: 'S1 Deep' },
  { chapter: 3,  heading: -20,  type: 'corner-l', label: 'S2 Pipeline' },
  { chapter: 4,  heading: -20,  type: 'straight', label: 'S2 Proof' },
  { chapter: 5,  heading: 25,   type: 'corner-r', label: 'S3 Product' },
  { chapter: 6,  heading: 25,   type: 'straight', label: 'S4 Workflows' },
  { chapter: 7,  heading: 40,   type: 'corner-r', label: 'S5 Personas' },
  { chapter: 8,  heading: 0,    type: 'pit-lane', label: 'Pit Stop' },
  { chapter: 9,  heading: 0,    type: 'straight', label: 'Garage' },
  { chapter: 10, heading: 0,    type: 'straight', label: 'Podium' },
];
```

### D. File Structure (New Modules)

```
src/experience/
├── reveal/
│   ├── RevealMaskPipeline.tsx       # R3F FBO ping-pong reveal system
│   ├── useRevealState.ts            # Hook for mask coverage + brush state
│   ├── RevealSubjects.tsx           # Layer A/B content per chapter
│   └── shaders/
│       ├── mask-stamp.glsl          # Soft brush stamp
│       ├── mask-decay.glsl          # Persistence decay pass
│       ├── mask-blur.glsl           # Separable Gaussian blur
│       └── reveal-blend.glsl        # Final A/B composite
├── narrative/
│   ├── SectorGateController.tsx     # Sector gate event orchestration
│   ├── TrackPath.ts                 # Track spline data + heading interpolation
│   ├── DrsController.tsx            # DRS activation/deactivation logic
│   └── PitModeController.tsx        # Pit limiter engage/disengage
├── renderer/scenes/
│   └── LivingSurface.tsx            # Extended AtmosphereBase (5 depth layers)
└── state/
    └── types.ts                     # Extended with HudState, RevealState, etc.

src/components/chrome/
├── TimingTower.tsx                  # Replaces SectorTabs
├── DeltaHud.tsx                     # Extended DeltaStrip
├── MiniTrackMap.tsx                 # SVG track + animated dot
├── DrsLabel.tsx                     # DRS OPEN animated label
├── FinishLine.tsx                   # Checkered band animation
├── RadioCard.tsx                    # F1-style explanation card
└── PitWheel.tsx                     # Background wheel SVG + rotation

src/components/ui/
└── TrackCard.tsx                    # 3D tilt card for S4/S5
```

---

*End of blueprint. Pending approval before implementation planning.*
