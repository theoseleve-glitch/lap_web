# Unified Optimal Lap Engine Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Unify three theoretical speed-trace paths into a single canonical forward-backward solver with shared input contract, per-point provenance, and migration-safe rollout via feature flag.

**Architecture:** New `optimal_solver.py` defines `OptimalCaps` (unified input) and `OptimalResult` (unified output). Each existing cap source (percentile envelope, physics simulation, kart adapter) produces `OptimalCaps`. A shared `solve_optimal_speed()` runs the forward-backward feasibility pass. Pipeline stage 10 gains an optional `optimal_v2` path behind a feature flag. DB and API expose the new result without breaking existing endpoints.

**Tech Stack:** Python 3.x, NumPy, pandas, pytest

---

### Task 1: OptimalCaps + OptimalResult dataclasses + solve_optimal_speed()

**Files:**
- Create: `telemetry_tool/optimal_solver.py`
- Create: `telemetry_tool/tests/test_optimal_solver.py`

**Step 1: Write the failing tests**

In `telemetry_tool/tests/test_optimal_solver.py`:

```python
"""Tests for unified optimal lap solver."""
import math
import numpy as np
import pandas as pd
import pytest


def test_optimal_caps_fields():
    """OptimalCaps has all required fields and to_dict()."""
    from optimal_solver import OptimalCaps

    n = 100
    caps = OptimalCaps(
        distance_m=np.linspace(0, 500, n),
        v_cap=np.full(n, 30.0),
        ax_accel=np.full(n, 5.0),
        ax_brake=np.full(n, 8.0),
        curvature=np.full(n, 0.01),
        mu=np.full(n, 1.0),
        cap_source=["envelope_p98"] * n,
        solver_version="optimal_v2_1.0",
    )
    assert len(caps.distance_m) == n
    assert caps.solver_version == "optimal_v2_1.0"
    d = caps.to_dict()
    assert "solver_version" in d
    assert "cap_source_summary" in d


def test_optimal_result_fields():
    """OptimalResult has all required fields and to_dict()."""
    from optimal_solver import OptimalResult

    n = 100
    r = OptimalResult(
        distance_m=np.linspace(0, 500, n),
        v_opt_mps=np.full(n, 25.0),
        accel_profile_mps2=np.zeros(n),
        lap_time_s=20.0,
        cornering_limited=np.zeros(n, dtype=bool),
        accel_limited=np.zeros(n, dtype=bool),
        brake_limited=np.zeros(n, dtype=bool),
        cap_source=["envelope_p98"] * n,
        solver_version="optimal_v2_1.0",
        n_iterations=3,
    )
    assert r.lap_time_s == 20.0
    d = r.to_dict()
    assert "v_opt_mps" in d
    assert "lap_time_s" in d


def test_solve_straight_track():
    """Straight track (zero curvature) → speed limited by v_cap and accel."""
    from optimal_solver import OptimalCaps, solve_optimal_speed

    n = 200
    dist = np.linspace(0, 1000, n)
    caps = OptimalCaps(
        distance_m=dist,
        v_cap=np.full(n, 50.0),
        ax_accel=np.full(n, 5.0),
        ax_brake=np.full(n, 8.0),
        curvature=np.zeros(n),  # straight
        mu=np.full(n, 1.5),
        cap_source=["test"] * n,
        solver_version="test",
    )
    result = solve_optimal_speed(caps)

    assert result.lap_time_s > 0
    assert result.lap_time_s < 100  # reasonable
    assert np.all(result.v_opt_mps >= 0)
    assert np.all(result.v_opt_mps <= 50.0 + 0.1)  # respect v_cap


def test_solve_corner_slows_down():
    """Track with one tight corner → speed dips at corner."""
    from optimal_solver import OptimalCaps, solve_optimal_speed

    n = 200
    dist = np.linspace(0, 500, n)
    curvature = np.zeros(n)
    # Tight corner in the middle (radius = 20m, curvature = 0.05)
    mid = n // 2
    curvature[mid - 10:mid + 10] = 0.05

    caps = OptimalCaps(
        distance_m=dist,
        v_cap=np.full(n, 40.0),
        ax_accel=np.full(n, 5.0),
        ax_brake=np.full(n, 8.0),
        curvature=curvature,
        mu=np.full(n, 1.0),
        cap_source=["test"] * n,
        solver_version="test",
    )
    result = solve_optimal_speed(caps)

    # Speed at the corner should be lower than on the straights
    corner_speed = np.mean(result.v_opt_mps[mid - 5:mid + 5])
    straight_speed = np.mean(result.v_opt_mps[:20])
    assert corner_speed < straight_speed * 0.8

    # Some points should be cornering-limited
    assert result.cornering_limited[mid]


def test_same_caps_same_result():
    """Same OptimalCaps → identical v_opt regardless of how caps were built."""
    from optimal_solver import OptimalCaps, solve_optimal_speed

    n = 100
    dist = np.linspace(0, 500, n)
    curvature = np.zeros(n)
    curvature[40:60] = 0.03  # corner

    caps1 = OptimalCaps(
        distance_m=dist,
        v_cap=np.full(n, 35.0),
        ax_accel=np.full(n, 4.0),
        ax_brake=np.full(n, 7.0),
        curvature=curvature,
        mu=np.full(n, 1.2),
        cap_source=["envelope_p98"] * n,
        solver_version="v1",
    )
    caps2 = OptimalCaps(
        distance_m=dist.copy(),
        v_cap=np.full(n, 35.0),
        ax_accel=np.full(n, 4.0),
        ax_brake=np.full(n, 7.0),
        curvature=curvature.copy(),
        mu=np.full(n, 1.2),
        cap_source=["physics_hybrid"] * n,  # different source label
        solver_version="v2",  # different version label
    )

    r1 = solve_optimal_speed(caps1)
    r2 = solve_optimal_speed(caps2)

    # Physics must be identical — only provenance differs
    np.testing.assert_allclose(r1.v_opt_mps, r2.v_opt_mps, atol=1e-10)
    assert abs(r1.lap_time_s - r2.lap_time_s) < 1e-10


def test_solve_no_mu_uses_v_cap_only():
    """When mu is None, cornering limit comes only from v_cap."""
    from optimal_solver import OptimalCaps, solve_optimal_speed

    n = 100
    dist = np.linspace(0, 500, n)
    v_cap = np.full(n, 30.0)
    v_cap[40:60] = 15.0  # pre-computed corner speed cap

    caps = OptimalCaps(
        distance_m=dist,
        v_cap=v_cap,
        ax_accel=np.full(n, 5.0),
        ax_brake=np.full(n, 8.0),
        curvature=np.full(n, 0.02),  # curvature present but no mu
        mu=None,
        cap_source=["test"] * n,
        solver_version="test",
    )
    result = solve_optimal_speed(caps)

    # Corner speed should respect v_cap
    assert np.all(result.v_opt_mps[40:60] <= 15.0 + 0.1)
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_optimal_solver.py -v`
Expected: FAIL

