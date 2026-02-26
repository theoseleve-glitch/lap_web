# LAP Sales Website — Design Document

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement the companion implementation plan task-by-task.

**Goal:** Build a single immersive sales website for the LAP motorsport telemetry SaaS, covering both B2C (individual drivers) and B2B (tracks/circuits as a services play), optimized for conversion, trust, and clarity.

**Architecture:** A continuous single-page scroll experience ("the website is a lap") built with Next.js + GSAP ScrollTrigger + React Three Fiber. Nine "rooms" pinned to scroll position, each with a mechanism that reveals, changes, or demonstrates. Brutalist visual surface, museum-grade choreography, discovery-first navigation.

**Tech Stack:** Next.js 14 (App Router), Tailwind CSS + CSS custom properties, GSAP 3 + ScrollTrigger, React Three Fiber + Drei, Howler.js (opt-in audio), Plausible analytics, Vercel deployment.

---

## 1. Core Concept

"The website is not pages. It's a lap."

The user enters an installation where every scroll is distance, every click is a mechanism, and every transition is a reveal. A single continuous experience (one route), with an Index Overlay for instant jump to any chapter.

### Motorsport Metaphors (structural, not decorative)

| Metaphor | Maps to |
|---|---|
| Start grid / lights out | Entry ritual |
| Sectors (S1/S2/S3) | Chapters |
| Pit stop | Pricing / demo / CTA moment |
| Telemetry overlay | UI language (delta, traces, stamps) |
| Scrutineering | Trust, proof, credibility |
| Podium | Final action |

### Design Promise

- Brutalist surface (raw, typographic, hard contrasts)
- Museum-grade choreography (timing, inertia, physicality)
- Discovery-first navigation (the user "finds" the site)

---

## 2. Visual System

### A) Color Tokens

**Base (95% usage):**

| Token | Hex | Role |
|---|---|---|
| `--asphalt` | `#0B0C0F` | Background |
| `--concrete` | `#161A20` | Panels |
| `--chalk` | `#F3F0E8` | Primary text |
| `--steel` | `#8A8F98` | Secondary text |

**Accents (used sparingly — like trackside flags):**

| Token | Hex | Meaning |
|---|---|---|
| `--acid-green` | `#B6FF2E` | Delta positive / "go" |
| `--safety-red` | `#FF2A2A` | Alerts / "no" |
| `--marshal-yellow` | `#FFD400` | Warnings / highlights |
| `--pit-orange` | `#FF6A00` | CTA / "pit now" |

**Single-accent rule:** At any moment, only ONE accent dominates the scene. Enforced structurally via `data-accent` attribute per room section — CSS scopes all other accent vars to `--steel` within that room.

| Room | Dominant Accent |
|---|---|
| Start Grid | None (monochrome → red lights) |
| S1 Pain | `--acid-green` |
| S1 Deep | `--acid-green` |
| S2 Pipeline | `--marshal-yellow` |
| S2 Proof | `--marshal-yellow` |
| S3 Product | `--acid-green` (B2C) / `--marshal-yellow` (B2B) |
| Pit Stop | `--pit-orange` |
| Garage | None (monochrome) |
| Podium | `--pit-orange` |

### B) Typography

| Role | Font | Weight | Style |
|---|---|---|---|
| Monument Headline | Teko | 600-700 | ALL CAPS, tracking -0.02em, leading 0.85 |
| Body | Inter | 400/500 | Normal case, line-height 1.65 |
| Telemetry / Labels | IBM Plex Mono | 400 | UPPERCASE, tracking +0.12em |

**Type scale (fluid via CSS clamp):**

| Token | Size |
|---|---|
| `--text-monument-xl` | `clamp(80px, 14vw, 220px)` |
| `--text-h1` | `clamp(48px, 6vw, 84px)` |
| `--text-h2` | `clamp(36px, 4vw, 56px)` |
| `--text-h3` | `clamp(24px, 2.5vw, 32px)` |
| `--text-body` | `clamp(16px, 1.2vw, 18px)` |
| `--text-caption` | `13px` |
| `--text-telemetry` | `11px` |

