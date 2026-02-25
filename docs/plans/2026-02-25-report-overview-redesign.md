# Report Overview Redesign

**Date**: 2026-02-25
**Scope**: Session detail page → Overview tab — three sections + global tooltips

---

## 1. Driving Style — Complete Rewrite (JS-rendered)

### Problem
The current Driving Style section shows raw 0–1 values (e.g., "Trail Braking: 0.42") that are meaningless without context. The layout is dense and clinical — a spreadsheet, not a coaching tool.

### Solution
Replace the 100-line Jinja template block with a client-side JS component (`driving_style.js`) that fetches enriched data from a new API endpoint.

### Backend: New API endpoint

**`GET /api/session/<session_id>/driving-style`**

Response:
```json
{
  "style_label": "Smooth",
  "style_confidence": 0.87,
  "features": [
    {
      "key": "trail_braking_depth",
      "label": "Trail Braking",
      "value": 0.42,
      "qualitative": "Moderate",
      "rating": "average",
      "hint": "How deep into corners you maintain brake pressure",
      "tip": "Try holding brake pressure 10m deeper into Turn 3 and 7",
      "inverted": false
    }
  ],
  "strengths": ["Excellent throttle modulation"],
  "weaknesses": ["Inconsistent braking points"],
  "radar_labels": ["Trail Braking", "Brake Consistency", ...],
  "radar_values": [0.42, 0.78, ...]
}
```

Qualitative tier mapping (applied in Python):
- `0.00–0.20` → **Low** (red)
- `0.20–0.40` → **Below Avg** (orange)
- `0.40–0.60` → **Moderate** (amber)
- `0.60–0.80` → **Good** (blue)
- `0.80–1.00` → **Elite** (green)

For inverted features (lower = better), thresholds flip. Coaching `tip` generated per-feature based on value tier.

### Frontend: `driving_style.js`

New JS module following `summary_report.js` / `session_badges.js` pattern:
- `window.DrivingStyle.init(containerId, sessionId)`
- Fetches from API, renders into DOM (no innerHTML)
- Auto-init via `DOMContentLoaded` + `FetchHelper.lazyInit`

Layout:
1. **Style header** — Style label badge ("Smooth") + confidence pill + one-line description
2. **Feature gauge list** — Each feature:
   - Feature name with tooltip (metric explanation)
   - Color-coded gauge bar (fill color = rating tier)
   - Qualitative label instead of raw number ("Moderate" in amber)
   - Coaching tip tooltip on hover over label/gauge
3. **Radar chart** — Canvas-based radar from `radar_labels`/`radar_values`
4. **Strengths / Weaknesses** — Two side-by-side insight boxes from API data

### Template change

Replace lines 163–263 in `session_detail.html` with:
```html
<section class="section">
    <h2>Driving Style</h2>
    <div id="driving-style-container" aria-live="polite">
        <div class="loading-center">...</div>
    </div>
</section>
```

### Files touched
- `telemetry_tool/web/routes/api_data.py` — new endpoint
- `telemetry_tool/web/static/js/driving_style.js` — new file
- `telemetry_tool/web/static/css/main.css` — new styles
- `telemetry_tool/web/templates/session_detail.html` — replace Jinja block

---

## 2. Next Session Actions — Elevated Visual Hierarchy

### Problem
Actions section blends in with highlights and improvements. Same card style, font sizes, spacing. The most actionable part of the debrief doesn't stand out.

### Solution
Wrap the actions section in a visually distinct hero container. No backend changes.

### Visual changes
1. **Hero wrapper** (`.debrief-actions-hero`):
   - Subtle accent gradient background (`rgba(255,107,53,0.04)` → `rgba(255,107,53,0.08)`)
   - Left accent border (3px solid accent)
   - Extra padding (1.2rem), rounded corners
   - Top margin gap (2rem) to break from improvements above

2. **Larger title**: `.debrief-actions-title` from `1rem` → `1.25rem`, with flag/arrow icon prefix

3. **Cards unchanged** — prominence comes from section wrapper, not card bloat

4. **Count pill** — inline after title: "**Next Session Actions** `3 actions`"

### Files touched
- `telemetry_tool/web/static/js/summary_report.js` — wrap actions in hero div (~5 lines)
- `telemetry_tool/web/static/css/main.css` — new `.debrief-actions-hero` styles

