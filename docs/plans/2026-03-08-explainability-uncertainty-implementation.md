# Solver Explainability + Uncertainty Bands + Corner Coaching Labels Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add per-point limiting factor labels, uncertainty bands, and physics-aware corner coaching to the optimal solver pipeline.

**Architecture:** Extend `OptimalResult` with `limiting_factor` array and band fields. Add `CornerSaturation` + `solve_optimal_speed_with_bands()` to `optimal_solver.py`. Extend `CornerPerformance` with priority/coaching fields in `corner_analysis.py`. Wire through pipeline, reporting, and API.

**Tech Stack:** Python 3.x, NumPy, pytest

---

### Task 1: Per-point limiting factor classification

**Files:**
- Modify: `telemetry_tool/optimal_solver.py`
- Modify: `telemetry_tool/tests/test_optimal_solver.py`

**Step 1: Write the failing tests**

Append to `telemetry_tool/tests/test_optimal_solver.py`:

```python


def test_limiting_factor_cornering_dominated():
    """Track with tight corners → most points cornering-limited."""
    from optimal_solver import OptimalCaps, solve_optimal_speed

    n = 200
    dist = np.linspace(0, 500, n)
    curvature = np.full(n, 0.04)  # tight everywhere (radius=25m)

    caps = OptimalCaps(
        distance_m=dist,
        v_cap=np.full(n, 60.0),
        ax_accel=np.full(n, 8.0),
        ax_brake=np.full(n, 12.0),
        curvature=curvature,
        mu=np.full(n, 1.0),
        cap_source=["test"] * n,
        solver_version="test",
    )
    result = solve_optimal_speed(caps)

    assert hasattr(result, "limiting_factor")
    assert len(result.limiting_factor) == n

    # Most points should be cornering
    factor_counts = {}
    for f in result.limiting_factor:
        factor_counts[f] = factor_counts.get(f, 0) + 1
    assert factor_counts.get("cornering", 0) > n * 0.5

    # to_dict should include limiting_factor
    d = result.to_dict()
    assert "limiting_factor" in d
    assert "limiting_factor_summary" in d


def test_limiting_factor_straight_track():
    """Straight track → traction or cap limited, not cornering."""
    from optimal_solver import OptimalCaps, solve_optimal_speed

    n = 200
    dist = np.linspace(0, 1000, n)
    caps = OptimalCaps(
        distance_m=dist,
        v_cap=np.full(n, 30.0),  # low cap
        ax_accel=np.full(n, 5.0),
        ax_brake=np.full(n, 8.0),
        curvature=np.zeros(n),
        mu=np.full(n, 1.5),
        cap_source=["test"] * n,
        solver_version="test",
    )
    result = solve_optimal_speed(caps)

    # No cornering limitation on straight track
    cornering_count = sum(1 for f in result.limiting_factor if f == "cornering")
    total = len(result.limiting_factor)
    assert cornering_count < total * 0.1  # very few if any
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_optimal_solver.py::test_limiting_factor_cornering_dominated telemetry_tool/tests/test_optimal_solver.py::test_limiting_factor_straight_track -v`
Expected: FAIL with AttributeError "limiting_factor"

**Step 3: Modify `solve_optimal_speed()` in `optimal_solver.py`**

Add `limiting_factor` field to `OptimalResult` (line 72, after `brake_limited`):

```python
    limiting_factor: np.ndarray     # str per point: "cornering"|"traction"|"braking"|"cap"
```

Update `OptimalResult.to_dict()` to include:

```python
            "limiting_factor": self.limiting_factor.tolist(),
            "limiting_factor_summary": dict(Counter(self.limiting_factor.tolist())),
```

In `solve_optimal_speed()`, after the existing constraint classification (line 196), add:

```python
    # Per-point limiting factor (priority: cornering > braking > traction > cap)
    limiting_factor = np.full(n, "cap", dtype=object)
    for i in range(n):
        if cornering_limited[i]:
            limiting_factor[i] = "cornering"
        elif brake_limited[i]:
            limiting_factor[i] = "braking"
        elif accel_limited[i]:
            limiting_factor[i] = "traction"
        # else stays "cap"
```

Add `limiting_factor=limiting_factor` to the `return OptimalResult(...)` call (line 222).

Also update the `n < 2` early return (line 121) to include `limiting_factor=np.full(n, "cornering", dtype=object)`.

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_optimal_solver.py -v`
Expected: 11 PASSED (9 existing + 2 new)

**Step 5: Commit**

```bash
git add telemetry_tool/optimal_solver.py telemetry_tool/tests/test_optimal_solver.py
git commit -m "feat(optimal): add per-point limiting_factor classification to solver"
```

---

### Task 2: CornerSaturation dataclass + compute_corner_saturation()

**Files:**
- Modify: `telemetry_tool/optimal_solver.py`
- Modify: `telemetry_tool/tests/test_optimal_solver.py`

**Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_optimal_solver.py`:

