# Corner Diagnosis Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a per-lap corner diagnosis classifier that labels each user-selected corner on every valid lap, plus rewire V3 deep coaching to user corners.

**Architecture:** A new `corner_diagnosis.py` module with pure numpy threshold comparisons. It receives resampled lap DataFrames, theoretical lap, user corners from DB, and MRP events. Outputs a flat `{lap: {corner_id: label}}` grid. The orchestrator gets a new S10h step and the V3 block is rewired to use user corners.

**Tech Stack:** Python 3.10+, numpy, pandas. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-03-12-corner-diagnosis-design.md`

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `telemetry_tool/mrp_detector.py` | MRP detection dataclass | EDIT: add `to_dict()` to `CornerEvents` |
| `telemetry_tool/coaching/corner_diagnosis.py` | Per-lap corner label classifier | CREATE (~300 lines) |
| `telemetry_tool/pipeline/orchestrator.py` | Pipeline wiring | EDIT: fetch user corners, S10h step, V3 rewire |
| `telemetry_tool/tests/test_corner_diagnosis.py` | Unit + integration tests | CREATE (~250 lines) |

---

## Chunk 1: Prerequisite + Foundation

### Task 1: Add `to_dict()` to `CornerEvents` dataclass

**Files:**
- Modify: `telemetry_tool/mrp_detector.py:45-58`
- Test: `telemetry_tool/tests/test_corner_diagnosis.py`

- [ ] **Step 1: Write the failing test**

Create the test file with the first test:

```python
# telemetry_tool/tests/test_corner_diagnosis.py
"""Tests for corner diagnosis classifier and prerequisites."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


class TestCornerEventsToDict:
    """Prerequisite: CornerEvents.to_dict() must exist for MRP serialisation."""

    def test_to_dict_returns_plain_dict(self):
        from mrp_detector import CornerEvents

        ev = CornerEvents(
            corner_id=1,
            brake_point_m=100.0,
            turn_in_m=110.0,
            trail_brake_end_m=120.0,
            mrp_m=130.0,
            mrp_speed_mps=25.0,
            mrp_yaw_rate=0.05,
            throttle_application_m=135.0,
            track_out_m=160.0,
            geometric_apex_m=125.0,
            mrp_apex_delta_m=5.0,
        )
        d = ev.to_dict()
        assert isinstance(d, dict)
        assert d["mrp_m"] == 130.0
        assert d["mrp_apex_delta_m"] == 5.0
        assert d["corner_id"] == 1

    def test_to_dict_handles_none_fields(self):
        from mrp_detector import CornerEvents

        ev = CornerEvents(
            corner_id=2,
            brake_point_m=None,
            turn_in_m=50.0,
            trail_brake_end_m=None,
            mrp_m=60.0,
            mrp_speed_mps=20.0,
            mrp_yaw_rate=0.03,
            throttle_application_m=None,
            track_out_m=80.0,
            geometric_apex_m=55.0,
            mrp_apex_delta_m=5.0,
        )
        d = ev.to_dict()
        assert d["brake_point_m"] is None
        assert d["throttle_application_m"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_corner_diagnosis.py::TestCornerEventsToDict -v`
Expected: FAIL with `AttributeError: 'CornerEvents' object has no attribute 'to_dict'`

- [ ] **Step 3: Implement `to_dict()` on CornerEvents**

In `telemetry_tool/mrp_detector.py`, add after the `mrp_apex_delta_m` field (line 58):

```python
    def to_dict(self) -> dict:
        """Serialise to plain dict for JSON storage."""
        import dataclasses
        return dataclasses.asdict(self)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_corner_diagnosis.py::TestCornerEventsToDict -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/mrp_detector.py telemetry_tool/tests/test_corner_diagnosis.py
git commit -m "feat: add to_dict() to CornerEvents dataclass"
```

---

### Task 2: Thresholds, tier detection, and data structures

**Files:**
- Create: `telemetry_tool/coaching/corner_diagnosis.py`
- Test: `telemetry_tool/tests/test_corner_diagnosis.py`

- [ ] **Step 1: Write failing tests for thresholds and tier detection**

Append to `test_corner_diagnosis.py`:

```python
class TestThresholdsAndTier:
    """Vehicle class thresholds and tier auto-detection."""

    def test_car_thresholds(self):
        from coaching.corner_diagnosis import _get_thresholds

        t = _get_thresholds("car")
        assert t["v_entry_delta_kmh"] == 3.0
        assert t["yaw_residual_dps"] == 10.0
        assert t["coast_gap_s"] == 0.3
        assert t["late_rotation_m"] == 8.0

    def test_kart_thresholds(self):
        from coaching.corner_diagnosis import _get_thresholds

        t = _get_thresholds("kart")
        assert t["v_entry_delta_kmh"] == 2.0
        assert t["yaw_residual_dps"] == 8.0
        assert t["coast_gap_s"] == 0.2
        assert t["late_rotation_m"] == 4.0

    def test_unknown_class_defaults_to_car(self):
        from coaching.corner_diagnosis import _get_thresholds

        t = _get_thresholds("unknown")
        assert t["v_entry_delta_kmh"] == 3.0

    def test_detect_tier_full(self):
        from coaching.corner_diagnosis import _detect_tier

        cols = {"Speed (m/s)", "Heading (rad)", "accel_lat_mps2", "Brake (%)"}
        assert _detect_tier(cols) == "full"

    def test_detect_tier_accel(self):
        from coaching.corner_diagnosis import _detect_tier

        cols = {"Speed (m/s)", "Heading (rad)", "accel_lat_mps2"}
        assert _detect_tier(cols) == "accel"

    def test_detect_tier_gps(self):
        from coaching.corner_diagnosis import _detect_tier

        cols = {"Speed (m/s)", "Heading (rad)"}
        assert _detect_tier(cols) == "gps"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_corner_diagnosis.py::TestThresholdsAndTier -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'coaching.corner_diagnosis'`

- [ ] **Step 3: Create the module with thresholds and tier detection**

Create `telemetry_tool/coaching/corner_diagnosis.py`:

```python
"""Per-lap corner diagnosis classifier.

Classifies driving symptoms for each user-selected corner on every valid lap.
Produces a flat grid {lap_number: {corner_id: label}} with one dominant label
per cell from a 23-label taxonomy across 4 corner phases.

Spec: docs/superpowers/specs/2026-03-12-corner-diagnosis-design.md
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Label constants
# ---------------------------------------------------------------------------
# Entry phase
ENTRY_OVERSPEED = "entry_overspeed"
ENTRY_UNDERSPEED = "entry_underspeed"
LATE_BRAKING = "late_braking"
EARLY_BRAKING = "early_braking"
ENTRY_UNDERSTEER = "entry_understeer"
ENTRY_OVERSTEER = "entry_oversteer"
INSUFFICIENT_TRAIL_BRAKE = "insufficient_trail_brake"
EXCESSIVE_TRAIL_BRAKE = "excessive_trail_brake"
# Apex / mid-corner phase
LOW_MIN_SPEED = "low_min_speed"
EARLY_APEX = "early_apex"
LATE_APEX = "late_apex"
MID_CORNER_UNDERSTEER = "mid_corner_understeer"
MID_CORNER_OVERSTEER = "mid_corner_oversteer"
COAST_HESITATION = "coast_hesitation"
# Exit phase
EXIT_UNDERSTEER = "exit_understeer"
EXIT_OVERSTEER = "exit_oversteer"
EARLY_THROTTLE = "early_throttle"
LATE_ROTATION = "late_rotation"
LATE_THROTTLE = "late_throttle"
THROTTLE_LIFT = "throttle_lift"
# Overall
GOOD = "good"
SLOW_EXIT = "slow_exit"
SCRAPPY = "scrappy"

# Safety labels get highest priority
_SAFETY_LABELS = {EXIT_OVERSTEER, ENTRY_OVERSTEER}

# ---------------------------------------------------------------------------
# Causal chains: child -> parent (root cause)
# ---------------------------------------------------------------------------
_CAUSAL_PARENT: dict[str, str] = {
    ENTRY_UNDERSTEER: ENTRY_OVERSPEED,
    EARLY_APEX: ENTRY_UNDERSTEER,
    MID_CORNER_UNDERSTEER: ENTRY_OVERSPEED,
    EXCESSIVE_TRAIL_BRAKE: LATE_BRAKING,
    ENTRY_OVERSTEER: LATE_BRAKING,  # via excessive trail brake
    LATE_THROTTLE: COAST_HESITATION,
    THROTTLE_LIFT: SLOW_EXIT,
    EXIT_UNDERSTEER: EARLY_THROTTLE,  # power understeer caused by early throttle
}
# Chains where child (key) is suppressed when ANY of its parents (values) are present:
_CAUSAL_ALWAYS: dict[str, list[str]] = {
    SLOW_EXIT: [EARLY_APEX, LATE_ROTATION],
}
# Note: can't use dict[str, str] — SLOW_EXIT has two parents, duplicate key would silently drop one.


# ---------------------------------------------------------------------------
# Vehicle class thresholds
# ---------------------------------------------------------------------------
_CAR_THRESHOLDS = {
    "v_entry_delta_kmh": 3.0,
    "v_underspeed_delta_kmh": 5.0,
    "v_min_delta_kmh": 3.0,  # spec Vehicle Class Thresholds table: car=3, kart=2
    "v_exit_delta_kmh": 5.0,
    "coast_gap_s": 0.3,
    "yaw_residual_dps": 10.0,
    "good_time_tol_s": 0.15,
    "late_rotation_m": 8.0,
    "apex_offset_m": 5.0,
    "exit_yaw_understeer_dps": 8.0,  # slightly lower threshold for exit understeer
}

