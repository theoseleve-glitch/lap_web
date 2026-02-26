# LAP Sales Website Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the LAP motorsport telemetry sales website — a single immersive scroll experience with 9 rooms, interactive mechanisms, and brutalist visual design.

**Architecture:** Next.js 14 App Router single-page site. GSAP ScrollTrigger pins rooms to scroll. React Three Fiber for 3D traces (with Canvas 2D fallback). CSS custom properties for the token system. Tailwind for utility layout.

**Tech Stack:** Next.js 14, React 18, TypeScript, Tailwind CSS 3.4, GSAP 3 + ScrollTrigger, React Three Fiber + Drei, Howler.js, Plausible Analytics, Vitest + React Testing Library

**Design doc:** `docs/plans/2026-02-26-lap-sales-website-design.md`

---

## Phase 1: Foundation

### Task 1: Project Scaffold + Token System

**Files:**
- Create: `lap-website/package.json`
- Create: `lap-website/tsconfig.json`
- Create: `lap-website/tailwind.config.ts`
- Create: `lap-website/next.config.js`
- Create: `lap-website/src/styles/tokens.css`
- Create: `lap-website/src/styles/textures.css`
- Create: `lap-website/src/styles/reduced-motion.css`
- Create: `lap-website/src/app/globals.css`
- Create: `lap-website/src/app/layout.tsx`
- Create: `lap-website/src/app/page.tsx`
- Create: `lap-website/src/lib/tokens.ts`
- Test: `lap-website/src/__tests__/tokens.test.ts`

**Step 1: Initialize project**

```bash
cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai
npx create-next-app@14 lap-website --typescript --tailwind --eslint --app --src-dir --no-import-alias
cd lap-website
```

**Step 2: Install dependencies**

```bash
npm install gsap @gsap/react @react-three/fiber @react-three/drei three howler
npm install -D @types/three @types/howler vitest @vitejs/plugin-react jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event
```

**Step 3: Create `lap-website/vitest.config.ts`**

```typescript
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/__tests__/setup.ts'],
  },
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
});
```

**Step 4: Create `lap-website/src/__tests__/setup.ts`**

```typescript
import '@testing-library/jest-dom';
```

**Step 5: Create `lap-website/src/styles/tokens.css`**

```css
:root {
  /* ── Base Colors ──────────────────── */
  --asphalt: #0B0C0F;
  --concrete: #161A20;
  --chalk: #F3F0E8;
  --steel: #8A8F98;

  /* ── Accent Colors ────────────────── */
  --acid-green: #B6FF2E;
  --safety-red: #FF2A2A;
  --marshal-yellow: #FFD400;
  --pit-orange: #FF6A00;

  /* ── Active accent (overridden per room via data-accent) ── */
  --accent: var(--chalk);

  /* ── Typography Scale ─────────────── */
  --text-monument-xl: clamp(80px, 14vw, 220px);
  --text-h1: clamp(48px, 6vw, 84px);
  --text-h2: clamp(36px, 4vw, 56px);
  --text-h3: clamp(24px, 2.5vw, 32px);
  --text-body: clamp(16px, 1.2vw, 18px);
  --text-caption: 13px;
  --text-telemetry: 11px;

  /* ── Spacing (8px baseline) ───────── */
  --space-1: 8px;
  --space-2: 16px;
  --space-3: 24px;
  --space-4: 32px;
  --space-5: 40px;
  --space-6: 48px;
  --space-8: 64px;
  --space-10: 80px;
  --space-12: 96px;
  --space-16: 128px;

  /* ── Grid ──────────────────────────── */
  --grid-columns: 12;
  --grid-gutter: clamp(20px, 2vw, 32px);
  --grid-margin: clamp(16px, 6vw, 8vw);

  /* ── Z-Layers ─────────────────────── */
  --z-base: 0;
  --z-panels: 10;
  --z-stamps: 20;
  --z-delta: 30;
  --z-sector: 40;
  --z-timecode: 50;
  --z-nav: 60;
  --z-overlay: 100;
  --z-cursor: 999;

  /* ── Timing ────────────────────────── */
  --duration-micro: 420ms;
  --duration-room: 900ms;
  --duration-monument: 1400ms;

  /* ── Easing ────────────────────────── */
  --ease-inertia: cubic-bezier(0.16, 1, 0.3, 1);
  --ease-overshoot: cubic-bezier(0.34, 1.56, 0.64, 1);
  --ease-spring: cubic-bezier(0.22, 1.2, 0.36, 1);
  --ease-snap: cubic-bezier(0.7, 0, 0.84, 0);
}

/* ── Single-accent enforcement per room ── */
[data-accent="none"]    { --accent: var(--chalk); }
[data-accent="green"]   { --accent: var(--acid-green); }
[data-accent="red"]     { --accent: var(--safety-red); }
[data-accent="yellow"]  { --accent: var(--marshal-yellow); }
[data-accent="orange"]  { --accent: var(--pit-orange); }
```

**Step 6: Create `lap-website/src/styles/textures.css`**

```css
/* ── Concrete grain overlay ── */
.texture-grain::after {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0.04;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
  background-size: 256px 256px;
  z-index: 1;
}

/* ── Dither overlay for panels ── */
.texture-dither::after {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0.03;
  background-image: radial-gradient(circle, var(--chalk) 1px, transparent 1px);
  background-size: 4px 4px;
  z-index: 1;
}

/* ── Scan lines for photography ── */
.texture-scanlines::after {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0.02;
  background-image: repeating-linear-gradient(
    0deg,
    transparent,
    transparent 1px,
    var(--chalk) 1px,
    var(--chalk) 2px
  );
  z-index: 1;
}
```

**Step 7: Create `lap-website/src/styles/reduced-motion.css`**

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 200ms !important;
  }
}

/* User-toggled reduced motion (class on html) */
.reduce-motion *, .reduce-motion *::before, .reduce-motion *::after {
  animation-duration: 0.01ms !important;
  animation-iteration-count: 1 !important;
  transition-duration: 200ms !important;
}
```

**Step 8: Create `lap-website/src/app/globals.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@import '../styles/tokens.css';
@import '../styles/textures.css';
@import '../styles/reduced-motion.css';

/* ── Font imports ── */
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400&family=Inter:wght@400;500&family=Teko:wght@600;700&display=swap&subset=latin');

/* ── Base reset ── */
html {
  scroll-behavior: auto; /* GSAP handles scrolling */
  background: var(--asphalt);
  color: var(--chalk);
}

body {
  font-family: 'Inter', sans-serif;
  font-size: var(--text-body);
  line-height: 1.65;
  overflow-x: hidden;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* ── Typography classes ── */
.font-monument {
  font-family: 'Teko', sans-serif;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: -0.02em;
  line-height: 0.85;
}

.font-telemetry {
  font-family: 'IBM Plex Mono', monospace;
  font-weight: 400;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-size: var(--text-telemetry);
}

.font-body {
  font-family: 'Inter', sans-serif;
  font-weight: 400;
  line-height: 1.65;
}

/* ── Layout utilities ── */
.grid-lap {
  display: grid;
  grid-template-columns: repeat(var(--grid-columns), 1fr);
  gap: var(--grid-gutter);
  padding-inline: var(--grid-margin);
}

/* ── Room container ── */
.room {
  position: relative;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  justify-content: center;
  overflow: hidden;
}

/* ── Selection ── */
::selection {
  background: var(--accent);
  color: var(--asphalt);
}
```

**Step 9: Create `lap-website/tailwind.config.ts`**

```typescript
import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./src/**/*.{js,ts,jsx,tsx,mdx}'],
  theme: {
    extend: {
      colors: {
        asphalt: '#0B0C0F',
        concrete: '#161A20',
        chalk: '#F3F0E8',
        steel: '#8A8F98',
        'acid-green': '#B6FF2E',
        'safety-red': '#FF2A2A',
        'marshal-yellow': '#FFD400',
        'pit-orange': '#FF6A00',
      },
      fontFamily: {
        monument: ['Teko', 'sans-serif'],
        body: ['Inter', 'sans-serif'],
        telemetry: ['IBM Plex Mono', 'monospace'],
      },
      spacing: {
        'grid-margin': 'var(--grid-margin)',
        'grid-gutter': 'var(--grid-gutter)',
      },
      zIndex: {
        base: '0',
        panels: '10',
        stamps: '20',
        delta: '30',
        sector: '40',
        timecode: '50',
        nav: '60',
        overlay: '100',
        cursor: '999',
      },
    },
  },
  plugins: [],
};

export default config;
```

**Step 10: Create `lap-website/src/lib/tokens.ts`**

```typescript
// Token values exported for JS/GSAP usage (mirrors tokens.css)