```python


def test_corner_saturation_cornering_dominated():
    """Corner with tight curvature → high cornering saturation."""
    from optimal_solver import (
        OptimalCaps, solve_optimal_speed, compute_corner_saturation,
    )

    n = 200
    dist = np.linspace(0, 500, n)
    curvature = np.zeros(n)
    curvature[80:120] = 0.05  # tight corner

    caps = OptimalCaps(
        distance_m=dist,
        v_cap=np.full(n, 50.0),
        ax_accel=np.full(n, 5.0),
        ax_brake=np.full(n, 8.0),
        curvature=curvature,
        mu=np.full(n, 1.0),
        cap_source=["test"] * n,
        solver_version="test",
    )
    result = solve_optimal_speed(caps)

    corners = [{"corner_id": 1, "s_start": dist[80], "s_end": dist[120]}]
    saturations = compute_corner_saturation(result, corners)

    assert len(saturations) == 1
    sat = saturations[0]
    assert sat.corner_id == 1
    assert sat.cornering_pct > 0.3  # majority cornering-limited
    assert sat.dominant_factor == "cornering"
    assert 0.0 <= sat.saturation_98pct <= 1.0

    d = sat.to_dict()
    assert "dominant_factor" in d
    assert "saturation_98pct" in d
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_optimal_solver.py::test_corner_saturation_cornering_dominated -v`
Expected: FAIL with ImportError

**Step 3: Add CornerSaturation + compute_corner_saturation() to optimal_solver.py**

Append before `solve_optimal_speed()` (after OptimalResult class):

```python


@dataclass
class CornerSaturation:
    """Per-corner breakdown of limiting factor distribution."""
    corner_id: int
    s_start: float
    s_end: float
    cornering_pct: float
    traction_pct: float
    braking_pct: float
    cap_pct: float
    dominant_factor: str
    saturation_98pct: float   # fraction of bins at >98% of active constraint

    def to_dict(self) -> dict:
        return {
            "corner_id": self.corner_id,
            "s_start": round(self.s_start, 2),
            "s_end": round(self.s_end, 2),
            "cornering_pct": round(self.cornering_pct, 4),
            "traction_pct": round(self.traction_pct, 4),
            "braking_pct": round(self.braking_pct, 4),
            "cap_pct": round(self.cap_pct, 4),
            "dominant_factor": self.dominant_factor,
            "saturation_98pct": round(self.saturation_98pct, 4),
        }
```

Append after `solve_optimal_speed()`:

```python


def compute_corner_saturation(
    result: OptimalResult,
    corners: list[dict],
) -> list[CornerSaturation]:
    """Compute per-corner saturation metrics from solver result.

    Parameters
    ----------
    result : OptimalResult with limiting_factor
    corners : list of dicts with corner_id, s_start, s_end

    Returns
    -------
    List of CornerSaturation, one per corner.
    """
    if not corners:
        return []

    dist = result.distance_m
    saturations = []

    for corner in corners:
        cid = corner.get("corner_id", 0)
        s_start = corner.get("s_start", 0)
        s_end = corner.get("s_end", 0)

        # Find indices within corner
        mask = (dist >= s_start) & (dist <= s_end)
        n_pts = int(mask.sum())
        if n_pts == 0:
            continue

        # Factor distribution
        factors = result.limiting_factor[mask]
        total = len(factors)
        cornering_pct = float(np.sum(factors == "cornering")) / total
        traction_pct = float(np.sum(factors == "traction")) / total
        braking_pct = float(np.sum(factors == "braking")) / total
        cap_pct = float(np.sum(factors == "cap")) / total

        # Dominant factor
        counts = {"cornering": cornering_pct, "traction": traction_pct,
                  "braking": braking_pct, "cap": cap_pct}
        dominant = max(counts, key=counts.get)

        # Saturation: fraction of bins where v_opt is >98% of the constraint
        # that is actually limiting at that point
        v_opt = result.v_opt_mps[mask]
        v_corner_approx = v_opt.copy()  # corner limit approximation
        cornering_mask_local = result.cornering_limited[mask]
        accel_mask_local = result.accel_limited[mask]
        brake_mask_local = result.brake_limited[mask]

        # For each point, the constraint is v_opt / (v_opt + headroom)
        # We approximate saturation as how close v_opt is to the bool limit
        # Since cornering_limited means v_opt ≈ v_corner within tolerance,
        # we count how many limited points there are as the saturation proxy
        limited_any = cornering_mask_local | accel_mask_local | brake_mask_local
        sat_98 = float(limited_any.sum()) / total if total > 0 else 0.0

        saturations.append(CornerSaturation(
            corner_id=cid,
            s_start=s_start,
            s_end=s_end,
            cornering_pct=cornering_pct,
            traction_pct=traction_pct,
            braking_pct=braking_pct,
            cap_pct=cap_pct,
            dominant_factor=dominant,
            saturation_98pct=sat_98,
        ))

    return saturations
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_optimal_solver.py -v`
Expected: 12 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/optimal_solver.py telemetry_tool/tests/test_optimal_solver.py
git commit -m "feat(optimal): add CornerSaturation dataclass and compute_corner_saturation()"
```

---

### Task 3: Uncertainty bands — solve_optimal_speed_with_bands()

**Files:**
- Modify: `telemetry_tool/optimal_solver.py`
- Modify: `telemetry_tool/tests/test_optimal_solver.py`

**Step 1: Write the failing tests**

Append to `telemetry_tool/tests/test_optimal_solver.py`:

```python