### C) Grid & Spacing

- 12 columns, `clamp(20px, 2vw, 32px)` gutters
- Side margins: `clamp(16px, 6vw, 8vw)`
- Baseline unit: 8px (all spacing multiples of 8)
- "Brutalist breaks": may violate visible grid, never the baseline rhythm

### D) Graphic Motifs

1. **Delta Strip** — thin horizontal bar, fills like a progress bar, always present at viewport bottom
2. **Sector Tabs** — S1/S2/S3/PIT/GAR/POD, always visible left edge, trackside signage look
3. **Scrutineering Stamp** — rectangular stamp, misaligned 1-2px, "VERIFIED" / "REPRODUCIBLE" / etc.
4. **Track Map Linework** — minimal 1-2px stroke track outline, used as separators/masks/reveal windows
5. **Timecode + Distance Counter** — top-right, `T+ 02:13.420` + `D 1.84 km`, scroll-driven

### E) Textures

- Concrete grain: noise SVG filter at 4% opacity on `--asphalt` backgrounds
- Dither overlay: repeating 2px dot pattern at 3% on panels
- Scan lines: optional 1px horizontal stripes at 2% on photography
- All applied via `::after` pseudo-elements

### F) Z-Layer System

| Token | Value | Role |
|---|---|---|
| `--z-base` | 0 | Content |
| `--z-panels` | 10 | Cards, placards |
| `--z-stamps` | 20 | Scrutineering stamps |
| `--z-delta` | 30 | Delta strip |
| `--z-sector` | 40 | Sector tabs |
| `--z-timecode` | 50 | Timecode counter |
| `--z-nav` | 60 | Index trigger |
| `--z-overlay` | 100 | Index overlay |
| `--z-cursor` | 999 | Custom cursor |

---

## 3. Room-by-Room Narrative & Copy

### ROOM 0: START GRID

**Monument (Teko, 220px):**
> EVERY LAP HAS A SECRET

**Telemetry label:** `HOLD TO START // 2.0s`

**Mechanism:** User presses and holds. Five red circles appear (F1 start lights), 400ms intervals. On release: lights out → white flash (120ms) → timecode starts → auto-scroll into S1.

**Mobile:** Long-press. Haptic on each light.
**Reduced motion:** Click to proceed, no hold.

---

### ROOM S1: WHY TIME IS LOST

**Transition in:** Concrete Slab Wipe (bottom to top).

**Monument (Teko, 140px):**
> YOU'RE LOSING TIME IN PLACES YOU CAN'T SEE

**Body:**
> Every corner has an optimal line. The difference between your line and that line is measurable, repeatable, fixable.

**Mechanism — Corner Drag:** Simplified 90° corner silhouette. User drags 3 control points (entry, apex, exit). Delta strip updates live. Stamp appears on first interaction: `DATA SOURCE: GPS + IMU @ 25Hz`.

**Tooltips:**
- Entry: `BRAKE POINT // EARLIER = SLOWER ENTRY, TIGHTER RADIUS`
- Apex: `APEX // GEOMETRIC vs LATE — AFFECTS EXIT SPEED`
- Exit: `THROTTLE APPLICATION // EARLIER = MORE TIME GAINED`

---

### ROOM S1 DEEP: TELEMETRY BECOMES SCULPTURE

**Transition in:** Apex Mask Reveal (corner outline expands as clip-path).

**Monument (Teko, 84px):**
> DATA HAS A SHAPE

**Mechanism:** Three telemetry traces as flowing ribbons (R3F 3D / Canvas 2D fallback): Speed (chalk), Brake (red spikes), Steering (steel). Draw left-to-right on enter (1400ms). Hover dims non-hovered traces to 10%.

**Tooltips:**
- Speed: `SPEED // 87.4 KM/H — EXIT VELOCITY, CORNER 4`
- Brake: `BRAKE // 0.94G — PEAK DECELERATION`
- Steering: `STEERING // 12.4° — LOCK ANGLE AT APEX`

