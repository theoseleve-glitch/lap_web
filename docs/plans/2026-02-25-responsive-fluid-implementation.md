# Responsive Fluid Design — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make every element in the web app dynamically resize based on window size — 360px to ultrawide, live resize, zero breakpoints (1 exception).

**Architecture:** CSS Grid `auto-fit` + `clamp()` overhaul. Replace all fixed pixel dimensions with fluid `clamp(min, preferred, max)` functions. Add a global `ResizeObserver` utility that batches canvas redraws via `requestAnimationFrame`. Each chart JS file registers a `__redraw` callback.

**Tech Stack:** Vanilla CSS (no preprocessor), vanilla JS (no framework), Canvas 2D API, Flask/Jinja2 templates.

**Design doc:** `docs/plans/2026-02-25-responsive-fluid-design.md`

---

### Task 1: Add CSS Spacing Custom Properties to `:root`

**Files:**
- Modify: `telemetry_tool/web/static/css/main.css:7-62` (existing `:root` block)

**Step 1: Add spacing scale variables to `:root`**

In `main.css`, inside the existing `:root` block (after the last variable, before the closing `}`), add:

```css
    /* ── Fluid spacing scale ── */
    --space-xs: clamp(0.25rem, 0.5vw, 0.5rem);
    --space-sm: clamp(0.5rem, 1vw, 0.75rem);
    --space-md: clamp(0.75rem, 1.5vw, 1.25rem);
    --space-lg: clamp(1rem, 2.5vw, 2rem);
    --space-xl: clamp(1.5rem, 3.5vw, 3rem);
```

**Step 2: Verify no syntax errors**

Run: `python telemetry_tool/main.py --serve` and open localhost:5000 in browser.
Expected: Page loads normally, no visual changes yet.

**Step 3: Commit**

```bash
git add telemetry_tool/web/static/css/main.css
git commit -m "feat(responsive): add fluid spacing CSS custom properties"
```

---

### Task 2: Convert Core Layout to Fluid in `main.css`

**Files:**
- Modify: `telemetry_tool/web/static/css/main.css`

**Step 1: Convert main content container**

Line 325 — change:
```css
/* FROM */
.main-content { max-width: 1280px; width: 100%; margin: 0 auto; }
/* TO */
.main-content { width: clamp(360px, 95vw, 1400px); margin: 0 auto; }
```

**Step 2: Convert GPS map height to aspect-ratio**

Line 1286-1288 — change:
```css
/* FROM */
.gps-map { height: 450px; width: 100%; border-radius: var(--radius-lg); overflow: hidden; margin-bottom: 1rem; }
/* TO */
.gps-map { width: 100%; aspect-ratio: 16 / 9; border-radius: var(--radius-lg); overflow: hidden; margin-bottom: var(--space-md); }
```

Also line 7140 — change `.gps-map-tall`:
```css
/* FROM */
.gps-map-tall { height: 400px; }
/* TO */
.gps-map-tall { aspect-ratio: 4 / 3; }
```

Remove the media query override at line 2247-2249 (`@media (max-width: 768px) .gps-map { height: 300px; }`) — no longer needed since aspect-ratio scales naturally.

**Step 3: Convert grid-template-columns with fixed `1fr 1fr` to auto-fit**

Line 2336: `grid-template-columns: 1fr 1fr;` → `grid-template-columns: repeat(auto-fit, minmax(clamp(280px, 40vw, 500px), 1fr));`

Line 2402: `grid-template-columns: 1fr 1fr;` → `grid-template-columns: repeat(auto-fit, minmax(clamp(280px, 40vw, 500px), 1fr));`

Line 2412: `grid-template-columns: 1fr 1fr;` → `grid-template-columns: repeat(auto-fit, minmax(clamp(280px, 40vw, 500px), 1fr));`

Line 5715: `grid-template-columns: 1fr 1fr;` → `grid-template-columns: repeat(auto-fit, minmax(clamp(280px, 40vw, 500px), 1fr));`

Line 9074: `grid-template-columns: 1fr 1fr;` → `grid-template-columns: repeat(auto-fit, minmax(clamp(280px, 40vw, 500px), 1fr));`

**Step 4: Convert sidebar layout (1fr 300px)**

Line 9009: `grid-template-columns: 1fr 300px;` → `grid-template-columns: 1fr clamp(200px, 20vw, 300px);`

Add below it:
```css
@media (max-width: 600px) {
    /* Sidebar collapse — only breakpoint in the system */
    [style*="grid-template-columns: 1fr clamp"] { grid-template-columns: 1fr; }
}
```