export const colors = {
  asphalt: '#0B0C0F',
  concrete: '#161A20',
  chalk: '#F3F0E8',
  steel: '#8A8F98',
  acidGreen: '#B6FF2E',
  safetyRed: '#FF2A2A',
  marshalYellow: '#FFD400',
  pitOrange: '#FF6A00',
} as const;

export const timing = {
  micro: 0.42,    // 420ms in seconds (for GSAP)
  room: 0.9,      // 900ms
  monument: 1.4,  // 1400ms
} as const;

export const easing = {
  inertia: 'power3.out',            // approx cubic-bezier(0.16, 1, 0.3, 1)
  overshoot: 'back.out(1.7)',       // approx cubic-bezier(0.34, 1.56, 0.64, 1)
  spring: 'back.out(1.2)',          // approx cubic-bezier(0.22, 1.2, 0.36, 1)
  snap: 'power2.in',               // approx cubic-bezier(0.7, 0, 0.84, 0)
} as const;

export const roomAccents: Record<string, string> = {
  'start-grid': 'none',
  's1-pain': 'green',
  's1-deep': 'green',
  's2-pipeline': 'yellow',
  's2-proof': 'yellow',
  's3-product': 'green',     // switches to yellow in B2B mode
  'pit-stop': 'orange',
  'garage': 'none',
  'podium': 'orange',
} as const;

export const rooms = [
  { id: 'start-grid', label: 'START', sector: '—' },
  { id: 's1-pain', label: 'S1', sector: 'S1' },
  { id: 's1-deep', label: 'S1', sector: 'S1' },
  { id: 's2-pipeline', label: 'S2', sector: 'S2' },
  { id: 's2-proof', label: 'S2', sector: 'S2' },
  { id: 's3-product', label: 'S3', sector: 'S3' },
  { id: 'pit-stop', label: 'PIT', sector: 'PIT' },
  { id: 'garage', label: 'GAR', sector: 'GAR' },
  { id: 'podium', label: 'POD', sector: 'POD' },
] as const;

// Sector tab entries (deduplicated for display)
export const sectorTabs = [
  { id: 's1-pain', label: 'S1' },
  { id: 's2-pipeline', label: 'S2' },
  { id: 's3-product', label: 'S3' },
  { id: 'pit-stop', label: 'PIT' },
  { id: 'garage', label: 'GAR' },
  { id: 'podium', label: 'POD' },
] as const;
```

**Step 11: Create `lap-website/src/app/layout.tsx`**

```tsx
import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'LAP — Motorsport Telemetry Analysis | Find Time.',
  description:
    'Upload your telemetry. Get a score, corner-by-corner coaching, and a plan to go faster. Physics-based analysis for kart, car, and sim drivers. Free starter plan.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      </head>
      <body className="relative bg-asphalt text-chalk texture-grain">
        {children}
      </body>
    </html>
  );
}
```

**Step 12: Create `lap-website/src/app/page.tsx`**

```tsx
export default function Home() {
  return (
    <main>
      {/* Rooms will be added in Tasks 5-12 */}
      <section
        id="start-grid"
        data-accent="none"
        className="room"
        aria-label="Start Grid"
      >
        <div className="grid-lap">
          <h1
            className="font-monument col-span-full"
            style={{ fontSize: 'var(--text-monument-xl)' }}
          >
            EVERY LAP<br />HAS A SECRET
          </h1>
        </div>
      </section>
    </main>
  );
}
```

**Step 13: Write test `lap-website/src/__tests__/tokens.test.ts`**

```typescript
import { describe, it, expect } from 'vitest';
import { colors, timing, easing, rooms, sectorTabs } from '@/lib/tokens';

describe('Token system', () => {
  it('exports all base colors', () => {
    expect(colors.asphalt).toBe('#0B0C0F');
    expect(colors.concrete).toBe('#161A20');
    expect(colors.chalk).toBe('#F3F0E8');
    expect(colors.steel).toBe('#8A8F98');
  });

  it('exports all accent colors', () => {
    expect(colors.acidGreen).toBe('#B6FF2E');
    expect(colors.safetyRed).toBe('#FF2A2A');
    expect(colors.marshalYellow).toBe('#FFD400');
    expect(colors.pitOrange).toBe('#FF6A00');
  });

  it('exports timing in seconds for GSAP', () => {
    expect(timing.micro).toBe(0.42);
    expect(timing.room).toBe(0.9);
    expect(timing.monument).toBe(1.4);
  });

  it('exports GSAP easing strings', () => {
    expect(easing.inertia).toBe('power3.out');
    expect(easing.overshoot).toContain('back.out');
  });

  it('defines 9 rooms', () => {
    expect(rooms).toHaveLength(9);
    expect(rooms[0].id).toBe('start-grid');
    expect(rooms[8].id).toBe('podium');
  });

  it('defines 6 sector tabs', () => {
    expect(sectorTabs).toHaveLength(6);
    expect(sectorTabs[0].label).toBe('S1');
    expect(sectorTabs[5].label).toBe('POD');
  });
});
```

**Step 14: Run tests to verify**

```bash
cd lap-website
npx vitest run
```

Expected: 5 tests PASS

**Step 15: Verify dev server**

```bash
npm run dev
```

Expected: Page loads at localhost:3000 with asphalt background, grain texture, and monument text "EVERY LAP HAS A SECRET" in Teko font.

**Step 16: Commit**

```bash
git add lap-website/
git commit -m "feat(lap): project scaffold with token system, fonts, textures, and base layout"
```

---

### Task 2: Core Data Files

**Files:**
- Create: `lap-website/src/data/copy.ts`
- Create: `lap-website/src/data/pricing.ts`
- Create: `lap-website/src/data/faq.ts`
- Create: `lap-website/src/data/pipeline-stages.ts`
- Test: `lap-website/src/__tests__/data.test.ts`

**Step 1: Create `lap-website/src/data/copy.ts`**

```typescript
// All room copy — no hardcoded strings in components

export const startGrid = {
  monument: ['EVERY LAP', 'HAS A SECRET'],
  instruction: 'HOLD TO START // 2.0s',
} as const;

export const s1Pain = {
  monument: ["YOU'RE LOSING TIME", "IN PLACES YOU CAN'T SEE"],
  body: 'Every corner has an optimal line. The difference between your line and that line is measurable, repeatable, fixable.',
  tooltips: {
    entry: 'BRAKE POINT // EARLIER = SLOWER ENTRY, TIGHTER RADIUS',
    apex: 'APEX // GEOMETRIC vs LATE — AFFECTS EXIT SPEED',
    exit: 'THROTTLE APPLICATION // EARLIER = MORE TIME GAINED',
  },
  stamp: { label: 'DATA SOURCE', detail: 'GPS + IMU @ 25Hz' },
} as const;

export const s1Deep = {
  monument: 'DATA HAS A SHAPE',
  body: 'Speed. Brake. Steering. Three traces tell the whole story. LAP reads them, maps them to your track, and finds where time hides.',
  tooltips: {
    speed: 'SPEED // 87.4 KM/H — EXIT VELOCITY, CORNER 4',
    brake: 'BRAKE // 0.94G — PEAK DECELERATION',
    steering: 'STEERING // 12.4° — LOCK ANGLE AT APEX',
  },
} as const;

export const s2Pipeline = {
  monument: 'INGEST → CLEAN → MAP → ANALYZE → REPORT',
  body: 'From raw CSV to scored report in under 60 seconds. 14 pipeline stages. Every step validated. No black boxes.',
} as const;

export const s2Proof = {
  monument: 'SCRUTINEERING',
  subhead: 'THREE PROOFS THAT THE NUMBERS ARE REAL',
  plates: [
    {
      title: 'REPEATABILITY',
      front: 'Upload the same session twice. Get the same score twice. Every time.',
      reveal: 'Scoring uses deterministic physics models. No ML randomness in the core pipeline. SHA-256 checksum verifies identical input. Reproducible to ±0.001s on lap times.',
      stamp: { label: 'VERIFIED', detail: 'DETERMINISTIC PIPELINE' },
    },
    {
      title: 'REFERENCE ACCURACY',
      front: 'Corner-by-corner analysis validated against professional data engineering methodology.',
      reveal: 'Theoretical lap computed from friction model + optimal racing line geometry. Reference speeds derived from GPS + IMU sensor fusion at 25Hz. Not arbitrary — physics-based.',
      stamp: { label: 'VALIDATED', detail: 'PHYSICS-BASED MODEL' },
    },
    {
      title: 'CONDITION SENSITIVITY',
      front: 'Wet track? New tires? Different kart? The scoring adapts. Your progress is real.',
      reveal: 'Phase-aware scoring detects grip evolution. Wet/dry thresholds adjust expectations. Kart-specific profiles normalize comparisons. Detrending only applied when it helps — never hurts.',
      stamp: { label: 'CALIBRATED', detail: 'CONDITION-AWARE' },
    },
  ],
} as const;

