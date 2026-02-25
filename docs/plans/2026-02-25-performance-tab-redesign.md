# Performance Tab Redesign

**Date**: 2026-02-25
**Status**: Approved

## Summary

Redesign the Performance tab (Tab 3) in `session_detail.html` with 5 changes: add section tooltips, gate Tire Degradation behind 6h+ endurance sessions, replace Race Pace Predictor with a user-driven Race Pace Simulator (new endpoint), remove Efficiency & Smoothness Trend, and enrich Energy Balance.

## Change 1: Section Tooltips

Every `<h2>` in the Performance tab gets an `(i)` icon using `<span class="info-tip" data-tooltip="...">`. Pure CSS hover tooltip via `::after` pseudo-element.

### Tooltip Texts

| Section | Tooltip |
|---------|---------|
| Stint Analysis | Breaks your session into stints based on pace drops. Shows pace fade %, tyre cliff detection, and per-stint coaching. |
| Race Pace Simulator | Simulate race outcomes using your session data. Define race parameters and driver factors, then click Simulate. |
| Optimal Pit Window | Calculates the best lap range to pit based on stint degradation and pit loss time. |
| Tyre Performance | Compares grip and pace across stint phases (early/mid/late) to reveal tyre compound behaviour. |
| Driver Workload | Estimates physical and cognitive load per lap. Flags fatigue onset when complexity increases without pace improvement. |
| Session Timeline | Chronological view of key events — pace changes, incidents, pit stops — across the full session. |
| Energy Balance | Shows braking and acceleration energy per lap. Highlights energy recovery efficiency and driving smoothness patterns. |
| Tire Degradation | Analyses lap time trends to detect degradation rate, tyre cliff, and optimal stint length. Only available for 6h+ endurance sessions. |

### CSS

New `.info-tip` class in `main.css`:
```css
.info-tip {
    cursor: help;
    position: relative;
    font-size: 0.75rem;
    color: var(--text-secondary);
    margin-left: 0.4rem;
    vertical-align: middle;
}
.info-tip::after {
    content: attr(data-tooltip);
    position: absolute;
    /* standard tooltip positioning, hidden by default, shown on :hover */
}
```

### Files Modified
- `telemetry_tool/web/templates/session_detail.html`
- `telemetry_tool/web/static/css/main.css`

---

## Change 2: Tire Degradation — 6h+ Endurance Gate

### Visibility Rule
Show only when BOTH conditions are met:
1. `session_type` in (`endurance`, `endurance_race`, `endurance_stint`)
2. Sum of all lap times >= 21,600 seconds (6 hours)

### Implementation
- Backend: In the session detail route handler, compute `total_session_time_s` from the lap times query that already runs, pass to template.
- Frontend: `window.TELEMETRY.totalSessionTime` and `window.TELEMETRY.sessionType` checked by JS. If conditions not met, hide the `<section>` and skip API call.
- Template: Add `data-endurance-only="true"` attribute to the Tire Degradation section.
- No changes to `tire_degradation.py` or its API route.

### Files Modified
- `telemetry_tool/web/templates/session_detail.html`
- Session detail route handler (to inject `total_session_time`)

---

## Change 3: Race Pace Simulator (New)

### Overview
Replace the auto-fetching Race Pace Predictor with a user-driven Race Pace Simulator. Only visible for non-race session types (`practice`, `qualifying`, `warmup`, `test`).

### 10 User-Definable Parameters

**Race Scenario:**
1. `race_laps` (int) — Total race laps
2. `pit_stop_loss_s` (float) — Pit stop time loss in seconds
3. `num_pit_stops` (int) — Number of planned pit stops
4. `tire_deg_rate_s` (float) — Tire degradation rate in seconds/lap
5. `fuel_effect_s` (float) — Fuel/weight effect in seconds/lap lighter (0 for karts)

**Driver Capability:**
6. `target_lap_time_s` (float) — Target lap time, pre-filled from session best
7. `consistency_cv_pct` (float) — Consistency variance %, pre-filled from session CV
8. `fatigue_onset_lap` (int) — Fatigue onset lap, pre-filled from workload analysis if available
9. `stint_length` (int) — Expected stint length in laps before pace drops
10. `traffic_penalty_s` (float) — Traffic/dirty air penalty in seconds/lap

### Frontend — `pace_simulator.js` (new file)
- Renders two-column parameter form with pre-filled defaults
- Pre-fill data from existing `/api/session/<sid>/lap_times` and `/api/session/<sid>/workload`
- "Simulate" button POSTs to new endpoint
- Result renders into Canvas 2D chart + stats sidebar + coaching area
- Chart shows: predicted lap times with stint boundaries, pit stop markers, fatigue onset line, degradation trend