Note: this targets the sidebar-with-content pattern. Verify the selector matches the actual parent class at line 9009 and use that class instead.

**Step 5: Convert grid minmax values to use clamp()**

Line 453: `minmax(160px, 1fr)` → `minmax(clamp(120px, 15vw, 180px), 1fr)`
Line 1054: `minmax(180px, 1fr)` → `minmax(clamp(140px, 18vw, 200px), 1fr)`
Line 1506: `minmax(280px, 1fr)` → `minmax(clamp(240px, 30vw, 320px), 1fr)`
Line 1769: `minmax(180px, 1fr)` → `minmax(clamp(140px, 20vw, 220px), 1fr)`
Line 2017: `minmax(200px, 1fr)` → `minmax(clamp(160px, 22vw, 240px), 1fr)`
Line 3498: `minmax(220px, 1fr)` → `minmax(clamp(180px, 22vw, 260px), 1fr)`
Line 3507: `minmax(200px, 1fr)` → `minmax(clamp(160px, 22vw, 240px), 1fr)`
Line 4038: `minmax(150px, 1fr)` → `minmax(clamp(120px, 15vw, 180px), 1fr)`
Line 6433: `minmax(200px, 1fr)` → `minmax(clamp(160px, 22vw, 240px), 1fr)`
Line 6437: `minmax(220px, 1fr)` → `minmax(clamp(180px, 22vw, 260px), 1fr)`
Line 7882: `minmax(140px, 1fr)` → `minmax(clamp(100px, 14vw, 160px), 1fr)`
Line 9197: `minmax(260px, 1fr)` → `minmax(clamp(220px, 28vw, 300px), 1fr)`
Line 9374: `minmax(280px, 1fr)` → `minmax(clamp(240px, 30vw, 320px), 1fr)`
Line 9581: `minmax(250px, 1fr)` → `minmax(clamp(200px, 26vw, 280px), 1fr)`
Line 9877: `minmax(260px, 1fr)` → `minmax(clamp(220px, 28vw, 300px), 1fr)`

**Step 6: Convert gap/padding/margin to spacing vars**

Search and replace throughout `main.css`:
- `gap: 1.5rem` → `gap: var(--space-lg)`
- `gap: 1rem` → `gap: var(--space-md)`
- `gap: 0.75rem` → `gap: var(--space-sm)`
- `gap: 0.5rem` → `gap: var(--space-xs)`
- `padding: 1rem` → `padding: var(--space-md)` (on cards/sections, NOT on small elements)
- `margin-bottom: 1rem` → `margin-bottom: var(--space-md)` (on sections)
- `margin-bottom: 2rem` → `margin-bottom: var(--space-lg)` (on page sections)

Be selective — only convert spacing on layout containers (cards, sections, grids, page headers), NOT on small elements like badges, buttons, or inline spans.

**Step 7: Remove redundant media queries that adjusted heights/columns**

Remove or comment out these now-unnecessary breakpoint blocks:
- Line 2247-2249: `@media (max-width: 768px) .gps-map` (handled by aspect-ratio)
- Line 4819-4821: `@media (max-height: 480px) .chart-container` (handled by aspect-ratio)
- Line 6351: `@media (min-width: 481px) and (max-width: 768px) .chart-container` (handled)
- Line 6407: `@media (max-height: 680px) .chart-container` (handled)
- Line 6445: `@media (min-width: 769px) .chart-container` (handled)

Keep: print queries, `prefers-reduced-motion`, `hover` queries — those serve different purposes.

**Step 8: Verify layout**

Run: `python telemetry_tool/main.py --serve` and check dashboard, session list, session detail pages.
Expected: Layout should be fluid — drag browser width from 360px to full width. Grids reflow smoothly, no jumps.

**Step 9: Commit**

```bash
git add telemetry_tool/web/static/css/main.css
git commit -m "feat(responsive): convert core layout to fluid clamp/auto-fit"
```

---

### Task 3: Convert Chart Containers to Aspect-Ratio

**Files:**
- Modify: `telemetry_tool/web/static/css/main.css`

**Step 1: Convert `.chart-container` to aspect-ratio**

Line 1316-1328 — replace height/min-height rules:
```css
.chart-container {
    position: relative;
    width: 100%;
    aspect-ratio: 2 / 1;
    background: rgba(14, 17, 24, 0.65);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: var(--radius-sm);
    margin: var(--space-xs) 0;
    padding: var(--space-md);
    box-shadow: 0 2px 16px rgba(0, 0, 0, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.03);
    overflow: hidden;
}
```