**Step 3: Write implementation**

In `telemetry_tool/optimal_solver.py`:

```python
"""
optimal_solver.py
-----------------
Unified forward-backward feasibility solver for optimal lap speed.

Defines a canonical input contract (OptimalCaps) and output schema
(OptimalResult). All cap sources (percentile envelope, physics model,
kart_envelope adapter) produce OptimalCaps; the shared solver
produces a single canonical v_opt(s).

Deterministic: same OptimalCaps always produces same v_opt.
"""
from __future__ import annotations

import logging
import math
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)

_G: float = 9.80665
_SOLVER_VERSION: str = "optimal_v2_1.0"
_MIN_SPEED_MPS: float = 1.0
_MAX_ITERATIONS: int = 5


@dataclass
class OptimalCaps:
    """Unified input contract for the optimal solver.

    All cap sources fill this structure — the solver treats them identically.
    """
    distance_m: np.ndarray        # distance grid [m]
    v_cap: np.ndarray             # max speed at each point [m/s]
    ax_accel: np.ndarray          # max traction accel [m/s^2] per point
    ax_brake: np.ndarray          # max braking decel [m/s^2] per point (positive)
    curvature: np.ndarray         # curvature [1/m] at each point
    mu: np.ndarray | None         # friction coeff per point (None = use v_cap only)
    cap_source: list[str]         # per-point provenance tag
    solver_version: str = _SOLVER_VERSION

    def to_dict(self) -> dict:
        source_counts = dict(Counter(self.cap_source))
        return {
            "n_points": len(self.distance_m),
            "lap_length_m": round(float(self.distance_m[-1] - self.distance_m[0]), 1)
                if len(self.distance_m) > 1 else 0.0,
            "v_cap_mean": round(float(np.mean(self.v_cap)), 2),
            "ax_accel_mean": round(float(np.mean(self.ax_accel)), 2),
            "ax_brake_mean": round(float(np.mean(self.ax_brake)), 2),
            "has_mu": self.mu is not None,
            "cap_source_summary": source_counts,
            "solver_version": self.solver_version,
        }


@dataclass
class OptimalResult:
    """Canonical output from the optimal solver."""
    distance_m: np.ndarray
    v_opt_mps: np.ndarray           # optimal speed trace
    accel_profile_mps2: np.ndarray  # longitudinal accel at each point
    lap_time_s: float
    cornering_limited: np.ndarray   # bool per point
    accel_limited: np.ndarray       # bool per point
    brake_limited: np.ndarray       # bool per point
    cap_source: list[str]           # from OptimalCaps
    solver_version: str
    n_iterations: int

    def to_dict(self) -> dict:
        source_counts = dict(Counter(self.cap_source))
        n = len(self.v_opt_mps)
        return {
            "distance_m": np.round(self.distance_m, 2).tolist(),
            "v_opt_mps": np.round(self.v_opt_mps, 4).tolist(),
            "lap_time_s": round(self.lap_time_s, 4),
            "solver_version": self.solver_version,
            "cap_source_summary": source_counts,
            "cornering_limited_frac": round(float(self.cornering_limited.mean()), 4)
                if n > 0 else 0.0,
            "accel_limited_frac": round(float(self.accel_limited.mean()), 4)
                if n > 0 else 0.0,
            "brake_limited_frac": round(float(self.brake_limited.mean()), 4)
                if n > 0 else 0.0,
            "n_iterations": self.n_iterations,
        }

    def to_theoretical_df(self) -> "pd.DataFrame":
        """Convert to the legacy pipeline DataFrame format."""
        import pandas as pd
        accel = self.accel_profile_mps2.copy()
        accel_pos = np.where(accel > 0, accel, 0.0)
        brake_pos = np.where(accel < 0, np.abs(accel), 0.0)
        return pd.DataFrame({
            "distance_m": self.distance_m,
            "v_env_mps": self.v_opt_mps,
            "accel_max_mps2": accel_pos,
            "brake_max_mps2": brake_pos,
        })


def solve_optimal_speed(caps: OptimalCaps) -> OptimalResult:
    """Run forward-backward feasibility solver on unified caps.

    Deterministic: same OptimalCaps always produces same v_opt.

    Algorithm
    ---------
    1. Cornering pass: v_corner = min(v_cap, sqrt(mu*g / |curvature|))
    2. Forward pass: v[i+1] = sqrt(v[i]^2 + 2*ax_accel*ds), capped by v_corner
    3. Backward pass: v[i] = sqrt(v[i+1]^2 + 2*ax_brake*ds), capped by v_corner
    4. v_opt = min(forward, backward, v_corner)
    5. Iterate for closed-loop convergence

    Parameters
    ----------
    caps : OptimalCaps — unified input contract

    Returns
    -------
    OptimalResult with canonical v_opt(s).
    """
    n = len(caps.distance_m)
    if n < 2:
        return OptimalResult(
            distance_m=caps.distance_m,
            v_opt_mps=caps.v_cap.copy(),
            accel_profile_mps2=np.zeros(n),
            lap_time_s=0.0,
            cornering_limited=np.ones(n, dtype=bool),
            accel_limited=np.zeros(n, dtype=bool),
            brake_limited=np.zeros(n, dtype=bool),
            cap_source=caps.cap_source,
            solver_version=caps.solver_version,
            n_iterations=0,
        )

    dist = caps.distance_m
    ds = np.diff(dist)

    # Step 1: Cornering speed limit
    v_corner = caps.v_cap.copy()
    if caps.mu is not None:
        for i in range(n):
            kappa = abs(caps.curvature[i])
            if kappa > 1e-6:
                v_mu = math.sqrt(caps.mu[i] * _G / kappa)
                v_corner[i] = min(v_corner[i], v_mu)
    v_corner = np.clip(v_corner, _MIN_SPEED_MPS, None)

    # Iterate forward-backward for convergence
    v_opt = v_corner.copy()
    n_iter = 0

    for iteration in range(_MAX_ITERATIONS):
        n_iter = iteration + 1
        v_prev = v_opt.copy()

        # Step 2: Forward pass (acceleration limited)
        v_fwd = v_corner.copy()
        for i in range(n - 1):
            a_max = caps.ax_accel[i]
            v_next_sq = v_fwd[i] ** 2 + 2.0 * a_max * ds[i]
            if v_next_sq > 0:
                v_fwd[i + 1] = min(v_corner[i + 1], math.sqrt(v_next_sq))
            else:
                v_fwd[i + 1] = _MIN_SPEED_MPS

        # Step 3: Backward pass (braking limited)
        v_bwd = v_corner.copy()
        for i in range(n - 2, -1, -1):
            b_max = caps.ax_brake[i + 1]
            v_prev_sq = v_bwd[i + 1] ** 2 + 2.0 * b_max * ds[i]
            if v_prev_sq > 0:
                v_bwd[i] = min(v_corner[i], math.sqrt(v_prev_sq))
            else:
                v_bwd[i] = _MIN_SPEED_MPS

        # Step 4: v_opt = min(forward, backward, v_corner)
        v_opt = np.minimum(np.minimum(v_fwd, v_bwd), v_corner)
        v_opt = np.clip(v_opt, _MIN_SPEED_MPS, None)

        # Convergence check
        if np.max(np.abs(v_opt - v_prev)) < 0.001:
            break

    # Compute accel profile from v_opt
    accel_profile = np.zeros(n)
    for i in range(n - 1):
        if ds[i] > 0:
            accel_profile[i] = (v_opt[i + 1] ** 2 - v_opt[i] ** 2) / (2.0 * ds[i])
    accel_profile[-1] = accel_profile[-2] if n > 1 else 0.0

    # Classify limiting constraints
    tol = 0.5  # m/s tolerance
    cornering_limited = np.abs(v_opt - v_corner) < tol
    accel_limited = np.abs(v_opt - v_fwd) < tol
    brake_limited = np.abs(v_opt - v_bwd) < tol

    # Lap time via trapezoidal integration
    inv_v = 1.0 / np.clip(v_opt, _MIN_SPEED_MPS, None)
    dt = 0.5 * (inv_v[:-1] + inv_v[1:]) * np.abs(ds)
    lap_time = float(np.sum(dt))

    logger.info(
        "Optimal solver: %.2fs, %d iterations, %.0f%% corner / "
        "%.0f%% accel / %.0f%% brake limited.",
        lap_time, n_iter,
        100 * cornering_limited.mean(),
        100 * accel_limited.mean(),
        100 * brake_limited.mean(),
    )

    return OptimalResult(
        distance_m=dist,
        v_opt_mps=v_opt,
        accel_profile_mps2=accel_profile,
        lap_time_s=lap_time,
        cornering_limited=cornering_limited,
        accel_limited=accel_limited,
        brake_limited=brake_limited,
        cap_source=caps.cap_source,
        solver_version=caps.solver_version,
        n_iterations=n_iter,
    )
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_optimal_solver.py -v`
Expected: 6 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/optimal_solver.py telemetry_tool/tests/test_optimal_solver.py
git commit -m "feat(optimal): add OptimalCaps, OptimalResult, and solve_optimal_speed() forward-backward solver"
```

---

### Task 2: caps_from_percentile_envelope()

**Files:**
- Modify: `telemetry_tool/theoretical_engine.py` (append)
- Modify: `telemetry_tool/tests/test_optimal_solver.py` (append)

**Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_optimal_solver.py`:

