# Front-End Architecture Overhaul — Design Document

**Date**: 2026-02-26
**Scope**: Full engineering + visual refresh
**Strategy**: Fix P0s first, then incremental migration

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Migration strategy | Fix P0s first, then incremental | Stabilize memory leaks before redesign; keep app shipping |
| CSS approach | Enhanced CSS Variables | Zero build step, builds on existing foundation, lowest risk |
| JS modules | Lifecycle Protocol (ModuleManager) | Fixes P0 leaks without rewriting to ES modules |
| Mobile charts | Swipeable card stack + bottom drawer | Touch-native, avoids cramming data into tiny cells |
| Visual direction | NASA Eyes — mission control precision | Natural evolution of existing dark glassmorphism |
| Motion | Purposeful micro-motion | GPU-only, <400ms, prefers-reduced-motion safe |
| Flagship pages | Dashboard + Race Strategy Live | Highest traffic + highest complexity |

---

## Current State Audit Summary

### Critical Issues (P0)

| Issue | Impact | Scope |
|-------|--------|-------|
| 77% of JS modules leak event listeners | Memory growth on navigation | 27 of 35 files |
| `setInterval` without `clearInterval` | Infinite polling after page leave | `race_strategy_live.js` |
| Unbounded canvas/data caches | OOM on large sessions (50+ laps) | `lap_overlay.js`, `gg_explorer.js` |
| Light mode incomplete | 4 of 6 CSS files have zero light-mode support | corner_replay, focus_mode, gg_explorer, speed_trace_zoom |
| 40+ `!important` declarations | Specificity wars | `race_strategy.css` |

### High Issues (P1)

- 12+ fragmented breakpoints (no unified scale)
- No container queries (charts adapt to viewport only)
- No module lifecycle (init/destroy)
- Inconsistent DPR scaling (double-scaling bug in cross_session.js)
- z-index: 5000 in focus mode (undocumented)
- 264 inline styles across templates
- 500 lines of inline JS in base.html

### Inventory

- **CSS**: 13,300 lines across 6 files, no external framework
- **JS**: 22,800 lines across 56 IIFE files, no build step
- **Templates**: 43 Jinja2 templates extending base.html
- **CDNs**: Leaflet 1.9.4, Google Fonts (DM Sans, JetBrains Mono)

---

## Phase Structure

```
Phase 0  — P0 Stabilization ——————————————— [~2 days]
Phase 1  — Token System + CSS Split ———————— [~3 days]
Phase 2  — ModuleManager + JS Lifecycle ————— [~3 days]
Phase 3  — Responsive System + Chart Contract [~3 days]
Phase 4  — Visual Refresh: Dashboard ———————— [~4 days]
Phase 5  — Visual Refresh: Race Strategy Live  [~4 days]
Phase 6  — Component Library ————————————————— [~5 days]
Phase 7  — Remaining Pages Migration ———————— [~8 days]
Phase 8  — Accessibility Hardening ——————————— [~3 days]
Phase 9  — Performance Budgets + CI —————————— [~2 days]
Phase 10 — Documentation + Governance ————————— [~2 days]

Total: ~39 working days
```

---

## Phase 0: P0 Stabilization

Fix memory leaks, listener cleanup, clearInterval, unbounded caches, recursive rAF guards.

### Module Migration Priority

| Priority | Module | Lines | Key Leak | Fix |
|----------|--------|-------|----------|-----|
| 1 | `race_strategy_live.js` | 1,381 | `setInterval` never cleared | `addInterval` + destroy |
| 2 | `visualize.js` | 1,382 | Listeners on canvas, no cleanup | Full lifecycle |
| 3 | `corner_replay.js` | 645 | Recursive rAF, no cancel guard | `addRaf` + playing check |
| 4 | `chart_sync.js` | 671 | mousemove/touchstart never removed | `addListener` + destroy |
| 5 | `lap_overlay.js` | ~400 | Unbounded `lapDataCache` | LRU cap (20 entries) |
| 6 | `gg_explorer.js` | 1,047 | Unbounded cache + listeners | LRU + lifecycle |
| 7 | `focus_mode.js` | 582 | Tool references persist | destroy calls tool.destroy |
| 8 | `gps_trace.js` | 526 | Leaflet layers never removed | map.remove() in destroy |