---

## 3. Achievements & Rating — Premium Motorsport Aesthetic

### Problem
Flat cards with colored left-border, plain Unicode stars, simple tier boxes. Functional but lacks the premium feel expected in a motorsport tool.

### Solution
Metallic gradients, glassmorphism cards, animated stars. No backend changes.

### Visual changes

1. **Stars**:
   - Size bump `1.8rem` → `2.4rem`
   - Gold metallic text gradient (`#ffd700 → #ffaa00 → #ffd700` with `background-clip: text`)
   - One-shot pulse glow animation on load (0.6s)

2. **Tier counters**:
   - Metallic gradient borders: gold (`#ffd700 → #b8860b`), silver (`#c0c0c0 → #808080`), bronze (`#cd7f32 → #8b4513`)
   - Metallic text gradient on count number
   - Dark glassmorphism background (`rgba(255,255,255,0.03)` + `backdrop-filter: blur(8px)`)
   - Hover: glow intensifies + `scale(1.03)`

3. **Badge cards**:
   - Top metallic accent stripe (2px gradient) replaces left border
   - Dark card + subtle inner shadow for depth
   - Tier pill gets metallic gradient background
   - Badge name weight `700` → `800`
   - Progress bar: rounded ends + tier-colored glow shadow

4. **Category radar**: Higher contrast grid lines, more metallic orange fill gradient

5. **Coaching box**: Restyle as "pit crew note" — darker background, monospace-accented label

### Files touched
- `telemetry_tool/web/static/js/session_badges.js` — add tooltip spans, minor DOM tweaks
- `telemetry_tool/web/static/css/main.css` — restyle badges section

---

## 4. Global Tooltips Across All Sections

### Problem
Sections and categories lack context. A new user doesn't know what "Pace score" or "Execution" means without reading docs.

### Solution
Add hover tooltips (`data-tip` pattern already in CSS) to all section headings and sub-categories.

### Tooltip locations

| Location | Example tooltip |
|---|---|
| Score Breakdown `<h2>` | "Weighted score from pace, consistency, execution, and robustness" |
| Each score sub-bar | "Pace: How close your lap times are to the theoretical best" |
| Driving Style `<h2>` | "Your driving fingerprint — 10 input behaviors analyzed across all laps" |
| Each feature gauge | Covered by Section 1 (hint + coaching tip) |
| Session Debrief `<h2>` | "AI-generated performance report with highlights, metrics, and action plan" |
| Debrief sub-labels | "Highlights: Strongest aspects" / "Key Metrics: Core numbers with context" |
| Next Session Actions title | "Concrete actions to focus on next session, ranked by impact" |
| Achievements `<h2>` | "Badges earned based on pace, consistency, endurance, flow, and improvement" |
| Tier counters | "Gold badges require top-tier performance in a category" |
| Badge category dots | Per-category explanation |
| Performance Fingerprint `<h2>` | "Radar signature across key performance dimensions" |

### Implementation
- **Server-rendered sections**: Add `<span class="tip tip-right" data-tip="...">ⓘ</span>` in `session_detail.html`
- **JS-rendered sections**: Add tooltip spans in JS render functions
- **CSS**: Existing `.tip`, `.tip-right`, `.tip-wrap` classes — no new tooltip CSS needed

### Files touched
- `telemetry_tool/web/templates/session_detail.html` — tooltip spans on headings
- `telemetry_tool/web/static/js/summary_report.js` — tooltips on debrief sub-labels
- `telemetry_tool/web/static/js/session_badges.js` — tooltips on tier/category elements
- `telemetry_tool/web/static/js/driving_style.js` — tooltips built into render

---

## Summary of all files touched

| File | Change type |
|---|---|
| `web/routes/api_data.py` | New endpoint `/api/session/<id>/driving-style` |
| `web/static/js/driving_style.js` | **New file** — JS component |
| `web/static/js/summary_report.js` | Wrap actions in hero div + add tooltips |
| `web/static/js/session_badges.js` | Add tooltip spans + minor DOM tweaks for metallic styling |
| `web/static/css/main.css` | New driving style CSS, actions hero CSS, badges premium CSS |
| `web/templates/session_detail.html` | Replace Jinja driving style block, add tooltip spans on headings |
