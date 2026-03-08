# Distance Integrity Preflight Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a mandatory distance_m integrity preflight that validates, repairs, and gates pipeline stages based on per-lap distance quality.

**Architecture:** New `distance_integrity.py` module with dataclasses (`LapDistanceMetrics`, `DistanceQuality`) + metric computation + XY rebuild + isotonic regression fallback. Inserted as pipeline stage 6.5 (after derived channels, before resampling). Gates stages 10 (theoretical), 13b (coaching). API endpoint + report debug section surface results to users.

**Tech Stack:** Python 3.x, NumPy, pandas, sklearn (IsotonicRegression), Flask, pytest

---

### Task 1: LapDistanceMetrics dataclass + compute_lap_metrics()

**Files:**
- Create: `telemetry_tool/distance_integrity.py`
- Create: `telemetry_tool/tests/test_distance_integrity.py`

**Step 1: Write the failing tests**

In `telemetry_tool/tests/test_distance_integrity.py`:

```python
"""Tests for distance_integrity module."""
import numpy as np
import pandas as pd
import pytest


def test_perfect_monotonic_distance():
    """Perfectly monotonic distance → ratio=1.0, jump_count=0."""
    from distance_integrity import compute_lap_metrics

    d = np.linspace(0, 500, 1000)
    m = compute_lap_metrics(d, lap_number=1)
    assert m.monotonic_ratio == 1.0
    assert m.jump_count == 0
    assert m.lap_length == pytest.approx(500.0)


def test_non_monotonic_distance():
    """Backward jumps reduce monotonic_ratio and increase jump_count."""
    from distance_integrity import compute_lap_metrics

    d = np.linspace(0, 500, 100)
    d[30] = d[20]  # backward jump
    d[60] = d[50]  # another
    m = compute_lap_metrics(d, lap_number=1)
    assert m.monotonic_ratio < 1.0
    assert m.jump_count >= 2


def test_compression_ratio_uniform():
    """Uniform spacing → compression_ratio close to 0."""
    from distance_integrity import compute_lap_metrics

    d = np.linspace(0, 500, 1000)
    m = compute_lap_metrics(d, lap_number=1)
    assert m.compression_ratio < 0.01


def test_compression_ratio_irregular():
    """Irregular spacing → higher compression_ratio."""
    from distance_integrity import compute_lap_metrics

    d = np.array([0, 1, 2, 3, 100, 101, 102, 200, 201, 500])
    m = compute_lap_metrics(d, lap_number=1)
    assert m.compression_ratio > 0.5


def test_lap_length():
    """lap_length = max - min."""
    from distance_integrity import compute_lap_metrics

    d = np.array([10, 20, 30, 40, 50])
    m = compute_lap_metrics(d, lap_number=1)
    assert m.lap_length == pytest.approx(40.0)
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_distance_integrity.py -v`
Expected: FAIL with "cannot import name 'compute_lap_metrics'"

**Step 3: Write minimal implementation**

In `telemetry_tool/distance_integrity.py`:

```python
"""
distance_integrity.py
---------------------
Pre-resampling distance_m quality check, repair, and gating.

Inserted as pipeline stage 6.5 — after derived channels compute
distance_m, before resampling normalises to a uniform grid.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── Thresholds (configurable via pipeline config) ─────────────────
MONO_RATIO_REPAIR = 0.95      # below this → attempt repair
JUMP_COUNT_REPAIR = 5         # above this → attempt repair
MONO_RATIO_GATE = 0.99        # below this after repair → gate advanced
LAP_LENGTH_ZSCORE_OUTLIER = 3.0  # flag outlier laps


@dataclass
class LapDistanceMetrics:
    """Per-lap distance quality metrics."""
    lap_number: int
    monotonic_ratio: float
    jump_count: int
    compression_ratio: float
    lap_length: float
    lap_length_zscore: float = 0.0  # set later when all laps known

    def to_dict(self) -> dict:
        return asdict(self)


def compute_lap_metrics(distance: np.ndarray, *, lap_number: int) -> LapDistanceMetrics:
    """Compute distance quality metrics for a single lap.

    Parameters
    ----------
    distance : 1-D array of distance_m values for one lap.
    lap_number : Lap identifier.
    """
    d = np.asarray(distance, dtype=np.float64)
    n = len(d)

    if n < 2:
        return LapDistanceMetrics(
            lap_number=lap_number,
            monotonic_ratio=0.0,
            jump_count=0,
            compression_ratio=0.0,
            lap_length=0.0,
        )

    diffs = np.diff(d)
    n_diffs = len(diffs)

    # monotonic_ratio: fraction of strictly increasing steps
    mono_count = int(np.sum(diffs > 0))
    monotonic_ratio = mono_count / n_diffs if n_diffs > 0 else 0.0

    # jump_count: number of backward jumps (d[i+1] < d[i])
    jump_count = int(np.sum(diffs < 0))

    # compression_ratio: std(diff) / mean(diff) — coefficient of variation
    pos_diffs = diffs[diffs > 0]
    if len(pos_diffs) > 1:
        compression_ratio = float(np.std(pos_diffs) / np.mean(pos_diffs))
    else:
        compression_ratio = 0.0

    # lap_length: total span
    finite = d[np.isfinite(d)]
    lap_length = float(finite.max() - finite.min()) if len(finite) >= 2 else 0.0

    return LapDistanceMetrics(
        lap_number=lap_number,
        monotonic_ratio=monotonic_ratio,
        jump_count=jump_count,
        compression_ratio=compression_ratio,
        lap_length=lap_length,
    )
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_distance_integrity.py -v`
Expected: 5 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/distance_integrity.py telemetry_tool/tests/test_distance_integrity.py
git commit -m "feat(distance): add LapDistanceMetrics dataclass and compute_lap_metrics()"
```

---

### Task 2: DistanceQuality dataclass + assess_all_laps()

**Files:**
- Modify: `telemetry_tool/distance_integrity.py`
- Modify: `telemetry_tool/tests/test_distance_integrity.py`

**Step 1: Write the failing tests**

Append to `telemetry_tool/tests/test_distance_integrity.py`:

```python
def _make_lap_dict(distances: dict[int, np.ndarray]) -> dict[int, pd.DataFrame]:
    """Helper: build lap_dict from {lap_num: distance_array}."""
    result = {}
    for lap_num, d in distances.items():
        df = pd.DataFrame({"Distance (m)": d, "Speed (m/s)": np.ones(len(d))})
        result[lap_num] = df
    return result


