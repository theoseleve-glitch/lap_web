# Production Integration Design — Unified Next.js App + Flask API

> **Status**: Approved | **Date**: 2026-02-26

## Goal

Rebuild the Flask Jinja2/vanilla-JS frontend as a Next.js 14 App Router application, unified with the existing `lap-website` marketing site, using the `lap-website` design system as the visual foundation. Flask becomes a headless API backend.

## Architecture

```
lap.racing (single Next.js deployment)
+-----------------------------------------------------+
|  Next.js 14 (App Router)                            |
|                                                     |
|  Public routes (marketing - already built):         |
|    /  /pricing  /demo  /contact  /waitlist          |
|    /drivers  /circuits  /teams  /endurance           |
|                                                     |
|  Auth routes (new):                                 |
|    /login  /register  /verify-email                 |
|                                                     |
|  App routes (rebuild from 44 Flask templates):      |
|    /app/dashboard                                   |
|    /app/sessions  /app/sessions/[id]                |
|    /app/tracks  /app/tracks/[id]                    |
|    /app/drivers  /app/drivers/[id]                  |
|    /app/analyze                                     |
|    /app/visualize/[id]                              |
|    /app/compare                                     |
|    /app/race-strategy  /app/race-strategy/[id]/live |
|    /app/leaderboard                                 |
|    /app/analytics  /app/karts  /app/weekends        |
|    ... (44 pages total under /app/*)                |
+------------------------+----------------------------+
                         | HTTPS (fetch from client)
+------------------------v----------------------------+
|  Flask API Backend (headless - no HTML, no static)  |
|  Gunicorn + nginx at api.lap.racing                 |
|  /api/v1/* endpoints only (150+ routes)             |
|  PostgreSQL + Redis + Celery                        |
|  Auth (JWT), CORS (allow lap.racing), rate limiting |
+-----------------------+-----------------------------+
```

## Approach

**Approach 3: Full frontend rebuild in Next.js.**

- Marketing pages stay as-is in `lap-website/src/app/`
- All 44 Flask templates rebuilt as React pages under `/app/*`
- All 71 JS files ported (35 Canvas draw functions reused via `useCanvas` hook)
- Flask becomes headless API only — Jinja2 templates and static assets no longer served
- Everything ships before launch — no incremental/partial migration

## Rebuild Scope

### Pages by Tier

**Tier 1 — Simple CRUD (16 pages)**: List + detail + form pattern
- Sessions list, Tracks list/detail, Drivers list/detail/editor
- Karts list/detail/form, Weekends list/detail/form
- Leaderboard, Annotations list/search, Data health list/detail

**Tier 2 — Chart-heavy (14 pages)**: Canvas 2D or Chart.js ports
- Dashboard (sparklines), Session detail (24+ embedded charts)
- Visualize workspace (3 canvases), Compare sessions/drivers
- Analytics (weather, trends, meteo), Weight simulator, Pace predictor
- Track evolution, Driver progression

**Tier 3 — Complex interactive (10 pages)**: State machines, real-time, multi-panel
- Analyze wizard (3-step upload + progress polling)
- Corner replay (state machine + animation loop + cockpit gauges)
- Focus mode (split pane + tool registry)
- Race strategy config/live/summary (real-time updates, neutralization, rival tracker)

**Tier 4 — Infrastructure (4 pages + shared)**: Auth, layout, errors
- Login/register/verify, Base layout + nav, 404/500

### Tech Stack

| Concern | Current (Flask) | Next.js replacement |
|---------|----------------|-------------------|
| Templates | 44 Jinja2 files | React Server + Client Components |
| Routing | Flask blueprints | Next.js App Router (`/app/*`) |
| Navigation | 400 lines inline JS | `<AppNav>` React component |
| Data fetching | `FetchHelper` (vanilla) | React Query (TanStack Query) |
| Forms | Inline JS validation | React Hook Form + Zod |
| Charts (5) | Chart.js via CDN | `react-chartjs-2` wrapper |
| Canvas viz (35) | Vanilla Canvas 2D | `useCanvas` hook wrapping existing draw logic |
| Maps | Leaflet 1.9.4 CDN | `react-leaflet` |
| Animations | Custom `motion.js` | Framer Motion + GSAP (already in lap-website) |
| State | `ModuleManager` | Zustand (global) + React state (local) |
| Layout panels | Custom `SplitPane` | React component port |
| Real-time | SSE polling | SSE + React Query polling |
| Styling | 10 CSS files (dark theme) | Tailwind CSS + lap-website design tokens |
| Auth | None on FE | JWT in httpOnly cookie + Next.js middleware |

### Canvas Reuse Strategy

The 35 Canvas 2D draw functions are reused, not rewritten:

```tsx
function useCanvas(drawFn, deps) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const ctx = ref.current?.getContext('2d');
    if (ctx) drawFn(ctx, ...deps);
  }, deps);
  return ref;
}
```

Draw logic extracted as pure functions from existing JS. Only lifecycle/data wrappers are new.

## Design System — Unified Visual Language

Source of truth: `lap-website/src/styles/tokens.css` + `lap-website/src/lib/tokens.ts`

### Colors (dark-only)

