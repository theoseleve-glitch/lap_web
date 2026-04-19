# First Report Reveal — Design Spec

**Date:** 2026-03-20
**Status:** Approved (v3 — revised after two spec reviews)
**Scope:** New standalone reveal page shown once after successful upload

---

## Overview

A dedicated reveal screen at `/app/sessions/<id>/reveal` that surfaces the five most valuable insights immediately after upload: focus areas, top corners, recoverable lap time, next-session drills, and data confidence. The existing session detail page is not modified.

## Data Flow

### Backend: New `GET /api/v1/sessions/<id>/reveal` Endpoint

The upload is **async** — `POST /api/v1/sessions/upload` returns `HTTP 202` with a `job_id`, dispatches a Celery pipeline chain, and the frontend polls via SSE (`GET /api/v1/jobs/<id>/stream`) until `status === "completed"`. The pipeline persists all results (scores, corners, coaching, theoretical data) to PostgreSQL before marking the job complete.

A new lightweight endpoint assembles the reveal payload from already-persisted DB data:

**`GET /api/v1/sessions/<id>/reveal`** (in `telemetry_tool/web/routes/data_v2.py`)

```json
{
  "ok": true,
  "data": {
    "focus_areas": [
      { "category": "braking", "summary": "Late braking into T3, T7" },
      { "category": "exit_traction", "summary": "Exit speed lost in T3-T7" },
      { "category": "consistency", "summary": "Lap time variation above target" }
    ],
    "top_corners": [
      { "corner_id": 3, "direction": "L", "time_loss_s": 0.31, "coaching_hint": "Trail-brake deeper" },
      { "corner_id": 7, "direction": "R", "time_loss_s": 0.22, "coaching_hint": "Earlier throttle application" },
      { "corner_id": 1, "direction": "L", "time_loss_s": 0.18, "coaching_hint": "Tighter entry line" }
    ],
    "recoverable_s": 0.847,
    "drills": [
      { "title": "Trail-brake deeper into T3", "target_improvement": "0.31s" },
      { "title": "Hold throttle through T7 exit", "target_improvement": "0.22s" },
      { "title": "Smooth steering input T1 entry", "target_improvement": "0.18s" }
    ],
    "confidence": {
      "score": 82,
      "level": "high"
    },
    "best_lap_s": 58.234,
    "n_laps": 14,
    "total_score": 72,
    "grade": "B",
    "track_name": "Franciacorta",
    "session_date": "2026-03-20"
  }
}
```

### Data Source Mapping

| Field | DB Source | Extraction Logic |
|-------|----------|------------------|
| `focus_areas` | `analysis_json` table → `coaching_v3.focus_areas` or `coaching_v2.focus_areas` | Prefer `coaching_v3`, fall back to `coaching_v2`. Each entry has `category` (e.g., `"braking"`, `"exit_traction"`) and `summary` (human-readable string). Sort by `time_loss_s` desc if present, take top 3. If neither coaching version exists, fall back to `scores.weaknesses` (plain `list[str]` of sentence-form labels). |
| `top_corners` | `theoretical_data` table → `corner_coaching` JSON array | Sort by `time_loss_total_s` desc, take top 3. Extract `corner_id`, `direction`, `time_loss_total_s` (rename to `time_loss_s` for API consistency with existing corners endpoint). For `coaching_hint`: read `coaching_hints` (plural, a `list[str]`) and take `coaching_hints[0]`. If empty or missing, use `null`. |
| `recoverable_s` | Same `corner_coaching` array | Sum of `time_loss_total_s` across ALL corners with positive time loss (not just top 3). This is the session-wide recoverable figure. |
| `drills` | `analysis_json` table → `coaching_v3.drills` or `coaching_v2.drills` | Prefer `coaching_v3`, fall back to `coaching_v2`. Each drill has `title` (string), `target_improvement` (string like `"0.31s"`), and optionally `rank`, `description`, `focus_corners`. Take top 3 by `rank` (lower = higher priority). If neither coaching version exists, return empty array. |
| `confidence` | `theoretical_data` table → `theoretical_metrics.confidence` | Extract `confidence_score` (rename to `score`) and `confidence_level` (rename to `level`). The `ConfidenceAssessment` dataclass has these two fields plus `confidence_reasons` and `component_scores` which we don't need for the reveal. If confidence data is missing, return `null`. |
| `best_lap_s` | `sessions` table → `best_lap_time_s` column | Direct read. Already computed and persisted by the pipeline. Do not re-query the `laps` table. |
| `n_laps` | `sessions` table → `n_laps` column | Direct read |
| `total_score` / `grade` | `sessions` table → `total_score` and `grade` columns | Direct reads. Already computed and persisted by the scoring engine. Do NOT recompute from sub-scores (the scoring engine uses adaptive weighting that cannot be replicated by simple addition). |
| `track_name` / `session_date` | `sessions` table | Direct reads, needed for header bar |

### Frontend: Fetch-on-Mount

The reveal page is simple: fetch `/api/v1/sessions/<id>/reveal` on mount. No sessionStorage handoff needed — the endpoint is lightweight (single DB round-trip, no computation).

1. Upload SSE stream completes with `status === "completed"` and `session_id`
2. Upload page redirects to `/app/sessions/<id>/reveal` (change from current `/app/sessions/<id>`)
3. Reveal page fetches `GET /api/v1/sessions/<id>/reveal`
4. Renders the 5 sections with staggered animation
5. "View Full Session" CTA navigates to `/app/sessions/<id>`

