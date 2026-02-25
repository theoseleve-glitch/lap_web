# Performance Tab Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Redesign the Performance tab with section tooltips, 6h+ endurance gate on Tire Degradation, new Race Pace Simulator with user-driven parameters, removal of Efficiency & Smoothness Trend, and enriched Energy Balance.

**Architecture:** 5 independent changes to the Performance tab (Tab 3) in `session_detail.html`. Changes 1-2 are template/CSS only. Change 3 creates a new `race_simulator.py` backend module + `pace_simulator.js` frontend + API route. Changes 4-5 modify `energy_balance.py` and `energy_balance.js`. Existing tooltip CSS class `.tip` (with `data-tip` attribute) is reused — no new CSS class needed.

**Tech Stack:** Python 3.x, Flask, SQLite, Jinja2, vanilla JS (Canvas 2D), CSS. No npm/node.

**Design doc:** `docs/plans/2026-02-25-performance-tab-redesign.md`

**Security note:** All JS rendering uses the project's existing `esc()` function for user-facing text. The `esc()` function is globally available from the template and handles HTML entity escaping. All dynamic content rendered via innerHTML uses `esc()` for any user/data-sourced text values. Form inputs are numeric only (type="number") and validated server-side.

---

## Task 1: Add Section Tooltips to Performance Tab

**Files:**
- Modify: `telemetry_tool/web/templates/session_detail.html:452-529`

The project already has a CSS-only tooltip system (`.tip` class with `data-tip` attribute, `.tip-wrap` for multiline) at `telemetry_tool/web/static/css/main.css:6263-6394`. No new CSS needed.

**Step 1: Add `(i)` tooltip spans to each `<h2>` in the Performance tab**

Replace each section heading with the heading + tooltip span. The `(i)` icon reuses the existing `.tip .tip-bottom .tip-wrap` classes.

In `telemetry_tool/web/templates/session_detail.html`, update lines 452-529:

```html
<!-- Stint Analysis (race/sprint/endurance only) -->
<section class="section stint-race-only" data-race-types="race,sprint,endurance,sprint_race,feature_race,endurance_race,endurance_stint,heat,final">
    <h2>Stint Analysis <span class="tip tip-bottom tip-wrap" data-tip="Breaks your session into stints based on pace drops. Shows pace fade %, tyre cliff detection, and per-stint coaching.">(i)</span></h2>
    ...
</section>

<!-- Race Pace Simulator (non-race only, see Task 3) -->

<!-- Optimal Pit Window (race types only) -->
<section class="section stint-race-only" data-race-types="...">
    <h2>Optimal Pit Window <span class="tip tip-bottom tip-wrap" data-tip="Calculates the best lap range to pit based on stint degradation and pit loss time.">(i)</span></h2>
    ...
</section>

<!-- Tyre Performance (race types only) -->
<section class="section stint-race-only" data-race-types="...">
    <h2>Tyre Performance <span class="tip tip-bottom tip-wrap" data-tip="Compares grip and pace across stint phases (early/mid/late) to reveal tyre compound behaviour.">(i)</span></h2>
    ...
</section>

<!-- Driver Workload -->
<section class="section">
    <h2>Driver Workload <span class="tip tip-bottom tip-wrap" data-tip="Estimates physical and cognitive load per lap. Flags fatigue onset when complexity increases without pace improvement.">(i)</span></h2>
    ...
</section>

<!-- Session Timeline -->
<section class="section">
    <h2>Session Timeline <span class="tip tip-bottom tip-wrap" data-tip="Chronological view of key events — pace changes, incidents, pit stops — across the full session.">(i)</span></h2>
    ...
</section>

<!-- Energy Balance -->
<section class="section">
    <h2>Energy Balance <span class="tip tip-bottom tip-wrap" data-tip="Shows braking and acceleration energy per lap. Highlights energy recovery efficiency and worst braking laps.">(i)</span></h2>
    ...
</section>

<!-- Tire Degradation Analysis (endurance 6h+ only, see Task 2) -->
<section class="section" id="tire-deg-section" data-endurance-only="true">
    <h2>Tire Degradation Analysis <span class="tip tip-bottom tip-wrap" data-tip="Analyses lap time trends to detect degradation rate, tyre cliff, and optimal stint length. Only available for 6h+ endurance sessions.">(i)</span></h2>
    ...
</section>
```

**Step 2: Widen the tooltip max-width for section tips**

The existing `.tip-wrap` class sets `white-space: normal` but the base `.tip::after` has `max-width: 260px`. Add a wider variant for section headings.

In `telemetry_tool/web/static/css/main.css`, after the `.tip-wrap::after` rule (line ~6394), add:

```css
/* Wider tooltip for section info tips */
h2 .tip-wrap::after {
    max-width: 360px;
}
```

