# Traffic Detection + Lap Inclusion Policy Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Detect traffic-induced speed lifts on straights, exclude/mask contaminated laps from envelope learning, and split lap inclusion into learning vs display sets with queryable exclusion reasons.

**Architecture:** New `traffic_detection.py` detects straights from curvature then flags per-lap traffic events via cross-lap envelope comparison + a_long correlation. New `lap_inclusion.py` builds a `LapInclusionPolicy` with learning/display sets and per-lap traffic masks. `theoretical_engine.py` gains a `masks` parameter to NaN-out traffic segments before percentile computation. Pipeline stage 9.5 orchestrates detection + policy, stages 10+13 consume the policy.

**Tech Stack:** Python 3.x, NumPy, pandas, pytest

---

### Task 1: TrafficEvent + TrafficResult dataclasses

**Files:**
- Create: `telemetry_tool/traffic_detection.py`
- Create: `telemetry_tool/tests/test_traffic_detection.py`

**Step 1: Write the failing tests**

In `telemetry_tool/tests/test_traffic_detection.py`:

```python
"""Tests for traffic detection module."""
import numpy as np
import pandas as pd
import pytest


def test_traffic_event_fields():
    """TrafficEvent has all required fields."""
    from traffic_detection import TrafficEvent

    ev = TrafficEvent(
        lap_number=3,
        s_start=100.0,
        s_end=200.0,
        speed_deficit_pct=8.5,
        max_decel_mps2=-1.2,
    )
    assert ev.lap_number == 3
    assert ev.s_end - ev.s_start == 100.0
    d = ev.to_dict()
    assert "lap_number" in d
    assert "speed_deficit_pct" in d


def test_traffic_result_fields():
    """TrafficResult has required fields and to_dict()."""
    from traffic_detection import TrafficResult, TrafficEvent

    ev = TrafficEvent(1, 50.0, 100.0, 6.0, -0.8)
    result = TrafficResult(
        straights=[{"s_start": 0.0, "s_end": 200.0, "length_m": 200.0}],
        events=[ev],
        per_lap_score={1: 0.25},
        n_laps_affected=1,
    )
    assert result.n_laps_affected == 1
    d = result.to_dict()
    assert "events" in d
    assert "per_lap_score" in d
    assert isinstance(d["events"], list)


def test_traffic_result_empty():
    """TrafficResult with no events."""
    from traffic_detection import TrafficResult

    result = TrafficResult(
        straights=[],
        events=[],
        per_lap_score={},
        n_laps_affected=0,
    )
    d = result.to_dict()
    assert d["n_laps_affected"] == 0
    assert len(d["events"]) == 0
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_traffic_detection.py -v`
Expected: FAIL with "cannot import name 'TrafficEvent'"

**Step 3: Write minimal implementation**

In `telemetry_tool/traffic_detection.py`:

```python
"""
traffic_detection.py
--------------------
Detect traffic-induced speed lifts on straights.

Uses curvature-based straight detection and cross-lap speed envelope
comparison to flag segments where the driver lifted due to slower
traffic ahead. Produces per-lap traffic_score and per-segment flags.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict, field
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── Column name constants ──────────────────────────────────────────
_COL_DIST = "Distance (m)"
_COL_SPEED = "Speed (m/s)"
_COL_BEARING = "Bearing (deg)"
_COL_ACCEL_LONG = "accel_long_mps2"
_COL_YAW = "yaw_rate_dps"

# ── Detection thresholds ──────────────────────────────────────────
_CURVATURE_STRAIGHT_THRESHOLD = 0.005  # 1/m — below this is "straight"
_MIN_STRAIGHT_LENGTH_M = 30.0          # metres — minimum straight segment
_SPEED_DEFICIT_FACTOR = 0.95           # flag when v < envelope * this
_MIN_DEFICIT_LENGTH_M = 10.0           # metres — minimum continuous deficit
_DECEL_THRESHOLD_MPS2 = -0.5           # m/s² — unexplained braking
_CORNER_PROXIMITY_M = 20.0             # metres — don't flag near corners
_ENVELOPE_PERCENTILE = 90.0            # cross-lap speed envelope percentile


@dataclass
class TrafficEvent:
    """A single traffic-induced speed lift on a straight."""
    lap_number: int
    s_start: float              # metres
    s_end: float                # metres
    speed_deficit_pct: float    # how much below envelope (%)
    max_decel_mps2: float       # worst a_long in event (m/s²)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TrafficResult:
    """Result of traffic detection across all laps."""
    straights: list[dict]           # detected straight segments
    events: list[TrafficEvent]      # all traffic events
    per_lap_score: dict[int, float] # lap_number → traffic_score [0-1]
    n_laps_affected: int

    def to_dict(self) -> dict:
        return {
            "straights": list(self.straights),
            "events": [e.to_dict() for e in self.events],
            "per_lap_score": dict(self.per_lap_score),
            "n_laps_affected": self.n_laps_affected,
        }
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_traffic_detection.py -v`
Expected: 3 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/traffic_detection.py telemetry_tool/tests/test_traffic_detection.py
git commit -m "feat(traffic): add TrafficEvent and TrafficResult dataclasses"
```

---

### Task 2: Straight detection from curvature

**Files:**
- Modify: `telemetry_tool/traffic_detection.py` (append)
- Modify: `telemetry_tool/tests/test_traffic_detection.py` (append)

**Step 1: Write the failing tests**

Append to `telemetry_tool/tests/test_traffic_detection.py`:

```python