**Body:**
> Speed. Brake. Steering. Three traces tell the whole story. LAP reads them, maps them to your track, and finds where time hides.

**Exit:** Telemetry Crush (traces compress to 2px line → becomes Delta Strip).

---

### ROOM S2: HOW IT WORKS (Pipeline)

**Transition in:** Delta Flip (200ms black/white invert).

**Monument (Teko, 84px):**
> INGEST → CLEAN → MAP → ANALYZE → REPORT

**Mechanism:** 5 brutalist blocks fill from bottom on scroll. Each completion triggers a Scrutineering Stamp slam:

| Block | Stamp |
|---|---|
| INGEST | `HEADER DETECTED // 47 CHANNELS` |
| CLEAN | `OUTLIERS REMOVED // 99.2% RETAINED` |
| MAP | `TRACK MATCHED // CITY KART SAUTRON` |
| ANALYZE | `14 CORNERS SEGMENTED // 25 LAPS` |
| REPORT | `SCORE: 86 // GRADE A` |

**Body:**
> From raw CSV to scored report in under 60 seconds. 14 pipeline stages. Every step validated. No black boxes.

---

### ROOM S2 PROOF: SCRUTINEERING

**Transition in:** Pit Stop Jump-Cut (hard cut, timecode persists).

**Monument (Teko, 56px):**
> SCRUTINEERING

**Subhead:** `THREE PROOFS THAT THE NUMBERS ARE REAL`

**3 Museum Placards with flip reveal:**

**A) REPEATABILITY**
- Front: "Upload the same session twice. Get the same score twice. Every time."
- Reveal: "Scoring uses deterministic physics models. No ML randomness in the core pipeline. SHA-256 checksum verifies identical input. Reproducible to ±0.001s on lap times."
- Stamp: `VERIFIED // DETERMINISTIC PIPELINE`

**B) REFERENCE ACCURACY**
- Front: "Corner-by-corner analysis validated against professional data engineering methodology."
- Reveal: "Theoretical lap computed from friction model + optimal racing line geometry. Reference speeds derived from GPS + IMU sensor fusion at 25Hz. Not arbitrary — physics-based."
- Stamp: `VALIDATED // PHYSICS-BASED MODEL`

**C) CONDITION SENSITIVITY**
- Front: "Wet track? New tires? Different kart? The scoring adapts. Your progress is real."
- Reveal: "Phase-aware scoring detects grip evolution. Wet/dry thresholds adjust expectations. Kart-specific profiles normalize comparisons. Detrending only applied when it helps — never hurts."
- Stamp: `CALIBRATED // CONDITION-AWARE`

---

### ROOM S3: PRODUCT

**Transition in:** Concrete Slab Wipe (from left).

**Monument (Teko, 140px):**
> FIND TIME.

**Mode Selector:** Cockpit switch toggle: `DRIVER` (B2C) / `TRACK` (B2B). Spring easing, mechanical snap.

**B2C (DRIVER mode):**

Subhead: `FOR KART, CAR & SIM DRIVERS`

Report Scrubber mechanism: art-directed product screenshot with distance scrubber. Dragging reveals:
- Tile 1: `YOUR SCORE: 86/A` — 4-pillar breakdown
- Tile 2: `CORNER 7: BRAKE 0.4s LATE` — specific coaching
- Tile 3: `NEXT SESSION: 3 DRILLS` — development plan

**B2B (TRACK mode):**

Subhead: `FOR CIRCUITS, SCHOOLS & ORGANIZERS`

4 outcome placards:
1. `BRANDED REPORTS` — "Your logo. Your colors. Every driver gets a professional debrief."
2. `DRIVER RETENTION` — "Drivers who see progress come back. Average +40% return rate."
3. `TIMING INTEGRATION` — "Connects to your existing timing system. No new hardware."
4. `TURNKEY SETUP` — "We configure everything. You run events. Pilot program available."

CTA: `REQUEST PILOT EVENT` (stamp button)

---

### ROOM 6: PIT STOP

**Transition in:** Hard cut to black (500ms silence), then pitwall assembly stagger.

**Monument (Teko, 84px):**
> PIT STOP

