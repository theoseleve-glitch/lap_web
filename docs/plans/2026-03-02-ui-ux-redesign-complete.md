# Lap Coach UI/UX Redesign — Complete Specification

**Date:** 2026-03-02
**Team:** Product/UX Lead, Visual/Brand Designer, Motion/Interaction Designer, Frontend Architect, Accessibility Specialist, Copy + Messaging Strategist

---

## Executive Summary

1. **The "Hold to Start" gate blocks all content** — first-time visitors cannot see what the product does. Remove or demote to optional Easter egg.
2. **No B2C/B2B fork exists** — both audiences must scroll through a single narrative. Add an explicit "Driver or Venue?" mode selector within 5 seconds.
3. **Product identity is unclear for 15+ seconds** — the hero says "EVERY LAP HAS A SECRET" but not "Telemetry reports that coach you." Add a clear subtitle.
4. **Zero social proof** — no testimonials, no user count, no logos. Add a trust strip within the first two screens.
5. **Navigation is too minimal** — 4 links with no mobile hamburger, no B2B entry point. Expand with audience-aware nav.
6. **Accent colors are collapsed** — acid-green, marshal-yellow, racing-purple all resolve to the same value. Restore differentiation.
7. **Pricing is buried at Section 10 of 12** — a visitor must scroll 8+ full-viewport sections to see cost. Surface pricing earlier or add a sticky "See Plans" shortcut.
8. **The S3Venue (B2B) section is a single room in a 12-room sequence** — venue buyers need a dedicated page with operational proof, timeline, ROI.
9. **Mobile touch targets are undersized** — nav links at `text-xs` with tight padding fail the 44px minimum.
10. **Performance risk from 3D models + GSAP + Lenis + Howler** — heavy client bundle. Need progressive loading and a performance budget gate.

---

## 1. UX Audit — Top 20 Friction Points

### Critical (Fix immediately — blocks comprehension/conversion)

| # | Issue | Location | Impact | Fix Type |
|---|-------|----------|--------|----------|
| F1 | **"Hold to Start" blocks all content** | `StartGrid.tsx` | Visitors cannot see product without interaction. Scroll intent threshold (220px delta) + hold mechanic = opaque gate. | **Structural**: Remove gate. Keep animation as optional delight (auto-plays after 1s, or on scroll). |
| F2 | **Hero doesn't say what the product is** | `StartGrid.tsx` | "EVERY LAP HAS A SECRET" is atmospheric but not informative. No subtitle explains the product. | **Quick win**: Add subtitle: "Telemetry reports that coach every driver. Live event tools for every venue." |
| F3 | **No B2C/B2B audience fork** | Home page flow | Venue buyers must scroll through driver-focused content to find S3Venue. Drivers see venue ops content. | **Structural**: Add "Mode Selector" component after hero. Two paths: "I'm a Driver" / "I Run a Venue." |
| F4 | **Zero social proof** | Entire site | No testimonials, user counts, partner logos, or case studies on landing page. | **Structural**: Add proof strip (driver count, sessions analyzed, tracks supported) + 2-3 testimonial cards. |
| F5 | **Pricing buried at scroll position ~80%** | Section 10 of 12 | Users who want to evaluate cost must scroll through 8 full-screen rooms. | **Quick win**: Add "See Plans" link in nav. Add pricing teaser after mode selector. |

### High (Significantly impacts conversion/usability)

| # | Issue | Location | Impact | Fix Type |
|---|-------|----------|--------|----------|
| F6 | **Nav too minimal, no mobile menu** | `SiteHeader.tsx` | 4 links + login + signup wrap awkwardly on mobile. No hamburger menu. No B2B-specific entry. | **Quick win**: Add hamburger for mobile. Add "For Venues" nav item. |
| F7 | **No dedicated B2B/Pilot page** | Missing page | Venue decision-makers need: timeline, hardware requirements, ROI, pilot structure, pricing shape. Currently just one section (S3Venue) + "/contact". | **Structural**: Create `/venues` (or `/pilot`) page with full B2B journey. |
| F8 | **"Data Has a Shape" is opaque** | S1DeepSculpture room | Heading without supporting context. Visitors don't know what "shape" means until they read the body text. | **Quick win**: Change to "Your Lap Data, Visualized" or "See Where You're Losing Time." |
| F9 | **Strategist Mode repeats identical image descriptions** | S3Product room | Copy/paste error in the section. Three identical screenshot references. | **Quick win**: Fix content. Use distinct screenshots for each mode feature. |
| F10 | **B2B card is an afterthought in pricing** | `PitStop.tsx` | The B2B card is a narrow sidebar next to the B2C pricing table. Venue buyers feel like an add-on. | **Structural**: Give B2B its own row or dedicated section. |

### Medium (Impacts polish/trust/performance)

| # | Issue | Location | Impact | Fix Type |
|---|-------|----------|--------|----------|
| F11 | **Accent colors are aliased** | `tokens.css` | `--acid-green`, `--marshal-yellow` = `#F0EDE5` (chalk). `--racing-purple` = `#C9A84C` (pit-orange). Rooms lose visual differentiation. | **Quick win**: Restore distinct colors. |
| F12 | **No "How it Works" diagram** | Missing | The pipeline section (S2Pipeline) is technical. No simple 3-step "Upload → Analyze → Improve" visual. | **Quick win**: Add a 3-step horizontal diagram before the technical pipeline. |
| F13 | **Scrutineering stamps lack context** | Trust strip in PitStop | "ZERO STAFF," "UNIFIED," etc. are jargon to first-time visitors. Need brief explanatory text. | **Quick win**: Add one-line descriptions under each stamp. |
| F14 | **No ROI or value quantification** | Missing | B2B buyers need: "Save X hours/week," "Y% driver retention increase." B2C needs: "Average improvement: 0.8s/lap." | **Structural**: Add KPI/ROI section for both audiences. |
| F15 | **GDPR/compliance badges are text-only** | Trust strip | "GDPR READY" / "256-BIT ENCRYPTED" appear as ScrutineeringStamps — look like UI elements, not trust signals. | **Quick win**: Use recognizable shield/lock icons + text. |

