# Front-End Architecture Overhaul — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Complete engineering + visual overhaul of the telemetry web dashboard — fix P0 memory leaks, establish a formal token/component system, add ModuleManager lifecycle, responsive chart contract, NASA Eyes visual refresh, accessibility hardening, and performance CI.

**Architecture:** Enhanced CSS Variables (no build step), IIFE modules with init/destroy lifecycle protocol, mobile-first responsive with container queries, swipeable chart card stack on mobile with bottom drawer tooltips.

**Tech Stack:** Vanilla CSS + JS (no framework), Flask/Jinja2 templates, Leaflet maps, Canvas 2D charts, Playwright for visual regression, axe-core for a11y CI.

**Design doc:** `docs/plans/2026-02-26-frontend-architecture-overhaul-design.md`

---

## Phase 0: P0 Stabilization

> Fix critical memory leaks, uncleared intervals, unbounded caches, recursive rAF.

---

### Task 0.1: Create ModuleManager + LifecycleHelpers

**Files:**
- Create: `telemetry_tool/web/static/js/module_manager.js`
- Create: `telemetry_tool/web/static/js/lifecycle_helpers.js`

**Step 1: Create `module_manager.js`**

```js
/**
 * module_manager.js — Central lifecycle coordinator for UI modules.
 *
 * Every module registers via ModuleManager.register(name, { init, destroy, redraw }).
 * Pages call ModuleManager.activate([names]) to init a set and auto-destroy the previous set.
 */
(function () {
    'use strict';

    var _modules = {};
    var _active = [];

    window.ModuleManager = {
        register: function (name, mod) {
            if (!mod || typeof mod.init !== 'function' || typeof mod.destroy !== 'function') {
                console.warn('[ModuleManager] module "' + name + '" missing init or destroy');
            }
            _modules[name] = mod;
        },

        activate: function (names) {
            this.deactivateAll();
            for (var i = 0; i < names.length; i++) {
                var n = names[i];
                if (_modules[n] && typeof _modules[n].init === 'function') {
                    try {
                        _modules[n].init();
                    } catch (e) {
                        console.error('[ModuleManager] init failed:', n, e);
                    }
                    _active.push(n);
                }
            }
        },

        deactivateAll: function () {
            for (var i = 0; i < _active.length; i++) {
                var n = _active[i];
                if (_modules[n] && typeof _modules[n].destroy === 'function') {
                    try {
                        _modules[n].destroy();
                    } catch (e) {
                        console.warn('[ModuleManager] destroy failed:', n, e);
                    }
                }
            }
            _active = [];
        },

        isActive: function (name) {
            return _active.indexOf(name) !== -1;
        },

        getActive: function () {
            return _active.slice();
        },

        getRegistered: function () {
            return Object.keys(_modules);
        }
    };
})();
```

**Step 2: Create `lifecycle_helpers.js`**

```js
/**
 * lifecycle_helpers.js — Tracked listener/timer/rAF helpers for automatic cleanup.
 *
 * Usage:
 *   var lc = window.LifecycleHelpers.create();
 *   lc.addListener(el, 'click', handler);
 *   lc.addInterval(fn, 2000);
 *   lc.addRaf(frameCallback);
 *   // On destroy:
 *   lc.destroyAll();  // removes everything
 */
(function () {
    'use strict';

    window.LifecycleHelpers = {
        create: function () {
            var _listeners = [];
            var _timers = [];
            var _intervals = [];
            var _rafs = [];

            return {
                addListener: function (el, evt, fn, opts) {
                    el.addEventListener(evt, fn, opts);
                    _listeners.push({ el: el, evt: evt, fn: fn, opts: opts });
                },

                removeListener: function (el, evt, fn, opts) {
                    el.removeEventListener(evt, fn, opts);
                    for (var i = _listeners.length - 1; i >= 0; i--) {
                        var l = _listeners[i];
                        if (l.el === el && l.evt === evt && l.fn === fn) {
                            _listeners.splice(i, 1);
                            break;
                        }
                    }
                },

                addTimer: function (fn, ms) {
                    var id = setTimeout(fn, ms);
                    _timers.push(id);
                    return id;
                },

                clearTimer: function (id) {
                    clearTimeout(id);
                    var idx = _timers.indexOf(id);
                    if (idx !== -1) _timers.splice(idx, 1);
                },

                addInterval: function (fn, ms) {
                    var id = setInterval(fn, ms);
                    _intervals.push(id);
                    return id;
                },

                clearInterval: function (id) {
                    clearInterval(id);
                    var idx = _intervals.indexOf(id);
                    if (idx !== -1) _intervals.splice(idx, 1);
                },

                addRaf: function (fn) {
                    var id = requestAnimationFrame(fn);
                    _rafs.push(id);
                    return id;
                },

                cancelRaf: function (id) {
                    cancelAnimationFrame(id);
                    var idx = _rafs.indexOf(id);
                    if (idx !== -1) _rafs.splice(idx, 1);
                },

                destroyAll: function () {
                    var i;
                    for (i = 0; i < _listeners.length; i++) {
                        var l = _listeners[i];
                        l.el.removeEventListener(l.evt, l.fn, l.opts);
                    }
                    for (i = 0; i < _timers.length; i++) {
                        clearTimeout(_timers[i]);
                    }
                    for (i = 0; i < _intervals.length; i++) {
                        clearInterval(_intervals[i]);
                    }
                    for (i = 0; i < _rafs.length; i++) {
                        cancelAnimationFrame(_rafs[i]);
                    }
                    _listeners = [];
                    _timers = [];
                    _intervals = [];
                    _rafs = [];
                }
            };
        }
    };

    /**
     * sizeCanvas — Standard DPR-aware canvas sizing.
     * Replaces inconsistent ctx.scale / ctx.setTransform patterns.
     */
    window.sizeCanvas = function (canvas, w, h) {
        var dpr = window.devicePixelRatio || 1;
        canvas.width = w * dpr;
        canvas.height = h * dpr;
        canvas.style.width = w + 'px';
        canvas.style.height = h + 'px';
        var ctx = canvas.getContext('2d');
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        return ctx;
    };
})();
```

**Step 3: Add scripts to `base.html`**

In `telemetry_tool/web/templates/base.html`, add after line 201 (after Leaflet JS), before fetch_helper.js (line 204):

```html
<script src="{{ url_for('static', filename='js/lifecycle_helpers.js') }}"></script>
<script src="{{ url_for('static', filename='js/module_manager.js') }}"></script>
```

**Step 4: Verify scripts load**

Run: `python telemetry_tool/main.py --serve`
Open: `http://localhost:5000`
Open DevTools console, type: `window.ModuleManager`
Expected: Object with `register`, `activate`, `deactivateAll` methods
Type: `window.LifecycleHelpers.create()`
Expected: Object with `addListener`, `addInterval`, `addRaf`, `destroyAll` methods
Type: `window.sizeCanvas`
Expected: Function

**Step 5: Commit**

```bash
git add telemetry_tool/web/static/js/module_manager.js telemetry_tool/web/static/js/lifecycle_helpers.js telemetry_tool/web/templates/base.html
git commit -m "feat(ui): add ModuleManager lifecycle coordinator + LifecycleHelpers

Central module registry with init/destroy contract. Tracked listeners,
timers, intervals, and rAF for automatic cleanup. Standard sizeCanvas
helper for DPR-aware canvas sizing."
```

---

### Task 0.2: Fix `race_strategy_live.js` — 4 uncleared setInterval calls

**Files:**
- Modify: `telemetry_tool/web/static/js/race_strategy_live.js`
  - Line 659: `setInterval(fetchWeather, 300000)` — no clearInterval
  - Line 1364: `setInterval(fetchRivals, 10000)` — no clearInterval
  - Line 1367-1376: `setInterval(function() { updateTimer(); ... }, 1000)` — no clearInterval
  - Line 1379: `setInterval(fetchState, POLL_INTERVAL)` — no clearInterval

