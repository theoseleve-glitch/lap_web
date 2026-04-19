# Per-Corner Aggregate Coaching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For each detected corner, compare the driver's performance to the track's aggregate physics limits and generate template-based coaching narratives explaining what to change and why.

**Architecture:** A single new module `corner_coaching_aggregate.py` computes proven limits from the track surface aggregate, classifies root causes, and generates narrative text. An API endpoint serves it on-demand (no pipeline changes). A new React component renders the coaching cards.

**Tech Stack:** Python 3.14 / NumPy (backend), Next.js 14 / TypeScript / Canvas-free pure JSX (frontend), PostgreSQL track_surfaces table.

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `telemetry_tool/corner_coaching_aggregate.py` | Proven limits, root cause classification, narrative generation | Create |
| `telemetry_tool/tests/test_corner_coaching_aggregate.py` | Tests for all functions | Create |
| `telemetry_tool/web/routes/data_v2.py` | `/corner-coaching-v4` API endpoint | Modify |
| `lap-website/src/components/shared/charts/CornerCoachingV4.tsx` | Coaching UI component | Create |
| `lap-website/src/components/app/analytics/AnalyticsTab.tsx` | Wire CornerCoachingV4 into session view | Modify |

---

## Task 1: Proven Limits + Actual Metrics

**Files:**
- Create: `telemetry_tool/corner_coaching_aggregate.py`
- Create: `telemetry_tool/tests/test_corner_coaching_aggregate.py`

- [ ] **Step 1: Write test for `compute_proven_limits`**

Create `telemetry_tool/tests/test_corner_coaching_aggregate.py`:

```python
"""Tests for corner_coaching_aggregate.py."""
from __future__ import annotations

import numpy as np
import pytest

from corner_coaching_aggregate import (
    CornerProven,
    CornerActual,
    compute_proven_limits,
    compute_actual_metrics,
)
from track_surface import AggregateGrip


def _make_aggregate(n=100, mu=1.2):
    dist = np.linspace(0, 500, n)
    return AggregateGrip(
        distance_bins=dist,
        mu_p95=np.full(n, mu),
        mu_mean=np.full(n, mu * 0.9),
        mu_lon_accel=np.full(n, 0.4),
        mu_lon_brake=np.full(n, 0.9),
        session_count=10,
        track_id="test",
    )


def _make_corners():
    return [
        {"corner_id": 1, "corner_name": "T1", "direction": "R",
         "s_start": 100.0, "s_apex": 130.0, "s_end": 160.0,
         "curvature_1pm": 0.02},
        {"corner_id": 2, "corner_name": "T2", "direction": "L",
         "s_start": 250.0, "s_apex": 280.0, "s_end": 310.0,
         "curvature_1pm": 0.01},
    ]


class TestComputeProvenLimits:
    def test_returns_one_entry_per_corner(self):
        agg = _make_aggregate()
        corners = _make_corners()
        result = compute_proven_limits(agg, corners)
        assert len(result) == 2

    def test_proven_speeds_are_positive(self):
        agg = _make_aggregate(mu=1.2)
        corners = _make_corners()
        result = compute_proven_limits(agg, corners)
        for p in result:
            assert p.entry_kph > 0
            assert p.apex_kph > 0
            assert p.exit_kph > 0

    def test_higher_grip_gives_higher_speed(self):
        corners = _make_corners()
        low = compute_proven_limits(_make_aggregate(mu=0.8), corners)
        high = compute_proven_limits(_make_aggregate(mu=1.4), corners)
        assert high[0].apex_kph > low[0].apex_kph

    def test_tighter_corner_gives_lower_speed(self):
        agg = _make_aggregate(mu=1.2)
        corners = _make_corners()
        result = compute_proven_limits(agg, corners)
        # T1 has kappa=0.02 (tighter), T2 has kappa=0.01 (wider)
        assert result[0].apex_kph < result[1].apex_kph


class TestComputeActualMetrics:
    def test_extracts_speeds_at_corner_points(self):
        distances = np.linspace(0, 500, 200)
        speeds_mps = np.full(200, 25.0)  # constant 90kph
        accel_mps2 = np.zeros(200)
        corners = _make_corners()
        result = compute_actual_metrics(distances, speeds_mps, accel_mps2, corners)
        assert len(result) == 2
        for a in result:
            assert abs(a.entry_kph - 90.0) < 2.0
            assert abs(a.apex_kph - 90.0) < 2.0

    def test_detects_brake_point(self):
        distances = np.linspace(0, 500, 500)
        speeds_mps = np.full(500, 30.0)
        accel_mps2 = np.zeros(500)
        # Simulate braking before T1 (s_start=100)
        brake_zone = (distances >= 80) & (distances <= 100)
        accel_mps2[brake_zone] = -5.0  # heavy braking
        speeds_mps[brake_zone] = np.linspace(30, 22, brake_zone.sum())
        corners = _make_corners()
        result = compute_actual_metrics(distances, speeds_mps, accel_mps2, corners)
        assert result[0].brake_point_m is not None
        assert 75 < result[0].brake_point_m < 100
```

