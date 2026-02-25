# Focus Mode & GPS Fallback Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a fullscreen "Focus Mode" with resizable split panes, an icon dock sidebar, and GPS fallback to static track outline.

**Architecture:** Three new files — `split_pane.js` (standalone resize engine), `focus_mode.js` (overlay controller + sidebar + tool registry), `focus_mode.css` (all styles). Tool modules register render/destroy/redraw functions. Template adds expand buttons per section and focus button per tab. GPS fallback adds a track geometry API endpoint and static outline rendering.

**Tech Stack:** Vanilla JS (IIFE), CSS custom properties, Canvas 2D, existing `__redraw`/ResizeObserver patterns, Flask/Jinja2.

**Security:** No `innerHTML` usage — all DOM is built with `document.createElement` / `textContent`. Cleanup uses `while (el.firstChild) el.removeChild(el.firstChild)`.

---

### Task 1: Split Pane Engine — `split_pane.js`

**Files:**
- Create: `telemetry_tool/web/static/js/split_pane.js`

**Context:** Standalone, reusable module with zero dependencies. Manages a container element and creates resizable panels with drag handles. Follow the project's IIFE pattern. Expose via `window.SplitPane`.

**Step 1: Create `split_pane.js`**

Complete implementation — drag-to-resize with `pointermove`/`setPointerCapture`, min panel size 150px, double-click to reset, `__redraw` firing on release. Layout rules: 1 panel = full, 2 = side by side, 3 = 2 top + 1 bottom, 4 = 2x2, 5+ = 3 top + rest bottom.

All DOM cleanup uses `while (el.firstChild) el.removeChild(el.firstChild)` — no `innerHTML`.

**Step 2: Verify** — Load `/static/js/split_pane.js` directly in browser, check for syntax errors.

**Step 3: Commit**

```bash
git add telemetry_tool/web/static/js/split_pane.js
git commit -m "feat(focus-mode): add split pane engine — drag-to-resize panels"
```

---

### Task 2: Focus Mode CSS — `focus_mode.css`

**Files:**
- Create: `telemetry_tool/web/static/css/focus_mode.css`
- Modify: `telemetry_tool/web/templates/base.html:15` — add CSS link after `main.css`

**Context:** Styles for fullscreen overlay (z-index 5000), icon dock sidebar (48px), split pane handles (4px, accent on hover), expand buttons (⛶), tab focus button (⊞). Base overlay on existing `.loading-overlay` pattern (position:fixed, all-0, backdrop).

**Key CSS classes:**
- `.focus-overlay` / `.focus-overlay.active` — fullscreen fixed overlay with fade-in
- `.focus-dock` / `.focus-dock-btn` — 48px sidebar, 36x36 icon buttons, scale(1.3) on hover
- `.focus-dock-label` — absolute positioned hover label that slides out right
- `.focus-dock-btn.active` — accent background for active tools
- `.focus-dock-btn.unavailable` — grayed out, no pointer
- `.sp-grid` / `.sp-panel` / `.sp-handle` — split pane structural classes
- `.sp-handle--horizontal` (col-resize) / `.sp-handle--vertical` (row-resize)
- `.focus-expand-btn` — 24x24 inline button for section headers
- `.focus-tab-btn` — 32x32 button for tab bar

**Step 1: Create `focus_mode.css`** with all styles above.

**Step 2: Add CSS link** in `base.html` after line 15: `<link rel="stylesheet" href="/static/css/focus_mode.css">`

**Step 3: Verify** — Load any page, no console errors.

**Step 4: Commit**

```bash
git add telemetry_tool/web/static/css/focus_mode.css telemetry_tool/web/templates/base.html
git commit -m "feat(focus-mode): add Focus Mode CSS — overlay, dock, split pane, expand buttons"
```

---

### Task 3: Focus Mode Controller — `focus_mode.js`

**Files:**
- Create: `telemetry_tool/web/static/js/focus_mode.js`