**Step 3: Verify tooltips render**

Run: `python telemetry_tool/main.py --serve`
Navigate to any session detail page, Performance tab. Hover over each `(i)` icon. Verify tooltip appears below the heading with multiline wrapping.

**Step 4: Commit**

```bash
git add telemetry_tool/web/templates/session_detail.html telemetry_tool/web/static/css/main.css
git commit -m "feat: add (i) hover tooltips to all Performance tab section headings"
```

---

## Task 2: Gate Tire Degradation Behind 6h+ Endurance

**Files:**
- Modify: `telemetry_tool/web/routes/sessions.py:46-83` (inject `total_session_time`)
- Modify: `telemetry_tool/web/templates/session_detail.html:825-834` (inject into TELEMETRY obj)
- Modify: `telemetry_tool/web/templates/session_detail.html:981-992` (add endurance guard)
- Modify: `telemetry_tool/web/templates/session_detail.html:523-529` (add data attribute + id)

**Step 1: Compute total session time in the route handler**

In `telemetry_tool/web/routes/sessions.py`, after `laps = get_laps_for_session(conn, session_id)` (line 53), add:

```python
    # Compute total session duration from lap times (for 6h+ endurance gate)
    total_session_time = sum(
        lap.get("lap_time_s", 0) or 0 for lap in laps
        if lap.get("lap_time_s") is not None
    )
```

Then pass it to the template in the `render_template` call (line 73-83):

```python
    return render_template(
        "session_detail.html",
        session=session,
        laps=laps,
        score=score,
        phases=phases,
        gps_laps=gps_laps,
        best_lap=best_lap,
        driving_style=driving_style,
        theoretical=theoretical,
        total_session_time=total_session_time,
    )
```

**Step 2: Inject session type and total time into JS TELEMETRY object**

In `telemetry_tool/web/templates/session_detail.html`, update the `window.TELEMETRY` block (lines 827-834):

```javascript
    window.TELEMETRY = {
        sessionId: {{ session.session_id|tojson }},
        trackId: {{ (session.track_id or '')|tojson }},
        sessionType: {{ (session.session_type or 'practice')|tojson }},
        totalSessionTime: {{ total_session_time|tojson }},
        {% if gps_laps %}
        gpsLaps: {{ gps_laps|tojson }},
        bestLap: {{ best_lap|tojson }},
        {% endif %}
    };
```

**Step 3: Add endurance guard JS alongside the existing race-only guard**

In `telemetry_tool/web/templates/session_detail.html`, after the race-only guard (line 992), add:

```javascript
    // ── Endurance 6h+ sections guard ─────────────────
    // Hide sections that only apply to 6h+ endurance sessions
    (function() {
        var sessionType = {{ (session.session_type or 'practice')|tojson }};
        var totalTime = {{ total_session_time|tojson }};
        var ENDURANCE_TYPES = ['endurance', 'endurance_race', 'endurance_stint'];
        var MIN_DURATION_S = 21600; // 6 hours

        var enduranceSections = document.querySelectorAll('[data-endurance-only]');
        enduranceSections.forEach(function(sec) {
            var isEndurance = ENDURANCE_TYPES.indexOf(sessionType) !== -1;
            var isLongEnough = totalTime >= MIN_DURATION_S;
            if (!isEndurance || !isLongEnough) {
                sec.style.display = 'none';
            }
        });
    })();
```

**Step 4: Add `data-endurance-only` attribute to the Tire Degradation section**

In `telemetry_tool/web/templates/session_detail.html`, change the Tire Degradation section (line 524):

From:
```html
<section class="section">
    <h2>Tire Degradation Analysis</h2>
```

To:
```html
<section class="section" data-endurance-only="true">
    <h2>Tire Degradation Analysis <span class="tip tip-bottom tip-wrap" data-tip="Analyses lap time trends to detect degradation rate, tyre cliff, and optimal stint length. Only available for 6h+ endurance sessions.">(i)</span></h2>
```

**Step 5: Verify the gate works**

Run: `python telemetry_tool/main.py --serve`
- Open a practice session -> Tire Degradation section should be hidden.
- If you have an endurance session with 6h+ of laps, verify it shows.

**Step 6: Commit**

```bash
git add telemetry_tool/web/routes/sessions.py telemetry_tool/web/templates/session_detail.html
git commit -m "feat: gate Tire Degradation section behind 6h+ endurance sessions"
```

---

## Task 3: Create Race Simulator Backend (`race_simulator.py`)

**Files:**
- Create: `telemetry_tool/race_simulator.py`
- Test: `telemetry_tool/tests/test_race_simulator.py`

**Step 1: Write failing tests**

Create `telemetry_tool/tests/test_race_simulator.py`:

```python
"""Tests for race_simulator.py -- deterministic race simulation engine."""
import math
import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from race_simulator import SimulationParams, simulate_race


def _default_params(**overrides) -> SimulationParams:
    """Helper to build params with sensible defaults."""
    defaults = dict(
        race_laps=25,
        pit_stop_loss_s=30.0,
        num_pit_stops=1,
        tire_deg_rate_s=0.05,
        fuel_effect_s=0.0,
        target_lap_time_s=62.0,
        consistency_cv_pct=1.5,
        fatigue_onset_lap=18,
        stint_length=12,
        traffic_penalty_s=0.3,
    )
    defaults.update(overrides)
    return SimulationParams(**defaults)


class TestSimulateRace:
    def test_basic_output_shape(self):
        params = _default_params()
        result = simulate_race(params)
        assert len(result.predicted_laps) == 25
        assert result.total_race_time_s > 0
        assert all(math.isfinite(t) for t in result.predicted_laps)

    def test_pit_stops_inserted(self):
        params = _default_params(num_pit_stops=2, stint_length=8, race_laps=25)
        result = simulate_race(params)
        assert len(result.pit_stop_laps) == 2
        # Pit stop laps should have the pit loss added
        for pit_lap in result.pit_stop_laps:
            assert result.predicted_laps[pit_lap - 1] > params.target_lap_time_s + params.pit_stop_loss_s * 0.5

    def test_no_pit_stops(self):
        params = _default_params(num_pit_stops=0)
        result = simulate_race(params)
        assert len(result.pit_stop_laps) == 0

    def test_tire_degradation_increases_times(self):
        params = _default_params(tire_deg_rate_s=0.1, num_pit_stops=0,
                                  fuel_effect_s=0.0, traffic_penalty_s=0.0,
                                  consistency_cv_pct=0.0, fatigue_onset_lap=999)
        result = simulate_race(params)
        # Later laps should be slower due to tire deg
        assert result.predicted_laps[-1] > result.predicted_laps[0]
        assert result.tire_impact_s > 0

    def test_fuel_effect_decreases_times(self):
        params = _default_params(fuel_effect_s=0.02, tire_deg_rate_s=0.0,
                                  num_pit_stops=0, traffic_penalty_s=0.0,
                                  consistency_cv_pct=0.0, fatigue_onset_lap=999)
        result = simulate_race(params)
        # Later laps should be slightly faster (lighter car)
        assert result.predicted_laps[-1] < result.predicted_laps[0]

    def test_fatigue_onset(self):
        params = _default_params(fatigue_onset_lap=10, tire_deg_rate_s=0.0,
                                  fuel_effect_s=0.0, traffic_penalty_s=0.0,
                                  consistency_cv_pct=0.0, num_pit_stops=0)
        result = simulate_race(params)
        assert result.fatigue_impact_s > 0
        # Laps after fatigue onset should be slower
        assert result.predicted_laps[15] > result.predicted_laps[5]

    def test_tire_resets_after_pit(self):
        params = _default_params(tire_deg_rate_s=0.1, num_pit_stops=1,
                                  stint_length=12, race_laps=24,
                                  fuel_effect_s=0.0, traffic_penalty_s=0.0,
                                  consistency_cv_pct=0.0, fatigue_onset_lap=999)
        result = simulate_race(params)
        # Lap after pit should be close to base time (tire deg reset)
        pit_lap = result.pit_stop_laps[0]
        if pit_lap < 24:
            next_lap_time = result.predicted_laps[pit_lap]  # 0-indexed: pit_lap is the next
            # Should be close to target since tire deg resets
            assert next_lap_time < params.target_lap_time_s + 0.5

    def test_deterministic(self):
        params = _default_params(consistency_cv_pct=0.0)
        r1 = simulate_race(params)
        r2 = simulate_race(params)
        assert r1.predicted_laps == r2.predicted_laps
        assert r1.total_race_time_s == r2.total_race_time_s

    def test_coaching_not_empty(self):
        params = _default_params()
        result = simulate_race(params)
        assert len(result.coaching) > 10

    def test_best_worst_stint_pace(self):
        params = _default_params(num_pit_stops=1, stint_length=12, race_laps=24)
        result = simulate_race(params)
        assert result.best_stint_pace_s > 0
        assert result.worst_stint_pace_s >= result.best_stint_pace_s

    def test_serialization(self):
        import json
        params = _default_params()
        result = simulate_race(params)
        d = result.to_dict()
        json.dumps(d)  # must not raise
        assert "predicted_laps" in d
        assert "coaching" in d
        assert "pit_stop_laps" in d

    def test_zero_race_laps(self):
        params = _default_params(race_laps=0)
        result = simulate_race(params)
        assert len(result.predicted_laps) == 0
        assert result.total_race_time_s == 0

    def test_single_lap_race(self):
        params = _default_params(race_laps=1, num_pit_stops=0)
        result = simulate_race(params)
        assert len(result.predicted_laps) == 1
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_race_simulator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'race_simulator'`