Line 1330-1332 — keep but ensure canvas fills:
```css
.chart-container canvas {
    display: block;
    width: 100%;
    height: 100%;
}
```

**Step 2: Convert viz containers**

Line 3098-3099 — change:
```css
/* FROM */
.viz-container { height: 45vh; min-height: 320px; }
/* TO */
.viz-container { width: 100%; aspect-ratio: 2 / 1; }
```

Line 3110-3111 — change:
```css
/* FROM */
.viz-chart-container { height: 300px; min-height: 260px; }
/* TO */
.viz-chart-container { width: 100%; aspect-ratio: 2 / 1; }
```

Line 3122-3123 — change (G-G diagram is taller/square):
```css
/* FROM */
.gg-diagram { height: 400px; min-height: 350px; }
/* TO */
.gg-diagram { width: 100%; aspect-ratio: 1 / 1; max-width: clamp(300px, 50vw, 500px); }
```

**Step 3: Add modifier classes for different aspect ratios**

Add after the `.chart-container` rules:
```css
/* Chart aspect-ratio modifiers */
.chart-container--wide    { aspect-ratio: 5 / 2; }   /* speed traces, timelines */
.chart-container--tall    { aspect-ratio: 3 / 2; }   /* GPS maps, detail charts */
.chart-container--square  { aspect-ratio: 1 / 1; max-width: clamp(240px, 40vw, 420px); }  /* radar, fingerprint */
.chart-container--short   { aspect-ratio: 3 / 1; }   /* progress bars, heatmaps */
```

**Step 4: Convert skeleton placeholders**

Line 4031: `.skeleton-card { height: 120px; }` → `.skeleton-card { aspect-ratio: 3 / 1; }`
Line 4084: `.skeleton-chart { height: 250px; }` → `.skeleton-chart { aspect-ratio: 2 / 1; }`
Line 7942: `.skeleton-card { height: 120px; }` → `.skeleton-card { aspect-ratio: 3 / 1; }`
Line 7952: `.skeleton-chart { height: 200px; }` → `.skeleton-chart { aspect-ratio: 2 / 1; }`

**Step 5: Verify charts**

Run app. Check session detail page (most charts), visualize page, dashboard.
Expected: Charts maintain proportions, shrink/grow with window width.

**Step 6: Commit**

```bash
git add telemetry_tool/web/static/css/main.css
git commit -m "feat(responsive): convert chart containers to aspect-ratio"
```

---

### Task 4: Convert Typography to Fluid

**Files:**
- Modify: `telemetry_tool/web/static/css/main.css`

**Step 1: Convert body font-size**

Line 210: `font-size: 15px;` → `font-size: clamp(0.85rem, 0.8rem + 0.25vw, 1rem);`

**Step 2: Add fluid heading sizes**

Find `.section h2` at line 567 and similar heading rules. Add general heading rules after the body rule (around line 215):

```css
h1, .h1 { font-size: clamp(1.25rem, 1rem + 1.5vw, 2rem); }
h2, .h2 { font-size: clamp(1.1rem, 0.9rem + 1vw, 1.5rem); }
h3, .h3 { font-size: clamp(1rem, 0.85rem + 0.7vw, 1.25rem); }
```

These will be overridden by more specific selectors where needed, but set the default fluid behavior.

**Step 3: Convert stat-value**

Line 521-522: `font-size: 2rem;` → `font-size: clamp(1.4rem, 1rem + 2vw, 2.5rem);`

Remove the media query overrides that adjusted stat-value font sizes:
- Line 4645: `@media (max-height: 480px) .stat-value { font-size: 1.3rem; }` — remove
- Line 8288: `@media (min-width: 769px) .stat-value { font-size: 1.5rem; }` — remove

These are now handled by `clamp()`.

**Step 4: Convert nav link font sizes**

Find `.nav-link` font-size and convert to:
```css
.nav-link { font-size: clamp(0.75rem, 0.7rem + 0.3vw, 0.95rem); }
```

**Step 5: Verify text scaling**

Run app. Drag window from 360px to full width. Text should scale smoothly.
Expected: No jumps, all text readable at 360px, comfortable at 1400px+.

**Step 6: Commit**

```bash
git add telemetry_tool/web/static/css/main.css
git commit -m "feat(responsive): convert typography to fluid clamp() scaling"
```

---

### Task 5: Convert Navigation, Modals & Forms to Fluid

**Files:**
- Modify: `telemetry_tool/web/static/css/main.css`

**Step 1: Fix nav overflow and make fluid**