```python


def test_caps_from_percentile_envelope():
    """Percentile envelope produces valid OptimalCaps."""
    from theoretical_engine import caps_from_percentile_envelope

    rng = np.random.default_rng(42)
    n_points = 200
    laps = []
    for _ in range(8):
        dist = np.linspace(0, 500, n_points)
        speed = np.full(n_points, 20.0) + rng.normal(0, 1.0, n_points)
        speed = np.clip(speed, 5.0, 40.0)
        laps.append(pd.DataFrame({
            "Distance (m)": dist,
            "Speed (m/s)": speed,
            "accel_long_mps2": rng.normal(0, 2.0, n_points),
        }))

    curvature = np.full(n_points, 0.005)
    caps = caps_from_percentile_envelope(laps, curvature)

    assert len(caps.distance_m) == n_points
    assert np.all(caps.v_cap > 0)
    assert np.all(caps.ax_accel > 0)
    assert np.all(caps.ax_brake > 0)
    assert all(s == "envelope_p98" for s in caps.cap_source)
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_optimal_solver.py::test_caps_from_percentile_envelope -v`
Expected: FAIL

**Step 3: Write implementation**

Append to `telemetry_tool/theoretical_engine.py`:

```python


def caps_from_percentile_envelope(
    laps: list[pd.DataFrame],
    curvature: np.ndarray,
    speed_percentile: float = 98.0,
    accel_percentile: float = 99.0,
    smooth_window: int = 5,
) -> "OptimalCaps":
    """Build OptimalCaps from percentile envelope extraction.

    Parameters
    ----------
    laps : list of lap DataFrames
    curvature : curvature array [1/m] aligned with distance grid
    speed_percentile : percentile for speed envelope
    accel_percentile : percentile for accel envelope

    Returns
    -------
    OptimalCaps ready for solve_optimal_speed().
    """
    from optimal_solver import OptimalCaps

    # Speed envelope
    env_df = compute_speed_percentile_envelope(
        laps, percentile=speed_percentile, smooth_window=smooth_window,
    )
    distance = env_df["distance_m"].values
    v_cap = env_df["v_env_mps"].values
    n = len(distance)

    # Ensure curvature aligns
    if len(curvature) != n:
        curv_aligned = np.interp(
            distance,
            np.linspace(distance[0], distance[-1], len(curvature)),
            curvature,
        )
    else:
        curv_aligned = curvature

    # Accel envelope
    accel_env = compute_accel_envelope(
        laps, percentile=accel_percentile, smooth_window=smooth_window,
    )
    # Sample at each speed point
    ax_accel = np.abs(accel_env.accel_func(v_cap))
    ax_brake = np.abs(accel_env.brake_func(v_cap))

    # Ensure positive
    ax_accel = np.clip(ax_accel, 0.5, 20.0)
    ax_brake = np.clip(ax_brake, 0.5, 30.0)

    return OptimalCaps(
        distance_m=distance,
        v_cap=np.clip(v_cap, 1.0, 100.0),
        ax_accel=ax_accel,
        ax_brake=ax_brake,
        curvature=np.abs(curv_aligned),
        mu=None,  # percentile envelope already bakes in grip
        cap_source=[f"envelope_p{int(speed_percentile)}"] * n,
        solver_version="optimal_v2_1.0",
    )
```

**Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_optimal_solver.py -v`
Expected: 7 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/theoretical_engine.py telemetry_tool/tests/test_optimal_solver.py
git commit -m "feat(optimal): add caps_from_percentile_envelope() to theoretical_engine"
```

---

### Task 3: caps_from_vehicle_model()

**Files:**
- Modify: `telemetry_tool/lap_simulation.py` (append)
- Modify: `telemetry_tool/tests/test_optimal_solver.py` (append)

**Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_optimal_solver.py`:

```python


def test_caps_from_vehicle_model():
    """Physics vehicle model produces valid OptimalCaps."""
    from lap_simulation import caps_from_vehicle_model

    n = 200
    dist = np.linspace(0, 500, n)
    curvature = np.zeros(n)
    curvature[80:120] = 0.02  # corner

    caps = caps_from_vehicle_model(
        distance_m=dist,
        curvature=curvature,
        traction_mps2=5.0,
        braking_mps2=8.0,
        mu=1.2,
        v_max_mps=40.0,
    )

    assert len(caps.distance_m) == n
    assert np.all(caps.ax_accel > 0)
    assert np.all(caps.ax_brake > 0)
    assert caps.mu is not None
    assert all("physics" in s for s in caps.cap_source)

    # Corner speeds should be lower than straight speeds
    corner_cap = np.mean(caps.v_cap[90:110])
    straight_cap = np.mean(caps.v_cap[:20])
    assert corner_cap < straight_cap