_KART_THRESHOLDS = {
    "v_entry_delta_kmh": 2.0,
    "v_underspeed_delta_kmh": 5.0,  # spec: no kart/car split for underspeed, 5 km/h uniform
    "v_min_delta_kmh": 2.0,
    "v_exit_delta_kmh": 3.0,
    "coast_gap_s": 0.2,
    "yaw_residual_dps": 8.0,
    "good_time_tol_s": 0.10,
    "late_rotation_m": 4.0,
    "apex_offset_m": 3.0,
    "exit_yaw_understeer_dps": 6.0,
}


def _get_thresholds(vehicle_class: str) -> dict:
    """Return threshold dict for the given vehicle class."""
    if vehicle_class == "kart":
        return _KART_THRESHOLDS.copy()
    return _CAR_THRESHOLDS.copy()


# ---------------------------------------------------------------------------
# Tier detection
# ---------------------------------------------------------------------------
_BRAKE_THROTTLE_COLS = {
    "Brake (%)", "Throttle (%)", "brake_pct", "throttle_pct",
    "Brake", "Throttle",
}
_ACCEL_COLS = {"accel_lat_mps2", "accel_long_mps2", "Lat G", "Long G"}


def _detect_tier(columns: set[str]) -> str:
    """Determine detection tier from available DataFrame columns."""
    if columns & _BRAKE_THROTTLE_COLS:
        return "full"
    if columns & _ACCEL_COLS:
        return "accel"
    return "gps"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_corner_diagnosis.py::TestThresholdsAndTier -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/coaching/corner_diagnosis.py telemetry_tool/tests/test_corner_diagnosis.py
git commit -m "feat: corner diagnosis thresholds and tier detection"
```

---

### Task 3: Corner segment extraction and metrics computation

**Files:**
- Modify: `telemetry_tool/coaching/corner_diagnosis.py`
- Test: `telemetry_tool/tests/test_corner_diagnosis.py`

This is the core data extraction: given a lap DataFrame and a user corner, slice the segment and compute all the metrics the phase checkers will need.

- [ ] **Step 1: Write failing tests for segment extraction**

Append to `test_corner_diagnosis.py`:

```python
def _make_lap_df(
    n=100, s_start=50.0, s_end=150.0, v_min_at=100.0,
    v_entry_mps=30.0, v_min_mps=20.0, v_exit_mps=28.0,
    has_accel=False, has_pedals=False,
    yaw_residual_entry_dps=0.0,  # injected residual in entry zone
    yaw_residual_apex_dps=0.0,   # injected residual in apex zone
):
    """Build a synthetic lap DataFrame for a single corner segment.

    Speed profile: linear decrease from v_entry to v_min, then linear increase to v_exit.
    Distance: linear from s_start to s_end.
    """
    dist = np.linspace(s_start, s_end, n)
    mid_idx = int(n * (v_min_at - s_start) / (s_end - s_start))
    mid_idx = max(1, min(n - 2, mid_idx))

    speed = np.concatenate([
        np.linspace(v_entry_mps, v_min_mps, mid_idx),
        np.linspace(v_min_mps, v_exit_mps, n - mid_idx),
    ])

    # Heading: smooth curve (left turn, ~90 deg over the corner)
    heading = np.linspace(0.0, np.pi / 2, n)

    data = {
        "Distance (m)": dist,
        "Speed (m/s)": speed,
        "Heading (rad)": heading,
    }

    if has_accel:
        # Derive lon_g from speed change
        dt = 0.1  # assume 10Hz
        lon_g = np.gradient(speed, dt) / 9.81
        lat_g = np.full(n, 0.5)  # moderate lateral g
        data["accel_long_mps2"] = lon_g * 9.81
        data["accel_lat_mps2"] = lat_g * 9.81

    if has_pedals:
        brake = np.zeros(n)
        brake[:mid_idx] = np.linspace(80, 0, mid_idx)
        throttle = np.zeros(n)
        throttle[mid_idx:] = np.linspace(0, 90, n - mid_idx)
        data["Brake (%)"] = brake
        data["Throttle (%)"] = throttle

    return pd.DataFrame(data)


def _make_corner(s_entry=50.0, s_apex=100.0, s_exit=150.0, corner_index=1):
    """Build a user corner dict matching _fetch_user_corners output."""
    return {
        "corner_index": corner_index,
        "s_entry": s_entry,
        "s_apex": s_apex,
        "s_exit": s_exit,
    }


def _make_curvature_profile(s_start=0.0, s_end=200.0, n=200):
    """Build a curvature profile DataFrame (left turn, positive curvature)."""
    dist = np.linspace(s_start, s_end, n)
    curv = np.full(n, 0.01)  # gentle left turn: kappa > 0
    return pd.DataFrame({"distance_m": dist, "curvature_1pm": curv})


class TestSegmentExtraction:
    """Test _extract_corner_metrics: slicing + metric computation."""

    def test_basic_metrics(self):
        from coaching.corner_diagnosis import _extract_corner_metrics

        lap_df = _make_lap_df(v_entry_mps=30.0, v_min_mps=20.0, v_exit_mps=28.0)
        corner = _make_corner(s_entry=50.0, s_apex=100.0, s_exit=150.0)
        curv = _make_curvature_profile()

        m = _extract_corner_metrics(lap_df, corner, curv, mrp_event=None)
        assert m is not None
        # v_entry should be close to 30 m/s
        assert abs(m["v_entry_mps"] - 30.0) < 1.0
        # v_min should be close to 20 m/s
        assert abs(m["v_min_mps"] - 20.0) < 1.0
        # s_vmin should be near s_apex (100m)
        assert abs(m["s_vmin"] - 100.0) < 10.0
        # kappa_sign should be +1 (left turn)
        assert m["kappa_sign"] == 1.0

    def test_kappa_sign_from_heading_fallback(self):
        from coaching.corner_diagnosis import _extract_corner_metrics

        lap_df = _make_lap_df()
        corner = _make_corner()
        # No curvature profile -> fall back to heading
        m = _extract_corner_metrics(lap_df, corner, curvature_profile=None, mrp_event=None)
        # Heading goes 0 -> pi/2 (left turn) -> positive kappa_sign
        assert m["kappa_sign"] == 1.0

    def test_right_turn_kappa_sign(self):
        from coaching.corner_diagnosis import _extract_corner_metrics

        lap_df = _make_lap_df()
        # Override heading to go 0 -> -pi/2 (right turn)
        lap_df["Heading (rad)"] = np.linspace(0.0, -np.pi / 2, len(lap_df))
        corner = _make_corner()
        m = _extract_corner_metrics(lap_df, corner, curvature_profile=None, mrp_event=None)
        assert m["kappa_sign"] == -1.0

    def test_mrp_event_fields_passed_through(self):
        from coaching.corner_diagnosis import _extract_corner_metrics

        lap_df = _make_lap_df()
        corner = _make_corner()
        mrp = {"mrp_m": 105.0, "mrp_apex_delta_m": 10.0, "geometric_apex_m": 95.0}
        m = _extract_corner_metrics(lap_df, corner, None, mrp_event=mrp)
        assert m["mrp_m"] == 105.0
        assert m["mrp_apex_delta_m"] == 10.0

    def test_empty_segment_returns_none(self):
        from coaching.corner_diagnosis import _extract_corner_metrics

        lap_df = _make_lap_df(s_start=50.0, s_end=150.0)
        # Corner range doesn't overlap with lap data
        corner = _make_corner(s_entry=500.0, s_apex=550.0, s_exit=600.0)
        m = _extract_corner_metrics(lap_df, corner, None, mrp_event=None)
        assert m is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_corner_diagnosis.py::TestSegmentExtraction -v`
Expected: FAIL with `ImportError: cannot import name '_extract_corner_metrics'`

- [ ] **Step 3: Implement `_extract_corner_metrics`**

Append to `telemetry_tool/coaching/corner_diagnosis.py`:

```python
# ---------------------------------------------------------------------------
# Segment extraction and metrics
# ---------------------------------------------------------------------------
_COL_DIST = "Distance (m)"
_COL_SPEED = "Speed (m/s)"
_COL_HEADING = "Heading (rad)"
_COL_ACCEL_LONG = "accel_long_mps2"
_COL_ACCEL_LAT = "accel_lat_mps2"
_COL_BRAKE = "Brake (%)"
_COL_THROTTLE = "Throttle (%)"


def _extract_corner_metrics(
    lap_df: pd.DataFrame,
    corner: dict,
    curvature_profile: pd.DataFrame | None,
    mrp_event: dict | None,
) -> dict | None:
    """Slice a lap DataFrame for one corner and compute all metrics.

    Returns None if the segment has fewer than 5 data points.
    """
    s_entry = corner["s_entry"]
    s_apex = corner["s_apex"]
    s_exit = corner["s_exit"]

    if _COL_DIST not in lap_df.columns or _COL_SPEED not in lap_df.columns:
        return None

    dist = lap_df[_COL_DIST].values
    # Include 50m pre-corner buffer for early_braking detection
    mask = (dist >= s_entry - 50.0) & (dist <= s_exit)
    core_mask = (dist >= s_entry) & (dist <= s_exit)
    if core_mask.sum() < 5:
        return None

    seg = lap_df[mask]  # boolean indexing (not .loc) — safe regardless of index type
    d = seg[_COL_DIST].values
    v = seg[_COL_SPEED].values

    # Basic speed metrics
    v_entry_mps = float(np.interp(s_entry, d, v))
    v_exit_mps = float(np.interp(s_exit, d, v))
    vmin_idx = int(np.argmin(v))
    v_min_mps = float(v[vmin_idx])
    s_vmin = float(d[vmin_idx])

    # Kappa sign (corner direction)
    kappa_sign = _compute_kappa_sign(seg, s_apex, curvature_profile)

    # Yaw residual (direction-normalised)
    yaw_residual = _compute_yaw_residual(seg, curvature_profile, kappa_sign)

    # Accel channels (may be None)
    lon_g = seg[_COL_ACCEL_LONG].values if _COL_ACCEL_LONG in seg.columns else None
    lat_g = seg[_COL_ACCEL_LAT].values if _COL_ACCEL_LAT in seg.columns else None

    # Pedal channels (may be None)
    brake = seg[_COL_BRAKE].values if _COL_BRAKE in seg.columns else None
    throttle = seg[_COL_THROTTLE].values if _COL_THROTTLE in seg.columns else None

    metrics = {
        "s_entry": s_entry,
        "s_apex": s_apex,
        "s_exit": s_exit,
        "d": d,
        "v": v,
        "v_entry_mps": v_entry_mps,
        "v_exit_mps": v_exit_mps,
        "v_min_mps": v_min_mps,
        "s_vmin": s_vmin,
        "kappa_sign": kappa_sign,
        "yaw_residual": yaw_residual,
        "lon_g": lon_g,
        "lat_g": lat_g,
        "brake": brake,
        "throttle": throttle,
        # MRP fields (may be None)
        "mrp_m": mrp_event["mrp_m"] if mrp_event else None,
        "mrp_apex_delta_m": mrp_event["mrp_apex_delta_m"] if mrp_event else None,
    }
    return metrics