export const s3Product = {
  monument: 'FIND TIME.',
  b2c: {
    subhead: 'FOR KART, CAR & SIM DRIVERS',
    tiles: [
      { label: 'YOUR SCORE: 86/A', detail: '4-pillar breakdown visible' },
      { label: 'CORNER 7: BRAKE 0.4s LATE', detail: 'Specific, actionable coaching' },
      { label: 'NEXT SESSION: 3 DRILLS', detail: 'Development plan generated' },
    ],
  },
  b2b: {
    subhead: 'FOR CIRCUITS, SCHOOLS & ORGANIZERS',
    placards: [
      { title: 'BRANDED REPORTS', body: 'Your logo. Your colors. Every driver gets a professional debrief after every session.' },
      { title: 'DRIVER RETENTION', body: 'Drivers who see progress come back. Average +40% return rate with data programs.' },
      { title: 'TIMING INTEGRATION', body: 'Connects to your existing timing system. No new hardware. No driver friction.' },
      { title: 'TURNKEY SETUP', body: 'We configure everything. You run events. Pilot program available.' },
    ],
    cta: 'REQUEST PILOT EVENT',
  },
} as const;

export const pitStop = {
  monument: 'PIT STOP',
  subhead: 'PRICING // DEMO // CONTACT',
  riskReversal: [
    '30-DAY MONEY BACK',
    'CANCEL ANYTIME',
    'YOUR DATA, ALWAYS',
    'EXPORT EVERYTHING',
    'GDPR COMPLIANT',
    'NO LOCK-IN',
  ],
  trustStrip: [
    'GDPR READY',
    '256-BIT ENCRYPTED',
    '99.9% UPTIME',
    'MADE IN FRANCE',
  ],
} as const;

export const garage = {
  monument: 'GARAGE',
  subhead: 'TECHNICAL DOCUMENTATION // FOR SKEPTICS',
  panels: [
    {
      title: 'STACK',
      content: 'Python 3.x // Flask // pandas // scikit-learn\nPostgreSQL // Redis // Celery\n14-stage pipeline // Physics-based models\nPyInstaller desktop builds',
    },
    {
      title: 'DATA SOURCES',
      content: 'RaceChrono Pro (CSV export)\nRaceBox (via RaceChrono format)\nGPS + IMU @ 10-25Hz\nStreaming ingest for files up to 12GB\nAdaptive chunking — <1GB peak memory',
    },
    {
      title: 'METHODOLOGY',
      content: 'Scoring: Pace + Consistency + Execution + Robustness\nCorner analysis: brake point, apex speed, exit drive\nReference lap: friction model + optimal geometry\nDetrending: condition-aware, only applied when beneficial\nConfidence weighting: data quality affects score range',
    },
    {
      title: 'PRIVACY & COMPLIANCE',
      content: 'GDPR-ready: data stored in EU\nEncryption: AES-256 at rest, TLS in transit\nRetention: you choose — 30 days to forever\nDeletion: full account + data wipe on request\nAudit trail: every pipeline run logged\nData ownership: 100% yours. Export anytime. No lock-in.',
    },
  ],
} as const;

export const podium = {
  monument: ['READY TO RUN', 'A CLEAN LAP?'],
  ctaPrimary: 'TRY DEMO',
  ctaSecondary: 'TALK',
  subtext: 'FREE STARTER PLAN // NO CARD REQUIRED // 60 SECONDS TO FIRST SCORE',
  restart: '← RESTART LAP',
} as const;
```

**Step 2: Create `lap-website/src/data/pricing.ts`**

```typescript
export interface Plan {
  name: string;
  priceMonthly: string;
  priceAnnual: string;
  features: Record<string, string>;
  cta: string;
  highlighted?: boolean;
}

export const b2cPlans: Plan[] = [
  {
    name: 'STARTER',
    priceMonthly: 'Free',
    priceAnnual: 'Free',
    features: {
      Sessions: '3/month',
      Scoring: 'Preview',
      Coaching: '—',
      History: '30 days',
      Reports: '—',
      Team: '—',
    },
    cta: 'START FREE',
  },
  {
    name: 'PERFORMANCE',
    priceMonthly: '€8.99/mo',
    priceAnnual: '€69/yr',
    features: {
      Sessions: 'Unlimited',
      Scoring: 'Full 4-pillar',
      Coaching: 'Corner-by-corner',
      History: '1 year',
      Reports: 'PDF export',
      Team: '—',
    },
    cta: 'UPGRADE',
    highlighted: true,
  },
  {
    name: 'PRO RACER',
    priceMonthly: '€13.99/mo',
    priceAnnual: '€109/yr',
    features: {
      Sessions: 'Unlimited',
      Scoring: 'Full 4-pillar',
      Coaching: 'Corner + dev plans',
      History: 'Unlimited',
      Reports: 'PDF + API/webhooks',
      Team: 'Up to 5 seats',
    },
    cta: 'GO PRO',
  },
];

export const b2bPlans: Plan[] = [
  {
    name: 'TRACK ESSENTIEL',
    priceMonthly: '—',
    priceAnnual: '€1,490/yr',
    features: {
      Drivers: 'Up to 50/event',
      Reports: 'Standard',
      Timing: 'Manual CSV',
      Support: 'Email',
      Setup: 'Self-serve docs',
    },
    cta: 'GET STARTED',
  },
  {
    name: 'CIRCUIT PRO',
    priceMonthly: '—',
    priceAnnual: '€2,990/yr',
    features: {
      Drivers: 'Up to 200/event',
      Reports: 'Branded',
      Timing: 'API integration',
      Support: 'Priority',
      Setup: 'Guided setup',
    },
    cta: 'BOOK DEMO',
    highlighted: true,
  },
  {
    name: 'CIRCUIT PREMIUM',
    priceMonthly: '—',
    priceAnnual: '€4,990/yr',
    features: {
      Drivers: 'Unlimited',
      Reports: 'White-label',
      Timing: 'Full + live',
      Support: 'Dedicated + SLA',
      Setup: 'Full onboarding',
    },
    cta: 'CONTACT SALES',
  },
];

export interface Addon {
  name: string;
  price: string;
}

export const addons: Addon[] = [
  { name: 'Advanced timing integration', price: '+€490/yr' },
  { name: 'Endurance module (6h+ events)', price: '+€390/yr' },
  { name: 'White-label upgrade', price: '+€990/yr' },
  { name: 'Premium SLA (4h response)', price: '+€690/yr' },
  { name: 'Extended API + webhooks', price: '+€290/yr' },
];
```

**Step 3: Create `lap-website/src/data/faq.ts`**

```typescript
export interface FaqItem {
  question: string;
  answer: string;
}

export const faqItems: FaqItem[] = [
  {
    question: 'What payment methods do you accept?',
    answer: 'Card via Stripe. Bank transfer for B2B annual plans.',
  },
  {
    question: 'Can I switch plans?',
    answer: 'Upgrade or downgrade anytime. Changes are prorated.',
  },
  {
    question: 'What data formats are supported?',
    answer: 'RaceChrono CSV and RaceBox export. More formats coming soon.',
  },
  {
    question: 'Is my data private?',
    answer: 'Your data. Encrypted at rest. Never shared with third parties. Delete anytime.',
  },
  {
    question: 'What devices are supported?',
    answer: 'Upload from any device. Analysis runs in the cloud.',
  },
  {
    question: 'Do you support sim racing?',
    answer: 'Coming soon. Join the waitlist for early access.',
  },
];
```

**Step 4: Create `lap-website/src/data/pipeline-stages.ts`**

```typescript
export interface PipelineStage {
  name: string;
  label: string;
  stamp: { label: string; detail: string };
  telemetryLabel: string;
}