**Step 3: Write `race_simulator.py`**

Create `telemetry_tool/race_simulator.py`:

```python
"""
race_simulator.py
-----------------
Deterministic Race Pace Simulator -- predicts lap-by-lap race times from
user-defined parameters (tire deg, fuel effect, fatigue, pit stops, etc.).

Unlike race_pace_predictor.py (which extrapolates from actual session data),
this module runs a pure simulation: no DB, no session history. It takes
explicit parameters and produces a deterministic predicted timeline.

Public API
~~~~~~~~~~
- ``simulate_race(params: SimulationParams) -> SimulationResult``

Design Principles
~~~~~~~~~~~~~~~~~
- Pure functions; no global mutable state.
- Deterministic: identical inputs -> identical outputs.
- NaN-robust; all outputs are finite floats.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Final

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

FATIGUE_RATE_S_PER_LAP: Final[float] = 0.015  # seconds/lap after fatigue onset


# ============================================================================
# Data Structures
# ============================================================================


@dataclass
class SimulationParams:
    """User-defined simulation inputs."""
    race_laps: int = 25
    pit_stop_loss_s: float = 30.0
    num_pit_stops: int = 1
    tire_deg_rate_s: float = 0.05
    fuel_effect_s: float = 0.0
    target_lap_time_s: float = 62.0
    consistency_cv_pct: float = 1.5
    fatigue_onset_lap: int = 18
    stint_length: int = 12
    traffic_penalty_s: float = 0.3


@dataclass
class SimulationResult:
    """Output of the race simulation."""
    predicted_laps: list[float] = field(default_factory=list)
    total_race_time_s: float = 0.0
    best_stint_pace_s: float = 0.0
    worst_stint_pace_s: float = 0.0
    pit_stop_laps: list[int] = field(default_factory=list)
    fatigue_impact_s: float = 0.0
    tire_impact_s: float = 0.0
    coaching: str = ""
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "predicted_laps": [round(t, 3) for t in self.predicted_laps],
            "total_race_time_s": round(self.total_race_time_s, 3),
            "best_stint_pace_s": round(self.best_stint_pace_s, 3),
            "worst_stint_pace_s": round(self.worst_stint_pace_s, 3),
            "pit_stop_laps": self.pit_stop_laps,
            "fatigue_impact_s": round(self.fatigue_impact_s, 3),
            "tire_impact_s": round(self.tire_impact_s, 3),
            "coaching": self.coaching,
            "confidence": round(self.confidence, 3),
        }


# ============================================================================
# Simulation Engine
# ============================================================================


def simulate_race(params: SimulationParams) -> SimulationResult:
    """
    Run a deterministic race simulation.

    For each lap, the predicted time is:
        base_time + tire_deg + fuel_offset + fatigue + traffic

    Pit stops are inserted at stint boundaries. Tire degradation resets
    after each pit stop. Fuel effect is cumulative (lighter each lap).
    Fatigue kicks in after fatigue_onset_lap.

    Parameters
    ----------
    params : SimulationParams
        All 10 user-defined simulation inputs.

    Returns
    -------
    SimulationResult
    """
    result = SimulationResult()

    if params.race_laps <= 0:
        return result

    # Determine pit stop laps (evenly spaced by stint length)
    pit_laps = _compute_pit_laps(
        params.race_laps, params.num_pit_stops, params.stint_length,
    )
    result.pit_stop_laps = pit_laps

    # Track tire age (laps since last pit / start)
    tire_age = 0
    total_fatigue = 0.0
    total_tire_deg = 0.0
    stint_times: list[list[float]] = [[]]

    for lap in range(1, params.race_laps + 1):
        base = params.target_lap_time_s

        # Tire degradation: increases with tire age
        tire_offset = params.tire_deg_rate_s * tire_age
        total_tire_deg += tire_offset

        # Fuel effect: car gets lighter each lap (negative offset = faster)
        fuel_offset = -params.fuel_effect_s * (lap - 1)

        # Fatigue: kicks in after onset lap
        fatigue_offset = 0.0
        if lap > params.fatigue_onset_lap:
            laps_fatigued = lap - params.fatigue_onset_lap
            fatigue_offset = FATIGUE_RATE_S_PER_LAP * laps_fatigued
            total_fatigue += fatigue_offset

        # Traffic penalty (constant per lap)
        traffic = params.traffic_penalty_s

        # Compute lap time (no randomness -- deterministic)
        lap_time = base + tire_offset + fuel_offset + fatigue_offset + traffic

        # Pit stop: add pit loss to this lap
        is_pit = lap in pit_laps
        if is_pit:
            lap_time += params.pit_stop_loss_s
            tire_age = 0  # reset tire after pit
            # Start new stint
            stint_times.append([])
        else:
            tire_age += 1

        result.predicted_laps.append(round(lap_time, 3))
        stint_times[-1].append(lap_time)

    result.total_race_time_s = sum(result.predicted_laps)
    result.fatigue_impact_s = total_fatigue
    result.tire_impact_s = total_tire_deg

    # Best/worst stint pace
    stint_avgs = []
    for stint in stint_times:
        if not stint:
            continue
        stint_avg = sum(stint) / len(stint)
        stint_avgs.append(stint_avg)

    if stint_avgs:
        result.best_stint_pace_s = min(stint_avgs)
        result.worst_stint_pace_s = max(stint_avgs)

    # Confidence: based on how many user params are non-zero
    non_default_count = sum([
        params.tire_deg_rate_s > 0,
        params.fuel_effect_s > 0,
        params.fatigue_onset_lap < params.race_laps,
        params.traffic_penalty_s > 0,
        params.num_pit_stops > 0,
    ])
    result.confidence = min(1.0, 0.5 + non_default_count * 0.1)

    result.coaching = _generate_coaching(params, result)

    logger.info(
        "Race simulation: %d laps, total=%.1fs, pits=%d, tire_impact=%.1fs, fatigue=%.1fs",
        params.race_laps, result.total_race_time_s,
        len(pit_laps), result.tire_impact_s, result.fatigue_impact_s,
    )

    return result


def _compute_pit_laps(
    race_laps: int, num_pits: int, stint_length: int,
) -> list[int]:
    """Compute which laps to pit on, evenly spaced by stint length."""
    if num_pits <= 0 or race_laps <= 1:
        return []

    pits = []
    for i in range(1, num_pits + 1):
        pit_lap = i * stint_length
        if pit_lap < race_laps:
            pits.append(pit_lap)

    return pits[:num_pits]


def _generate_coaching(params: SimulationParams, result: SimulationResult) -> str:
    """Generate actionable coaching from simulation results."""
    parts: list[str] = []

    parts.append(
        f"Simulated {params.race_laps}-lap race: "
        f"total {result.total_race_time_s / 60:.1f} min."
    )

    if result.tire_impact_s > 5:
        parts.append(
            f"Tire degradation adds {result.tire_impact_s:.1f}s total. "
            f"Consider an extra pit stop if deg rate exceeds "
            f"{params.tire_deg_rate_s * 2:.2f}s/lap."
        )

    if result.fatigue_impact_s > 3:
        parts.append(
            f"Fatigue costs {result.fatigue_impact_s:.1f}s after lap "
            f"{params.fatigue_onset_lap}. "
            f"Physical conditioning could delay onset."
        )

    if params.traffic_penalty_s > 0.5:
        parts.append(
            f"Traffic adds {params.traffic_penalty_s:.1f}s/lap -- "
            f"qualifying higher reduces this significantly."
        )

    if params.fuel_effect_s > 0 and params.race_laps > 10:
        saved = params.fuel_effect_s * params.race_laps
        parts.append(
            f"Fuel burn-off saves {saved:.1f}s over the race -- "
            f"late-stint pace will be naturally faster."
        )

    if len(result.pit_stop_laps) > 0:
        pit_str = ", ".join(f"L{p}" for p in result.pit_stop_laps)
        parts.append(f"Pit stops on: {pit_str}.")

    return " ".join(parts)
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_race_simulator.py -v`
Expected: All 12 tests PASS.

