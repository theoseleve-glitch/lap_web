# Focus Mode & GPS Fallback Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a fullscreen "Focus Mode" to the session detail page that lets users view 3-4 analysis tools together in resizable panels with an icon dock sidebar, plus a GPS fallback that shows a track outline when GPS data is unavailable.

**Architecture:** In-page fullscreen overlay (z-index 5000) with a custom split-pane engine using pointer events for drag handles. An icon-only sidebar dock (48px) lets users toggle tools on/off. Tools re-render into focus panels via registered render functions. When GPS is missing, the track map falls back to a static track outline from the track database.

**Tech Stack:** Vanilla JS (IIFE modules), CSS custom properties, Canvas 2D, existing `__redraw` / ResizeObserver patterns.

---

## 1. Architecture Overview

### New files

| File | Purpose |
|------|---------|
| `static/js/focus_mode.js` | Focus Mode controller — overlay lifecycle, sidebar, tool management |
| `static/js/split_pane.js` | Drag-to-resize split pane engine (standalone, reusable) |
| `static/css/focus_mode.css` | All Focus Mode styles (overlay, sidebar, panels, drag handles) |

### Overlay structure

```
┌─ Fullscreen Overlay (position:fixed, z-index:5000) ───────────────────┐
│ ┌─ Dock (48px) ─┐ ┌─ Panel Grid (resizable) ──────────────────────┐  │
│ │  [🗺]  active  │ │  ┌─ Panel A ──────┐ ┌─ Panel B ────────┐    │  │
│ │  [📈]  active  │ │  │  Track Map      │ │  Speed Trace     │    │  │
│ │  [⚡]  active  │ │  │  (canvas)       │ │  (canvas)        │    │  │
│ │  [📊]         │ │  └─────────────────┘ └──────────────────┘    │  │
│ │  [📉]         │ │  ┌─ Panel C ──────────────────────────────┐   │  │
│ │  [🎯]         │ │  │  G-G Diagram (canvas)                 │   │  │
│ │               │ │  └────────────────────────────────────────┘   │  │
│ │  [✕] close    │ │                                               │  │
│ └───────────────┘ └───────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────┘
```

### Key decisions

- **z-index: 5000** — above loading overlays (1000), below toasts (9999)
- **Tools re-render** into focus panels via registered `render()` functions. Original page DOM stays untouched.
- **Escape key** or close button exits focus mode
- **Panel resize fires `__redraw`** on all canvases inside affected panels via ResizeObserver
- **Sidebar collapses** to icon-only dock (48px) by default

---

## 2. Sidebar — Icon Dock

### Behavior

