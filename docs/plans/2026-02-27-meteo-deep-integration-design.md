# Meteo Deep Integration Design

**Date**: 2026-02-27
**Status**: Approved
**Scope**: Weather-enriched analysis pipeline, Adaptation scoring grade, race strategy weather alerts, condition-aware theoretical lap, weather-annotated reports

## Overview

Upgrade the existing Open-Meteo integration from a standalone dashboard/correlation tool into the core of the analysis pipeline. Every session analysis becomes weather-aware: per-lap conditions are interpolated from hourly API data, scoring includes a new Adaptation grade, reports show condition timelines and phase-specific insights, and the race strategy live dashboard gains rain alerts.

## Architecture

```
CSV Upload
  |
  v
parse_session_datetime() -----> date + time
  |                              |
  v                              v
Track Detection (GPS) ----> lat/lon
  |                              |
  v                              v
fetch_historical_weather(lat, lon, date) ----> hourly weather data
  |
  v
weather_timeline.py::build_weather_timeline(hourly, lap_timestamps)
  |    - interpolate per-lap: temp, humidity, wind, rain, weather_code
  |    - compute per-lap: grip_score, track_state, track_temp_est via estimate_track_conditions()
  |
  v
Pipeline Step 8e: weather_timeline DataFrame
  |
  +----> condition_tracking.py (enhanced: uses weather_timeline for label_phases)
  +----> theoretical_engine.py (grip-scaled + per-condition envelope)
  +----> scoring.py (_score_adaptation)
  +----> reporting_html.py (5 new sections)
  +----> DB: session_weather_laps table
```

## Workstream A: Per-Lap Weather Timeline

### New Module: `telemetry_tool/weather_timeline.py`

**Purpose**: Bridge between hourly API data and per-lap analysis.

**Functions**:

```python
def parse_session_datetime(csv_path: Path) -> Optional[datetime]:
    """Extract session date/time from RaceChrono CSV metadata headers.
    Tries: '# Date:' header, first GPS timestamp column, file modification time.
    Returns None if all fail."""

def build_weather_timeline(
    hourly_weather: dict,       # from fetch_historical_weather()
    lap_timestamps: list[float], # cumulative seconds from session start
    session_start: datetime,     # absolute start time
) -> pd.DataFrame:
    """Interpolate hourly weather to per-lap resolution.

    Returns DataFrame indexed by lap_number with columns:
    - timestamp (datetime), air_temp_c, humidity_pct, wind_speed_mps,
      wind_dir_deg, rain_mm, cloud_cover_pct, weather_code (WMO, nearest hour),
      grip_score, track_state, track_temp_est_c

    Uses linear interpolation for continuous vars (temp, humidity, wind, rain).
    WMO weather_code uses nearest-hour assignment (categorical, not interpolatable).
    """
```

**Pipeline Integration**: New step 8e between track evolution (8d2) and feature building (11).

```python
# In pipeline.py analyze_session():
def _weather_timeline():
    session_dt = parse_session_datetime(csv_path)
    if session_dt is None:
        session_dt = _try_user_provided_datetime(meta)  # from web form
    if session_dt is None:
        return None  # graceful skip

    track_coords = _get_track_coords(track_id, conn)
    if track_coords is None:
        return None

    hourly = fetch_historical_weather(track_coords.lat, track_coords.lon,
                                       session_dt.strftime("%Y-%m-%d"))
    if "error" in hourly:
        return None

    return build_weather_timeline(hourly, lap_timestamps, session_dt)

weather_tl, err = _safe_step("8e_weather_timeline", _weather_timeline)
summary["weather_timeline"] = weather_tl
```

**Fallback**: When `weather_timeline` is `None`, all downstream consumers use existing behavior (no regression).

### New DB Table: `session_weather_laps`

```sql
CREATE TABLE IF NOT EXISTS session_weather_laps (
    session_id   TEXT NOT NULL,
    lap_number   INTEGER NOT NULL,
    timestamp    TEXT,
    air_temp_c   REAL,
    humidity_pct REAL,
    wind_speed_mps REAL,
    wind_dir_deg REAL,
    rain_mm      REAL,
    cloud_cover_pct REAL,
    weather_code INTEGER,
    grip_score   REAL,
    track_state  TEXT,
    track_temp_est_c REAL,
    PRIMARY KEY (session_id, lap_number)
);
```

PostgreSQL variant adds `workspace_id` column + RLS policy.

