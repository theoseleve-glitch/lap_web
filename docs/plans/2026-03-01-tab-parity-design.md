# Tab Structure Parity Restoration — Design

**Date**: 2026-03-01
**Status**: Approved
**Goal**: Bring SaaS session detail page to parity with the local desktop tool's report.

## Context

The local desktop tool renders 5 tabs with deep scoring, driving style, debrief, badges, and 12+ analytics modules. The SaaS frontend has 6 tabs but is missing several sections. This design closes the gap.

## Tab Structure (5 tabs)

| # | Tab | Source |
|---|-----|--------|
| 1 | Overview | Merge of current Overview + Performance tab |
| 2 | Corners & Coaching | Unchanged |
| 3 | Timeline | Unchanged (lap progress + stint analysis) |
| 4 | Analytics | Renamed from "Visualize", adds new modules |
| 5 | Lap Data | Unchanged |

**Performance tab is removed.** Its contents:
- 7 score metric cards → Overview (below score breakdown)
- Sector Panel → Analytics tab
- Strengths/Weaknesses → already in Overview

## Overview Tab — Full Depth

Sections in order:

1. **Score Header**: Total score + grade badge (existing)
2. **Score Breakdown**: Horizontal bars for 5 categories. Add subtitle "How your score is built". Display scores as clean integers (`Math.round()`), keep float for bar width calculations.
3. **Strengths & Areas to Improve**: Green/orange insight boxes. Already exist but verify rendering matches local (80%/50% thresholds).
4. **Performance Metrics Grid**: 7 cards moved from Performance tab (Total, Grade, Pace, Consistency, Execution, Robustness, Adaptation).
5. **Driving Style**: New section. 10-feature radar chart, style label + confidence %, trait bars, strengths/weaknesses. Data from `GET /sessions/{id}/driving-style`.
6. **Session Debrief**: New section. Rule-based template strings built from scores + corner coaching + lap metrics. No LLM. Sections: Performance Summary, Key Highlights, Focus Areas, Next Session Plan.
7. **Achievements & Badges**: New section. Badge cards with tier icons (Bronze/Silver/Gold). Data from `badges` field added to `/scores` response.
8. **Session Info + Best Lap**: Existing cards, unchanged.

## Analytics Tab (renamed from Visualize)

### Phase 1 (this PR)
- GPS Track Map (existing)
- Speed Trace Zoom (existing)
- G-G Explorer (existing)
- Sector Panel (moved from Performance tab)

### Phase 2 (future, feature-flagged behind `ANALYTICS_MODULES_V2`)
- Lap Time Distribution
- Lap Progress Tracker
- Cross-Session Comparison
- Brake Precision Chart

## Backend Changes

### A. Badge System (`scoring.py`)

New function `evaluate_badges(score_result) -> list[dict]`.

Badge definitions:

| Badge | Category | Bronze (≥60%) | Silver (≥75%) | Gold (≥90%) |
|-------|----------|---------------|---------------|-------------|
| Pace Master | pace | ≥60% of 25 | ≥75% | ≥90% |
| Consistency Champion | consistency | ≥60% of 25 | ≥75% | ≥90% |
| Execution Expert | execution | ≥60% of 20 | ≥75% | ≥90% |
| Endurance Warrior | robustness | ≥60% of 15 | ≥75% | ≥90% |
| Adaptor | adaptation | ≥60% of 15 | ≥75% | ≥90% |
| Flow State | total | ≥60 | ≥75 | ≥90 |

Return shape:
```json
{
  "id": "pace_master",
  "label": "Pace Master",
  "tier": "gold",
  "category": "pace",
  "criteria": "≥90% pace score"
}
```

### B. API Changes (`data_v2.py`)

`GET /sessions/{id}/scores` response adds:
- `badges`: list of badge dicts from `evaluate_badges()`
- Scores formatted as integers for display (new `display_scores` field), raw floats preserved