- [ ] **Step 2: Write `compute_proven_limits` and `compute_actual_metrics`**

Create `telemetry_tool/corner_coaching_aggregate.py`:

```python
"""
corner_coaching_aggregate.py
----------------------------
Per-corner aggregate coaching: computes proven limits from the track
surface, classifies root causes, and generates narrative coaching text.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

_G = 9.80665
_BRAKE_THRESHOLD_G = 0.3  # decel threshold to detect braking onset
_BRAKE_SEARCH_M = 80      # search window before corner entry


@dataclass
class CornerProven:
    """Proven limits for one corner from aggregate data."""
    corner_id: int
    entry_kph: float
    apex_kph: float
    exit_kph: float
    brake_point_m: float | None

    def to_dict(self) -> dict:
        return {
            "entry_kph": round(self.entry_kph, 1),
            "apex_kph": round(self.apex_kph, 1),
            "exit_kph": round(self.exit_kph, 1),
            "brake_point_m": round(self.brake_point_m, 1) if self.brake_point_m else None,
        }


@dataclass
class CornerActual:
    """Actual performance for one corner from this session."""
    corner_id: int
    entry_kph: float
    apex_kph: float
    exit_kph: float
    brake_point_m: float | None

    def to_dict(self) -> dict:
        return {
            "entry_kph": round(self.entry_kph, 1),
            "apex_kph": round(self.apex_kph, 1),
            "exit_kph": round(self.exit_kph, 1),
            "brake_point_m": round(self.brake_point_m, 1) if self.brake_point_m else None,
        }


def _speed_at_grip(mu: float, kappa: float) -> float:
    """v = sqrt(mu * g / kappa), capped at 360kph."""
    if kappa < 1e-6:
        return 100.0  # straight
    v_mps = math.sqrt(mu * _G / kappa)
    return min(v_mps * 3.6, 360.0)


def compute_proven_limits(
    aggregate_grip: "AggregateGrip",
    corners: list[dict],
) -> list[CornerProven]:
    """Compute proven entry/apex/exit speeds from aggregate grip + curvature."""
    results = []
    for c in corners:
        cid = c.get("corner_id", 0)
        s_start = c.get("s_start", 0.0)
        s_apex = c.get("s_apex", s_start)
        s_end = c.get("s_end", s_apex)
        kappa = abs(c.get("curvature_1pm", 0.01))
        kappa = max(kappa, 1e-4)

        mu_entry = aggregate_grip.mu_at(s_start, "p95")
        mu_apex = aggregate_grip.mu_at(s_apex, "p95")
        mu_exit = aggregate_grip.mu_at(s_end, "p95")

        # Entry curvature is typically lower (transitioning in)
        kappa_entry = kappa * 0.4
        kappa_exit = kappa * 0.6

        entry_kph = _speed_at_grip(mu_entry, kappa_entry)
        apex_kph = _speed_at_grip(mu_apex, kappa)
        exit_kph = _speed_at_grip(mu_exit, kappa_exit)

        results.append(CornerProven(
            corner_id=cid,
            entry_kph=entry_kph,
            apex_kph=apex_kph,
            exit_kph=exit_kph,
            brake_point_m=None,  # requires observed data, not grip alone
        ))
    return results


def compute_actual_metrics(
    distances: np.ndarray,
    speeds_mps: np.ndarray,
    accel_mps2: np.ndarray,
    corners: list[dict],
) -> list[CornerActual]:
    """Extract actual entry/apex/exit speeds and brake points for each corner."""
    results = []
    for c in corners:
        cid = c.get("corner_id", 0)
        s_start = c.get("s_start", 0.0)
        s_apex = c.get("s_apex", s_start)
        s_end = c.get("s_end", s_apex)

        entry_kph = float(np.interp(s_start, distances, speeds_mps)) * 3.6
        apex_kph = float(np.interp(s_apex, distances, speeds_mps)) * 3.6
        exit_kph = float(np.interp(s_end, distances, speeds_mps)) * 3.6

        # Detect brake point: first point where decel > threshold before corner
        brake_point = None
        search_start = s_start - _BRAKE_SEARCH_M
        pre_mask = (distances >= search_start) & (distances < s_start)
        if pre_mask.any():
            pre_dist = distances[pre_mask]
            pre_accel = accel_mps2[pre_mask]
            braking = pre_accel < -(_BRAKE_THRESHOLD_G * _G)
            if braking.any():
                first_brake_idx = np.argmax(braking)
                brake_point = float(pre_dist[first_brake_idx])

        results.append(CornerActual(
            corner_id=cid,
            entry_kph=entry_kph,
            apex_kph=apex_kph,
            exit_kph=exit_kph,
            brake_point_m=brake_point,
        ))
    return results
```