### Low (Polish items, nice-to-have)

| # | Issue | Location | Impact | Fix Type |
|---|-------|----------|--------|----------|
| F16 | **Marquee strips feel decorative, not informative** | Between rooms | "TELEMETRY / LAP ANALYSIS / CORNER COACHING" marquees add visual rhythm but no conversion value. | **Quick win**: Replace one marquee with a social proof strip (logos, stats). |
| F17 | **Garage (tech stack) section is niche** | Garage room | Listing "Next.js / Flask / PostgreSQL" matters to developers, not buyers. Move to footer or /product page. | **Quick win**: Move to footer or remove from landing. |
| F18 | **No skip-to-content link** | Global | Keyboard users must tab through all nav elements. | **Quick win**: Add visually-hidden skip link. |
| F19 | **3D model loading not progressive** | StartGrid, Chrome | helmet.glb, tire.glb, etc. load eagerly. No loading skeleton. | **Structural**: Lazy-load 3D assets. Show placeholder until loaded. |
| F20 | **Custom cursor may conflict with assistive tech** | `CustomCursor` component | Custom cursor overlays can confuse screen magnifiers and alternative input devices. | **Quick win**: Disable custom cursor when `prefers-reduced-motion` is set. |

---

## 2. Updated Information Architecture

### Principle: Two Journeys, One Brand

```
                          ┌─────────────────┐
                          │   lap-coach.racing   │
                          │   (Home / Landing)   │
                          └────────┬────────┘
                                   │
                     ┌─────────────┼─────────────┐
                     ▼                           ▼
              ┌─────────────┐           ┌──────────────┐
              │  FOR DRIVERS │           │  FOR VENUES  │
              │    (B2C)     │           │    (B2B)     │
              └──────┬──────┘           └──────┬───────┘
                     │                          │
           ┌────────┼────────┐        ┌────────┼────────┐
           ▼        ▼        ▼        ▼        ▼        ▼
        Product  Pricing   Demo    Venues   Pilot    Contact
        /product /pricing  /demo   /venues  /book    /contact
```

### Global Navigation (All Pages)

```
┌─────────────────────────────────────────────────────────────────┐
│  [LAP]   Product ▾   Pricing   For Venues   Insights   [Login] [Try Free] │
│                │                                                │
│           ├── Engineer Mode                                      │
│           ├── Strategist Mode                                    │
│           └── Integrations (RaceChrono, RaceBox)                │
└─────────────────────────────────────────────────────────────────┘
```

**Mobile**: Hamburger menu with two sections: "Drivers" and "Venues" clearly separated.

### Page Map

| Page | Audience | Purpose | Primary CTA |
|------|----------|---------|-------------|
| `/` (Home) | Both | Awareness → Interest → Mode selection | "Try Free Report" / "Book a Pilot" |
| `/product` | B2C | Deep dive: Engineer + Strategist modes, screenshots, scoring | "Upload Your First Session" |
| `/pricing` | B2C | Plan comparison, feature matrix, FAQ | "Start Free" / "Upgrade" |
| `/demo` | B2C | Free report tool, interactive demo | "Upload CSV Now" |
| `/venues` | B2B | Full venue pitch: V1 QR + V2 Live, ops dashboard, ROI | "Book a Pilot" |
| `/book` | B2B | Pilot booking: timeline, requirements, pricing shape | Calendar embed / form |
| `/customers` | Both | Case studies, testimonials, results | "See Your Potential" |
| `/insights` | Both | Blog / educational content | Newsletter signup |
| `/contact` | Both | General contact form | Form submit |
| `/login` | Auth | Login | — |
| `/register` | Auth | Signup | — |
| `/free-report/*` | B2C | Analyze uploaded session | Upload → Report |

---

## 3. Page Blueprint — Home (Landing Page)

### Section Order (New)

The landing page is restructured from 12 ambiguous rooms to 10 purpose-driven sections. The "lap journey" metaphor is preserved but subordinate to clarity.

```
Section 1: HERO                    (5s — What is this?)
Section 2: MODE SELECTOR           (10s — Is this for me?)
Section 3: PROOF STRIP             (12s — Can I trust it?)
  ── B2C TRACK ──
Section 4: HOW IT WORKS (3 steps)  (20s — How does it work?)
Section 5: PRODUCT SHOWCASE        (30s — Show me the product)
Section 6: RESULTS / TESTIMONIALS  (40s — Does it work?)
  ── B2B TRACK ──
Section 7: VENUE PITCH             (30s — How does it work for my venue?)
Section 8: OPS REASSURANCE         (35s — Will it be painful to run?)
  ── SHARED ──
Section 9: PRICING                 (45s — What does it cost?)
Section 10: FINAL CTA + TRUST      (50s — I'm ready)
```

### Section Details

#### Section 1: HERO
**Purpose:** Instant product identification + emotional hook.
**Content:**
- Headline: **"Every lap coached. Every venue connected."**
- Subtitle: "Telemetry reports that show exactly where you're losing time. Event tools that give every driver a story."
- Two CTAs: `[Try Free Report]` (B2C primary) + `[Book a Pilot]` (B2B secondary)
- Background: Subtle dark grid with faint track outline animation (no gate, no hold mechanic)
- Trust micro-strip: "1,200+ sessions analyzed | 45 tracks | GDPR compliant"

**Metaphor:** Start grid — lights go green automatically (no hold required).

#### Section 2: MODE SELECTOR
**Purpose:** Fork the visitor into their journey while keeping them on one page.
**Content:**
- Headline: "Choose your lane."
- Two large cards:
  - **"I'm a Driver"** — "Upload telemetry, get coaching reports, track your improvement." → scrolls to Section 4.
  - **"I Run a Venue"** — "Give every driver post-session reports. Zero staff overhead." → scrolls to Section 7.
- Both cards always visible. Selecting one highlights the relevant sections but doesn't hide the other.

**Metaphor:** Choose your racing line.