```

**Step 2: Run test to verify it fails**

**Step 3: Write implementation**

Append to `telemetry_tool/lap_simulation.py`:

```python


def caps_from_vehicle_model(
    *,
    distance_m: np.ndarray,
    curvature: np.ndarray,
    traction_mps2: float,
    braking_mps2: float,
    mu: float,
    v_max_mps: float = 80.0,
    grip_map: "GripMap | None" = None,
) -> "OptimalCaps":
    """Build OptimalCaps from physics vehicle model parameters.

    Parameters
    ----------
    distance_m : distance grid [m]
    curvature : curvature [1/m] at each point
    traction_mps2 : max traction accel [m/s^2]
    braking_mps2 : max braking decel [m/s^2]
    mu : global friction coefficient
    v_max_mps : max vehicle speed [m/s]
    grip_map : optional per-distance grip map (overrides mu)

    Returns
    -------
    OptimalCaps ready for solve_optimal_speed().
    """
    from optimal_solver import OptimalCaps

    n = len(distance_m)

    # Per-point mu
    mu_arr = np.full(n, mu)
    if grip_map is not None and not grip_map.is_global_fallback:
        for i in range(n):
            mu_arr[i] = grip_map.mu_at(float(distance_m[i]), "p95")

    # Cornering speed cap: v = sqrt(mu * g / |curvature|)
    v_cap = np.full(n, v_max_mps)
    for i in range(n):
        kappa = abs(curvature[i])
        if kappa > 1e-6:
            v_corner = math.sqrt(mu_arr[i] * _G / kappa)
            v_cap[i] = min(v_cap[i], v_corner)

    return OptimalCaps(
        distance_m=distance_m,
        v_cap=np.clip(v_cap, 1.0, v_max_mps),
        ax_accel=np.full(n, traction_mps2),
        ax_brake=np.full(n, braking_mps2),
        curvature=np.abs(curvature),
        mu=mu_arr,
        cap_source=["physics_model"] * n,
        solver_version="optimal_v2_1.0",
    )