**Step 1: Add LifecycleHelpers at top of IIFE**

After line 5 (`(function() {`), add:
```js
    var _lc = window.LifecycleHelpers.create();
```

**Step 2: Replace all 4 setInterval calls with tracked versions**

Line 659 — change:
```js
setInterval(fetchWeather, 300000);
```
to:
```js
_lc.addInterval(fetchWeather, 300000);
```

Line 1364 — change:
```js
setInterval(fetchRivals, 10000);
```
to:
```js
_lc.addInterval(fetchRivals, 10000);
```

Line 1367 — change:
```js
setInterval(function() {
```
to:
```js
_lc.addInterval(function() {
```

Line 1379 — change:
```js
setInterval(fetchState, POLL_INTERVAL);
```
to:
```js
_lc.addInterval(fetchState, POLL_INTERVAL);
```

**Step 3: Add visibility-aware polling**

Before the closing `})();` (line 1381), add:
```js
    // Pause polling when tab is hidden to save CPU + server load
    _lc.addListener(document, 'visibilitychange', function () {
        if (document.hidden) {
            _lc.destroyAll();
        }
    });
```

Note: When tab becomes visible again, the page will reload naturally (no stale state risk).

**Step 4: Register with ModuleManager**

Before the closing `})();`, add:
```js
    window.ModuleManager.register('race_strategy_live', {
        init: function () { /* already auto-inits on load */ },
        destroy: function () { _lc.destroyAll(); }
    });
```

**Step 5: Verify**

Run: `python telemetry_tool/main.py --serve`
Navigate to any Race Strategy Live page.
Open DevTools console, type: `window.ModuleManager.getRegistered()`
Expected: Array includes `'race_strategy_live'`

**Step 6: Commit**

```bash
git add telemetry_tool/web/static/js/race_strategy_live.js
git commit -m "fix(race-live): tracked intervals + visibility-aware polling

Replace 4 bare setInterval calls with LifecycleHelpers.addInterval
for automatic cleanup. Pause all polling when tab is hidden."
```

---

### Task 0.3: Fix `chart_sync.js` — 7 uncleared addEventListener calls

**Files:**
- Modify: `telemetry_tool/web/static/js/chart_sync.js`
  - Line 290: `speedCanvas.addEventListener('mousemove', ...)`
  - Line 316: `speedCanvas.addEventListener('mouseleave', ...)`
  - Line 349: `speedCanvas.addEventListener('touchstart', ...)`
  - Line 350: `speedCanvas.addEventListener('touchmove', ...)`
  - Line 596: `lapCanvas.addEventListener('mousemove', ...)`
  - Line 625: `lapCanvas.addEventListener('mouseleave', ...)`

**Step 1: Add LifecycleHelpers at top of IIFE**

After the `'use strict';` line, add:
```js
    var _lc = window.LifecycleHelpers.create();
```

**Step 2: Replace all addEventListener calls with tracked versions**

For each `element.addEventListener(evt, fn, opts)` call, replace with `_lc.addListener(element, evt, fn, opts)`.

Example — line 290, change:
```js
speedCanvas.addEventListener('mousemove', function (e) {
```
to:
```js
_lc.addListener(speedCanvas, 'mousemove', function (e) {
```

Repeat for all 6 canvas listeners (lines 290, 316, 349, 350, 596, 625).

Keep the `DOMContentLoaded` listener (line 39) as-is — it's a one-time setup.

**Step 3: Add destroy function + register with ModuleManager**

Before the closing `})();` (line 671), add:
```js
    function destroy() {
        _lc.destroyAll();
        chartData = null;
        chartBounds = null;
        theoreticalData = null;
        _lastLaps = null;
        if (speedCanvas) {
            speedCanvas.width = 0;
            speedCanvas.height = 0;
        }
        if (lapCanvas) {
            lapCanvas.width = 0;
            lapCanvas.height = 0;
        }
    }

    window.ModuleManager.register('chart_sync', {
        init: function () { /* auto-inits on DOMContentLoaded */ },
        destroy: destroy
    });
```

**Step 4: Commit**

```bash
git add telemetry_tool/web/static/js/chart_sync.js
git commit -m "fix(chart-sync): tracked listeners + canvas cleanup on destroy

Replace bare addEventListener with LifecycleHelpers for automatic
cleanup. Release canvas GPU memory and data references on destroy."
```

---

### Task 0.4: Fix `corner_replay.js` — recursive rAF + resize leak

**Files:**
- Modify: `telemetry_tool/web/static/js/corner_replay.js`
  - Line 37: `var _rafId = null;` — rAF stored but never cancelled on destroy
  - Line 154: `window.addEventListener('resize', ...)` — never removed
  - Line 222: recursive `requestAnimationFrame` chain

**Step 1: Add LifecycleHelpers after `'use strict';`**

```js
    var _lc = window.LifecycleHelpers.create();
```

**Step 2: Replace resize listener (line 154)**

Change:
```js
window.addEventListener('resize', function () {
    clearTimeout(_resizeTimer);
    _resizeTimer = setTimeout(function () {
        if (_initialized) _renderFrame();
    }, 150);
});
```
to:
```js
_lc.addListener(window, 'resize', function () {
    clearTimeout(_resizeTimer);
    _resizeTimer = _lc.addTimer(function () {
        if (_initialized) _renderFrame();
    }, 150);
});
```

**Step 3: Guard recursive rAF (around line 222)**

In the `_animate` function, replace:
```js
_rafId = requestAnimationFrame(function (now) {
```
with:
```js
_rafId = _lc.addRaf(function (now) {
```

Add at the top of the rAF callback:
```js
if (!_state.playing) { _rafId = null; return; }
```

**Step 4: Add destroy to init pattern + register**

Add destroy function before closing `})();`:
```js
    function destroy() {
        _state.playing = false;
        _initialized = false;
        _lc.destroyAll();
        _state.traces = {};
        _state.cornerMetrics = {};
        _state.lapTimes = {};
    }

    // Update the existing window.CornerReplay export
```

Change line 41 from:
```js
window.CornerReplay = { init: init };
```
to:
```js
window.CornerReplay = { init: init, destroy: destroy };
window.ModuleManager.register('corner_replay', { init: function() {}, destroy: destroy });
```

**Step 5: Commit**

```bash
git add telemetry_tool/web/static/js/corner_replay.js
git commit -m "fix(corner-replay): guard recursive rAF + tracked resize listener

Add playing guard to rAF chain to prevent queue buildup on rapid
play/pause. Track resize listener and timers for automatic cleanup."
```

---

### Task 0.5: Fix `lap_overlay.js` — unbounded cache + leaked listeners

**Files:**
- Modify: `telemetry_tool/web/static/js/lap_overlay.js`
  - Line 26: `var lapDataCache = {};` — grows without limit
  - Line 27: `var deltaCache = {};` — grows without limit
  - Lines 48, 54, 58, 81, 152: addEventListener calls — never removed

**Step 1: Add LifecycleHelpers + LRU cap constant**

After `'use strict';`, add:
```js
    var _lc = window.LifecycleHelpers.create();
    var MAX_CACHE_ENTRIES = 20;
```

**Step 2: Add LRU eviction to lapDataCache**

Find where data is added to `lapDataCache` (the fetch callback). After the line that sets `lapDataCache[lapNum] = data`, add:
```js
var keys = Object.keys(lapDataCache);
if (keys.length > MAX_CACHE_ENTRIES) {
    delete lapDataCache[keys[0]];
}
```

Same for `deltaCache`.

**Step 3: Replace addEventListener calls**

Replace each `el.addEventListener(evt, fn)` with `_lc.addListener(el, evt, fn)` for lines 48, 54, 58, 81, 152.

**Step 4: Add destroy + register**