- [ ] **Step 3: Run tests**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai && python -m pytest telemetry_tool/tests/test_corner_coaching_aggregate.py -v --tb=short`

Expected: 6 passed.

- [ ] **Step 4: Commit**

```bash
git add telemetry_tool/corner_coaching_aggregate.py telemetry_tool/tests/test_corner_coaching_aggregate.py
git commit -m "feat: proven limits + actual metrics for aggregate corner coaching"
```

---

## Task 2: Root Cause Classification

**Files:**
- Modify: `telemetry_tool/corner_coaching_aggregate.py`
- Modify: `telemetry_tool/tests/test_corner_coaching_aggregate.py`

- [ ] **Step 1: Write classification tests**

Add to `telemetry_tool/tests/test_corner_coaching_aggregate.py`:

```python
from corner_coaching_aggregate import classify_root_cause


class TestClassifyRootCause:
    def _proven(self, entry=100, apex=75, exit_=90, brake=230):
        return CornerProven(corner_id=1, entry_kph=entry, apex_kph=apex,
                            exit_kph=exit_, brake_point_m=brake)

    def _actual(self, entry=100, apex=75, exit_=90, brake=230):
        return CornerActual(corner_id=1, entry_kph=entry, apex_kph=apex,
                            exit_kph=exit_, brake_point_m=brake)

    def test_early_brake(self):
        proven = self._proven(brake=230)
        actual = self._actual(brake=222)  # 8m early
        causes = classify_root_cause(proven, actual)
        assert "early_brake" in causes

    def test_late_brake(self):
        proven = self._proven(brake=230)
        actual = self._actual(brake=238)  # 8m late
        causes = classify_root_cause(proven, actual)
        assert "late_brake" in causes

    def test_apex_deficit(self):
        proven = self._proven(apex=78)
        actual = self._actual(apex=72, entry=100)  # entry fine, apex low
        causes = classify_root_cause(proven, actual)
        assert "apex_deficit" in causes

    def test_exit_under_application(self):
        proven = self._proven(exit_=92)
        actual = self._actual(exit_=80)  # big exit deficit
        causes = classify_root_cause(proven, actual, grip_headroom_pct=15.0)
        assert "exit_under_application" in causes

    def test_clean_corner_returns_empty(self):
        proven = self._proven()
        actual = self._actual()  # matches proven
        causes = classify_root_cause(proven, actual)
        assert causes == []
```

- [ ] **Step 2: Implement `classify_root_cause`**

Add to `telemetry_tool/corner_coaching_aggregate.py`:

```python
def classify_root_cause(
    proven: CornerProven,
    actual: CornerActual,
    *,
    handling_events: list[str] | None = None,
    grip_headroom_pct: float = 0.0,
) -> list[str]:
    """Classify root causes of time loss at a corner.

    Returns a list of cause keys, ordered by significance.
    """
    causes: list[str] = []
    events = handling_events or []

    # Brake point delta
    if proven.brake_point_m is not None and actual.brake_point_m is not None:
        brake_delta = actual.brake_point_m - proven.brake_point_m
        if brake_delta < -3:
            causes.append("early_brake")
        elif brake_delta > 3:
            causes.append("late_brake")

    # Entry too hot (entry exceeds proven AND handling event)
    entry_excess = actual.entry_kph - proven.entry_kph
    if entry_excess > 3 and any(e in events for e in ("understeer", "oversteer")):
        causes.append("entry_too_hot")

    # Apex speed deficit (entry OK but apex low)
    apex_delta = proven.apex_kph - actual.apex_kph
    if apex_delta > 2 and entry_excess < 3:
        causes.append("apex_deficit")

    # Exit under-application (exit low, no handling event, grip available)
    exit_delta = proven.exit_kph - actual.exit_kph
    if exit_delta > 3 and grip_headroom_pct > 10 and not any(
        e in events for e in ("oversteer", "understeer")
    ):
        causes.append("exit_under_application")

    return causes
```

- [ ] **Step 3: Run tests**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai && python -m pytest telemetry_tool/tests/test_corner_coaching_aggregate.py -v --tb=short`

Expected: 11 passed (6 + 5 new).

- [ ] **Step 4: Commit**

```bash
git add telemetry_tool/corner_coaching_aggregate.py telemetry_tool/tests/test_corner_coaching_aggregate.py
git commit -m "feat: root cause classification for aggregate corner coaching"
```

---

## Task 3: Narrative Generation + Time Loss