#### Section 3: PROOF STRIP
**Purpose:** Instant credibility before any explanation.
**Content:**
- 3-4 KPI blocks: Sessions Analyzed, Tracks Covered, Average Lap Improvement, Uptime
- Optional: 3 small partner/track logos
- Style: Horizontal strip, dark background, monospace numbers (telemetry font)

**Metaphor:** Timing tower — hard data, no fluff.

#### Section 4: HOW IT WORKS (B2C) — "3 Sectors to Your Report"
**Purpose:** Simple mental model of the product flow.
**Content:**
- **Sector 1: Upload** — "Drop your RaceChrono or RaceBox CSV. 25Hz GPS + IMU data."
- **Sector 2: Analyze** — "14-stage pipeline: corner detection, scoring, physics models."
- **Sector 3: Coach** — "Corner-by-corner coaching. 4-pillar score. Improvement plan."
- Visual: Three connected cards with icons, brief text, and a progress indicator.
- CTA: `[Try It Free — No Card Required]`

**Metaphor:** Three sectors of a lap.

#### Section 5: PRODUCT SHOWCASE (B2C) — "Engineer Mode + Strategist Mode"
**Purpose:** Prove the product with real screenshots/interactions.
**Content:**
- Tab switcher: **Engineer** | **Strategist**
- Engineer: Screenshot gallery (score overview, corner coaching, speed trace, GG diagram)
- Strategist: Screenshot gallery (race dashboard, stint timeline, pit planning)
- Each screenshot has a 1-line caption explaining the value
- CTA: `[See All Features →]` links to /product

**Metaphor:** Pit wall monitor — showing real telemetry screens.

#### Section 6: RESULTS + TESTIMONIALS (B2C)
**Purpose:** Social proof — real drivers, real results.
**Content:**
- 2-3 testimonial cards: driver photo, name, category (kart/car), quote, result delta
- Optional: "Before/After" score comparison (e.g., "Session 1: 72/100 → Session 5: 89/100")
- CTA: `[Start Your Improvement Journey]`

**Metaphor:** Podium interviews.

#### Section 7: VENUE PITCH (B2B) — "One Engine. Two Channels."
**Purpose:** Explain the B2B value proposition clearly.
**Content:**
- Headline: "Give every driver a story. Run zero extra staff."
- **V1: QR Recap** — "Post-session QR codes. Lap times, best corner, session score. Autonomous delivery."
- **V2: Burst Zone (Roadmap)** — "Live leaderboard + telemetry for endurance events."
- **Ops Dashboard** — "Battery SOC, device health, delivery status. Weekly battery workflow."
- Diagram: Hardware → Trackside Server → QR Report → Driver's Phone
- CTA: `[Book a Pilot — See It on Your Track]`

**Metaphor:** Pit wall for venue operators.

#### Section 8: OPS REASSURANCE (B2B) — "Designed Around Staff, Not Against Them"
**Purpose:** Address the #1 B2B objection: "Will this be painful to operate?"
**Content:**
- 3 reassurance cards:
  - "Weekly Battery Swap" — "Slide-in/out battery workflow. 5 minutes per kart."
  - "Zero-Touch Reports" — "QR codes auto-generated. Drivers self-serve."
  - "SOC Dashboard" — "Fleet health at a glance. Alerts before failures."
- Timeline: "Pilot: 4 weeks → Production: 2 weeks → Scaled: ongoing"
- CTA: `[See the Pilot Timeline]`

#### Section 9: PRICING — "Pit Stop"
**Purpose:** Convert interested visitors.
**Content:**
- B2C pricing table (3 tiers: Demo / Racer / World-Class) — keep existing structure
- B2B card: separate row below, full-width, with "Book a Pilot" CTA
- Billing toggle (monthly/annual)
- Feature comparison matrix (collapsed by default, expandable)
- Risk reversal stamps: "No card required" / "Cancel anytime" / "GDPR compliant"
- FAQ accordion (6 items)

**Metaphor:** Pit stop — refuel, choose your strategy, get back on track.

#### Section 10: FINAL CTA + TRUST — "Podium"
**Purpose:** Last conversion opportunity + trust closure.
**Content:**
- Headline: "Your next session could be your best."
- Two CTAs: `[Try Free Report]` + `[Talk to Sales]`
- Trust strip: GDPR Ready | 256-Bit Encrypted | 99.9% Uptime Target | EU Data Residency
- Footer: Full site map, legal links, social links

**Metaphor:** Podium — the finish.

---

## 4. Design System — Tokens + Components

### 4.1 Color Tokens (Revised)

```css
:root {
  /* ── Base ───────────────────── */
  --color-asphalt:         #000000;   /* true black — backgrounds */
  --color-concrete:        #141414;   /* near-black — cards, panels */
  --color-tarmac:          #1C1917;   /* warm dark — elevated surfaces */
  --color-chalk:           #F0EDE5;   /* warm white — primary text */
  --color-white:           #FFFFFF;   /* pure white — high-contrast text */
  --color-steel:           #888888;   /* mid-gray — secondary text */
  --color-steel-muted:     #555555;   /* dark gray — tertiary text */

  /* ── Brand Accent ───────────── */
  --color-safety-red:      #FF2A2A;   /* brand red — primary accent, errors */
  --color-pit-orange:      #C9A84C;   /* gold — premium accent, CTAs, highlights */
  --color-racing-purple:   #8B5CF6;   /* purple — B2B accent, upsell */
  --color-sector-green:    #22C55E;   /* green — success, improvement, positive delta */
  --color-marshal-yellow:  #FACC15;   /* yellow — warnings, caution, neutral delta */

  /* ── Semantic ────────────────── */
  --color-bg-primary:      var(--color-asphalt);
  --color-bg-elevated:     var(--color-concrete);
  --color-bg-surface:      var(--color-tarmac);
  --color-text-primary:    var(--color-chalk);
  --color-text-secondary:  var(--color-steel);
  --color-text-muted:      var(--color-steel-muted);
  --color-cta-primary:     var(--color-pit-orange);
  --color-cta-hover:       #D4B35A;   /* lighter gold on hover */
  --color-accent-b2c:      var(--color-safety-red);
  --color-accent-b2b:      var(--color-racing-purple);
  --color-border-subtle:   rgba(240, 237, 229, 0.10);
  --color-border-medium:   rgba(240, 237, 229, 0.20);
  --color-border-strong:   rgba(240, 237, 229, 0.40);
}
```