Find `.nav-links` and change `overflow: hidden` → `overflow: visible`. Add `flex-wrap: wrap`.

```css
.nav-links {
    display: flex;
    flex-wrap: wrap;
    gap: clamp(0.25rem, 1vw, 1rem);
    overflow: visible;
}
```

**Step 2: Convert modals to fluid**

Find `.modal-content` or equivalent modal rules (around line 3026+):
```css
.modal-content {
    width: clamp(320px, 85vw, 700px);
    max-height: clamp(300px, 80vh, 90vh);
    overflow-y: auto;
}
```

**Step 3: Convert form inputs**

Line 7004 `.rename-input { max-width: 300px; }` → `.rename-input { max-width: clamp(200px, 50vw, 350px); }`

Add general form fluid rules:
```css
.form-group input,
.form-group select,
.form-group textarea {
    width: 100%;
    max-width: clamp(240px, 60vw, 450px);
}

.form-row {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-sm);
}

.form-row > .form-group {
    flex: 1 1 clamp(200px, 30vw, 350px);
}
```

**Step 4: Convert empty state min-heights**

Line 1378: `.empty-state { min-height: 200px; }` → `.empty-state { min-height: clamp(120px, 20vh, 250px); }`
Line 1400: `.empty-state-inline { min-height: 200px; }` → `.empty-state-inline { min-height: clamp(100px, 15vh, 200px); }`

**Step 5: Convert `.style-header`**

Line 2347: `.style-header { min-height: 260px; }` → `.style-header { min-height: clamp(160px, 25vh, 300px); }`

**Step 6: Verify navigation, forms, modals**

Run app. Test nav at narrow widths, open a modal, check form pages.
Expected: Nav wraps gracefully, modals scale, forms don't overflow.

**Step 7: Commit**

```bash
git add telemetry_tool/web/static/css/main.css
git commit -m "feat(responsive): convert nav, modals, forms to fluid sizing"
```

---

### Task 6: Overflow Audit — Fix Clipping Issues

**Files:**
- Modify: `telemetry_tool/web/static/css/main.css`

**Step 1: Change layout-level overflow:hidden to visible/auto**

The following `overflow: hidden` should be changed. Look up each line and verify the selector before changing:

Keep `overflow: hidden` (aesthetic/intentional):
- Line 195: `.sr-only` — keep
- Line 467: `.btn` — keep
- Line 1281: `.card` — keep (border-radius clipping)
- Line 1327: `.chart-container` — keep (border-radius clipping)
- Line 3484: `.dashboard-widget` — keep (border-radius clipping)

Change to `overflow: visible`:
- `.section` or any generic content wrapper that uses `overflow: hidden` — change to `overflow: visible`

Change to `overflow-y: auto`:
- `.sidebar` — change to `overflow-y: auto; overflow-x: hidden;`

**Step 2: Remove `!important` overflow utility**

Line 5694: `.overflow-hidden { overflow: hidden !important; }` — keep as-is (utility class, used intentionally).

**Step 3: Verify no content clipping**

Run app. Check session detail (scroll through charts), sidebar navigation.
Expected: No content clipped unexpectedly. Cards and chart containers still have rounded corners.

**Step 4: Commit**

```bash
git add telemetry_tool/web/static/css/main.css
git commit -m "fix(responsive): resolve overflow:hidden clipping on layout containers"
```

---

### Task 7: Convert Race Strategy CSS to Fluid

**Files:**
- Modify: `telemetry_tool/web/static/css/race_strategy.css`

**Step 1: Convert grid layouts**

Line 276: `minmax(260px, 1fr)` → `minmax(clamp(200px, 28vw, 300px), 1fr)`
Line 647: `grid-template-columns: repeat(3, 1fr);` → `grid-template-columns: repeat(auto-fit, minmax(clamp(280px, 30vw, 400px), 1fr));`
Line 1127: `minmax(150px, 1fr)` → `minmax(clamp(120px, 15vw, 180px), 1fr)`

Remove breakpoint overrides that are now unnecessary:
- Line 1247: `@media (max-width: 1024px)` grid override — remove
- Line 1259: `@media (max-width: 768px)` grid override — remove

**Step 2: Convert padding/gap to spacing vars**

Replace `gap` and `padding` values in race_strategy.css with `var(--space-*)` equivalents where appropriate (cards, sections, grids).

**Step 3: Audit overflow:hidden instances**

Check lines 177, 244, 434, 515, 704, 721, 870, 973, 1065 — for each:
- If it's on a card/aesthetic element: keep
- If it's on a layout/grid container: change to `overflow: visible` or `overflow: auto`