**Subhead:** `PRICING // DEMO // CONTACT`

**B2C Pricing:**

| | STARTER | PERFORMANCE | PRO RACER |
|---|---|---|---|
| Price | Free | €8.99/mo · €69/yr | €13.99/mo · €109/yr |
| Sessions | 3/month | Unlimited | Unlimited |
| Scoring | Preview | Full 4-pillar | Full 4-pillar |
| Coaching | — | Corner-by-corner | Corner + dev plans |
| History | 30 days | 1 year | Unlimited |
| Reports | — | PDF export | PDF + API/webhooks |
| Team | — | — | Up to 5 seats |
| CTA | `START FREE` | `UPGRADE` (pit-orange) | `GO PRO` |

**B2B Pricing:**

| | TRACK ESSENTIEL | CIRCUIT PRO | CIRCUIT PREMIUM |
|---|---|---|---|
| Price | €1,490/yr | €2,990/yr | €4,990/yr |
| Drivers | Up to 50/event | Up to 200/event | Unlimited |
| Reports | Standard | Branded | White-label |
| Timing | Manual CSV | API integration | Full + live |
| Support | Email | Priority | Dedicated + SLA |
| Setup | Self-serve docs | Guided setup | Full onboarding |
| CTA | `GET STARTED` | `BOOK DEMO` (pit-orange) | `CONTACT SALES` |

**Add-ons board:**
- Advanced timing integration: +€490/yr
- Endurance module (6h+): +€390/yr
- White-label upgrade: +€990/yr
- Premium SLA (4h response): +€690/yr
- Extended API + webhooks: +€290/yr

**Risk Reversal (stamps):**
`30-DAY MONEY BACK` · `CANCEL ANYTIME` · `YOUR DATA, ALWAYS` · `EXPORT EVERYTHING` · `GDPR COMPLIANT` · `NO LOCK-IN`

**FAQ (6 items):**
1. Payment methods? — Card (Stripe), bank transfer for B2B annual.
2. Switch plans? — Upgrade/downgrade anytime, prorated.
3. Data formats? — RaceChrono CSV, RaceBox export. More coming.
4. Data private? — Your data. Encrypted at rest. Never shared. Delete anytime.
5. Supported devices? — Upload from any device. Analysis in the cloud.
6. Sim racing? — Coming soon. Waitlist available.

**Trust strip:** `GDPR READY` · `256-BIT ENCRYPTED` · `99.9% UPTIME` · `MADE IN FRANCE`

---

### ROOM 7: GARAGE

**Transition in:** Continuous scroll, background gains blueprint grid lines.

**Monument (Teko, 56px):**
> GARAGE

**Subhead:** `TECHNICAL DOCUMENTATION // FOR SKEPTICS`

**4 expandable panels:**

1. **STACK** — Python 3.x, Flask, pandas, scikit-learn, PostgreSQL, Redis, Celery. 14-stage pipeline. Physics-based models.
2. **DATA SOURCES** — RaceChrono Pro CSV, RaceBox. GPS + IMU @ 10-25Hz. Streaming ingest up to 12GB. Adaptive chunking, <1GB peak memory.
3. **METHODOLOGY** — 4-pillar scoring. Corner analysis (brake, apex, exit). Reference lap from friction model. Condition-aware detrending. Confidence weighting.
4. **PRIVACY & COMPLIANCE** — GDPR-ready (EU storage). AES-256 at rest, TLS in transit. User-controlled retention. Full deletion on request. Audit trail. 100% data ownership. Export anytime.

---

### ROOM 8: PODIUM

**Transition in:** Telemetry Crush (compress up) → 400ms black → monument drops in (1400ms inertia).

**Monument (Teko, 220px):**
> READY TO RUN A CLEAN LAP?

**Two CTAs:**
- `TRY DEMO` — PIT button (pit-orange), B2C path
- `TALK` — Stamp button (chalk border), B2B path

**Subtext:** `FREE STARTER PLAN // NO CARD REQUIRED // 60 SECONDS TO FIRST SCORE`