def test_solve_with_bands_produces_interval():
    """Bands solver produces low/high traces and lap time interval."""
    from optimal_solver import OptimalCaps, solve_optimal_speed_with_bands

    n = 100
    dist = np.linspace(0, 500, n)
    curvature = np.zeros(n)
    curvature[40:60] = 0.03

    def _make_caps(mu_val, ax_accel, ax_brake):
        return OptimalCaps(
            distance_m=dist,
            v_cap=np.full(n, 40.0),
            ax_accel=np.full(n, ax_accel),
            ax_brake=np.full(n, ax_brake),
            curvature=curvature,
            mu=np.full(n, mu_val),
            cap_source=["test"] * n,
            solver_version="test",
        )

    caps = _make_caps(1.0, 5.0, 8.0)
    caps_low = _make_caps(0.8, 4.0, 6.5)
    caps_high = _make_caps(1.15, 6.0, 9.5)

    result = solve_optimal_speed_with_bands(caps, caps_low, caps_high)

    assert hasattr(result, "v_opt_low_mps")
    assert hasattr(result, "v_opt_high_mps")
    assert len(result.v_opt_low_mps) == n
    assert len(result.v_opt_high_mps) == n

    # Low bound should be <= nominal <= high bound (within tolerance)
    assert np.all(result.v_opt_low_mps <= result.v_opt_mps + 0.5)
    assert np.all(result.v_opt_mps <= result.v_opt_high_mps + 0.5)

    # Lap time interval
    assert result.lap_time_low_s <= result.lap_time_s + 0.1
    assert result.lap_time_s <= result.lap_time_high_s + 0.1

    d = result.to_dict()
    assert "v_opt_low_mps" in d
    assert "v_opt_high_mps" in d
    assert "lap_time_low_s" in d
    assert "lap_time_high_s" in d


def test_bands_wider_with_worse_mu():
    """Lower-quality mu (wider range) → wider bands."""
    from optimal_solver import OptimalCaps, solve_optimal_speed_with_bands

    n = 100
    dist = np.linspace(0, 500, n)
    curvature = np.full(n, 0.02)

    def _make_caps(mu_val, ax_accel, ax_brake):
        return OptimalCaps(
            distance_m=dist,
            v_cap=np.full(n, 40.0),
            ax_accel=np.full(n, ax_accel),
            ax_brake=np.full(n, ax_brake),
            curvature=curvature,
            mu=np.full(n, mu_val),
            cap_source=["test"] * n,
            solver_version="test",
        )

    # Narrow uncertainty
    caps_n = _make_caps(1.0, 5.0, 8.0)
    caps_n_lo = _make_caps(0.95, 4.8, 7.8)
    caps_n_hi = _make_caps(1.05, 5.2, 8.2)
    r_narrow = solve_optimal_speed_with_bands(caps_n, caps_n_lo, caps_n_hi)

    # Wide uncertainty
    caps_w = _make_caps(1.0, 5.0, 8.0)
    caps_w_lo = _make_caps(0.7, 3.5, 5.5)
    caps_w_hi = _make_caps(1.3, 6.5, 10.5)
    r_wide = solve_optimal_speed_with_bands(caps_w, caps_w_lo, caps_w_hi)

    # Wide bands should be wider
    narrow_width = np.mean(r_narrow.v_opt_high_mps - r_narrow.v_opt_low_mps)
    wide_width = np.mean(r_wide.v_opt_high_mps - r_wide.v_opt_low_mps)
    assert wide_width > narrow_width
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_optimal_solver.py::test_solve_with_bands_produces_interval telemetry_tool/tests/test_optimal_solver.py::test_bands_wider_with_worse_mu -v`
Expected: FAIL with ImportError

**Step 3: Add OptimalResultWithBands + solve_optimal_speed_with_bands()**

Append to `telemetry_tool/optimal_solver.py` after `compute_corner_saturation()`:

```python


@dataclass
class OptimalResultWithBands(OptimalResult):
    """OptimalResult extended with uncertainty bands."""
    v_opt_low_mps: np.ndarray = field(default_factory=lambda: np.array([]))
    v_opt_high_mps: np.ndarray = field(default_factory=lambda: np.array([]))
    lap_time_low_s: float = 0.0
    lap_time_high_s: float = 0.0

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["v_opt_low_mps"] = np.round(self.v_opt_low_mps, 4).tolist()
        d["v_opt_high_mps"] = np.round(self.v_opt_high_mps, 4).tolist()
        d["lap_time_low_s"] = round(self.lap_time_low_s, 4)
        d["lap_time_high_s"] = round(self.lap_time_high_s, 4)
        return d


def solve_optimal_speed_with_bands(
    caps: OptimalCaps,
    caps_low: OptimalCaps,
    caps_high: OptimalCaps,
) -> OptimalResultWithBands:
    """Run solver 3x to produce nominal + uncertainty bands.

    Parameters
    ----------
    caps : nominal OptimalCaps
    caps_low : pessimistic caps (lower mu, lower accel)
    caps_high : optimistic caps (higher mu, higher accel)

    Returns
    -------
    OptimalResultWithBands with v_opt_low_mps, v_opt_high_mps, lap_time interval.
    """
    r_nom = solve_optimal_speed(caps)
    r_low = solve_optimal_speed(caps_low)
    r_high = solve_optimal_speed(caps_high)

    return OptimalResultWithBands(
        distance_m=r_nom.distance_m,
        v_opt_mps=r_nom.v_opt_mps,
        accel_profile_mps2=r_nom.accel_profile_mps2,
        lap_time_s=r_nom.lap_time_s,
        cornering_limited=r_nom.cornering_limited,
        accel_limited=r_nom.accel_limited,
        brake_limited=r_nom.brake_limited,
        limiting_factor=r_nom.limiting_factor,
        cap_source=r_nom.cap_source,
        solver_version=r_nom.solver_version,
        n_iterations=r_nom.n_iterations,
        v_opt_low_mps=r_low.v_opt_mps,
        v_opt_high_mps=r_high.v_opt_mps,
        lap_time_low_s=r_high.lap_time_s,   # faster lap = optimistic caps
        lap_time_high_s=r_low.lap_time_s,    # slower lap = pessimistic caps
    )
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_optimal_solver.py -v`
Expected: 14 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/optimal_solver.py telemetry_tool/tests/test_optimal_solver.py
git commit -m "feat(optimal): add solve_optimal_speed_with_bands() for uncertainty quantification"
```