**Step 4: Verify race strategy pages**

Run app. Navigate to race strategy index, config, live, detail pages.
Expected: Grids reflow at all widths, no content clipped.

**Step 5: Commit**

```bash
git add telemetry_tool/web/static/css/race_strategy.css
git commit -m "feat(responsive): convert race strategy CSS to fluid layout"
```

---

### Task 8: Convert Corner Replay CSS to Fluid

**Files:**
- Modify: `telemetry_tool/web/static/css/corner_replay.css`

**Step 1: Convert viewport grid**

Line 118-122 — change:
```css
/* FROM */
.cr-viewport { display: grid; grid-template-columns: 1fr 1fr; min-height: 340px; }
/* TO */
.cr-viewport { display: grid; grid-template-columns: repeat(auto-fit, minmax(clamp(280px, 40vw, 600px), 1fr)); }
```

**Step 2: Convert panels to aspect-ratio**

Line 133: `.cr-map-panel { min-height: 340px; }` → `.cr-map-panel { aspect-ratio: 4 / 3; }`
Line 150: `.cr-cockpit-panel { min-height: 340px; }` → `.cr-cockpit-panel { aspect-ratio: 4 / 3; }`
Line 168: `.cr-cockpit-row { min-height: 170px; }` → `.cr-cockpit-row { aspect-ratio: 8 / 3; }`

**Step 3: Remove min-height media query overrides**

Remove:
- Line 428: `@media (max-width: 768px) .cr-map-panel { min-height: 240px; }` — handled by aspect-ratio
- Line 432: `@media (max-width: 768px) .cr-cockpit-panel { min-height: 280px; }` — handled
- Line 451: `@media (max-height: 500px) .cr-viewport { min-height: 280px; }` — handled
- Line 455: `@media (max-height: 500px) .cr-map-panel, .cr-cockpit-panel { min-height: 220px; }` — handled

Keep the `@media (max-width: 768px)` rule if it changes `grid-template-columns` to `1fr` for stacking.
But since we now use `auto-fit`, that stacking happens automatically. Remove it.

**Step 4: Convert overflow:hidden**

Line 12: `.cr-section { overflow: hidden; }` — change to `overflow: visible;` (layout container).

**Step 5: Verify corner replay**

Run app. Open session detail → corner replay section.
Expected: Map and cockpit panels scale with window, maintain 4:3 ratio, stack on narrow screens.

**Step 6: Commit**

```bash
git add telemetry_tool/web/static/css/corner_replay.css
git commit -m "feat(responsive): convert corner replay to fluid aspect-ratio layout"
```

---

### Task 9: Convert Secondary CSS Files to Fluid

**Files:**
- Modify: `telemetry_tool/web/static/css/speed_trace_zoom.css`
- Modify: `telemetry_tool/web/static/css/gg_explorer.css`

**Step 1: Audit speed_trace_zoom.css (262 lines)**

Search for fixed `height`, `width`, `min-height` values. Convert any pixel-based container dimensions to `aspect-ratio` or `clamp()`. Convert `gap`/`padding` to spacing vars.

**Step 2: Audit gg_explorer.css (194 lines)**

Same audit. The GG explorer canvas likely has fixed dimensions — convert to `aspect-ratio: 1 / 1` with `max-width: clamp(...)`.

**Step 3: Verify**

Run app. Open visualize page with speed trace zoom, GG explorer.
Expected: Both scale fluidly.

**Step 4: Commit**

```bash
git add telemetry_tool/web/static/css/speed_trace_zoom.css telemetry_tool/web/static/css/gg_explorer.css
git commit -m "feat(responsive): convert speed trace and GG explorer CSS to fluid"
```

---

### Task 10: Remove Hardcoded Canvas Attributes from Templates

**Files:**
- Modify: `telemetry_tool/web/templates/dev_plan.html:44,48`
- Modify: `telemetry_tool/web/templates/meteo_dashboard.html:55`
- Modify: `telemetry_tool/web/templates/race_strategy.html:105`
- Modify: `telemetry_tool/web/templates/session_detail.html:240,519`
- Modify: `telemetry_tool/web/templates/weight_simulator.html:76`

**Step 1: dev_plan.html — remove width/height/style from canvases**

Line 44: `<canvas id="progress-canvas" width="700" height="220" style="width:100%;max-width:700px;" ...>`
→ `<canvas id="progress-canvas" ...>`

Line 48: `<canvas id="score-canvas" width="700" height="160" style="width:100%;max-width:700px;" ...>`
→ `<canvas id="score-canvas" ...>`