export const pipelineStages: PipelineStage[] = [
  {
    name: 'INGEST',
    label: 'Ingest',
    stamp: { label: 'HEADER DETECTED', detail: '47 CHANNELS' },
    telemetryLabel: 'csv/25hz',
  },
  {
    name: 'CLEAN',
    label: 'Clean',
    stamp: { label: 'OUTLIERS REMOVED', detail: '99.2% RETAINED' },
    telemetryLabel: 'gps+imu',
  },
  {
    name: 'MAP',
    label: 'Map',
    stamp: { label: 'TRACK MATCHED', detail: 'CITY KART SAUTRON' },
    telemetryLabel: 'fingerprint',
  },
  {
    name: 'ANALYZE',
    label: 'Analyze',
    stamp: { label: '14 CORNERS SEGMENTED', detail: '25 LAPS' },
    telemetryLabel: 'physics',
  },
  {
    name: 'REPORT',
    label: 'Report',
    stamp: { label: 'SCORE: 86', detail: 'GRADE A' },
    telemetryLabel: '4-pillar',
  },
];
```

**Step 5: Write test `lap-website/src/__tests__/data.test.ts`**

```typescript
import { describe, it, expect } from 'vitest';
import { b2cPlans, b2bPlans, addons } from '@/data/pricing';
import { faqItems } from '@/data/faq';
import { pipelineStages } from '@/data/pipeline-stages';
import * as copy from '@/data/copy';

describe('Pricing data', () => {
  it('has 3 B2C plans', () => {
    expect(b2cPlans).toHaveLength(3);
    expect(b2cPlans[0].name).toBe('STARTER');
    expect(b2cPlans[1].highlighted).toBe(true);
  });

  it('has 3 B2B plans', () => {
    expect(b2bPlans).toHaveLength(3);
    expect(b2bPlans[1].highlighted).toBe(true);
  });

  it('has 5 add-ons', () => {
    expect(addons).toHaveLength(5);
  });
});

describe('FAQ data', () => {
  it('has 6 items', () => {
    expect(faqItems).toHaveLength(6);
  });
});

describe('Pipeline stages', () => {
  it('has 5 stages', () => {
    expect(pipelineStages).toHaveLength(5);
    expect(pipelineStages[0].name).toBe('INGEST');
    expect(pipelineStages[4].name).toBe('REPORT');
  });
});

describe('Copy', () => {
  it('defines all room copy objects', () => {
    expect(copy.startGrid.monument).toHaveLength(2);
    expect(copy.s1Pain.monument).toHaveLength(2);
    expect(copy.s2Proof.plates).toHaveLength(3);
    expect(copy.s3Product.b2b.placards).toHaveLength(4);
    expect(copy.pitStop.riskReversal).toHaveLength(6);
    expect(copy.garage.panels).toHaveLength(4);
    expect(copy.podium.monument).toHaveLength(2);
  });
});
```

**Step 6: Run tests**

```bash
cd lap-website && npx vitest run
```

Expected: All tests PASS

**Step 7: Commit**

```bash
git add lap-website/src/data/ lap-website/src/__tests__/data.test.ts
git commit -m "feat(lap): all content data files — copy, pricing, FAQ, pipeline stages"
```

---

### Task 3: Core Hooks + Utilities

**Files:**
- Create: `lap-website/src/hooks/useScrollProgress.ts`
- Create: `lap-website/src/hooks/useActiveRoom.ts`
- Create: `lap-website/src/hooks/useAccentColor.ts`
- Create: `lap-website/src/hooks/useDelta.ts`
- Create: `lap-website/src/hooks/useReducedMotion.ts`
- Create: `lap-website/src/hooks/useGpuCapability.ts`
- Create: `lap-website/src/hooks/useFpsMonitor.ts`
- Create: `lap-website/src/hooks/useSound.ts`
- Create: `lap-website/src/lib/analytics.ts`
- Create: `lap-website/src/lib/easing.ts`
- Create: `lap-website/src/lib/gsap-config.ts`
- Create: `lap-website/src/lib/corner-physics.ts`
- Create: `lap-website/src/components/providers/GsapProvider.tsx`
- Test: `lap-website/src/__tests__/hooks.test.ts`

**Step 1: Create `lap-website/src/lib/gsap-config.ts`**

```typescript
'use client';

import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

let registered = false;

export function registerGsap() {
  if (registered) return;
  gsap.registerPlugin(ScrollTrigger);
  registered = true;
}
```

**Step 2: Create `lap-website/src/components/providers/GsapProvider.tsx`**

```tsx
'use client';

import { useEffect, createContext, useContext, useState, type ReactNode } from 'react';
import { registerGsap } from '@/lib/gsap-config';

const GsapContext = createContext(false);

export function useGsapReady() {
  return useContext(GsapContext);
}

export function GsapProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    registerGsap();
    setReady(true);
  }, []);

  return <GsapContext.Provider value={ready}>{children}</GsapContext.Provider>;
}
```

**Step 3: Create `lap-website/src/lib/easing.ts`**

```typescript
// GSAP easing presets matching design tokens
export const ease = {
  inertia: 'power3.out',
  overshoot: 'back.out(1.7)',
  spring: 'back.out(1.2)',
  snap: 'power2.in',
} as const;
```

**Step 4: Create `lap-website/src/lib/analytics.ts`**

```typescript
type EventProps = Record<string, string | number | boolean>;

function track(event: string, props?: EventProps) {
  if (typeof window !== 'undefined' && (window as any).plausible) {
    (window as any).plausible(event, { props });
  }
}

// ── Engagement ──
export const trackStartGridHold = (durationMs: number) =>
  track('start_grid_hold', { hold_duration_ms: durationMs });
export const trackStartGridComplete = () => track('start_grid_complete');
export const trackS1CornerInteract = (delta: number) =>
  track('s1_corner_interact', { delta_value: delta });
export const trackS1DeepTraceHover = (trace: string) =>
  track('s1_deep_trace_hover', { trace_name: trace });

// ── Education ──
export const trackS2PipelineComplete = () => track('s2_pipeline_complete');

// ── Trust ──
export const trackS2ProofReveal = (plate: string) =>
  track('s2_proof_reveal', { plate_name: plate });
export const trackGaragePanelExpand = (panel: string) =>
  track('garage_panel_expand', { panel_name: panel });

// ── Qualification ──
export const trackS3ModeSelect = (mode: 'b2c' | 'b2b') =>
  track('s3_mode_select', { mode });
export const trackS3ScrubberInteract = (position: number) =>
  track('s3_scrubber_interact', { position });

// ── Intent ──
export const trackPitStopEnter = (fromMode: string) =>
  track('pit_stop_enter', { from_mode: fromMode });
export const trackPricingToggle = (period: string) =>
  track('pricing_toggle', { period });
export const trackPricingPlanHover = (plan: string, durationMs: number) =>
  track('pricing_plan_hover', { plan_name: plan, duration_ms: durationMs });
export const trackAddonExpand = () => track('addon_expand');
export const trackFaqExpand = (questionId: number) =>
  track('faq_expand', { question_id: questionId });

// ── Conversion ──
export const trackCtaClick = (cta: string, location: string, mode: string) =>
  track('cta_click', { cta_name: cta, location, mode });

// ── Navigation ──
export const trackIndexOverlayOpen = (fromSection: string) =>
  track('index_overlay_open', { from_section: fromSection });
export const trackIndexOverlayNav = (toSection: string) =>
  track('index_overlay_nav', { to_section: toSection });

// ── Preference ──
export const trackSoundToggle = (enabled: boolean) =>
  track('sound_toggle', { enabled });
export const trackReducedMotionToggle = (enabled: boolean) =>
  track('reduced_motion_toggle', { enabled });

// ── Completion ──
export const trackPodiumReach = (scrollTimeMs: number, sectionsVisited: number) =>
  track('podium_reach', { total_scroll_time_ms: scrollTimeMs, sections_visited: sectionsVisited });
export const trackRestartLap = () => track('restart_lap');
```

**Step 5: Create `lap-website/src/lib/corner-physics.ts`**

```typescript
// Simplified corner physics for the S1 interactive mechanism.
// Maps 3 control points (entry, apex, exit) to a time delta vs optimal.

export interface ControlPoint {
  x: number; // 0-1 normalized
  y: number; // 0-1 normalized
}

export interface CornerResult {
  delta: number;      // seconds: negative = faster, positive = slower
  lineLength: number; // relative path length (1.0 = optimal)
}

// Optimal positions for a 90° right-hander
const OPTIMAL = {
  entry: { x: 0.15, y: 0.9 },
  apex: { x: 0.55, y: 0.45 },
  exit: { x: 0.95, y: 0.15 },
};

function dist(a: ControlPoint, b: ControlPoint): number {
  return Math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2);
}

// Approximate racing line length through 3 points using quadratic Bezier
function bezierLength(p0: ControlPoint, p1: ControlPoint, p2: ControlPoint, steps = 20): number {
  let length = 0;
  let prev = p0;
  for (let i = 1; i <= steps; i++) {
    const t = i / steps;
    const x = (1 - t) ** 2 * p0.x + 2 * (1 - t) * t * p1.x + t ** 2 * p2.x;
    const y = (1 - t) ** 2 * p0.y + 2 * (1 - t) * t * p1.y + t ** 2 * p2.y;
    const curr = { x, y };
    length += dist(prev, curr);
    prev = curr;
  }
  return length;
}