**Files:**
- Modify: `telemetry_tool/corner_coaching_aggregate.py`
- Modify: `telemetry_tool/tests/test_corner_coaching_aggregate.py`

- [ ] **Step 1: Write narrative tests**

Add to `telemetry_tool/tests/test_corner_coaching_aggregate.py`:

```python
from corner_coaching_aggregate import (
    generate_narrative,
    compute_time_loss,
)


class TestComputeTimeLoss:
    def test_slower_driver_has_positive_loss(self):
        distances = np.array([0, 10, 20, 30])
        v_actual = np.array([20, 20, 20, 20], dtype=float)  # 20 m/s
        v_proven = np.array([25, 25, 25, 25], dtype=float)  # 25 m/s (faster)
        loss = compute_time_loss(distances, v_actual, v_proven)
        assert loss > 0

    def test_equal_speed_zero_loss(self):
        distances = np.array([0, 10, 20, 30])
        v = np.array([25, 25, 25, 25], dtype=float)
        loss = compute_time_loss(distances, v, v)
        assert abs(loss) < 0.001


class TestGenerateNarrative:
    def test_early_brake_narrative(self):
        text = generate_narrative(
            corner_name="T4", direction="R",
            proven=CornerProven(4, entry_kph=105, apex_kph=78, exit_kph=92, brake_point_m=234),
            actual=CornerActual(4, entry_kph=105, apex_kph=72, exit_kph=88, brake_point_m=229),
            causes=["early_brake"],
            n_sessions=12, time_loss_s=0.31,
        )
        assert "braking" in text.lower()
        assert "T4" in text
        assert "12" in text  # sessions

    def test_apex_deficit_narrative(self):
        text = generate_narrative(
            corner_name="T2", direction="L",
            proven=CornerProven(2, entry_kph=95, apex_kph=68, exit_kph=82, brake_point_m=None),
            actual=CornerActual(2, entry_kph=95, apex_kph=61, exit_kph=80, brake_point_m=None),
            causes=["apex_deficit"],
            n_sessions=8, time_loss_s=0.18,
        )
        assert "apex" in text.lower()
        assert "T2" in text

    def test_empty_causes_returns_text(self):
        text = generate_narrative(
            corner_name="T1", direction="R",
            proven=CornerProven(1, 100, 75, 90, None),
            actual=CornerActual(1, 100, 75, 90, None),
            causes=[],
            n_sessions=5, time_loss_s=0.0,
        )
        assert isinstance(text, str)
```

- [ ] **Step 2: Implement `compute_time_loss` and `generate_narrative`**

Add to `telemetry_tool/corner_coaching_aggregate.py`:

```python
def compute_time_loss(
    distances: np.ndarray,
    v_actual_mps: np.ndarray,
    v_proven_mps: np.ndarray,
) -> float:
    """Time loss = integral of (1/v_actual - 1/v_proven) ds over range.

    Positive = driver slower than proven. In seconds.
    """
    v_a = np.maximum(v_actual_mps, 1.0)
    v_p = np.maximum(v_proven_mps, 1.0)
    ds = np.diff(distances)
    dt_actual = ds / v_a[:-1]
    dt_proven = ds / v_p[:-1]
    return float(np.sum(dt_actual - dt_proven))


def generate_narrative(
    corner_name: str,
    direction: str,
    proven: CornerProven,
    actual: CornerActual,
    causes: list[str],
    n_sessions: int,
    time_loss_s: float,
) -> str:
    """Generate coaching narrative from template based on root causes."""
    if not causes or time_loss_s < 0.02:
        return (
            f"{corner_name} looks clean — you're within "
            f"{abs(proven.apex_kph - actual.apex_kph):.0f}kph of the "
            f"proven apex speed across {n_sessions} sessions."
        )

    primary = causes[0]
    parts: list[str] = []

    if primary == "early_brake":
        delta = abs((actual.brake_point_m or 0) - (proven.brake_point_m or 0))
        parts.append(
            f"You're braking {delta:.0f}m too early for {corner_name}. "
            f"The track supports {proven.apex_kph:.0f}kph at the apex across "
            f"{n_sessions} sessions — you have margin to brake at the "
            f"{proven.brake_point_m:.0f}m mark instead of {actual.brake_point_m:.0f}m. "
            f"This costs {time_loss_s:.2f}s per lap."
        )
    elif primary == "late_brake":
        delta = abs((actual.brake_point_m or 0) - (proven.brake_point_m or 0))
        parts.append(
            f"You're braking {delta:.0f}m too late for {corner_name}, "
            f"overshooting the apex by {actual.apex_kph - proven.apex_kph:.0f}kph. "
            f"Brake at {proven.brake_point_m:.0f}m to set up a "
            f"{proven.apex_kph:.0f}kph apex. "
            f"This costs {time_loss_s:.2f}s per lap."
        )
    elif primary == "apex_deficit":
        apex_delta = proven.apex_kph - actual.apex_kph
        parts.append(
            f"Your entry speed is right at {actual.entry_kph:.0f}kph, "
            f"but you're scrubbing {apex_delta:.0f}kph at the {corner_name} apex. "
            f"The track supports {proven.apex_kph:.0f}kph here across {n_sessions} sessions. "
            f"Trail-brake deeper into the corner to maintain speed through the mid-corner "
            f"— the grip is there."
        )
    elif primary == "entry_too_hot":
        excess = actual.entry_kph - proven.entry_kph
        parts.append(
            f"You're carrying {excess:.0f}kph too much into {corner_name}. "
            f"The proven entry is {proven.entry_kph:.0f}kph — fast enough to set up a "
            f"{proven.apex_kph:.0f}kph apex without losing the rear. "
            f"Scrub {excess:.0f}kph on approach."
        )
    elif primary == "exit_under_application":
        exit_delta = proven.exit_kph - actual.exit_kph
        parts.append(
            f"You're only reaching {actual.exit_kph:.0f}kph at the {corner_name} exit "
            f"vs the {proven.exit_kph:.0f}kph the track supports. "
            f"Get on throttle earlier — the surface can take it. "
            f"This costs {time_loss_s:.2f}s per lap."
        )
    elif primary == "consistency_gap":
        parts.append(
            f"{corner_name} is your biggest consistency issue. "
            f"Focus on repeating your best approach — the variance alone "
            f"costs {time_loss_s:.2f}s on average."
        )
    else:
        parts.append(
            f"{corner_name}: losing {time_loss_s:.2f}s vs the track's "
            f"proven {proven.apex_kph:.0f}kph apex across {n_sessions} sessions."
        )

    return " ".join(parts)
```