### Session DateTime Extraction

Added to `io_racechrono.py` or as utility in `weather_timeline.py`:

```python
def parse_session_datetime(csv_path: Path) -> Optional[datetime]:
    """
    Priority order:
    1. RaceChrono '# Date:' / '# Time:' headers in first 20 lines
    2. First valid value in 'Time (s)' or 'Timestamp (s)' column + file date
    3. File modification time (last resort, often wrong)
    4. None (caller must prompt user)
    """
```

### Web UI Fallback

When `parse_session_datetime()` returns `None` and session is uploaded via web:
- Ingest route returns `{"needs_datetime": true}` in the SSE progress
- Frontend shows a date/time picker modal
- User submits → stored in `sessions.session_date` column
- Re-triggers weather timeline computation

## Workstream B: Adaptation Scoring Grade

### Score Redistribution

```python
MAX_PACE:        Final[float] = 25.0   # was 30
MAX_CONSISTENCY: Final[float] = 25.0   # unchanged
MAX_EXECUTION:   Final[float] = 20.0   # was 25
MAX_ROBUSTNESS:  Final[float] = 15.0   # was 20
MAX_ADAPTATION:  Final[float] = 15.0   # NEW
TOTAL_MAX:       Final[float] = 100.0
```

### Grade Thresholds (adjusted for 5th dimension)

```python
_GRADE_THRESHOLDS = [
    (90, "S"), (78, "A"), (63, "B"), (48, "C"), (33, "D")
]
# Below 33 = F
```

### `_score_adaptation()` Function

```python
def _score_adaptation(
    weather_timeline: Optional[pd.DataFrame],
    lap_metrics_df: pd.DataFrame,
    phases_df: Optional[pd.DataFrame],
    track_evolution: Optional[dict],
    theoretical_metrics: dict,
    simulation_method: str,
) -> dict[str, Any]:
    """
    Score driver's adaptation to changing conditions.

    Returns dict with:
      score (float, 0-MAX_ADAPTATION),
      transition_speed_score, phase_pace_score, technique_adaptation_score,
      details (dict with per-phase breakdown)
    """
```

**Sub-metrics**:

#### 1. Transition Speed (40% = 6.0 pts max)

When condition phases change (from `phases_df`):
- Measure laps-to-stabilize after each transition point
- Stabilized = CV of last 3 laps drops below 2x phase-average CV
- Full marks: avg <=2 laps to stabilize
- Zero marks: avg >=8 laps
- Decay exponent: 1.4

```python
ADAPT_TRANSITION_FULL_LAPS: Final[float] = 2.0
ADAPT_TRANSITION_ZERO_LAPS: Final[float] = 8.0
ADAPT_TRANSITION_WEIGHT:    Final[float] = 0.40
```

#### 2. Phase-Relative Pace (35% = 5.25 pts max)

For each phase, compare driver's best lap to the condition-adjusted theoretical:
- Grip-scaled theoretical: `theory_time / sqrt(phase_avg_grip_score / 100)`
- Gap = `(driver_best - adjusted_theory) / adjusted_theory * 100`
- Full marks: gap <= 3%
- Zero marks: gap >= 12%
- Weighted average across phases (by phase duration)

```python
ADAPT_PHASE_PACE_FULL_PCT: Final[float] = 3.0
ADAPT_PHASE_PACE_ZERO_PCT: Final[float] = 12.0
ADAPT_PHASE_PACE_WEIGHT:   Final[float] = 0.35
```

#### 3. Condition-Appropriate Execution (25% = 3.75 pts max)

Compare driving technique metrics between phases:
- Jerk RMS ratio (wet should be lower — smoother)
- Braking onset distance (wet should be earlier)
- Line length (wet may be wider)

For each metric, check if the change direction matches the expected adaptation:
- Correct direction: score proportional to magnitude
- Wrong direction: 0

```python
ADAPT_TECHNIQUE_WEIGHT: Final[float] = 0.25
```

#### Stable-Session Default

When `phases_df` has only 1 phase AND `track_evolution` shows no significant grip change:
- Return 75% of MAX_ADAPTATION (11.25 pts)
- Rationale: neutral — no opportunity to demonstrate adaptation

When `phases_df` has 1 phase BUT `track_evolution` shows grip improvement (rubbering in):
- Score based on how well the driver exploited the improvement
- Compare pace improvement vs expected pace from grip evolution

## Workstream C: Condition-Aware Theoretical Lap