---

## Phase 1: Token System + CSS Architecture

### Token System

Single source of truth in `tokens.css`. Every color, space, radius, shadow, duration, and z-index references these tokens.

```css
:root {
  /* Backgrounds */
  --bg-void: #06080c;
  --bg-primary: #0a0d14;
  --bg-secondary: #10141c;
  --bg-tertiary: #161b26;
  --bg-hover: #1c2230;
  --bg-active: #232a3a;

  /* Borders */
  --border: rgba(255, 255, 255, 0.06);
  --border-subtle: rgba(255, 255, 255, 0.03);
  --border-focus: rgba(240, 112, 48, 0.4);
  --surface-glass: rgba(16, 20, 28, 0.7);

  /* Text */
  --text-primary: #e8ecf4;
  --text-secondary: #8b93a6;
  --text-muted: #515a6e;
  --text-inverse: #0a0d14;

  /* Accent */
  --accent: #f07030;
  --accent-hover: #f58040;
  --accent-dim: rgba(240, 112, 48, 0.15);
  --accent-glow: 0 0 20px rgba(240, 112, 48, 0.25);

  /* Semantic */
  --success: #34d399;  --success-dim: rgba(52, 211, 153, 0.12);
  --warning: #fbbf24;  --warning-dim: rgba(251, 191, 36, 0.12);
  --danger: #f87171;   --danger-dim: rgba(248, 113, 113, 0.12);
  --info: #60a5fa;     --info-dim: rgba(96, 165, 250, 0.12);

  /* Data Viz (categorical, contrast-safe) */
  --data-1: #f07030;  --data-2: #38bdf8;  --data-3: #34d399;
  --data-4: #a78bfa;  --data-5: #fbbf24;  --data-6: #f472b6;
  --data-7: #22d3ee;  --data-8: #e879f9;

  /* Spacing (fluid, 8 steps) */
  --space-0: 0;
  --space-1: clamp(0.25rem, 0.4vw, 0.375rem);
  --space-2: clamp(0.5rem, 0.8vw, 0.625rem);
  --space-3: clamp(0.75rem, 1.2vw, 1rem);
  --space-4: clamp(1rem, 1.6vw, 1.5rem);
  --space-5: clamp(1.5rem, 2.4vw, 2rem);
  --space-6: clamp(2rem, 3.2vw, 3rem);
  --space-7: clamp(3rem, 5vw, 4.5rem);
  --space-8: clamp(4rem, 7vw, 6rem);

  /* Typography (fluid) */
  --font-sans: 'DM Sans', system-ui, -apple-system, sans-serif;
  --font-mono: 'JetBrains Mono', 'Fira Code', monospace;
  --font-size-xs: clamp(0.7rem, 0.65rem + 0.2vw, 0.75rem);
  --font-size-sm: clamp(0.8rem, 0.75rem + 0.2vw, 0.875rem);
  --font-size-base: clamp(0.875rem, 0.82rem + 0.25vw, 1rem);
  --font-size-md: clamp(1rem, 0.9rem + 0.4vw, 1.25rem);
  --font-size-lg: clamp(1.25rem, 1rem + 0.8vw, 1.75rem);
  --font-size-xl: clamp(1.5rem, 1.1rem + 1.2vw, 2.25rem);
  --font-size-2xl: clamp(2rem, 1.4rem + 1.8vw, 3rem);
  --font-weight-normal: 400;
  --font-weight-medium: 500;
  --font-weight-semibold: 600;
  --font-weight-bold: 700;
  --line-height-tight: 1.2;
  --line-height-normal: 1.5;
  --line-height-relaxed: 1.7;

  /* Radii */
  --radius-xs: 4px;
  --radius-sm: 6px;
  --radius: 10px;
  --radius-lg: 14px;
  --radius-xl: 20px;
  --radius-pill: 9999px;

  /* Shadows */
  --shadow-sm: 0 1px 3px rgba(0, 0, 0, 0.3);
  --shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
  --shadow-lg: 0 8px 32px rgba(0, 0, 0, 0.5);
  --shadow-glow: 0 0 24px rgba(240, 112, 48, 0.15);
  --shadow-inset: inset 0 1px 2px rgba(0, 0, 0, 0.3);

  /* Glass */
  --glass-bg: rgba(16, 20, 28, 0.65);
  --glass-border: rgba(255, 255, 255, 0.06);
  --glass-blur: 16px;

  /* Motion */
  --duration-instant: 0ms;
  --duration-fast: 100ms;
  --duration-normal: 200ms;
  --duration-slow: 400ms;
  --duration-slower: 600ms;
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
  --ease-in-out: cubic-bezier(0.65, 0, 0.35, 1);
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
  --ease-linear: linear;

  /* Z-Index Layers (strict) */
  --z-base: 1;
  --z-elevated: 2;
  --z-sticky: 100;
  --z-dropdown: 200;
  --z-overlay: 1000;
  --z-modal: 5000;
  --z-toast: 9000;
  --z-skip: 10000;

  /* Touch Targets */
  --touch-min: 44px;
  --touch-comfortable: 48px;
}

/* Light Theme */
:root[data-theme="light"] {
  --bg-void: #f8f9fc;
  --bg-primary: #ffffff;
  --bg-secondary: #f3f4f8;
  --bg-tertiary: #eaecf2;
  --bg-hover: #e2e5ed;
  --bg-active: #d8dce6;
  --border: rgba(0, 0, 0, 0.08);
  --border-subtle: rgba(0, 0, 0, 0.04);
  --border-focus: rgba(220, 90, 30, 0.4);
  --surface-glass: rgba(255, 255, 255, 0.75);
  --text-primary: #151820;
  --text-secondary: #5a6270;
  --text-muted: #8a929e;
  --text-inverse: #f8f9fc;
  --accent: #e05a1a;
  --accent-hover: #c94e15;
  --accent-dim: rgba(224, 90, 26, 0.10);
  --accent-glow: 0 0 16px rgba(224, 90, 26, 0.15);
  --shadow-sm: 0 1px 3px rgba(0, 0, 0, 0.06);
  --shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
  --shadow-lg: 0 8px 32px rgba(0, 0, 0, 0.1);
  --shadow-glow: 0 0 20px rgba(224, 90, 26, 0.1);
  --glass-bg: rgba(255, 255, 255, 0.7);
  --glass-border: rgba(0, 0, 0, 0.06);
}

/* Reduced Motion */
@media (prefers-reduced-motion: reduce) {
  :root {
    --duration-instant: 0ms;
    --duration-fast: 0ms;
    --duration-normal: 0ms;
    --duration-slow: 0ms;
    --duration-slower: 0ms;
  }
}
```