**Step 5: Commit**

```bash
git add telemetry_tool/race_simulator.py telemetry_tool/tests/test_race_simulator.py
git commit -m "feat: add race_simulator.py deterministic simulation engine with tests"
```

---

## Task 4: Add Simulate-Race API Route

**Files:**
- Modify: `telemetry_tool/web/routes/api_data.py` (add route after line ~1855)

**Step 1: Add the POST route**

In `telemetry_tool/web/routes/api_data.py`, after the existing `api_pace_prediction` function (around line 1860), add:

```python
# ------------------------------------------------------------------
# Race Pace Simulator API (user-driven)
# ------------------------------------------------------------------

@bp.route("/session/<session_id>/simulate-race", methods=["POST"])
def api_simulate_race(session_id: str):
    """Run a deterministic race simulation with user-defined parameters."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if not row:
        return jsonify({"error": "Session not found"}), 404

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    try:
        from race_simulator import SimulationParams, simulate_race

        params = SimulationParams(
            race_laps=int(data.get("race_laps", 25)),
            pit_stop_loss_s=float(data.get("pit_stop_loss_s", 30.0)),
            num_pit_stops=int(data.get("num_pit_stops", 1)),
            tire_deg_rate_s=float(data.get("tire_deg_rate_s", 0.05)),
            fuel_effect_s=float(data.get("fuel_effect_s", 0.0)),
            target_lap_time_s=float(data.get("target_lap_time_s", 62.0)),
            consistency_cv_pct=float(data.get("consistency_cv_pct", 1.5)),
            fatigue_onset_lap=int(data.get("fatigue_onset_lap", 18)),
            stint_length=int(data.get("stint_length", 12)),
            traffic_penalty_s=float(data.get("traffic_penalty_s", 0.3)),
        )

        result = simulate_race(params)
        d = result.to_dict()
        d["session_id"] = session_id
        return jsonify(d)
    except (ValueError, TypeError) as exc:
        return jsonify({"error": f"Invalid parameter: {exc}"}), 400
    except ImportError:
        return jsonify({"error": "race_simulator module not available"}), 500
```