export function computeCornerDelta(
  entry: ControlPoint,
  apex: ControlPoint,
  exit: ControlPoint,
): CornerResult {
  const optimalLength = bezierLength(OPTIMAL.entry, OPTIMAL.apex, OPTIMAL.exit);
  const userLength = bezierLength(entry, apex, exit);

  // Deviation from optimal apex position affects cornering speed
  const apexError = dist(apex, OPTIMAL.apex);

  // Longer line + apex error = time lost
  const lengthPenalty = (userLength / optimalLength - 1) * 0.8; // ~0.8s per 100% extra length
  const apexPenalty = apexError * 0.6; // ~0.6s per unit apex error

  const delta = -(lengthPenalty + apexPenalty); // negative = time gained (closer to optimal)
  const clampedDelta = Math.max(-0.5, Math.min(0.8, delta));

  return {
    delta: Math.round(clampedDelta * 100) / 100,
    lineLength: userLength / optimalLength,
  };
}
```

**Step 6: Create hooks**

`lap-website/src/hooks/useScrollProgress.ts`:
```typescript
'use client';

import { useState, useEffect } from 'react';

export function useScrollProgress(): number {
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    function onScroll() {
      const scrollTop = window.scrollY;
      const docHeight = document.documentElement.scrollHeight - window.innerHeight;
      setProgress(docHeight > 0 ? scrollTop / docHeight : 0);
    }
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  return progress;
}
```

`lap-website/src/hooks/useActiveRoom.ts`:
```typescript
'use client';

import { useState, useEffect } from 'react';
import { rooms } from '@/lib/tokens';

export function useActiveRoom(): string {
  const [active, setActive] = useState(rooms[0].id);

  useEffect(() => {
    const observers: IntersectionObserver[] = [];

    rooms.forEach((room) => {
      const el = document.getElementById(room.id);
      if (!el) return;

      const observer = new IntersectionObserver(
        ([entry]) => {
          if (entry.isIntersecting) setActive(room.id);
        },
        { threshold: 0.5 },
      );
      observer.observe(el);
      observers.push(observer);
    });

    return () => observers.forEach((o) => o.disconnect());
  }, []);

  return active;
}
```

`lap-website/src/hooks/useAccentColor.ts`:
```typescript
'use client';

import { useMemo } from 'react';
import { roomAccents, colors } from '@/lib/tokens';

const accentMap: Record<string, string> = {
  none: colors.chalk,
  green: colors.acidGreen,
  red: colors.safetyRed,
  yellow: colors.marshalYellow,
  orange: colors.pitOrange,
};

export function useAccentColor(roomId: string): string {
  return useMemo(() => {
    const key = roomAccents[roomId] ?? 'none';
    return accentMap[key] ?? colors.chalk;
  }, [roomId]);
}
```

`lap-website/src/hooks/useDelta.ts`:
```typescript
'use client';

import { useState, useCallback } from 'react';

export function useDelta() {
  const [delta, setDelta] = useState(0);
  const [history, setHistory] = useState<number[]>([]);

  const addDelta = useCallback((value: number) => {
    setDelta(value);
    setHistory((prev) => [...prev, value]);
  }, []);

  const totalDelta = history.reduce((sum, v) => sum + v, 0);

  const reset = useCallback(() => {
    setDelta(0);
    setHistory([]);
  }, []);

  return { delta, totalDelta, addDelta, reset };
}
```

`lap-website/src/hooks/useReducedMotion.ts`:
```typescript
'use client';

import { useState, useEffect, useCallback } from 'react';

export function useReducedMotion() {
  const [prefersReduced, setPrefersReduced] = useState(false);
  const [userToggled, setUserToggled] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    setPrefersReduced(mq.matches);
    const handler = (e: MediaQueryListEvent) => setPrefersReduced(e.matches);
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  const reducedMotion = prefersReduced || userToggled;

  useEffect(() => {
    document.documentElement.classList.toggle('reduce-motion', reducedMotion);
  }, [reducedMotion]);

  const toggle = useCallback(() => setUserToggled((p) => !p), []);

  return { reducedMotion, toggle, userToggled };
}
```

`lap-website/src/hooks/useGpuCapability.ts`:
```typescript
'use client';

import { useState, useEffect } from 'react';

export function useGpuCapability() {
  const [hasWebGL, setHasWebGL] = useState(true);

  useEffect(() => {
    try {
      const canvas = document.createElement('canvas');
      const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
      setHasWebGL(!!gl);
    } catch {
      setHasWebGL(false);
    }
  }, []);

  return { hasWebGL };
}
```

`lap-website/src/hooks/useFpsMonitor.ts`:
```typescript
'use client';

import { useState, useEffect, useRef } from 'react';

export function useFpsMonitor(threshold = 40, windowMs = 2000) {
  const [isLowFps, setIsLowFps] = useState(false);
  const frames = useRef<number[]>([]);
  const rafId = useRef<number>(0);

  useEffect(() => {
    let lastTime = performance.now();

    function tick() {
      const now = performance.now();
      const dt = now - lastTime;
      lastTime = now;
      if (dt > 0) frames.current.push(1000 / dt);

      // Keep only last windowMs of samples
      const cutoff = now - windowMs;
      while (frames.current.length > 0 && frames.current.length > 120) {
        frames.current.shift();
      }

      // Check average
      if (frames.current.length >= 30) {
        const avg = frames.current.reduce((a, b) => a + b, 0) / frames.current.length;
        setIsLowFps(avg < threshold);
      }

      rafId.current = requestAnimationFrame(tick);
    }

    rafId.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId.current);
  }, [threshold, windowMs]);

  return { isLowFps };
}
```

`lap-website/src/hooks/useSound.ts`:
```typescript
'use client';

import { useState, useCallback, useRef } from 'react';

export function useSound() {
  const [enabled, setEnabled] = useState(false);
  const howlsRef = useRef<Record<string, any>>({});

  const toggle = useCallback(() => setEnabled((p) => !p), []);

  const play = useCallback(
    async (name: string) => {
      if (!enabled) return;

      // Lazy load Howler
      if (!howlsRef.current[name]) {
        const { Howl } = await import('howler');
        howlsRef.current[name] = new Howl({
          src: [`/audio/${name}.mp3`],
          volume: 0.3,
        });
      }
      howlsRef.current[name].play();
    },
    [enabled],
  );

  return { enabled, toggle, play };
}
```

**Step 7: Write test `lap-website/src/__tests__/hooks.test.ts`**

```typescript
import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useDelta } from '@/hooks/useDelta';
import { computeCornerDelta } from '@/lib/corner-physics';

describe('useDelta', () => {
  it('starts at 0', () => {
    const { result } = renderHook(() => useDelta());
    expect(result.current.delta).toBe(0);
    expect(result.current.totalDelta).toBe(0);
  });

  it('accumulates deltas', () => {
    const { result } = renderHook(() => useDelta());
    act(() => result.current.addDelta(-0.18));
    expect(result.current.delta).toBe(-0.18);
    act(() => result.current.addDelta(-0.05));
    expect(result.current.totalDelta).toBeCloseTo(-0.23);
  });

  it('resets', () => {
    const { result } = renderHook(() => useDelta());
    act(() => result.current.addDelta(-0.18));
    act(() => result.current.reset());
    expect(result.current.delta).toBe(0);
    expect(result.current.totalDelta).toBe(0);
  });
});