Ensure parent has class `chart-container` (or add it).

**Step 2: meteo_dashboard.html — remove canvas attrs**

Line 55: `<canvas id="meteo-forecast-canvas" width="900" height="260" style="width:100%;max-width:900px;" ...>`
→ `<canvas id="meteo-forecast-canvas" ...>`

Ensure parent has `chart-container` class.

**Step 3: race_strategy.html — remove canvas attrs**

Line 105: `<canvas id="rs-lap-canvas" width="900" height="280" style="width:100%;max-width:900px;" ...>`
→ `<canvas id="rs-lap-canvas" ...>`

Ensure parent has `chart-container` class.

**Step 4: session_detail.html — remove hardcoded dimensions**

Line 240: `<canvas id="fingerprint-radar" width="380" height="380" class="chart-canvas" ...>`
→ `<canvas id="fingerprint-radar" class="chart-canvas" ...>`

Ensure parent has `chart-container chart-container--square` classes.

Line 519: `<canvas id="pit-window-chart" width="560" height="280" class="chart-canvas" ...>`
→ `<canvas id="pit-window-chart" class="chart-canvas" ...>`

Ensure parent has `chart-container` class.

**Step 5: weight_simulator.html — remove canvas attrs**

Line 76: `<canvas id="ws-scenarios-canvas" width="900" height="300" style="width:100%;max-width:900px;" ...>`
→ `<canvas id="ws-scenarios-canvas" ...>`

Ensure parent has `chart-container` class.

**Step 6: Verify canvases still render**

Run app. Check dev plan, meteo, race strategy, session detail (fingerprint + pit window), weight simulator pages.
Expected: Canvases render correctly (JS reads parent size), filling their container.

**Step 7: Commit**

```bash
git add telemetry_tool/web/templates/dev_plan.html telemetry_tool/web/templates/meteo_dashboard.html telemetry_tool/web/templates/race_strategy.html telemetry_tool/web/templates/session_detail.html telemetry_tool/web/templates/weight_simulator.html
git commit -m "feat(responsive): remove hardcoded canvas dimensions from templates"
```

---

### Task 11: Add Table Scroll Wrappers to Templates

**Files:**
- Modify: All templates with `<table` tags (see list below)

**Step 1: Add `.table-scroll-wrapper` CSS to main.css**

Add after the existing table styles:
```css
/* ── Table scroll wrapper for responsive tables ── */
.table-scroll-wrapper {
    width: 100%;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    border-radius: var(--radius-sm);
}
.table-scroll-wrapper table {
    min-width: 600px;
    width: 100%;
}
```

**Step 2: Wrap HTML tables in templates**

For each template with a `<table>` in HTML (not JS-generated), wrap with `<div class="table-scroll-wrapper">`:

Templates to modify (HTML tables only):
- `analyze.html:289`
- `dashboard.html:110`
- `data_health.html:50`
- `driver_profile.html:233`
- `kart_detail.html:64`
- `leaderboard.html:40`
- `race_strategy/detail.html:66,153,187`
- `race_strategy/index.html:44`
- `race_strategy/live.html:98`
- `race_strategy/summary.html:99,128,171`
- `session_detail.html:790`
- `session_list.html:22`
- `track_detail.html:215,319`
- `weekend_detail.html:89,166,211`
- `weekend_form.html:111`

Pattern for each:
```html
<!-- FROM -->
<table class="data-table striped">
<!-- TO -->
<div class="table-scroll-wrapper">
<table class="data-table striped">
...
</table>
</div>
```

**Step 3: Handle JS-generated tables**

For tables generated in JS (dashboard_view.html, dev_plan.html, rival_comparison.html, race_strategy.html, session_detail.html JS blocks, setup_tracker.html, weather_analysis.html, weight_simulator.html) — wrap the JS-generated HTML string:

Change JS patterns like:
```javascript
html += '<table class="data-table">';
```
to:
```javascript
html += '<div class="table-scroll-wrapper"><table class="data-table">';
// ... at the end of table:
html += '</table></div>';
```

**Step 4: Verify table scrolling**

Run app. Check any page with a wide table (session list, leaderboard). Narrow the browser to 360px.
Expected: Table scrolls horizontally, rest of page layout stays intact.

**Step 5: Commit**

```bash
git add telemetry_tool/web/static/css/main.css telemetry_tool/web/templates/
git commit -m "feat(responsive): add horizontal scroll wrappers to all data tables"
```

---

### Task 12: Create ResizeObserver Utility