### New Function in `theoretical_engine.py`

```python
def scale_theoretical_by_grip(
    theoretical_df: pd.DataFrame,
    grip_factor: float,  # 0.0-1.0 from grip_score/100
) -> pd.DataFrame:
    """
    Apply physics-based grip scaling to a dry theoretical lap.

    Speed: v_scaled = v_dry * sqrt(grip_factor)
    Accel: a_scaled = a_dry * grip_factor
    Braking: b_scaled = b_dry * grip_factor

    Returns new DataFrame with scaled columns.
    """
```

### Pipeline Step 10 Enhancement

```python
def _theoretical_lap():
    # Existing: build dry theoretical from historical laps
    dry_theo = build_theoretical_lap(laps, n_points)

    # NEW: determine session conditions
    dominant_state = _get_dominant_track_state(weather_timeline, phases_df)

    if dominant_state == "dry":
        return dry_theo, {"method": "envelope", "condition": "dry"}

    # Tier 2: check for condition-specific historical laps
    cond_laps = load_historical_laps(track_id, track_state=dominant_state)
    if cond_laps is not None and len(cond_laps) >= 5:
        cond_theo = build_theoretical_lap(cond_laps, n_points)
        # Tier 1: grip-scaled as anchor
        avg_grip = weather_timeline["grip_score"].mean() / 100.0
        scaled_theo = scale_theoretical_by_grip(dry_theo, avg_grip)
        # Blend: 70% condition envelope + 30% grip-scaled
        blended = 0.70 * cond_theo + 0.30 * scaled_theo
        return blended, {"method": "blended", "condition": dominant_state}

    # Tier 1 only: grip-scaled
    avg_grip = weather_timeline["grip_score"].mean() / 100.0
    return scale_theoretical_by_grip(dry_theo, avg_grip), {
        "method": "grip_scaled", "condition": dominant_state, "grip_factor": avg_grip
    }
```

### Per-Phase Theoretical (for Adaptation scoring)

For multi-phase sessions, compute a separate theoretical per phase:

```python
def get_phase_theoreticals(
    dry_theoretical: pd.DataFrame,
    weather_timeline: pd.DataFrame,
    phases_df: pd.DataFrame,
) -> dict[int, pd.DataFrame]:
    """Return {phase_id: theoretical_df} using per-phase average grip."""
```

## Workstream D: Race Strategy Weather Integration

### Weather Alerts in Live Dashboard

**Backend** (`web/routes/race_strategy_v2.py`):

```python
# In-memory forecast cache (per race)
_forecast_cache: dict[int, tuple[float, dict]] = {}
_FORECAST_CACHE_TTL = 300  # 5 minutes

def _check_weather_alerts(race_id: int, lat: float, lon: float, conn) -> Optional[dict]:
    """
    Check forecast for rain, generate alert if threshold exceeded.
    Returns alert dict or None.
    """
    now = time.time()
    cached = _forecast_cache.get(race_id)
    if cached and (now - cached[0]) < _FORECAST_CACHE_TTL:
        forecast = cached[1]
    else:
        forecast = get_weather_forecast(lat, lon, hours=3)
        _forecast_cache[race_id] = (now, forecast)

    if forecast.get("error"):
        return None

    # Check rain in next 2 hours
    upcoming = forecast.get("forecast", [])[:2]  # next 2 hourly slots
    max_prob = max((h.get("rain_prob_pct", 0) or 0) for h in upcoming) if upcoming else 0
    max_rain = max((h.get("rain_mm", 0) or 0) for h in upcoming) if upcoming else 0

    if max_prob < 50 and max_rain < 0.5:
        return None  # no alert needed

    # Check if alert already sent recently
    recent = conn.execute(
        "SELECT alert_id FROM race_alerts WHERE race_id = ? AND alert_type = 'weather' "
        "AND created_at > datetime('now', '-30 minutes')",
        (race_id,)
    ).fetchone()
    if recent:
        return None  # don't spam

    severity = "critical" if max_rain > 2 or max_prob > 80 else "warning"

    # Determine timing
    rain_hour = next(
        (h for h in upcoming if (h.get("rain_prob_pct", 0) or 0) > 50),
        None
    )
    eta_min = None
    if rain_hour:
        from datetime import datetime as dt
        rain_time = dt.fromisoformat(rain_hour["time"])
        eta_min = max(0, int((rain_time - dt.now()).total_seconds() / 60))

    # Get compound recommendation
    conditions = estimate_track_conditions({
        "air_temp_c": upcoming[0].get("air_temp_c", 20),
        "rain_mm": max_rain,
        "humidity_pct": upcoming[0].get("humidity_pct", 70),
    })

    msg = f"Rain {'expected' if max_rain < 0.5 else 'detected'}"
    if eta_min is not None:
        msg += f" in ~{eta_min}min"
    msg += f" ({max_prob:.0f}% probability, {max_rain:.1f}mm forecast)"
    msg += f". Recommended: {conditions.get('recommended_compound', 'wet')} tires."

    alert = {
        "race_id": race_id,
        "alert_type": "weather",
        "severity": severity,
        "message": msg,
        "payload_json": json.dumps({
            "rain_prob_pct": max_prob,
            "rain_mm_forecast": max_rain,
            "eta_minutes": eta_min,
            "recommended_compound": conditions.get("recommended_compound"),
            "grip_score": conditions.get("grip_score"),
        }),
    }

    conn.execute(
        "INSERT INTO race_alerts (race_id, alert_type, severity, message, payload_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (race_id, alert["alert_type"], alert["severity"], alert["message"], alert["payload_json"])
    )
    conn.commit()

    return alert
```