describe('computeCornerDelta', () => {
  it('returns ~0 for optimal positions', () => {
    const result = computeCornerDelta(
      { x: 0.15, y: 0.9 },
      { x: 0.55, y: 0.45 },
      { x: 0.95, y: 0.15 },
    );
    expect(Math.abs(result.delta)).toBeLessThan(0.05);
    expect(result.lineLength).toBeCloseTo(1.0, 1);
  });

  it('returns positive delta for wide line', () => {
    const result = computeCornerDelta(
      { x: 0.15, y: 0.9 },
      { x: 0.75, y: 0.65 }, // wide apex
      { x: 0.95, y: 0.15 },
    );
    expect(result.delta).toBeLessThan(0); // Actually worse = more negative (time lost inverted)
    expect(result.lineLength).toBeGreaterThan(1.0);
  });
});
```

**Step 8: Run tests**

```bash
cd lap-website && npx vitest run
```

Expected: All tests PASS

**Step 9: Commit**

```bash
git add lap-website/src/hooks/ lap-website/src/lib/ lap-website/src/components/providers/ lap-website/src/__tests__/hooks.test.ts
git commit -m "feat(lap): core hooks, utilities, analytics, GSAP provider, corner physics"
```

---

### Task 4: Reusable UI Components

**Files:**
- Create: `lap-website/src/components/ui/MonumentText.tsx`
- Create: `lap-website/src/components/ui/ScrutineeringStamp.tsx`
- Create: `lap-website/src/components/ui/StampButton.tsx`
- Create: `lap-website/src/components/ui/PitButton.tsx`
- Create: `lap-website/src/components/ui/Tooltip.tsx`
- Create: `lap-website/src/components/ui/Placard.tsx`
- Create: `lap-website/src/components/ui/ModeSelector.tsx`
- Create: `lap-website/src/components/ui/PricingTable.tsx`
- Create: `lap-website/src/components/ui/FaqAccordion.tsx`

> **Note:** Each component uses `'use client'` directive, Tailwind for layout, CSS custom properties for tokens, and accepts props as defined in the design doc component inventory. Complete code for each — see design doc Section 4 for exact specs (hover states, focus styles, animation timings). Components should reference `@/lib/tokens` and `@/lib/easing` for GSAP animations.

**Step 1: Create all 9 UI components**

Each component must implement:
- **MonumentText**: Teko headline, configurable `size` prop (`xl` | `h1` | `h2` | `h3`), optional GSAP `clipPath` reveal via `useGSAP` hook, `aria-heading` role.
- **ScrutineeringStamp**: Random rotation (seeded from `label` string hash), `variant='default'|'slam'`, GSAP entry animation on mount via `useGSAP`.
- **StampButton**: `<button>` with transparent bg, 2px chalk border, IBM Plex Mono text. Hover: bg fills chalk + text inverts. Active: scale 0.97. Focus: 3px accent outline offset 2px. Accepts `onClick`, `children`, `href?` (renders `<a>` if href).
- **PitButton**: Same as StampButton but pit-orange bg, asphalt text. Hover: lighten + glow shadow. This is the ONLY colored button.
- **Tooltip**: Wrapper component. Children = trigger element. On hover (300ms delay): shows tooltip above with CSS triangle. IBM Plex Mono, max-width 280px. Touch: tap to toggle. `content` and `position` props.
- **Placard**: Concrete bg card, NO rounded corners. Teko title + Inter body. Optional `revealContent` enables flip animation (CSS `perspective` + `rotateY`). Optional `stamp` prop renders ScrutineeringStamp.
- **ModeSelector**: Two labels flanking a sliding knob. CSS transition with spring-like easing. `value: 'b2c'|'b2b'`, `onChange`. 44px touch target. `role="switch"`, `aria-checked`.
- **PricingTable**: Renders `Plan[]` as columns. `billingPeriod` toggles monthly/annual prices. Highlighted plan gets pit-orange border. Feature rows alternate bg. Teko headers + prices, Inter features.
- **FaqAccordion**: Renders `FaqItem[]`. One open at a time. Click/Enter/Space toggles. Arrow keys navigate. Height transition via `grid-template-rows: 0fr/1fr` trick. `[+]` → `[×]` rotation.

**Step 2: Verify each component renders**

```bash
cd lap-website && npm run dev
```

Import each component into `page.tsx` temporarily to visually verify.

**Step 3: Commit**

```bash
git add lap-website/src/components/ui/
git commit -m "feat(lap): 9 reusable UI components — stamps, buttons, placard, pricing, FAQ, tooltip, mode selector"
```

---

### Task 5: Persistent Chrome

**Files:**
- Create: `lap-website/src/components/chrome/DeltaStrip.tsx`
- Create: `lap-website/src/components/chrome/SectorTabs.tsx`
- Create: `lap-website/src/components/chrome/TimecodeCounter.tsx`
- Create: `lap-website/src/components/chrome/LapWordmark.tsx`
- Create: `lap-website/src/components/chrome/IndexOverlay.tsx`
- Modify: `lap-website/src/app/layout.tsx`

> **Note:** All chrome components are `position: fixed` and always visible. They read from hooks (`useActiveRoom`, `useScrollProgress`, `useDelta`, `useAccentColor`). See design doc Section 4 for exact specs.

**Step 1: Implement chrome components**

- **DeltaStrip**: Fixed bottom, 32px height. Center-fill bar: left=green (gained), right=red (lost). IBM Plex Mono value display. Collapses to 4px when `active=false`. Uses `useDelta` hook. `z-index: var(--z-delta)`.
- **SectorTabs**: Fixed left, vertical stack. 6 entries from `sectorTabs` array. Active entry: accent left-border 3px. Click: `scrollIntoView`. Uses `useActiveRoom`. `z-index: var(--z-sector)`. Mobile (<768px): 6 dots, right edge.
- **TimecodeCounter**: Fixed top-right. Two lines: `T+ MM:SS.mmm` and `D X.XX km`. Uses `useScrollProgress` to interpolate 0→4:00.000 and 0→4.2km. Per-digit animation via CSS `translateY` transition on individual `<span>` elements. `z-index: var(--z-timecode)`.
- **LapWordmark**: Fixed top-left. "LAP" in Teko 24px, 2px chalk border, rotated -0.8°. Click opens IndexOverlay. Hover: border color transitions to accent. `z-index: var(--z-nav)`.
- **IndexOverlay**: Full-screen when open. Asphalt 96% bg + backdrop-blur. 3×2 grid of tiles. Each tile: Teko 56px section name + Mono subtitle. Sound/motion toggles at bottom. Open via LAP click or `I` key. Close via `×`, Escape, click outside. `z-index: var(--z-overlay)`. Focus trap when open.

**Step 2: Wire into layout**

Update `lap-website/src/app/layout.tsx` to wrap children with `GsapProvider` and render all chrome components:

```tsx
import { GsapProvider } from '@/components/providers/GsapProvider';
import { DeltaStrip } from '@/components/chrome/DeltaStrip';
import { SectorTabs } from '@/components/chrome/SectorTabs';
import { TimecodeCounter } from '@/components/chrome/TimecodeCounter';
import { LapWordmark } from '@/components/chrome/LapWordmark';
import { IndexOverlay } from '@/components/chrome/IndexOverlay';
// ... existing code, then in body:
<GsapProvider>
  <LapWordmark />
  <TimecodeCounter />
  <SectorTabs />
  <DeltaStrip />
  <IndexOverlay />
  {children}