def _compute_kappa_sign(
    seg: pd.DataFrame, s_apex: float, curvature_profile: pd.DataFrame | None,
) -> float:
    """Determine corner direction: +1 = left turn, -1 = right turn."""
    if curvature_profile is not None and len(curvature_profile) > 1:
        cp_dist = curvature_profile["distance_m"].values
        cp_curv = curvature_profile["curvature_1pm"].values
        kappa_at_apex = float(np.interp(s_apex, cp_dist, cp_curv))
        if abs(kappa_at_apex) > 1e-6:
            return float(np.sign(kappa_at_apex))

    # Fallback: heading change across segment
    if _COL_HEADING in seg.columns:
        h = seg[_COL_HEADING].values
        if len(h) >= 2:
            # Wrap-safe angular difference (radians)
            delta_rad = h[-1] - h[0]
            delta_rad = (delta_rad + np.pi) % (2 * np.pi) - np.pi
            if abs(delta_rad) > 1e-6:
                return float(np.sign(delta_rad))

    return 1.0  # default left turn if unknown


def _compute_yaw_residual(
    seg: pd.DataFrame, curvature_profile: pd.DataFrame | None, kappa_sign: float,
) -> np.ndarray | None:
    """Compute direction-normalised yaw residual for the segment.

    yaw_residual_norm = (yaw_measured - yaw_expected) * sign(kappa)
    Positive = oversteer, Negative = understeer.
    Returns None if heading data is unavailable.
    """
    if _COL_HEADING not in seg.columns or _COL_SPEED not in seg.columns:
        return None
    if _COL_DIST not in seg.columns:
        return None

    d = seg[_COL_DIST].values
    v = seg[_COL_SPEED].values
    h = seg[_COL_HEADING].values

    if len(d) < 3:
        return None

    # Measured yaw rate: dh/dd (rad/m) * v (m/s) = rad/s, then * (180/pi) = deg/s
    dd = np.diff(d)
    dd = np.where(np.abs(dd) > 1e-9, dd, 1e-9)
    dh = np.diff(h)
    dh = (dh + np.pi) % (2 * np.pi) - np.pi  # wrap
    yaw_rate_radpm = dh / dd
    yaw_rate_radpm = np.append(yaw_rate_radpm, yaw_rate_radpm[-1])
    # Convert to deg/s: yaw_rate_radpm * speed * (180/pi)
    yaw_measured_dps = yaw_rate_radpm * v * (180.0 / np.pi)

    # Expected yaw rate from curvature
    if curvature_profile is not None and len(curvature_profile) > 1:
        cp_dist = curvature_profile["distance_m"].values
        cp_curv = curvature_profile["curvature_1pm"].values
        kappa = np.interp(d, cp_dist, cp_curv)
    else:
        # No curvature profile: assume uniform curvature from heading change
        total_heading_change = h[-1] - h[0]
        total_heading_change = (total_heading_change + np.pi) % (2 * np.pi) - np.pi
        total_dist = d[-1] - d[0]
        if abs(total_dist) > 1e-6:
            kappa = np.full(len(d), total_heading_change / total_dist)
        else:
            return None

    yaw_expected_dps = v * kappa * (180.0 / np.pi)

    # Direction-normalised residual
    residual = (yaw_measured_dps - yaw_expected_dps) * kappa_sign
    return residual
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_corner_diagnosis.py::TestSegmentExtraction -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/coaching/corner_diagnosis.py telemetry_tool/tests/test_corner_diagnosis.py
git commit -m "feat: corner segment extraction and metrics computation"
```

---

## Chunk 2: Phase Checkers

### Task 4: Entry phase checker

**Files:**
- Modify: `telemetry_tool/coaching/corner_diagnosis.py`
- Test: `telemetry_tool/tests/test_corner_diagnosis.py`

- [ ] **Step 1: Write failing tests for entry phase**

Append to `test_corner_diagnosis.py`:

```python
class TestEntryPhase:
    """Entry phase label detection."""

    def test_entry_overspeed(self):
        from coaching.corner_diagnosis import _check_entry_phase

        # v_entry 5 km/h above theoretical (> 3 km/h threshold)
        metrics = {"v_entry_mps": 30.0, "s_apex": 100.0, "s_entry": 50.0,
                   "kappa_sign": 1.0, "yaw_residual": None,
                   "lon_g": None, "lat_g": None, "brake": None, "d": np.linspace(50, 150, 100)}
        theo = {"v_entry_mps": 28.6}  # 30 - 28.6 = 1.4 m/s = 5.04 km/h
        thresholds = {"v_entry_delta_kmh": 3.0, "yaw_residual_dps": 10.0}
        labels = _check_entry_phase(metrics, theo, thresholds, "gps")
        assert any(c.label == "entry_overspeed" for c in labels)

    def test_entry_underspeed(self):
        from coaching.corner_diagnosis import _check_entry_phase

        metrics = {"v_entry_mps": 25.0, "s_apex": 100.0, "s_entry": 50.0,
                   "kappa_sign": 1.0, "yaw_residual": None,
                   "lon_g": None, "lat_g": None, "brake": None, "d": np.linspace(50, 150, 100)}
        theo = {"v_entry_mps": 27.0}  # 27 - 25 = 2 m/s = 7.2 km/h > 5 threshold
        thresholds = {"v_entry_delta_kmh": 3.0, "v_underspeed_delta_kmh": 5.0,
                      "yaw_residual_dps": 10.0}
        labels = _check_entry_phase(metrics, theo, thresholds, "gps")
        assert any(c.label == "entry_underspeed" for c in labels)

    def test_entry_oversteer_via_yaw(self):
        from coaching.corner_diagnosis import _check_entry_phase

        n = 100
        # Sustained positive yaw residual > 10 dps in entry half
        yaw_res = np.zeros(n)
        yaw_res[:50] = 15.0  # oversteer in entry half
        metrics = {"v_entry_mps": 28.0, "s_apex": 100.0, "s_entry": 50.0,
                   "kappa_sign": 1.0, "yaw_residual": yaw_res,
                   "lon_g": None, "lat_g": None, "brake": None,
                   "d": np.linspace(50, 150, n)}
        theo = {"v_entry_mps": 28.0}
        thresholds = {"v_entry_delta_kmh": 3.0, "v_underspeed_delta_kmh": 5.0,
                      "yaw_residual_dps": 10.0}
        labels = _check_entry_phase(metrics, theo, thresholds, "gps")
        assert any(c.label == "entry_oversteer" for c in labels)

    def test_no_labels_when_within_tolerance(self):
        from coaching.corner_diagnosis import _check_entry_phase

        metrics = {"v_entry_mps": 28.0, "s_apex": 100.0, "s_entry": 50.0,
                   "kappa_sign": 1.0, "yaw_residual": np.zeros(100),
                   "lon_g": None, "lat_g": None, "brake": None,
                   "d": np.linspace(50, 150, 100)}
        theo = {"v_entry_mps": 28.0}
        thresholds = {"v_entry_delta_kmh": 3.0, "v_underspeed_delta_kmh": 5.0,
                      "yaw_residual_dps": 10.0}
        labels = _check_entry_phase(metrics, theo, thresholds, "gps")
        assert len(labels) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_corner_diagnosis.py::TestEntryPhase -v`
Expected: FAIL with `ImportError: cannot import name '_check_entry_phase'`

- [ ] **Step 3: Implement the entry phase checker and `Candidate` dataclass**

Append to `corner_diagnosis.py`:

```python
@dataclass
class Candidate:
    """A candidate label with priority for resolution."""
    label: str
    priority: int  # lower = higher priority (safety=1, time-loss=2, misc=3)
    phase: str     # "entry", "apex", "exit", "overall"