**Integration point**: Called from `api_state()` route (already polled every 3s by frontend). Only actually fetches forecast every 5 min due to cache.

**Frontend changes** (both Jinja2 live template and Next.js live page):
- Weather alert card: amber (warning) / red (critical) banner at top
- Current conditions widget: temp, grip bar, track state icon
- Forecast mini-bar: 3h horizontal colored by rain probability

### Strategy Adjustment

```python
def adjust_stints_for_weather(
    remaining_stints: list[dict],
    forecast: dict,
    config: dict,
) -> list[dict]:
    """
    Annotate remaining stints with weather risk and adjusted lap time estimates.

    For each stint:
    - Estimate conditions at stint time from forecast
    - Compute grip_factor → adjust expected lap time
    - Flag 'wet_risk' if rain probable during stint
    - Suggest compound if conditions warrant change

    Does NOT modify strategy — returns annotations for human decision.
    """
```

Called during `reoptimize_remaining()` when weather data is available.

## Workstream E: Weather-Enriched Reports

### New Report Sections in `reporting_html.py`

#### 1. Session Conditions Banner
Position: Below headline score, above sub-score breakdown.
Content: One-line weather summary + grip sparkline (30px tall SVG).

#### 2. Condition Timeline Strip
Position: Above lap time heatmap.
Content: Horizontal bar (lap-width segments) colored by track_state:
- Dry: #3ddc84 (green)
- Greasy: #ffd600 (yellow)
- Damp: #4fc3f7 (light blue)
- Wet: #1565c0 (dark blue)

Temperature curve overlay (orange line). Rain bars below (blue bars, height proportional to mm).

#### 3. Per-Phase Analysis Cards
Position: After condition timeline.
Content: Card per phase with:
- Phase label, lap range, duration
- Average conditions (temp, grip, state)
- Best lap vs condition-adjusted theoretical
- Adaptation notes

#### 4. Adaptation Score Breakdown
Position: In sub-scores section alongside pace, consistency, execution, robustness.
Content:
- 3 sub-metric bars (transition speed, phase pace, technique)
- Transition laps highlight on the lap time chart
- Per-phase theoretical comparison chart

#### 5. Enhanced Coaching
Position: In existing coaching section.
Content:
- Weather-contextual advice (condition-specific tips)
- Transition improvement suggestions
- Phase-specific drill recommendations

### `generate_report()` Signature Change

```python
def generate_report(
    score_result, best_lap, theoretical_lap, session_meta,
    delta_segments=None, lap_times=None, segment_losses=None,
    driver_profiles=None, comparison_sessions=None,
    # NEW optional kwargs:
    weather_timeline: Optional[pd.DataFrame] = None,
    adaptation_result: Optional[dict] = None,
    phase_theoreticals: Optional[dict] = None,
) -> str:
```

All new kwargs default to `None` → backward compatible.

## Database Changes

### New Alembic Migration (017)