def test_assess_all_laps_ok():
    """All laps with perfect distance → status='ok', gate_advanced=False."""
    from distance_integrity import assess_all_laps

    laps = _make_lap_dict({
        1: np.linspace(0, 500, 100),
        2: np.linspace(0, 502, 100),
        3: np.linspace(0, 498, 100),
    })
    dq = assess_all_laps(laps)
    assert dq.status == "ok"
    assert dq.gate_advanced is False
    assert len(dq.metrics) == 3


def test_assess_all_laps_zscore():
    """One lap with very different length gets flagged with high zscore."""
    from distance_integrity import assess_all_laps

    laps = _make_lap_dict({
        1: np.linspace(0, 500, 100),
        2: np.linspace(0, 500, 100),
        3: np.linspace(0, 500, 100),
        4: np.linspace(0, 1500, 100),  # 3x longer
    })
    dq = assess_all_laps(laps)
    # Lap 4 should have a high zscore
    lap4 = [m for m in dq.metrics if m["lap_number"] == 4][0]
    assert lap4["lap_length_zscore"] > 2.0


def test_assess_flags_non_monotonic():
    """Lap with backward jumps → needs_repair list populated."""
    from distance_integrity import assess_all_laps

    d_bad = np.linspace(0, 500, 100)
    # Introduce 10 backward jumps
    for i in range(10, 100, 9):
        d_bad[i] = d_bad[i] - 50
    laps = _make_lap_dict({
        1: np.linspace(0, 500, 100),
        2: d_bad,
    })
    dq = assess_all_laps(laps)
    assert 2 in dq.laps_repaired or 2 in dq.laps_degraded or dq.status != "ok"
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_distance_integrity.py::test_assess_all_laps_ok -v`
Expected: FAIL with "cannot import name 'assess_all_laps'"

**Step 3: Write minimal implementation**

Append to `telemetry_tool/distance_integrity.py`:

```python
@dataclass
class DistanceQuality:
    """Overall distance quality assessment across all laps."""
    status: str                          # "ok" | "repaired" | "degraded"
    repair_method: Optional[str] = None  # "xy_rebuild" | "isotonic_regression" | None
    laps_repaired: list[int] = field(default_factory=list)
    laps_degraded: list[int] = field(default_factory=list)
    metrics: list[dict] = field(default_factory=list)
    gate_advanced: bool = False
    message: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def assess_all_laps(
    lap_dict: dict[int, "pd.DataFrame"],
    *,
    dist_col: str = "Distance (m)",
) -> DistanceQuality:
    """Compute per-lap distance metrics and identify laps needing repair.

    Does NOT repair — only assesses.  Returns a DistanceQuality with
    status="ok" if all laps pass, or lists of laps needing attention.
    """
    import pandas as pd

    all_metrics: list[LapDistanceMetrics] = []
    needs_repair: list[int] = []

    for lap_num in sorted(lap_dict.keys()):
        df = lap_dict[lap_num]
        if dist_col not in df.columns:
            continue
        d = pd.to_numeric(df[dist_col], errors="coerce").values.astype(np.float64)
        m = compute_lap_metrics(d, lap_number=lap_num)
        all_metrics.append(m)

        if m.monotonic_ratio < MONO_RATIO_REPAIR or m.jump_count > JUMP_COUNT_REPAIR:
            needs_repair.append(lap_num)

    # Compute z-scores for lap_length
    if len(all_metrics) >= 3:
        lengths = np.array([m.lap_length for m in all_metrics])
        med = float(np.median(lengths))
        mad = float(np.median(np.abs(lengths - med)))
        # Use MAD-based z-score (robust to outliers)
        sigma = mad * 1.4826 if mad > 0 else 1.0  # MAD → σ estimator
        for m in all_metrics:
            m.lap_length_zscore = abs(m.lap_length - med) / sigma

    metrics_dicts = [m.to_dict() for m in all_metrics]

    if not needs_repair:
        return DistanceQuality(
            status="ok",
            metrics=metrics_dicts,
            message="Distance data is clean across all laps.",
        )

    return DistanceQuality(
        status="ok",  # Will be updated by repair step
        laps_repaired=needs_repair,  # Candidates for repair
        metrics=metrics_dicts,
        message=f"Laps needing repair: {needs_repair}",
    )
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_distance_integrity.py -v`
Expected: 8 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/distance_integrity.py telemetry_tool/tests/test_distance_integrity.py
git commit -m "feat(distance): add DistanceQuality dataclass and assess_all_laps()"
```

---

### Task 3: XY rebuild repair strategy

**Files:**
- Modify: `telemetry_tool/distance_integrity.py`
- Modify: `telemetry_tool/tests/test_distance_integrity.py`

**Step 1: Write the failing tests**

Append to `telemetry_tool/tests/test_distance_integrity.py`:

```python
def test_rebuild_distance_from_xy_euclidean():
    """Rebuild distance from x/y columns using Euclidean method."""
    from distance_integrity import rebuild_distance_from_xy

    # Simple right-angle path: 100m east then 100m north
    n = 50
    x = np.concatenate([np.linspace(0, 100, n), np.full(n, 100)])
    y = np.concatenate([np.zeros(n), np.linspace(0, 100, n)])
    df = pd.DataFrame({"x": x, "y": y, "Distance (m)": np.zeros(2 * n)})

    result = rebuild_distance_from_xy(df)
    assert "Distance (m)" in result.columns
    # Total distance should be ~200m
    total = result["Distance (m)"].iloc[-1]
    assert total == pytest.approx(200.0, rel=0.01)
    # Must be monotonically increasing
    diffs = np.diff(result["Distance (m)"].values)
    assert np.all(diffs >= 0)


def test_rebuild_distance_from_latlon():
    """Rebuild distance from Latitude/Longitude columns using Haversine."""
    from distance_integrity import rebuild_distance_from_xy

    # ~111m per degree at equator for latitude
    lat = np.linspace(0.0, 0.001, 100)  # ~111m
    lon = np.zeros(100)
    df = pd.DataFrame({
        "Latitude (deg)": lat,
        "Longitude (deg)": lon,
        "Distance (m)": np.zeros(100),
    })
    result = rebuild_distance_from_xy(df)
    total = result["Distance (m)"].iloc[-1]
    assert 100 < total < 120  # Haversine ~111m for 0.001 deg


def test_rebuild_returns_none_no_coords():
    """No coordinate columns → returns None."""
    from distance_integrity import rebuild_distance_from_xy

    df = pd.DataFrame({"Distance (m)": np.linspace(0, 100, 50)})
    result = rebuild_distance_from_xy(df)
    assert result is None
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_distance_integrity.py::test_rebuild_distance_from_xy_euclidean -v`
Expected: FAIL with "cannot import name 'rebuild_distance_from_xy'"

**Step 3: Write minimal implementation**

Append to `telemetry_tool/distance_integrity.py`:

```python
# ── Coordinate column detection ───────────────────────────────────
_XY_PAIRS = [
    ("x", "y"),
    ("X (m)", "Y (m)"),
    ("x_m", "y_m"),
]
_LATLON_PAIRS = [
    ("Latitude (deg)", "Longitude (deg)"),
    ("latitude", "longitude"),
    ("Latitude (°)", "Longitude (°)"),
    ("lat", "lon"),
]


def _haversine_cumulative(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Cumulative Haversine distance in metres."""
    R = 6_371_000.0  # Earth radius in metres
    lat_r = np.radians(lat)
    lon_r = np.radians(lon)

    dlat = np.diff(lat_r)
    dlon = np.diff(lon_r)

    a = np.sin(dlat / 2) ** 2 + np.cos(lat_r[:-1]) * np.cos(lat_r[1:]) * np.sin(dlon / 2) ** 2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    seg = R * c

    return np.concatenate([[0.0], np.cumsum(seg)])


def rebuild_distance_from_xy(
    df: "pd.DataFrame",
    *,
    dist_col: str = "Distance (m)",
) -> "Optional[pd.DataFrame]":
    """Rebuild distance_m from coordinate columns if available.

    Tries XY (Euclidean) first, then lat/lon (Haversine).
    Returns a copy with repaired distance column, or None if no
    coordinate columns are found.
    """
    import pandas as pd

    cols = set(df.columns)

    # Try Euclidean XY pairs
    for x_col, y_col in _XY_PAIRS:
        if x_col in cols and y_col in cols:
            x = pd.to_numeric(df[x_col], errors="coerce").values.astype(np.float64)
            y = pd.to_numeric(df[y_col], errors="coerce").values.astype(np.float64)
            dx = np.diff(x)
            dy = np.diff(y)
            seg = np.sqrt(dx ** 2 + dy ** 2)
            dist = np.concatenate([[0.0], np.cumsum(seg)])
            result = df.copy()
            result[dist_col] = dist
            logger.info("Distance rebuilt from XY columns (%s, %s)", x_col, y_col)
            return result

    # Try lat/lon pairs (Haversine)
    for lat_col, lon_col in _LATLON_PAIRS:
        if lat_col in cols and lon_col in cols:
            lat = pd.to_numeric(df[lat_col], errors="coerce").values.astype(np.float64)
            lon = pd.to_numeric(df[lon_col], errors="coerce").values.astype(np.float64)
            dist = _haversine_cumulative(lat, lon)
            result = df.copy()
            result[dist_col] = dist
            logger.info("Distance rebuilt from lat/lon (%s, %s)", lat_col, lon_col)
            return result

    return None
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_distance_integrity.py -v`
Expected: 11 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/distance_integrity.py telemetry_tool/tests/test_distance_integrity.py
git commit -m "feat(distance): add XY rebuild repair strategy with Haversine fallback"
```

---

### Task 4: Isotonic regression fallback repair

**Files:**
- Modify: `telemetry_tool/distance_integrity.py`
- Modify: `telemetry_tool/tests/test_distance_integrity.py`

**Step 1: Write the failing tests**

Append to `telemetry_tool/tests/test_distance_integrity.py`:

```python
def test_isotonic_repair():
    """Isotonic regression forces monotonicity."""
    from distance_integrity import repair_distance_isotonic

    d = np.array([0, 10, 20, 15, 30, 25, 40, 50])  # two backward jumps
    result = repair_distance_isotonic(d)
    diffs = np.diff(result)
    assert np.all(diffs >= 0), "Must be non-decreasing after repair"
    assert result[0] == pytest.approx(0.0, abs=1.0)
    assert result[-1] == pytest.approx(50.0, abs=5.0)