**Context:** Main controller. Creates overlay DOM, manages icon dock sidebar, integrates with `SplitPane`, handles tool lifecycle. Must load AFTER `split_pane.js` and `resize_observer.js`. All DOM built with `createElement`/`textContent` — zero `innerHTML`.

**Dependencies:** `window.SplitPane` (Task 1), `window.TELEMETRY` (session_detail.html line 854).

**Public API:**
- `FocusMode.registerTool(id, { icon, label, tabs, render, available })`
- `FocusMode.open({ primaryTool, tab })`
- `FocusMode.close()`
- `FocusMode.toggle(tab)`

**Smart defaults map:**
```javascript
var DEFAULTS = {
    'track-map':       ['track-map', 'speed-trace', 'gg-diagram'],
    'speed-trace':     ['speed-trace', 'track-map', 'lap-overlay'],
    'gg-diagram':      ['gg-diagram', 'track-map', 'speed-trace'],
    'lap-overlay':     ['lap-overlay', 'speed-trace', 'lap-distribution'],
    'lap-distribution':['lap-distribution', 'lap-progress', 'lap-overlay'],
    'stint-analysis':  ['stint-analysis', 'driver-workload', 'lap-progress'],
    'fingerprint':     ['fingerprint', 'badges'],
};
var TAB_DEFAULTS = {
    'analytics':   ['track-map', 'speed-trace', 'gg-diagram', 'lap-distribution'],
    'corners':     ['track-map', 'gg-diagram'],
    'performance': ['stint-analysis', 'driver-workload', 'lap-progress', 'session-timeline'],
    'overview':    ['fingerprint', 'badges'],
};
```

**Key behaviors:**
- `open()`: builds overlay if needed, determines tools from smart defaults or localStorage, filters by tab + availability, builds dock, renders panels
- `close()`: saves layout to localStorage, calls `destroy()` on all rendered tools, removes overlay active class, restores body scroll
- Dock buttons: click toggles tool on/off, hover shows label, active tools highlighted with accent
- Keyboard: Escape=close, F=toggle, R=reset, S=sidebar toggle, 1-9=tool by position
- All input guards: skip shortcuts when focused on INPUT/TEXTAREA/SELECT

**Persistence:** `localStorage.setItem('focus_layout_' + tab, JSON.stringify(toolIds))`

**Step 1: Create `focus_mode.js`** — ~300 lines.

**Step 2: Verify** — Load directly in browser for syntax check.

**Step 3: Commit**

```bash
git add telemetry_tool/web/static/js/focus_mode.js
git commit -m "feat(focus-mode): add Focus Mode controller — overlay, dock, tool registry, keyboard shortcuts"
```

---

### Task 4: Tool Registrations — `focus_tools.js`

**Files:**
- Create: `telemetry_tool/web/static/js/focus_tools.js`

**Context:** Registers all chart tools with `FocusMode.registerTool()`. Each tool creates a fresh canvas in the provided container and draws using API data. Loaded LAST, after all chart modules and focus_mode.js. All DOM built with safe methods — no `innerHTML`.

**Tools to register:**

| Tool ID | Icon | Tabs | Data source | Drawing |
|---------|------|------|-------------|---------|
| `track-map` | 🗺 | analytics, corners | `/api/session/{id}/gps/{lap}` | GPS trace with speed coloring |
| `speed-trace` | 📈 | analytics | `/api/session/{id}/gps/{lap}` | Speed vs distance line chart |
| `gg-diagram` | ⚡ | analytics, corners | `/api/session/{id}/gg_data` | Lateral vs longitudinal G scatter |
| `lap-overlay` | 📊 | analytics | `/api/session/{id}/gps/{lap}` | Multi-lap speed overlay |
| `lap-distribution` | 📉 | analytics | `/api/session/{id}/lap-distribution` | Histogram bars |
| `lap-progress` | 🎯 | analytics | `/api/session/{id}/lap-progress` | Lap time trend line |
| `brake-precision` | 🛑 | corners | `/api/session/{id}/brake-scatter` | Scatter plot |
| `stint-analysis` | ⏱ | performance | `/api/session/{id}/stint-data` | Bar chart |
| `driver-workload` | 💪 | performance | — | Placeholder message |
| `session-timeline` | 📅 | performance | — | Placeholder message |
| `fingerprint` | 🕸 | overview | — | Placeholder message |
| `badges` | ⭐ | overview | — | Placeholder message |

