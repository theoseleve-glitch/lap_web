# V2 Experience Kernel — Design Document

**Date:** 2026-02-27
**Status:** Approved
**Scope:** Marketing homepage experience upgrade (V1 → V2)

## Summary

Evolve the lap-website marketing homepage from a DOM + Canvas 2D site into a monumental installation experience. Add an Experience Kernel that centralizes all animation, interaction, and rendering through a single orchestrator. WebGL atmosphere layer behind DOM content, virtual scroll with damping, composited shader transitions, pointer magnetism, upgraded instrument interaction, and a crafted preloader ritual.

**Non-goal:** No changes to content, copy, CTAs, page routes, or information architecture.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| WebGL engine | Three.js + R3F | Already installed, zero new bundle weight, React-native integration |
| Scroll | Lenis + GSAP ScrollTrigger | Damped virtual scroll with accessibility, ST for scrub/pin |
| Transitions | WebGL-only RTT + synchronized DOM CSS | Composited without html2canvas overhead |
| Instrument | Upgraded CornerDrag + WebGL reactivity | Already product-narrative-aligned ("find the line") |
| Integration | Kernel-First Rewrite (Approach A) | Cleanest architecture, rooms become pure registrations |

## Architecture

### Layer Model

```
┌─────────────────────────────────────────┐  z-index
│  Layer 3: Chrome (cursor, HUD, overlay) │  999+
├─────────────────────────────────────────┤
│  Layer 2: DOM Rooms (content, CTAs)     │  10-100
├─────────────────────────────────────────┤
│  Layer 1: R3F Canvas (atmosphere,       │  0
│           transitions, effects)         │
└─────────────────────────────────────────┘
```

### File Tree

```
src/experience/                    # Experience Kernel
├── ExperienceKernel.tsx           # Root provider — state machine + all sub-providers
├── ExperienceShell.tsx            # Replaces ChromeLayout for marketing home
│
├── state/
│   ├── machine.ts                 # State machine (chapter, mode, progress)
│   ├── types.ts                   # All state types + events
│   └── store.ts                   # Zustand store (single source of truth)
│
├── input/
│   ├── ScrollController.tsx       # Lenis + ScrollTrigger integration
│   ├── PointerField.tsx           # Pointer position + magnetism vector
│   └── InputManager.tsx           # Unified input: scroll + pointer + drag + keyboard
│
├── renderer/
│   ├── ExperienceCanvas.tsx       # R3F <Canvas> — fixed fullscreen behind DOM
│   ├── SceneManager.tsx           # Mounts/unmounts per-chapter 3D scenes
│   ├── PostStack.tsx              # EffectComposer (bloom/grain/chromatic/blur)
│   └── scenes/                    # Per-chapter atmosphere scenes
│       ├── StartGridScene.tsx
│       ├── S1Scene.tsx
│       ├── S2Scene.tsx
│       ├── S3Scene.tsx
│       ├── S4Scene.tsx
│       ├── S5Scene.tsx
│       ├── PitStopScene.tsx
│       ├── GarageScene.tsx
│       └── PodiumScene.tsx
│
├── transitions/
│   ├── TransitionCompositor.tsx   # Orchestrates outgoing→incoming scene swap
│   ├── shaders/
│   │   ├── crossfade-blur.glsl   # Transition A: crossfade + blur resolve
│   │   ├── mask-wipe.glsl        # Transition B: brutal slab mask wipe
│   │   ├── velocity-warp.glsl    # Transition C: velocity-linked smear
│   │   └── refraction.glsl       # Transition D: glass refraction reveal
│   └── TransitionLibrary.ts      # Registry: chapter pairs → transition type
│
├── motion/
│   ├── MotionOrchestrator.tsx     # Timeline primitives: enter/exit/scrub/spring
│   ├── springs.ts                 # Spring physics constants
│   └── timeline.ts               # GSAP timeline factory with kernel-aware easing
│
├── quality/
│   ├── QualityManager.tsx         # Auto-degrade: High/Balanced/Low/Auto
│   ├── FallbackShell.tsx          # DOM-only fallback when WebGL fails
│   └── DebugHUD.tsx               # Dev overlay: FPS, quality, chapter, progress
│
├── preloader/
│   ├── Preloader.tsx              # Crafted entry ritual sequence
│   ├── PreloaderTimeline.ts       # Staged load: critical → progressive → unlock
│   └── PreloaderScene.tsx         # R3F scene during load
│
└── hooks/
    ├── useKernel.ts               # Access kernel state from any component
    ├── useChapter.ts              # Current chapter + progress within chapter
    ├── useScrollVelocity.ts       # Damped scroll velocity for shader uniforms
    ├── usePointerInfluence.ts     # Pointer magnetism for interactive elements
    └── useQuality.ts              # Current quality tier for conditional rendering
```