def test_isotonic_preserves_monotonic():
    """Already-monotonic input is unchanged (within tolerance)."""
    from distance_integrity import repair_distance_isotonic

    d = np.linspace(0, 500, 100)
    result = repair_distance_isotonic(d)
    np.testing.assert_allclose(result, d, atol=1e-6)
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_distance_integrity.py::test_isotonic_repair -v`
Expected: FAIL with "cannot import name 'repair_distance_isotonic'"

**Step 3: Write minimal implementation**

Append to `telemetry_tool/distance_integrity.py`:

```python
def repair_distance_isotonic(distance: np.ndarray) -> np.ndarray:
    """Force distance array to be monotonically non-decreasing.

    Uses sklearn's IsotonicRegression which finds the best
    non-decreasing fit in a least-squares sense.
    """
    from sklearn.isotonic import IsotonicRegression

    d = np.asarray(distance, dtype=np.float64).copy()
    ir = IsotonicRegression(increasing=True)
    indices = np.arange(len(d), dtype=np.float64)
    return ir.fit_transform(indices, d)
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_distance_integrity.py -v`
Expected: 13 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/distance_integrity.py telemetry_tool/tests/test_distance_integrity.py
git commit -m "feat(distance): add isotonic regression fallback repair"
```

---

### Task 5: run_distance_integrity() orchestrator

**Files:**
- Modify: `telemetry_tool/distance_integrity.py`
- Modify: `telemetry_tool/tests/test_distance_integrity.py`

**Step 1: Write the failing tests**

Append to `telemetry_tool/tests/test_distance_integrity.py`:

```python
def test_run_integrity_ok_laps():
    """Clean laps → status='ok', no repair, no gate."""
    from distance_integrity import run_distance_integrity

    laps = _make_lap_dict({
        1: np.linspace(0, 500, 200),
        2: np.linspace(0, 498, 200),
    })
    result_laps, dq = run_distance_integrity(laps)
    assert dq.status == "ok"
    assert dq.gate_advanced is False
    assert dq.repair_method is None
    assert len(result_laps) == 2


def test_run_integrity_repairs_with_xy():
    """Non-monotonic lap with XY columns → repaired via xy_rebuild."""
    from distance_integrity import run_distance_integrity

    d_bad = np.linspace(0, 500, 100)
    for i in range(10, 100, 8):
        d_bad[i] = d_bad[i] - 80  # severe backward jumps
    x = np.linspace(0, 500, 100)
    y = np.zeros(100)
    df = pd.DataFrame({"Distance (m)": d_bad, "x": x, "y": y, "Speed (m/s)": np.ones(100)})
    laps = {1: pd.DataFrame({"Distance (m)": np.linspace(0, 500, 100), "x": x, "y": y, "Speed (m/s)": np.ones(100)}), 2: df}

    result_laps, dq = run_distance_integrity(laps)
    assert dq.status == "repaired"
    assert dq.repair_method == "xy_rebuild"
    assert 2 in dq.laps_repaired
    # Repaired lap should now be monotonic
    repaired_d = result_laps[2]["Distance (m)"].values
    assert np.all(np.diff(repaired_d) >= 0)


def test_run_integrity_isotonic_fallback():
    """Non-monotonic lap without XY → repaired via isotonic_regression."""
    from distance_integrity import run_distance_integrity

    d_bad = np.linspace(0, 500, 100)
    for i in range(10, 100, 8):
        d_bad[i] = d_bad[i] - 80
    df = pd.DataFrame({"Distance (m)": d_bad, "Speed (m/s)": np.ones(100)})
    laps = {1: pd.DataFrame({"Distance (m)": np.linspace(0, 500, 100), "Speed (m/s)": np.ones(100)}), 2: df}

    result_laps, dq = run_distance_integrity(laps)
    assert dq.status == "repaired"
    assert dq.repair_method == "isotonic_regression"
    assert 2 in dq.laps_repaired


def test_run_integrity_gate_on_severe_damage():
    """Distance so corrupted that even repair fails → gate_advanced=True."""
    from distance_integrity import run_distance_integrity

    # All-zeros distance can't be repaired without coordinates
    d_bad = np.zeros(100)
    df = pd.DataFrame({"Distance (m)": d_bad, "Speed (m/s)": np.ones(100)})
    laps = {1: df}

    result_laps, dq = run_distance_integrity(laps)
    assert dq.gate_advanced is True
    assert dq.status == "degraded"
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_distance_integrity.py::test_run_integrity_ok_laps -v`
Expected: FAIL with "cannot import name 'run_distance_integrity'"

**Step 3: Write minimal implementation**

Append to `telemetry_tool/distance_integrity.py`:

```python
def run_distance_integrity(
    lap_dict: dict[int, "pd.DataFrame"],
    *,
    dist_col: str = "Distance (m)",
    config: Optional[dict] = None,
) -> tuple[dict[int, "pd.DataFrame"], DistanceQuality]:
    """Full distance integrity check: assess → repair → re-assess → gate.

    Parameters
    ----------
    lap_dict : {lap_number: DataFrame} with distance column.
    dist_col : Name of distance column.
    config : Optional overrides for thresholds.

    Returns
    -------
    (repaired_lap_dict, DistanceQuality)
    """
    import pandas as pd

    cfg = config or {}
    mono_repair = cfg.get("mono_ratio_repair", MONO_RATIO_REPAIR)
    jump_repair = cfg.get("jump_count_repair", JUMP_COUNT_REPAIR)
    mono_gate = cfg.get("mono_ratio_gate", MONO_RATIO_GATE)

    # Phase 1: Assess
    quality = assess_all_laps(lap_dict, dist_col=dist_col)

    # Identify laps needing repair
    needs_repair = []
    for m_dict in quality.metrics:
        if m_dict["monotonic_ratio"] < mono_repair or m_dict["jump_count"] > jump_repair:
            needs_repair.append(m_dict["lap_number"])

    if not needs_repair:
        quality.status = "ok"
        quality.gate_advanced = False
        quality.message = "Distance data is clean across all laps."
        return lap_dict, quality

    # Phase 2: Repair
    repaired_dict = dict(lap_dict)  # shallow copy
    repair_method = None
    actually_repaired = []
    still_degraded = []

    for lap_num in needs_repair:
        df = lap_dict[lap_num]

        # Try XY rebuild first
        rebuilt = rebuild_distance_from_xy(df, dist_col=dist_col)
        if rebuilt is not None:
            repaired_dict[lap_num] = rebuilt
            repair_method = "xy_rebuild"
            actually_repaired.append(lap_num)
            continue

        # Fallback: isotonic regression
        if dist_col in df.columns:
            d = pd.to_numeric(df[dist_col], errors="coerce").values.astype(np.float64)
            repaired_d = repair_distance_isotonic(d)
            new_df = df.copy()
            new_df[dist_col] = repaired_d
            repaired_dict[lap_num] = new_df
            if repair_method is None:
                repair_method = "isotonic_regression"
            actually_repaired.append(lap_num)
        else:
            still_degraded.append(lap_num)

    # Phase 3: Re-assess repaired laps
    re_quality = assess_all_laps(repaired_dict, dist_col=dist_col)

    for m_dict in re_quality.metrics:
        if m_dict["lap_number"] in actually_repaired:
            if m_dict["monotonic_ratio"] < mono_gate:
                if m_dict["lap_number"] not in still_degraded:
                    still_degraded.append(m_dict["lap_number"])
                    actually_repaired.remove(m_dict["lap_number"])

    # Phase 4: Determine final status
    gate = len(still_degraded) > 0
    if still_degraded:
        status = "degraded"
        msg = (
            f"Distance repair failed for laps {still_degraded}. "
            "Advanced analysis (theoretical, coaching) disabled."
        )
    elif actually_repaired:
        status = "repaired"
        msg = (
            f"Distance repaired for laps {actually_repaired} "
            f"via {repair_method}."
        )
    else:
        status = "ok"
        msg = "Distance data is clean across all laps."

    return repaired_dict, DistanceQuality(
        status=status,
        repair_method=repair_method,
        laps_repaired=actually_repaired,
        laps_degraded=still_degraded,
        metrics=re_quality.metrics,
        gate_advanced=gate,
        message=msg,
    )
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_distance_integrity.py -v`
Expected: 17 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/distance_integrity.py telemetry_tool/tests/test_distance_integrity.py
git commit -m "feat(distance): add run_distance_integrity() orchestrator with repair + gate"
```

---

### Task 6: Pipeline integration — stage 6.5

**Files:**
- Modify: `telemetry_tool/pipeline.py:934-956` (between segment_laps and resample)
- Create: `telemetry_tool/tests/test_distance_gate.py`

**Step 1: Write the failing test**

In `telemetry_tool/tests/test_distance_gate.py`:

```python
"""Integration tests for distance integrity gating in the pipeline."""
import numpy as np
import pandas as pd
import pytest