### CSS File Structure

```
css/
  tokens.css           (~200 lines)  — Variables only
  base.css             (~300 lines)  — Reset, typography, links
  utilities.css        (~200 lines)  — d-flex, gap-*, text-*, sr-only
  layout.css           (~600 lines)  — Nav, page shell, grid, split
  components.css       (~800 lines)  — Btn, badge, card, table, form, tooltip
  charts.css           (~400 lines)  — ChartFrame, legend, drawer, skeleton
  motion.css           (~200 lines)  — @keyframes, transitions, stagger
  corner_replay.css    (refactored)
  focus_mode.css       (refactored)
  gg_explorer.css      (refactored)
  speed_trace_zoom.css (refactored)
  race_strategy.css    (refactored)
```

---

## Phase 2: ModuleManager + JS Lifecycle

### ModuleManager API

```js
window.ModuleManager = {
  register(name, { init, destroy, redraw })  // Register module
  activate(names[])                           // Init modules, deactivate previous
  deactivateAll()                             // Destroy all active modules
  isActive(name) -> bool
  getActive() -> names[]
}
```

### LifecycleHelpers

Shared utility for tracking listeners, timers, intervals, and rAF for automatic cleanup:

```js
window.LifecycleHelpers = {
  create() -> {
    addListener(el, evt, fn, opts)  // Tracked addEventListener
    addTimer(fn, ms) -> id          // Tracked setTimeout
    addInterval(fn, ms) -> id       // Tracked setInterval
    addRaf(fn) -> id                // Tracked requestAnimationFrame
    destroyAll()                    // Cleans up everything
  }
}
```

