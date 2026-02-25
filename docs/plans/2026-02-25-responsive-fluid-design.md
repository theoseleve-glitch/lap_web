# Responsive Fluid Design — CSS Grid `auto-fit` + `clamp()` Overhaul

**Date:** 2026-02-25
**Status:** Approved
**Approach:** B — Full CSS `clamp()` + `auto-fit` overhaul, zero breakpoints (1 exception)

## Requirements

- All images, graphs, sections dynamically adjust to window size at all times
- Minimum supported width: 360px (modern smartphones)
- Maximum: ultrawide (no upper bound, content constrained by `clamp()`)
- Charts maintain aspect ratio as width shrinks — never distorted
- Layout sections auto-stack on narrow screens; data tables scroll horizontally
- Live resize on desktop (drag browser edge) triggers canvas redraws

## Architecture

### Layer Summary

| Layer | Strategy | Breakpoints |
|-------|----------|-------------|
| Layout | CSS Grid `auto-fit` + `minmax(clamp())` | 1: sidebar collapse at 600px |
| Charts | `aspect-ratio` + `width: 100%` containers; canvas fills parent | None |
| Canvas redraw | Global `ResizeObserver` with `rAF` batching; charts register `__redraw` | None |
| Typography | `clamp(min, preferred, max)` on all font sizes | None |
| Spacing | 5 CSS custom properties using `clamp()` | None |
| Data tables | `.table-scroll-wrapper` with `overflow-x: auto` + fade hints | None |
| Forms | `flex-wrap` + `clamp()` max-widths | None |
| Modals | `clamp()` width + `vh`-based max-height | None |
| Navigation | `flex-wrap` + `overflow: visible` fix | None |
| Overflow audit | 47 instances triaged: keep / visible / auto | None |

### 1. Core Layout System

Replace fixed `max-width`, `width`, `height`, `min-height` with `clamp()`:

```css
.main-content { width: clamp(360px, 95vw, 1400px); }

.card-grid {
  grid-template-columns: repeat(auto-fit, minmax(clamp(240px, 30vw, 400px), 1fr));
  gap: clamp(0.5rem, 1.5vw, 1.5rem);
}

.layout-with-sidebar {
  display: grid;
  grid-template-columns: clamp(200px, 20vw, 300px) 1fr;
  gap: clamp(0.75rem, 2vw, 1.5rem);
}
@media (max-width: 600px) {
  .layout-with-sidebar { grid-template-columns: 1fr; }
}
```

### 2. Chart & Canvas Containers

Replace fixed heights with `aspect-ratio`:

```css
.chart-container { width: 100%; aspect-ratio: 2 / 1; }
.chart-container--tall { aspect-ratio: 3 / 2; }
.chart-container--square { aspect-ratio: 1 / 1; max-width: clamp(240px, 40vw, 420px); }
.chart-container canvas { display: block; width: 100%; height: 100%; }
```

Race strategy canvas:
```css
.rs-canvas { width: clamp(280px, 50vw, 600px); aspect-ratio: 1 / 1; }
.rs-canvas-small { width: clamp(160px, 25vw, 300px); aspect-ratio: 1 / 1; }
```

Corner replay:
```css
.cr-viewport {
  grid-template-columns: repeat(auto-fit, minmax(clamp(280px, 40vw, 600px), 1fr));
}
.cr-panel { aspect-ratio: 4 / 3; }
```

Remove hardcoded `width`/`height` HTML attributes from all `<canvas>` elements.

### 3. Typography & Spacing