```

**Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_optimal_solver.py -v`
Expected: 8 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/lap_simulation.py telemetry_tool/tests/test_optimal_solver.py
git commit -m "feat(optimal): add caps_from_vehicle_model() to lap_simulation"
```

---

### Task 4: caps_from_kart_envelope()

**Files:**
- Modify: `telemetry_tool/theoretical_adapter.py` (append)
- Modify: `telemetry_tool/tests/test_optimal_solver.py` (append)

**Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_optimal_solver.py`:

```python


def test_caps_from_kart_envelope_fallback():
    """caps_from_kart_envelope() returns None when kart_envelope not installed."""
    from theoretical_adapter import caps_from_kart_envelope

    # With no kart_envelope available, should return None gracefully
    result = caps_from_kart_envelope(
        resampled_laps={},
        curvature_profile=None,
    )
    assert result is None
```

**Step 2: Write implementation**

Append to `telemetry_tool/theoretical_adapter.py`:

```python


def caps_from_kart_envelope(
    resampled_laps: dict[int, pd.DataFrame],
    curvature_profile: pd.DataFrame | None,
    *,
    vehicle_params: Any = None,
    config: Any = None,
) -> "OptimalCaps | None":
    """Build OptimalCaps from kart_envelope training.

    Returns None if kart_envelope is not available or curvature_profile is missing.

    Parameters
    ----------
    resampled_laps : lap data
    curvature_profile : curvature from reference line
    vehicle_params : optional vehicle parameters
    config : optional KartEnvelopeConfig

    Returns
    -------
    OptimalCaps or None if unavailable.
    """
    if curvature_profile is None or not resampled_laps:
        return None

    try:
        from kart_envelope.config import default_config as _default_config
        from kart_envelope.envelope.capability import train_capability_envelope
        from kart_envelope.inference.session_scalars import infer_session_scalars
    except ImportError:
        logger.debug("kart_envelope not installed; caps_from_kart_envelope unavailable.")
        return None

    try:
        from optimal_solver import OptimalCaps

        cfg = config if config is not None else _default_config()

        # Map columns
        mapped_laps = {k: _map_columns_to_canonical(v) for k, v in resampled_laps.items()}

        # Build geometry
        geometry = _build_geometry_from_curvature(curvature_profile)

        # Train envelope
        envelope = train_capability_envelope(sessions=[mapped_laps], config=cfg)

        # Infer session scalars
        scalars = infer_session_scalars(
            resampled_laps=mapped_laps, envelope=envelope, config=cfg,
        )

        # Extract caps from envelope
        dist = geometry.distance_m
        n = len(dist)
        curvature = geometry.curvature_1pm

        # Speed cap from envelope + geometry
        v_cap = np.full(n, 80.0)
        mu = scalars.mu_session
        for i in range(n):
            kappa = abs(curvature[i])
            if kappa > 1e-6:
                v_cap[i] = min(v_cap[i], math.sqrt(mu * _G / kappa))

        # Accel/brake from envelope
        v_sample = np.clip(v_cap, 1.0, 80.0)
        ax_accel = np.abs(envelope.traction_max(v_sample))
        ax_brake = np.abs(envelope.braking_max(v_sample))
        ax_accel = np.clip(ax_accel, 0.5, 20.0)
        ax_brake = np.clip(ax_brake, 0.5, 30.0)

        return OptimalCaps(
            distance_m=dist,
            v_cap=np.clip(v_cap, 1.0, 80.0),
            ax_accel=ax_accel,
            ax_brake=ax_brake,
            curvature=np.abs(curvature),
            mu=np.full(n, mu),
            cap_source=["kart_qss"] * n,
            solver_version="optimal_v2_1.0",
        )
    except Exception as exc:
        logger.warning("caps_from_kart_envelope failed: %s", exc)
        return None
```