- **Default width**: 48px, icons only, subtle right border
- **Hover on icon**: icon scales to `transform: scale(1.3)` with a label that slides out to the right (absolute positioned, doesn't push layout). Like macOS Dock.
- **Active tools**: accent-colored left border indicator
- **Click**: toggles tool on/off in the panel grid
- **Close button** (✕) at dock bottom
- **Unavailable tools** (e.g. GPS-dependent when no GPS): grayed out with 🚫 overlay, not clickable

### Icons per tab

| Tool | Icon | Tabs |
|------|------|------|
| Track Map | 🗺 | Analytics, Corners |
| Speed Trace | 📈 | Analytics |
| G-G Diagram | ⚡ | Analytics, Corners |
| Lap Overlay | 📊 | Analytics |
| Lap Distribution | 📉 | Analytics |
| Lap Progress | 🎯 | Analytics |
| Corner Replay | 🎬 | Corners |
| Brake Precision | 🛑 | Corners |
| Stint Analysis | ⏱ | Performance |
| Driver Workload | 💪 | Performance |
| Session Timeline | 📅 | Performance |
| Fingerprint Radar | 🕸 | Overview |
| Badges | ⭐ | Overview |

---

## 3. Split Pane Engine

### Resize mechanics

```
┌──────────────┬─┬──────────────┐
│              │▐│              │
│   Panel A    │▐│   Panel B    │
│              │▐│              │
├──────────────┴─┴──────────────┤
│▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬│ ← horizontal handle (4px)
├───────────────────────────────┤
│          Panel C              │
└───────────────────────────────┘
▐ = vertical drag handle (4px)
▬ = horizontal drag handle (4px)
```

### Layout rules by tool count

| Active tools | Layout | Grid template |
|---|---|---|
| 1 | Full | `1fr / 1fr` |
| 2 | Side by side | `1fr | 1fr` — one vertical handle |
| 3 | 2 top + 1 bottom | `1fr | 1fr` top, `1fr` bottom — vertical + horizontal handle |
| 4 | 2x2 | `1fr | 1fr` / `1fr | 1fr` — vertical + horizontal handle |
| 5+ | 3 top + rest bottom | `1fr | 1fr | 1fr` top, remaining bottom |

### Drag handle behavior

- **4px wide/tall**, `cursor: col-resize` or `row-resize`
- On hover: handle highlights with accent color
- Drag uses `pointermove` + `setPointerCapture` for smooth tracking
- **Min panel size**: 150px
- On release: ResizeObserver triggers `canvas.__redraw()` on affected panels
- **Double-click** handle: reset to equal split

### Tool registration API

```javascript
FocusMode.registerTool('track-map', {
    icon: '🗺',
    label: 'Track Map',
    tabs: ['analytics', 'corners'],
    render: function(container, sessionId) {
        // Creates canvas, calls TrackMap.init(canvas, sessionId)
        // Returns { destroy: fn, redraw: fn }
    }
});
```

- Tool toggled ON: new panel added, `render()` called
- Tool toggled OFF: `destroy()` called, panel removed, grid reflows
- Panel resize: `redraw()` called (maps to `canvas.__redraw`)

---

## 4. Smart Defaults & Persistence

### Default groupings by entry point

| Entry section | Pre-selected tools |
|---|---|
| Track Map | Track Map + Speed Trace + G-G Diagram |
| Speed Trace | Speed Trace + Track Map + Lap Overlay |
| G-G Diagram | G-G Diagram + Track Map + Speed Trace |
| Lap Overlay | Lap Overlay + Speed Trace + Lap Distribution |
| Lap Distribution | Lap Distribution + Lap Progress + Lap Overlay |
| Corner Replay | Corner Replay + Track Map + Brake Precision |
| Stint Analysis | Stint Analysis + Driver Workload + Lap Progress |
| Fingerprint Radar | Fingerprint Radar + Badges |

### Per-tab Focus Mode button defaults

| Tab | Default group |
|---|---|
| Analytics | Track Map + Speed Trace + G-G Diagram + Lap Distribution |
| Corners & Coaching | Corner Replay + Track Map + Brake Precision + G-G Diagram |
| Performance | Stint Analysis + Driver Workload + Lap Progress + Session Timeline |
| Overview | Fingerprint Radar + Badges |

### Persistence

- User toggle selections saved to `localStorage`: `focus_layout_{tab}`
- Restored on next focus mode entry from same tab
- Smart defaults only on first use or after clearing storage

---

## 5. GPS Fallback

### Decision tree

```
GPS data available?
  ├─ YES → Normal rendering
  └─ NO → Session has track_id with known track?
            ├─ YES → Static track outline from reference_line
            │         Corner markers from track definition
            │         Speed/G-G hidden, sidebar icons grayed
            └─ NO → Placeholder card with "Assign Track" dropdown
```

### Behavior matrix

| Component | With GPS | Without GPS (track known) | Without GPS (no track) |
|---|---|---|---|
| Track Map | Full GPS trace, speed-colored | Static outline, neutral color | Placeholder card |
| Speed Trace | Full chart | Hidden | Hidden |
| G-G Diagram | Full scatter | Hidden | Hidden |
| Corner Markers | From GPS positions | From track definition | Hidden |
| Focus Mode sidebar | All tools | Available only, rest grayed (🚫) | Focus mode disabled |
| Chart sync | Full sync | No sync (static only) | N/A |

### Data source

- `tracks` table → `reference_line` column (JSON: lat/lon arrays)
- API endpoint: `/api/track/{track_id}/geometry` (new)
- Track map canvas reuses `toPixel()` projection, draws single neutral-colored outline

---

## 6. Entry Points & Keyboard Shortcuts

### Visual entry points

**Per-section expand button** added to every section header that has a registered focus tool:
```html
<h2>Track Map <button class="focus-expand-btn" data-tool="track-map">⛶</button></h2>
```

**Per-tab Focus Mode button** at the right edge of the tab bar:
```html
<button class="focus-tab-btn" data-tab="analytics">⊞</button>
```

### Keyboard shortcuts

| Key | Action |
|---|---|
| `Escape` | Close focus mode |
| `F11` or `F` | Toggle focus mode for current tab |
| `1-9` | Toggle sidebar tools by position |
| `R` | Reset panels to equal split |
| `S` | Toggle sidebar visibility |

### Transitions

- **Open**: overlay fades in (200ms), panels slide up (translateY)
- **Close**: reverse animation, page restored
- **Tool toggle**: grid reflows with 150ms CSS transition on grid-template