This eliminates sessionStorage complexity (tab-scoping, size limits, cleanup).

## Page Layout

Route: `lap-website/src/app/app/sessions/[id]/reveal/page.tsx`

Full-viewport dark screen (`bg-asphalt`), content centered, max-width container.

### Sections (top to bottom)

**1. Header bar**
- Left: Track name + session date (`font-monument text-sm text-steel`)
- Right: Confidence pill — colored by level (acid-green for "high", marshal-yellow for "medium", safety-red for "low"), shows percentage

**2. Hero: Score + Grade**
- Score: `font-monument text-6xl text-chalk`, uses existing `AnimatedCounter` (1.4s count-up)
- "/ 100" label: `font-body text-steel`
- Grade badge: bordered square using inline style with the same color logic as `GRADE_COLORS` in session detail page (defined locally in the reveal component — no import, matches the pattern of other files)
- Subtitle: "Your Session Report" in `font-body text-steel`

**3. Stat row (3 columns)**
- Recoverable time: `font-telemetry text-2xl text-chalk`, label "recoverable" in `font-body text-xs text-steel`
- Best lap: formatted via `formatLapTime()`, same styling
- Lap count: "14 laps analyzed"
- On mobile: stack vertically

**4. Top Corners**
- Section header: `font-monument text-xs text-steel uppercase tracking-wider`
- Up to 3 rows, each a `bg-concrete rounded-xl border border-steel/10 p-4` card
- Left: corner ID + direction badge (e.g., "T3 L")
- Center: time loss in `text-safety-red font-telemetry` (e.g., "-0.31s")
- Right: coaching hint in `text-chalk/80 font-body text-sm`
- Rows stagger in with 100ms delay each

**5. Focus Areas + Next-Session Drills (2-column grid)**
- Left column "FOCUS AREAS": bullet list showing `focus_areas[].summary` strings, `text-chalk font-body text-sm`
- Right column "NEXT-SESSION DRILLS": numbered list showing `drills[].title`, each with `target_improvement` shown as muted `text-steel font-telemetry text-xs` badge (e.g., "~0.31s")
- On mobile: stack vertically

**6. CTA**
- "View Full Session" button: `bg-gold text-white font-telemetry rounded-lg px-8 py-3 hover:bg-gold/80`
- Links to `/app/sessions/<id>`
- Fades in last

### Animation Sequence

All animations use CSS `@keyframes` with staggered `animation-delay`:

| Step | Section | Delay | Duration | Effect |
|------|---------|-------|----------|--------|
| 1 | Header + confidence | 0ms | 300ms | fade-in |
| 2 | Score + grade | 200ms | 1400ms | AnimatedCounter count-up |
| 3 | Stat row | 1600ms | 400ms | fade-up (translateY 20px -> 0) |
| 4 | Corner row 1 | 2000ms | 300ms | fade-up |
| 4 | Corner row 2 | 2100ms | 300ms | fade-up |
| 4 | Corner row 3 | 2200ms | 300ms | fade-up |
| 5 | Focus + Drills | 2500ms | 400ms | fade-up |
| 6 | CTA button | 2900ms | 400ms | fade-in |

Total reveal sequence: ~3.3 seconds.

## Edge Cases

### Graceful degradation

| Condition | Behavior |
|-----------|----------|
| No corners detected | "Top Corners" section hidden; recoverable shows "—" |
| No coaching/drills data | "Drills" column shows "Upload more sessions for personalized drills" |
| No scores (pipeline partial failure) | Hero shows best lap time instead of score; grade hidden |
| Confidence data missing | Confidence pill hidden (not an error — some pipeline runs skip theoretical) |
| Confidence low (score <60) | Pill is `safety-red`; small note appears directly below the confidence pill in the header: "Limited data — results improve with more laps" |
| Zero valid laps | Redirect straight to session detail (skip reveal) |
| Session not found (404 from reveal endpoint) | Redirect to `/app/sessions` |
| Reveal endpoint returns partial data | Each section renders independently; missing sections are hidden |

### Upload handler change

In `lap-website/src/app/app/sessions/upload/page.tsx`:
- Find `router.push(`/app/sessions/${sid}`)` (in the single-file upload completed handler) and change to `router.push(`/app/sessions/${sid}/reveal`)`
- No other changes to the upload page

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `telemetry_tool/web/routes/data_v2.py` | Modify | Add `GET /api/v1/sessions/<id>/reveal` endpoint with `_build_reveal_payload()` helper |
| `lap-website/src/app/app/sessions/[id]/reveal/page.tsx` | Create | Reveal page component (~250 lines) |
| `lap-website/src/app/app/sessions/upload/page.tsx` | Modify | Change redirect target in completed handler (one-line change, search for `router.push(.*/app/sessions/`) |

## Styling Tokens (per CLAUDE.md rules)

- Backgrounds: `bg-asphalt` (page), `bg-concrete` (cards)
- Text: `text-chalk` (primary), `text-steel` (secondary)
- Accents: `bg-gold` (CTA), `text-safety-red` (time loss), `text-acid-green` (confidence high)
- Fonts: `font-monument` (headings), `font-telemetry` (data/numbers), `font-body` (descriptions)
- No raw hex values, no Tailwind defaults
- Grade colors defined locally in the reveal component (same values as `GRADE_COLORS` in session detail page)

## Not In Scope

- Changes to the existing session detail page (Overview tab)
- Changes to the existing scoring or pipeline logic
- Share/export from the reveal page
- Caching or pre-computation of the reveal payload (the endpoint is a simple DB read)