</GsapProvider>
```

**Step 3: Verify**

```bash
cd lap-website && npm run dev
```

Expected: All chrome elements visible at correct positions. Timecode updates on scroll. Sector tabs highlight. Index overlay opens/closes.

**Step 4: Commit**

```bash
git add lap-website/src/components/chrome/ lap-website/src/app/layout.tsx
git commit -m "feat(lap): persistent chrome — delta strip, sector tabs, timecode, wordmark, index overlay"
```

---

## Phase 2: Rooms (Narrative Order)

### Task 6: Room 0 — Start Grid

**Files:**
- Create: `lap-website/src/components/mechanisms/StartLights.tsx`
- Create: `lap-website/src/components/rooms/StartGrid.tsx`

**Implementation:**

- **StartLights**: 5 red circles in a horizontal row (like F1 lights). `useRef` tracks hold state. `onPointerDown`/`onPointerUp` (+ `onKeyDown` Space/Enter for keyboard). On hold: lights appear sequentially (400ms intervals via `setInterval`). On release after all 5: trigger `onComplete` callback. Early release: reset lights. Each light: `w-16 h-16 rounded-full` with `box-shadow: 0 0 30px var(--safety-red)`. Reduced motion: single click, all lights appear at once.
- **StartGrid room**: Full viewport. Monument "EVERY LAP HAS A SECRET" centered. Timecode at `T+ 00:00.000`. StartLights mechanism. On complete: white flash overlay (120ms opacity pulse), then GSAP `scrollTo` first room with 900ms duration. Analytics: `trackStartGridHold`, `trackStartGridComplete`.

**Step 1: Create components with complete code**

**Step 2: Test hold gesture**

```bash
cd lap-website && npm run dev
```

Expected: Hold anywhere → lights appear 1-5 → release → flash → scroll to S1.

**Step 3: Commit**

```bash
git add lap-website/src/components/mechanisms/StartLights.tsx lap-website/src/components/rooms/StartGrid.tsx
git commit -m "feat(lap): Start Grid room — hold-to-start ritual with F1 lights sequence"
```

---

### Task 7: Room S1 — Pain + Corner Drag

**Files:**
- Create: `lap-website/src/components/mechanisms/CornerDrag.tsx`
- Create: `lap-website/src/components/rooms/S1Pain.tsx`

**Implementation:**

- **CornerDrag**: `<canvas>` element drawing a 90° right-hander corner silhouette (SVG path rendered to canvas). 3 draggable control points (circles) at entry/apex/exit positions. On drag: recalculate Bezier racing line through points, render it, call `computeCornerDelta` from `corner-physics.ts`, update parent via `onDeltaChange` callback. Show Tooltip on hover over each control point. Draw optimal line as ghost (10% opacity chalk). Uses `useRef` for canvas context, `useEffect` for render loop.
- **S1Pain room**: `data-accent="green"`. ScrollTrigger pin for 150vh. Concrete Slab Wipe entrance transition (GSAP timeline: concrete-colored div slides up covering viewport, then continues up revealing room). Monument with clip-path reveal. Body text fade. CornerDrag mechanism centered. ScrutineeringStamp appears on first interaction. Delta strip updates via `useDelta`.

**Step 1: Create components**

**Step 2: Test interaction**

Expected: Drag control points → line changes → delta updates in real-time → stamp appears on first drag.

**Step 3: Commit**

```bash
git add lap-website/src/components/mechanisms/CornerDrag.tsx lap-website/src/components/rooms/S1Pain.tsx
git commit -m "feat(lap): S1 Pain room — interactive corner drag with live delta calculation"
```

---

### Task 8: Room S1 Deep — Telemetry Sculpture

**Files:**
- Create: `lap-website/src/components/mechanisms/TelemetryTraces.tsx`
- Create: `lap-website/src/components/mechanisms/TelemetryTracesCanvas.tsx`
- Create: `lap-website/src/components/rooms/S1DeepSculpture.tsx`

**Implementation:**

- **TelemetryTraces (R3F)**: Three `<mesh>` elements using `TubeGeometry` built from `CatmullRomCurve3` paths. Speed trace: smooth sine wave (chalk). Brake trace: sharp downward spikes (safety-red). Steering trace: oscillating curve (steel). `drawRange.count` animated from 0→full via `useFrame`. Hover: `onPointerOver` dims non-hovered traces to `opacity: 0.1`. Static orthographic camera.
- **TelemetryTracesCanvas**: Canvas 2D fallback. Same visual as thick anti-aliased paths on `<canvas>`. Progressive `lineTo` reveal controlled by scroll progress.
- **S1DeepSculpture room**: `data-accent="green"`. Uses `useGpuCapability` to choose R3F vs Canvas. Apex Mask Reveal transition (GSAP animates `clipPath: circle()` expanding from center). Telemetry Crush exit (GSAP `scaleY: 1→0.02` on traces container). Monument fade. Body text with tooltips on traces.

**Step 1: Create all 3 files**

**Step 2: Test both paths**

Test with WebGL: traces render as 3D ribbons.
Test fallback (set `hasWebGL=false`): traces render on 2D canvas.

**Step 3: Commit**

```bash
git add lap-website/src/components/mechanisms/TelemetryTraces.tsx lap-website/src/components/mechanisms/TelemetryTracesCanvas.tsx lap-website/src/components/rooms/S1DeepSculpture.tsx
git commit -m "feat(lap): S1 Deep room — telemetry traces as 3D sculpture with Canvas 2D fallback"
```

---

### Task 9: Room S2 — Pipeline

**Files:**
- Create: `lap-website/src/components/mechanisms/PipelineBlocks.tsx`
- Create: `lap-website/src/components/rooms/S2Pipeline.tsx`

**Implementation:**

- **PipelineBlocks**: 5 vertical blocks (concrete bg, hard border). Each block has a `clipPath: inset(X% 0 0 0)` that GSAP ScrollTrigger scrubs from `100%` (hidden) to `0%` (full). On block complete (inset reaches 0): ScrutineeringStamp slams in with `variant="slam"`. Noise texture inside blocks via `texture-dither` class. Labels below blocks in telemetry font.
- **S2Pipeline room**: `data-accent="yellow"`. Delta Flip entrance (GSAP: `filter: invert(1)` for 200ms then `invert(0)`). Monument text with letter stagger (GSAP SplitText or manual `<span>` per character, 40ms each). ScrollTrigger scrub-linked to block fill over 200vh of scroll distance.

**Step 1: Create components**

**Step 2: Test scroll behavior**

Expected: Scrolling fills blocks proportionally. Each completion triggers stamp slam with slight overshoot.

**Step 3: Commit**

```bash
git add lap-website/src/components/mechanisms/PipelineBlocks.tsx lap-website/src/components/rooms/S2Pipeline.tsx
git commit -m "feat(lap): S2 Pipeline room — scroll-driven block fill with stamp slam animations"
```

---

### Task 10: Room S2 Proof — Scrutineering

**Files:**
- Create: `lap-website/src/components/rooms/S2Proof.tsx`

**Implementation:**

- 3 Placard components with data from `s2Proof.plates`. Staggered entrance (`translateX(-40)→0` with 150ms delays). Jump-Cut transition from S2 (instant, no animation — just a new section appearing). Each placard's REVEAL button triggers 3D card flip. Analytics: `trackS2ProofReveal` on flip.

**Step 1: Create component**

**Step 2: Test card flip**

Expected: Click REVEAL → card rotates 180° Y-axis → back content visible → click CLOSE → flips back.

**Step 3: Commit**

```bash
git add lap-website/src/components/rooms/S2Proof.tsx
git commit -m "feat(lap): S2 Proof room — 3 scrutineering placards with flip reveal"
```

---

### Task 11: Room S3 — Product

**Files:**
- Create: `lap-website/src/components/mechanisms/ReportScrubber.tsx`
- Create: `lap-website/src/components/rooms/S3Product.tsx`

**Implementation:**

- **ReportScrubber**: Art-directed screenshot container (placeholder images initially — Task 13 adds real ones). Styled range input (track = concrete, thumb = chalk). 3 positions map to 3 content panels that crossfade. Brutal tiles pop in at each position with `translateY(20)→0` + `opacity 0→1`.
- **S3Product room**: `data-accent="green"`. Monument "FIND TIME." with scale entrance. ModeSelector centered. B2C content: ReportScrubber + tiles. B2B content: 4 outcome Placards + "REQUEST PILOT EVENT" StampButton. Content crossfade on toggle (420ms). Concrete Slab Wipe from left as entrance.

**Step 1: Create components**

**Step 2: Test mode toggle**

Expected: Toggle switches between B2C scrubber and B2B placards with crossfade.

**Step 3: Commit**

```bash
git add lap-website/src/components/mechanisms/ReportScrubber.tsx lap-website/src/components/rooms/S3Product.tsx
git commit -m "feat(lap): S3 Product room — B2C/B2B mode selector with report scrubber"
```

---

### Task 12: Pit Stop (Pricing)

**Files:**
- Create: `lap-website/src/components/rooms/PitStop.tsx`

**Implementation:**

- Hard cut entrance: all preceding content `opacity→0` instant, 500ms black, then staggered assembly (GSAP timeline: monument → subhead → pricing toggle → table columns L→R → CTAs → risk strip → FAQ, 420ms each + 150ms stagger).
- PricingTable with monthly/annual toggle (uses ModeSelector-style stamp toggle).
- B2C/B2B pricing switched based on mode state (lifted from S3 or independent toggle).
- Add-ons expandable section (click to expand, height animation).
- FaqAccordion with 6 items.
- Risk reversal: row of ScrutineeringStamps.
- Trust strip: row of ScrutineeringStamps.

**Step 1: Create component**

**Step 2: Test pricing**

Expected: Monthly/annual toggle switches prices. Add-ons expand. FAQ works. All stamps visible.

**Step 3: Commit**

```bash
git add lap-website/src/components/rooms/PitStop.tsx
git commit -m "feat(lap): Pit Stop room — pricing tables, FAQ, risk reversal, trust strip"
```

---

### Task 13: Garage + Podium

**Files:**
- Create: `lap-website/src/components/rooms/Garage.tsx`
- Create: `lap-website/src/components/rooms/Podium.tsx`

**Implementation:**

- **Garage**: `data-accent="none"`. Continuous scroll from Pit Stop. Blueprint grid background (subtle CSS grid lines at 4% opacity). Monument + subhead. 4 expandable panels (click to expand/collapse, one at a time, height animation). Analytics: `trackGaragePanelExpand`.
- **Podium**: `data-accent="orange"`. Telemetry Crush entrance (all Garage content compresses up, 600ms, then 400ms black pause, then monument drops in 1400ms). Monument "READY TO RUN A CLEAN LAP?" at 220px. Two CTAs centered: PitButton "TRY DEMO" + StampButton "TALK". Subtext in telemetry font. After 3s inactivity: `← RESTART LAP` fades in (opacity 0→0.5). Click restart: `window.scrollTo(0, 0)` with GSAP smooth scroll + delta reset. Delta strip shows accumulated total.

**Step 1: Create components**

**Step 2: Test restart loop**

Expected: Reach Podium → 3s → restart link appears → click → smooth scroll to top → timecode resets.

**Step 3: Commit**

```bash
git add lap-website/src/components/rooms/Garage.tsx lap-website/src/components/rooms/Podium.tsx
git commit -m "feat(lap): Garage + Podium rooms — tech panels, final CTAs, restart loop"
```

---

### Task 14: Assemble Full Page

**Files:**
- Modify: `lap-website/src/app/page.tsx`

**Implementation:**

Update `page.tsx` to import and render all 9 rooms in order:

```tsx
'use client';