**Key change:** Accent colors are now truly distinct. Purple is restored for B2B differentiation. Green is added for positive deltas/success states.

### 4.2 Typography Scale

```css
:root {
  /* ── Font Families ─────────── */
  --font-monument:    'Space Grotesk', system-ui, sans-serif;   /* headings */
  --font-body:        'Inter', system-ui, sans-serif;            /* body text */
  --font-telemetry:   'Space Mono', 'Courier New', monospace;    /* data, HUD, numbers */

  /* ── Size Scale (fluid) ────── */
  --text-display:     clamp(48px, 8vw, 120px);    /* hero headline only */
  --text-h1:          clamp(36px, 5vw, 72px);      /* section headlines */
  --text-h2:          clamp(28px, 3.5vw, 48px);    /* subsection headlines */
  --text-h3:          clamp(22px, 2vw, 32px);       /* card titles */
  --text-body-lg:     clamp(18px, 1.4vw, 22px);     /* lead paragraphs */
  --text-body:        clamp(16px, 1.2vw, 18px);     /* body text (never below 16px!) */
  --text-caption:     14px;                          /* metadata, labels */
  --text-telemetry:   12px;                          /* HUD data, monospace numbers */

  /* ── Line Heights ──────────── */
  --leading-tight:    1.1;    /* display/h1 */
  --leading-snug:     1.3;    /* h2/h3 */
  --leading-normal:   1.6;    /* body text */
  --leading-relaxed:  1.75;   /* long-form reading */

  /* ── Max Line Width ────────── */
  --measure-narrow:   45ch;   /* captions */
  --measure-normal:   65ch;   /* body paragraphs */
  --measure-wide:     80ch;   /* technical content */
}
```

### 4.3 Spacing Scale

```
--space-1:  4px       --space-8:   32px
--space-2:  8px       --space-10:  40px
--space-3:  12px      --space-12:  48px
--space-4:  16px      --space-16:  64px
--space-5:  20px      --space-20:  80px
--space-6:  24px      --space-24:  96px
```

**Section spacing:** `py-16` (64px) on mobile, `py-24` (96px) on desktop. Consistent across all sections.

### 4.4 Grid System

```css
.grid-page {
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  gap: clamp(16px, 2vw, 32px);
  max-width: 1280px;
  margin: 0 auto;
  padding: 0 clamp(16px, 4vw, 64px);
}
```

| Breakpoint | Columns | Max Width | Side Margin |
|------------|---------|-----------|-------------|
| `< 640px`  | 4       | 100%      | 16px        |
| `640-1024px` | 8     | 100%      | 32px        |
| `> 1024px` | 12      | 1280px    | auto        |

### 4.5 Border, Radius, Shadow

```css
:root {
  /* ── Borders ──────────────── */
  --border-width-thin:  1px;
  --border-width-thick: 2px;

  /* ── Radii — deliberately sharp. Premium = precision. ── */
  --radius-none:   0px;     /* default for most elements */
  --radius-sm:     2px;     /* subtle softening on small elements */
  --radius-md:     4px;     /* buttons, inputs */
  --radius-lg:     8px;     /* cards (only when needed for softness) */

  /* ── Shadows (minimal — dark theme) ── */
  --shadow-card:   0 1px 2px rgba(0,0,0,0.3), 0 0 0 1px rgba(240,237,229,0.05);
  --shadow-elevated: 0 4px 12px rgba(0,0,0,0.5), 0 0 0 1px rgba(240,237,229,0.08);
  --shadow-glow:   0 0 20px rgba(201,168,76,0.15);  /* gold glow for CTAs */
}
```

**Philosophy:** Sharp edges (radius 0-4px) maintain the precision/instrumentation aesthetic. Rounded corners are reserved for buttons and form inputs only.

### 4.6 Component Library

#### Navigation Components

| Component | Description | States |
|-----------|-------------|--------|
| `SiteHeader` | Sticky header with logo, nav links, auth buttons, mobile hamburger | visible / hidden (scroll) / mobile-open |
| `MobileDrawer` | Full-screen mobile nav overlay with audience sections | open / closed |
| `NavLink` | Individual nav link with active indicator | default / hover / active / focus |
| `StickyCtaBar` | Bottom-fixed bar on mobile with primary CTA | visible (after scroll past hero) / hidden |

#### Hero Components

| Component | Description | States |
|-----------|-------------|--------|
| `HeroSection` | Full-viewport hero with headline, subtitle, dual CTAs, trust micro-strip | default / reduced-motion |
| `ModeSelector` | Two-card audience fork ("Driver" / "Venue") | default / driver-selected / venue-selected / hover |
| `ProofStrip` | Horizontal KPI bar with animated counters | loading / revealed |

#### Content Components

| Component | Description | States |
|-----------|-------------|--------|
| `StepCard` | Numbered step in "How it Works" flow | default / active (scrolled-to) |
| `ProductShowcase` | Tab switcher with screenshot gallery | engineer-active / strategist-active |
| `ScreenshotFrame` | Dark-chrome browser frame around product screenshots | default / expanded (lightbox) |
| `TestimonialCard` | Driver photo + quote + result delta | default / hover |
| `KpiBlock` | Single metric with label, value, and optional delta indicator | default / counting-up |
| `VenueCard` | V1/V2 feature card for B2B section | default / hover |
| `OpsReassuranceCard` | Icon + title + description for operational proof | default |

#### Pricing Components