### Kernel State Shape (Zustand)

```typescript
interface KernelState {
  // Chapter system
  currentChapter: number;           // 0-10 (index into rooms array)
  chapterProgress: number;          // 0..1 within current chapter
  globalProgress: number;           // 0..1 across entire page

  // Scroll
  scrollY: number;                  // Virtual scroll position (Lenis)
  scrollVelocity: number;           // Damped velocity (-1..1 normalized)
  scrollDirection: 'up' | 'down' | 'idle';

  // Pointer
  pointerX: number;                 // 0..1 normalized
  pointerY: number;                 // 0..1 normalized
  pointerMagnetism: { x: number; y: number };

  // Interaction mode
  mode: 'preloading' | 'idle' | 'scrolling' | 'dragging' | 'transitioning';

  // Quality
  qualityTier: 'high' | 'balanced' | 'low';
  qualityMode: 'auto' | 'manual';
  reducedMotion: boolean;
  webglAvailable: boolean;

  // Preloader
  loadProgress: number;
  preloaderComplete: boolean;
}
```

### State Machine Transitions

```
preloading ──[assets loaded]──→ idle
idle       ──[scroll start]───→ scrolling
idle       ──[drag start]────→ dragging
scrolling  ──[chapter boundary]→ transitioning ──[transition done]→ idle
scrolling  ──[scroll stop]───→ idle
dragging   ──[drag end]──────→ idle
```

### Chapter Registration Pattern

```typescript
export const startGridConfig: ChapterConfig = {
  id: 'start-grid',
  index: 0,
  scene: StartGridScene,
  transition: {
    enter: 'preloader-unlock',
    exit: 'crossfade-blur',
  },
  snapWeight: 1.0,
  accentColor: 'none',
};
```

## Motion Spec

### Timing

| Token | Value | Use |
|-------|-------|-----|
| `micro` | 420ms | Hover, underline, tooltip, button press |
| `room` | 900ms | Chapter transition, scroll snap settle |
| `monument` | 1400ms | Monument text reveal, preloader unlock, wow moments |

### Easing

| Token | GSAP | CSS | Use |
|-------|------|-----|-----|
| `inertia` | `power3.out` | `cubic-bezier(0.16, 1, 0.3, 1)` | Default motion |
| `overshoot` | `back.out(1.7)` | `cubic-bezier(0.34, 1.56, 0.64, 1)` | Large reveals |
| `spring` | `back.out(1.2)` | `cubic-bezier(0.22, 1.2, 0.36, 1)` | Button rebound |
| `snap` | `power2.in` | `cubic-bezier(0.7, 0, 0.84, 0)` | Snap-to-chapter |
| `anticipate` | `power2.inOut` | `cubic-bezier(0.45, 0, 0.55, 1)` | Pre-move wind-up |