```css
h1 { font-size: clamp(1.25rem, 1rem + 1.5vw, 2rem); }
h2 { font-size: clamp(1.1rem, 0.9rem + 1vw, 1.5rem); }
h3 { font-size: clamp(1rem, 0.85rem + 0.7vw, 1.25rem); }
body { font-size: clamp(0.85rem, 0.8rem + 0.25vw, 1rem); }
.stat-value { font-size: clamp(1.4rem, 1rem + 2vw, 2.5rem); }

:root {
  --space-xs: clamp(0.25rem, 0.5vw, 0.5rem);
  --space-sm: clamp(0.5rem, 1vw, 0.75rem);
  --space-md: clamp(0.75rem, 1.5vw, 1.25rem);
  --space-lg: clamp(1rem, 2.5vw, 2rem);
  --space-xl: clamp(1.5rem, 3.5vw, 3rem);
}
```

### 4. Data Tables

Wrap all `<table>` elements in scroll container:

```html
<div class="table-scroll-wrapper">
  <table class="data-table">...</table>
</div>
```

```css
.table-scroll-wrapper {
  width: 100%;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}
.table-scroll-wrapper table { min-width: 600px; width: 100%; }
```

### 5. Navigation, Modals & Forms

```css
.nav-links { display: flex; flex-wrap: wrap; gap: clamp(0.25rem, 1vw, 1rem); overflow: visible; }
.nav-link { font-size: clamp(0.75rem, 0.7rem + 0.3vw, 0.95rem); white-space: nowrap; }

.modal-content { width: clamp(320px, 85vw, 700px); max-height: clamp(300px, 80vh, 90vh); overflow-y: auto; }

.form-group input, .form-group select, .form-group textarea { width: 100%; max-width: clamp(240px, 60vw, 450px); }
.form-row { display: flex; flex-wrap: wrap; gap: var(--space-sm); }
.form-row > .form-group { flex: 1 1 clamp(200px, 30vw, 350px); }
```

### 6. Overflow Audit

47 instances of `overflow: hidden` triaged:
- **Keep:** Cards, modals, toasts (aesthetic — border-radius clipping)
- **Change to `visible`:** `.top-nav`, `.nav-links`, `.section` (were clipping content)
- **Change to `auto`:** `.sidebar`, `.rs-telemetry-grid` (allow scrolling)

### 7. ResizeObserver Utility

New file: `telemetry_tool/web/static/js/resize_observer.js`

- Global `ResizeObserver` watches all `.chart-container` elements
- Batches redraws via `requestAnimationFrame` (one frame, all charts)
- Charts register `canvas.__redraw = () => drawFunction(canvas, data)`
- Public API: `window.TelemetryResize.observe(el)` for AJAX-loaded content
- Loaded in `base.html` before chart scripts

## Files Touched

**CSS (edit in-place):**
- `main.css` — layout, typography, spacing, overflow, nav, modals, forms, chart containers
- `race_strategy.css` — canvas sizing, grid layouts
- `corner_replay.css` — viewport grid, panel sizing, overflow
- `speed_trace_zoom.css` — container sizing
- `gg_explorer.css` — container sizing

**JS (new):**
- `resize_observer.js` — global resize utility

**JS (edit — add `__redraw` registration):**
- `trend_chart.js`
- `fingerprint_chart.js`
- `brake_scatter.js`
- `consistency_heatmap.js`
- `throttle_heatmap.js`
- `gg_diagram.js`
- `corner_replay_map.js`
- `corner_replay_cockpit.js`
- `speed_trace_zoom.js`
- `race_strategy.js` (if applicable)

**Templates (edit):**
- `base.html` — add resize_observer.js script tag
- `session_detail.html` — remove canvas attrs, add chart-container classes
- `race_strategy.html` — remove canvas attrs
- `dev_plan.html` — remove canvas attrs
- `meteo_dashboard.html` — remove canvas attrs
- `weight_simulator.html` — remove canvas attrs
- `analyze.html` — remove inline fixed styles
- All templates with `<table>` — wrap in `.table-scroll-wrapper`

## What Does NOT Change

- No new dependencies or npm packages
- No framework additions
- Chart rendering logic untouched (just wired to `__redraw`)
- Dark theme / glassmorphic styling preserved
- All existing functionality intact
- Existing media queries for print / reduced-motion / hover preserved