| Component | Description | States |
|-----------|-------------|--------|
| `PricingTable` | 3-tier B2C comparison table | monthly / annual |
| `PricingCard` | Individual plan card within table | default / highlighted (recommended) / hover |
| `B2BPricingCard` | Full-width B2B pricing/contact card | default / hover |
| `BillingToggle` | Monthly/Annual switch with savings badge | monthly / annual |
| `FeatureMatrix` | Expandable feature comparison grid | collapsed / expanded |
| `FaqAccordion` | Question/answer accordion | closed / open / hover |

#### CTA Components

| Component | Description | States |
|-----------|-------------|--------|
| `PrimaryButton` | Gold/pit-orange filled button (main CTA) | default / hover / focus / disabled / loading |
| `SecondaryButton` | Outlined chalk/white button | default / hover / focus / disabled |
| `GhostButton` | Text-only button with underline | default / hover / focus |

#### Chrome / Decorative Components (Keep)

| Component | Description | Notes |
|-----------|-------------|-------|
| `MonumentText` | Large display text with scroll-reveal | Keep — defines brand typography |
| `MarqueeStrip` | Horizontal scrolling text band | Keep — reduce to 1 on home page |
| `ScrutineeringStamp` | Badge/stamp visual element | Keep — add descriptive subtitle |
| `DeltaStrip` | Time delta HUD overlay | Keep for app pages only |

#### Trust / Compliance

| Component | Description |
|-----------|-------------|
| `TrustBadge` | Icon + text trust signal (GDPR, encryption, uptime) |
| `ComplianceStrip` | Horizontal row of TrustBadges |

---

## 5. Motion & Interaction Rules

### 5.1 Core Principles

1. **Motion serves hierarchy** — guide the eye to what matters, never distract from content.
2. **One hero animation per viewport** — never more than two elements animating simultaneously.
3. **Reduced motion is first-class** — all motion must have a `prefers-reduced-motion` fallback that shows content instantly.
4. **No gating** — motion must never prevent access to content (no "hold to start," no mandatory animations).

### 5.2 Duration Scale

| Token | Duration | Use |
|-------|----------|-----|
| `--duration-instant` | 0ms | Reduced-motion fallback |
| `--duration-micro` | 150ms | Button hover, focus ring, toggle |
| `--duration-fast` | 250ms | Card hover lift, tooltip appear, nav transition |
| `--duration-medium` | 400ms | Section reveal, tab switch, accordion |
| `--duration-slow` | 700ms | Page transition, hero entrance |
| `--duration-dramatic` | 1200ms | MonumentText reveal (display headings only) |

### 5.3 Easing

| Token | Curve | Use |
|-------|-------|-----|
| `--ease-out` | `cubic-bezier(0.16, 1, 0.3, 1)` | Entering elements (default) |
| `--ease-in` | `cubic-bezier(0.7, 0, 0.84, 0)` | Exiting elements |
| `--ease-spring` | `cubic-bezier(0.22, 1.2, 0.36, 1)` | Playful emphasis (CTA press, card flip) |
| `--ease-linear` | `linear` | Marquee scroll, progress bars only |

### 5.4 Scroll-Triggered Animations

| Element | Animation | Trigger | Duration | Reduced-Motion |
|---------|-----------|---------|----------|----------------|
| Section headings | Fade up + translate Y 20px | IntersectionObserver 20% | 400ms | Instant show |
| Cards | Stagger fade up (100ms offset per card) | IntersectionObserver 10% | 300ms each | Instant show |
| KPI counters | Count up from 0 | IntersectionObserver 50% | 800ms | Show final value |
| Screenshots | Fade in + subtle scale 0.98→1.0 | IntersectionObserver 30% | 500ms | Instant show |
| MonumentText | Character-by-character reveal | IntersectionObserver 20% | 1200ms | Instant show |

### 5.5 Micro-Interactions

| Element | Interaction | Animation |
|---------|-------------|-----------|
| Primary button | Hover | Background lightens, subtle glow (`--shadow-glow`), 150ms |
| Primary button | Press | Scale 0.97 + shadow shrink, 100ms, spring ease on release |
| Card | Hover | Translate Y -2px + shadow-elevated, 250ms |
| Nav link | Hover | Underline slides in from left, 200ms |
| Billing toggle | Switch | Thumb slides with spring ease, 300ms |
| FAQ accordion | Expand | Height auto with 300ms ease-out |
| Tab switcher | Switch | Underline slides to active tab, content cross-fades, 250ms |
| Mode selector | Select | Border highlight + scale 1.01 + glow, 300ms |

### 5.6 Reduced Motion Fallback

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

All IntersectionObserver-triggered reveals should check `prefers-reduced-motion` and skip animation, showing content immediately.

### 5.7 What NOT to Animate

- Text content (body paragraphs) — always visible immediately
- Navigation elements — always accessible
- Form inputs — no entry animations
- Pricing numbers — show immediately (counters only on KPI stats)
- Any element that blocks comprehension of what the product is

---

## 6. Responsive + Accessibility Spec

### 6.1 Breakpoints

| Name | Width | Columns | Container | Notes |
|------|-------|---------|-----------|-------|
| `xs` | < 480px | 4 | fluid, 16px margin | Phones portrait |
| `sm` | 480-639px | 4 | fluid, 16px margin | Large phones |
| `md` | 640-1023px | 8 | fluid, 32px margin | Tablets |
| `lg` | 1024-1279px | 12 | fluid, 48px margin | Small desktops |
| `xl` | 1280-1535px | 12 | 1280px max | Standard desktops |
| `2xl` | 1536px+ | 12 | 1280px max | Large screens |

### 6.2 Typography Scaling

| Element | Mobile (xs) | Tablet (md) | Desktop (xl) |
|---------|-------------|-------------|--------------|
| Display | 48px | 72px | 120px |
| H1 | 36px | 48px | 72px |
| H2 | 28px | 36px | 48px |
| H3 | 22px | 26px | 32px |
| Body | 16px | 17px | 18px |
| Caption | 14px | 14px | 14px |
| Telemetry | 12px | 12px | 12px |

**Critical rule:** Body text never below 16px on any device.

### 6.3 Touch Targets