- [ ] **Step 3: Run tests**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai && python -m pytest telemetry_tool/tests/test_corner_coaching_aggregate.py -v --tb=short`

Expected: 16 passed (11 + 5 new).

- [ ] **Step 4: Commit**

```bash
git add telemetry_tool/corner_coaching_aggregate.py telemetry_tool/tests/test_corner_coaching_aggregate.py
git commit -m "feat: narrative generation + time loss for aggregate corner coaching"
```

---

## Task 4: Orchestrator Function + API Endpoint

**Files:**
- Modify: `telemetry_tool/corner_coaching_aggregate.py`
- Modify: `telemetry_tool/web/routes/data_v2.py`

- [ ] **Step 1: Add `compute_corner_coaching_v4` orchestrator function**

Add to `telemetry_tool/corner_coaching_aggregate.py`:

```python
def compute_corner_coaching_v4(
    aggregate_grip: "AggregateGrip",
    corners: list[dict],
    speed_trace: dict,
    *,
    handling_events: list[dict] | None = None,
) -> dict:
    """Compute full corner coaching response.

    Parameters
    ----------
    aggregate_grip : AggregateGrip from track_surface module
    corners : list of corner dicts with corner_id, s_start, s_apex, s_end, curvature_1pm
    speed_trace : dict with 'distances' (list[float]) and 'speeds' (list[float], m/s)
    handling_events : optional list of handling event dicts per corner

    Returns dict matching the /corner-coaching-v4 API response schema.
    """
    distances = np.array(speed_trace.get("distances", []), dtype=float)
    speeds_mps = np.array(speed_trace.get("speeds", []), dtype=float)

    if len(distances) < 2 or len(speeds_mps) < 2:
        return {"corners": [], "summary": {"total_time_loss_s": 0, "top_3_corners": [], "aggregate_sessions": aggregate_grip.session_count, "narrative": "Insufficient speed data."}}

    # Derive acceleration from speed + distance
    ds = np.diff(distances)
    ds[ds < 0.01] = 0.01
    dv = np.diff(speeds_mps)
    accel = np.append(dv / ds * speeds_mps[:-1], 0.0)

    proven_list = compute_proven_limits(aggregate_grip, corners)
    actual_list = compute_actual_metrics(distances, speeds_mps, accel, corners)

    coaching_corners = []
    for i, c in enumerate(corners):
        if i >= len(proven_list) or i >= len(actual_list):
            break
        proven = proven_list[i]
        actual = actual_list[i]

        # Compute time loss over corner range
        s_start = c.get("s_start", 0)
        s_end = c.get("s_end", 0)
        mask = (distances >= s_start) & (distances <= s_end)
        if mask.sum() < 2:
            continue

        corner_dist = distances[mask]
        corner_v_actual = speeds_mps[mask]
        kappa = abs(c.get("curvature_1pm", 0.01))
        corner_v_proven = np.array([
            _speed_at_grip(aggregate_grip.mu_at(float(d), "p95"), kappa) / 3.6
            for d in corner_dist
        ])
        time_loss = compute_time_loss(corner_dist, corner_v_actual, corner_v_proven)

        # Grip headroom at apex
        mu_apex = aggregate_grip.mu_at(c.get("s_apex", s_start), "p95")
        headroom = (mu_apex * _G / max(kappa, 1e-6) - (actual.apex_kph / 3.6) ** 2 * kappa)
        headroom_pct = max(0, headroom / (mu_apex * _G / max(kappa, 1e-6)) * 100) if mu_apex > 0 else 0

        # Get handling events for this corner
        corner_events = []
        if handling_events:
            for he in handling_events:
                if isinstance(he, dict):
                    he_d = he.get("distance_m", 0)
                    if s_start <= he_d <= s_end:
                        corner_events.append(he.get("type", ""))

        causes = classify_root_cause(
            proven, actual,
            handling_events=corner_events,
            grip_headroom_pct=headroom_pct,
        )

        corner_name = c.get("corner_name", f"T{c.get('corner_id', i+1)}")
        direction = c.get("direction", "?")
        narrative = generate_narrative(
            corner_name, direction, proven, actual, causes,
            aggregate_grip.session_count, time_loss,
        )

        radius_m = 1.0 / max(kappa, 1e-6)
        coaching_corners.append({
            "corner_id": c.get("corner_id", i + 1),
            "corner_name": corner_name,
            "direction": direction,
            "radius_m": round(radius_m, 1),
            "time_loss_s": round(time_loss, 3),
            "proven": proven.to_dict(),
            "actual": actual.to_dict(),
            "root_causes": causes,
            "narrative": narrative,
            "aggregate_sessions": aggregate_grip.session_count,
            "grip_headroom_pct": round(headroom_pct, 1),
        })

    # Sort by time loss (biggest loss first)
    coaching_corners.sort(key=lambda x: x["time_loss_s"], reverse=True)
    total_loss = sum(c["time_loss_s"] for c in coaching_corners)
    top_3 = [c["corner_id"] for c in coaching_corners[:3]]

    # Summary narrative
    if coaching_corners:
        top_desc = ", ".join(
            f"{c['corner_name']} ({c['time_loss_s']:.2f}s)" for c in coaching_corners[:3]
        )
        top_pct = sum(c["time_loss_s"] for c in coaching_corners[:3]) / max(total_loss, 0.01) * 100
        summary_text = (
            f"You're leaving {total_loss:.2f}s on the table across "
            f"{len(coaching_corners)} corners. Focus on {top_desc} "
            f"— these account for {top_pct:.0f}% of your total loss."
        )
    else:
        summary_text = "All corners look clean against the track's aggregate data."

    return {
        "corners": coaching_corners,
        "summary": {
            "total_time_loss_s": round(total_loss, 3),
            "top_3_corners": top_3,
            "aggregate_sessions": aggregate_grip.session_count,
            "narrative": summary_text,
        },
    }