**Shared drawing helpers** (all use same Canvas 2D pattern):
- `_focusMsg(canvas, text)` — centered message on dark background
- `_drawSpeedTrace(canvas, data, color)` — speed vs distance line
- `_drawGG(canvas, data)` — G-G scatter with grid circles
- `_drawDistribution(canvas, data)` — histogram bars
- `_drawProgress(canvas, data)` — lap time trend line

**Availability logic:**
- GPS-dependent tools: `available: hasGps()` where `hasGps = T().gpsLaps && T().gpsLaps.length > 0`
- Track map also available when `T().trackId` (GPS fallback)
- Non-GPS tools: `available: true`

**Cleanup pattern** for destroy:
```javascript
destroy: function () {
    while (container.firstChild) container.removeChild(container.firstChild);
}
```

**Step 1: Create `focus_tools.js`** — ~400 lines.

**Step 2: Verify** — Load directly for syntax check.

**Step 3: Commit**

```bash
git add telemetry_tool/web/static/js/focus_tools.js
git commit -m "feat(focus-mode): add tool registrations — Analytics, Corners, Performance, Overview tools"
```

---

### Task 5: Template Integration — Expand Buttons + Script Includes

**Files:**
- Modify: `telemetry_tool/web/templates/session_detail.html`

**Context:** Add ⛶ expand buttons to section headers, ⊞ focus button to tab bar, include new JS files.

**Step 1: Add Focus Mode tab button to tab bar**

At line 140 (after last `<button>` tab, before closing `</div>` of `.session-tabs`), insert:
```html
<button type="button" class="focus-tab-btn" id="focus-tab-btn" title="Focus Mode (F)">&#x229E;</button>
```

**Step 2: Add expand buttons to section headers**

Append `<button class="focus-expand-btn" data-tool="TOOL_ID" title="Focus Mode">&#x26F6;</button>` to these `<h2>` tags:

| Section | Line (approx) | data-tool |
|---------|---------------|-----------|
| Track Map | 570 | `track-map` |
| Track Speed Profile | ~625 | `speed-trace` |
| Lap Speed Comparison | ~647 | `lap-overlay` |
| Lap Time Distribution | ~660 | `lap-distribution` |
| Lap Progress Tracker | ~690 | `lap-progress` |
| G-G Explorer | ~446 | `gg-diagram` |
| Stint Analysis | (Performance tab) | `stint-analysis` |
| Driver Fitness & Endurance | (Performance tab) | `driver-workload` |
| Performance Fingerprint | (Overview tab) | `fingerprint` |
| Achievements & Rating | (Overview tab) | `badges` |

**Step 3: Add script includes**

After line ~1011 (after `cross_session.js`), before the corner replay conditional block, add:
```html
<script src="{{ url_for('static', filename='js/split_pane.js') }}"></script>
<script src="{{ url_for('static', filename='js/focus_mode.js') }}"></script>
<script src="{{ url_for('static', filename='js/focus_tools.js') }}"></script>
```

**Step 4: Wire up event listeners**

In the DOMContentLoaded `<script>` block (around line 1018), add:
```javascript
// Focus Mode — expand buttons
document.querySelectorAll('.focus-expand-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
        var tool = btn.dataset.tool;
        var tab = btn.closest('.tab-panel');
        var tabName = tab ? tab.id.replace('tab-', '') : 'analytics';
        FocusMode.open({ primaryTool: tool, tab: tabName });
    });
});
// Focus Mode — tab button
var focusTabBtn = document.getElementById('focus-tab-btn');
if (focusTabBtn) {
    focusTabBtn.addEventListener('click', function() {
        var activeTab = document.querySelector('.session-tab.active');
        var tabName = activeTab ? activeTab.dataset.tab : 'analytics';
        FocusMode.open({ tab: tabName });
    });
}
```