**Step 2: Verify route is accessible**

Run: `python telemetry_tool/main.py --serve`
Test with curl (replace `<sid>` with a real session ID):
```bash
curl -X POST http://localhost:5000/api/session/<sid>/simulate-race \
  -H "Content-Type: application/json" \
  -d '{"race_laps":20,"target_lap_time_s":62.0,"num_pit_stops":1,"stint_length":10}'
```
Expected: JSON response with `predicted_laps`, `coaching`, etc.

**Step 3: Commit**

```bash
git add telemetry_tool/web/routes/api_data.py
git commit -m "feat: add POST /api/session/<sid>/simulate-race endpoint"
```

---

## Task 5: Create Race Pace Simulator Frontend (`pace_simulator.js`)

**Files:**
- Create: `telemetry_tool/web/static/js/pace_simulator.js`
- Modify: `telemetry_tool/web/templates/session_detail.html:463-475` (replace predictor section)
- Modify: `telemetry_tool/web/templates/session_detail.html:953-970` (swap script tag)

**Step 1: Create `pace_simulator.js`**

Create `telemetry_tool/web/static/js/pace_simulator.js`.

This module renders a parameter form with 10 numeric inputs (grouped in two columns: Race Scenario and Driver Capability), a Simulate button, and on submit POSTs to `/api/session/<sid>/simulate-race`. The result renders into a Canvas 2D chart showing predicted lap times with pit stop markers + stats sidebar + coaching.

Key implementation details:
- Uses the project's existing `esc()` function for all data-sourced text to prevent XSS
- Uses `FetchHelper.fetch()` for API calls (project convention)
- Uses `FetchHelper.lazyInit()` for deferred loading when tab becomes visible
- Pre-fills target lap time from session best lap, CV from session stats, fatigue onset from workload API
- All form inputs are `type="number"` with appropriate `step` attributes
- Chart drawing follows same Canvas 2D pattern as other chart modules (DPR-aware, responsive)
- Stats sidebar uses same card layout pattern as `pace_predictor.js`

See design doc for full specification. The JS file should be approximately 350 lines following the patterns in `pace_predictor.js` and `energy_balance.js`.

**Step 2: Add simulator form CSS to `main.css`**

In `telemetry_tool/web/static/css/main.css`, at the end of the file, add styles for `.sim-form-grid`, `.sim-form-group`, `.sim-group-title`, `.sim-field`, `.sim-input`, `.sim-btn-icon`. See design doc for full specification.

**Step 3: Replace the Pace Predictor section in the template**

In `telemetry_tool/web/templates/session_detail.html`, replace lines 463-475 (the Race Pace Predictor section) with:

```html
<!-- Race Pace Simulator (non-race only) -->
<section class="section" data-non-race-only="true">
    <h2>Race Pace Simulator <span class="tip tip-bottom tip-wrap" data-tip="Simulate race outcomes using your session data. Define race parameters and driver factors, then click Simulate.">(i)</span></h2>
    <div id="pace-simulator-container">
        <div class="no-data"><div class="spinner-inline spinner-accent"></div><span class="text-secondary text-sm">Loading simulator...</span></div>
    </div>
</section>
```

**Step 4: Add non-race-only guard JS**

In `telemetry_tool/web/templates/session_detail.html`, after the endurance guard (added in Task 2), add:

```javascript
    // ── Non-race sections guard ──────────────────
    // Hide sections that only apply to non-race sessions (e.g., simulator)
    (function() {
        var sessionType = {{ (session.session_type or 'practice')|tojson }};
        var RACE_TYPES = ['race', 'sprint', 'endurance', 'sprint_race',
                          'feature_race', 'endurance_race', 'endurance_stint',
                          'heat', 'final'];

        var nonRaceSections = document.querySelectorAll('[data-non-race-only]');
        nonRaceSections.forEach(function(sec) {
            if (RACE_TYPES.indexOf(sessionType) !== -1) {
                sec.style.display = 'none';
            }
        });
    })();
```