### Canvas Standard

```js
function sizeCanvas(canvas, w, h) {
  var dpr = window.devicePixelRatio || 1;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  canvas.style.width = w + 'px';
  canvas.style.height = h + 'px';
  var ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return ctx;
}
```

### Canvas Cleanup Standard

```js
destroy: function() {
  helpers.destroyAll();
  if (_canvas) {
    var ctx = _canvas.getContext('2d');
    if (ctx) ctx.clearRect(0, 0, _canvas.width, _canvas.height);
    _canvas.width = 0;
    _canvas.height = 0;
  }
  _dataCache = {};
  _state = { /* initial */ };
}
```

---

## Phase 3: Responsive System + Chart Contract

### Unified Breakpoint Scale (mobile-first, min-width only)

```
xs:  0-479px      (small phones)
sm:  480-767px    (large phones)
md:  768-1023px   (tablets)
lg:  1024-1439px  (laptops)
xl:  1440-1919px  (desktops)
2xl: 1920-2559px  (large monitors)
3xl: 2560+        (ultrawide/4K)
```

Rule: Base styles = xs. @media uses min-width only. No max-width except print. No ad-hoc pixel values.

### Container Queries for Charts

```css
.chart-frame { container-type: inline-size; container-name: chart; }

@container chart (max-width: 400px) {
  .chart-frame .chart-legend { display: none; }
}
@container chart (max-width: 300px) {
  .chart-frame .chart-axis-y { display: none; }
}
```

### ChartFrame Contract

Every chart wraps in `.chart-frame`:
- Header: title, legend toggle, export, expand
- Canvas area: ResizeObserver-driven, DPR-aware
- Tooltip: desktop = pointer-follows, mobile = bottom drawer
- States: `--loading` (skeleton), `--empty` (message + action), `--error` (retry)

### Mobile Card Stack

```css
@media (max-width: 767px) {
  .chart-stack {
    display: flex;
    overflow-x: auto;
    scroll-snap-type: x mandatory;
    -webkit-overflow-scrolling: touch;
  }
  .chart-stack > .chart-frame {
    flex: 0 0 100%;
    scroll-snap-align: start;
  }
}
```

### Bottom Drawer (mobile tooltip)

Fixed to bottom, slides up on chart tap, max-height 40vh, auto-dismissed.

### Interaction Throttling

- mousemove: 16ms (60fps)
- resize: 150ms debounce
- scroll: 100ms throttle, passive
- touchmove: no throttle, passive

---

## Phase 4: Visual Refresh — Dashboard

NASA Eyes "Mission Control" treatment:

- KPI cards with instrument glow line (accent gradient at top)
- Monospace numbers with tick-up animation on load
- Delta indicators (up/down arrows, green/red)
- Stagger fade-in for card grids (50ms per child, 300ms duration)
- Hover: 2px lift + glow shadow
- Recent sessions table with skeleton loading
- Quick charts in ChartFrame containers
- Track coverage mini-maps

---

## Phase 5: Visual Refresh — Race Strategy Live

Real-time instrument panel:

- Connection status dot with pulse animation
- Race progress bar (gradient fill)
- Position board with driver color swatches and border-left indicator
- Alert panel with pulse-glow on new alerts
- Pace analysis charts in ChartFrame
- Visibility-aware polling (pause when tab hidden)

---