def _check_entry_phase(
    metrics: dict, theo: dict | None, thresholds: dict, tier: str,
) -> list[Candidate]:
    """Check entry phase labels. Returns list of candidates."""
    candidates: list[Candidate] = []
    v_entry = metrics["v_entry_mps"]
    d = metrics["d"]
    s_entry = metrics["s_entry"]
    s_apex = metrics["s_apex"]

    # Entry half indices
    entry_mask = d <= s_apex

    # Speed-based checks (all tiers)
    if theo and "v_entry_mps" in theo:
        v_theo = theo["v_entry_mps"]
        delta_kmh = (v_entry - v_theo) * 3.6
        if delta_kmh > thresholds["v_entry_delta_kmh"]:
            candidates.append(Candidate(ENTRY_OVERSPEED, 2, "entry"))
        elif -delta_kmh > thresholds.get("v_underspeed_delta_kmh", 5.0):
            candidates.append(Candidate(ENTRY_UNDERSPEED, 3, "entry"))

    # Yaw residual checks (all tiers)
    yaw_res = metrics.get("yaw_residual")
    if yaw_res is not None and entry_mask.sum() >= 5:
        entry_yaw = yaw_res[entry_mask]
        yaw_thresh = thresholds["yaw_residual_dps"]
        # Oversteer: sustained positive residual
        if np.sum(entry_yaw > yaw_thresh) >= 5:
            candidates.append(Candidate(ENTRY_OVERSTEER, 1, "entry"))
        # Understeer: sustained negative residual
        elif np.sum(entry_yaw < -yaw_thresh) >= 5:
            candidates.append(Candidate(ENTRY_UNDERSTEER, 2, "entry"))

    # Accel-tier checks
    lon_g = metrics.get("lon_g")
    if tier in ("accel", "full") and lon_g is not None:
        # Late braking: lon_g < -0.3g past s_apex
        past_apex = d > s_apex
        if past_apex.any() and np.any(lon_g[past_apex] < -0.3 * 9.81):
            candidates.append(Candidate(LATE_BRAKING, 2, "entry"))
        # Early braking: lon_g < -0.3g starts >15m before s_entry
        pre_entry = d < (s_entry - 15.0)
        if pre_entry.any() and np.any(lon_g[pre_entry] < -0.3 * 9.81):
            candidates.append(Candidate(EARLY_BRAKING, 3, "entry"))
        # Excessive trail brake: lon_g < -0.2g at s_apex
        apex_idx = np.argmin(np.abs(d - s_apex))
        if lon_g[apex_idx] < -0.2 * 9.81:
            candidates.append(Candidate(EXCESSIVE_TRAIL_BRAKE, 2, "entry"))

    # Pedal-tier checks
    brake = metrics.get("brake")
    if tier == "full" and brake is not None:
        # Late braking: brake > 20% past s_apex
        past_apex = d > s_apex
        if past_apex.any() and np.any(brake[past_apex] > 20):
            # Only add if not already added by accel tier
            if not any(c.label == LATE_BRAKING for c in candidates):
                candidates.append(Candidate(LATE_BRAKING, 2, "entry"))
        # Early braking: brake > 10% starts >15m before s_entry
        pre_entry = d < (s_entry - 15.0)
        if pre_entry.any() and np.any(brake[pre_entry] > 10):
            if not any(c.label == EARLY_BRAKING for c in candidates):
                candidates.append(Candidate(EARLY_BRAKING, 3, "entry"))
        # Excessive trail brake: brake > 30% at s_apex
        apex_idx = np.argmin(np.abs(d - s_apex))
        if brake[apex_idx] > 30:
            if not any(c.label == EXCESSIVE_TRAIL_BRAKE for c in candidates):
                candidates.append(Candidate(EXCESSIVE_TRAIL_BRAKE, 2, "entry"))
        # Insufficient trail brake: brake to 0 before first 10% of corner
        corner_len = s_apex - s_entry
        first_10pct = s_entry + corner_len * 0.1
        early_mask = d <= first_10pct
        if early_mask.any() and np.all(brake[early_mask] < 1):
            candidates.append(Candidate(INSUFFICIENT_TRAIL_BRAKE, 3, "entry"))

    return candidates
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_corner_diagnosis.py::TestEntryPhase -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/coaching/corner_diagnosis.py telemetry_tool/tests/test_corner_diagnosis.py
git commit -m "feat: entry phase checker with 8 labels"
```

---

### Task 5: Apex phase checker

**Files:**
- Modify: `telemetry_tool/coaching/corner_diagnosis.py`
- Test: `telemetry_tool/tests/test_corner_diagnosis.py`

- [ ] **Step 1: Write failing tests**

Append to `test_corner_diagnosis.py`:

```python
class TestApexPhase:
    """Apex/mid-corner phase label detection."""

    def test_low_min_speed(self):
        from coaching.corner_diagnosis import _check_apex_phase

        metrics = {"v_min_mps": 18.0, "s_vmin": 100.0, "s_apex": 100.0,
                   "s_entry": 50.0, "s_exit": 150.0, "v": np.full(100, 20.0),
                   "d": np.linspace(50, 150, 100), "kappa_sign": 1.0,
                   "yaw_residual": None, "lon_g": None, "brake": None,
                   "throttle": None}
        theo = {"v_min_mps": 20.0}  # 20 - 18 = 2 m/s = 7.2 km/h > 4 threshold
        thresholds = {"v_min_delta_kmh": 4.0, "apex_offset_m": 5.0,
                      "yaw_residual_dps": 10.0, "coast_gap_s": 0.3}
        labels = _check_apex_phase(metrics, theo, thresholds, "gps")
        assert any(c.label == "low_min_speed" for c in labels)

    def test_early_apex(self):
        from coaching.corner_diagnosis import _check_apex_phase

        metrics = {"v_min_mps": 20.0, "s_vmin": 90.0, "s_apex": 100.0,
                   "s_entry": 50.0, "s_exit": 150.0, "v": np.full(100, 20.0),
                   "d": np.linspace(50, 150, 100), "kappa_sign": 1.0,
                   "yaw_residual": None, "lon_g": None, "brake": None,
                   "throttle": None}
        theo = {"v_min_mps": 20.0}
        thresholds = {"v_min_delta_kmh": 4.0, "apex_offset_m": 5.0,
                      "yaw_residual_dps": 10.0, "coast_gap_s": 0.3}
        labels = _check_apex_phase(metrics, theo, thresholds, "gps")
        assert any(c.label == "early_apex" for c in labels)

    def test_late_apex(self):
        from coaching.corner_diagnosis import _check_apex_phase

        metrics = {"v_min_mps": 20.0, "s_vmin": 112.0, "s_apex": 100.0,
                   "s_entry": 50.0, "s_exit": 150.0, "v": np.full(100, 20.0),
                   "d": np.linspace(50, 150, 100), "kappa_sign": 1.0,
                   "yaw_residual": None, "lon_g": None, "brake": None,
                   "throttle": None}
        theo = {"v_min_mps": 20.0}
        thresholds = {"v_min_delta_kmh": 4.0, "apex_offset_m": 5.0,
                      "yaw_residual_dps": 10.0, "coast_gap_s": 0.3}
        labels = _check_apex_phase(metrics, theo, thresholds, "gps")
        assert any(c.label == "late_apex" for c in labels)

    def test_coast_hesitation_gps_tier(self):
        from coaching.corner_diagnosis import _check_apex_phase

        n = 100
        d = np.linspace(50, 150, n)
        # Speed profile: decel, flat coast zone, then accel
        v = np.concatenate([
            np.linspace(30, 20, 30),   # decel
            np.full(40, 20.0),          # coast (flat speed for 40 samples)
            np.linspace(20, 28, 30),    # accel
        ])
        metrics = {"v_min_mps": 20.0, "s_vmin": 100.0, "s_apex": 100.0,
                   "s_entry": 50.0, "s_exit": 150.0, "v": v, "d": d,
                   "kappa_sign": 1.0, "yaw_residual": None,
                   "lon_g": None, "brake": None, "throttle": None}
        theo = {"v_min_mps": 20.0}
        thresholds = {"v_min_delta_kmh": 4.0, "apex_offset_m": 5.0,
                      "yaw_residual_dps": 10.0, "coast_gap_s": 0.3}
        labels = _check_apex_phase(metrics, theo, thresholds, "gps")
        assert any(c.label == "coast_hesitation" for c in labels)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_corner_diagnosis.py::TestApexPhase -v`
Expected: FAIL

- [ ] **Step 3: Implement `_check_apex_phase`**

Append to `corner_diagnosis.py`:

```python
def _check_apex_phase(
    metrics: dict, theo: dict | None, thresholds: dict, tier: str,
) -> list[Candidate]:
    """Check apex/mid-corner phase labels."""
    candidates: list[Candidate] = []
    s_apex = metrics["s_apex"]
    s_entry = metrics["s_entry"]
    s_exit = metrics["s_exit"]
    v_min = metrics["v_min_mps"]
    s_vmin = metrics["s_vmin"]
    d = metrics["d"]
    v = metrics["v"]
    apex_offset = thresholds["apex_offset_m"]

    # Low min speed (all tiers)
    if theo and "v_min_mps" in theo:
        delta_kmh = (theo["v_min_mps"] - v_min) * 3.6
        if delta_kmh > thresholds["v_min_delta_kmh"]:
            candidates.append(Candidate(LOW_MIN_SPEED, 2, "apex"))

    # Apex position (all tiers)
    if s_vmin < s_apex - apex_offset:
        candidates.append(Candidate(EARLY_APEX, 2, "apex"))
    elif s_vmin > s_apex + apex_offset:
        candidates.append(Candidate(LATE_APEX, 3, "apex"))

    # Yaw residual in apex zone (all tiers)
    apex_zone_start = s_apex - 0.15 * (s_exit - s_entry)
    apex_zone_end = s_apex + 0.15 * (s_exit - s_entry)
    apex_mask = (d >= apex_zone_start) & (d <= apex_zone_end)

    yaw_res = metrics.get("yaw_residual")
    if yaw_res is not None and apex_mask.sum() >= 3:
        apex_yaw = yaw_res[apex_mask]
        yaw_thresh = thresholds["yaw_residual_dps"]
        if np.sum(apex_yaw > yaw_thresh) >= 3:
            candidates.append(Candidate(MID_CORNER_OVERSTEER, 1, "apex"))
        elif np.sum(apex_yaw < -yaw_thresh) >= 3:
            candidates.append(Candidate(MID_CORNER_UNDERSTEER, 2, "apex"))

    # Coast hesitation
    coast_gap_s = thresholds["coast_gap_s"]
    _check_coast_hesitation(metrics, tier, coast_gap_s, candidates)

    return candidates