def _make_oval_lap(n=500, straight_len=200.0, corner_radius=30.0, speed=20.0):
    """Synthetic oval: two straights + two corners.

    Layout: straight1 (0–200m) → corner1 (200–294m) → straight2 (294–494m)
    → corner2 (494–588m). Total ~588m.
    """
    rng = np.random.default_rng(42)

    # Build distance + heading arrays
    ds = []  # heading at each point
    total_d = 0.0
    distances = []
    headings = []

    # Straight 1: heading = 0 (east)
    s1_dist = np.linspace(0, straight_len, n // 4)
    s1_hdg = np.zeros(len(s1_dist))

    # Corner 1: 180° turn (pi radians over semi-circle)
    arc_len = np.pi * corner_radius
    c1_dist = np.linspace(0, arc_len, n // 4) + straight_len
    c1_hdg = np.linspace(0, np.pi, len(c1_dist))

    # Straight 2: heading = pi (west)
    s2_start = straight_len + arc_len
    s2_dist = np.linspace(0, straight_len, n // 4) + s2_start
    s2_hdg = np.full(len(s2_dist), np.pi)

    # Corner 2: 180° turn back
    c2_start = s2_start + straight_len
    c2_dist = np.linspace(0, arc_len, n // 4) + c2_start
    c2_hdg = np.linspace(np.pi, 2 * np.pi, len(c2_dist))

    all_dist = np.concatenate([s1_dist, c1_dist, s2_dist, c2_dist])
    all_hdg = np.concatenate([s1_hdg, c1_hdg, s2_hdg, c2_hdg])

    df = pd.DataFrame({
        "Distance (m)": all_dist,
        "Speed (m/s)": np.full(len(all_dist), speed) + rng.normal(0, 0.2, len(all_dist)),
        "Bearing (deg)": np.degrees(all_hdg) % 360,
        "accel_long_mps2": rng.normal(0, 0.1, len(all_dist)),
        "yaw_rate_dps": np.zeros(len(all_dist)),
    })
    # Compute yaw_rate from heading changes
    dt = np.diff(all_dist) / speed
    dhdg = np.diff(all_hdg)
    yr = np.concatenate([[0], dhdg / np.where(dt > 0, dt, 0.01)])
    df["yaw_rate_dps"] = np.degrees(yr)

    return df


def test_detect_straights_oval():
    """Oval track with 2 straights → detects 2 straight segments."""
    from traffic_detection import detect_straights

    df = _make_oval_lap()
    straights = detect_straights(df)
    assert len(straights) >= 2
    for s in straights:
        assert s["length_m"] >= 30.0
        assert s["s_end"] > s["s_start"]


def test_detect_straights_circle():
    """Constant-radius circle → no straights detected."""
    from traffic_detection import detect_straights

    n = 300
    radius = 50.0
    speed = 15.0
    omega = speed / radius
    t = np.arange(n) * 0.1
    theta = omega * t
    dist = speed * t

    df = pd.DataFrame({
        "Distance (m)": dist,
        "Speed (m/s)": np.full(n, speed),
        "Bearing (deg)": np.degrees(theta) % 360,
        "accel_long_mps2": np.zeros(n),
        "yaw_rate_dps": np.full(n, np.degrees(omega)),
    })
    straights = detect_straights(df)
    assert len(straights) == 0
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_traffic_detection.py::test_detect_straights_oval -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Append to `telemetry_tool/traffic_detection.py`:

```python


def _compute_curvature(df: "pd.DataFrame") -> np.ndarray:
    """Compute curvature from heading derivative w.r.t. distance.

    curvature = dheading/ds (rad/m).
    Uses Bearing (deg) and Distance (m) columns.
    """
    import pandas as pd

    bearing = pd.to_numeric(df[_COL_BEARING], errors="coerce").values.astype(float)
    dist = pd.to_numeric(df[_COL_DIST], errors="coerce").values.astype(float)

    # Convert bearing to radians, unwrap to remove 0/360 jumps
    hdg_rad = np.unwrap(np.radians(bearing))

    # dheading / ds
    ds = np.diff(dist)
    dh = np.diff(hdg_rad)
    ds = np.where(ds > 0, ds, np.nan)

    curvature = np.concatenate([[0.0], dh / ds])
    curvature = np.where(np.isfinite(curvature), curvature, 0.0)

    # Smooth with a small window to reduce noise
    if len(curvature) > 7:
        kernel = np.ones(7) / 7
        curvature = np.convolve(curvature, kernel, mode="same")

    return curvature


def detect_straights(
    df: "pd.DataFrame",
    *,
    curvature_threshold: float = _CURVATURE_STRAIGHT_THRESHOLD,
    min_length_m: float = _MIN_STRAIGHT_LENGTH_M,
) -> list[dict]:
    """Detect straight segments from curvature.

    Returns list of dicts with keys: s_start, s_end, length_m.
    """
    import pandas as pd

    if _COL_BEARING not in df.columns or _COL_DIST not in df.columns:
        logger.warning("detect_straights: missing Bearing or Distance column.")
        return []

    dist = pd.to_numeric(df[_COL_DIST], errors="coerce").values.astype(float)
    curvature = _compute_curvature(df)

    # Identify low-curvature regions
    is_straight = np.abs(curvature) < curvature_threshold

    # Find contiguous runs of True
    straights = []
    in_straight = False
    start_idx = 0

    for i in range(len(is_straight)):
        if is_straight[i] and not in_straight:
            start_idx = i
            in_straight = True
        elif not is_straight[i] and in_straight:
            s_start = float(dist[start_idx])
            s_end = float(dist[i - 1])
            length = s_end - s_start
            if length >= min_length_m:
                straights.append({
                    "s_start": round(s_start, 1),
                    "s_end": round(s_end, 1),
                    "length_m": round(length, 1),
                })
            in_straight = False

    # Handle straight that extends to end
    if in_straight:
        s_start = float(dist[start_idx])
        s_end = float(dist[-1])
        length = s_end - s_start
        if length >= min_length_m:
            straights.append({
                "s_start": round(s_start, 1),
                "s_end": round(s_end, 1),
                "length_m": round(length, 1),
            })

    logger.info("detect_straights: found %d straight segments.", len(straights))
    return straights
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_traffic_detection.py -v`
Expected: 5 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/traffic_detection.py telemetry_tool/tests/test_traffic_detection.py
git commit -m "feat(traffic): add curvature-based straight detection"
```

---

### Task 3: Cross-lap traffic flagging + traffic_score

**Files:**
- Modify: `telemetry_tool/traffic_detection.py` (append)
- Modify: `telemetry_tool/tests/test_traffic_detection.py` (append)

**Step 1: Write the failing tests**

Append to `telemetry_tool/tests/test_traffic_detection.py`:

```python


def test_traffic_flag_injected_lift():
    """Lap with injected speed lift on straight → flagged as traffic."""
    from traffic_detection import run_traffic_detection

    # Create 5 identical laps on an oval
    base = _make_oval_lap(speed=25.0)
    laps = {}
    for i in range(1, 6):
        laps[i] = base.copy()

    # Inject traffic lift on lap 3: drop speed by 30% on first straight (50-150m)
    lap3 = laps[3].copy()
    dist = lap3["Distance (m)"].values
    mask = (dist >= 50) & (dist <= 150)
    lap3.loc[mask, "Speed (m/s)"] = lap3.loc[mask, "Speed (m/s)"] * 0.7
    lap3.loc[mask, "accel_long_mps2"] = -2.0  # hard decel
    laps[3] = lap3

    result = run_traffic_detection(laps)
    assert result.n_laps_affected >= 1
    assert 3 in result.per_lap_score
    assert result.per_lap_score[3] > 0.0

    # Other laps should have low/zero traffic scores
    for lap_num in [1, 2, 4, 5]:
        assert result.per_lap_score.get(lap_num, 0.0) < 0.1


def test_clean_laps_no_traffic():
    """All identical laps → zero traffic on all."""
    from traffic_detection import run_traffic_detection

    base = _make_oval_lap(speed=20.0)
    laps = {i: base.copy() for i in range(1, 6)}

    result = run_traffic_detection(laps)
    assert result.n_laps_affected == 0
    for score in result.per_lap_score.values():
        assert score == 0.0
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_traffic_detection.py::test_traffic_flag_injected_lift -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Append to `telemetry_tool/traffic_detection.py`:

```python


def _flag_straight_traffic(
    laps: dict[int, "pd.DataFrame"],
    straight: dict,
    corner_entries: list[float],
) -> list[TrafficEvent]:
    """Flag traffic events on a single straight segment across all laps.

    1. Extract speed for each lap on this straight
    2. Build p90 envelope across laps
    3. For each lap, check speed deficit + unexplained decel
    """
    import pandas as pd

    s_start = straight["s_start"]
    s_end = straight["s_end"]
    events = []

    # Build shared distance grid for this straight
    n_grid = max(20, int((s_end - s_start) / 2.0))
    grid = np.linspace(s_start, s_end, n_grid)

    # Interpolate each lap's speed onto grid
    speed_matrix = np.full((len(laps), n_grid), np.nan)
    accel_matrix = np.full((len(laps), n_grid), np.nan)
    lap_keys = sorted(laps.keys())

    for i, lap_num in enumerate(lap_keys):
        df = laps[lap_num]
        dist = pd.to_numeric(df[_COL_DIST], errors="coerce").values
        speed = pd.to_numeric(df[_COL_SPEED], errors="coerce").values
        mask = np.isfinite(dist) & np.isfinite(speed)
        if mask.sum() < 2:
            continue
        d_m, s_m = dist[mask], speed[mask]
        order = np.argsort(d_m)
        speed_matrix[i] = np.interp(grid, d_m[order], s_m[order])

        # Accel
        if _COL_ACCEL_LONG in df.columns:
            accel = pd.to_numeric(df[_COL_ACCEL_LONG], errors="coerce").values
            a_m = accel[mask]
            accel_matrix[i] = np.interp(grid, d_m[order], a_m[order])

    # Build p90 envelope
    envelope = np.nanpercentile(speed_matrix, _ENVELOPE_PERCENTILE, axis=0)
    if not np.any(np.isfinite(envelope)):
        return events

    # Check each lap against envelope
    threshold = envelope * _SPEED_DEFICIT_FACTOR

    for i, lap_num in enumerate(lap_keys):
        if not np.any(np.isfinite(speed_matrix[i])):
            continue

        # Find deficit zones: v_lap < threshold
        is_deficit = speed_matrix[i] < threshold
        if not np.any(is_deficit):
            continue

        # Find contiguous deficit runs >= MIN_DEFICIT_LENGTH_M
        deficit_runs = _find_contiguous_runs(is_deficit, grid, _MIN_DEFICIT_LENGTH_M)

        for run_start, run_end in deficit_runs:
            # Check for unexplained decel within this run
            run_mask = (grid >= run_start) & (grid <= run_end)

            # Skip if near a corner entry
            near_corner = any(
                abs(ce - run_start) < _CORNER_PROXIMITY_M or
                abs(ce - run_end) < _CORNER_PROXIMITY_M
                for ce in corner_entries
            )
            if near_corner:
                continue

            accel_in_run = accel_matrix[i, run_mask]
            if not np.any(np.isfinite(accel_in_run)):
                continue

            max_decel = float(np.nanmin(accel_in_run))
            if max_decel > _DECEL_THRESHOLD_MPS2:
                continue  # No unexplained braking

            # Compute speed deficit percentage
            env_in_run = envelope[run_mask]
            spd_in_run = speed_matrix[i, run_mask]
            finite = np.isfinite(env_in_run) & np.isfinite(spd_in_run) & (env_in_run > 0)
            if not np.any(finite):
                continue
            deficit_pct = float(np.nanmean(
                (env_in_run[finite] - spd_in_run[finite]) / env_in_run[finite] * 100
            ))

            events.append(TrafficEvent(
                lap_number=lap_num,
                s_start=round(run_start, 1),
                s_end=round(run_end, 1),
                speed_deficit_pct=round(deficit_pct, 1),
                max_decel_mps2=round(max_decel, 2),
            ))

    return events


def _find_contiguous_runs(
    mask: np.ndarray, distances: np.ndarray, min_length: float,
) -> list[tuple[float, float]]:
    """Find contiguous True runs in mask that span >= min_length in distance."""
    runs = []
    in_run = False
    start_idx = 0

    for i in range(len(mask)):
        if mask[i] and not in_run:
            start_idx = i
            in_run = True
        elif not mask[i] and in_run:
            d_start = float(distances[start_idx])
            d_end = float(distances[i - 1])
            if d_end - d_start >= min_length:
                runs.append((d_start, d_end))
            in_run = False

    if in_run:
        d_start = float(distances[start_idx])
        d_end = float(distances[-1])
        if d_end - d_start >= min_length:
            runs.append((d_start, d_end))

    return runs


def run_traffic_detection(
    resampled_laps: dict[int, "pd.DataFrame"],
    corner_list: "list[dict] | None" = None,
) -> TrafficResult:
    """Run traffic detection across all resampled laps.

    Parameters
    ----------
    resampled_laps : dict mapping lap_number → resampled DataFrame
    corner_list : optional list of corner dicts with s_start keys
                  (from corner_detection)

    Returns
    -------
    TrafficResult with per-lap scores and traffic events.
    """
    if not resampled_laps:
        return TrafficResult(straights=[], events=[], per_lap_score={}, n_laps_affected=0)

    # Use first lap for straight detection (all laps share same track)
    first_lap = resampled_laps[min(resampled_laps.keys())]
    straights = detect_straights(first_lap)

    if not straights:
        logger.info("run_traffic_detection: no straights found — skipping.")
        per_lap = {k: 0.0 for k in resampled_laps}
        return TrafficResult(
            straights=[], events=[], per_lap_score=per_lap, n_laps_affected=0,
        )

    # Corner entries for proximity check
    corner_entries: list[float] = []
    if corner_list:
        corner_entries = [c.get("s_start", 0.0) for c in corner_list]

    # Detect traffic on each straight
    all_events: list[TrafficEvent] = []
    for straight in straights:
        events = _flag_straight_traffic(resampled_laps, straight, corner_entries)
        all_events.extend(events)

    # Compute per-lap traffic_score
    total_straight_dist = sum(s["length_m"] for s in straights)
    per_lap_score: dict[int, float] = {}

    for lap_num in resampled_laps:
        lap_events = [e for e in all_events if e.lap_number == lap_num]
        if not lap_events or total_straight_dist <= 0:
            per_lap_score[lap_num] = 0.0
            continue
        flagged_dist = sum(e.s_end - e.s_start for e in lap_events)
        per_lap_score[lap_num] = round(
            min(1.0, flagged_dist / total_straight_dist), 3,
        )

    n_affected = sum(1 for s in per_lap_score.values() if s > 0)

    logger.info(
        "Traffic detection: %d straights, %d events, %d/%d laps affected.",
        len(straights), len(all_events), n_affected, len(resampled_laps),
    )

    return TrafficResult(
        straights=straights,
        events=all_events,
        per_lap_score=per_lap_score,
        n_laps_affected=n_affected,
    )
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_traffic_detection.py -v`
Expected: 7 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/traffic_detection.py telemetry_tool/tests/test_traffic_detection.py
git commit -m "feat(traffic): add cross-lap envelope traffic flagging and per-lap traffic_score"
```

---

### Task 4: LapExclusion + LapInclusionPolicy dataclasses

**Files:**
- Create: `telemetry_tool/lap_inclusion.py`
- Create: `telemetry_tool/tests/test_lap_inclusion.py`

**Step 1: Write the failing tests**

In `telemetry_tool/tests/test_lap_inclusion.py`:

```python
"""Tests for lap inclusion policy."""
import numpy as np
import pandas as pd
import pytest


def test_lap_exclusion_fields():
    """LapExclusion has required fields."""
    from lap_inclusion import LapExclusion

    exc = LapExclusion(
        lap_number=1,
        reasons=["outlap"],
        detail={"lap_time_ratio": 2.1},
    )
    assert exc.lap_number == 1
    assert "outlap" in exc.reasons
    d = exc.to_dict()
    assert "reasons" in d


def test_lap_inclusion_policy_fields():
    """LapInclusionPolicy has learning_laps, display_laps, traffic_masks."""
    from lap_inclusion import LapInclusionPolicy

    policy = LapInclusionPolicy(
        learning_laps=[2, 3, 4],
        display_laps=[1, 2, 3, 4, 5],
        exclusions=[],
        traffic_masks={3: [(100.0, 150.0)]},
    )
    assert 2 in policy.learning_laps
    assert 1 in policy.display_laps
    assert 1 not in policy.learning_laps
    d = policy.to_dict()
    assert "learning_laps" in d
    assert "traffic_masks" in d


def test_policy_label_method():
    """LapInclusionPolicy.label() returns correct label per lap."""
    from lap_inclusion import LapInclusionPolicy, LapExclusion

    policy = LapInclusionPolicy(
        learning_laps=[2, 3, 4],
        display_laps=[1, 2, 3, 4, 5],
        exclusions=[
            LapExclusion(1, ["outlap"], {}),
            LapExclusion(5, ["traffic"], {"traffic_score": 0.6}),
        ],
        traffic_masks={3: [(100.0, 150.0)]},
    )
    assert policy.label(2) == "clean"
    assert policy.label(1) == "outlap"
    assert policy.label(5) == "traffic"
    assert policy.label(3) == "clean"  # masked but still learning
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_lap_inclusion.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

In `telemetry_tool/lap_inclusion.py`:

```python
"""
lap_inclusion.py
----------------
Lap inclusion policy: learning set vs display set.

Splits laps into two sets:
- learning_laps: clean laps used for envelope, mu(s), calibration
- display_laps: all laps shown in report/replay

Each excluded lap carries queryable exclusion reasons.
Traffic-affected laps may be partially included via segment masks.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict, field

logger = logging.getLogger(__name__)


@dataclass
class LapExclusion:
    """Why a lap was excluded from the learning set."""
    lap_number: int
    reasons: list[str]       # e.g. ["outlap", "traffic"]
    detail: dict             # reason-specific metadata

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LapInclusionPolicy:
    """Lap inclusion policy for learning vs display."""
    learning_laps: list[int]
    display_laps: list[int]
    exclusions: list[LapExclusion]
    traffic_masks: dict[int, list[tuple[float, float]]]

    def to_dict(self) -> dict:
        return {
            "learning_laps": list(self.learning_laps),
            "display_laps": list(self.display_laps),
            "exclusions": [e.to_dict() for e in self.exclusions],
            "traffic_masks": {
                str(k): [list(r) for r in v]
                for k, v in self.traffic_masks.items()
            },
        }

    def label(self, lap_number: int) -> str:
        """Return display label for a lap.

        Returns one of: "clean", "outlap", "inlap", "traffic", "degraded",
        "abnormal_length", "low_coverage", "excluded".
        """
        if lap_number in self.learning_laps:
            return "clean"
        for exc in self.exclusions:
            if exc.lap_number == lap_number:
                # Return first reason as label
                return exc.reasons[0] if exc.reasons else "excluded"
        return "excluded"
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_lap_inclusion.py -v`
Expected: 3 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/lap_inclusion.py telemetry_tool/tests/test_lap_inclusion.py
git commit -m "feat(inclusion): add LapExclusion and LapInclusionPolicy dataclasses"
```

---

### Task 5: build_inclusion_policy() with all exclusion criteria

**Files:**
- Modify: `telemetry_tool/lap_inclusion.py` (append)
- Modify: `telemetry_tool/tests/test_lap_inclusion.py` (append)

**Step 1: Write the failing tests**

Append to `telemetry_tool/tests/test_lap_inclusion.py`:

```python


def _make_simple_laps(n_laps=5, n_points=200, speed=20.0):
    """Create simple identical resampled laps."""
    laps = {}
    for i in range(1, n_laps + 1):
        laps[i] = pd.DataFrame({
            "Distance (m)": np.linspace(0, 500, n_points),
            "Speed (m/s)": np.full(n_points, speed),
            "accel_long_mps2": np.zeros(n_points),
        })
    return laps


def test_outlap_excluded():
    """First lap with 2× median time → excluded as outlap."""
    from lap_inclusion import build_inclusion_policy
    from traffic_detection import TrafficResult

    laps = _make_simple_laps(5)
    # Lap times: lap 1 is 2.5× the median (outlap)
    lap_times = [150.0, 60.0, 61.0, 62.0, 63.0]
    traffic = TrafficResult([], [], {k: 0.0 for k in range(1, 6)}, 0)

    policy = build_inclusion_policy(laps, lap_times, traffic)
    assert 1 not in policy.learning_laps
    assert 1 in policy.display_laps
    assert policy.label(1) == "outlap"


def test_high_traffic_excluded():
    """Lap with traffic_score > 0.5 → fully excluded from learning."""
    from lap_inclusion import build_inclusion_policy
    from traffic_detection import TrafficResult

    laps = _make_simple_laps(5)
    lap_times = [60.0, 61.0, 62.0, 63.0, 64.0]
    traffic = TrafficResult(
        straights=[{"s_start": 0, "s_end": 200, "length_m": 200}],
        events=[],
        per_lap_score={1: 0.0, 2: 0.0, 3: 0.6, 4: 0.0, 5: 0.0},
        n_laps_affected=1,
    )

    policy = build_inclusion_policy(laps, lap_times, traffic)
    assert 3 not in policy.learning_laps
    assert policy.label(3) == "traffic"


def test_low_traffic_masked():
    """Lap with traffic_score 0.2 → in learning set but has traffic mask."""
    from lap_inclusion import build_inclusion_policy
    from traffic_detection import TrafficResult, TrafficEvent

    laps = _make_simple_laps(5)
    lap_times = [60.0, 61.0, 62.0, 63.0, 64.0]
    traffic = TrafficResult(
        straights=[{"s_start": 0, "s_end": 200, "length_m": 200}],
        events=[TrafficEvent(2, 50.0, 100.0, 8.0, -1.0)],
        per_lap_score={1: 0.0, 2: 0.2, 3: 0.0, 4: 0.0, 5: 0.0},
        n_laps_affected=1,
    )

    policy = build_inclusion_policy(laps, lap_times, traffic)
    assert 2 in policy.learning_laps  # still in learning set
    assert 2 in policy.traffic_masks  # but has masks
    assert len(policy.traffic_masks[2]) == 1
    assert policy.traffic_masks[2][0] == (50.0, 100.0)


def test_low_channel_coverage_excluded():
    """Lap with >20% NaN speed → excluded for low coverage."""
    from lap_inclusion import build_inclusion_policy
    from traffic_detection import TrafficResult

    laps = _make_simple_laps(5)
    # Lap 4: 50% NaN speed
    bad_lap = laps[4].copy()
    bad_lap.loc[:99, "Speed (m/s)"] = np.nan
    laps[4] = bad_lap

    lap_times = [60.0, 61.0, 62.0, 63.0, 64.0]
    traffic = TrafficResult([], [], {k: 0.0 for k in range(1, 6)}, 0)

    policy = build_inclusion_policy(laps, lap_times, traffic)
    assert 4 not in policy.learning_laps
    assert policy.label(4) == "low_coverage"
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_lap_inclusion.py::test_outlap_excluded -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Append to `telemetry_tool/lap_inclusion.py`:

```python
import math
import numpy as np


_OUTLAP_TIME_RATIO = 2.0          # > 2× median → outlap/inlap
_TRAFFIC_FULL_EXCLUDE = 0.5       # traffic_score above this → fully excluded
_NAN_COVERAGE_THRESHOLD = 0.20    # > 20% NaN in speed/accel → excluded
_LAP_LENGTH_ZSCORE = 3.0          # z-score for abnormal lap length


def build_inclusion_policy(
    resampled_laps: dict[int, "pd.DataFrame"],
    lap_times: list[float],
    traffic_result: "TrafficResult",
    *,
    distance_quality: "dict | None" = None,
) -> LapInclusionPolicy:
    """Build lap inclusion policy from traffic detection and quality data.

    Parameters
    ----------
    resampled_laps : lap_number → resampled DataFrame
    lap_times : list of lap times in seconds (aligned with sorted lap keys)
    traffic_result : output from run_traffic_detection()
    distance_quality : optional distance quality dict from summary

    Returns
    -------
    LapInclusionPolicy with learning/display sets and traffic masks.
    """
    sorted_keys = sorted(resampled_laps.keys())
    exclusions: list[LapExclusion] = []
    excluded_set: set[int] = set()
    traffic_masks: dict[int, list[tuple[float, float]]] = {}

    # Align lap_times with sorted keys
    key_to_time = {}
    for i, k in enumerate(sorted_keys):
        if i < len(lap_times) and math.isfinite(lap_times[i]):
            key_to_time[k] = lap_times[i]

    finite_times = [t for t in key_to_time.values() if math.isfinite(t)]
    median_time = float(np.median(finite_times)) if finite_times else 0.0

    # ── Rule 1: Outlap / Inlap ──
    if median_time > 0:
        for k in sorted_keys:
            t = key_to_time.get(k)
            if t is not None and t > median_time * _OUTLAP_TIME_RATIO:
                # First lap = outlap, last = inlap, otherwise just slow
                if k == sorted_keys[0]:
                    reason = "outlap"
                elif k == sorted_keys[-1]:
                    reason = "inlap"
                else:
                    reason = "outlap"  # generic slow lap
                exclusions.append(LapExclusion(k, [reason], {
                    "lap_time": round(t, 2),
                    "median_time": round(median_time, 2),
                    "ratio": round(t / median_time, 2),
                }))
                excluded_set.add(k)

    # ── Rule 2: Traffic ──
    for k in sorted_keys:
        if k in excluded_set:
            continue
        score = traffic_result.per_lap_score.get(k, 0.0)
        if score > _TRAFFIC_FULL_EXCLUDE:
            exclusions.append(LapExclusion(k, ["traffic"], {
                "traffic_score": round(score, 3),
            }))
            excluded_set.add(k)
        elif score > 0:
            # Partial: include in learning but mask affected segments
            lap_events = [e for e in traffic_result.events if e.lap_number == k]
            if lap_events:
                traffic_masks[k] = [(e.s_start, e.s_end) for e in lap_events]

    # ── Rule 3: Distance quality ──
    if distance_quality and isinstance(distance_quality, dict):
        degraded = distance_quality.get("laps_degraded", [])
        metrics = distance_quality.get("metrics", [])
        for lap_num in degraded:
            if lap_num not in excluded_set:
                exclusions.append(LapExclusion(lap_num, ["degraded"], {}))
                excluded_set.add(lap_num)
        # Abnormal length
        for m in metrics:
            ln = m.get("lap_number")
            zscore = m.get("lap_length_zscore", 0.0)
            if ln and abs(zscore) > _LAP_LENGTH_ZSCORE and ln not in excluded_set:
                exclusions.append(LapExclusion(ln, ["abnormal_length"], {
                    "lap_length_zscore": round(zscore, 2),
                }))
                excluded_set.add(ln)

    # ── Rule 4: Low channel coverage ──
    for k in sorted_keys:
        if k in excluded_set:
            continue
        df = resampled_laps[k]
        if df is None or len(df) == 0:
            exclusions.append(LapExclusion(k, ["low_coverage"], {"reason": "empty"}))
            excluded_set.add(k)
            continue

        speed_nan_frac = 0.0
        if "Speed (m/s)" in df.columns:
            speed_nan_frac = float(df["Speed (m/s)"].isna().mean())
        elif _COL_SPEED_ALT := "speed_mps":
            pass  # column might not exist

        accel_nan_frac = 0.0
        if "accel_long_mps2" in df.columns:
            accel_nan_frac = float(df["accel_long_mps2"].isna().mean())

        max_nan = max(speed_nan_frac, accel_nan_frac)
        if max_nan > _NAN_COVERAGE_THRESHOLD:
            exclusions.append(LapExclusion(k, ["low_coverage"], {
                "speed_nan_pct": round(speed_nan_frac * 100, 1),
                "accel_nan_pct": round(accel_nan_frac * 100, 1),
            }))
            excluded_set.add(k)

    # Build sets
    learning_laps = [k for k in sorted_keys if k not in excluded_set]
    display_laps = list(sorted_keys)

    logger.info(
        "Lap inclusion: %d learning, %d display, %d excluded, %d masked.",
        len(learning_laps), len(display_laps),
        len(exclusions), len(traffic_masks),
    )

    return LapInclusionPolicy(
        learning_laps=learning_laps,
        display_laps=display_laps,
        exclusions=exclusions,
        traffic_masks=traffic_masks,
    )
```

Note: The walrus operator usage `_COL_SPEED_ALT :=` above is a placeholder — remove it. Replace that block with a simpler check. Here's the corrected version of the speed NaN check:

```python
        speed_nan_frac = 0.0
        if "Speed (m/s)" in df.columns:
            speed_nan_frac = float(df["Speed (m/s)"].isna().mean())
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_lap_inclusion.py -v`
Expected: 7 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/lap_inclusion.py telemetry_tool/tests/test_lap_inclusion.py
git commit -m "feat(inclusion): add build_inclusion_policy() with outlap/traffic/distance/coverage rules"
```

---

### Task 6: Segment masking in theoretical_engine

**Files:**
- Modify: `telemetry_tool/theoretical_engine.py` (~line 408)
- Modify: `telemetry_tool/tests/test_lap_inclusion.py` (append)

**Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_lap_inclusion.py`:

```python


def test_envelope_ignores_masked_segments():
    """Speed matrix samples within masked ranges are NaN'd before percentile."""
    from theoretical_engine import compute_speed_percentile_envelope

    n = 200
    base_speed = 25.0

    # 5 identical laps
    laps = []
    for i in range(5):
        laps.append(pd.DataFrame({
            "Distance (m)": np.linspace(0, 500, n),
            "Speed (m/s)": np.full(n, base_speed),
        }))

    # Lap 2: traffic dip at 100-200m (speed drops to 15)
    laps[2] = laps[2].copy()
    dist = laps[2]["Distance (m)"].values
    mask = (dist >= 100) & (dist <= 200)
    laps[2].loc[mask, "Speed (m/s)"] = 15.0

    # Without mask: envelope at 100-200m will be lower
    env_no_mask = compute_speed_percentile_envelope(laps, percentile=90.0)

    # With mask: NaN out lap 2's traffic zone
    masks = {2: [(100.0, 200.0)]}
    env_masked = compute_speed_percentile_envelope(laps, percentile=90.0, masks=masks)

    # Masked envelope should be >= unmasked at traffic zone
    d = env_masked["distance_m"].values
    traffic_zone = (d >= 100) & (d <= 200)
    assert np.all(
        env_masked.loc[traffic_zone, "v_env_mps"].values
        >= env_no_mask.loc[traffic_zone, "v_env_mps"].values - 0.5
    ), "Masked envelope should not be dragged down by traffic"
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_lap_inclusion.py::test_envelope_ignores_masked_segments -v`
Expected: FAIL (masks parameter not accepted)

**Step 3: Modify theoretical_engine.py**

Read `telemetry_tool/theoretical_engine.py` lines 408-414. Add `masks` parameter to the function signature:

Change:
```python
def compute_speed_percentile_envelope(
    laps:       list[pd.DataFrame],
    percentile: float = 98.0,
    *,
    n_bins:     int   = 0,
    smooth_window: int = 5,
) -> pd.DataFrame:
```

To:
```python
def compute_speed_percentile_envelope(
    laps:       list[pd.DataFrame],
    percentile: float = 98.0,
    *,
    n_bins:     int   = 0,
    smooth_window: int = 5,
    masks: "dict[int, list[tuple[float, float]]] | None" = None,
) -> pd.DataFrame:
```

Then, after `speed_matrix` is populated (after line 543, `speed_matrix[i] = np.interp(...)`) and before the per-bin percentile (line 547), insert:

```python
        # Apply traffic masks: NaN out masked distance ranges
        if masks is not None and i in masks:
            for m_start, m_end in masks[i]:
                mask_bins = (grid >= m_start) & (grid <= m_end)
                speed_matrix[i, mask_bins] = np.nan
```

Also change the percentile computation (line 547-549) from `_safe_percentile` to use `np.nanpercentile` to handle NaN:

Check what `_safe_percentile` does — if it already handles NaN, no change needed. If not, ensure it uses `np.nanpercentile`.

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_lap_inclusion.py::test_envelope_ignores_masked_segments -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/theoretical_engine.py telemetry_tool/tests/test_lap_inclusion.py
git commit -m "feat(theoretical): add masks parameter to compute_speed_percentile_envelope()"
```

---

### Task 7: Pipeline stage 9.5 — traffic detection + lap inclusion

**Files:**
- Modify: `telemetry_tool/pipeline.py` (between stages 9f and 10, around line 1938)
- Create: `telemetry_tool/tests/test_traffic_pipeline.py`

**Step 1: Write the failing test**

In `telemetry_tool/tests/test_traffic_pipeline.py`:

```python
"""Integration tests for traffic detection in the pipeline."""
import numpy as np
import pandas as pd
import pytest


def _make_multi_lap_csv(tmp_path, n_laps=5, inject_traffic_lap=None):
    """Create a CSV with multiple laps, optionally injecting traffic on one."""
    rng = np.random.default_rng(42)
    frames = []
    n_per_lap = 200
    lap_length = 500.0

    for lap in range(1, n_laps + 1):
        t_start = (lap - 1) * 30.0
        t = np.linspace(t_start, t_start + 25.0, n_per_lap)
        dist = np.linspace(0, lap_length, n_per_lap)
        speed = np.full(n_per_lap, 20.0) + rng.normal(0, 0.3, n_per_lap)
        lat = np.linspace(45.0, 45.002, n_per_lap) + rng.normal(0, 1e-5, n_per_lap)
        lon = np.linspace(9.0, 9.002, n_per_lap) + rng.normal(0, 1e-5, n_per_lap)

        # Inject traffic on specified lap
        if lap == inject_traffic_lap:
            traffic_mask = (dist >= 100) & (dist <= 250)
            speed[traffic_mask] = speed[traffic_mask] * 0.6
            # Don't set a_long here — it will be computed by derived_channels

        df = pd.DataFrame({
            "Lap #": np.full(n_per_lap, lap),
            "Time (s)": t,
            "Distance (m)": dist + (lap - 1) * lap_length,
            "Speed (m/s)": speed,
            "Latitude (deg)": lat,
            "Longitude (deg)": lon,
            "Bearing (deg)": np.full(n_per_lap, 90.0) + rng.normal(0, 1, n_per_lap),
            "Longitudinal acceleration (G) *calc": rng.normal(0, 0.02, n_per_lap),
            "Lateral acceleration (G) *calc": rng.normal(0, 0.02, n_per_lap),
        })
        frames.append(df)

    full_df = pd.concat(frames, ignore_index=True)
    csv_path = tmp_path / "traffic_test.csv"
    full_df.to_csv(csv_path, index=False)
    return csv_path


def test_pipeline_has_traffic_and_inclusion(tmp_path):
    """Pipeline summary contains traffic and lap_inclusion keys."""
    import pipeline

    csv_path = _make_multi_lap_csv(tmp_path, n_laps=5)
    summary = pipeline.run_full_analysis(str(csv_path), {})

    assert "traffic" in summary
    assert "lap_inclusion" in summary

    traffic = summary["traffic"]
    assert "per_lap_score" in traffic
    assert "n_laps_affected" in traffic

    inclusion = summary["lap_inclusion"]
    assert "learning_laps" in inclusion
    assert "display_laps" in inclusion
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_traffic_pipeline.py -v`
Expected: FAIL (no traffic/lap_inclusion keys in summary)

**Step 3: Modify pipeline.py**

Read `telemetry_tool/pipeline.py` around line 1938 (after stage 9f progressive physics). Insert stage 9.5 between stage 9f and stage 10:

```python
    # ====================================================================
    # STEP 9.5 -- Traffic detection + Lap inclusion policy
    # ====================================================================

    _td_mod = _import("traffic_detection")
    _li_mod = _import("lap_inclusion")

    def _traffic_and_inclusion():
        _traffic_result = None
        _inclusion_policy = None

        if _td_mod is not None:
            _traffic_result = _td_mod.run_traffic_detection(
                resampled_laps, summary.get("corners"),
            )

        if _li_mod is not None and _traffic_result is not None:
            from traffic_detection import TrafficResult
            _inclusion_policy = _li_mod.build_inclusion_policy(
                resampled_laps,
                lap_times,
                _traffic_result,
                distance_quality=summary.get("distance_quality"),
            )
        elif _li_mod is not None:
            from traffic_detection import TrafficResult
            empty_traffic = TrafficResult([], [], {k: 0.0 for k in resampled_laps}, 0)
            _inclusion_policy = _li_mod.build_inclusion_policy(
                resampled_laps, lap_times, empty_traffic,
                distance_quality=summary.get("distance_quality"),
            )

        return _traffic_result, _inclusion_policy

    _traffic_incl, err = _safe_step("09g_traffic_inclusion", _traffic_and_inclusion)
    _record("09g_traffic_inclusion", _traffic_incl, err)
    _fire_progress("09g_traffic_inclusion")

    _traffic_result = None
    _inclusion_policy = None
    if _traffic_incl is not None:
        _traffic_result, _inclusion_policy = _traffic_incl
    if _traffic_result is not None:
        summary["traffic"] = _traffic_result.to_dict()
    else:
        summary["traffic"] = None
    if _inclusion_policy is not None:
        summary["lap_inclusion"] = _inclusion_policy.to_dict()
    else:
        summary["lap_inclusion"] = None
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_traffic_pipeline.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/pipeline.py telemetry_tool/tests/test_traffic_pipeline.py
git commit -m "feat(traffic): integrate traffic detection + lap inclusion as pipeline stage 9.5"
```

---

### Task 8: Filter laps at stage 10 (theoretical) using inclusion policy

**Files:**
- Modify: `telemetry_tool/pipeline.py` (~line 2080-2145, the theoretical envelope section)

**Step 1: Read current stage 10 code**

Read `telemetry_tool/pipeline.py` lines 2078-2145 to find the exact code that builds `laps_for_theo`.

**Step 2: Modify stage 10**

In the existing code around line 2081-2108 where `laps_for_theo` is built, add inclusion policy filtering. Find this block:

```python
        if theo_mod is not None:
            sorted_keys = sorted(resampled_laps.keys())
            ...
            if best_n_lap_indices:
                laps_for_theo = ...
            else:
                laps_for_theo = laps_list
                keys_for_theo = sorted_keys
```

After `keys_for_theo` is set (around line 2108), add:

```python
            # Filter by inclusion policy (if available)
            if _inclusion_policy is not None and hasattr(_inclusion_policy, 'learning_laps'):
                _learning_set = set(_inclusion_policy.learning_laps)
                _filtered = [
                    (lap, key) for lap, key in zip(laps_for_theo, keys_for_theo)
                    if key in _learning_set
                ]
                if len(_filtered) >= 3:
                    laps_for_theo = [x[0] for x in _filtered]
                    keys_for_theo = [x[1] for x in _filtered]
                    logger.info(
                        "Theoretical envelope: filtered to %d learning laps "
                        "(excluded %d by inclusion policy).",
                        len(laps_for_theo),
                        len(sorted_keys) - len(laps_for_theo),
                    )
                else:
                    logger.warning(
                        "Inclusion policy leaves only %d laps — using all %d.",
                        len(_filtered), len(laps_for_theo),
                    )
```

Then where `theo_mod.build_theoretical_lap()` or `theo_mod.compute_speed_percentile_envelope()` is called, pass `masks=_inclusion_policy.traffic_masks` if available. Find the call at line ~2135:

```python
                return theo_mod.build_theoretical_lap(
                    laps_for_theo, n_points=n_resample_points,
                    speed_percentile=speed_pct,
                    accel_percentile=accel_pct,
                )
```

This calls `build_theoretical_lap` which internally calls `compute_speed_percentile_envelope`. The masks need to be passed down. The simplest approach: if `build_theoretical_lap` doesn't accept masks, pass them to `compute_speed_percentile_envelope` directly by modifying the `_theoretical()` function to call the envelope function first with masks, then pass the result.

However, to keep changes minimal, add `masks` as a kwarg to `build_theoretical_lap` that it passes through to `compute_speed_percentile_envelope`. Read `theoretical_engine.py` to find the `build_theoretical_lap` signature and modify it.

**Step 3: Run existing tests to verify no regression**

Run: `pytest telemetry_tool/tests/test_fusion_pipeline.py telemetry_tool/tests/test_traffic_pipeline.py -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add telemetry_tool/pipeline.py telemetry_tool/theoretical_engine.py
git commit -m "feat(theoretical): filter laps by inclusion policy + pass traffic masks to envelope"
```

---

### Task 9: Reporting — traffic badges + learning/display summary

**Files:**
- Modify: `telemetry_tool/reporting_html.py`

**Step 1: Read current report structure**

Read `telemetry_tool/reporting_html.py` to find the `generate_report()` signature and where the distance_quality section was added (from previous work). The traffic section goes in the same area.

**Step 2: Add traffic section builder**

Add a `_build_traffic_html()` helper function similar to `_build_distance_quality_html()`:

```python
def _build_traffic_html(traffic: dict | None, lap_inclusion: dict | None) -> str:
    """Build HTML for traffic detection and lap inclusion summary."""
    if traffic is None and lap_inclusion is None:
        return ""

    parts = ['<div class="section traffic-section">',
             '<h3>Traffic Detection & Lap Inclusion</h3>']

    if lap_inclusion:
        n_learn = len(lap_inclusion.get("learning_laps", []))
        n_display = len(lap_inclusion.get("display_laps", []))
        n_excluded = len(lap_inclusion.get("exclusions", []))
        parts.append(
            f'<p><strong>{n_learn}</strong> laps used for learning, '
            f'<strong>{n_display}</strong> displayed, '
            f'<strong>{n_excluded}</strong> excluded.</p>'
        )

        exclusions = lap_inclusion.get("exclusions", [])
        if exclusions:
            parts.append('<table class="metrics-table"><tr>'
                         '<th>Lap</th><th>Reason</th><th>Label</th></tr>')
            for exc in exclusions:
                reasons = ", ".join(exc.get("reasons", []))
                parts.append(
                    f'<tr><td>{exc.get("lap_number", "?")}</td>'
                    f'<td>{reasons}</td>'
                    f'<td><span class="badge badge-warning">{reasons}</span></td></tr>'
                )
            parts.append('</table>')

    if traffic:
        n_affected = traffic.get("n_laps_affected", 0)
        if n_affected > 0:
            parts.append(f'<p>Traffic detected on <strong>{n_affected}</strong> lap(s).</p>')

    parts.append('</div>')
    return "\n".join(parts)
```

Add `traffic` and `lap_inclusion` parameters to `generate_report()` and insert the section.

**Step 3: Run report tests**

Run: `pytest telemetry_tool/tests/test_traffic_pipeline.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add telemetry_tool/reporting_html.py
git commit -m "feat(report): add traffic detection badges and lap inclusion summary"
```

---

### Task 10: Integration test — theoretical never slower due to traffic

**Files:**
- Modify: `telemetry_tool/tests/test_traffic_pipeline.py` (append)

**Step 1: Write the test**

Append to `telemetry_tool/tests/test_traffic_pipeline.py`:

```python


def test_theoretical_not_slower_with_traffic(tmp_path):
    """Envelope from learning set >= envelope from all laps at every point.

    When traffic laps are excluded, the theoretical should never be slower
    than when they're included.
    """
    import theoretical_engine

    rng = np.random.default_rng(42)
    n = 200
    base_speed = 25.0

    # 5 clean laps
    laps = []
    for i in range(5):
        laps.append(pd.DataFrame({
            "Distance (m)": np.linspace(0, 500, n),
            "Speed (m/s)": np.full(n, base_speed) + rng.normal(0, 0.3, n),
        }))

    # Add 2 traffic-contaminated laps (speed drops on 100-300m)
    for i in range(2):
        df = pd.DataFrame({
            "Distance (m)": np.linspace(0, 500, n),
            "Speed (m/s)": np.full(n, base_speed) + rng.normal(0, 0.3, n),
        })
        dist = df["Distance (m)"].values
        mask = (dist >= 100) & (dist <= 300)
        df.loc[mask, "Speed (m/s)"] = df.loc[mask, "Speed (m/s)"] * 0.6
        laps.append(df)

    # Envelope with all laps (contaminated)
    env_all = theoretical_engine.compute_speed_percentile_envelope(
        laps, percentile=90.0,
    )

    # Envelope with only clean laps (first 5)
    env_clean = theoretical_engine.compute_speed_percentile_envelope(
        laps[:5], percentile=90.0,
    )

    # Clean envelope should be >= contaminated at every point
    # (within smoothing tolerance)
    diff = env_clean["v_env_mps"].values - env_all["v_env_mps"].values
    assert np.all(diff >= -0.5), (
        f"Clean envelope should not be slower than contaminated. "
        f"Min diff: {diff.min():.2f} m/s"
    )
```

**Step 2: Run test**

Run: `pytest telemetry_tool/tests/test_traffic_pipeline.py -v`
Expected: All PASS

**Step 3: Commit**

```bash
git add telemetry_tool/tests/test_traffic_pipeline.py
git commit -m "test(traffic): add integration test verifying theoretical never slower due to traffic"
```

---

## Summary

| Task | What | Tests |
|------|------|-------|
| 1 | TrafficEvent + TrafficResult dataclasses | 3 |
| 2 | Straight detection from curvature | 2 |
| 3 | Cross-lap traffic flagging + traffic_score | 2 |
| 4 | LapExclusion + LapInclusionPolicy dataclasses | 3 |
| 5 | build_inclusion_policy() with all rules | 4 |
| 6 | Segment masking in theoretical_engine | 1 |
| 7 | Pipeline stage 9.5 integration | 1 |
| 8 | Stage 10 learning-set filtering | 0 (covered by existing) |
| 9 | Reporting badges + summary | 0 (covered by integration) |
| 10 | Theoretical never slower test | 1 |
| **Total** | | **17** |