### C. Score Formatting

- Internal: keep all floats for calculations
- API response: add `display_scores` dict with `Math.round()` equivalents
- Frontend: use `display_scores` for text, raw scores for bar widths

### D. Adaptation Score Parity

- Add integration test: run `score_session()` on a known CSV, compare output between local SQLite path and PG path
- If rounding differs, align to `round(score, 1)` in `scoring.py`
- Default adaptation (75% of max = 11.25) → display as 11

## Focus Mode

- Wire existing `FocusMode.tsx` skeleton to session detail header
- Add "Focus Mode" button (fullscreen icon) to page header
- Register 3 existing tools: GPS Map, Speed Trace, GG Explorer
- Opens in fullscreen overlay with SplitPane layout
- Not attempting full 12-tool parity — just enable button with what exists

## Driving Style Component

**API**: `GET /sessions/{id}/driving-style` — already exists

**New Component**: `DrivingStyleSection.tsx` in Overview tab
- Canvas-based radar chart with 10 features
- Style label display + confidence percentage badge
- Trait bars (horizontal, 0–1 scale per feature)
- Strengths list (green) / Weaknesses list (orange)
- Graceful fallback: "Driving style analysis not available" if API returns no data

10 features from `driving_style.py`:
1. Trail braking depth
2. Brake point consistency
3. Apex speed ratio
4. Exit speed ratio
5. Line consistency
6. Throttle smoothness
7. Turn-in aggression
8. Stability on power
9. Over-rotation tendency
10. Recovery smoothness

## Session Debrief Component

**New Component**: `SessionDebrief.tsx` in Overview tab
- Frontend-only — no new API endpoint
- Builds narrative from existing data:
  - `scores` → performance summary paragraph
  - `corners` → focus areas (sorted by time loss)
  - `laps` → key highlights (best lap, consistency %)
  - Score thresholds → next session plan recommendations

Template structure:
```
Performance Summary:
  "You scored {total}/100 ({grade} grade). {strength_narrative}..."

Key Highlights:
  • Best lap: {best_time}s ({gap}s from theoretical)
  • Consistency: {cv}% variation across {n_laps} laps
  • Top 25% average: {top25_avg}s

Focus Areas:
  • {corner_name}: {coaching_text} ({time_loss}s potential)
  ...

Next Session Plan:
  1. {actionable_drill_1}
  2. {actionable_drill_2}
```

## Achievements Component

**New Component**: `AchievementsBadges.tsx` in Overview tab
- Renders badge cards in a responsive grid
- Each card: icon (medal emoji), badge name, tier label, brief insight
- Tier colors: Bronze (#CD7F32), Silver (#C0C0C0), Gold (#FFD700)
- If no badges earned: "Keep pushing — badges unlock at 60%+ category scores"

## Files Changed

### Backend
- `telemetry_tool/scoring.py` — add `evaluate_badges()`
- `telemetry_tool/web/routes/data_v2.py` — add badges to scores endpoint, add display_scores
- `telemetry_tool/tests/test_scoring_badges.py` — new test file for badge evaluation
- `telemetry_tool/tests/test_adaptation_parity.py` — new test for adaptation score alignment

### Frontend
- `lap-website/src/app/app/sessions/[id]/page.tsx` — restructure tabs, merge Performance into Overview
- `lap-website/src/components/app/DrivingStyleSection.tsx` — new radar chart component
- `lap-website/src/components/app/SessionDebrief.tsx` — new debrief component
- `lap-website/src/components/app/AchievementsBadges.tsx` — new badges component
- `lap-website/src/components/app/focus-mode/FocusMode.tsx` — wire to header button

## Non-Goals

- Full 12-tool Focus Mode (only 3 tools for now)
- LLM-generated debrief (rule-based only)
- Phase 2 Analytics modules (feature-flagged, not implemented this PR)
- Corner Replay changes (already functional)
- Cross-session comparison (future)