def _check_coast_hesitation(
    metrics: dict, tier: str, coast_gap_s: float, candidates: list[Candidate],
) -> None:
    """Detect coast hesitation across all three tiers."""
    d = metrics["d"]
    v = metrics["v"]

    if tier == "full":
        brake = metrics.get("brake")
        throttle = metrics.get("throttle")
        if brake is not None and throttle is not None:
            coast_mask = (brake < 5) & (throttle < 10)
            if _sustained_run(coast_mask, d, coast_gap_s):
                candidates.append(Candidate(COAST_HESITATION, 3, "apex"))
                return

    if tier in ("accel", "full"):
        lon_g = metrics.get("lon_g")
        if lon_g is not None:
            coast_mask = np.abs(lon_g) < 0.05 * 9.81
            if _sustained_run(coast_mask, d, coast_gap_s):
                candidates.append(Candidate(COAST_HESITATION, 3, "apex"))
                return

    # GPS tier only: smoothed speed derivative (skip if higher tier already checked)
    if tier == "gps" and len(v) >= 3 and len(d) >= 3:
        # 3-point Gaussian-like smoothing: simple [0.25, 0.5, 0.25] kernel
        v_smooth = np.convolve(v, [0.25, 0.5, 0.25], mode="same")
        dd = np.diff(d)
        dd = np.where(np.abs(dd) > 1e-9, dd, 1e-9)
        dv_ds = np.diff(v_smooth) / dd
        # Convert to m/s^2 approximation: dv/ds * v_avg
        v_avg = (v_smooth[:-1] + v_smooth[1:]) / 2
        accel_approx = dv_ds * v_avg
        coast_mask_gps = np.abs(accel_approx) < 0.5
        # Pad to original length
        coast_mask_full = np.zeros(len(d), dtype=bool)
        coast_mask_full[:-1] = coast_mask_gps
        if _sustained_run(coast_mask_full, d, coast_gap_s):
            candidates.append(Candidate(COAST_HESITATION, 3, "apex"))


def _sustained_run(mask: np.ndarray, distances: np.ndarray, min_duration_s: float) -> bool:
    """Check if a boolean mask has a contiguous True run spanning >= min_duration_s.

    Uses distance span as proxy for time (assumes ~constant speed in the zone).
    For a more accurate check, we'd need time stamps — but distance works for
    the threshold ranges we use (0.2-0.3s at 20+ m/s = 4-9m).
    """
    if not mask.any():
        return False
    # Convert time threshold to distance: assume 20 m/s typical apex speed
    min_dist = min_duration_s * 20.0  # conservative ~20 m/s

    runs = np.diff(np.concatenate([[0], mask.astype(int), [0]]))
    starts = np.where(runs == 1)[0]
    ends = np.where(runs == -1)[0]
    for s, e in zip(starts, ends):
        if e <= len(distances) and s < len(distances):
            span = distances[min(e, len(distances) - 1)] - distances[s]
            if span >= min_dist:
                return True
    return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_corner_diagnosis.py::TestApexPhase -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/coaching/corner_diagnosis.py telemetry_tool/tests/test_corner_diagnosis.py