**Loop:** After 3s inactivity, `← RESTART LAP` fades in. Click resets timecode to 0 and scrolls to Start Grid.

**Delta strip:** Shows accumulated total from all interactions: `TOTAL TIME SAVED: −2.847s`

---

## 4. Component Inventory

### A) Delta Strip
Fixed bottom, 32px height. Center-origin fill: left = time gained (acid-green), right = time lost (safety-red). IBM Plex Mono value. Collapses to 4px when passive. Props: `value`, `label?`, `active`.

### B) Sector Tabs
Fixed left edge, vertical. 6 labels: S1/S2/S3/PIT/GAR/POD. Active tab: accent left-border. Click scrolls to room. IntersectionObserver-driven. Mobile: 6 dots right edge. Props: `activeSection`, `accent`.

### C) Timecode + Distance Counter
Fixed top-right. IBM Plex Mono 13px. Scroll-mapped: 0→~4:00.000 / 0→~4.2km. Digit slot-machine roll (200ms per digit). Mobile: single line, 11px. Props: `scrollProgress` (0-1).

### D) Scrutineering Stamp
2px accent border, transparent fill. IBM Plex Mono 11px label + 9px detail. Random rotation ±0.5-2°, offset ±1-2px (set per instance). Entry: `scale 1.15→1, opacity 0→1` (420ms overshoot). Slam variant: `scale 1.4→1` (280ms spring). Props: `label`, `detail?`, `variant`, `rotation?`, `offset?`.

### E) Index Overlay
Full-screen z-100. Asphalt 96% + backdrop-blur 24px. 3×2 poster grid of section tiles (Teko 56px + Mono 11px). Hover: concrete bg + accent border. Sound + reduced-motion toggles. Open: LAP wordmark click or `I` key. Close: `×`, Escape, click outside. Props: `isOpen`, `onNavigate`, `soundEnabled`, `reducedMotion`.

### F) LAP Wordmark
Fixed top-left. Teko 24px, chalk, 2px border, rotated -0.8° (stamp feel). Click opens Index Overlay. Hover: border transitions to room accent. Props: `accent`, `onClick`.

### G) Placard (Museum Card)
Concrete bg, 1px border, NO rounded corners. Teko 32px title + Inter 18px body + optional stamp. `REVEAL` button flips card (Y-axis 600ms) to show methodology. Hover: 2px accent top border. Props: `title`, `body`, `revealContent`, `stamp?`.

### H) Stamp Button
Transparent bg, 2px chalk border. IBM Plex Mono 13px uppercase. Hover: fills chalk, text inverts to asphalt (instant). Active: scale 0.97. Focus: 3px accent outline.

### I) PIT Button (Primary CTA)
Pit-orange bg, asphalt text. IBM Plex Mono 14px uppercase bold. Hover: lighten 10% + glow shadow. Active: scale 0.97. Focus: 3px chalk outline. The ONLY colored surface in monochrome rooms.

### J) Tooltip
Asphalt/concrete bg, 1px border. IBM Plex Mono 11px chalk text. Max 280px. 300ms hover delay. CSS triangle pointer. Touch: tap to show/dismiss. Props: `content`, `position`.

### K) Mode Selector (Cockpit Switch)
Toggle: `DRIVER` / `TRACK`. Concrete track, chalk knob. Spring easing 300ms (4% overshoot). Active label: chalk, inactive: steel. 44px min touch target. Props: `value`, `onChange`.

### L) Pricing Table
Teko 24px headers, Teko 48px price. Inter 16px features. Alternating row backgrounds. Recommended column: pit-orange border + shadow. Monthly/annual stamp toggle. Props: `plans[]`, `billingPeriod`, `highlightedPlan?`.

### M) FAQ Accordion
1px border-top separators. IBM Plex Mono 13px questions, Inter 16px answers. `[+]` rotates to `[×]` on expand. One item open at a time. Keyboard: Enter/Space toggle, arrows between. Height animation 420ms.

---

## 5. Motion Spec

### Timing Tokens

```
--duration-micro:    420ms
--duration-room:     900ms
--duration-monument: 1400ms
```