```

- [ ] **Step 2: Add `/corner-coaching-v4` API endpoint**

In `telemetry_tool/web/routes/data_v2.py`, find the `/physics-ceiling` or `/global-surface` endpoint block. Add AFTER it (before `/optimal-v2`):

```python
# ══════════════════════════════════════════════════════════════════
# GET /api/v1/sessions/<id>/corner-coaching-v4
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/corner-coaching-v4", methods=["GET"])
@_safe_api
def get_corner_coaching_v4(session_id: str) -> tuple[dict, int]:
    """Per-corner aggregate coaching with physics-based narratives."""
    import os

    if os.environ.get("USE_PG", "0") != "1":
        return api_error(ErrorCode.NOT_FOUND, "Aggregate coaching requires PostgreSQL mode", status=404)

    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    analysis = models.get_analysis_json(conn, session_id)
    if not analysis or not isinstance(analysis, dict):
        return api_error(ErrorCode.NOT_FOUND, "No analysis data", status=404)

    # Track ID
    track_id = analysis.get("track_id")
    if not track_id and isinstance(session, dict):
        track_id = session.get("track_id")
    if not track_id or track_id == "unknown_track":
        return api_error(ErrorCode.NOT_FOUND, "No track detected", status=404)

    # Aggregate grip
    try:
        from track_surface import get_aggregate_grip
        from corner_coaching_aggregate import compute_corner_coaching_v4
    except ImportError:
        return api_error(ErrorCode.NOT_FOUND, "Required modules not available", status=404)

    aggregate = get_aggregate_grip(conn, track_id)
    if aggregate is None:
        return api_error(ErrorCode.NOT_FOUND, "No aggregate surface data yet — upload more sessions", status=404)

    # Corners
    corners = analysis.get("corners", [])
    if not corners:
        return api_error(ErrorCode.NOT_FOUND, "No corners detected for this session", status=404)

    # Speed trace — try to get per-lap from the speed trace data
    lap = request.args.get("lap", type=int)
    speed_data = analysis.get("speed_trace_data") or {}
    if not speed_data:
        # Fallback: read from the session's speed trace endpoint data
        grip_map = analysis.get("grip_map") or {}
        distances = grip_map.get("distance_bins", [])
        speed_data = {"distances": distances, "speeds": []}

    if not speed_data.get("distances") or not speed_data.get("speeds"):
        # Try loading from DB speed trace
        try:
            from web.models import get_speed_trace_data
            st = get_speed_trace_data(conn, session_id, lap=lap)
            if st:
                speed_data = {
                    "distances": st.get("distances", []),
                    "speeds": [s for s in st.get("speeds", [])],  # m/s
                }
        except Exception:
            pass

    if not speed_data.get("distances") or not speed_data.get("speeds"):
        return api_error(ErrorCode.NOT_FOUND, "No speed trace data available", status=404)

    # Handling events (optional)
    handling = analysis.get("handling_events", [])

    result = compute_corner_coaching_v4(
        aggregate, corners, speed_data, handling_events=handling,
    )

    return api_response(result)
