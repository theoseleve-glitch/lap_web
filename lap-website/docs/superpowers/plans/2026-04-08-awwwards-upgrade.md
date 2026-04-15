# Awwwards-Level Homepage Upgrade — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the Lap homepage from a static SaaS page into an immersive, award-worthy experience by activating the dormant ExperienceKernel, adding Lenis smooth scroll, scroll-driven animations, 3D background, preloader, sound design, and micro-interactions.

**Architecture:** The site already has GSAP+ScrollTrigger, Lenis, Three.js+R3F, and Howler.js installed but dormant. Most work is wiring up existing infrastructure + upgrading the 10 homepage room components with scroll choreography, parallax, grid-breaking layouts, and interaction polish.

**Tech Stack:** Next.js 14 (App Router), GSAP 3 + ScrollTrigger, Lenis 1.3, Three.js + R3F, Howler.js, Tailwind CSS, existing design tokens from tokens.css.

---

## File Map

### New Files
| File | Responsibility |
|------|---------------|
| `src/hooks/useLenis.ts` | Lenis init + GSAP sync hook |
| `src/hooks/useMagnetic.ts` | Magnetic hover effect for buttons |
| `src/hooks/useParallax.ts` | ScrollTrigger-driven parallax offset |
| `src/hooks/useSplitText.ts` | Character-level text splitting for animation |
| `src/hooks/useCountUp.ts` | Animated number counter on scroll entry |
| `src/components/chrome/Preloader.tsx` | Racing countdown preloader |
| `src/components/chrome/GrainOverlay.tsx` | SVG noise texture overlay |
| `src/components/chrome/SoundToggle.tsx` | Mute/unmute button |
| `src/components/chrome/CustomScrollbar.tsx` | Thin accent scrollbar replacement |
| `src/lib/sound-manager.ts` | Howler.js singleton for ambient + interaction sounds |

### Modified Files
| File | Changes |
|------|---------|
| `src/experience/ExperienceShell.tsx` | Add Lenis init, preloader, grain, sound, scrollbar |
| `src/experience/motion/MotionOrchestrator.tsx` | Upgraded section entrances, parallax, velocity skew |
| `src/experience/background/BackgroundScene.tsx` | Reactivate TrackRibbon + SpeedStreaks |
| `src/components/chrome/CustomCursor.tsx` | Text labels (GO, VIEW, EXPLORE) |
| `src/components/ui/MonumentText.tsx` | Split-text animation mode |
| `src/components/rooms/StartGrid.tsx` | Split-text hero, scroll-scrub, asymmetric product card |
| `src/components/rooms/SessionProof.tsx` | Stagger cascade, parallax offsets |
| `src/components/rooms/S1Pain.tsx` | Overlap layout, parallax |
| `src/components/rooms/S2Versus.tsx` | Asymmetric grid, coaching card overlap |
| `src/components/rooms/S3Product.tsx` | Horizontal scroll pinned section |
| `src/components/rooms/SimFirst.tsx` | Entrance upgrade |
| `src/components/rooms/PremiumLayer.tsx` | Magnetic cards |
| `src/components/rooms/Garage.tsx` | Grid-break avatar, counter animation |
| `src/components/rooms/PitStop.tsx` | Magnetic CTAs |
| `src/components/rooms/Podium.tsx` | Mix-blend-mode headline, magnetic CTA |
| `src/styles/tokens.css` | Scrollbar hide, grain base styles, section bg tints, Lenis |

---

## Task 1: Lenis Smooth Scroll + GSAP Sync

**Files:**
- Create: `src/hooks/useLenis.ts`
- Modify: `src/experience/ExperienceShell.tsx`
- Modify: `src/styles/tokens.css`

- [ ] **Step 1: Create useLenis hook** — `src/hooks/useLenis.ts`
- [ ] **Step 2: Wire Lenis into HomepageShell** — add `useLenis(!reducedMotion)` call
- [ ] **Step 3: Add Lenis CSS to tokens.css** — `html.lenis { scroll-behavior: auto; height: auto; }`
- [ ] **Step 4: Verify smooth scroll active on dev server**
- [ ] **Step 5: Commit**

---

## Task 2: Grain Overlay + Custom Scrollbar

**Files:**
- Create: `src/components/chrome/GrainOverlay.tsx`
- Create: `src/components/chrome/CustomScrollbar.tsx`
- Modify: `src/styles/tokens.css`
- Modify: `src/experience/ExperienceShell.tsx`

- [ ] **Step 1: Create GrainOverlay** — fixed overlay with SVG noise, `mix-blend-overlay`, `opacity: 0.035`
- [ ] **Step 2: Create CustomScrollbar** — fixed 3px track, gold thumb, fades after 1.2s idle
- [ ] **Step 3: Hide native scrollbar in tokens.css** — `scrollbar-width: none` + webkit
- [ ] **Step 4: Add both to ExperienceContent in ExperienceShell.tsx**
- [ ] **Step 5: Verify grain + scrollbar**
- [ ] **Step 6: Commit**