---

### Task 4: Cap producers — low/high variants

**Files:**
- Modify: `telemetry_tool/theoretical_engine.py`
- Modify: `telemetry_tool/lap_simulation.py`
- Modify: `telemetry_tool/tests/test_optimal_solver.py`

**Step 1: Write the failing tests**

Append to `telemetry_tool/tests/test_optimal_solver.py`:

```python


def test_caps_from_percentile_envelope_with_bands():
    """Percentile envelope produces low/high cap variants."""
    from theoretical_engine import caps_from_percentile_envelope_with_bands

    rng = np.random.default_rng(42)
    n_points = 200
    laps = []
    for _ in range(8):
        dist = np.linspace(0, 500, n_points)
        speed = np.full(n_points, 20.0) + rng.normal(0, 1.5, n_points)
        speed = np.clip(speed, 5.0, 40.0)
        laps.append(pd.DataFrame({
            "distance_m": dist,
            "speed_mps": speed,
            "accel_long_mps2": rng.normal(0, 2.0, n_points),
        }))

    curvature = np.full(n_points, 0.005)
    caps, caps_low, caps_high = caps_from_percentile_envelope_with_bands(
        laps, curvature,
    )

    assert len(caps.distance_m) == n_points
    # Low caps should have lower v_cap on average
    assert np.mean(caps_low.v_cap) <= np.mean(caps.v_cap) + 0.1
    # High caps should have higher v_cap on average
    assert np.mean(caps_high.v_cap) >= np.mean(caps.v_cap) - 0.1


def test_caps_from_vehicle_model_with_bands():
    """Vehicle model produces low/high cap variants via mu range."""
    from lap_simulation import caps_from_vehicle_model_with_bands

    n = 200
    dist = np.linspace(0, 500, n)
    curvature = np.zeros(n)
    curvature[80:120] = 0.02

    caps, caps_low, caps_high = caps_from_vehicle_model_with_bands(
        distance_m=dist,
        curvature=curvature,
        traction_mps2=5.0,
        braking_mps2=8.0,
        mu=1.2,
        mu_low=1.0,
        mu_high=1.35,
        v_max_mps=40.0,
    )

    assert len(caps.distance_m) == n
    # Low mu → lower corner speed caps
    corner_cap_low = np.mean(caps_low.v_cap[90:110])
    corner_cap_nom = np.mean(caps.v_cap[90:110])
    corner_cap_high = np.mean(caps_high.v_cap[90:110])
    assert corner_cap_low <= corner_cap_nom + 0.1
    assert corner_cap_nom <= corner_cap_high + 0.1
```

**Step 2: Run tests to verify they fail**

**Step 3: Add `caps_from_percentile_envelope_with_bands()` to `theoretical_engine.py`**

Append after the existing `caps_from_percentile_envelope()`:

```python


def caps_from_percentile_envelope_with_bands(
    laps: list["pd.DataFrame"],
    curvature: "np.ndarray",
    speed_percentile: float = 98.0,
    speed_percentile_low: float = 90.0,
    speed_percentile_high: float = 99.5,
    accel_percentile: float = 99.0,
    accel_percentile_low: float = 90.0,
    accel_percentile_high: float = 99.9,
    smooth_window: int = 5,
) -> tuple["OptimalCaps", "OptimalCaps", "OptimalCaps"]:
    """Build nominal + low + high OptimalCaps from percentile envelope.

    Returns (caps_nominal, caps_low, caps_high).
    """
    caps_nom = caps_from_percentile_envelope(
        laps, curvature,
        speed_percentile=speed_percentile,
        accel_percentile=accel_percentile,
        smooth_window=smooth_window,
    )
    caps_low = caps_from_percentile_envelope(
        laps, curvature,
        speed_percentile=speed_percentile_low,
        accel_percentile=accel_percentile_low,
        smooth_window=smooth_window,
    )
    caps_high = caps_from_percentile_envelope(
        laps, curvature,
        speed_percentile=speed_percentile_high,
        accel_percentile=accel_percentile_high,
        smooth_window=smooth_window,
    )
    # Override source tags
    n = len(caps_low.distance_m)
    caps_low.cap_source = [f"envelope_p{int(speed_percentile_low)}"] * n
    caps_high.cap_source = [f"envelope_p{int(speed_percentile_high)}"] * n

    return caps_nom, caps_low, caps_high
```

**Step 4: Add `caps_from_vehicle_model_with_bands()` to `lap_simulation.py`**

Append after the existing `caps_from_vehicle_model()`:

```python


def caps_from_vehicle_model_with_bands(
    *,
    distance_m: "np.ndarray",
    curvature: "np.ndarray",
    traction_mps2: float,
    braking_mps2: float,
    mu: float,
    mu_low: float | None = None,
    mu_high: float | None = None,
    v_max_mps: float = 80.0,
    grip_map: Any = None,
) -> tuple["OptimalCaps", "OptimalCaps", "OptimalCaps"]:
    """Build nominal + low + high OptimalCaps from vehicle model.

    Returns (caps_nominal, caps_low, caps_high).
    """
    if mu_low is None:
        mu_low = mu * 0.85
    if mu_high is None:
        mu_high = mu * 1.05

    caps_nom = caps_from_vehicle_model(
        distance_m=distance_m, curvature=curvature,
        traction_mps2=traction_mps2, braking_mps2=braking_mps2,
        mu=mu, v_max_mps=v_max_mps, grip_map=grip_map,
    )
    caps_low = caps_from_vehicle_model(
        distance_m=distance_m, curvature=curvature,
        traction_mps2=traction_mps2 * 0.8,
        braking_mps2=braking_mps2 * 0.8,
        mu=mu_low, v_max_mps=v_max_mps,
    )
    caps_high = caps_from_vehicle_model(
        distance_m=distance_m, curvature=curvature,
        traction_mps2=traction_mps2 * 1.1,
        braking_mps2=braking_mps2 * 1.1,
        mu=mu_high, v_max_mps=v_max_mps,
    )

    n = len(distance_m)
    caps_low.cap_source = ["physics_model_low"] * n
    caps_high.cap_source = ["physics_model_high"] * n

    return caps_nom, caps_low, caps_high
```