### Easing Presets

```
--ease-inertia:    cubic-bezier(0.16, 1, 0.3, 1)      // primary
--ease-overshoot:  cubic-bezier(0.34, 1.56, 0.64, 1)   // big moves
--ease-spring:     cubic-bezier(0.22, 1.2, 0.36, 1)    // switches, stamps
--ease-snap:       cubic-bezier(0.7, 0, 0.84, 0)       // hard cuts
```

### Signature Transitions

| Transition | Used between | Description | Duration |
|---|---|---|---|
| Concrete Slab Wipe | Grid→S1, S2Proof→S3 | Concrete rect slides across viewport | 1900ms (cover + reveal) |
| Apex Mask Reveal | S1→S1Deep | Corner outline clip-path expands from center | 900ms |
| Telemetry Crush | S1Deep→S2, Garage→Podium | Content compresses vertically to 2px line | 600ms |
| Delta Flip | S2 entry | 200ms full-viewport invert filter | 200ms |
| Pit Stop Jump-Cut | S2→S2Proof, S3→PitStop | Instant frame cut, no animation (timecode persists) | 0ms |

### Room Motion Details

**Start Grid:** Red lights `opacity 0→1` (400ms each, sequential) → lights out 80ms snap → white flash 120ms → auto-scroll 900ms.

**S1:** Monument clip-path wipe (1400ms) → body fade (420ms) → corner SVG draw (900ms) → control points scale in (420ms staggered). Delta updates per-frame on drag.

**S1 Deep:** Monument fade (900ms) → traces draw L→R (1400ms, 200ms stagger) → continuous pulse ±2%. Hover dims others 300ms.

**S2 Pipeline:** Letters stagger in 40ms each (~1400ms total) → blocks fill scroll-mapped → stamp slam per block (280ms spring).

**S2 Proof:** Monument + subhead fade (900ms) → placards translateX stagger (420ms, 150ms apart) → card flip on REVEAL (600ms rotateY).

**S3:** Monument scale (1400ms) → mode selector fade (420ms) → content crossfade on toggle (620ms total). Scrubber/tiles animate on scroll.

**Pit Stop:** 500ms black silence → pitwall assembly stagger (420ms each, 150ms apart, ~2800ms total).

**Garage:** Monument + panels fade stagger (420ms, 150ms apart). Panel expand height 420ms.

**Podium:** Compress up (600ms) → 400ms pause → monument drop (1400ms) → CTAs stagger (420ms, 200ms apart) → delta counter rolls to final (900ms).

### Reduced Motion

All scroll-pinning disabled. All transitions become opacity crossfade 200ms. No scale, rotate, or clip-path animations. No continuous loops. Hold-to-start becomes click. Timecode updates instantly. No cursor effects. No WebGL.

### Performance Guards

| Guard | Trigger | Action |
|---|---|---|
| GPU fail | No WebGL context | R3F disabled, Canvas 2D fallback |
| Low FPS | Avg < 40fps for 2s | Disable scroll-pinning, simplify transitions |
| Mobile | Viewport < 768px | No pinning, no cursor, no WebGL, simpler staggers |
| Low battery | Charging=false, level<0.2 | Switch to reduced motion |
| Intersection budget | >3 simultaneous observers | Queue excess |

---

## 6. Navigation Model

### Index Overlay

Always available via LAP wordmark (top-left) or `I` key. Full-screen poster grid:

```
S1: WHY TIME IS LOST    S2: HOW IT WORKS    S3: PRODUCT
PIT: PRICING             GARAGE: TECH        PODIUM: FINAL
```

Users can explore in any order. Scroll narrative still works linearly.

### Sector Tabs

Vertical left-edge tabs always visible. Click any to smooth-scroll. Active room detected via IntersectionObserver.

---

## 7. SEO & Sharing

### Meta

```
Title: LAP — Motorsport Telemetry Analysis | Find Time.
Description: Upload your telemetry. Get a score, corner-by-corner coaching,
             and a plan to go faster. Physics-based analysis for kart, car,
             and sim drivers. Free starter plan.
```