**Files:**
- Create: `telemetry_tool/web/static/js/resize_observer.js`

**Step 1: Write the utility**

```javascript
/**
 * Global ResizeObserver for canvas chart containers.
 * Watches all .chart-container elements and calls canvas.__redraw()
 * when the container resizes. Batches redraws via requestAnimationFrame.
 */
(function() {
    'use strict';

    var pending = new Set();
    var rafId = null;

    function flushRedraws() {
        pending.forEach(function(canvas) {
            if (typeof canvas.__redraw === 'function') {
                try {
                    canvas.__redraw();
                } catch (e) {
                    console.warn('[ResizeObserver] redraw failed for', canvas.id, e);
                }
            }
        });
        pending.clear();
        rafId = null;
    }

    var ro = new ResizeObserver(function(entries) {
        for (var i = 0; i < entries.length; i++) {
            var canvases = entries[i].target.querySelectorAll('canvas');
            for (var j = 0; j < canvases.length; j++) {
                pending.add(canvases[j]);
            }
        }
        if (!rafId) {
            rafId = requestAnimationFrame(flushRedraws);
        }
    });

    function init() {
        var containers = document.querySelectorAll('.chart-container');
        for (var i = 0; i < containers.length; i++) {
            ro.observe(containers[i]);
        }
        /* Also observe GPS map, corner replay, viz containers */
        var extras = document.querySelectorAll('.gps-map, .cr-viewport, .viz-container, .viz-chart-container');
        for (var j = 0; j < extras.length; j++) {
            ro.observe(extras[j]);
        }
    }

    window.TelemetryResize = {
        observe: function(el) { ro.observe(el); },
        unobserve: function(el) { ro.unobserve(el); },
        init: init
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
```

**Step 2: Verify file created**

Run: `ls telemetry_tool/web/static/js/resize_observer.js`
Expected: File exists.

**Step 3: Commit**

```bash
git add telemetry_tool/web/static/js/resize_observer.js
git commit -m "feat(responsive): add ResizeObserver utility for canvas redraws"
```

---

### Task 13: Wire Chart JS Files to `__redraw`

**Files:**
- Modify: `telemetry_tool/web/static/js/trend_chart.js`
- Modify: `telemetry_tool/web/static/js/fingerprint_chart.js`
- Modify: `telemetry_tool/web/static/js/brake_scatter.js`
- Modify: `telemetry_tool/web/static/js/consistency_heatmap.js`
- Modify: `telemetry_tool/web/static/js/throttle_heatmap.js`
- Modify: `telemetry_tool/web/static/js/gg_diagram.js`
- Modify: `telemetry_tool/web/static/js/gg_explorer.js`
- Modify: `telemetry_tool/web/static/js/corner_replay_map.js`
- Modify: `telemetry_tool/web/static/js/corner_replay_cockpit.js`
- Modify: `telemetry_tool/web/static/js/speed_trace_zoom.js`
- Modify: `telemetry_tool/web/static/js/gps_trace.js`
- Modify: `telemetry_tool/web/static/js/track_map.js`
- Modify: `telemetry_tool/web/static/js/pit_window_chart.js`
- Modify: `telemetry_tool/web/static/js/stint_chart.js`
- Modify: `telemetry_tool/web/static/js/sector_chart.js`
- Modify: `telemetry_tool/web/static/js/lap_distribution.js`
- Modify: `telemetry_tool/web/static/js/lap_overlay.js`
- Modify: `telemetry_tool/web/static/js/cross_session.js`
- Modify: `telemetry_tool/web/static/js/corner_map_view.js`
- Modify: `telemetry_tool/web/static/js/speed_profile.js`
- Modify: `telemetry_tool/web/static/js/weather_chart.js`
- Modify: `telemetry_tool/web/static/js/fatigue_chart.js`
- Modify: `telemetry_tool/web/static/js/energy_balance.js`
- Modify: `telemetry_tool/web/static/js/workload_chart.js`
- Modify: `telemetry_tool/web/static/js/tyre_chart.js`
- Modify: `telemetry_tool/web/static/js/driving_style.js`
- Modify: `telemetry_tool/web/static/js/pace_predictor.js`
- Modify: `telemetry_tool/web/static/js/pace_simulator.js`
- Modify: `telemetry_tool/web/static/js/track_evolution.js`
- Modify: `telemetry_tool/web/static/js/progression.js`
- Modify: `telemetry_tool/web/static/js/session_timeline.js`
- Modify: `telemetry_tool/web/static/js/visualize.js`
- Modify: `telemetry_tool/web/static/js/race_strategy.js`
- Modify: `telemetry_tool/web/static/js/race_strategy_live.js`
- Modify: `telemetry_tool/web/static/js/lap_progress.js`
- Modify: `telemetry_tool/web/static/js/corner_mastery.js`
- Modify: `telemetry_tool/web/static/js/comparison.js`
- Modify: `telemetry_tool/web/static/js/comparison_matrix.js`
- Modify: `telemetry_tool/web/static/js/rival_chart.js`
- Modify: `telemetry_tool/web/static/js/summary_report.js`