```

- [ ] **Step 3: Verify imports**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/telemetry_tool && python -c "from corner_coaching_aggregate import compute_corner_coaching_v4; from web.routes.data_v2 import bp; print('OK')"`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add telemetry_tool/corner_coaching_aggregate.py telemetry_tool/web/routes/data_v2.py
git commit -m "feat(api): add /corner-coaching-v4 endpoint with physics narratives"
```

---

## Task 5: Frontend Component

**Files:**
- Create: `lap-website/src/components/shared/charts/CornerCoachingV4.tsx`
- Modify: `lap-website/src/components/app/analytics/AnalyticsTab.tsx`

- [ ] **Step 1: Create CornerCoachingV4 component**

Create `lap-website/src/components/shared/charts/CornerCoachingV4.tsx`:

```tsx
/**
 * CornerCoachingV4.tsx — Per-corner aggregate coaching with narratives.
 *
 * Fetches /corner-coaching-v4 and renders:
 *   - Summary card with total time loss + top-3 corners
 *   - Per-corner cards ranked by time loss with narratives
 */
'use client';

import { useEffect, useState, useRef } from 'react';
import { apiFetch, ApiError } from '@/lib/api-client';

interface CornerCoachingProven {
  entry_kph: number;
  apex_kph: number;
  exit_kph: number;
  brake_point_m: number | null;
}

interface CornerCoachingCorner {
  corner_id: number;
  corner_name: string;
  direction: string;
  radius_m: number;
  time_loss_s: number;
  proven: CornerCoachingProven;
  actual: CornerCoachingProven;
  root_causes: string[];
  narrative: string;
  aggregate_sessions: number;
  grip_headroom_pct: number;
}

interface CornerCoachingSummary {
  total_time_loss_s: number;
  top_3_corners: number[];
  aggregate_sessions: number;
  narrative: string;
}

interface CornerCoachingV4Response {
  corners: CornerCoachingCorner[];
  summary: CornerCoachingSummary;
}

interface CornerCoachingV4Props {
  sessionId: string;
  className?: string;
}

const CAUSE_STYLES: Record<string, string> = {
  early_brake: 'bg-marshal-yellow/10 text-marshal-yellow border border-marshal-yellow/30',
  late_brake: 'bg-marshal-yellow/10 text-marshal-yellow border border-marshal-yellow/30',
  apex_deficit: 'bg-safety-red/10 text-safety-red border border-safety-red/30',
  entry_too_hot: 'bg-safety-red/10 text-safety-red border border-safety-red/30',
  exit_under_application: 'bg-acid-green/10 text-acid-green border border-acid-green/30',
  consistency_gap: 'bg-steel/10 text-steel border border-steel/30',
};

function causeStyle(cause: string): string {
  return CAUSE_STYLES[cause] ?? 'bg-steel/10 text-steel border border-steel/30';
}

function formatCause(cause: string): string {
  return cause.replace(/_/g, ' ');
}