**Step 5: Run tests, commit**

Run: `pytest telemetry_tool/tests/test_optimal_solver.py -v`
Expected: 16 PASSED

```bash
git add telemetry_tool/theoretical_engine.py telemetry_tool/lap_simulation.py telemetry_tool/tests/test_optimal_solver.py
git commit -m "feat(optimal): add cap producer low/high variants for uncertainty bands"
```

---

### Task 5: Corner coaching labels — limiting_factor, priority, coaching_text

**Files:**
- Modify: `telemetry_tool/corner_analysis.py`
- Create: `telemetry_tool/tests/test_corner_coaching.py`

**Step 1: Write the failing tests**

Create `telemetry_tool/tests/test_corner_coaching.py`:

```python
"""Tests for corner coaching labels with physics-aware text."""
import numpy as np
import pytest


def test_corner_performance_has_coaching_fields():
    """CornerPerformance has limiting_factor, corner_priority, coaching_text."""
    from corner_analysis import CornerPerformance

    cp = CornerPerformance(
        corner_id=1,
        s_start=100.0,
        s_end=200.0,
        limiting_factor="cornering",
        corner_priority="balanced",
        coaching_text="Grip-limited through corner 1.",
    )
    assert cp.limiting_factor == "cornering"
    assert cp.corner_priority == "balanced"
    d = cp.to_dict()
    assert "limiting_factor" in d
    assert "corner_priority" in d
    assert "coaching_text" in d


def test_compute_corner_coaching_labels_traction_exit():
    """Traction-limited corner with long straight → exit priority."""
    from corner_analysis import compute_corner_coaching_labels

    corners = [
        {"corner_id": 1, "s_start": 100.0, "s_end": 200.0},
        {"corner_id": 2, "s_start": 400.0, "s_end": 450.0},
    ]
    # Simulate factor distribution: mostly traction in corner 1
    limiting_factors = np.full(500, "cap", dtype=object)
    limiting_factors[100:200] = "traction"
    limiting_factors[400:450] = "cornering"

    distance_m = np.linspace(0, 500, 500)
    lap_length_m = 500.0

    labels = compute_corner_coaching_labels(
        corners=corners,
        limiting_factors=limiting_factors,
        distance_m=distance_m,
        lap_length_m=lap_length_m,
    )

    assert len(labels) == 2
    assert labels[0]["corner_id"] == 1
    assert labels[0]["limiting_factor"] == "traction"
    assert labels[0]["corner_priority"] == "exit"
    assert "traction" in labels[0]["coaching_text"].lower()

    assert labels[1]["corner_id"] == 2
    assert labels[1]["limiting_factor"] == "cornering"


def test_compute_corner_coaching_labels_braking_entry():
    """Braking-limited corner with long straight → entry priority."""
    from corner_analysis import compute_corner_coaching_labels

    corners = [
        {"corner_id": 1, "s_start": 200.0, "s_end": 300.0},
    ]
    limiting_factors = np.full(600, "cap", dtype=object)
    limiting_factors[200:300] = "braking"

    distance_m = np.linspace(0, 600, 600)

    labels = compute_corner_coaching_labels(
        corners=corners,
        limiting_factors=limiting_factors,
        distance_m=distance_m,
        lap_length_m=600.0,
    )

    assert len(labels) == 1
    assert labels[0]["limiting_factor"] == "braking"
    assert labels[0]["corner_priority"] == "entry"
    assert "brak" in labels[0]["coaching_text"].lower()


def test_compute_corner_coaching_empty_corners():
    """Empty corners list → empty labels."""
    from corner_analysis import compute_corner_coaching_labels

    labels = compute_corner_coaching_labels(
        corners=[],
        limiting_factors=np.array([], dtype=object),
        distance_m=np.array([]),
        lap_length_m=0.0,
    )
    assert labels == []
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_corner_coaching.py -v`
Expected: FAIL

**Step 3: Add coaching fields to CornerPerformance and compute_corner_coaching_labels()**

In `corner_analysis.py`, add three new fields to `CornerPerformance` (after line 135 `coaching_hint`):

```python
    limiting_factor: str = ""       # "cornering"|"traction"|"braking"|"cap"
    corner_priority: str = ""       # "entry"|"exit"|"balanced"
    coaching_text: str = ""         # physics-aware coaching sentence
```

Update `CornerPerformance.to_dict()` to include:

```python
            "limiting_factor":               self.limiting_factor,
            "corner_priority":               self.corner_priority,
            "coaching_text":                 self.coaching_text,
```

Append to `corner_analysis.py` (before the `_run_tests()` function or at module level):