**Step 5: Update script tags**

In `telemetry_tool/web/templates/session_detail.html`, in the script loading section (~lines 953-970), replace:

```html
<script src="{{ url_for('static', filename='js/pace_predictor.js') }}"></script>
```

with:

```html
<script src="{{ url_for('static', filename='js/pace_simulator.js') }}"></script>
```

**Step 6: Verify in browser**

Run: `python telemetry_tool/main.py --serve`
- Open a practice session: Race Pace Simulator section with form should appear.
- Fill in parameters, click Simulate: chart + stats + coaching render.
- Open a race session: Simulator section should be hidden.

**Step 7: Commit**

```bash
git add telemetry_tool/web/static/js/pace_simulator.js telemetry_tool/web/static/css/main.css telemetry_tool/web/templates/session_detail.html
git commit -m "feat: add Race Pace Simulator UI with parameter form and non-race gating"
```

---

## Task 6: Enrich Energy Balance Backend

**Files:**
- Modify: `telemetry_tool/energy_balance.py:86-113` (EnergyBalanceResult), `300-328` (_generate_coaching)
- Test: `telemetry_tool/tests/test_energy_balance_enriched.py`

**Step 1: Write failing tests**

Create `telemetry_tool/tests/test_energy_balance_enriched.py`:

```python
"""Tests for enriched energy balance (recovery ratio, worst laps, coaching)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from energy_balance import analyze_energy_balance


class TestRecoveryRatio:
    def test_recovery_ratio_present(self):
        times = [60.0 + i * 0.1 for i in range(10)]
        r = analyze_energy_balance(times)
        d = r.to_dict()
        assert "recovery_ratio" in d
        assert 0 < d["recovery_ratio"] <= 200  # percentage

    def test_constant_speed_ratio(self):
        # Very similar times -> ratio close to 100%
        times = [60.0, 60.01, 60.02, 60.01, 60.0]
        r = analyze_energy_balance(times)
        assert 80 < r.to_dict()["recovery_ratio"] < 120


class TestWorstBrakingLaps:
    def test_worst_laps_present(self):
        times = [60.0 + i * 0.1 for i in range(10)]
        r = analyze_energy_balance(times)
        d = r.to_dict()
        assert "worst_braking_laps" in d
        assert isinstance(d["worst_braking_laps"], list)
        assert len(d["worst_braking_laps"]) <= 3

    def test_worst_laps_are_valid_numbers(self):
        times = [60.0, 61.0, 62.0, 60.5, 63.0]
        r = analyze_energy_balance(times)
        d = r.to_dict()
        for lap_num in d["worst_braking_laps"]:
            assert isinstance(lap_num, int)
            assert lap_num >= 1


class TestEnrichedCoaching:
    def test_coaching_mentions_lap_numbers(self):
        times = [60.0 + i * 0.2 for i in range(10)]
        r = analyze_energy_balance(times)
        assert r.coaching != ""

    def test_coaching_not_empty(self):
        times = [60.0, 60.5, 61.0]
        r = analyze_energy_balance(times)
        assert len(r.coaching) > 10


class TestEfficiencyTrendRemoved:
    def test_no_efficiency_trend_in_dict(self):
        """efficiency_trend field should no longer be in the output dict."""
        times = [60.0 + i * 0.1 for i in range(10)]
        r = analyze_energy_balance(times)
        d = r.to_dict()
        assert "efficiency_trend" not in d
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_energy_balance_enriched.py -v`
Expected: FAIL -- `recovery_ratio` and `worst_braking_laps` not in dict, `efficiency_trend` still present.

**Step 3: Update `EnergyBalanceResult` dataclass**

In `telemetry_tool/energy_balance.py`, modify the `EnergyBalanceResult` dataclass (lines 86-113):

- Add fields: `recovery_ratio: float = 0.0` and `worst_braking_laps: list[int] = field(default_factory=list)`
- Remove `efficiency_trend` from `to_dict()` output
- Add `recovery_ratio` and `worst_braking_laps` to `to_dict()` output

**Step 4: Compute recovery ratio and worst laps in `analyze_energy_balance()`**

In `telemetry_tool/energy_balance.py`, after the best/worst efficiency block (after line 283), add:

```python
    # Recovery ratio: braking / accel as percentage
    if result.total_accel_kj > 0:
        result.recovery_ratio = (result.total_braking_kj / result.total_accel_kj) * 100
    else:
        result.recovery_ratio = 0.0

    # Worst 3 braking laps (highest braking energy)
    sorted_by_braking = sorted(
        result.lap_metrics, key=lambda m: m.braking_energy_j, reverse=True,
    )
    result.worst_braking_laps = [m.lap_number for m in sorted_by_braking[:3]]
```