---

## Task 3: SplitText Hook + MonumentText Upgrade

**Files:**
- Create: `src/hooks/useSplitText.ts`
- Modify: `src/components/ui/MonumentText.tsx`

- [ ] **Step 1: Create useSplitText hook** — walks DOM childNodes, wraps each character in a span with class `split-char` using DOM createElement (NOT innerHTML for safety), then GSAP staggers with `opacity + y + rotateX` entrance
- [ ] **Step 2: Add `split` and `scrub` props to MonumentText** — when `split` is true, uses useSplitText ref instead of data-monument-reveal
- [ ] **Step 3: Test on S1Pain headline** — change `reveal` to `split`
- [ ] **Step 4: Verify character-by-character animation**
- [ ] **Step 5: Commit**

---

## Task 4: useMagnetic + useParallax + useCountUp Hooks

**Files:**
- Create: `src/hooks/useMagnetic.ts`
- Create: `src/hooks/useParallax.ts`
- Create: `src/hooks/useCountUp.ts`

- [ ] **Step 1: Create useMagnetic** — tracks mouse distance from button center, applies `gsap.to(x, y)` when within radius, elastic snap-back on leave
- [ ] **Step 2: Create useParallax** — ScrollTrigger scrub with configurable speed multiplier on translateY
- [ ] **Step 3: Create useCountUp** — IntersectionObserver triggers requestAnimationFrame counter with ease-out quad
- [ ] **Step 4: Commit**

---

## Task 5: Hero Overhaul (StartGrid)

**Files:**
- Modify: `src/components/rooms/StartGrid.tsx`

- [ ] **Step 1: Rewrite StartGrid** — split-text headline, scroll-scrubbed parallax (content fades up on scroll), magnetic CTAs via useMagnetic, asymmetric product card (`md:translate-x-8 md:rotate-[0.5deg]`), staggered entrance for sub-elements via `data-hero-stagger`, `data-cursor="GO"` on CTA
- [ ] **Step 2: Verify hero entrance + scroll parallax + magnetic pull**
- [ ] **Step 3: Commit**

---

## Task 6: Upgraded MotionOrchestrator

**Files:**
- Modify: `src/experience/motion/MotionOrchestrator.tsx`
- Modify: `src/components/rooms/S1Pain.tsx`
- Modify: `src/components/rooms/S2Versus.tsx`

- [ ] **Step 1: Upgrade section entrance animations** — replace simple `opacity+y` with `translateY(50px) + opacity: 0 + scale(0.97) + filter: blur(4px)`, stagger 0.1s between children, `power3.out` ease, start at `top 75%`
- [ ] **Step 2: Add velocity-based skewing** — GSAP ticker reads scroll velocity, applies `skewY` (max 2deg) to `[data-skew]` elements with lerp smoothing
- [ ] **Step 3: Add `data-skew` to comparison cards** in S1Pain and S2Versus
- [ ] **Step 4: Add IntersectionObserver for background color tints** — detect active section, set `data-bg-tint` attribute on `main#main-content` (warm/cool/gold/neutral)
- [ ] **Step 5: Add section bg tint CSS to tokens.css** — `[data-bg-tint="warm"] { background-color: #080604 }` etc with 1.2s transition
- [ ] **Step 6: Verify entrances + skew + bg transitions**
- [ ] **Step 7: Commit**

---

## Task 7: Reactivate 3D Background (Signature Moment)

**Files:**
- Modify: `src/experience/background/BackgroundScene.tsx`

- [ ] **Step 1: Replace `return null` with TrackRibbon + SpeedStreaks rendering**
- [ ] **Step 2: Read TrackRibbon.tsx** — verify it returns valid R3F JSX, fix any issues
- [ ] **Step 3: Read SpeedStreaks.tsx** — verify the same
- [ ] **Step 4: Verify 3D renders** — check DebugHUD fps, verify GPU fallback works
- [ ] **Step 5: Commit**

---

## Task 8: Horizontal-Scroll Pinned Pipeline (S3Product)

**Files:**
- Modify: `src/components/rooms/S3Product.tsx`

- [ ] **Step 1: Rewrite S3Product** — pin section at top, horizontal flex track scrolls via GSAP scrub, progress bar fills, each card fades in via containerAnimation, reduced-motion fallback renders vertical stack
- [ ] **Step 2: Verify pin + horizontal scroll + progress indicator**
- [ ] **Step 3: Commit**

---

## Task 9: Section Layout Upgrades (Grid-Breaking)