```python


_COACHING_TEMPLATES: dict[tuple[str, str], str] = {
    ("cornering", "balanced"): (
        "Grip-limited through corner {cid}. Focus on racing line "
        "to increase minimum speed."
    ),
    ("cornering", "exit"): (
        "Grip-limited through corner {cid}. Smooth throttle application "
        "after apex — the {straight_m:.0f}m straight rewards exit speed."
    ),
    ("traction", "exit"): (
        "Traction-limited on exit of corner {cid}. Prioritize rotation "
        "before throttle — the {straight_m:.0f}m straight amplifies "
        "exit speed gain."
    ),
    ("traction", "balanced"): (
        "Traction-limited through corner {cid}. Progressive throttle "
        "to manage wheelspin."
    ),
    ("braking", "entry"): (
        "Braking-limited into corner {cid}. You can brake later — "
        "entry speed directly feeds the {straight_m:.0f}m straight."
    ),
    ("braking", "balanced"): (
        "Braking-limited into corner {cid}. Trail-braking deeper "
        "may unlock more rotation."
    ),
    ("cap", "exit"): (
        "Near vehicle limit through corner {cid}. Focus on consistency."
    ),
    ("cap", "balanced"): (
        "At speed cap through corner {cid}. You are driving near "
        "the vehicle's maximum capability."
    ),
}


def compute_corner_coaching_labels(
    *,
    corners: list[dict],
    limiting_factors: np.ndarray,
    distance_m: np.ndarray,
    lap_length_m: float,
) -> list[dict]:
    """Compute per-corner coaching labels from solver limiting factors.

    Parameters
    ----------
    corners : list of dicts with corner_id, s_start, s_end
    limiting_factors : per-point limiting factor array from OptimalResult
    distance_m : distance grid matching limiting_factors
    lap_length_m : total lap length

    Returns
    -------
    List of dicts with corner_id, limiting_factor, corner_priority, coaching_text.
    """
    if not corners or len(limiting_factors) == 0:
        return []

    sorted_corners = sorted(corners, key=lambda c: c.get("s_start", 0))
    results = []

    for idx, corner in enumerate(sorted_corners):
        cid = corner.get("corner_id", idx + 1)
        s_start = corner.get("s_start", 0)
        s_end = corner.get("s_end", 0)

        # Find next corner start or wrap to lap end
        if idx + 1 < len(sorted_corners):
            next_s_start = sorted_corners[idx + 1].get("s_start", lap_length_m)
        else:
            next_s_start = lap_length_m
        next_straight_m = max(0, next_s_start - s_end)

        # Factor distribution within corner
        mask = (distance_m >= s_start) & (distance_m <= s_end)
        if not mask.any():
            results.append({
                "corner_id": cid,
                "limiting_factor": "cap",
                "corner_priority": "balanced",
                "coaching_text": f"No data for corner {cid}.",
            })
            continue

        factors = limiting_factors[mask]
        counts = {}
        for f in factors:
            counts[f] = counts.get(f, 0) + 1
        dominant = max(counts, key=counts.get)

        # Priority logic
        if dominant == "braking" and next_straight_m > 100:
            priority = "entry"
        elif dominant == "traction" and next_straight_m > 80:
            priority = "exit"
        elif dominant == "cornering":
            priority = "balanced"
        else:
            priority = "exit"

        # Coaching text from template
        template_key = (dominant, priority)
        template = _COACHING_TEMPLATES.get(
            template_key,
            _COACHING_TEMPLATES.get(
                (dominant, "balanced"),
                "Focus on corner {cid} technique.",
            ),
        )
        coaching_text = template.format(
            cid=cid,
            straight_m=next_straight_m,
        )

        results.append({
            "corner_id": cid,
            "limiting_factor": dominant,
            "corner_priority": priority,
            "coaching_text": coaching_text,
        })

    return results
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_corner_coaching.py -v`
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/corner_analysis.py telemetry_tool/tests/test_corner_coaching.py
git commit -m "feat(coaching): add physics-aware corner coaching labels with entry/exit priority"
```

---

### Task 6: Pipeline wiring — bands + saturation + coaching

**Files:**
- Modify: `telemetry_tool/pipeline.py`

**Step 1: Read pipeline.py around lines 2446-2496**

Understand the existing `_compute_optimal_v2()` function and find where to add bands, saturation, and coaching wiring.

**Step 2: Modify `_compute_optimal_v2()` to use bands**

Replace the `return _opt_mod.solve_optimal_speed(caps)` call with:

```python
        # Build low/high caps if percentile envelope with bands is available
        result_with_bands = None
        if hasattr(theo_mod, "caps_from_percentile_envelope_with_bands"):
            try:
                caps_nom, caps_low, caps_high = theo_mod.caps_from_percentile_envelope_with_bands(
                    laps_list, curv_arr,
                    speed_percentile=speed_pct,
                )
                # Apply grip map to all three
                for c in (caps_nom, caps_low, caps_high):
                    if _grip_map is not None and not _grip_map.is_global_fallback and c.mu is None:
                        c.mu = np.array([
                            _grip_map.mu_at(float(d), "p95") for d in c.distance_m
                        ])
                result_with_bands = _opt_mod.solve_optimal_speed_with_bands(
                    caps_nom, caps_low, caps_high,
                )
            except Exception as exc:
                logger.debug("solve_optimal_speed_with_bands failed: %s", exc)

        if result_with_bands is not None:
            return result_with_bands

        return _opt_mod.solve_optimal_speed(caps)