### OG Image

1200×630px. Asphalt black background. "FIND TIME." in Teko monument. Delta strip: `−2.847s` acid-green. LAP wordmark top-left.

### Structured Data

- `SoftwareApplication` with 3 offers (Starter/Performance/Pro Racer)
- `FAQPage` wrapping Pit Stop FAQ
- `Organization` for LAP

### Performance Budget

| Metric | Target |
|---|---|
| FCP | <1.5s |
| LCP | <2.5s |
| CLS | <0.05 |
| TBT | <200ms |
| JS initial | <120KB gzip |
| JS total (lazy) | <250KB gzip |
| Fonts | <80KB (subsetted Latin) |
| Total page weight | <1.5MB |

---

## 8. Accessibility

- Full keyboard navigation (Tab through rooms, Enter to interact)
- Skip links: "Skip to pricing" + "Skip to demo"
- ARIA landmarks per room, `aria-live` on delta values
- Focus indicators: 3px accent outline, 2px offset
- Color contrast: Chalk/Asphalt = 15.4:1 (AAA), Steel/Asphalt = 4.7:1 (AA)
- Touch targets: minimum 44×44px
- Screen reader: descriptive alt text, `aria-hidden` on decorative textures
- Full reduced-motion mode (see Section 5)
- `<html lang="en">`

---

## 9. Analytics Plan

### Event Taxonomy (22 events)

| Event | Trigger | Funnel |
|---|---|---|
| `page_view` | Load | Entry |
| `start_grid_hold` | Hold begins | Engagement |
| `start_grid_complete` | All 5 lights | Engagement |
| `s1_corner_interact` | First drag | Engagement |
| `s1_deep_trace_hover` | Trace hover | Engagement |
| `s2_pipeline_complete` | All stamps | Education |
| `s2_proof_reveal` | Card flip | Trust |
| `s3_mode_select` | B2C/B2B toggle | Qualification |
| `s3_scrubber_interact` | Drag scrubber | Product |
| `pit_stop_enter` | Section visible | Intent |
| `pricing_toggle` | Monthly/annual | Intent |
| `pricing_plan_hover` | Column hover | Intent |
| `addon_expand` | Open add-ons | Intent |
| `faq_expand` | Open FAQ item | Objection |
| `cta_click` | Any CTA | Conversion |
| `index_overlay_open` | Open overlay | Navigation |
| `index_overlay_nav` | Jump to section | Navigation |
| `sound_toggle` | Sound switch | Preference |
| `reduced_motion_toggle` | Motion switch | Preference |
| `garage_panel_expand` | Open tech panel | Trust |
| `podium_reach` | Scroll to end | Completion |
| `restart_lap` | Click restart | Re-engagement |

### Primary Funnel

```
page_view → start_grid_complete → s1_corner_interact → pit_stop_enter → cta_click
```

---

## 10. Screenshot Shot List

| Shot | Source | Art Direction |
|---|---|---|
| `score-overview.webp` | Session detail → Overview | Desaturate, accent green on score bars |
| `corner-coaching.webp` | Corners & Coaching tab | Desaturate, accent green on fastest line |
| `lap-data-table.webp` | Lap Data tab | Desaturate, accent green on best lap row |
| `driving-style.webp` | Overview → Driving Style | Desaturate, accent green on radar fill |
| `dashboard-hero.webp` | Dashboard | Full monochrome treatment |
| `pipeline-result.webp` | Post-analysis score | Tight crop, accent green on grade badge |

All: 1440px viewport, WebP, max 150KB, 4% concrete grain overlay.

---

## 11. Decisions Log

| Question | Decision |
|---|---|
| Product name | LAP (brand name AND website concept) |
| B2B features | Services play — site captures leads, custom delivery |
| Deployment | Standalone repo, Vercel, separate from Flask product |
| Product imagery | Real screenshots, art-directed to match brutalist brand |
| Launch context | Full launch — live pricing, real signup/payment |
| Tech stack | Next.js + GSAP + R3F (Approach A: full immersive) |