git commit -m "feat: apex phase checker with 6 labels"
```

---

### Task 6: Exit phase checker

**Files:**
- Modify: `telemetry_tool/coaching/corner_diagnosis.py`
- Test: `telemetry_tool/tests/test_corner_diagnosis.py`

- [ ] **Step 1: Write failing tests**

Append to `test_corner_diagnosis.py`:

```python
class TestExitPhase:
    """Exit phase label detection."""

    def test_late_rotation_from_mrp(self):
        from coaching.corner_diagnosis import _check_exit_phase

        metrics = {"s_apex": 100.0, "s_exit": 150.0, "s_vmin": 100.0,
                   "v_exit_mps": 28.0, "v": np.full(100, 25.0),
                   "d": np.linspace(50, 150, 100), "kappa_sign": 1.0,
                   "yaw_residual": None, "lon_g": None,
                   "brake": None, "throttle": None,
                   "mrp_m": 115.0, "mrp_apex_delta_m": 10.0}
        theo = {"v_exit_mps": 28.0}
        thresholds = {"v_exit_delta_kmh": 5.0, "late_rotation_m": 8.0,
                      "yaw_residual_dps": 10.0, "exit_yaw_understeer_dps": 8.0}
        labels = _check_exit_phase(metrics, theo, thresholds, "gps")
        assert any(c.label == "late_rotation" for c in labels)

    def test_late_rotation_not_fired_below_threshold(self):
        from coaching.corner_diagnosis import _check_exit_phase

        metrics = {"s_apex": 100.0, "s_exit": 150.0, "s_vmin": 100.0,
                   "v_exit_mps": 28.0, "v": np.full(100, 25.0),
                   "d": np.linspace(50, 150, 100), "kappa_sign": 1.0,
                   "yaw_residual": None, "lon_g": None,
                   "brake": None, "throttle": None,
                   "mrp_m": 105.0, "mrp_apex_delta_m": 5.0}
        theo = {"v_exit_mps": 28.0}
        thresholds = {"v_exit_delta_kmh": 5.0, "late_rotation_m": 8.0,
                      "yaw_residual_dps": 10.0, "exit_yaw_understeer_dps": 8.0}
        labels = _check_exit_phase(metrics, theo, thresholds, "gps")
        assert not any(c.label == "late_rotation" for c in labels)

    def test_early_throttle_with_mrp_reference(self):
        from coaching.corner_diagnosis import _check_exit_phase

        n = 100
        d = np.linspace(50, 150, n)
        throttle = np.zeros(n)
        # Throttle at 60% starting well before MRP (mrp_m=110, throttle starts at d~95)
        throttle_start_idx = np.searchsorted(d, 95.0)
        throttle[throttle_start_idx:] = 60.0

        metrics = {"s_apex": 100.0, "s_exit": 150.0, "s_vmin": 100.0,
                   "v_exit_mps": 28.0, "v": np.full(n, 25.0), "d": d,
                   "kappa_sign": 1.0, "yaw_residual": None, "lon_g": None,
                   "brake": None, "throttle": throttle,
                   "mrp_m": 110.0, "mrp_apex_delta_m": 5.0}
        theo = {"v_exit_mps": 28.0}
        thresholds = {"v_exit_delta_kmh": 5.0, "late_rotation_m": 8.0,
                      "yaw_residual_dps": 10.0, "exit_yaw_understeer_dps": 8.0}
        labels = _check_exit_phase(metrics, theo, thresholds, "full")
        assert any(c.label == "early_throttle" for c in labels)

    def test_throttle_lift(self):
        from coaching.corner_diagnosis import _check_exit_phase

        n = 100
        d = np.linspace(50, 150, n)
        throttle = np.zeros(n)
        # Throttle ramps up then drops 30% before exit
        throttle[50:70] = 80
        throttle[70:80] = 50  # 30% drop
        throttle[80:] = 80

        metrics = {"s_apex": 100.0, "s_exit": 150.0, "s_vmin": 100.0,
                   "v_exit_mps": 28.0, "v": np.full(n, 25.0), "d": d,
                   "kappa_sign": 1.0, "yaw_residual": None, "lon_g": None,
                   "brake": None, "throttle": throttle,
                   "mrp_m": None, "mrp_apex_delta_m": None}
        theo = {"v_exit_mps": 28.0}
        thresholds = {"v_exit_delta_kmh": 5.0, "late_rotation_m": 8.0,
                      "yaw_residual_dps": 10.0, "exit_yaw_understeer_dps": 8.0}
        labels = _check_exit_phase(metrics, theo, thresholds, "full")
        assert any(c.label == "throttle_lift" for c in labels)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_corner_diagnosis.py::TestExitPhase -v`
Expected: FAIL

- [ ] **Step 3: Implement `_check_exit_phase`**

Append to `corner_diagnosis.py`:

```python
def _check_exit_phase(
    metrics: dict, theo: dict | None, thresholds: dict, tier: str,
) -> list[Candidate]:
    """Check exit phase labels."""
    candidates: list[Candidate] = []
    s_apex = metrics["s_apex"]
    s_exit = metrics["s_exit"]
    d = metrics["d"]
    v = metrics["v"]

    exit_mask = d >= s_apex

    # Late rotation (all tiers, requires MRP data)
    mrp_delta = metrics.get("mrp_apex_delta_m")
    if mrp_delta is not None and mrp_delta > thresholds["late_rotation_m"]:
        candidates.append(Candidate(LATE_ROTATION, 2, "exit"))

    # Yaw residual in exit zone (accel + full tiers only — GPS excluded per spec)
    yaw_res = metrics.get("yaw_residual")
    if tier in ("accel", "full") and yaw_res is not None and exit_mask.sum() >= 3:
        exit_yaw = yaw_res[exit_mask]
        if np.sum(exit_yaw > thresholds["yaw_residual_dps"]) >= 3:
            candidates.append(Candidate(EXIT_OVERSTEER, 1, "exit"))
        elif np.sum(exit_yaw < -thresholds["exit_yaw_understeer_dps"]) >= 3:
            candidates.append(Candidate(EXIT_UNDERSTEER, 2, "exit"))

    # Pedal-tier checks
    throttle = metrics.get("throttle")
    if tier == "full" and throttle is not None:
        mrp_m = metrics.get("mrp_m")

        # Early throttle: throttle > 50% before MRP + 2m (or v_min fallback)
        reference_m = (mrp_m + 2.0) if mrp_m is not None else metrics["s_vmin"]
        before_ref = (d >= s_apex) & (d < reference_m)  # exit zone only, not entry/braking
        if before_ref.any() and np.any(throttle[before_ref] > 50):
            candidates.append(Candidate(EARLY_THROTTLE, 2, "exit"))

        # Late throttle: first throttle application > 40% of exit zone past apex
        exit_zone_len = s_exit - s_apex
        late_threshold_m = s_apex + 0.4 * exit_zone_len
        first_throttle_idx = None
        for i in range(len(d)):
            if d[i] >= s_apex and throttle[i] > 10:
                first_throttle_idx = i
                break
        if first_throttle_idx is not None and d[first_throttle_idx] > late_threshold_m:
            candidates.append(Candidate(LATE_THROTTLE, 3, "exit"))

        # Throttle lift: drop > 20% before s_exit after initial application
        exit_throttle = throttle[exit_mask]
        if len(exit_throttle) > 5:
            peak_throttle = 0.0
            for val in exit_throttle:
                if val > peak_throttle:
                    peak_throttle = val
                elif peak_throttle > 20 and (peak_throttle - val) > 20:
                    candidates.append(Candidate(THROTTLE_LIFT, 2, "exit"))
                    break

    return candidates
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_corner_diagnosis.py::TestExitPhase -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/coaching/corner_diagnosis.py telemetry_tool/tests/test_corner_diagnosis.py
git commit -m "feat: exit phase checker with 6 labels including MRP"
```

---

### Task 7: Overall phase checker

**Files:**
- Modify: `telemetry_tool/coaching/corner_diagnosis.py`
- Test: `telemetry_tool/tests/test_corner_diagnosis.py`

- [ ] **Step 1: Write failing tests**

Append to `test_corner_diagnosis.py`:

```python
class TestOverallPhase:
    """Overall label detection: good, slow_exit, scrappy."""

    def test_slow_exit(self):
        from coaching.corner_diagnosis import _check_overall

        metrics = {"v_exit_mps": 22.0, "yaw_residual": np.zeros(100),
                   "throttle": None}
        theo = {"v_exit_mps": 24.0}  # 2 m/s = 7.2 km/h > 5 threshold
        thresholds = {"v_exit_delta_kmh": 5.0, "good_time_tol_s": 0.15,
                      "yaw_residual_dps": 10.0}
        existing = []  # no entry/apex causes
        labels = _check_overall(metrics, theo, thresholds, existing)
        assert any(c.label == "slow_exit" for c in labels)

    def test_slow_exit_suppressed_when_entry_cause_exists(self):
        from coaching.corner_diagnosis import _check_overall, Candidate

        metrics = {"v_exit_mps": 22.0, "yaw_residual": np.zeros(100),
                   "throttle": None}
        theo = {"v_exit_mps": 24.0}
        thresholds = {"v_exit_delta_kmh": 5.0, "good_time_tol_s": 0.15,
                      "yaw_residual_dps": 10.0}
        existing = [Candidate("entry_overspeed", 2, "entry")]
        labels = _check_overall(metrics, theo, thresholds, existing)
        assert not any(c.label == "slow_exit" for c in labels)

    def test_scrappy(self):
        from coaching.corner_diagnosis import _check_overall

        # 4 yaw sign reversals -> scrappy
        yaw = np.zeros(100)
        yaw[10:20] = 15
        yaw[20:30] = -15
        yaw[30:40] = 15
        yaw[40:50] = -15
        metrics = {"v_exit_mps": 28.0, "yaw_residual": yaw, "throttle": None}
        theo = {"v_exit_mps": 28.0}
        thresholds = {"v_exit_delta_kmh": 5.0, "good_time_tol_s": 0.15,
                      "yaw_residual_dps": 10.0}
        labels = _check_overall(metrics, theo, thresholds, [])
        assert any(c.label == "scrappy" for c in labels)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_corner_diagnosis.py::TestOverallPhase -v`
Expected: FAIL

- [ ] **Step 3: Implement `_check_overall`**

Append to `corner_diagnosis.py`:

```python
def _check_overall(
    metrics: dict, theo: dict | None, thresholds: dict,
    existing_candidates: list[Candidate],
) -> list[Candidate]:
    """Check overall labels: slow_exit, scrappy."""
    candidates: list[Candidate] = []

    # Slow exit: exit speed deficit with no entry/apex cause
    if theo and "v_exit_mps" in theo:
        delta_kmh = (theo["v_exit_mps"] - metrics["v_exit_mps"]) * 3.6
        has_upstream_cause = any(
            c.phase in ("entry", "apex") for c in existing_candidates
        )
        if delta_kmh > thresholds["v_exit_delta_kmh"] and not has_upstream_cause:
            candidates.append(Candidate(SLOW_EXIT, 3, "overall"))

    # Scrappy: many yaw sign reversals (spec: >2 sign-reversals in residual)
    yaw_res = metrics.get("yaw_residual")
    if yaw_res is not None and len(yaw_res) > 2:
        signs = np.sign(yaw_res)
        reversals = int(np.sum(np.abs(np.diff(signs)) > 0))
        if reversals > 2:
            candidates.append(Candidate(SCRAPPY, 3, "overall"))

    # Throttle modulations (scrappy via pedals)
    throttle = metrics.get("throttle")
    if throttle is not None and not any(c.label == SCRAPPY for c in candidates):
        # Count throttle on/off cycles above 20%
        above = throttle > 20
        transitions = np.sum(np.abs(np.diff(above.astype(int))))
        if transitions > 4:  # 2 full on/off cycles = 4 transitions
            candidates.append(Candidate(SCRAPPY, 3, "overall"))

    return candidates
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_corner_diagnosis.py::TestOverallPhase -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/coaching/corner_diagnosis.py telemetry_tool/tests/test_corner_diagnosis.py
git commit -m "feat: overall phase checker (good, slow_exit, scrappy)"
```

---

## Chunk 3: Resolution + Public API

### Task 8: Causal chain resolution and dominant label picker

**Files:**
- Modify: `telemetry_tool/coaching/corner_diagnosis.py`
- Test: `telemetry_tool/tests/test_corner_diagnosis.py`

- [ ] **Step 1: Write failing tests**

Append to `test_corner_diagnosis.py`:

```python
class TestCausalResolution:
    """Causal chain resolution and dominant label picking."""

    def test_entry_overspeed_is_root_of_entry_understeer(self):
        from coaching.corner_diagnosis import _resolve_and_pick, Candidate

        candidates = [
            Candidate("entry_overspeed", 2, "entry"),
            Candidate("entry_understeer", 2, "entry"),
        ]
        label = _resolve_and_pick(candidates)
        assert label == "entry_overspeed"

    def test_safety_label_wins_over_time_loss(self):
        from coaching.corner_diagnosis import _resolve_and_pick, Candidate

        candidates = [
            Candidate("entry_overspeed", 2, "entry"),
            Candidate("exit_oversteer", 1, "exit"),
        ]
        label = _resolve_and_pick(candidates)
        assert label == "exit_oversteer"

    def test_good_when_no_candidates(self):
        from coaching.corner_diagnosis import _resolve_and_pick

        label = _resolve_and_pick([])
        assert label == "good"

    def test_early_apex_is_root_over_slow_exit(self):
        from coaching.corner_diagnosis import _resolve_and_pick, Candidate

        candidates = [
            Candidate("early_apex", 2, "apex"),
            Candidate("slow_exit", 3, "overall"),
        ]
        label = _resolve_and_pick(candidates)
        assert label == "early_apex"

    def test_late_rotation_is_root_over_slow_exit(self):
        from coaching.corner_diagnosis import _resolve_and_pick, Candidate

        candidates = [
            Candidate("late_rotation", 2, "exit"),
            Candidate("slow_exit", 3, "overall"),
        ]
        label = _resolve_and_pick(candidates)
        assert label == "late_rotation"

    def test_early_throttle_is_root_of_exit_understeer(self):
        from coaching.corner_diagnosis import _resolve_and_pick, Candidate

        candidates = [
            Candidate("early_throttle", 2, "exit"),
            Candidate("exit_understeer", 2, "exit"),
        ]
        label = _resolve_and_pick(candidates)
        assert label == "early_throttle"

    def test_coast_hesitation_chain(self):
        from coaching.corner_diagnosis import _resolve_and_pick, Candidate

        candidates = [
            Candidate("coast_hesitation", 3, "apex"),
            Candidate("late_throttle", 3, "exit"),
        ]
        label = _resolve_and_pick(candidates)
        assert label == "coast_hesitation"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_corner_diagnosis.py::TestCausalResolution -v`
Expected: FAIL

- [ ] **Step 3: Implement `_resolve_and_pick`**

Append to `corner_diagnosis.py`:

```python
def _resolve_and_pick(candidates: list[Candidate]) -> str:
    """Resolve causal chains and return the single dominant label.

    1. Remove labels that are downstream of a present root cause.
    2. Pick the highest-priority remaining label.
    3. Return "good" if nothing remains.
    """
    if not candidates:
        return GOOD

    # Build set of present labels
    present = {c.label for c in candidates}

    # Remove downstream labels when their upstream cause is present
    to_remove: set[str] = set()
    for child, parent in _CAUSAL_PARENT.items():
        if child in present and parent in present:
            to_remove.add(child)

    # Also check "always" chains (e.g. slow_exit removed when early_apex or late_rotation present)
    for child, parents in _CAUSAL_ALWAYS.items():
        if child in present and any(p in present for p in parents):
            to_remove.add(child)

    filtered = [c for c in candidates if c.label not in to_remove]
    if not filtered:
        return GOOD

    # Sort by priority (lower = higher priority), then prefer safety labels
    filtered.sort(key=lambda c: (c.priority, c.label not in _SAFETY_LABELS))
    return filtered[0].label
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_corner_diagnosis.py::TestCausalResolution -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/coaching/corner_diagnosis.py telemetry_tool/tests/test_corner_diagnosis.py
git commit -m "feat: causal chain resolution and dominant label picker"
```

---

### Task 9: Public API `classify_all_corners`

**Files:**
- Modify: `telemetry_tool/coaching/corner_diagnosis.py`
- Test: `telemetry_tool/tests/test_corner_diagnosis.py`

- [ ] **Step 1: Write failing tests**

Append to `test_corner_diagnosis.py`:

```python
class TestClassifyAllCorners:
    """End-to-end classify_all_corners tests."""

    def test_basic_grid_shape(self):
        from coaching.corner_diagnosis import classify_all_corners

        lap_df = _make_lap_df(v_entry_mps=30.0, v_min_mps=20.0, v_exit_mps=28.0)
        corners = [_make_corner(s_entry=50.0, s_apex=100.0, s_exit=150.0, corner_index=1)]
        # Theoretical with matching speeds (should produce "good")
        theo_df = _make_lap_df(v_entry_mps=30.0, v_min_mps=20.0, v_exit_mps=28.0)

        result = classify_all_corners(
            resampled_laps={2: lap_df},
            theoretical_lap=theo_df,
            user_corners=corners,
            vehicle_class="car",
            valid_lap_numbers=[2],
        )
        assert "2" in result
        assert "1" in result["2"]
        assert isinstance(result["2"]["1"], str)

    def test_multiple_laps_and_corners(self):
        from coaching.corner_diagnosis import classify_all_corners

        lap_df_fast = _make_lap_df(v_entry_mps=33.0, v_min_mps=20.0, v_exit_mps=28.0)
        lap_df_good = _make_lap_df(v_entry_mps=30.0, v_min_mps=20.0, v_exit_mps=28.0)
        theo = _make_lap_df(v_entry_mps=30.0, v_min_mps=20.0, v_exit_mps=28.0)

        corners = [
            _make_corner(s_entry=50.0, s_apex=100.0, s_exit=150.0, corner_index=1),
        ]
        result = classify_all_corners(
            resampled_laps={2: lap_df_fast, 3: lap_df_good},
            theoretical_lap=theo,
            user_corners=corners,
            vehicle_class="car",
            valid_lap_numbers=[2, 3],
        )
        assert "2" in result and "3" in result
        # Lap 2 is too fast into corner (33 vs 30 m/s = 10.8 km/h over)
        assert result["2"]["1"] == "entry_overspeed"

    def test_empty_corners_returns_empty(self):
        from coaching.corner_diagnosis import classify_all_corners

        result = classify_all_corners(
            resampled_laps={2: _make_lap_df()},
            theoretical_lap=_make_lap_df(),
            user_corners=[],
            vehicle_class="car",
            valid_lap_numbers=[2],
        )
        assert result == {}

    def test_no_theoretical_returns_null_labels(self):
        from coaching.corner_diagnosis import classify_all_corners

        corners = [_make_corner()]
        result = classify_all_corners(
            resampled_laps={2: _make_lap_df()},
            theoretical_lap=None,
            user_corners=corners,
            vehicle_class="car",
            valid_lap_numbers=[2],
        )
        # Should still produce a grid, labels may be "good" or null
        assert "2" in result

    def test_kart_thresholds_applied(self):
        from coaching.corner_diagnosis import classify_all_corners

        # 2.5 km/h over: above kart threshold (2) but below car threshold (3)
        v_over = 30.0 + 2.5 / 3.6  # ~30.7 m/s
        lap_df = _make_lap_df(v_entry_mps=v_over, v_min_mps=20.0, v_exit_mps=28.0)
        theo = _make_lap_df(v_entry_mps=30.0, v_min_mps=20.0, v_exit_mps=28.0)
        corners = [_make_corner()]

        result_kart = classify_all_corners(
            resampled_laps={2: lap_df},
            theoretical_lap=theo,
            user_corners=corners,
            vehicle_class="kart",
            valid_lap_numbers=[2],
        )
        result_car = classify_all_corners(
            resampled_laps={2: lap_df},
            theoretical_lap=theo,
            user_corners=corners,
            vehicle_class="car",
            valid_lap_numbers=[2],
        )
        assert result_kart["2"]["1"] == "entry_overspeed"
        # Car may or may not fire depending on exact interpolation
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_corner_diagnosis.py::TestClassifyAllCorners -v`
Expected: FAIL

- [ ] **Step 3: Implement `classify_all_corners` and helpers**

Append to `corner_diagnosis.py`:

```python
# ---------------------------------------------------------------------------
# MRP key mapping
# ---------------------------------------------------------------------------
def _map_mrp_to_corners(
    user_corners: list[dict], mrp_events: dict[int, dict] | None,
) -> dict[int, dict | None]:
    """Map user corner_index to MRP event dict.

    Strategy: positional match first (sorted corner_index vs sorted section_id),
    then spatial fallback (overlapping distance ranges).
    Returns {corner_index: mrp_event_dict_or_None}.
    """
    result: dict[int, dict | None] = {c["corner_index"]: None for c in user_corners}
    if not mrp_events:
        return result

    sorted_corners = sorted(user_corners, key=lambda c: c["corner_index"])
    sorted_mrp_keys = sorted(mrp_events.keys())

    # Positional match
    if len(sorted_corners) == len(sorted_mrp_keys):
        for corner, mrp_key in zip(sorted_corners, sorted_mrp_keys):
            result[corner["corner_index"]] = mrp_events[mrp_key]
        return result

    # Spatial fallback: overlap between corner [s_entry, s_exit] and MRP [s_start, s_end]
    for corner in sorted_corners:
        s_entry = corner["s_entry"]
        s_exit = corner["s_exit"]
        for mrp_key, mrp_ev in mrp_events.items():
            mrp_m = mrp_ev.get("mrp_m", 0)
            if s_entry <= mrp_m <= s_exit:
                result[corner["corner_index"]] = mrp_ev
                break

    return result