```sql
-- session_weather_laps table
CREATE TABLE session_weather_laps (
    session_id      TEXT NOT NULL,
    lap_number      INTEGER NOT NULL,
    timestamp       TEXT,
    air_temp_c      REAL,
    humidity_pct    REAL,
    wind_speed_mps  REAL,
    wind_dir_deg    REAL,
    rain_mm         REAL,
    cloud_cover_pct REAL,
    weather_code    INTEGER,
    grip_score      REAL,
    track_state     TEXT,
    track_temp_est_c REAL,
    workspace_id    TEXT,
    PRIMARY KEY (session_id, lap_number)
);

-- RLS policy (PG only)
ALTER TABLE session_weather_laps ENABLE ROW LEVEL SECURITY;
CREATE POLICY session_weather_laps_tenant ON session_weather_laps
    USING (workspace_id = current_setting('app.workspace_id', true));

-- Add session_date column to sessions table if not exists
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS session_datetime TEXT;
```

SQLite version in `db/schema.py` phase 15 (or next phase).

## Testing Strategy

### Unit Tests

- `test_weather_timeline.py`:
  - `test_interpolation_between_hours` — verify linear interp for temp, humidity
  - `test_nearest_weather_code` — WMO codes use nearest hour
  - `test_missing_hours_graceful` — gaps in API data handled
  - `test_single_hour_session` — no interpolation needed
  - `test_empty_lap_timestamps` — returns empty DataFrame

- `test_scoring_adaptation.py`:
  - `test_multi_phase_transition_speed` — verify lap-count scoring
  - `test_single_phase_default` — returns 75% of max
  - `test_phase_relative_pace` — grip-adjusted theoretical comparison
  - `test_technique_adaptation_direction` — correct vs wrong direction
  - `test_score_redistribution_sums_to_100` — weight invariant

- `test_theoretical_grip_scaling.py`:
  - `test_grip_factor_1_no_change` — identity when dry
  - `test_grip_factor_0_5_halves_accel` — physics correct
  - `test_blended_envelope` — 70/30 blend math

- `test_strategy_weather_alerts.py`:
  - `test_rain_alert_threshold` — >50% triggers alert
  - `test_no_spam_30min` — dedup within window
  - `test_critical_severity` — >80% or >2mm = critical
  - `test_forecast_cache_ttl` — cached for 5 min

### Integration Test

- `test_pipeline_weather_integration.py`:
  - Full pipeline run with mocked `fetch_historical_weather()`
  - Verify `weather_timeline` flows through to scoring and report
  - Verify backward compat when weather unavailable

## File Changes Summary

| File | Change |
|------|--------|
| `telemetry_tool/weather_timeline.py` | **NEW** — Per-lap weather interpolation |
| `telemetry_tool/meteo_service.py` | Minor: add `pressure_hpa` to forecast if available |
| `telemetry_tool/scoring.py` | Redistribute weights, add `_score_adaptation()`, update `score_session()` |
| `telemetry_tool/theoretical_engine.py` | Add `scale_theoretical_by_grip()`, `get_phase_theoreticals()` |
| `telemetry_tool/condition_tracking.py` | Enhanced `label_phases()` to accept weather_timeline |
| `telemetry_tool/pipeline.py` | Add step 8e, wire weather_timeline through scoring and report |
| `telemetry_tool/reporting_html.py` | 5 new optional sections, signature change |
| `telemetry_tool/io_racechrono.py` | Add `parse_session_datetime()` |
| `telemetry_tool/race_strategy_v2.py` | Add `adjust_stints_for_weather()` |
| `telemetry_tool/web/routes/race_strategy_v2.py` | Add `_check_weather_alerts()`, integrate into `api_state()` |
| `telemetry_tool/web/templates/race_strategy/live.html` | Weather alert card, conditions widget |
| `lap-website/src/app/app/race-strategy/[id]/live/page.tsx` | Weather alert card, conditions widget |
| `telemetry_tool/db/schema.py` | Add `session_weather_laps` table |
| `alembic/versions/017_session_weather_laps.py` | **NEW** migration |
| Tests (5 new files) | ~40 new tests |

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Open-Meteo API down during analysis | Graceful fallback: `weather_timeline = None`, all downstream skips |
| Hourly resolution too coarse for rain onset | WMO weather codes add categorical granularity; condition_tracking's z-score detection fills gaps |
| Score redistribution breaks existing grades | Migration: re-score stored sessions OR grandfather old scores (display "scored with v1 weights") |
| Per-lap DB table grows large | Index on session_id; only store when weather_timeline is non-null; prune with session deletion cascade |
| grip_factor physics too simplified | The sqrt model is conservative; Tier 2 envelope data corrects when available |