```

**Step 3: Add corner saturation and coaching after the optimal result**

After `summary["optimal_v2"] = _optimal_result.to_dict()`, add:

```python
        # Corner saturation
        if corners and hasattr(_opt_mod, "compute_corner_saturation"):
            try:
                corner_dicts = [c if isinstance(c, dict) else c.to_dict()
                                for c in corners]
                sats = _opt_mod.compute_corner_saturation(_optimal_result, corner_dicts)
                summary["optimal_v2"]["corner_saturation"] = [s.to_dict() for s in sats]
            except Exception:
                logger.debug("Corner saturation failed", exc_info=True)

        # Corner coaching labels
        _ca_mod = _import("corner_analysis")
        if _ca_mod is not None and corners and hasattr(_ca_mod, "compute_corner_coaching_labels"):
            try:
                corner_dicts = [c if isinstance(c, dict) else c.to_dict()
                                for c in corners]
                coaching_labels = _ca_mod.compute_corner_coaching_labels(
                    corners=corner_dicts,
                    limiting_factors=_optimal_result.limiting_factor,
                    distance_m=_optimal_result.distance_m,
                    lap_length_m=float(_optimal_result.distance_m[-1]),
                )
                summary["optimal_v2"]["corner_coaching_labels"] = coaching_labels
            except Exception:
                logger.debug("Corner coaching labels failed", exc_info=True)
```

**Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_optimal_pipeline.py telemetry_tool/tests/test_optimal_solver.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add telemetry_tool/pipeline.py
git commit -m "feat(pipeline): wire uncertainty bands, corner saturation, and coaching labels into optimal_v2"
```

---

### Task 7: Reporting — explainability panel + uncertainty sparkline + coaching columns

**Files:**
- Modify: `telemetry_tool/reporting_html.py`

**Step 1: Read reporting_html.py around `_build_grip_map_html()` (line 3252)**

Understand the SVG pattern used.

**Step 2: Add `_build_explainability_html()`**

Insert before `generate_report()`:

```python


def _build_explainability_html(optimal_v2: Optional[dict]) -> str:
    """Build HTML panel showing solver limiting factor breakdown."""
    if optimal_v2 is None:
        return ""

    lf_summary = optimal_v2.get("limiting_factor_summary", {})
    if not lf_summary:
        return ""

    total = sum(lf_summary.values())
    if total == 0:
        return ""

    colors = {
        "cornering": "#ef4444",   # red
        "braking": "#f59e0b",     # amber
        "traction": "#22c55e",    # green
        "cap": "#3b82f6",         # blue
    }

    # Stacked bar
    width = 500
    height = 30
    parts = [
        '<div class="section explainability-panel" style="margin: 16px 0;">',
        '<h3>Solver Limiting Factors</h3>',
        f'<svg viewBox="0 0 {width} {height}" '
        f'style="width: 100%; max-width: {width}px; height: {height}px;">',
    ]

    x = 0
    for factor in ("cornering", "braking", "traction", "cap"):
        count = lf_summary.get(factor, 0)
        w = (count / total) * width
        if w > 0:
            color = colors.get(factor, "#9ca3af")
            pct = round(100 * count / total)
            parts.append(
                f'<rect x="{x:.1f}" y="0" width="{w:.1f}" height="{height}" '
                f'fill="{color}" />'
            )
            if w > 30:
                parts.append(
                    f'<text x="{x + w / 2:.1f}" y="{height / 2 + 4}" '
                    f'text-anchor="middle" fill="white" font-size="11">'
                    f'{factor} {pct}%</text>'
                )
            x += w

    parts.append('</svg>')

    # Legend
    parts.append('<div style="margin-top: 8px; font-size: 0.85em;">')
    for factor in ("cornering", "braking", "traction", "cap"):
        count = lf_summary.get(factor, 0)
        pct = round(100 * count / total)
        if pct > 0:
            color = colors.get(factor, "#9ca3af")
            parts.append(
                f'<span style="display: inline-block; margin-right: 12px;">'
                f'<span style="display: inline-block; width: 10px; height: 10px; '
                f'background: {color}; margin-right: 4px;"></span>'
                f'{factor}: {pct}%</span>'
            )
    parts.append('</div>')

    # Corner saturation table
    sat_list = optimal_v2.get("corner_saturation", [])
    if sat_list:
        parts.append('<h4 style="margin-top: 12px;">Per-Corner Saturation</h4>')
        parts.append(
            '<table class="data-table" style="font-size: 0.85em;">'
            '<tr><th>Corner</th><th>Cornering</th><th>Traction</th>'
            '<th>Braking</th><th>Dominant</th><th>Sat. &gt;98%</th></tr>'
        )
        for sat in sat_list:
            parts.append(
                f'<tr><td>{sat.get("corner_id", "?")}</td>'
                f'<td>{sat.get("cornering_pct", 0) * 100:.0f}%</td>'
                f'<td>{sat.get("traction_pct", 0) * 100:.0f}%</td>'
                f'<td>{sat.get("braking_pct", 0) * 100:.0f}%</td>'
                f'<td><strong>{sat.get("dominant_factor", "?")}</strong></td>'
                f'<td>{sat.get("saturation_98pct", 0) * 100:.0f}%</td></tr>'
            )
        parts.append('</table>')

    parts.append('</div>')
    return "\n".join(parts)


def _build_uncertainty_html(optimal_v2: Optional[dict]) -> str:
    """Build HTML panel showing uncertainty bands."""
    if optimal_v2 is None:
        return ""

    v_low = optimal_v2.get("v_opt_low_mps", [])
    v_high = optimal_v2.get("v_opt_high_mps", [])
    v_opt = optimal_v2.get("v_opt_mps", [])
    distances = optimal_v2.get("distance_m", [])

    if not v_low or not v_high or not distances:
        return ""

    lap_time = optimal_v2.get("lap_time_s", 0)
    lap_low = optimal_v2.get("lap_time_low_s", 0)
    lap_high = optimal_v2.get("lap_time_high_s", 0)

    parts = [
        '<div class="section uncertainty-panel" style="margin: 16px 0;">',
        f'<h3>Uncertainty Bands</h3>',
        f'<p>Lap time: <strong>{lap_time:.2f}s</strong> '
        f'[{lap_low:.2f} – {lap_high:.2f}]</p>',
    ]

    # SVG sparkline with shaded band
    n = len(distances)
    width = 600
    height = 100
    d_min, d_max = distances[0], distances[-1]
    all_v = v_low + v_opt + v_high
    v_min = max(0, min(all_v) - 1)
    v_max_val = max(all_v) + 1

    def _sx(d):
        return (d - d_min) / max(1, d_max - d_min) * width

    def _sy(v):
        return height - (v - v_min) / max(0.01, v_max_val - v_min) * height

    # Band polygon (low → high, reversed)
    band_pts_fwd = " ".join(
        f"{_sx(distances[i]):.1f},{_sy(v_high[i]):.1f}" for i in range(n)
    )
    band_pts_rev = " ".join(
        f"{_sx(distances[n - 1 - i]):.1f},{_sy(v_low[n - 1 - i]):.1f}" for i in range(n)
    )
    band_polygon = f"{band_pts_fwd} {band_pts_rev}"

    # Nominal line
    nom_pts = " ".join(
        f"{_sx(distances[i]):.1f},{_sy(v_opt[i]):.1f}" for i in range(n)
    )

    parts.append(
        f'<svg viewBox="0 0 {width} {height}" '
        f'style="width: 100%; max-width: {width}px; height: {height}px; '
        f'background: rgba(0,0,0,0.02);">'
        f'<polygon points="{band_polygon}" fill="rgba(59,130,246,0.15)" />'
        f'<polyline points="{nom_pts}" fill="none" stroke="#3b82f6" stroke-width="1.5" />'
        f'</svg>'
    )

    parts.append('</div>')
    return "\n".join(parts)
```