**Step 3: Run tests**

Run: `pytest telemetry_tool/tests/test_optimal_solver.py -v`
Expected: 9 PASSED

**Step 4: Commit**

```bash
git add telemetry_tool/theoretical_adapter.py telemetry_tool/tests/test_optimal_solver.py
git commit -m "feat(optimal): add caps_from_kart_envelope() to theoretical_adapter"
```

---

### Task 5: Pipeline integration with feature flag

**Files:**
- Modify: `telemetry_tool/pipeline.py`
- Create: `telemetry_tool/tests/test_optimal_pipeline.py`

**Step 1: Write the integration test**

In `telemetry_tool/tests/test_optimal_pipeline.py`:

```python
"""Integration tests for unified optimal solver in pipeline."""
import os
import numpy as np
import pandas as pd
import pytest


def _make_test_csv(tmp_path, n_laps=8):
    """Create CSV for pipeline integration."""
    rng = np.random.default_rng(42)
    frames = []
    n_per_lap = 200

    for lap in range(1, n_laps + 1):
        t_start = (lap - 1) * 30.0
        t = np.linspace(t_start, t_start + 25.0, n_per_lap)
        dist = np.linspace(0, 500, n_per_lap)
        speed = np.full(n_per_lap, 20.0) + rng.normal(0, 0.5, n_per_lap)
        lat = np.linspace(45.0, 45.002, n_per_lap) + rng.normal(0, 1e-5, n_per_lap)
        lon = np.linspace(9.0, 9.002, n_per_lap) + rng.normal(0, 1e-5, n_per_lap)

        df = pd.DataFrame({
            "Lap #": np.full(n_per_lap, lap),
            "Time (s)": t,
            "Distance (m)": dist + (lap - 1) * 500,
            "Speed (m/s)": speed,
            "Latitude (deg)": lat,
            "Longitude (deg)": lon,
            "Bearing (deg)": np.full(n_per_lap, 90.0) + rng.normal(0, 1, n_per_lap),
            "Longitudinal acceleration (G) *calc": rng.normal(0, 0.02, n_per_lap),
            "Lateral acceleration (G) *calc": rng.normal(0, 0.3, n_per_lap) * 1.2,
        })
        frames.append(df)

    full_df = pd.concat(frames, ignore_index=True)
    csv_path = tmp_path / "optimal_test.csv"
    full_df.to_csv(csv_path, index=False)
    return csv_path


def test_optimal_v2_off_by_default(tmp_path):
    """With OPTIMAL_V2 unset, summary has no optimal_v2 key."""
    import pipeline

    os.environ.pop("OPTIMAL_V2", None)  # ensure OFF
    csv_path = _make_test_csv(tmp_path)
    summary = pipeline.run_full_analysis(str(csv_path), {})

    # Legacy theoretical_metrics should exist
    assert "theoretical_metrics" in summary
    # optimal_v2 should NOT exist when flag is off
    assert summary.get("optimal_v2") is None


def test_optimal_v2_on_produces_result(tmp_path):
    """With OPTIMAL_V2=1, summary gains optimal_v2 alongside legacy."""
    import pipeline

    os.environ["OPTIMAL_V2"] = "1"
    try:
        csv_path = _make_test_csv(tmp_path)
        summary = pipeline.run_full_analysis(str(csv_path), {})

        # Legacy still present
        assert "theoretical_metrics" in summary

        # New optimal_v2 should be present
        opt = summary.get("optimal_v2")
        assert opt is not None
        assert "v_opt_mps" in opt
        assert "lap_time_s" in opt
        assert "solver_version" in opt
        assert opt["solver_version"].startswith("optimal_v2")
        assert "cap_source_summary" in opt
    finally:
        os.environ.pop("OPTIMAL_V2", None)
```

**Step 2: Read pipeline.py to find insertion point**

Find the end of stage 10b (after confidence attachment) and before stage 10c. Insert stage 10b-iii.

**Step 3: Add optimal_v2 stage to pipeline**

After confidence attachment (around where `summary["theoretical_metrics"] = theo_metrics` is set), insert:

```python
    # ── 10b-iii: Unified optimal solver (feature flag) ──
    _opt_mod = _import("optimal_solver")

    def _compute_optimal_v2():
        if _opt_mod is None:
            return None
        if os.environ.get("OPTIMAL_V2", "0") not in ("1", "true", "yes"):
            return None
        if theoretical_lap is None:
            return None

        # Build OptimalCaps from whichever path produced the theoretical lap
        caps = None

        # Try percentile envelope caps (most common path)
        if theo_mod is not None and resampled_laps:
            try:
                curv_arr = np.zeros(len(theoretical_lap))
                if curvature_profile is not None and "curvature_1pm" in curvature_profile.columns:
                    cp_dist = curvature_profile["distance_m"].values
                    cp_curv = curvature_profile["curvature_1pm"].values
                    theo_dist = theoretical_lap["distance_m"].values
                    curv_arr = np.interp(theo_dist, cp_dist, cp_curv)

                laps_list = [resampled_laps[k] for k in sorted(resampled_laps.keys())]
                if hasattr(theo_mod, "caps_from_percentile_envelope"):
                    caps = theo_mod.caps_from_percentile_envelope(
                        laps_list, curv_arr,
                        speed_percentile=speed_pct,
                    )
            except Exception as exc:
                logger.debug("caps_from_percentile_envelope failed: %s", exc)

        if caps is None:
            return None

        # Apply grip map override
        if _grip_map is not None and not _grip_map.is_global_fallback and caps.mu is None:
            mu_arr = np.array([
                _grip_map.mu_at(float(d), "p95") for d in caps.distance_m
            ])
            caps.mu = mu_arr
            caps.cap_source = ["grip_map" if mu_arr[i] != caps.v_cap[i]
                               else caps.cap_source[i] for i in range(len(mu_arr))]

        return _opt_mod.solve_optimal_speed(caps)

    _optimal_result, err = _safe_step("10b_optimal_v2", _compute_optimal_v2)
    _record("10b_optimal_v2", _optimal_result, err)

    if _optimal_result is not None:
        summary["optimal_v2"] = _optimal_result.to_dict()
    else:
        summary["optimal_v2"] = None
```

Also add `import os` at the top of the function if not already present (it's likely already imported at module level).

**Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_optimal_pipeline.py telemetry_tool/tests/test_optimal_solver.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add telemetry_tool/pipeline.py telemetry_tool/tests/test_optimal_pipeline.py
git commit -m "feat(optimal): integrate unified solver into pipeline with OPTIMAL_V2 feature flag"
```

---

### Task 6: API endpoint + DB persistence

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py`

**Step 1: Read data_v2.py**

Find the speed-trace endpoint and scores endpoint.

**Step 2: Add optimal_v2 endpoint**

```python
@bp.route("/sessions/<int:session_id>/optimal-v2", methods=["GET"])
def get_optimal_v2(session_id):
    """Return unified optimal speed trace (v2 solver)."""
    conn = _get_conn()
    summary = models.get_session_summary(conn, session_id)
    if summary is None:
        return api_error("Session not found", 404)

    opt = summary.get("optimal_v2")
    if opt is None:
        return api_error("Optimal V2 not available — enable OPTIMAL_V2 flag", 404)

    return api_success(opt)
```

Add `optimal_v2_available` flag to scores endpoint.

**Step 3: Add version parameter to speed-trace endpoint**

Find the speed-trace endpoint. Add `?version=v2` support:

```python
    version = request.args.get("version", "v1")
    if version == "v2":
        opt = summary.get("optimal_v2")
        if opt and "v_opt_mps" in opt:
            return api_success({
                "distance": opt.get("distance_m", []),
                "theoretical_speed": opt["v_opt_mps"],
                "lap_time_s": opt.get("lap_time_s"),
                "solver_version": opt.get("solver_version"),
            })
```

**Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_optimal_solver.py telemetry_tool/tests/test_optimal_pipeline.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py
git commit -m "feat(api): add optimal-v2 endpoint and version parameter on speed-trace"
```

---

## Summary

| Task | What | Tests |
|------|------|-------|
| 1 | OptimalCaps + OptimalResult + solve_optimal_speed() | 6 |
| 2 | caps_from_percentile_envelope() | 1 |
| 3 | caps_from_vehicle_model() | 1 |
| 4 | caps_from_kart_envelope() | 1 |
| 5 | Pipeline integration + feature flag | 2 |
| 6 | API endpoint + DB persistence | 0 (existing) |