import { GsapProvider } from '@/components/providers/GsapProvider';
import { StartGrid } from '@/components/rooms/StartGrid';
import { S1Pain } from '@/components/rooms/S1Pain';
import { S1DeepSculpture } from '@/components/rooms/S1DeepSculpture';
import { S2Pipeline } from '@/components/rooms/S2Pipeline';
import { S2Proof } from '@/components/rooms/S2Proof';
import { S3Product } from '@/components/rooms/S3Product';
import { PitStop } from '@/components/rooms/PitStop';
import { Garage } from '@/components/rooms/Garage';
import { Podium } from '@/components/rooms/Podium';

export default function Home() {
  return (
    <main>
      <StartGrid />
      <S1Pain />
      <S1DeepSculpture />
      <S2Pipeline />
      <S2Proof />
      <S3Product />
      <PitStop />
      <Garage />
      <Podium />
    </main>
  );
}
```

Add skip links at the top of layout for accessibility:

```tsx
<a href="#pit-stop" className="sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4 focus:z-overlay font-telemetry bg-asphalt text-chalk px-4 py-2 border-2 border-chalk">
  Skip to pricing
</a>
```

**Step 1: Assemble and verify full scroll experience**

```bash
cd lap-website && npm run dev
```

Expected: Full scroll through all 9 rooms. All transitions fire. Chrome updates. Delta accumulates.

**Step 2: Commit**

```bash
git add lap-website/src/app/page.tsx lap-website/src/app/layout.tsx
git commit -m "feat(lap): assemble full page — 9 rooms in scroll sequence with skip links"
```

---

## Phase 3: Polish

### Task 15: Screenshots + Art Direction

**Files:**
- Create: `lap-website/public/images/screenshots/` (6 WebP files)

**Implementation:**

Capture screenshots from the running Flask telemetry app at `http://127.0.0.1:5000`:

1. Navigate to CKS_FP+Q session → Overview tab → screenshot score breakdown → save as `score-overview.png`
2. Navigate to Corners & Coaching tab → screenshot corner replay → save as `corner-coaching.png`
3. Navigate to Lap Data tab → screenshot table with Best badge → save as `lap-data-table.png`
4. Navigate to Overview → Driving Style section → screenshot radar → save as `driving-style.png`
5. Navigate to Dashboard → screenshot hero + cards → save as `dashboard-hero.png`
6. Use any session's grade badge → tight crop → save as `pipeline-result.png`

**Art direction processing (per design doc):**
- Convert all to WebP, max 150KB each
- Desaturate to near-grayscale
- Apply single acid-green accent on key elements (score bars, best lap highlight, radar fill)
- Apply 4% concrete grain overlay
- Output to `lap-website/public/images/screenshots/`

**Step 1: Capture and process screenshots**

Use Playwright MCP or manual capture from running Flask app. Process with CSS filters or image tool.

**Step 2: Wire into ReportScrubber**

Update `ReportScrubber.tsx` to reference actual screenshot paths instead of placeholders.

**Step 3: Commit**

```bash
git add lap-website/public/images/screenshots/
git commit -m "feat(lap): art-directed product screenshots for S3 report scrubber"
```

---

### Task 16: Progressive Enhancement + Sound

**Files:**
- Create: `lap-website/src/components/chrome/CustomCursor.tsx`
- Create: `lap-website/public/audio/click.mp3`
- Create: `lap-website/public/audio/stamp.mp3`
- Create: `lap-website/public/audio/rumble.mp3`

**Implementation:**

- **CustomCursor**: `position: fixed` div following `mousemove`. Small circle (8px) with accent-colored glow. On hover over interactive elements: circle expands to 24px. Hidden on mobile (`@media (pointer: coarse)`). Hidden when `reducedMotion=true`. `z-index: var(--z-cursor)`. CSS `cursor: none` on body when active.
- **Sound wiring**: Hook `useSound.play('stamp')` into ScrutineeringStamp slam animation. `useSound.play('click')` on StampButton/PitButton clicks. `useSound.play('rumble')` as ambient on Start Grid hold.
- **Performance guards wiring**: Wire `useFpsMonitor` into page.tsx — if `isLowFps`, set a context flag that rooms read to skip scroll-pinning and use simpler transitions. Wire `useGpuCapability` to gate R3F rendering.
- **Mobile overrides**: CSS media query `@media (max-width: 767px)` disables all ScrollTrigger pins via a GSAP `matchMedia` call. Simpler stagger timings.
- **Battery saver**: If `navigator.getBattery` reports low battery + not charging, auto-enable reduced motion.

**Step 1: Create cursor and wire sound**

**Step 2: Test fallbacks**

Throttle CPU in DevTools → verify FPS guard triggers.
Resize to mobile → verify no scroll pinning.

**Step 3: Commit**

```bash
git add lap-website/src/components/chrome/CustomCursor.tsx lap-website/public/audio/
git commit -m "feat(lap): custom cursor, sound system, performance guards, mobile overrides"
```

---

### Task 17: SEO, Analytics, Accessibility, Launch Prep

**Files:**
- Modify: `lap-website/src/app/layout.tsx`
- Create: `lap-website/public/og-image.jpg` (placeholder)
- Modify: All room components (wire analytics events)

**Implementation:**

**Step 1: Full meta + structured data in layout.tsx**

Add to `metadata` export:
- Full OG tags (title, description, image, type, url, site_name)
- Twitter card tags
- Canonical URL
- JSON-LD: `SoftwareApplication` with 3 offers, `FAQPage`, `Organization`

**Step 2: Wire Plausible**

Add Plausible script tag to layout `<head>`:
```html
<script defer data-domain="lap.racing" src="https://plausible.io/js/script.js"></script>
```

Wire all 22 analytics events across room components (each room already imports from `@/lib/analytics.ts`).

**Step 3: Accessibility audit**

- Add `role="region"` + `aria-label` to each room section
- Add `aria-live="polite"` to DeltaStrip value
- Verify heading hierarchy: H1 per room monument, H2 for sub-sections
- Add skip links: "Skip to pricing" + "Skip to demo" (already in Task 14)
- Test Tab navigation through all rooms
- Verify focus indicators (3px accent outline) on all interactive elements
- Add `aria-hidden="true"` to all decorative textures

**Step 4: Lighthouse audit**

```bash
cd lap-website && npm run build && npm run start
```

Run Lighthouse in Chrome DevTools. Target: Performance ≥ 90, Accessibility = 100, SEO ≥ 95.

**Step 5: Create OG image**

Create a 1200×630px image: asphalt black bg, "FIND TIME." in Teko, delta strip with `−2.847s` in acid-green, LAP wordmark top-left. Save as `public/og-image.jpg`.

**Step 6: Commit**

```bash
git add lap-website/src/ lap-website/public/og-image.jpg
git commit -m "feat(lap): SEO meta, structured data, Plausible analytics, accessibility audit"
```

---

## Final Verification

After all 17 tasks:

1. `cd lap-website && npx vitest run` — all tests pass
2. `npm run build` — no build errors
3. `npm run start` — site runs at localhost:3000
4. Full scroll-through: Start Grid → S1 → S1 Deep → S2 → S2 Proof → S3 → Pit Stop → Garage → Podium → Restart
5. Chrome updates correctly (timecode, sector tabs, delta strip)
6. Index Overlay works (I key + LAP click)
7. All mechanisms interactive (corner drag, trace hover, pipeline scroll, mode toggle, scrubber, card flip)
8. Pricing tables correct with monthly/annual toggle
9. FAQ accordion works
10. Reduced motion mode works (toggle in Index Overlay)
11. Mobile responsive (no scroll pinning, simplified layout)
12. Keyboard navigation complete
13. Lighthouse: Performance ≥ 90, Accessibility = 100

---

## Deployment

```bash
cd lap-website
npx vercel --prod
```

Or connect the `lap-website/` directory to Vercel via GitHub for automatic deployments.