# ---------------------------------------------------------------------------
# Theoretical metrics extraction
# ---------------------------------------------------------------------------
def _extract_theo_metrics(
    theoretical_lap: pd.DataFrame | None, corner: dict,
) -> dict | None:
    """Extract theoretical speed metrics for a corner from the theoretical lap."""
    if theoretical_lap is None:
        return None
    if _COL_DIST not in theoretical_lap.columns or _COL_SPEED not in theoretical_lap.columns:
        return None

    d = theoretical_lap[_COL_DIST].values
    v = theoretical_lap[_COL_SPEED].values
    s_entry = corner["s_entry"]
    s_apex = corner["s_apex"]
    s_exit = corner["s_exit"]

    mask = (d >= s_entry) & (d <= s_exit)
    if mask.sum() < 3:
        return None

    seg_d = d[mask]
    seg_v = v[mask]

    return {
        "v_entry_mps": float(np.interp(s_entry, seg_d, seg_v)),
        "v_min_mps": float(np.min(seg_v)),
        "v_exit_mps": float(np.interp(s_exit, seg_d, seg_v)),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def classify_all_corners(
    resampled_laps: dict[int, pd.DataFrame],
    theoretical_lap: pd.DataFrame | None,
    user_corners: list[dict],
    vehicle_class: str,
    valid_lap_numbers: list[int],
    curvature_profile: pd.DataFrame | None = None,
    mrp_events: dict[int, dict] | None = None,
) -> dict[str, dict[str, str | None]]:
    """Classify driving symptoms for each user corner on every valid lap.

    Returns {lap_num_str: {corner_index_str: label}}.
    """
    if not user_corners or not valid_lap_numbers:
        return {}

    thresholds = _get_thresholds(vehicle_class)
    mrp_map = _map_mrp_to_corners(user_corners, mrp_events)

    # Pre-compute theoretical metrics per corner
    theo_per_corner: dict[int, dict | None] = {}
    for corner in user_corners:
        cid = corner["corner_index"]
        theo_per_corner[cid] = _extract_theo_metrics(theoretical_lap, corner)

    result: dict[str, dict[str, str]] = {}

    for lap_num in valid_lap_numbers:
        lap_df = resampled_laps.get(lap_num)
        if lap_df is None or lap_df.empty:
            continue

        tier = _detect_tier(set(lap_df.columns))
        lap_labels: dict[str, str] = {}

        for corner in user_corners:
            cid = corner["corner_index"]
            mrp_event = mrp_map.get(cid)
            theo = theo_per_corner.get(cid)

            metrics = _extract_corner_metrics(lap_df, corner, curvature_profile, mrp_event)
            if metrics is None:
                lap_labels[str(cid)] = None
                continue

            # Run all phase checkers
            entry = _check_entry_phase(metrics, theo, thresholds, tier)
            apex = _check_apex_phase(metrics, theo, thresholds, tier)
            exit_ = _check_exit_phase(metrics, theo, thresholds, tier)
            all_phase = entry + apex + exit_
            overall = _check_overall(metrics, theo, thresholds, all_phase)
            all_candidates = all_phase + overall

            lap_labels[str(cid)] = _resolve_and_pick(all_candidates)

        result[str(lap_num)] = lap_labels

    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_corner_diagnosis.py::TestClassifyAllCorners -v`
Expected: 5 passed

- [ ] **Step 5: Run all tests to verify nothing broke**

Run: `cd telemetry_tool && python -m pytest tests/test_corner_diagnosis.py -v`
Expected: All tests pass (~31 total)

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/coaching/corner_diagnosis.py telemetry_tool/tests/test_corner_diagnosis.py
git commit -m "feat: classify_all_corners public API with MRP mapping"
```

---

## Chunk 4: Pipeline Integration

### Task 10: Wire into orchestrator — fetch user corners + S10h step

**Files:**
- Modify: `telemetry_tool/pipeline/orchestrator.py`
- Test: `telemetry_tool/tests/test_corner_diagnosis.py`

- [ ] **Step 1: Write failing integration test**

Append to `test_corner_diagnosis.py`:

```python
class TestOrchestratorWiring:
    """Test the _fetch_user_corners helper and pipeline integration."""

    def test_fetch_user_corners_returns_list(self, test_db):
        """_fetch_user_corners returns [] when no corners exist."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
        from pipeline.orchestrator import _fetch_user_corners

        rows = _fetch_user_corners(test_db, "nonexistent_session")
        assert rows == []

    def test_fetch_user_corners_with_data(self, test_db):
        from pipeline.orchestrator import _fetch_user_corners

        test_db.execute(
            "INSERT INTO user_corners (session_id, corner_index, s_entry, s_apex, s_exit, "
            "lat_entry, lon_entry, lat_apex, lon_apex, lat_exit, lon_exit) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("sess1", 1, 50.0, 100.0, 150.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        )
        test_db.commit()
        rows = _fetch_user_corners(test_db, "sess1")
        assert len(rows) == 1
        assert rows[0]["corner_index"] == 1
        assert rows[0]["s_entry"] == 50.0

    def test_fetch_user_corners_none_conn(self):
        from pipeline.orchestrator import _fetch_user_corners

        assert _fetch_user_corners(None, "sess1") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_corner_diagnosis.py::TestOrchestratorWiring -v`
Expected: FAIL with `ImportError: cannot import name '_fetch_user_corners'`

- [ ] **Step 3: Add `_fetch_user_corners` to orchestrator**

In `telemetry_tool/pipeline/orchestrator.py`, add after the existing import block (around line 30), or near the end of the module before the main `run_pipeline` function. The best location is near other DB helper functions. Add:

```python
def _fetch_user_corners(conn, session_id: str) -> list[dict] | None:
    """Fetch user-placed corner definitions for a session.

    Returns [] on success with no rows, None when conn/session_id missing.
    """
    if conn is None or not session_id:
        return None
    cursor = conn.execute(
        "SELECT corner_index, s_entry, s_apex, s_exit, lat_entry, lon_entry, "
        "lat_apex, lon_apex, lat_exit, lon_exit FROM user_corners WHERE session_id = ?",
        (session_id,),
    )
    return [dict(zip([d[0] for d in cursor.description], row)) for row in cursor.fetchall()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_corner_diagnosis.py::TestOrchestratorWiring -v`
Expected: 3 passed

- [ ] **Step 5: Wire S10h into the orchestrator pipeline**

In `telemetry_tool/pipeline/orchestrator.py`, after the S10g4 coaching block (around line 1001, after the `if v2_sections:` block ends), add:

```python
    # ── Step S10h: Corner diagnosis grid ──────────────────────────
    user_corner_rows, _err = _safe_step(
        "S10h_fetch_user_corners",
        lambda: _fetch_user_corners(_v2_conn, str(meta.get("session_id", ""))),
    )
    _record("S10h_fetch_user_corners", user_corner_rows, _err)

    if user_corner_rows:
        from coaching.corner_diagnosis import classify_all_corners as _classify_corners

        corner_labels, _err = _safe_step(
            "S10h_corner_labels",
            lambda: _classify_corners(
                resampled_laps=resampled_laps,
                theoretical_lap=theoretical_lap,
                user_corners=user_corner_rows,
                vehicle_class=meta.get("vehicle_class", "car"),
                valid_lap_numbers=[k for k in resampled_laps if k not in excluded_laps],
                curvature_profile=curvature_profile,
                mrp_events=summary.get("mrp_events_v2"),
            ),
        )
        _record("S10h_corner_labels", corner_labels, _err)
        if corner_labels is not None:
            summary["corner_labels"] = corner_labels  # propagates to API via _analysis_json_blob
```

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/pipeline/orchestrator.py telemetry_tool/tests/test_corner_diagnosis.py
git commit -m "feat: wire S10h corner diagnosis into pipeline orchestrator"
```

---

### Task 11: Rewire V3 coaching block to user corners

**Files:**
- Modify: `telemetry_tool/pipeline/orchestrator.py`

- [ ] **Step 1: Add `_build_corner_perfs_from_user_corners` to orchestrator**

In `telemetry_tool/pipeline/orchestrator.py`, add near `_fetch_user_corners`:

```python
def _build_corner_perfs_from_user_corners(
    user_corner_rows: list[dict],
    best_lap_df: Any,
    sim_result: Any,
    vehicle_class: str = "car",
) -> list[dict]:
    """Convert user corner rows to corner_perf dicts for V3 analyzers.

    Key mapping: s_entry->s_start, s_exit->s_end, corner_index->corner_id.
    """
    perfs = []
    for row in user_corner_rows:
        perf = {
            "corner_id": row["corner_index"],
            "s_start": row["s_entry"],
            "s_end": row["s_exit"],
            "s_apex": row["s_apex"],
            "braking_decel_mps2": 6.0,
            "cornering_accel_mps2": 5.0,
            "exit_accel_mps2": 3.0,
            "vehicle_class": vehicle_class,
        }
        # Try to extract actual values from best lap segment
        if best_lap_df is not None and "Distance (m)" in best_lap_df.columns:
            d = best_lap_df["Distance (m)"].values
            mask = (d >= row["s_entry"]) & (d <= row["s_exit"])
            if mask.sum() > 5:
                seg = best_lap_df[mask]  # boolean indexing, safe for non-default index
                if "accel_long_mps2" in seg.columns:
                    a_long = seg["accel_long_mps2"].values
                    braking = a_long[a_long < 0]
                    accel = a_long[a_long > 0]
                    if len(braking) > 0:
                        perf["braking_decel_mps2"] = abs(float(np.mean(braking)))
                    if len(accel) > 0:
                        perf["exit_accel_mps2"] = float(np.mean(accel))
                if "accel_lat_mps2" in seg.columns:
                    lat = np.abs(seg["accel_lat_mps2"].values)
                    if len(lat) > 0:
                        perf["cornering_accel_mps2"] = float(np.mean(lat))
        perfs.append(perf)
    return perfs
```

- [ ] **Step 2: Rewire the V3 coaching block**

In `telemetry_tool/pipeline/orchestrator.py`, right before the `# ── Coaching V3 (feature-flagged, default ON) ──` block (line ~1102), add:

```python
    # Build user-corner-based perfs for V3 if user corners available
    v3_corner_perfs = corner_performances  # default: auto-detected
    if user_corner_rows:
        _v3_perfs, _err = _safe_step(
            "S10h_build_v3_perfs",
            lambda: _build_corner_perfs_from_user_corners(
                user_corner_rows, best_lap_df, _sim_result,
                vehicle_class=meta.get("vehicle_class", "car"),
            ),
        )
        if _v3_perfs:
            v3_corner_perfs = _v3_perfs
```

Then modify the V3 block to use `v3_corner_perfs` instead of `corner_performances`. Change line 1108:

```python
        # WAS: corner_perfs=corner_performances,
        corner_perfs=v3_corner_perfs,
```

And line 1121:

```python
        # WAS: corner_ids=[c["corner_id"] for c in (corner_performances or [])],
        corner_ids=[c["corner_id"] for c in (v3_corner_perfs or [])],
```

And line 1127:

```python
        # WAS: corner_perfs=corner_performances,
        corner_perfs=v3_corner_perfs,
```

**CRITICAL**: Do NOT change any other reference to `corner_performances` — scoring (line 1037), driving_style (line 1057), coaching_guide (line 1068), coaching_v2 (line 1080), and HTML report (line 1238) all keep using the original `corner_performances`.

- [ ] **Step 3: Run existing pipeline tests**

Run: `cd telemetry_tool && python -m pytest tests/ -k "pipeline or re_port" --timeout=60 -v`
Expected: All existing tests pass (no regressions)

- [ ] **Step 4: Commit**

```bash
git add telemetry_tool/pipeline/orchestrator.py
git commit -m "feat: rewire V3 coaching block to user corners"
```

---

### Task 12: Final test pass and cleanup

**Files:**
- Test: `telemetry_tool/tests/test_corner_diagnosis.py`

- [ ] **Step 1: Run the full test suite**

Run: `cd telemetry_tool && python -m pytest tests/test_corner_diagnosis.py -v`
Expected: All ~33 tests pass

- [ ] **Step 2: Run the full project test suite to check for regressions**

Run: `cd telemetry_tool && python -m pytest tests/ --timeout=120 -x -q`
Expected: All tests pass, no regressions

- [ ] **Step 3: Commit if any cleanup was needed**

```bash
git add -A
git commit -m "test: corner diagnosis full test pass"
```

---

## Summary

| Task | What | Est. Time |
|------|------|-----------|
| 1 | `CornerEvents.to_dict()` prerequisite | 2 min |
| 2 | Thresholds + tier detection | 3 min |
| 3 | Segment extraction + metrics | 5 min |
| 4 | Entry phase checker (8 labels) | 5 min |
| 5 | Apex phase checker (6 labels) | 5 min |
| 6 | Exit phase checker (6 labels + MRP) | 5 min |
| 7 | Overall phase checker (3 labels) | 3 min |
| 8 | Causal chain resolution | 3 min |
| 9 | `classify_all_corners` public API | 5 min |
| 10 | Orchestrator wiring (fetch + S10h) | 5 min |
| 11 | V3 coaching block rewire | 5 min |
| 12 | Final test pass | 3 min |

**Total: 12 tasks, ~49 min**