**Files:**
- Modify: `src/components/rooms/S2Versus.tsx`
- Modify: `src/components/rooms/SessionProof.tsx`
- Modify: `src/components/rooms/Garage.tsx`

- [ ] **Step 1: S2Versus** — change grid to `grid-cols-[1fr,1.1fr]`, coaching card overlaps left by 16px with `shadow-e3`
- [ ] **Step 2: SessionProof** — stagger card heights: left `md:translate-y-4`, center 0, right `md:-translate-y-4`
- [ ] **Step 3: Garage** — founder avatar breaks out of card container with `md:-mt-12 md:mr-[-20px]`, larger size (20x20), `shadow-e3`
- [ ] **Step 4: Verify layouts**
- [ ] **Step 5: Commit**

---

## Task 10: Enhanced Custom Cursor

**Files:**
- Modify: `src/components/chrome/CustomCursor.tsx`

- [ ] **Step 1: Rewrite CustomCursor** — lerped position via rAF (0.15 interpolation), three states: default (8px dot), hover (28px glow), text (56px circle with label from `data-cursor` attribute), smooth transitions between states
- [ ] **Step 2: Add `data-cursor` attributes** — hero CTA gets "GO", product card gets "VIEW", PremiumLayer cards get "VIEW", Podium CTA gets "GO"
- [ ] **Step 3: Verify cursor states**
- [ ] **Step 4: Commit**

---

## Task 11: Preloader

**Files:**
- Create: `src/components/chrome/Preloader.tsx`
- Modify: `src/experience/ExperienceShell.tsx`

- [ ] **Step 1: Create Preloader** — racing countdown 5-4-3-2-1-GO, each number scales in via GSAP, "GO" in gold, exit animation blurs+fades, sets sessionStorage flag to skip on revisit
- [ ] **Step 2: Integrate into HomepageShell** — show preloader, hide content until done, skip on reduced-motion or revisit
- [ ] **Step 3: Defer Lenis init until preloader completes**
- [ ] **Step 4: Verify preloader plays + skips correctly**
- [ ] **Step 5: Commit**

---

## Task 12: Sound Design

**Files:**
- Create: `src/lib/sound-manager.ts`
- Create: `src/components/chrome/SoundToggle.tsx`
- Modify: `src/experience/ExperienceShell.tsx`

- [ ] **Step 1: Create SoundManager** — Howler.js singleton, ambient loop (vol 0.08), click (vol 0.15), hover (vol 0.06), mute toggle persisted in localStorage
- [ ] **Step 2: Create SoundToggle button** — fixed bottom-right, shows ON/OFF
- [ ] **Step 3: Wire into ExperienceContent** — init after preloader, start ambient
- [ ] **Step 4: Create placeholder audio directory** — `public/audio/` (actual files sourced separately)
- [ ] **Step 5: Commit**

---

## Task 13: Magnetic CTAs + Mix-Blend on Remaining Sections

**Files:**
- Modify: `src/components/rooms/Podium.tsx`
- Modify: `src/components/rooms/PitStop.tsx`
- Modify: `src/components/rooms/PremiumLayer.tsx`

- [ ] **Step 1: Podium** — useMagnetic on CTA, split-text headline, `mix-blend-difference` on "DESERVES BETTER" span
- [ ] **Step 2: PitStop** — `data-cursor="GO"` on all tier CTAs
- [ ] **Step 3: PremiumLayer** — `data-cursor="VIEW"` on all feature cards
- [ ] **Step 4: Commit**

---

## Task 14: Split-Text on All Section Headlines

**Files:**
- Modify: `src/components/rooms/S2Versus.tsx`
- Modify: `src/components/rooms/SessionProof.tsx`
- Modify: `src/components/rooms/SimFirst.tsx`
- Modify: `src/components/rooms/PremiumLayer.tsx`
- Modify: `src/components/rooms/Garage.tsx`

- [ ] **Step 1: Change `reveal` to `split` on all major section headlines** (S2Versus both lines, SessionProof, SimFirst, PremiumLayer, Garage)
- [ ] **Step 2: Add `data-stagger` to cards** in SimFirst, Garage result cards
- [ ] **Step 3: Add useCountUp to Garage iRating stat** (+2,000 counter animation)
- [ ] **Step 4: Commit**

---

## Task 15: Build Verification + Deploy

**Files:** All modified files

- [ ] **Step 1: Run `npm run build`** — fix any TypeScript errors
- [ ] **Step 2: Run `npm run lint`** — fix any lint errors
- [ ] **Step 3: Manual verification** — preloader, Lenis, grain, scrollbar, hero, 3D, entrances, skew, S3Product pin, overlaps, cursor, sound, bg transitions, reduced-motion, mobile
- [ ] **Step 4: Final commit**
- [ ] **Step 5: Deploy** — `npm run cf:deploy`