Before `})();`:
```js
    function destroy() {
        _lc.destroyAll();
        lapDataCache = {};
        deltaCache = {};
        selectedLaps = [];
        chartBounds = null;
        if (canvas) { canvas.width = 0; canvas.height = 0; }
    }

    window.ModuleManager.register('lap_overlay', {
        init: function () { /* auto-inits on DOMContentLoaded */ },
        destroy: destroy
    });
```

**Step 5: Commit**

```bash
git add telemetry_tool/web/static/js/lap_overlay.js
git commit -m "fix(lap-overlay): LRU cache cap + tracked listeners + destroy

Cap lapDataCache and deltaCache at 20 entries to prevent OOM on
large sessions. Track all listeners for automatic cleanup."
```

---

### Task 0.6: Fix `gg_explorer.js` — unbounded cache + 14 leaked listeners

**Files:**
- Modify: `telemetry_tool/web/static/js/gg_explorer.js`
  - Line 28: `lapDataCache: {}` in `_state` — unbounded
  - 14 addEventListener calls (lines 84, 90, 652, 675, 682, 845, 862, 872, 883, 891, 899, 943, 946, 971)

**Step 1: Add LifecycleHelpers + LRU constant**

After `'use strict';`:
```js
    var _lc = window.LifecycleHelpers.create();
    var MAX_LAP_CACHE = 20;
```

**Step 2: Replace all addEventListener calls with `_lc.addListener`**

Replace all 14 instances. The two `window.addEventListener('resize', ...)` calls at lines 90 and 971 should be deduplicated — keep only one, tracked.

**Step 3: Add LRU eviction**

After any line adding to `_state.lapDataCache`, add:
```js
var cacheKeys = Object.keys(_state.lapDataCache);
if (cacheKeys.length > MAX_LAP_CACHE) {
    delete _state.lapDataCache[cacheKeys[0]];
}
```

**Step 4: Replace resize setTimeout (line 973)**

Change from `setTimeout(...)` to `_lc.addTimer(...)`.

**Step 5: Add destroy + register**

Before `})();`:
```js
    function destroy() {
        _lc.destroyAll();
        _state.lapDataCache = {};
        _state.allGGData = null;
        _state.perLap = null;
        _state.selectedIdx = null;
        if (_ggCanvas) { _ggCanvas.width = 0; _ggCanvas.height = 0; }
        if (_mapCanvas) { _mapCanvas.width = 0; _mapCanvas.height = 0; }
    }

    window.ModuleManager.register('gg_explorer', {
        init: function () { /* auto-inits via tab:activate */ },
        destroy: destroy
    });
```

**Step 6: Commit**

```bash
git add telemetry_tool/web/static/js/gg_explorer.js
git commit -m "fix(gg-explorer): LRU cache cap + tracked 14 listeners + destroy

Cap lapDataCache at 20 entries. Track all event listeners including
wheel, mousedown, window mousemove/mouseup for automatic cleanup.
Deduplicate resize handler."
```

---

### Task 0.7: Fix `focus_mode.js` — tool references persist + 6 leaked listeners

**Files:**
- Modify: `telemetry_tool/web/static/js/focus_mode.js`
  - Lines 44-45: `_tools = {}`, `_rendered = {}` — never cleared
  - Lines 166, 190, 206, 429, 497, 561: addEventListener — never removed

**Step 1: Add LifecycleHelpers**

After `'use strict';`:
```js
    var _lc = window.LifecycleHelpers.create();
```

**Step 2: Replace addEventListener calls with `_lc.addListener`**

Replace all 6 instances (lines 166, 190, 206, 429, 497, 561).

**Step 3: Add proper close/destroy**

In the existing `close` function, add cleanup of rendered tools:
```js
Object.keys(_rendered).forEach(function (id) {
    if (_rendered[id] && typeof _rendered[id].destroy === 'function') {
        _rendered[id].destroy();
    }
});
_rendered = {};
```

Before `})();`:
```js
    function destroy() {
        close();
        _lc.destroyAll();
        if (_splitPane && typeof _splitPane.destroy === 'function') {
            _splitPane.destroy();
        }
        _splitPane = null;
    }

    window.ModuleManager.register('focus_mode', {
        init: function () { /* available globally, no init needed */ },
        destroy: destroy
    });
```

**Step 4: Commit**

```bash
git add telemetry_tool/web/static/js/focus_mode.js
git commit -m "fix(focus-mode): destroy rendered tools + tracked listeners

Call tool.destroy() on close for each rendered tool. Track all
event listeners for automatic cleanup. Clear SplitPane reference."
```

---

### Task 0.8: Fix `gps_trace.js` — Leaflet layers + 6 leaked listeners

**Files:**
- Modify: `telemetry_tool/web/static/js/gps_trace.js`
  - Lines 42-49: map, layers, marker — never destroyed
  - Lines 60, 83, 91, 103, 115: addEventListener — never removed
  - Line 281: Leaflet `.on()` event — never removed

**Step 1: Add LifecycleHelpers**

After `'use strict';`:
```js
    var _lc = window.LifecycleHelpers.create();
```

**Step 2: Replace addEventListener calls**

Replace lines 83, 91, 103, 115 with `_lc.addListener(...)`.
Keep line 60 (`DOMContentLoaded`) as-is.

**Step 3: Add destroy + register**

Before `})();`:
```js
    function destroy() {
        _lc.destroyAll();
        if (map) {
            map.remove();
            map = null;
        }
        traceLayer = null;
        marker = null;
        referenceLayer = null;
        bestLapLayer = null;
        cornerMarkersLayer = null;
        allLapsLayer = null;
        currentData = null;
    }

    window.ModuleManager.register('gps_trace', {
        init: function () { /* auto-inits on DOMContentLoaded */ },
        destroy: destroy
    });
```

**Step 4: Commit**

```bash
git add telemetry_tool/web/static/js/gps_trace.js
git commit -m "fix(gps-trace): Leaflet map.remove() + tracked listeners on destroy

Properly remove Leaflet map instance and all overlay layers. Track
change/toggle listeners for automatic cleanup."
```

---

### Task 0.9: Fix `visualize.js` — orchestrator with no cleanup

**Files:**
- Modify: `telemetry_tool/web/static/js/visualize.js`

**Step 1: Add LifecycleHelpers**

After `'use strict';`:
```js
    var _lc = window.LifecycleHelpers.create();
```

**Step 2: Track all addEventListener calls**

Search for all `addEventListener` in the file and replace with `_lc.addListener`.

**Step 3: Add destroy + register**

Before `})();`:
```js
    function destroy() {
        _lc.destroyAll();
        selectedLaps.clear();
    }

    window.ModuleManager.register('visualize', {
        init: function () { /* auto-inits */ },
        destroy: destroy
    });
```

**Step 4: Commit**

```bash
git add telemetry_tool/web/static/js/visualize.js
git commit -m "fix(visualize): tracked listeners + destroy for orchestrator module

Track all event listeners in the visualization workspace controller
for automatic cleanup when module is destroyed."
```

---

### Task 0.10: Smoke test all P0 fixes

**Step 1: Run the app**

```bash
python telemetry_tool/main.py --serve
```

**Step 2: Manual verification**

Open `http://localhost:5000`. Open DevTools Console.

1. Verify `window.ModuleManager.getRegistered()` returns at least:
   `['race_strategy_live', 'chart_sync', 'corner_replay', 'lap_overlay', 'gg_explorer', 'focus_mode', 'gps_trace', 'visualize']`

2. Navigate to a session detail page — check console for errors
3. Navigate to Race Strategy Live — check `_lc` intervals are tracked
4. Click around multiple pages — check for growing memory (Chrome Performance Monitor)
5. Toggle Focus Mode open/close — verify no console errors on close

**Step 3: Run existing tests**

```bash
pytest telemetry_tool/tests/ -x -q
```