### Physics Constants

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
} as const;
```

### Snap Rules

- Each chapter is a snap point with weight 1.0
- Velocity below |0.05| triggers snap
- Snap: `power2.in` pull, `power3.out` settle, 900ms duration
- Snap disabled during `dragging` mode

## Transition Library

### 4 Transitions

| ID | Name | Logic |
|----|------|-------|
| A | `crossfade-blur` | Lerp between scenes; outgoing blurs 0→8px, incoming resolves 8→0px |
| B | `mask-wipe` | Horizontal slab mask left→right, 2px feather, accent leading edge |
| C | `velocity-warp` | Scene warps in scroll direction, intensity = velocity * 0.3 |
| D | `refraction` | Glass distortion field; incoming emerges as refraction clears |

### Chapter → Transition Map

```typescript
export const transitionMap = {
  'start-grid→s1-pain':      'refraction',
  's1-pain→s1-deep':         'crossfade-blur',
  's1-deep→s2-pipeline':     'mask-wipe',
  's2-pipeline→s2-proof':    'crossfade-blur',
  's2-proof→s3-product':     'mask-wipe',
  's3-product→s4-workflows': 'crossfade-blur',
  's4-workflows→s5-personas':'velocity-warp',
  's5-personas→pit-stop':    'mask-wipe',
  'pit-stop→garage':         'crossfade-blur',
  'garage→podium':           'refraction',
};
```

### DOM Synchronization

- `.room-exiting`: opacity 0, blur 8px, translateY(-20px) over `room` duration
- `.room-entering`: opacity 1, blur 0, translateY(0) over `room` duration
- Timed by kernel's motion orchestrator (no separate setTimeout)

## Quality & Performance

### Quality Tiers

| Tier | Render Scale | Post Passes | Particles |
|------|-------------|-------------|-----------|
| High | 1.0 | All | Full |
| Balanced | 0.75 | Bloom + grain | 50% |
| Low | 0.5 | None | Disabled |

### Auto-Degrade

- avg < 45fps for 2s → drop one tier
- avg < 30fps for 1s → drop to Low immediately
- avg > 55fps for 5s → promote one tier (never above initial)

### WebGL Fallback

- No R3F canvas mounted
- CSS-only atmosphere (texture-grain, radial gradients)
- CSS-only crossfade transitions
- Lenis scroll still active
- All content and interactions preserved

### Reduced Motion

- Lenis lerp set to 0.9 (near-instant)
- Post-processing disabled
- Transitions → instant crossfade
- Pointer magnetism disabled
- Monument reveals → instant
- CornerDrag WebGL effects disabled

## Preloader Ritual

1. Black screen (300ms)
2. "LAP" wordmark fades in (1400ms, inertia ease)
3. Progress bar beneath wordmark (real asset load)
4. Stages: critical (0-40%) → scenes (40-80%) → progressive (80-100%)
5. "READY" text on completion (420ms fade)
6. Click/tap/scroll → refraction transition into StartGrid
7. Auto-unlock after 3s if no interaction

## Microinteractions

- **Links:** Animated underline left→right on hover (micro), accent color
- **Buttons:** Scale 1→1.02 hover, 0.97 press, 1.0 rebound (overshoot ease)
- **Tooltips:** 400ms delay, fade + translateY(4px→0) over micro
- **Cursor:** 8px idle ring → 24px interactive + magnetism pull → 6px drag dot

## Acceptance Criteria

1. [ ] Every chapter enter/exit has authored WebGL + DOM transition
2. [ ] No default-feeling interactions (links, buttons, scroll)
3. [ ] "Alive cursor" test: stop scrolling, move cursor — site responds
4. [ ] CTAs remain obvious and readable at all quality tiers
5. [ ] Reduced motion mode works
6. [ ] WebGL fallback: fully functional CSS-only
7. [ ] Preloader ritual plays on first visit
8. [ ] CornerDrag instrument: WebGL reacts to drag
9. [ ] 60fps desktop (High), 40-60fps mobile (Balanced)
10. [ ] Auto quality degradation works
11. [ ] Debug HUD via Ctrl+Shift+D
12. [ ] All V1 content/copy/CTAs/routes preserved
13. [ ] Keyboard navigation: focusable CTAs, visible focus states