## Phase 6: Component Library

### Components

| Component | Variants | States |
|-----------|----------|--------|
| Button | primary, ghost, danger, icon-only, sm/md/lg | hover, focus, active, disabled, loading |
| Badge | session-type, condition, grade, style, status, count | — |
| Card | default, glass, elevated, interactive | hover, active |
| Table | default, striped, compact, sortable, sticky | loading, empty |
| Form Input | text, number, select, textarea, file, checkbox, toggle | focus, invalid, disabled |
| ChartFrame | default, compact, fullscreen | loading, empty, error |
| Tooltip | desktop, drawer (mobile) | visible, hidden |
| Toast | success, error, warning, info | entering, visible, exiting |
| Empty State | default, compact, with-action | — |
| Skeleton | text, card, table-row, chart, circle | shimmer |
| Modal | default, confirm, fullscreen | open, closing |
| Chip/Tag | default, removable, selectable | selected, hover |
| Progress | bar, circular, stepped | indeterminate, determinate |

### Naming Convention

Prefix-based BEM-lite:
```
.component                    .btn, .card, .badge
.component--variant           .btn--primary, .card--glass
.component--state             .btn--loading
.component__element           .card__header
.component__element--mod      .card__header--sticky
```

Feature prefixes: `.cr-*`, `.rs-*`, `.fm-*`, `.gg-*`, `.sp-*`, `.st-*`

---

## Phase 7: Remaining Pages Migration

### Wave Order

| Wave | Pages | Count |
|------|-------|-------|
| 1 | Session Detail, Visualize | 2 |
| 2 | Driver Profile, Driver List | 2 |
| 3 | Track Detail, Track List | 2 |
| 4 | Analyze, Compare | 2 |
| 5 | Leaderboard, Analytics Index, Trends | 3 |
| 6 | Race Strategy (config, index, summary, detail) | 4 |
| 7 | Weekend, Kart, Annotation, Export | 8 |
| 8 | Data Health, Dev Plans, What-If, Setup, Meteo | 6 |
| 9 | Error pages (404, 500), Custom Dashboard | 3 |

### Per-Page Checklist

- Replace hardcoded values with tokens (colors, spacing, fonts, z-index, transitions, radii)
- Remove inline styles, use utilities or component classes
- Wrap charts in ChartFrame
- Add loading/empty/error states
- Verify light mode
- Verify 320px, 768px, 1920px breakpoints
- Migrate JS to lifecycle protocol
- Run axe-core check
- Capture Playwright screenshots

---

## Phase 8: Accessibility Hardening

### WCAG 2.2 AA Targets

- All charts: `aria-label` + sr-only data table
- All interactive elements: >=44px touch targets
- Focus ring: animated glow (2px solid accent, offset 2px)
- Color contrast: >=4.5:1 for all text
- Keyboard nav: Tab, Enter, Escape for all interactions
- prefers-reduced-motion: all durations set to 0ms

---

## Phase 9: Performance Budgets + CI

| Metric | Budget |
|--------|--------|
| CSS total | <80KB uncompressed |
| JS per page | <120KB |
| LCP | <2.5s |
| INP | <200ms |
| CLS | <0.1 |
| Accessibility score | >=0.9 |

### CI Integration

- Lighthouse CI on 4 key pages (dashboard, session list, session detail, race live)
- axe-core Playwright tests on all pages
- Visual regression screenshots: 5 viewports x N pages x 2 themes

---

## Phase 10: Documentation + Governance

```
docs/ui-architecture/
  README.md
  tokens.md
  components.md
  responsive.md
  charts.md
  motion.md
  accessibility.md
  migration-checklist.md
  contribution-checklist.md
```

### Contribution Checklist

Before merging any new UI:
- No hardcoded values (colors, spacing, fonts, z-index, transitions)
- Responsive at 360px, 768px, 1920px
- axe-core 0 violations
- Loading, empty, error states present
- Light mode correct
- Reduced motion safe
- Module registered with ModuleManager (init + destroy)