**Strategy:** For each chart JS file, find the main render/draw function and the canvas element reference. After the initial draw call, add `canvas.__redraw = () => drawFunction(canvas, data);`.

**Step 1: Open each file, identify the draw function and canvas ref**

For each file:
1. Read the file
2. Find the main draw/render function name
3. Find where the canvas element is obtained (e.g., `document.getElementById(...)`)
4. Find where the draw function is first called with data
5. Add `canvas.__redraw = function() { drawFunctionName(currentArgs); };` immediately after that call

**Pattern example for `trend_chart.js`:**
```javascript
// After the line that calls the draw function:
// drawTrendChart(canvas, data);
// Add:
canvas.__redraw = function() { drawTrendChart(canvas, data); };
```

**Step 2: Handle files where data is fetched asynchronously**

Some charts fetch data via AJAX and then draw. The `__redraw` registration should happen inside the callback, after the first draw, so it captures the data reference:

```javascript
fetch('/api/data').then(function(resp) { return resp.json(); }).then(function(data) {
    drawChart(canvas, data);
    canvas.__redraw = function() { drawChart(canvas, data); };
});
```

**Step 3: Handle files with multiple canvases**

Files like `visualize.js`, `gg_explorer.js`, `comparison.js` may manage multiple canvases. Register `__redraw` on each canvas separately.

**Step 4: Also register with TelemetryResize for dynamically created containers**

If any chart creates its container dynamically (AJAX-loaded content), add after creation:
```javascript
window.TelemetryResize && window.TelemetryResize.observe(container);
```

**Step 5: Verify resize redraws**

Run app. Open session detail. Resize window by dragging.
Expected: All charts redraw smoothly as window resizes. No visual glitches, no excessive redraws (check console for warnings).

**Step 6: Commit**

```bash
git add telemetry_tool/web/static/js/
git commit -m "feat(responsive): wire all chart JS files to ResizeObserver __redraw"
```

---

### Task 14: Add Script Tag to base.html

**Files:**
- Modify: `telemetry_tool/web/templates/base.html`

**Step 1: Add resize_observer.js script tag**

After line 198 (after `fetch_helper.js` include), before `toast.js`, add:

```html
<!-- Responsive resize observer for canvas charts -->
<script src="{{ url_for('static', filename='js/resize_observer.js') }}"></script>
```

**Step 2: Verify script loads**

Run app. Open browser console. Type `window.TelemetryResize`.
Expected: Returns object with `observe`, `unobserve`, `init` methods.

**Step 3: Commit**

```bash
git add telemetry_tool/web/templates/base.html
git commit -m "feat(responsive): include resize_observer.js in base template"
```

---

### Task 15: Full Visual Smoke Test

**Files:** None (testing only)

**Step 1: Test at 360px width**

Run app. Use browser DevTools to set viewport to 360px width.
Check: Dashboard, session list, session detail, race strategy, visualize, leaderboard.
Expected: Everything visible, grids stacked to 1 column, charts maintain aspect ratio, tables scroll horizontally, text readable.

**Step 2: Test at 768px width (tablet)**

Set viewport to 768px.
Expected: Grids show 2 columns where appropriate, charts well-proportioned, no overflow.

**Step 3: Test at 1440px width (standard desktop)**

Expected: Similar to current layout but with fluid spacing.

**Step 4: Test at 1920px+ (ultrawide)**

Expected: Content constrained by `clamp()` max values, not stretching to fill entire screen.

**Step 5: Test live resize**

Drag browser from 360px to full width continuously.
Expected: Smooth reflow, charts redraw without flicker, no layout jumps.

**Step 6: Test canvas redraws specifically**

Open session detail (fingerprint radar, GG diagram, speed trace). Resize window.
Expected: Canvas content redraws at new dimensions, no stretching/pixelation.

**Step 7: Fix any issues found**

If issues found, fix them and add to the relevant commit.

**Step 8: Final commit**

```bash
git add -A
git commit -m "fix(responsive): visual smoke test fixes"
```