**Step 5: Update `_generate_coaching()` to reference specific laps**

Replace the `_generate_coaching` function with a version that references worst braking laps by number and uses recovery_ratio instead of raw braking/accel ratio. See design doc for details.

**Step 6: Update inline self-tests**

In the `_run_tests()` function at the bottom of `energy_balance.py`, update test 10 (serialization) to not check for `efficiency_trend`, and instead check for `recovery_ratio` and `worst_braking_laps`.

**Step 7: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_energy_balance_enriched.py -v`
Expected: All tests PASS.

Run: `python telemetry_tool/energy_balance.py` (inline self-tests)
Expected: All 12 tests pass.

**Step 8: Commit**

```bash
git add telemetry_tool/energy_balance.py telemetry_tool/tests/test_energy_balance_enriched.py
git commit -m "feat: enrich energy balance with recovery ratio, worst braking laps, and specific coaching"
```

---

## Task 7: Update Energy Balance Frontend (`energy_balance.js`)

**Files:**
- Modify: `telemetry_tool/web/static/js/energy_balance.js`

**Step 1: Remove Efficiency & Smoothness Trend**

In `telemetry_tool/web/static/js/energy_balance.js`:

1. Delete the entire `_drawTrend()` function (lines 170-234).
2. In the `render()` function (line 35), remove:
   - The Efficiency & Smoothness Trend canvas block (lines 63-67)
   - The Efficiency, Smoothness, and Trend summary cards from the cards section (lines 48-52)
   - The `setTimeout` call to `_drawTrend(data)` (line 81)

**Step 2: Add Recovery Ratio card**

In the `render()` function, in the summary cards area, add a Recovery Ratio card using the existing `_card()` helper:

```javascript
html += _card("Recovery Ratio",
    (data.recovery_ratio || 0).toFixed(0) + "%",
    data.recovery_ratio > 110 ? COLORS.braking :
    data.recovery_ratio < 90 ? COLORS.accel : COLORS.text);
```

**Step 3: Highlight worst braking laps in the bar chart**

In the `_drawEnergyBars()` function, after drawing the bars, add a highlight pass that draws a red outline around the 3 worst braking laps:

```javascript
// Highlight worst braking laps
var worstLaps = data.worst_braking_laps || [];
laps.forEach(function (l, i) {
    if (worstLaps.indexOf(l.lap_number) !== -1) {
        var gx = pad.left + i * barGroupW;
        var bH = (l.braking_energy_kj / maxE) * plotH;
        ctx.strokeStyle = COLORS.braking;
        ctx.lineWidth = 2;
        ctx.strokeRect(gx + 1, pad.top + plotH - bH - 1, barW + 2, bH + 2);
    }
});
```

**Step 4: Add delta arrows on bars**

In the `_drawEnergyBars()` function, inside the `laps.forEach` loop, after drawing the bars, add delta arrows showing increase/decrease vs previous lap.

**Step 5: Verify in browser**

Run: `python telemetry_tool/main.py --serve`
Open any session detail, Performance tab, Energy Balance section. Verify:
- No Efficiency & Smoothness Trend chart
- Recovery Ratio card appears
- Worst braking laps have red outlines
- Delta arrows appear on bars

**Step 6: Commit**

```bash
git add telemetry_tool/web/static/js/energy_balance.js
git commit -m "feat: remove efficiency trend, add recovery ratio card, worst-lap highlights, and delta arrows"
```

---

## Task 8: Final Integration Test

**Files:** None modified -- verification only.

**Step 1: Run all tests**

Run: `pytest telemetry_tool/tests/ -v`
Expected: All tests pass, including new `test_race_simulator.py` and `test_energy_balance_enriched.py`.

**Step 2: Visual verification**

Run: `python telemetry_tool/main.py --serve`

Verify on a **practice session**:
- All 8 sections have `(i)` tooltips that show on hover
- Race Pace Simulator appears with 10-field form
- Simulate button works and renders chart + stats + coaching
- Tire Degradation section is hidden (not endurance 6h+)
- Energy Balance has Recovery Ratio card, worst-lap highlights, delta arrows, no trend chart
- Stint Analysis / Pit Window / Tyre Performance are hidden (not race type)

Verify on a **race session** (if available):
- Race Pace Simulator is hidden
- Stint Analysis / Pit Window / Tyre Performance are visible
- Other sections behave correctly

**Step 3: Commit any fixes**

```bash
git add -A
git commit -m "chore: final integration fixes for Performance tab redesign"
```