export function CornerCoachingV4({ sessionId, className = '' }: CornerCoachingV4Props) {
  const [data, setData] = useState<CornerCoachingV4Response | null>(null);
  const [notAvailable, setNotAvailable] = useState(false);
  const fetchRef = useRef(0);

  useEffect(() => {
    const ver = ++fetchRef.current;
    setNotAvailable(false);
    setData(null);
    (async () => {
      try {
        const res = await apiFetch<CornerCoachingV4Response>(
          `/sessions/${encodeURIComponent(sessionId)}/corner-coaching-v4`,
        );
        if (fetchRef.current !== ver) return;
        if (res) setData(res);
        else setNotAvailable(true);
      } catch (err) {
        if (fetchRef.current !== ver) return;
        if (err instanceof ApiError && err.status === 404) {
          setNotAvailable(true);
        } else {
          setNotAvailable(true);
        }
      }
    })();
  }, [sessionId]);

  if (notAvailable) {
    return (
      <div className={`rounded-lg border border-steel/20 bg-concrete p-4 ${className}`}>
        <p className="text-sm text-steel font-telemetry">
          Aggregate coaching not available yet — upload more sessions at this track.
        </p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className={`rounded-lg border border-steel/20 bg-concrete p-4 animate-pulse ${className}`}>
        <div className="h-4 bg-steel/20 rounded w-2/3 mb-2" />
        <div className="h-3 bg-steel/10 rounded w-1/2" />
      </div>
    );
  }

  return (
    <div className={`space-y-3 ${className}`}>
      {/* Summary card */}
      <div className="rounded-lg border border-steel/20 bg-concrete p-4">
        <div className="flex items-baseline justify-between mb-2">
          <h3 className="text-sm font-monument text-chalk">Track Coaching</h3>
          <span className="text-xs font-telemetry text-steel bg-steel/10 px-2 py-0.5 rounded">
            {data.summary.aggregate_sessions} sessions
          </span>
        </div>
        {data.summary.total_time_loss_s > 0.05 ? (
          <>
            <p className="text-2xl font-telemetry text-safety-red mb-1">
              -{data.summary.total_time_loss_s.toFixed(2)}s
            </p>
            <p className="text-sm font-body text-steel leading-relaxed">
              {data.summary.narrative}
            </p>
          </>
        ) : (
          <p className="text-sm font-body text-acid-green">
            {data.summary.narrative}
          </p>
        )}
      </div>

      {/* Per-corner cards */}
      {data.corners.filter(c => c.time_loss_s > 0.03).map((corner) => (
        <div
          key={corner.corner_id}
          className="rounded-lg border border-steel/20 bg-concrete p-4"
        >
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className="font-monument text-chalk text-sm">
                {corner.corner_name}
              </span>
              <span className="text-xs font-telemetry text-steel">
                {corner.direction === 'R' ? '→' : '←'} {corner.radius_m.toFixed(0)}m
              </span>
            </div>
            <span className="text-sm font-telemetry text-safety-red">
              -{corner.time_loss_s.toFixed(2)}s
            </span>
          </div>

          {/* Cause badges */}
          {corner.root_causes.length > 0 && (
            <div className="flex gap-1 mb-2">
              {corner.root_causes.map((cause) => (
                <span
                  key={cause}
                  className={`text-[10px] font-telemetry px-1.5 py-0.5 rounded ${causeStyle(cause)}`}
                >
                  {formatCause(cause)}
                </span>
              ))}
            </div>
          )}

          {/* Speed comparison */}
          <div className="flex gap-4 text-xs font-telemetry text-steel mb-2">
            <div>
              Entry: <span className="text-chalk">{corner.actual.entry_kph.toFixed(0)}</span>
              <span className="text-steel/50">/{corner.proven.entry_kph.toFixed(0)}</span>
            </div>
            <div>
              Apex: <span className="text-chalk">{corner.actual.apex_kph.toFixed(0)}</span>
              <span className="text-steel/50">/{corner.proven.apex_kph.toFixed(0)}</span>
            </div>
            <div>
              Exit: <span className="text-chalk">{corner.actual.exit_kph.toFixed(0)}</span>
              <span className="text-steel/50">/{corner.proven.exit_kph.toFixed(0)}</span>
            </div>
          </div>

          {/* Narrative */}
          <p className="text-sm font-body text-chalk/80 leading-relaxed">
            {corner.narrative}
          </p>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Wire into AnalyticsTab**

In `lap-website/src/components/app/analytics/AnalyticsTab.tsx`, add import:

```typescript
import { CornerCoachingV4 } from '@/components/shared/charts/CornerCoachingV4';
```

Find where `CornerCoachingTable` is rendered (line ~200). Add `CornerCoachingV4` right before it:

```tsx
        <div>
          <CornerCoachingV4 sessionId={sessionId} className="w-full" />
        </div>
        <div>
          <CornerCoachingTable sessionId={sessionId} className="w-full" />
        </div>
```

- [ ] **Step 3: Build frontend**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npx tsc --noEmit --pretty 2>&1 | grep -c "error TS"`

Expected: 0 (or only pre-existing errors in unrelated files)

- [ ] **Step 4: Commit**

```bash
git add lap-website/src/components/shared/charts/CornerCoachingV4.tsx lap-website/src/components/app/analytics/AnalyticsTab.tsx
git commit -m "feat(ui): per-corner aggregate coaching component with narratives"
```