Expected: All pass (JS changes don't affect Python tests, but verify server starts).

**Step 4: Commit verification note (if any fixes needed)**

---

## Phase 1: Token System + CSS Split

> Formalize `tokens.css`, split monolithic `main.css` into 7 focused files, add utility classes.

---

### Task 1.1: Create `tokens.css`

**Files:**
- Create: `telemetry_tool/web/static/css/tokens.css`

**Step 1: Create the file**

Write the full token system from the design doc (see `2026-02-26-frontend-architecture-overhaul-design.md`, Phase 1 section). The file contains ONLY CSS custom property definitions in `:root`, `:root[data-theme="light"]`, and the `@media (prefers-reduced-motion)` block.

Include the `@import url(...)` for Google Fonts at the top (moved from `main.css` line 5).

**Step 2: Commit**

```bash
git add telemetry_tool/web/static/css/tokens.css
git commit -m "feat(tokens): design token system — colors, spacing, typography, motion, z-index

Single source of truth for all visual variables. Dark + light themes,
reduced motion support, fluid spacing scale, data viz palette."
```

---

### Task 1.2: Create `utilities.css`

**Files:**
- Create: `telemetry_tool/web/static/css/utilities.css`

**Step 1: Create utility classes**

Extract from inline styles across templates. Include:

```css
/* ── Display ── */
.d-none { display: none; }
.d-block { display: block; }
.d-flex { display: flex; }
.d-grid { display: grid; }
.d-inline-flex { display: inline-flex; }

/* ── Flex ── */
.flex-1 { flex: 1; }
.flex-2 { flex: 2; }
.flex-wrap { flex-wrap: wrap; }
.flex-col { flex-direction: column; }
.items-center { align-items: center; }
.items-start { align-items: flex-start; }
.items-end { align-items: flex-end; }
.justify-center { justify-content: center; }
.justify-between { justify-content: space-between; }
.justify-end { justify-content: flex-end; }

/* ── Gap ── */
.gap-1 { gap: var(--space-1); }
.gap-2 { gap: var(--space-2); }
.gap-3 { gap: var(--space-3); }
.gap-4 { gap: var(--space-4); }
.gap-5 { gap: var(--space-5); }

/* ── Text ── */
.text-xs { font-size: var(--font-size-xs); }
.text-sm { font-size: var(--font-size-sm); }
.text-base { font-size: var(--font-size-base); }
.text-md { font-size: var(--font-size-md); }
.text-lg { font-size: var(--font-size-lg); }
.text-xl { font-size: var(--font-size-xl); }
.text-2xl { font-size: var(--font-size-2xl); }
.text-muted { color: var(--text-muted); }
.text-secondary { color: var(--text-secondary); }
.text-accent { color: var(--accent); }
.text-success { color: var(--success); }
.text-danger { color: var(--danger); }
.text-warning { color: var(--warning); }
.text-mono { font-family: var(--font-mono); }
.text-center { text-align: center; }
.text-right { text-align: right; }
.text-upper { text-transform: uppercase; letter-spacing: 0.05em; }
.font-medium { font-weight: var(--font-weight-medium); }
.font-semibold { font-weight: var(--font-weight-semibold); }
.font-bold { font-weight: var(--font-weight-bold); }
.truncate { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* ── Spacing ── */
.m-0 { margin: 0; }
.mt-1 { margin-top: var(--space-1); }
.mt-2 { margin-top: var(--space-2); }
.mt-3 { margin-top: var(--space-3); }
.mt-4 { margin-top: var(--space-4); }
.mb-1 { margin-bottom: var(--space-1); }
.mb-2 { margin-bottom: var(--space-2); }
.mb-3 { margin-bottom: var(--space-3); }
.mb-4 { margin-bottom: var(--space-4); }
.p-1 { padding: var(--space-1); }
.p-2 { padding: var(--space-2); }
.p-3 { padding: var(--space-3); }
.p-4 { padding: var(--space-4); }

/* ── Sizing ── */
.w-full { width: 100%; }
.max-w-sm { max-width: 350px; }
.max-w-md { max-width: 600px; }
.max-w-lg { max-width: 900px; }
.max-w-xl { max-width: 1200px; }

/* ── Overflow ── */
.overflow-auto { overflow: auto; }
.overflow-hidden { overflow: hidden; }
.overflow-y-auto { overflow-y: auto; }
.max-h-200 { max-height: 200px; }

/* ── Accessibility ── */
.sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
}
```

**Step 2: Commit**

```bash
git add telemetry_tool/web/static/css/utilities.css
git commit -m "feat(css): utility classes extracted from inline styles

Display, flex, gap, text, spacing, sizing, overflow, and sr-only
utilities mapped to design tokens."
```

---

### Task 1.3: Create `motion.css`

**Files:**
- Create: `telemetry_tool/web/static/css/motion.css`

**Step 1: Write animation presets + stagger system**

```css
/* ── Keyframes ── */
@keyframes fadeInUp {
    from { opacity: 0; transform: translateY(20px); }
    to { opacity: 1; transform: translateY(0); }
}
@keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
}
@keyframes spin {
    to { transform: rotate(360deg); }
}
@keyframes shimmer {
    0% { background-position: -200% 0; }
    100% { background-position: 200% 0; }
}
@keyframes pulseGlow {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
}
@keyframes slideUp {
    from { transform: translateY(100%); }
    to { transform: translateY(0); }
}
@keyframes slideDown {
    from { transform: translateY(-20px); opacity: 0; }
    to { transform: translateY(0); opacity: 1; }
}

/* ── Stagger fade-in ── */
.stagger-in > * {
    opacity: 0;
    animation: fadeInUp var(--duration-slow) var(--ease-out) forwards;
}
.stagger-in > *:nth-child(1) { animation-delay: 0ms; }
.stagger-in > *:nth-child(2) { animation-delay: 50ms; }
.stagger-in > *:nth-child(3) { animation-delay: 100ms; }
.stagger-in > *:nth-child(4) { animation-delay: 150ms; }
.stagger-in > *:nth-child(5) { animation-delay: 200ms; }
.stagger-in > *:nth-child(6) { animation-delay: 250ms; }
.stagger-in > *:nth-child(7) { animation-delay: 300ms; }
.stagger-in > *:nth-child(8) { animation-delay: 350ms; }
.stagger-in > *:nth-child(9) { animation-delay: 400ms; }
.stagger-in > *:nth-child(10) { animation-delay: 450ms; }
.stagger-in > *:nth-child(11) { animation-delay: 500ms; }
.stagger-in > *:nth-child(12) { animation-delay: 550ms; }

@media (prefers-reduced-motion: reduce) {
    .stagger-in > * {
        opacity: 1;
        animation: none;
    }
}

/* ── Transition presets ── */
.transition-colors {
    transition: color var(--duration-fast) var(--ease-out),
                background-color var(--duration-fast) var(--ease-out),
                border-color var(--duration-fast) var(--ease-out);
}
.transition-transform {
    transition: transform var(--duration-fast) var(--ease-out);
}
.transition-opacity {
    transition: opacity var(--duration-normal) var(--ease-out);
}
.transition-all {
    transition: all var(--duration-normal) var(--ease-out);
}
```

**Step 2: Commit**

```bash
git add telemetry_tool/web/static/css/motion.css
git commit -m "feat(motion): animation keyframes, stagger system, transition presets

Consolidate all keyframes (removing duplicates from main.css).
Stagger fade-in for up to 12 children. Reduced motion support."
```

---

### Task 1.4: Wire new CSS files into `base.html`

**Files:**
- Modify: `telemetry_tool/web/templates/base.html`

**Step 1: Add new CSS links**

After the existing `main.css` link (line 15), add:
```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/tokens.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/utilities.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/motion.css') }}">
```

Note: `tokens.css` MUST load before `main.css` so variables are available. Reorder to:
```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/tokens.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/main.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/utilities.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/motion.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/focus_mode.css') }}">
```

**Step 2: Verify**

Run: `python telemetry_tool/main.py --serve`
Open DevTools → Elements → inspect any element.
Check Computed tab → verify `--bg-void`, `--space-1`, `--duration-fast` tokens resolve.

**Step 3: Commit**

```bash
git add telemetry_tool/web/templates/base.html
git commit -m "feat(css): wire tokens.css, utilities.css, motion.css into base template

Load order: tokens → main → utilities → motion → focus_mode.
Tokens must load first so all variables resolve."
```

---

### Task 1.5: Migrate `main.css` :root to reference `tokens.css`

**Files:**
- Modify: `telemetry_tool/web/static/css/main.css`

**Step 1: Remove the @import Google Fonts line (line 5)**

Already moved to `tokens.css`.

**Step 2: Replace :root block (lines 7-68) with token references**

Change the existing `:root { ... }` block to reference the new tokens. For backward compatibility during migration, keep the OLD variable names as aliases:

```css
:root {
    /* ── Legacy aliases → new tokens (remove after migration) ── */
    --bg-card:       var(--bg-secondary);
    --surface:       var(--bg-tertiary);
    --surface-light: var(--bg-hover);
    --card-bg:       var(--bg-secondary);
    --border-light:  var(--border-subtle);
    --green-dim:     #059669;
    --accent-dim:    var(--accent-hover);

    /* These are now defined in tokens.css:
       --bg-primary, --bg-secondary, --bg-tertiary, --bg-hover,
       --text-primary, --text-secondary, --text-muted,
       --accent, --accent-glow, --border,
       --green, --yellow, --red, --blue, --purple,
       --danger, --warning, --success, --info,
       --radius, --radius-sm, --radius-xs, --radius-lg, --radius-pill,
       --shadow, --shadow-glow, --transition,
       --font-mono, --font-sans,
       --glass-bg, --glass-border, --glass-blur,
       --space-xs through --space-xl
    */
}
```

**Step 3: Replace light theme block (lines 70-108) with alias-only overrides**

The full light theme is in `tokens.css`. Keep only legacy aliases:

```css
:root[data-theme="light"] {
    /* Legacy aliases for light mode */
    --bg-card:       var(--bg-secondary);
    --surface:       var(--bg-tertiary);
    --surface-light: var(--bg-hover);
    --card-bg:       var(--bg-secondary);
    --border-light:  var(--border-subtle);
}
```

**Step 4: Remove duplicate `@keyframes spin` (lines 1912-1914 and 4537-4540)**

Both are now in `motion.css`. Delete both occurrences.

**Step 5: Remove `.sr-only` (lines 198-208)**

Now in `utilities.css`. Delete from `main.css`.

**Step 6: Verify the app still renders correctly**

Run: `python telemetry_tool/main.py --serve`
Check dashboard, session detail, race strategy pages. All colors/spacing/fonts should look identical.

**Step 7: Commit**

```bash
git add telemetry_tool/web/static/css/main.css
git commit -m "refactor(css): migrate main.css :root to reference tokens.css

Replace inline variable definitions with token references. Add legacy
aliases for backward compatibility. Remove duplicate keyframes and
sr-only (moved to motion.css and utilities.css)."
```

---

### Task 1.6: Add light mode to feature CSS files

**Files:**
- Modify: `telemetry_tool/web/static/css/corner_replay.css`
- Modify: `telemetry_tool/web/static/css/focus_mode.css`
- Modify: `telemetry_tool/web/static/css/gg_explorer.css`
- Modify: `telemetry_tool/web/static/css/speed_trace_zoom.css`

**Step 1: For each file, find hardcoded colors and replace with token variables**

Search each file for:
- Hardcoded hex colors (`#1a1d26`, `#0f1219`, etc.) → replace with `var(--bg-*)` tokens
- Hardcoded `rgba(255, 255, 255, ...)` → replace with `var(--border)` or `var(--text-*)`
- Hardcoded `rgba(0, 0, 0, ...)` → replace with `var(--shadow-*)` or `var(--bg-*)`

Since these files already use some `var(--*)` references, the light theme will automatically work once hardcoded colors are replaced.

**Step 2: Add `:root[data-theme="light"]` overrides for any remaining module-specific variables**

If a file defines custom variables (e.g., `.cr-section { --cr-bg: #1a1d26; }`), add light-mode counterparts.

**Step 3: Test light mode**

Switch theme in browser. Verify all 4 feature modules render correctly in light mode.

**Step 4: Commit**

```bash
git add telemetry_tool/web/static/css/corner_replay.css telemetry_tool/web/static/css/focus_mode.css telemetry_tool/web/static/css/gg_explorer.css telemetry_tool/web/static/css/speed_trace_zoom.css
git commit -m "fix(theme): add light mode support to 4 feature CSS files

Replace hardcoded colors with token variables in corner_replay,
focus_mode, gg_explorer, and speed_trace_zoom. All modules now
support both dark and light themes."
```

---

### Task 1.7: Enforce z-index scale

**Files:**
- Modify: `telemetry_tool/web/static/css/focus_mode.css` — line 8: `z-index: 5000`
- Modify: `telemetry_tool/web/static/css/gg_explorer.css` — tooltip z-index
- Modify: `telemetry_tool/web/static/css/speed_trace_zoom.css` — z-index 3, 4

**Step 1: Replace non-compliant z-index values**

`focus_mode.css` line 8: Change `z-index: 5000` to `z-index: var(--z-modal)` (5000 in tokens — now documented).

`gg_explorer.css` tooltip: Change to `z-index: var(--z-overlay)`.

`speed_trace_zoom.css`: Change z-index 3 and 4 to `z-index: var(--z-base)` or `var(--z-elevated)`.

**Step 2: In `main.css`, replace all hardcoded z-index values with token references**

Search for `z-index:` and replace each with the appropriate `var(--z-*)` token.

**Step 3: Commit**

```bash
git add telemetry_tool/web/static/css/focus_mode.css telemetry_tool/web/static/css/gg_explorer.css telemetry_tool/web/static/css/speed_trace_zoom.css telemetry_tool/web/static/css/main.css
git commit -m "fix(z-index): enforce token-based z-index scale across all CSS

Replace all hardcoded z-index values with --z-* tokens. No z-index
value outside the documented scale is allowed."
```

---

## Phase 2: JS Lifecycle Migration (remaining modules)

> Migrate all 55 JS modules to the lifecycle protocol. Phase 0 covered the 8 critical ones. This phase covers the remaining 47.

---

### Task 2.1: Batch migrate small chart modules (12 files)

**Files to modify** (each gets the same pattern: add `_lc`, replace `addEventListener`, add `destroy`, register):
- `brake_scatter.js`
- `consistency_heatmap.js`
- `energy_balance.js`
- `fatigue_chart.js`
- `fingerprint_chart.js`
- `lap_distribution.js`
- `lap_progress.js`
- `pace_predictor.js`
- `sector_chart.js`
- `speed_profile.js`
- `throttle_heatmap.js`
- `workload_chart.js`

**Pattern for each file:**

1. Add `var _lc = window.LifecycleHelpers.create();` after `'use strict';`
2. Replace each `addEventListener` with `_lc.addListener`
3. Replace each `setTimeout` with `_lc.addTimer`
4. Add before `})();`:
```js
    function destroy() {
        _lc.destroyAll();
        // null out any canvas references
    }
    window.ModuleManager.register('[module_name]', {
        init: function () {},
        destroy: destroy
    });
```
5. Commit each batch of 4 files.

**Commits:**
```bash
git commit -m "fix(lifecycle): migrate brake_scatter, consistency_heatmap, energy_balance, fatigue_chart"
git commit -m "fix(lifecycle): migrate fingerprint_chart, lap_distribution, lap_progress, pace_predictor"
git commit -m "fix(lifecycle): migrate sector_chart, speed_profile, throttle_heatmap, workload_chart"
```

---

### Task 2.2: Batch migrate medium modules (12 files)

**Files:**
- `corner_replay_cockpit.js`
- `corner_replay_controls.js`
- `corner_replay_map.js`
- `corner_map_view.js`
- `corner_mastery.js`
- `cross_session.js`
- `driving_style.js`
- `pace_simulator.js`
- `progression.js`
- `session_timeline.js`
- `track_evolution.js`
- `trend_chart.js`

Same pattern as Task 2.1. Commit in batches of 4.

---

### Task 2.3: Batch migrate remaining modules (23 files)

**Files:**
- `analyze_form.js` (has its own `clearInterval` at lines 794, 817 — verify cleanup)
- `comparison.js`
- `comparison_matrix.js`
- `context_menu.js`
- `corner_picker_map.js`
- `driver_editor.js`
- `gg_diagram.js`
- `pit_window_chart.js`
- `race_strategy.js`
- `rival_chart.js`
- `session_badges.js`
- `session_editor.js`
- `speed_trace_zoom.js`
- `split_pane.js` (already has cleanup — verify and register)
- `stint_chart.js`
- `summary_report.js`
- `theme.js` (global — register but don't destroy)
- `toast.js` (global — register but don't destroy)
- `track_map.js`
- `tyre_chart.js`
- `weather_chart.js`
- `fetch_helper.js` (global utility — no lifecycle needed)
- `resize_observer.js` (global utility — no lifecycle needed)

Notes:
- `fetch_helper.js`, `resize_observer.js`, `theme.js`, and `toast.js` are global utilities. Register them with ModuleManager but with no-op `destroy` (they persist across all pages).
- `split_pane.js` already has a `destroy` pattern — just register it.
- `analyze_form.js` already uses `clearInterval` in some paths — verify all paths are covered.

Commit in batches of 6.

---

## Phase 3: Responsive System + Chart Contract

---

### Task 3.1: Create `charts.css` with ChartFrame component

**Files:**
- Create: `telemetry_tool/web/static/css/charts.css`

**Step 1: Write ChartFrame CSS**

Full content includes:
- `.chart-frame` — container with `container-type: inline-size`
- `.chart-frame__header` — title + controls bar
- `.chart-frame__canvas` — flex:1 canvas area
- `.chart-frame--loading` — skeleton shimmer overlay
- `.chart-frame--empty` — centered message + action button
- `.chart-frame--error` — error message + retry
- `.chart-stack` — grid layout, mobile scroll-snap
- `.chart-drawer` — mobile bottom drawer for tooltip data
- `.chart-dot-nav` — dot indicators for mobile card position
- Container query rules for legend/axis hiding at small sizes

**Step 2: Add to `base.html`**

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/charts.css') }}">
```

**Step 3: Commit**

```bash
git add telemetry_tool/web/static/css/charts.css telemetry_tool/web/templates/base.html
git commit -m "feat(charts): ChartFrame component + mobile card stack + bottom drawer

Container-query-aware chart wrapper with loading/empty/error states.
Mobile scroll-snap card stack. Bottom drawer tooltip for touch."
```

---

### Task 3.2: Create `chart_frame.js` — JS companion for ChartFrame

**Files:**
- Create: `telemetry_tool/web/static/js/chart_frame.js`

**Step 1: Write ChartFrame JS**

Provides:
- `window.ChartFrame.wrap(canvasId, options)` — wraps existing canvas in ChartFrame markup
- `window.ChartFrame.setState(id, 'loading'|'empty'|'error'|'ready')` — state transitions
- `window.ChartFrame.openDrawer(html)` — open mobile bottom drawer with content
- `window.ChartFrame.closeDrawer()` — close drawer
- ResizeObserver integration — auto-calls `canvas.__redraw()` on frame resize
- Dot navigation for mobile card stack — updates active dot on scroll

**Step 2: Add to `base.html`**

```html
<script src="{{ url_for('static', filename='js/chart_frame.js') }}"></script>
```

**Step 3: Commit**

```bash
git add telemetry_tool/web/static/js/chart_frame.js telemetry_tool/web/templates/base.html
git commit -m "feat(charts): ChartFrame JS companion — state management, drawer, dot nav

Wrap existing canvases in ChartFrame containers. State transitions
for loading/empty/error/ready. Mobile bottom drawer. Dot pagination."
```

---

### Task 3.3: Create `motion.js` — micro-motion helpers

**Files:**
- Create: `telemetry_tool/web/static/js/motion.js`

**Step 1: Write micro-motion utilities**

```js
/**
 * motion.js — Micro-motion utilities.
 *
 * Provides:
 *   window.Motion.tickUp(el, target, duration)  — animate number 0→target
 *   window.Motion.staggerIn(parentEl)           — trigger stagger-in class
 *   window.Motion.drawLine(ctx, points, duration) — progressive line draw
 */
```

Includes reduced-motion check (`window.matchMedia('(prefers-reduced-motion: reduce)').matches`).

**Step 2: Add to `base.html`**

**Step 3: Commit**

```bash
git add telemetry_tool/web/static/js/motion.js telemetry_tool/web/templates/base.html
git commit -m "feat(motion): tick-up numbers, stagger-in, progressive line draw

GPU-accelerated micro-motion with prefers-reduced-motion support.
All animations under 400ms, never block interaction."
```

---

### Task 3.4: Update `resize_observer.js` to also watch `.chart-frame`

**Files:**
- Modify: `telemetry_tool/web/static/js/resize_observer.js`

**Step 1: Add `.chart-frame` to observed selectors (line 39 area)**

In the `init()` function, add `.chart-frame` to the selectors:
```js
var containers = document.querySelectorAll('.chart-container, .chart-frame');
```

**Step 2: Commit**

```bash
git add telemetry_tool/web/static/js/resize_observer.js
git commit -m "fix(resize): observe .chart-frame containers for canvas redraw"
```

---

## Phase 4: Visual Refresh — Dashboard

---

### Task 4.1: Redesign KPI cards

**Files:**
- Modify: `telemetry_tool/web/templates/dashboard.html`
- Modify: `telemetry_tool/web/static/css/main.css` (stat-card section)

**Step 1: Update `.stat-card` CSS to new KPI card design**

Replace existing `.stat-card` styles with the new `.kpi-card` design from the design doc. Add instrument glow line (`::before`), monospace values, delta indicators, hover lift + glow.

**Step 2: Update dashboard template**

Add `stagger-in` class to the stats grid. Add `data-target` attributes for tick-up animation. Add delta markup.

**Step 3: Wire tick-up animation**

In the dashboard template's `{% block scripts %}`, add:
```html
<script>
document.querySelectorAll('.kpi-card__value[data-target]').forEach(function(el) {
    window.Motion.tickUp(el, parseFloat(el.dataset.target), 600);
});
</script>
```

**Step 4: Verify at 360px, 768px, 1920px**

**Step 5: Commit**

```bash
git commit -m "feat(dashboard): NASA Eyes KPI cards with tick-up animation

Instrument glow line, monospace values, delta indicators, hover lift.
Stagger fade-in on load. Tick-up animation for score numbers."
```

---

### Task 4.2: Redesign dashboard session table

**Files:**
- Modify: `telemetry_tool/web/templates/dashboard.html`
- Modify: `telemetry_tool/web/static/css/main.css` (table section)

**Step 1: Add skeleton loading state to session table**

Skeleton rows visible on initial load, replaced when data renders.

**Step 2: Add empty state**

If no sessions, show empty hero with action button.

**Step 3: Style table with token-based colors**

Ensure all hardcoded colors in table styles use tokens.

**Step 4: Commit**

```bash
git commit -m "feat(dashboard): session table with skeleton loading + empty state"
```

---

### Task 4.3: Add quick charts section to dashboard

**Files:**
- Modify: `telemetry_tool/web/templates/dashboard.html`

**Step 1: Add ChartFrame containers for score trend + lap times sparklines**

Two `.chart-frame` containers in a `.chart-stack` grid.

**Step 2: Create `dashboard_charts.js` for sparkline rendering**

Register with ModuleManager. Use `sizeCanvas()` helper.

**Step 3: Commit**

```bash
git commit -m "feat(dashboard): score trend + lap times quick charts in ChartFrame"
```

---

### Task 4.4: Dashboard responsive polish

**Files:**
- Modify: `telemetry_tool/web/templates/dashboard.html`
- Modify: `telemetry_tool/web/static/css/main.css`

**Step 1: Test and fix at all target viewports**

320px, 360px, 768px, 1024px, 1440px, 1920px, 2560px.

**Step 2: Ensure mobile card stack for charts**

**Step 3: Verify light mode**

**Step 4: Commit**

```bash
git commit -m "fix(dashboard): responsive polish at all target viewports + light mode"
```

---

## Phase 5: Visual Refresh — Race Strategy Live

---

### Task 5.1: Redesign race clock + progress bar

**Files:**
- Modify: `telemetry_tool/web/templates/race_strategy/live.html`
- Modify: `telemetry_tool/web/static/css/race_strategy.css`

**Step 1: Add `.race-progress` bar with gradient fill**

**Step 2: Add connection status dot with pulse animation**

**Step 3: Style clock with monospace font + large display**

**Step 4: Commit**

```bash
git commit -m "feat(race-live): race clock, progress bar, connection status indicator"
```

---

### Task 5.2: Redesign position board

**Files:**
- Modify: `telemetry_tool/web/templates/race_strategy/live.html`
- Modify: `telemetry_tool/web/static/css/race_strategy.css`
- Modify: `telemetry_tool/web/static/js/race_strategy_live.js`

**Step 1: Add driver color swatches (`--driver-color` per row via inline variable)**

**Step 2: Add `.position-row--self` highlight for user's position**

**Step 3: Add gap time formatting with +/- prefix**

**Step 4: Commit**

```bash
git commit -m "feat(race-live): position board with driver colors and gap formatting"
```

---

### Task 5.3: Redesign alerts panel

**Files:**
- Modify: `telemetry_tool/web/templates/race_strategy/live.html`
- Modify: `telemetry_tool/web/static/css/race_strategy.css`

**Step 1: Add pulse-glow animation for new alerts**

**Step 2: Add severity-based left border coloring (warning/danger/info)**

**Step 3: Add dismiss button per alert**

**Step 4: Commit**

```bash
git commit -m "feat(race-live): alert panel with severity colors and pulse-glow"
```

---

### Task 5.4: Wrap race live charts in ChartFrame

**Files:**
- Modify: `telemetry_tool/web/templates/race_strategy/live.html`
- Modify: `telemetry_tool/web/static/js/race_strategy_live.js`

**Step 1: Wrap pace analysis charts in `.chart-frame` containers**

**Step 2: Add loading skeletons during initial fetch**

**Step 3: Mobile: stack charts as swipeable cards**

**Step 4: Commit**

```bash
git commit -m "feat(race-live): ChartFrame wrappers with loading skeletons + mobile stack"
```

---

### Task 5.5: Remove `!important` from `race_strategy.css`

**Files:**
- Modify: `telemetry_tool/web/static/css/race_strategy.css`

**Step 1: Find all 40+ `!important` declarations**

**Step 2: Fix each by increasing specificity naturally or restructuring selectors**

**Step 3: Verify no visual regressions**

**Step 4: Commit**

```bash
git commit -m "fix(race-strategy): remove all !important declarations

Refactor specificity conflicts by restructuring selectors. No visual
changes — all styles produce identical output."
```

---

## Phase 6: Component Library

---

### Task 6.1: Standardize button system

**Files:**
- Modify: `telemetry_tool/web/static/css/main.css` (button section, ~lines 473-527)

**Step 1: Replace existing `.btn` styles with the design doc button system**

Include: `.btn`, `.btn--primary`, `.btn--ghost`, `.btn--danger`, `.btn--sm`, `.btn--lg`, `.btn:disabled`, `.btn--loading`, `.btn--icon`.

Ensure `min-height: var(--touch-min)` (44px) on all buttons.

**Step 2: Commit**

```bash
git commit -m "feat(components): standardized button system with touch targets + loading state"
```

---

### Task 6.2: Standardize badge system

**Files:**
- Modify: `telemetry_tool/web/static/css/main.css` (badge section, ~lines 1102-1140)

**Step 1: Replace hardcoded badge colors with token references**

**Step 2: Add consistent padding and min-height for touch targets**

**Step 3: Commit**

```bash
git commit -m "feat(components): token-based badge system with consistent sizing"
```

---

### Task 6.3: Standardize card component

**Files:**
- Modify: `telemetry_tool/web/static/css/main.css`

**Step 1: Add `.card`, `.card--glass`, `.card--elevated`, `.card--interactive` classes**

**Step 2: Add `.card__header`, `.card__body`, `.card__footer` elements**

**Step 3: Commit**

```bash
git commit -m "feat(components): card component with glass, elevated, interactive variants"
```

---

### Task 6.4: Standardize table component

**Files:**
- Modify: `telemetry_tool/web/static/css/main.css` (table section, ~lines 799-1088)

**Step 1: Replace hardcoded values with tokens**

**Step 2: Add `.data-table--skeleton` for loading state**

**Step 3: Add horizontal scroll indicators with `.table-wrap`**

**Step 4: Commit**

```bash
git commit -m "feat(components): token-based table with skeleton loading + scroll indicators"
```

---

### Task 6.5: Standardize form controls

**Files:**
- Modify: `telemetry_tool/web/static/css/main.css` (form section, ~lines 1725-1882)

**Step 1: Ensure all form inputs have `min-height: var(--touch-min)`**

**Step 2: Standardize focus ring to `outline: 2px solid var(--accent); outline-offset: 2px;`**

**Step 3: Replace hardcoded colors with tokens**

**Step 4: Commit**

```bash
git commit -m "feat(components): standardized form controls with touch targets + focus ring"
```

---

### Task 6.6: Standardize toast notifications

**Files:**
- Modify: `telemetry_tool/web/static/js/toast.js`
- Modify: `telemetry_tool/web/static/css/main.css` (toast section)

**Step 1: Replace toast z-index with `var(--z-toast)`**

**Step 2: Add enter/exit animations from `motion.css`**

**Step 3: Commit**

```bash
git commit -m "feat(components): token-based toast with enter/exit animations"
```

---

### Task 6.7: Standardize empty/loading/error states

**Files:**
- Modify: `telemetry_tool/web/static/css/main.css` (empty hero + skeleton sections)

**Step 1: Replace hardcoded colors/spacing with tokens in `.empty-hero`, `.skeleton`**

**Step 2: Add `.error-state` component (icon + message + retry button)**

**Step 3: Commit**

```bash
git commit -m "feat(components): standardized empty, loading, and error state components"
```

---

### Task 6.8: Add modal component

**Files:**
- Add to: `telemetry_tool/web/static/css/main.css`
- Create: (optional) `telemetry_tool/web/static/js/modal.js`

**Step 1: Add `.modal-backdrop`, `.modal`, `.modal__header`, `.modal__body`, `.modal__footer`**

**Step 2: Use `z-index: var(--z-modal)`, backdrop-filter blur, focus trap**

**Step 3: Add accessible keyboard handling (Escape to close, trap focus)**

**Step 4: Register with ModuleManager**

**Step 5: Commit**

```bash
git commit -m "feat(components): accessible modal with focus trap + backdrop blur"
```

---

### Task 6.9: Standardize focus ring across all interactive elements

**Files:**
- Modify: `telemetry_tool/web/static/css/main.css`

**Step 1: Add global `:focus-visible` rule**

```css
:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
}
```

**Step 2: Remove any existing one-off focus styles that conflict**

**Step 3: Add enhanced glow for primary interactive elements**

```css
.btn:focus-visible,
.card--interactive:focus-visible,
.chart-frame:focus-visible {
    box-shadow: 0 0 0 4px var(--accent-dim);
}
```

**Step 4: Commit**

```bash
git commit -m "feat(a11y): unified focus ring with animated glow on key interactive elements"
```

---

## Phase 7: Remaining Pages Migration

> Migrate all 37 remaining pages to the token + component + responsive system.

---

### Task 7.1–7.9: Wave-based page migration

Each wave follows the **Per-Page Checklist** from the design doc:

**Wave 1 (Tasks 7.1-7.2):** Session Detail + Visualize
- Heaviest pages — wrap all charts in ChartFrame
- Mobile card stack for visualize canvas panels
- Skeleton loading for session data

**Wave 2 (Tasks 7.3-7.4):** Driver Profile + Driver List
- KPI cards for driver stats
- Trend charts in ChartFrame

**Wave 3 (Tasks 7.5-7.6):** Track Detail + Track List
- Track map integration
- Session table per track

**Wave 4 (Tasks 7.7-7.8):** Analyze + Compare
- Multi-step form wizard token migration
- Side-by-side comparison layout

**Wave 5 (Tasks 7.9-7.11):** Leaderboard + Analytics Index + Trends
- Data tables, ranking, filters

**Wave 6 (Tasks 7.12-7.15):** Race Strategy (config, index, summary, detail)
- Already heavy custom CSS — token migration + remove !important

**Wave 7 (Tasks 7.16-7.23):** Weekend, Kart, Annotation, Export
- Simpler CRUD forms — fastest migration

**Wave 8 (Tasks 7.24-7.29):** Data Health, Dev Plans, What-If, Setup, Meteo
- Utility pages

**Wave 9 (Tasks 7.30-7.32):** Error pages (404, 500) + Custom Dashboard

**Per-page commit pattern:**
```bash
git commit -m "refactor(session-detail): migrate to token system + ChartFrame + responsive"
```

---

## Phase 8: Accessibility Hardening

---

### Task 8.1: Add chart accessibility summaries

**Files:**
- Modify: All templates with charts

**Step 1: Add `role="img"` and `aria-label` to each `.chart-frame`**

**Step 2: Add `<table class="sr-only">` with sampled data points inside each ChartFrame**

**Step 3: Commit**

```bash
git commit -m "feat(a11y): screen reader summaries and data tables for all charts"
```

---

### Task 8.2: Contrast audit + fix

**Step 1: Run contrast check on all text/background combinations**

Use the WCAG contrast checker against the token system colors.

**Step 2: Fix any combinations below 4.5:1 ratio**

Key risk: `--accent` (#f07030) on `--bg-primary` (#0a0d14) — verify.
Key risk: `--text-muted` (#515a6e) on `--bg-secondary` (#10141c) — verify.

**Step 3: Commit**

```bash
git commit -m "fix(a11y): contrast fixes to meet WCAG 2.2 AA (4.5:1 minimum)"
```

---

### Task 8.3: Touch target audit

**Step 1: Find all interactive elements below 44px**

Check buttons, links, checkboxes, form inputs, table clickable rows.

**Step 2: Add `min-height: var(--touch-min)` or padding to reach 44px**

**Step 3: Commit**

```bash
git commit -m "fix(a11y): all interactive elements meet 44px minimum touch target"
```

---

### Task 8.4: Theme transition animation

**Files:**
- Modify: `telemetry_tool/web/static/js/theme.js`
- Modify: `telemetry_tool/web/static/css/main.css`

**Step 1: Add CSS transition on `body` for theme switch**

```css
body {
    transition: background-color var(--duration-slow) var(--ease-in-out),
                color var(--duration-slow) var(--ease-in-out);
}
```

**Step 2: Add transition to card/panel elements**

```css
.card, .chart-frame, .data-table, .top-nav, .kpi-card {
    transition: background-color var(--duration-slow) var(--ease-in-out),
                border-color var(--duration-slow) var(--ease-in-out),
                box-shadow var(--duration-slow) var(--ease-in-out);
}
```

**Step 3: Commit**

```bash
git commit -m "feat(theme): smooth dark/light transition animation"
```

---

## Phase 9: Performance Budgets + CI

---

### Task 9.1: Add Playwright visual regression tests

**Files:**
- Create: `telemetry_tool/tests/visual/test_screenshots.py`

**Step 1: Write Playwright screenshot tests**

Screenshot matrix: 5 viewports (360, 768, 1280, 1920, 2560) x key pages x 2 themes.

Key pages: dashboard, session list, session detail (if data exists), race strategy index.

**Step 2: Generate baseline screenshots**

```bash
pytest telemetry_tool/tests/visual/test_screenshots.py --update-snapshots
```

**Step 3: Commit**

```bash
git commit -m "test(visual): Playwright screenshot regression at 5 viewports x 2 themes"
```

---

### Task 9.2: Add axe-core accessibility tests

**Files:**
- Create: `telemetry_tool/tests/a11y/test_accessibility.py`

**Step 1: Write axe-core Playwright tests**

Test key pages for WCAG 2.2 AA violations.

**Step 2: Commit**

```bash
git commit -m "test(a11y): axe-core WCAG 2.2 AA automated checks on key pages"
```

---

### Task 9.3: Add CSS/JS size checks

**Files:**
- Create: `telemetry_tool/tests/performance/test_bundle_size.py`

**Step 1: Write file size assertions**

```python
def test_css_total_size():
    """CSS total should be under 100KB uncompressed."""
    total = sum(f.stat().st_size for f in css_dir.glob('*.css'))
    assert total < 100_000, f"CSS total {total} exceeds 100KB budget"

def test_js_total_size():
    """JS total should be under 200KB uncompressed."""
    total = sum(f.stat().st_size for f in js_dir.glob('*.js'))
    assert total < 200_000, f"JS total {total} exceeds 200KB budget"
```

**Step 2: Commit**

```bash
git commit -m "test(perf): CSS/JS bundle size budget assertions"
```

---

## Phase 10: Documentation + Governance

---

### Task 10.1: Create UI Architecture README

**Files:**
- Create: `docs/ui-architecture/README.md`

**Step 1: Write overview document**

Cover: tokens, theming, component guidelines, responsive rules, chart contract, motion rules, z-index policy, contribution checklist.

**Step 2: Commit**

```bash
git commit -m "docs: UI Architecture README — tokens, components, responsive, motion, charts"
```

---

### Task 10.2: Create contribution checklist

**Files:**
- Create: `docs/ui-architecture/contribution-checklist.md`

**Step 1: Write the checklist from the design doc**

Tokens, responsive, accessibility, states, performance, module lifecycle.

**Step 2: Commit**

```bash
git commit -m "docs: contribution checklist for new UI components and pages"
```

---

### Task 10.3: Remove legacy CSS aliases

**Files:**
- Modify: `telemetry_tool/web/static/css/main.css`

**Step 1: Search for all uses of legacy variable names**

`--bg-card`, `--surface`, `--surface-light`, `--card-bg`, `--border-light`, `--accent-dim` (old meaning).

**Step 2: Replace in all CSS files with new token names**

**Step 3: Remove the alias block from `main.css :root`**

**Step 4: Commit**

```bash
git commit -m "refactor(css): remove legacy variable aliases — migration complete"
```

---

### Task 10.4: Final smoke test + tag release

**Step 1: Run all tests**

```bash
pytest telemetry_tool/tests/ -x -q
```

**Step 2: Run visual regression**

```bash
pytest telemetry_tool/tests/visual/ -x
```

**Step 3: Run accessibility checks**

```bash
pytest telemetry_tool/tests/a11y/ -x
```

**Step 4: Manual test at 360px, 768px, 1920px in dark + light mode**

**Step 5: Tag release**

```bash
git tag -a v2.0.0-ui -m "Front-end architecture overhaul complete"
```