| Token | Hex | Product role |
|-------|-----|-------------|
| `--asphalt` | `#0B0C0F` | Page background |
| `--concrete` | `#161A20` | Cards, panels, table rows, chart backgrounds |
| `--chalk` | `#F3F0E8` | Primary text, axis labels, headings |
| `--steel` | `#8A8F98` | Secondary text, borders, grid lines |
| `--acid-green` | `#B6FF2E` | Positive scores, PB markers, success states |
| `--safety-red` | `#FF2A2A` | Errors, poor scores, brake zones |
| `--marshal-yellow` | `#FFD400` | Warnings, caution flags, medium scores |
| `--pit-orange` | `#FF6A00` | Primary CTAs, active states, brand accent |

### Typography

| Font | Class | Weight | Use |
|------|-------|--------|-----|
| Teko | `font-monument` | 600, 700 | Page titles, score numbers, big stats |
| Inter | `font-body` | 400, 500 | Body text, table cells, descriptions |
| IBM Plex Mono | `font-telemetry` | 400 | Lap times, channels, axis ticks, badges |

### Spacing

8px baseline grid: `--space-1` (8px) through `--space-16` (128px).
Fluid grid: 12 columns, `clamp(20px, 2vw, 32px)` gutter, `clamp(16px, 6vw, 8vw)` margin.

### Animation

GSAP + Framer Motion with 3 timing tiers:
- `micro` (420ms) — button hover, form focus, toggle
- `room` (900ms) — page transitions, panel expand
- `monument` (1400ms) — hero text reveals

Easing: `power3.out` (inertia), `back.out(1.7)` (overshoot), `power2.in` (snap).
Respects `prefers-reduced-motion`.

### Reused Marketing Components

- `PitButton` — primary CTA (Analyze, Save, Compare)
- `StampButton` — secondary actions, filters, tabs
- `Placard` — session/track/driver cards
- `ScrutineeringStamp` — grade badges, PB markers, condition labels
- Texture overlays (grain, scanlines) on dashboard/detail pages

### New Product Components

- `DataTable` — concrete bg, chalk text, steel borders, sortable columns
- `ChartPanel` — canvas wrapper with loading/empty/error states
- `StatCard` — big Teko number + IBM Plex Mono label
- `NavBar` — port marketing nav, add `/app/*` links
- `FormField` — steel border input, chalk text, pit-orange focus ring

### Canvas Chart Theme

```ts
export const chartTheme = {
  bg: '#161A20',       // concrete
  gridLine: '#8A8F98', // steel at 20% opacity
  axisLabel: '#F3F0E8',// chalk
  primary: '#B6FF2E',  // acid-green
  secondary: '#FF6A00',// pit-orange
  danger: '#FF2A2A',   // safety-red
  warning: '#FFD400',  // marshal-yellow
};
```

## Flask Backend Hardening (parallel track)

### Security (P0)
- `@require_auth` decorator replacing inline `getattr(g, "user_id", None)` checks
- CORS configured to allow `lap.racing` origin
- Secrets fail on defaults in production
- Tenant middleware on all `/api/` routes

### API Completeness
- ~30 legacy endpoints need v1 equivalents
- Next.js frontend calls `/api/v1/` exclusively

### Infrastructure
- Dockerfile + docker-compose.prod.yml
- GitHub Actions CI (pytest on push)
- `/healthz` endpoint
- Branch fix (main = master, delete master)

### Schema
- 16 missing PG tables (race strategy, karts, catalogs) via Alembic 011-015

## Build Sequence

```
Week 1-2: Foundation (parallel tracks)
  Track A: Flask hardening (branch fix, auth, CORS, CI, Dockerfile)
  Track B: Next.js scaffold (layout, auth pages, API client, design tokens)

Week 3-4: Core pages
  Track A: Flask v1 endpoint batch 2 (15 session endpoints)
  Track B: CRUD pages - sessions, tracks, drivers, karts, weekends (Tier 1)

Week 5-7: Visualization pages
  Track A: Flask v1 endpoint batch 3-4 (search, browse, annotations, dashboards)
  Track B: Canvas ports - session detail (24 charts), visualize workspace,
           dashboard sparklines, compare pages (Tier 2)

Week 8-10: Complex interactives
  Track A: Flask schema unification (16 missing PG tables)
  Track B: Analyze wizard, corner replay, focus mode,
           race strategy live (Tier 3)

Week 11: Integration testing
  All v1 endpoints working with Next.js frontend
  Auth flow end-to-end
  Every page loads, every chart renders, every form submits

Week 12: Deploy
  Flask API -> container at api.lap.racing
  Next.js -> Vercel at lap.racing
  DNS, TLS, monitoring
```

## Testing Strategy

| Layer | Tool | What |
|-------|------|------|
| Flask API | pytest (949+ tests) | All v1 endpoints, auth, GDPR, scoring, pipeline |
| React components | Vitest + RTL | Pages render, forms submit, charts mount |
| Canvas viz | Vitest + snapshots | Draw functions produce expected output |
| API integration | Vitest + MSW | Frontend-backend contract |
| E2E | Playwright | 10 critical flows |

## Acceptance Criteria

- Every Flask endpoint has a corresponding Next.js page that calls it
- Every Chart.js / Canvas visualization renders identically to Flask version
- Auth flow works end-to-end (register, login, JWT refresh, logout)
- CORS allows `lap.racing` -> `api.lap.racing`
- Lighthouse score > 80 on all pages
- 0 console errors in browser
- Marketing pages unchanged and still functional
- `lap-website` design system applied consistently across all product pages