All interactive elements: **minimum 44x44px touch target** (even if visual element is smaller, use padding/invisible hit area).

```css
/* Example: small nav link with adequate touch target */
.nav-link {
  display: inline-flex;
  align-items: center;
  min-height: 44px;
  padding: 12px 16px;
  /* Visual text can be 12px, but the touch area is 44px tall */
}
```

### 6.4 Contrast Requirements (WCAG AA)

| Element | Foreground | Background | Ratio | Pass? |
|---------|-----------|------------|-------|-------|
| Body text | #F0EDE5 (chalk) | #000000 (asphalt) | 16.2:1 | AA/AAA |
| Secondary text | #888888 (steel) | #000000 (asphalt) | 5.3:1 | AA |
| Muted text | #555555 (steel-muted) | #000000 (asphalt) | 3.3:1 | Fail — use for decorative only |
| CTA text | #000000 (asphalt) | #C9A84C (pit-orange) | 7.2:1 | AA/AAA |
| Link text | #C9A84C (pit-orange) | #000000 (asphalt) | 7.2:1 | AA/AAA |
| Error text | #FF2A2A (safety-red) | #000000 (asphalt) | 4.6:1 | AA |

**Action:** `--color-steel-muted` (#555) must NOT be used for functional text — only decorative/tertiary content.

### 6.5 Keyboard Navigation

| Pattern | Behavior |
|---------|----------|
| Skip link | First focusable element: "Skip to main content" → `<main>` |
| Tab order | Follows visual order: logo → nav links → auth buttons → content → footer |
| Focus rings | 2px solid `var(--color-pit-orange)` with 2px offset. Visible on all focusable elements. |
| Escape key | Closes mobile drawer, modals, accordions |
| Arrow keys | Navigate within tab groups, accordion items, pricing toggle |
| Enter/Space | Activates buttons, links, toggles, accordion headers |

### 6.6 ARIA Notes

| Component | ARIA |
|-----------|------|
| ModeSelector | `role="radiogroup"`, each card `role="radio"` with `aria-checked` |
| BillingToggle | `role="switch"` with `aria-checked` (already correct) |
| FaqAccordion | `role="region"` per answer, `aria-expanded` on trigger, `aria-controls` |
| MobileDrawer | `role="dialog"`, `aria-modal="true"`, focus trap |
| ScreenshotGallery | `role="tablist"` for tab nav, `role="tabpanel"` for content |
| ProofStrip KPIs | `aria-live="polite"` for count-up values |
| StickyCtaBar | `role="complementary"`, `aria-label="Quick actions"` |

### 6.7 Image Accessibility

- All product screenshots: descriptive `alt` text ("Score overview showing 87/100 with breakdown by pace, consistency, execution, robustness")
- Decorative images (grid textures, glow effects): `alt=""` + `aria-hidden="true"`
- 3D models: `aria-hidden="true"` with adjacent text description

---

## 7. Implementation Plan (Next.js / React)

### 7.1 CSS Strategy: **Tailwind CSS** (continue existing)

The project already uses Tailwind with custom CSS tokens. Keep this approach but enforce consistency:

- **tokens.css** — All design tokens as CSS custom properties (updated per Section 4)
- **Tailwind config** — Maps tokens to Tailwind utilities (`text-chalk`, `bg-asphalt`, etc.)
- **No inline styles** except for truly dynamic values (scroll-based transforms)
- **Component-scoped styles** — Use Tailwind classes. No CSS Modules (would split the system).

### 7.2 Component Folder Structure (Revised)

```
src/
├── components/
│   ├── chrome/               # App-level chrome (keep existing)
│   │   ├── ChromeLayout.tsx
│   │   ├── DeltaStrip.tsx
│   │   └── ...
│   ├── site/                 # Marketing site structure
│   │   ├── SiteHeader.tsx    # UPDATED — add mobile drawer, B2B nav
│   │   ├── SiteFooter.tsx
│   │   ├── PageShell.tsx
│   │   ├── MobileDrawer.tsx  # NEW
│   │   ├── StickyCtaBar.tsx  # NEW
│   │   └── SkipLink.tsx      # NEW
│   ├── marketing/            # Marketing-specific components
│   │   ├── HeroSection.tsx   # NEW — replaces StartGrid gate
│   │   ├── ModeSelector.tsx  # NEW
│   │   ├── ProofStrip.tsx    # NEW
│   │   ├── HowItWorks.tsx    # NEW
│   │   ├── ProductShowcase.tsx # NEW
│   │   ├── TestimonialCard.tsx # NEW
│   │   ├── VenuePitch.tsx    # NEW — replaces S3Venue
│   │   ├── OpsReassurance.tsx # NEW
│   │   └── DemoCtaSection.tsx # Keep existing
│   ├── pricing/              # Pricing components
│   │   ├── PricingSection.tsx # NEW — wraps table + B2B + FAQ
│   │   ├── PricingTable.tsx  # Keep, refine
│   │   ├── B2BPricingCard.tsx # NEW — full-width B2B card
│   │   ├── BillingToggle.tsx # Extract from PitStop
│   │   └── FeatureMatrix.tsx # NEW — expandable comparison
│   ├── trust/                # Trust + compliance
│   │   ├── TrustBadge.tsx    # NEW
│   │   ├── ComplianceStrip.tsx # NEW
│   │   └── RiskReversal.tsx  # NEW — "No card required" etc.
│   ├── ui/                   # Design system primitives
│   │   ├── MonumentText.tsx  # Keep
│   │   ├── MarqueeStrip.tsx  # Keep
│   │   ├── PrimaryButton.tsx # NEW — replaces PitButton
│   │   ├── SecondaryButton.tsx # NEW — replaces StampButton
│   │   ├── GhostButton.tsx   # NEW
│   │   ├── FaqAccordion.tsx  # Keep
│   │   ├── KpiBlock.tsx      # NEW
│   │   ├── StepCard.tsx      # NEW
│   │   ├── TabSwitcher.tsx   # NEW
│   │   ├── ScreenshotFrame.tsx # NEW
│   │   └── Tooltip.tsx       # Keep
│   ├── rooms/                # DEPRECATED — migrate to marketing/
│   │   ├── StartGrid.tsx     # → HeroSection.tsx
│   │   ├── S1Pain.tsx        # → HowItWorks.tsx (content merged)
│   │   ├── S3Venue.tsx       # → VenuePitch.tsx
│   │   ├── PitStop.tsx       # → PricingSection.tsx
│   │   └── ...               # Others deprecated or merged
│   ├── app/                  # Dashboard components (keep as-is)
│   ├── auth/                 # Auth components (keep)
│   ├── billing/              # Billing components (keep)
│   └── providers/            # Context providers (keep)
├── styles/
│   ├── tokens.css            # UPDATED — revised color tokens
│   ├── textures.css          # Keep
│   └── animations.css        # NEW — centralized animation definitions
├── hooks/
│   ├── useReducedMotion.ts   # Keep
│   ├── useInView.ts          # NEW — IntersectionObserver hook
│   ├── useCountUp.ts         # NEW — animated counter hook
│   └── useCurrency.ts        # Keep
├── data/
│   ├── navigation.ts         # UPDATED — add B2B nav, mobile sections
│   ├── pricing.ts            # Keep
│   ├── testimonials.ts       # NEW
│   └── kpis.ts               # NEW — proof strip data
└── app/
    ├── (marketing)/
    │   ├── page.tsx           # UPDATED — new section order
    │   ├── venues/page.tsx    # NEW — dedicated B2B page
    │   └── ...
    └── ...
```

### 7.3 Performance Plan

| Technique | Target | Implementation |
|-----------|--------|----------------|
| **Image optimization** | WebP/AVIF, responsive srcset | Use `next/image` for all screenshots. Generate 640/1024/1440 variants. |
| **3D model lazy load** | Only load when visible | Dynamic import with IntersectionObserver. Show static image placeholder until 3D is ready. |
| **GSAP tree-shaking** | Reduce bundle size | Import only used plugins: `gsap/ScrollTrigger`. Consider replacing with CSS-only for simple reveals. |
| **Font optimization** | Eliminate FOUT | `next/font` for Inter, Space Grotesk, Space Mono. `font-display: swap`. Subset Latin. |
| **Code splitting** | Per-route chunks | Dynamic import for: MobileDrawer, FeatureMatrix, FAQ, 3D components. |
| **CSS optimization** | Purge unused | Tailwind CSS purge already configured. Verify no unused tokens.css entries. |
| **LCP target** | < 2.5s | Hero headline is text (fast). Ensure no render-blocking assets. |
| **CLS target** | < 0.1 | Reserve space for images (explicit width/height). No layout shift from font loading. |
| **FID target** | < 100ms | Defer non-critical JS (analytics, 3D, Howler audio). |

**Lighthouse target: 90+ on mobile.**

### 7.4 Analytics Instrumentation

| Event | Trigger | Data |
|-------|---------|------|
| `mode_selected` | Click on ModeSelector card | `{mode: "driver" | "venue"}` |
| `cta_click` | Any CTA button click | `{cta_id, section, audience, plan?}` |
| `pricing_toggle` | Billing period switch | `{period: "monthly" | "annual"}` |
| `faq_expand` | FAQ item opened | `{question_index}` |
| `screenshot_view` | Screenshot gallery tab switch | `{tab: "engineer" | "strategist", image}` |
| `scroll_depth` | 25% / 50% / 75% / 100% | `{depth_percent}` |
| `pilot_form_submit` | B2B pilot form completed | `{venue_name, fleet_size}` |
| `proof_strip_visible` | Proof strip enters viewport | `{}` (impression) |

Continue using Plausible (already configured). Add custom events via `plausible()` calls.

---

## 8. Phased Backlog

### Week 1 — "Quick Wins" (Ship Immediately)

High-impact, low-effort changes that improve comprehension and conversion without restructuring.

| # | Task | Component | Effort | Impact |
|---|------|-----------|--------|--------|
| 1 | **Remove StartGrid gate** — auto-play animation, allow immediate scroll | `StartGrid.tsx` | 2h | Critical |
| 2 | **Add hero subtitle** — "Telemetry reports that coach every driver. Event tools for every venue." | `StartGrid.tsx` | 30min | Critical |
| 3 | **Add hero CTAs** — `[Try Free Report]` + `[Book a Pilot]` below subtitle | `StartGrid.tsx` | 1h | Critical |
| 4 | **Fix accent color aliases** — restore distinct green, yellow, purple in tokens.css | `tokens.css` | 30min | Medium |
| 5 | **Add "For Venues" to nav** — link to /contact (later to /venues) | `navigation.ts`, `SiteHeader.tsx` | 1h | High |
| 6 | **Add mobile hamburger menu** — drawer component with audience sections | `SiteHeader.tsx`, new `MobileDrawer.tsx` | 4h | High |
| 7 | **Add skip-to-content link** | `layout.tsx` | 30min | Medium |
| 8 | **Increase nav touch targets** — min 44px height on all nav links | `SiteHeader.tsx` | 1h | Medium |
| 9 | **Add "See Plans" link in nav** — quick path to pricing section | `navigation.ts` | 30min | Medium |
| 10 | **Fix Strategist Mode screenshot repetition** | `S3Product.tsx` | 1h | Low |

**Estimated total: 12 hours.**

### Week 2 — "Structural Improvements" (High-Impact Restructuring)

| # | Task | Component | Effort | Impact |
|---|------|-----------|--------|--------|
| 11 | **Build ModeSelector component** — "Driver" / "Venue" fork after hero | New `ModeSelector.tsx` | 4h | Critical |
| 12 | **Build ProofStrip component** — KPI counters + trust signals | New `ProofStrip.tsx` | 3h | High |
| 13 | **Build HowItWorks section** — 3-step "Upload → Analyze → Coach" | New `HowItWorks.tsx` | 3h | High |
| 14 | **Restructure home page section order** — implement new 10-section layout | `(marketing)/page.tsx` | 4h | Critical |
| 15 | **Build TestimonialCard** — prepare 2-3 driver testimonials (placeholder content OK) | New `TestimonialCard.tsx` | 2h | High |
| 16 | **Refactor PitStop into PricingSection** — separate B2B card to full-width row | New `PricingSection.tsx` | 3h | Medium |
| 17 | **Build ProductShowcase with tab switcher** — Engineer / Strategist tabs + screenshots | New `ProductShowcase.tsx` | 4h | High |
| 18 | **Build StickyCtaBar for mobile** — bottom-fixed bar after scrolling past hero | New `StickyCtaBar.tsx` | 2h | Medium |
| 19 | **Add `useInView` hook** — standardize IntersectionObserver usage across sections | New `useInView.ts` | 2h | Medium |
| 20 | **Update tokens.css** — implement full revised token system from Section 4 | `tokens.css` | 2h | Medium |

**Estimated total: 29 hours.**

### Later — "Full Redesign" (3-4 Weeks)

| # | Task | Effort | Impact |
|---|------|--------|--------|
| 21 | **Create `/venues` page** — full B2B journey with V1/V2 explanation, ops dashboard, ROI calculator, pilot timeline | 16h | Critical (B2B) |
| 22 | **Create `/book` (Pilot) page** — timeline, requirements, fleet sizing, pricing shape, calendar embed | 12h | Critical (B2B) |
| 23 | **Build OpsReassurance section** — battery workflow, zero-touch reports, SOC dashboard proof | 4h | High (B2B) |
| 24 | **Build ROI mini-calculator** — B2B: staff hours saved, driver retention. B2C: average improvement delta. | 8h | High |
| 25 | **Collect real testimonials** — reach out to existing users, get photos + quotes + result deltas | n/a (content) | Critical |
| 26 | **Full design system documentation** — Storybook or similar for all components | 16h | Medium |
| 27 | **3D model progressive loading** — lazy-load with static image placeholder, IntersectionObserver trigger | 4h | Medium |
| 28 | **GSAP → CSS-only audit** — replace simple fade/translate animations with CSS to reduce bundle | 8h | Medium |
| 29 | **Lighthouse performance audit** — run full audit, fix any <90 scores | 8h | High |
| 30 | **A/B test framework** — mode selector vs. single-page, hero copy variants | 8h | High |
| 31 | **Customers/case studies page** — 2-3 detailed case studies (kart academy, endurance team, rental venue) | 12h | High |
| 32 | **High-contrast mode** — toggle for users who need stronger contrast | 4h | Medium |
| 33 | **Remove Garage section from home** — move tech stack to footer or /product | 1h | Low |
| 34 | **Replace decorative marquee** — swap one marquee for social proof ticker | 2h | Low |

---

## Appendix A: Key Decisions + Rationale

### Clarity Over Spectacle
The "Hold to Start" gate is atmospheric but blocks the product message. **Decision:** Remove it. The premium feel comes from typography, spacing, and controlled motion — not from gating content.

### Sharp Edges Over Rounded
The current design uses `border-radius: 0` on most elements. **Decision:** Keep this. Sharp edges (0-4px) reinforce the precision/instrumentation identity. Rounding would soften the brand toward "friendly SaaS" — wrong for motorsport.

### Single Page With Forks Over Separate Funnels
B2C and B2B could have completely separate landing pages. **Decision:** Keep a single home page with a mode selector. The unified engine is a differentiator — showing both audiences on one page reinforces "same quality for everyone." Dedicated B2B pages (`/venues`, `/book`) handle deep-dive conversion.

### Tailwind Over CSS Modules
Both are valid. **Decision:** Continue with Tailwind. The existing codebase is 100% Tailwind. Switching would require rewriting 141 components. Tailwind's utility-first approach also makes the design system enforceable via config.

### Gold (Pit-Orange) as Primary CTA Color
The design system recommends the gold `#C9A84C` for CTAs. **Decision:** Keep. It has excellent contrast on dark backgrounds (7.2:1), reads as "premium," and differentiates from the red brand accent.

### No Full-Width Images in Hero
Many SaaS sites use a large product screenshot in the hero. **Decision:** Keep the text-dominant hero. The product is data-heavy — a screenshot at hero size would be illegible on mobile. Use the ProofStrip + ProductShowcase (with tab switcher and properly-framed screenshots) to prove the product visually.

---

## Appendix B: Component API Sketches

### ModeSelector

```tsx
interface ModeSelectorProps {
  onSelect?: (mode: 'driver' | 'venue') => void;
}

// Two cards side by side (stack on mobile)
// Each card: icon + title + 1-line description + arrow
// Click scrolls to relevant section (4 for driver, 7 for venue)
// Both sections always visible — selection highlights, doesn't hide
```

### ProofStrip

```tsx
interface ProofStripProps {
  kpis: Array<{
    value: number;
    suffix?: string;     // "+", "%", etc.
    label: string;       // "Sessions Analyzed"
  }>;
  logos?: Array<{ src: string; alt: string }>;
}

// Horizontal strip, dark bg, monospace numbers
// Count-up animation on first viewport entry
// aria-live="polite" for screen readers
```

### HowItWorks

```tsx
interface Step {
  number: 1 | 2 | 3;
  title: string;        // "Upload", "Analyze", "Coach"
  description: string;
  icon: ReactNode;
}

// Three connected cards with a progress line between them
// Stagger reveal on scroll
// CTA below: "Try It Free"
```

### ProductShowcase

```tsx
interface ProductShowcaseProps {
  tabs: Array<{
    id: string;          // "engineer" | "strategist"
    label: string;
    screenshots: Array<{
      src: string;
      alt: string;
      caption: string;
    }>;
  }>;
}

// Tab switcher at top
// Screenshot gallery with dark chrome frame
// Each screenshot has a 1-line caption
// Cross-fade between tabs (250ms)
```

---

*This document is the single source of truth for the Lap Coach UI/UX redesign. All implementation should reference these specifications. When tradeoffs arise between spectacle and clarity, choose clarity.*