**Step 5: Pass `trackId` to TELEMETRY global**

In `window.TELEMETRY = { ... }` block (line ~856), add:
```javascript
trackId: {{ session.track_id|tojson }},
```

**Step 6: Verify**

1. Load `/sessions/MKR_R`
2. See ⛶ buttons on section headers, ⊞ in tab bar
3. Click ⛶ on Track Map → overlay opens
4. Click ⊞ → opens with tab defaults
5. Toggle tools, resize panels, Escape to close

**Step 7: Commit**

```bash
git add telemetry_tool/web/templates/session_detail.html
git commit -m "feat(focus-mode): integrate into session detail — expand buttons, tab button, scripts"
```

---

### Task 6: GPS Fallback — Track Geometry API

**Files:**
- Modify: `telemetry_tool/web/routes/api_data.py` — add `/api/track/<track_id>/geometry` endpoint
- Modify: `telemetry_tool/web/static/js/focus_tools.js` — add static track outline drawing

**Step 1: Add API endpoint** in `api_data.py`:

```python
@bp.route("/track/<track_id>/geometry")
def track_geometry(track_id):
    """Return track reference line geometry for static track outline."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT track_name, reference_line FROM tracks WHERE track_id = ?",
        (track_id,)
    ).fetchone()
    if not row or not row["reference_line"]:
        return jsonify({"error": "No geometry available"}), 404
    import json
    try:
        geo = json.loads(row["reference_line"])
    except (json.JSONDecodeError, TypeError):
        return jsonify({"error": "Invalid geometry data"}), 500
    return jsonify({
        "track_name": row["track_name"],
        "latitudes": geo.get("latitudes", []),
        "longitudes": geo.get("longitudes", []),
    })
```

**Step 2: Add `_drawStaticTrack` helper** to `focus_tools.js` — draws neutral-colored track outline from lat/lon arrays using same `toPixel` projection as `track_map.js`. No speed coloring, just a white/gray line.

**Step 3: Update `track-map` tool render** — when `!hasGps() && T().trackId`, fetch from `/api/track/{trackId}/geometry` and call `_drawStaticTrack`.

**Step 4: Update availability** — `available: hasGps() || !!T().trackId`

**Step 5: Verify** — If possible, test with a no-GPS session.

**Step 6: Commit**

```bash
git add telemetry_tool/web/routes/api_data.py telemetry_tool/web/static/js/focus_tools.js
git commit -m "feat(focus-mode): GPS fallback — track geometry API + static outline rendering"
```

---

### Task 7: Polish & Edge Cases

**Files:**
- Modify: `telemetry_tool/web/static/js/focus_mode.js`
- Modify: `telemetry_tool/web/static/css/focus_mode.css`

**Step 1: Window resize in focus mode** — add resize listener that fires `redraw()` on all rendered tools.

**Step 2: Responsive dock** — add `@media (max-width: 768px)` to reduce dock width to 40px.

**Step 3: Verify** — resize browser while in focus mode, test on narrow viewport.

**Step 4: Commit**

```bash
git add telemetry_tool/web/static/js/focus_mode.js telemetry_tool/web/static/css/focus_mode.css
git commit -m "feat(focus-mode): polish — resize handling, responsive dock"
```

---

### Task 8: Final Integration Test

**No files — verification only.**

1. Navigate to `/sessions/MKR_R`
2. Click ⛶ on Track Map → 3-panel cockpit opens (Track Map + Speed Trace + G-G Diagram)
3. Drag handles to resize panels
4. Double-click handle to reset
5. Toggle tools via sidebar icons
6. Press R (reset), S (sidebar toggle), 1-9 (tool toggle), Escape (close)
7. Press F to reopen with last layout
8. Click ⊞ for tab defaults
9. Switch to Performance tab, click ⊞ → different tool set
10. Verify no console errors
11. Close and reopen → localStorage restores last layout