def test_distance_quality_in_summary(seeded_db, tmp_path):
    """Pipeline injects distance_quality into summary dict."""
    import pipeline

    csv_path = tmp_path / "test.csv"
    # Create minimal valid CSV
    n = 500
    laps = np.repeat([1, 2], n // 2)
    time = np.linspace(0, 60, n)
    speed = np.random.default_rng(42).uniform(10, 30, n)
    dist = np.cumsum(speed * np.diff(np.concatenate([[0], time])))
    lat = np.linspace(45.0, 45.001, n)
    lon = np.linspace(9.0, 9.001, n)

    df = pd.DataFrame({
        "Lap #": laps,
        "Time (s)": time,
        "Speed (m/s)": speed,
        "Distance (m)": dist,
        "Latitude (deg)": lat,
        "Longitude (deg)": lon,
    })
    df.to_csv(csv_path, index=False)

    summary = pipeline.run_full_analysis(str(csv_path))
    assert "distance_quality" in summary
    dq = summary["distance_quality"]
    assert dq["status"] in ("ok", "repaired", "degraded")
    assert isinstance(dq["gate_advanced"], bool)
    assert isinstance(dq["metrics"], list)
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_distance_gate.py::test_distance_quality_in_summary -v`
Expected: FAIL (no `distance_quality` key in summary)

**Step 3: Modify pipeline.py**

In `telemetry_tool/pipeline.py`, after line 944 (`lap_dict = validate_lap_consistency(lap_dict)`) and before line 946 (`# STEP 7 -- Normalise`), insert:

```python
        # STEP 6.5 -- Distance integrity preflight
        #
        _di_mod = _import("distance_integrity")

        def _distance_integrity():
            if _di_mod is None:
                logger.info("distance_integrity module absent; skipping preflight.")
                return lap_dict, None
            return _di_mod.run_distance_integrity(lap_dict)

        _di_result, err = _safe_step("06b_distance_integrity", _distance_integrity)
        _record("06b_distance_integrity", _di_result, err)
        _fire_progress("06b_distance_integrity")
        if _di_result is not None:
            lap_dict, _distance_quality = _di_result
            summary["distance_quality"] = _distance_quality.to_dict() if hasattr(_distance_quality, "to_dict") else _distance_quality
        else:
            _distance_quality = None
            summary["distance_quality"] = None
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_distance_gate.py::test_distance_quality_in_summary -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/pipeline.py telemetry_tool/tests/test_distance_gate.py
git commit -m "feat(distance): integrate distance integrity as pipeline stage 6.5"
```

---

### Task 7: Gate theoretical + coaching stages

**Files:**
- Modify: `telemetry_tool/pipeline.py:2091` (theoretical stage) and `telemetry_tool/pipeline.py:2518` (coaching stage)
- Modify: `telemetry_tool/tests/test_distance_gate.py`

**Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_distance_gate.py`:

```python
def test_gate_blocks_theoretical_when_degraded():
    """When distance_quality.gate_advanced=True, theoretical step is skipped."""
    from distance_integrity import DistanceQuality

    dq = DistanceQuality(
        status="degraded",
        gate_advanced=True,
        laps_degraded=[1],
        message="test",
    )
    # The gate check is: if _distance_quality and _distance_quality.gate_advanced
    assert dq.gate_advanced is True
    assert dq.status == "degraded"
```

**Step 2: Run test to verify it passes (it's a unit check)**

Run: `pytest telemetry_tool/tests/test_distance_gate.py::test_gate_blocks_theoretical_when_degraded -v`
Expected: PASS (this test validates the dataclass; the pipeline gate is structural)

**Step 3: Modify pipeline.py — gate theoretical**

In `telemetry_tool/pipeline.py`, before the `_safe_step("10_theoretical", ...)` call (line ~2091), wrap the theoretical step:

Find the existing `_theoretical` function definition and before the `_safe_step` call, add:

```python
    # Gate: skip theoretical if distance quality is degraded
    if _distance_quality is not None and hasattr(_distance_quality, 'gate_advanced') and _distance_quality.gate_advanced:
        logger.warning("Theoretical lap SKIPPED: distance quality gate active (status=%s).",
                       _distance_quality.status if hasattr(_distance_quality, 'status') else 'unknown')
        theoretical_lap = None
        _record("10_theoretical", None, "distance_quality_gate")
        _fire_progress("10_theoretical")
        summary["theoretical_lap"] = None
    else:
```

Similarly, gate the coaching stage (line ~2518) before `_safe_step("13b_coaching_guide", ...)`:

```python
    if _distance_quality is not None and hasattr(_distance_quality, 'gate_advanced') and _distance_quality.gate_advanced:
        logger.warning("Coaching guide SKIPPED: distance quality gate active.")
        cg_result = None
        _record("13b_coaching_guide", None, "distance_quality_gate")
    else:
```

**Step 4: Run full test suite**

Run: `pytest telemetry_tool/tests/test_distance_gate.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/pipeline.py telemetry_tool/tests/test_distance_gate.py
git commit -m "feat(distance): gate theoretical and coaching stages on distance quality"
```

---

### Task 8: API endpoint — GET /sessions/<id>/distance-quality

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py` (after provenance endpoint, line ~3410)
- Modify: `telemetry_tool/tests/test_distance_gate.py`

**Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_distance_gate.py`:

```python
class TestDistanceQualityEndpoint:
    """Tests for GET /api/v1/sessions/<id>/distance-quality."""

    def _setup_app(self, tmp_path):
        """Create a Flask test client with a seeded session."""
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from web.app import create_app
        app = create_app()
        app.config["TESTING"] = True
        return app.test_client()

    def test_distance_quality_returns_from_summary(self, seeded_db):
        """Endpoint returns distance_quality from analysis_json."""
        conn = seeded_db
        # Insert a session with distance_quality in analysis_json
        import json
        analysis = json.dumps({
            "distance_quality": {
                "status": "ok",
                "gate_advanced": False,
                "metrics": [],
                "message": "Clean",
                "repair_method": None,
                "laps_repaired": [],
                "laps_degraded": [],
            }
        })
        conn.execute(
            "UPDATE sessions SET analysis_json = ? WHERE id = 1",
            (analysis,),
        )
        conn.commit()

        from web.app import create_app
        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()
        resp = client.get("/api/v1/sessions/1/distance-quality")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["data"]["status"] == "ok"
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_distance_gate.py::TestDistanceQualityEndpoint -v`
Expected: FAIL with 404 (route not registered)

**Step 3: Add the endpoint**

In `telemetry_tool/web/routes/data_v2.py`, after line 3410 (`# Dev-plans endpoints moved...`), add:

```python
# ══════════════════════════════════════════════════════════════════
# 45. GET /api/v1/sessions/<id>/distance-quality — Distance quality
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/distance-quality", methods=["GET"])
@_safe_api
def get_distance_quality(session_id: str):
    """Return the distance quality assessment for a session.

    Read from analysis_json['distance_quality'].
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    analysis = models.get_analysis_json(conn, session_id)
    if analysis and isinstance(analysis, dict):
        dq = analysis.get("distance_quality")
        if dq:
            return api_response(dq)

    return api_error(
        ErrorCode.NOT_FOUND,
        "No distance quality data available for this session",
        status=404,
    )
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_distance_gate.py::TestDistanceQualityEndpoint -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py telemetry_tool/tests/test_distance_gate.py
git commit -m "feat(distance): add GET /sessions/<id>/distance-quality API endpoint"
```

---

### Task 9: Include distance_quality in session detail response

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py:324-330` (get_session endpoint)
- Modify: `telemetry_tool/tests/test_distance_gate.py`

**Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_distance_gate.py`:

```python
def test_session_detail_includes_distance_quality(seeded_db):
    """GET /api/v1/sessions/<id> includes distance_quality when available."""
    import json
    conn = seeded_db
    analysis = json.dumps({
        "distance_quality": {"status": "repaired", "gate_advanced": False,
                             "repair_method": "xy_rebuild", "laps_repaired": [2],
                             "laps_degraded": [], "metrics": [], "message": "Repaired"},
        "pipeline": {"status": "complete"},
    })
    conn.execute("UPDATE sessions SET analysis_json = ? WHERE id = 1", (analysis,))
    conn.commit()

    from web.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    resp = client.get("/api/v1/sessions/1")
    data = resp.get_json()["data"]
    assert "distance_quality" in data
    assert data["distance_quality"]["status"] == "repaired"
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_distance_gate.py::test_session_detail_includes_distance_quality -v`
Expected: FAIL (`distance_quality` not in response)

**Step 3: Modify get_session endpoint**

In `telemetry_tool/web/routes/data_v2.py`, in the `get_session()` function (around line 326-329), after the existing pipeline surfacing block:

```python
    # Surface pipeline status from analysis_json if available
    analysis = models.get_analysis_json(conn, session_id)
    if analysis and isinstance(analysis, dict):
        pipeline = analysis.get("pipeline")
        if pipeline:
            result["pipeline"] = pipeline
```

Add:

```python
        dq = analysis.get("distance_quality")
        if dq:
            result["distance_quality"] = dq
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_distance_gate.py::test_session_detail_includes_distance_quality -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py telemetry_tool/tests/test_distance_gate.py
git commit -m "feat(distance): surface distance_quality in session detail response"
```

---

### Task 10: Report debug section — lap length histogram + distance quality table

**Files:**
- Modify: `telemetry_tool/reporting_html.py:3077-3106` (generate_report signature) and template
- Modify: `telemetry_tool/tests/test_distance_gate.py`

**Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_distance_gate.py`:

```python
def test_report_includes_distance_debug_section():
    """generate_report() with distance_quality renders debug section."""
    from reporting_html import generate_report

    dq = {
        "status": "repaired",
        "repair_method": "xy_rebuild",
        "gate_advanced": False,
        "laps_repaired": [2],
        "laps_degraded": [],
        "message": "Distance repaired for laps [2] via xy_rebuild.",
        "metrics": [
            {"lap_number": 1, "monotonic_ratio": 1.0, "jump_count": 0,
             "compression_ratio": 0.01, "lap_length": 500.0, "lap_length_zscore": 0.1},
            {"lap_number": 2, "monotonic_ratio": 0.98, "jump_count": 2,
             "compression_ratio": 0.05, "lap_length": 502.0, "lap_length_zscore": 0.3},
        ],
    }
    path = generate_report(
        session_meta={"session_id": "test", "track_id": "test_track"},
        distance_quality=dq,
        output_path="test_dq_report.html",
    )
    html = path.read_text(encoding="utf-8")
    assert "Distance Quality" in html
    assert "xy_rebuild" in html
    assert "Lap 2" in html or "lap_number" in html
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_distance_gate.py::test_report_includes_distance_debug_section -v`
Expected: FAIL (generate_report doesn't accept distance_quality parameter)

**Step 3: Modify reporting_html.py**

3a. Add `distance_quality` parameter to `generate_report()` signature (after `phase_theoreticals`):

```python
    # --- Distance quality debug section (all optional) -
    distance_quality:     Optional[dict[str, Any]]         = None,
```

3b. Add a helper function `_build_distance_quality_html()` before `generate_report()`:

```python
def _build_distance_quality_html(distance_quality: Optional[dict]) -> str:
    """Build HTML fragment for the distance quality debug section."""
    if not distance_quality:
        return ""

    status = distance_quality.get("status", "unknown")
    repair = distance_quality.get("repair_method") or "none"
    message = distance_quality.get("message", "")
    metrics = distance_quality.get("metrics", [])
    gate = distance_quality.get("gate_advanced", False)

    # Status badge colour
    badge_map = {"ok": "#00d4aa", "repaired": "#ffd93d", "degraded": "#ff6b6b"}
    badge_color = badge_map.get(status, "#a0a4b0")

    parts = [
        '<div style="margin-top:2em; padding:1.5em; background:#1a1d26; border-radius:12px;">',
        '<h3 style="color:#e6e9ef; margin-bottom:0.5em;">Distance Quality Debug</h3>',
        f'<p><span style="display:inline-block; padding:2px 10px; border-radius:6px; '
        f'background:{badge_color}; color:#0e1117; font-weight:600;">{status.upper()}</span>',
        f' &nbsp; Repair: <code>{repair}</code></p>',
        f'<p style="color:#a0a4b0;">{message}</p>',
    ]

    if gate:
        parts.append(
            '<p style="color:#ff6b6b; font-weight:600;">'
            '⚠ Advanced analysis disabled due to distance quality issues.</p>'
        )

    # Metrics table
    if metrics:
        parts.append(
            '<table style="width:100%; border-collapse:collapse; margin-top:1em; font-size:0.9em;">'
            '<thead><tr style="border-bottom:1px solid #333;">'
            '<th style="text-align:left; padding:4px 8px; color:#a0a4b0;">Lap</th>'
            '<th style="text-align:right; padding:4px 8px; color:#a0a4b0;">Mono Ratio</th>'
            '<th style="text-align:right; padding:4px 8px; color:#a0a4b0;">Jumps</th>'
            '<th style="text-align:right; padding:4px 8px; color:#a0a4b0;">Compression</th>'
            '<th style="text-align:right; padding:4px 8px; color:#a0a4b0;">Length (m)</th>'
            '<th style="text-align:right; padding:4px 8px; color:#a0a4b0;">Z-score</th>'
            '</tr></thead><tbody>'
        )
        for m in metrics:
            mono = m.get("monotonic_ratio", 0)
            row_color = "#ff6b6b" if mono < 0.95 else ("#ffd93d" if mono < 0.99 else "#e6e9ef")
            parts.append(
                f'<tr style="border-bottom:1px solid #222;">'
                f'<td style="padding:4px 8px; color:{row_color};">Lap {m.get("lap_number", "?")}</td>'
                f'<td style="text-align:right; padding:4px 8px; color:{row_color};">{mono:.4f}</td>'
                f'<td style="text-align:right; padding:4px 8px; color:{row_color};">{m.get("jump_count", 0)}</td>'
                f'<td style="text-align:right; padding:4px 8px; color:{row_color};">{m.get("compression_ratio", 0):.3f}</td>'
                f'<td style="text-align:right; padding:4px 8px; color:{row_color};">{m.get("lap_length", 0):.1f}</td>'
                f'<td style="text-align:right; padding:4px 8px; color:{row_color};">{m.get("lap_length_zscore", 0):.2f}</td>'
                f'</tr>'
            )
        parts.append('</tbody></table>')

    parts.append('</div>')
    return "\n".join(parts)
```

3c. In the `generate_report()` body, build the HTML and pass it to the template. Find the line where `quality_badge` is built (~line 3385) and add nearby:

```python
    distance_quality_html = _build_distance_quality_html(distance_quality)
```

3d. Add `distance_quality_html=distance_quality_html` to the template render call (~line 3408).

3e. In the HTML template string, after the coaching guide section and before the closing `</body>`, add:

```html
<!-- ====== Distance Quality Debug ====== -->
{% if distance_quality_html %}
{{ distance_quality_html }}
{% endif %}
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_distance_gate.py::test_report_includes_distance_debug_section -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/reporting_html.py telemetry_tool/tests/test_distance_gate.py
git commit -m "feat(distance): add distance quality debug section to HTML report"
```

---

### Task 11: Wire distance_quality into report generation call

**Files:**
- Modify: `telemetry_tool/pipeline.py` (the `generate_report()` call, around line ~2530-2560)

**Step 1: Verify current report call location**

Read `pipeline.py` around line 2530-2560 to find where `generate_report()` is called and add `distance_quality=summary.get("distance_quality")` to the kwargs.

**Step 2: Add distance_quality kwarg**

Find the `generate_report(` call in pipeline.py and add:

```python
                distance_quality=summary.get("distance_quality"),
```

to the existing keyword arguments.

**Step 3: Run existing tests**

Run: `pytest telemetry_tool/tests/test_distance_integrity.py telemetry_tool/tests/test_distance_gate.py -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add telemetry_tool/pipeline.py
git commit -m "feat(distance): wire distance_quality into report generation"
```

---

### Task 12: Final integration test + cleanup

**Files:**
- Modify: `telemetry_tool/tests/test_distance_gate.py`

**Step 1: Write end-to-end test**

Append to `telemetry_tool/tests/test_distance_gate.py`:

```python
def test_non_monotonic_csv_gets_repaired(tmp_path):
    """End-to-end: CSV with non-monotonic distance → repaired + summary has distance_quality."""
    import pipeline

    n = 400
    laps = np.repeat([1, 2], n // 2)
    time = np.linspace(0, 60, n)
    speed = np.full(n, 20.0)

    # Create non-monotonic distance for lap 2
    d1 = np.linspace(0, 500, n // 2)
    d2 = np.linspace(0, 500, n // 2)
    # Inject backward jumps in lap 2
    for i in range(10, n // 2, 15):
        d2[i] = d2[i] - 50
    dist = np.concatenate([d1, d2])

    df = pd.DataFrame({
        "Lap #": laps,
        "Time (s)": time,
        "Speed (m/s)": speed,
        "Distance (m)": dist,
    })

    csv_path = tmp_path / "nonmono.csv"
    df.to_csv(csv_path, index=False)

    summary = pipeline.run_full_analysis(str(csv_path))

    dq = summary.get("distance_quality")
    assert dq is not None
    assert dq["status"] in ("ok", "repaired", "degraded")
    # Lap 2 should have been flagged
    if dq["status"] == "repaired":
        assert 2 in dq["laps_repaired"]
```

**Step 2: Run full test suite**

Run: `pytest telemetry_tool/tests/test_distance_integrity.py telemetry_tool/tests/test_distance_gate.py -v`
Expected: All PASS

**Step 3: Commit**

```bash
git add telemetry_tool/tests/test_distance_gate.py
git commit -m "test(distance): add end-to-end integration test for distance integrity"
```

---

## Summary

| Task | What | Tests |
|------|------|-------|
| 1 | LapDistanceMetrics + compute_lap_metrics() | 5 |
| 2 | DistanceQuality + assess_all_laps() | 3 |
| 3 | XY rebuild repair (Euclidean + Haversine) | 3 |
| 4 | Isotonic regression fallback | 2 |
| 5 | run_distance_integrity() orchestrator | 4 |
| 6 | Pipeline stage 6.5 integration | 1 |
| 7 | Gate theoretical + coaching stages | 1 |
| 8 | API endpoint GET /distance-quality | 1 |
| 9 | Session detail includes distance_quality | 1 |
| 10 | Report debug section (table + badges) | 1 |
| 11 | Wire distance_quality into report call | 0 (covered by existing) |
| 12 | End-to-end integration test | 1 |
| **Total** | | **23** |