### Backend — `race_simulator.py` (new module)

```python
@dataclass
class SimulationParams:
    race_laps: int
    pit_stop_loss_s: float
    num_pit_stops: int
    tire_deg_rate_s: float
    fuel_effect_s: float
    target_lap_time_s: float
    consistency_cv_pct: float
    fatigue_onset_lap: int
    stint_length: int
    traffic_penalty_s: float

@dataclass
class SimulationResult:
    predicted_laps: list[float]      # per-lap predicted times
    total_race_time_s: float
    best_stint_pace_s: float
    worst_stint_pace_s: float
    pit_stop_laps: list[int]
    fatigue_impact_s: float          # total time lost to fatigue
    tire_impact_s: float             # total time lost to deg
    coaching: str                    # actionable summary
    confidence: float
```

Core logic: for each lap, compute `base_time + tire_deg_offset + fuel_offset + fatigue_offset + traffic_offset + random_variance(cv)`. Pit stops reset tire deg, insert pit loss.

### Backend — New API Route
```
POST /api/session/<sid>/simulate-race
Body: { race_laps, pit_stop_loss_s, ... }
Returns: SimulationResult as JSON
```

### Visibility Gating
- Section gets `data-non-race-only="true"` attribute
- JS hides it for race session types (inverse of `stint-race-only` logic)

### Files Created
- `telemetry_tool/race_simulator.py`
- `telemetry_tool/web/static/js/pace_simulator.js`

### Files Modified
- `telemetry_tool/web/routes/api_data.py` (new route)
- `telemetry_tool/web/templates/session_detail.html` (replace predictor section)

---

## Change 4: Remove Efficiency & Smoothness Trend

### What Gets Removed
- The `_drawTrend()` function in `energy_balance.js`
- The `#energy-trend-canvas` canvas element
- The "Efficiency & Smoothness Trend" label/section
- The "Efficiency", "Smoothness", and "Trend" summary cards

### Files Modified
- `telemetry_tool/web/static/js/energy_balance.js`

---

## Change 5: Enrich Energy Balance

### What Gets Added
1. **Energy Recovery Ratio** — new card: `(Braking kJ / Accel kJ) × 100%`. Tooltip: "Closer to 100% means heavy braking matches heavy acceleration — aim lower for smoother corner entries."
2. **Worst 3 Laps highlight** — bar chart highlights 3 laps with highest braking energy (red outline). Most potential for improvement.
3. **Lap-over-lap delta indicator** — small arrows on bars showing braking energy increase/decrease vs previous lap.
4. **Enriched coaching** — references specific lap numbers: "Laps 5, 8, 12 show 40%+ more braking energy than your average — review corner entries on these laps."

### Backend Changes to `energy_balance.py`
- Add `recovery_ratio` to `EnergyBalanceResult`
- Add `worst_braking_laps` (top 3 lap numbers by braking kJ)
- Improve `coaching` string to reference specific laps
- Remove `efficiency_trend` computation

### Frontend Changes to `energy_balance.js`
- Remove `_drawTrend()` function and trend canvas
- Remove efficiency/smoothness/trend cards
- Add recovery ratio card
- Add worst-lap highlights to bar chart
- Add delta arrows on bars

### Files Modified
- `telemetry_tool/energy_balance.py`
- `telemetry_tool/web/static/js/energy_balance.js`

---

## Final Tab Order

| # | Section | Visibility | Status |
|---|---------|------------|--------|
| 1 | Stint Analysis | Race types only | Unchanged + tooltip |
| 2 | Race Pace Simulator | Non-race types only | **New** (replaces Predictor) |
| 3 | Optimal Pit Window | Race types only | Unchanged + tooltip |
| 4 | Tyre Performance | Race types only | Unchanged + tooltip |
| 5 | Driver Workload | Always | Unchanged + tooltip |
| 6 | Session Timeline | Always | Unchanged + tooltip |
| 7 | Energy Balance | Always | **Enriched** + tooltip |
| 8 | Tire Degradation | Endurance 6h+ only | **Gated** + tooltip |

## Non-Breaking Guarantees
- Existing APIs untouched
- `race_pace_predictor.py` remains (used internally by scoring)
- `pace_predictor.js` can be deleted (no longer loaded)
- New simulator is a separate endpoint with no side effects
