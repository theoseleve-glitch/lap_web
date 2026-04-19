# Awwwards-Level Homepage Upgrade — Design Spec

## Goal
Transform the Lap marketing homepage from a well-structured but static SaaS page into an award-worthy immersive experience. The architecture is already sophisticated (ExperienceKernel, GSAP, R3F, Lenis, Howler all installed) — most of it is dormant. This upgrade activates the engine.

## Constraints
- **Color tokens**: All existing `tokens.css` colors. No raw hex. No new colors.
- **Fonts**: Keep Space Grotesk / Inter / Space Mono — already distinctive.
- **Deployment**: Cloudflare Workers via OpenNext. No server-dependent APIs.
- **Accessibility**: `prefers-reduced-motion` must disable all new animations. WCAG AA contrast. Keyboard navigable.
- **Performance**: Only animate `transform` and `opacity` (plus `filter` for blur). Code-split heavy libs. 60fps desktop, 45fps+ mobile.
- **Mobile**: Disable/simplify WebGL. Touch-friendly 44px targets. Swipe replaces hover.

## Architecture Decisions

### Lenis Integration
Initialize in `ExperienceShell` → `HomepageShell`. Sync with GSAP ScrollTrigger via `lenis.on('scroll', ScrollTrigger.update)`. Destroy on unmount. Skip on reduced-motion.

### Split-Text Hero
Manual character splitting (no GSAP SplitText plugin — it's paid). Wrap each word in a `<span>`, each char in a nested `<span>`. GSAP staggers chars with `power4.out` easing. Scroll-scrubbed parallax on the hero section (y + opacity + scale).

### 3D Signature Moment: Track Ribbon
Reactivate `BackgroundScene` to render `TrackRibbon` — a glowing racing line that follows scroll progress. Speed increases as user scrolls faster. Metallic/gold material matching `--pit-orange`. Disable on mobile/low-GPU via `useGpuCapability`.

### Pinned Pipeline Section (S3Product)
Pin the section container. Each pipeline step reveals via scrub as user scrolls through. Step indicator animates, content fades/slides. 7 steps = 7 scroll-lengths pinned.

### Grain Overlay
CSS `::after` pseudo-element on `body` with SVG noise filter. `pointer-events: none`, `mix-blend-mode: overlay`, `opacity: 0.03`. Eliminates digital flatness.

### Magnetic Buttons
`useMagnetic` hook — tracks mouse position relative to button center. When within 80px radius, applies `transform: translate(dx, dy)` with spring easing. Applied to all primary CTAs.

### Preloader
Racing countdown sequence: "5 — 4 — 3 — 2 — 1 — GO". Monument text, center screen. Gold accent. Engine rev sound via Howler (fade in from silence). Minimum 2.5s duration. On exit: elements stagger in with 80ms delays. Uses `sessionStorage` flag to skip on return visits within session.

### Page Transitions
View Transitions API (CSS `view-transition-name` + `startViewTransition()`). Fallback: simple opacity crossfade for unsupported browsers. 300ms exit, 400ms enter.

### Sound Design
- Ambient: Low engine hum, volume 0.08, loop. Starts after preloader.
- Click: Short mechanical click on CTA buttons.
- Hover: Subtle whoosh on nav links.
- Mute toggle: Persistent button in bottom-right, remembers preference in `localStorage`.

### Enhanced Cursor
Extend `CustomCursor.tsx`:
- On links: grow to 24px, show glow
- On CTA buttons: grow to 40px, text "GO" appears inside
- On cards: grow to 32px, text "VIEW" appears
- On images: text "EXPLORE"
- Uses `data-cursor` attributes on target elements

### Parallax System
`useParallax` hook wrapping GSAP ScrollTrigger scrub. Applies `translateY` offset at configurable speed (0.8x for images, 1.2x for text accents). Used in S1Pain comparison cards, S2Versus columns, Garage result cards.

### Horizontal Scroll (S3Product alternative)
The 7-step pipeline scrolls horizontally within a vertically-pinned container. Each card is full viewport width. Progress indicator shows current step. Replaces the vertical timeline.

### Grid-Breaking Elements
- Hero: Product preview card offset -40px from center, rotated 1deg
- S2Versus: "COACHING-FIRST" card overlaps the left card by 20px on desktop
- Garage: Founder avatar breaks out of the card container, offset up -30px
- Podium: CTA button group positioned asymmetrically (60/40 split, not centered)

### Section Entrance Upgrades
Replace simple `opacity+y` with:
- `translateY(60px)` + `opacity: 0` + `scale(0.97)` + `filter: blur(6px)`
- Stagger children by 100ms
- Ease: `power3.out` for entrances
- Start: `top 80%`

### Background Color Transitions
CSS `background-color` transitions on `<main>` driven by `data-accent` attribute of the active section (detected via IntersectionObserver). Subtle shift — e.g., pure black → slightly warm-tinted black near gold sections.

### Scrollbar
Hide native scrollbar via CSS. Replace with thin 2px track on right edge, accent-colored thumb. Positioned via `position: fixed`.

## Section Flow (Updated)

```
[PRELOADER: 5-4-3-2-1-GO countdown]
  ↓ stagger entrance
[STARTGRID: Split-text hero + scroll-scrubbed parallax + 3D track ribbon behind]
  ↓ scroll
[SESSION PROOF: Staggered card cascade + parallax offsets]
  ↓ scroll
[S1 PAIN: Comparison columns with overlap + parallax]
  ↓ scroll
[S2 VERSUS: Asymmetric grid + coaching card overlap]
  ↓ scroll
[S3 PRODUCT: PINNED horizontal scroll pipeline — THE signature section]
  ↓ release pin
[SIM FIRST: Standard entrance + parallax cards]
  ↓ scroll
[PREMIUM LAYER: Hover-glow cards with magnetic effect + stagger]
  ↓ scroll
[GARAGE: Grid-breaking founder avatar + stat counter animation]
  ↓ scroll
[PIT STOP: Pricing with magnetic CTAs + billing toggle animation]
  ↓ scroll
[PODIUM: Mix-blend-mode headline + final magnetic CTA]
```

## Files Modified (estimated)
- `ExperienceShell.tsx` — Lenis init
- `MotionOrchestrator.tsx` — Upgraded section animations, parallax
- `BackgroundScene.tsx` — Reactivate 3D
- `CustomCursor.tsx` — Text labels
- `MonumentText.tsx` — Split-text mode
- `StartGrid.tsx` — Hero overhaul
- `SessionProof.tsx` — Stagger + parallax
- `S1Pain.tsx` — Overlap + parallax
- `S2Versus.tsx` — Asymmetric grid + overlap
- `S3Product.tsx` — Horizontal scroll pin
- `SimFirst.tsx` — Entrance upgrade
- `PremiumLayer.tsx` — Magnetic cards
- `Garage.tsx` — Grid-break + counter
- `PitStop.tsx` — Magnetic CTAs
- `Podium.tsx` — Blend mode + magnetic
- `tokens.css` — Grain overlay, scrollbar
- New: `src/hooks/useMagnetic.ts`
- New: `src/hooks/useLenis.ts`
- New: `src/hooks/useParallax.ts`
- New: `src/components/chrome/Preloader.tsx`
- New: `src/components/chrome/SoundToggle.tsx`
- New: `src/components/chrome/GrainOverlay.tsx`
- New: `src/lib/sound-manager.ts`
- New: `src/components/ui/SplitText.tsx`