**Step 3: Wire into `generate_report()`**

Add parameter `optimal_v2: Optional[dict[str, Any]] = None` to `generate_report()` signature.

In the report body assembly (find where `_build_grip_map_html` is called), add nearby:

```python
    sections.append(_build_explainability_html(optimal_v2))
    sections.append(_build_uncertainty_html(optimal_v2))
```

**Step 4: Update corner table to include coaching columns**

In `_build_corner_table_html()` (line 1779), extend the table header and rows to include `Priority` and `Why` columns. After extracting `hint`, add:

```python
        lf = _get(p, "limiting_factor", "")
        priority = _get(p, "corner_priority", "")
        coaching_txt = _get(p, "coaching_text", "")
```

Add to the header row `<th>Priority</th><th>Why</th>` and to each data row `<td>{priority}</td><td>{coaching_txt}</td>`.

**Step 5: Commit**

```bash
git add telemetry_tool/reporting_html.py
git commit -m "feat(report): add explainability panel, uncertainty sparkline, and coaching columns"
```

---

### Task 8: API extensions — optimal-v2, corners, speed-trace v2

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py`

**Step 1: Extend speed-trace v2 response with bands**

In the speed-trace endpoint (around line 391-406), extend the v2 response to include band arrays. Find the `if version == "v2":` block and add `speeds_low` and `speeds_high`:

```python
                return api_response({
                    "available": True,
                    "distances": opt.get("distance_m", []),
                    "speeds": opt["v_opt_mps"],
                    "speeds_low": opt.get("v_opt_low_mps", []),
                    "speeds_high": opt.get("v_opt_high_mps", []),
                    "lap_number": lap_num,
                    "lap_time_s": opt.get("lap_time_s"),
                    "lap_time_low_s": opt.get("lap_time_low_s"),
                    "lap_time_high_s": opt.get("lap_time_high_s"),
                    "solver_version": opt.get("solver_version"),
                    "version": "v2",
                })
```

**Step 2: Extend corners endpoint with coaching labels**

In the corners endpoint (around line 646), after building the merged corner list, check if coaching labels exist in analysis_json and merge them:

```python
    # -- 4. Merge coaching labels from optimal_v2 ---
    analysis = models.get_analysis_json(conn, session_id)
    coaching_labels = {}
    if analysis and isinstance(analysis, dict):
        opt = analysis.get("optimal_v2", {})
        for label in opt.get("corner_coaching_labels", []):
            coaching_labels[label.get("corner_id")] = label

    # Merge into each corner result
    for corner in merged_corners:
        cid = corner.get("corner_id")
        if cid in coaching_labels:
            cl = coaching_labels[cid]
            corner["limiting_factor"] = cl.get("limiting_factor", "")
            corner["corner_priority"] = cl.get("corner_priority", "")
            corner["coaching_text"] = cl.get("coaching_text", "")
```

**Step 3: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py
git commit -m "feat(api): extend speed-trace v2 with bands, corners with coaching labels"
```

---

## Summary

| Task | What | Tests |
|------|------|-------|
| 1 | Per-point limiting_factor in solve_optimal_speed() | 2 |
| 2 | CornerSaturation + compute_corner_saturation() | 1 |
| 3 | solve_optimal_speed_with_bands() + OptimalResultWithBands | 2 |
| 4 | Cap producer low/high variants | 2 |
| 5 | Corner coaching labels + templates + priority logic | 4 |
| 6 | Pipeline wiring for bands + saturation + coaching | 0 (existing pipeline tests) |
| 7 | Reporting panels (explainability, uncertainty, coaching columns) | 0 (visual) |
| 8 | API extensions | 0 (existing API tests) |
| **Total** | | **11 new tests** |
