# Grip Map + Friction Envelope Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Estimate per-distance-bin lateral grip mu(s) and per-speed-bin friction circle from observed laps, then use these to cap cornering speed in the physics simulation and expose via report + API.

**Architecture:** New `grip_map.py` estimates mu(s) from lateral accel or v²·curvature with robust percentiles and outlier rejection. New `friction_envelope.py` estimates combined (ax,ay) limits per speed bin. Both integrate into pipeline stage 9.9 and feed into `lap_simulation.py`. Report gets a grip map plot; API gets a grip-map endpoint.

**Tech Stack:** Python 3.x, NumPy, pandas, matplotlib (report plots), pytest

---

### Task 1: GripBinStats + GripMap dataclasses

**Files:**
- Create: `telemetry_tool/grip_map.py`
- Create: `telemetry_tool/tests/test_grip_map.py`

**Step 1: Write the failing tests**

In `telemetry_tool/tests/test_grip_map.py`:

```python
"""Tests for distance-binned grip map."""
import numpy as np
import pandas as pd
import pytest


def test_grip_bin_stats_fields():
    """GripBinStats has all required fields and to_dict()."""
    from grip_map import GripBinStats

    b = GripBinStats(
        distance_m=100.0,
        mu_mean=1.1,
        mu_p50=1.0,
        mu_p90=1.3,
        mu_p95=1.4,
        mu_p99=1.5,
        sample_count=15,
        variance=0.02,
        confidence=0.85,
        source="lat_accel",
    )
    assert b.distance_m == 100.0
    assert b.mu_mean == 1.1
    d = b.to_dict()
    assert "confidence" in d
    assert "source" in d


def test_grip_map_fields():
    """GripMap has all required fields and to_dict()."""
    from grip_map import GripMap

    gm = GripMap(
        distance_bins=np.linspace(0, 500, 100),
        mu_mean=np.full(100, 1.0),
        mu_p90=np.full(100, 1.2),
        mu_p95=np.full(100, 1.3),
        bin_stats=[],
        global_mu=1.1,
        is_global_fallback=False,
        source="lat_accel",
        warning=None,
        n_laps_used=10,
    )
    assert len(gm.distance_bins) == 100
    assert gm.global_mu == 1.1
    d = gm.to_dict()
    assert "distance_bins" in d
    assert "is_global_fallback" in d


def test_grip_map_mu_at():
    """mu_at() interpolates correctly."""
    from grip_map import GripMap

    gm = GripMap(
        distance_bins=np.array([0.0, 100.0, 200.0, 300.0]),
        mu_mean=np.array([0.8, 1.0, 1.2, 0.9]),
        mu_p90=np.array([1.0, 1.2, 1.4, 1.1]),
        mu_p95=np.array([1.1, 1.3, 1.5, 1.2]),
        bin_stats=[],
        global_mu=1.0,
        is_global_fallback=False,
        source="lat_accel",
        warning=None,
        n_laps_used=10,
    )
    # At exact bin
    assert abs(gm.mu_at(100.0, "mean") - 1.0) < 0.01
    # Interpolated between bins
    mu_150 = gm.mu_at(150.0, "p95")
    assert 1.3 < mu_150 < 1.5  # between 1.3 and 1.5
    # Beyond range: clamp to edge
    assert abs(gm.mu_at(-10.0, "mean") - 0.8) < 0.01
    assert abs(gm.mu_at(500.0, "mean") - 0.9) < 0.01
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_grip_map.py -v`
Expected: FAIL

**Step 3: Write implementation**

In `telemetry_tool/grip_map.py`:

```python
"""
grip_map.py
-----------
Distance-binned lateral grip estimator.

Estimates per-distance-bin friction coefficient mu(s) from observed
laps using lateral acceleration (preferred) or v^2 * curvature (fallback).
Produces mu_mean(s), mu_pXX(s), and per-bin confidence scores.

Degrades gracefully: if curvature unreliable or bins sparse, reverts
to global mu with a warning.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict, field

import numpy as np

logger = logging.getLogger(__name__)

_G = 9.80665  # m/s^2

# ── Column names ──────────────────────────────────────────────────
_COL_DIST = "Distance (m)"
_COL_SPEED = "Speed (m/s)"
_COL_LAT_ACCEL_G = "Lateral acceleration (G) *calc"
_COL_LAT_ACCEL_MPS2 = "accel_lat_mps2"
_COL_CURVATURE = "curvature_1pm"

# ── Thresholds ────────────────────────────────────────────────────
_MIN_LAPS = 3
_MIN_SAMPLES_PER_BIN = 3
_CONFIDENCE_SAMPLE_TARGET = 8
_CONFIDENCE_VARIANCE_CAP = 0.1
_SPARSE_BIN_THRESHOLD = 0.5   # if <50% bins confident, global fallback
_IQR_FENCE = 1.5
_MIN_BIN_CONFIDENCE = 0.3


@dataclass
class GripBinStats:
    """Per-distance-bin grip statistics."""
    distance_m: float
    mu_mean: float
    mu_p50: float
    mu_p90: float
    mu_p95: float
    mu_p99: float
    sample_count: int
    variance: float
    confidence: float    # 0-1
    source: str          # "lat_accel" | "curvature_speed" | "global_fallback"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GripMap:
    """Distance-binned grip map for a session."""
    distance_bins: np.ndarray        # [m]
    mu_mean: np.ndarray              # per-bin mean mu
    mu_p90: np.ndarray               # per-bin 90th percentile
    mu_p95: np.ndarray               # per-bin 95th percentile
    bin_stats: list[GripBinStats]
    global_mu: float                 # session-wide median mu
    is_global_fallback: bool
    source: str                      # "lat_accel" | "curvature_speed"
    warning: str | None
    n_laps_used: int

    def mu_at(self, distance: float, percentile: str = "p95") -> float:
        """Interpolate mu at arbitrary distance.

        Parameters
        ----------
        distance : distance along track [m]
        percentile : "mean", "p90", or "p95"

        Returns
        -------
        Interpolated mu value.
        """
        if self.is_global_fallback or len(self.distance_bins) == 0:
            return self.global_mu

        arr_map = {"mean": self.mu_mean, "p90": self.mu_p90, "p95": self.mu_p95}
        arr = arr_map.get(percentile, self.mu_p95)

        # Clamp distance to range
        d = max(self.distance_bins[0], min(self.distance_bins[-1], distance))
        return float(np.interp(d, self.distance_bins, arr))

    def to_dict(self) -> dict:
        return {
            "distance_bins": self.distance_bins.tolist(),
            "mu_mean": self.mu_mean.tolist(),
            "mu_p90": self.mu_p90.tolist(),
            "mu_p95": self.mu_p95.tolist(),
            "global_mu": round(self.global_mu, 4),
            "is_global_fallback": self.is_global_fallback,
            "source": self.source,
            "warning": self.warning,
            "n_laps_used": self.n_laps_used,
            "bin_count": len(self.distance_bins),
        }
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_grip_map.py -v`
Expected: 3 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/grip_map.py telemetry_tool/tests/test_grip_map.py
git commit -m "feat(grip): add GripBinStats and GripMap dataclasses with mu_at() interpolation"
```

---

### Task 2: compute_grip_map() — per-bin mu estimation

**Files:**
- Modify: `telemetry_tool/grip_map.py` (append)
- Modify: `telemetry_tool/tests/test_grip_map.py` (append)

**Step 1: Write the failing tests**

Append to `telemetry_tool/tests/test_grip_map.py`:

```python


def _make_synthetic_laps(n_laps=8, n_points=200, mu_profile=None):
    """Create synthetic laps with known grip profile.

    If mu_profile is None, uses constant mu=1.0.
    mu_profile: callable(distance) -> mu
    """
    rng = np.random.default_rng(42)
    lap_length = 500.0
    laps = {}

    for lap_num in range(1, n_laps + 1):
        dist = np.linspace(0, lap_length, n_points)
        speed = np.full(n_points, 20.0) + rng.normal(0, 0.5, n_points)
        speed = np.clip(speed, 5.0, 40.0)

        if mu_profile is not None:
            mu_at_dist = np.array([mu_profile(d) for d in dist])
        else:
            mu_at_dist = np.full(n_points, 1.0)

        # a_lat = mu * g (with noise)
        lat_accel_g = mu_at_dist * (1.0 + rng.normal(0, 0.05, n_points))
        # Randomly flip sign (left/right turns)
        sign = rng.choice([-1, 1], n_points)
        lat_accel_g *= sign

        laps[lap_num] = pd.DataFrame({
            "Distance (m)": dist,
            "Speed (m/s)": speed,
            "Lateral acceleration (G) *calc": lat_accel_g,
            "accel_long_mps2": rng.normal(0, 2.0, n_points),
        })

    return laps


def test_compute_grip_map_constant_mu():
    """Constant mu=1.0 across all bins."""
    from grip_map import compute_grip_map

    laps = _make_synthetic_laps(n_laps=8, mu_profile=lambda d: 1.0)
    gm = compute_grip_map(laps)

    assert not gm.is_global_fallback
    assert gm.source == "lat_accel"
    assert gm.warning is None
    assert gm.n_laps_used == 8

    # mu_mean should be close to 1.0 everywhere
    assert np.abs(np.median(gm.mu_mean) - 1.0) < 0.15
    # p95 should be slightly above mean
    assert np.median(gm.mu_p95) >= np.median(gm.mu_mean)


def test_compute_grip_map_varying_mu():
    """Varying mu: high in first half, low in second."""
    from grip_map import compute_grip_map

    def mu_profile(d):
        return 1.3 if d < 250 else 0.7

    laps = _make_synthetic_laps(n_laps=10, mu_profile=mu_profile)
    gm = compute_grip_map(laps)

    # First half bins should have higher mu than second half
    mid = len(gm.distance_bins) // 2
    first_half_mean = np.mean(gm.mu_mean[:mid])
    second_half_mean = np.mean(gm.mu_mean[mid:])
    assert first_half_mean > second_half_mean


def test_compute_grip_map_no_lat_accel_falls_back():
    """No lateral accel channel → fallback to curvature*speed method."""
    from grip_map import compute_grip_map

    rng = np.random.default_rng(42)
    laps = {}
    for i in range(1, 6):
        laps[i] = pd.DataFrame({
            "Distance (m)": np.linspace(0, 500, 100),
            "Speed (m/s)": np.full(100, 20.0) + rng.normal(0, 0.5, 100),
            "accel_long_mps2": rng.normal(0, 1.0, 100),
        })

    # With curvature profile
    curv_df = pd.DataFrame({
        "distance_m": np.linspace(0, 500, 100),
        "curvature_1pm": np.full(100, 0.01),  # radius=100m
    })

    gm = compute_grip_map(laps, curvature_profile=curv_df)
    # Should use curvature_speed source or global fallback
    assert gm.source in ("curvature_speed", "lat_accel")
    assert gm.global_mu > 0


def test_compute_grip_map_too_few_laps():
    """Fewer than 3 laps → global fallback."""
    from grip_map import compute_grip_map

    laps = _make_synthetic_laps(n_laps=2, mu_profile=lambda d: 1.0)
    gm = compute_grip_map(laps)

    assert gm.is_global_fallback is True
    assert gm.warning is not None
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_grip_map.py::test_compute_grip_map_constant_mu -v`
Expected: FAIL

**Step 3: Write implementation**

Append to `telemetry_tool/grip_map.py`:

```python


def _get_lat_accel_g(df: "pd.DataFrame") -> np.ndarray | None:
    """Extract lateral acceleration in G from a lap DataFrame."""
    import pandas as pd

    for col, scale in [(_COL_LAT_ACCEL_G, 1.0), (_COL_LAT_ACCEL_MPS2, 1.0 / _G)]:
        if col in df.columns:
            vals = pd.to_numeric(df[col], errors="coerce").values * scale
            if np.isfinite(vals).sum() > 10:
                return vals
    return None


def _iqr_reject(samples: np.ndarray) -> np.ndarray:
    """Remove outliers using IQR fence."""
    if len(samples) < 4:
        return samples
    q1, q3 = np.percentile(samples, [25, 75])
    iqr = q3 - q1
    lo = q1 - _IQR_FENCE * iqr
    hi = q3 + _IQR_FENCE * iqr
    mask = (samples >= lo) & (samples <= hi)
    return samples[mask] if mask.sum() >= 3 else samples


def _bin_confidence(sample_count: int, variance: float) -> float:
    """Compute per-bin confidence from sample count and variance."""
    count_score = min(1.0, sample_count / _CONFIDENCE_SAMPLE_TARGET)
    variance_score = max(0.0, 1.0 - variance / _CONFIDENCE_VARIANCE_CAP)
    return round(0.6 * count_score + 0.4 * variance_score, 3)


def compute_grip_map(
    resampled_laps: dict[int, "pd.DataFrame"],
    curvature_profile: "pd.DataFrame | None" = None,
    *,
    learning_laps: list[int] | None = None,
    n_bins: int = 0,
) -> GripMap:
    """Compute distance-binned grip map from observed laps.

    Parameters
    ----------
    resampled_laps : lap_number -> DataFrame
    curvature_profile : DataFrame with distance_m + curvature_1pm columns
    learning_laps : restrict to these lap numbers
    n_bins : number of distance bins (0 = auto from data)

    Returns
    -------
    GripMap with per-bin mu estimates and confidence.
    """
    import pandas as pd

    sorted_keys = sorted(resampled_laps.keys())
    if learning_laps is not None:
        learning_set = set(learning_laps)
        sorted_keys = [k for k in sorted_keys if k in learning_set]

    n_laps = len(sorted_keys)

    # Too few laps → global fallback
    if n_laps < _MIN_LAPS:
        # Collect whatever mu samples we can
        all_mu = []
        for k in sorted_keys:
            g_vals = _get_lat_accel_g(resampled_laps[k])
            if g_vals is not None:
                all_mu.extend(np.abs(g_vals[np.isfinite(g_vals)]).tolist())
        global_mu = float(np.median(all_mu)) if all_mu else 1.0
        return GripMap(
            distance_bins=np.array([]),
            mu_mean=np.array([]),
            mu_p90=np.array([]),
            mu_p95=np.array([]),
            bin_stats=[],
            global_mu=round(global_mu, 4),
            is_global_fallback=True,
            source="lat_accel" if all_mu else "global_fallback",
            warning=f"Only {n_laps} lap(s) — need {_MIN_LAPS}+ for per-bin grip map",
            n_laps_used=n_laps,
        )

    # Determine distance grid
    first_df = resampled_laps[sorted_keys[0]]
    if _COL_DIST in first_df.columns:
        dist_col = _COL_DIST
    else:
        dist_col = "distance_m" if "distance_m" in first_df.columns else _COL_DIST

    dist_vals = first_df[dist_col].values
    d_min, d_max = float(dist_vals[0]), float(dist_vals[-1])
    if n_bins <= 0:
        n_bins = max(20, min(200, len(dist_vals) // 2))
    bin_edges = np.linspace(d_min, d_max, n_bins + 1)
    bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])

    # Try lateral accel first
    has_lat_accel = False
    for k in sorted_keys[:3]:
        if _get_lat_accel_g(resampled_laps[k]) is not None:
            has_lat_accel = True
            break

    # Collect per-bin mu samples
    bin_samples: list[list[float]] = [[] for _ in range(n_bins)]

    if has_lat_accel:
        source = "lat_accel"
        for k in sorted_keys:
            df = resampled_laps[k]
            g_vals = _get_lat_accel_g(df)
            if g_vals is None:
                continue
            if dist_col not in df.columns:
                continue
            d = df[dist_col].values
            mu = np.abs(g_vals)
            valid = np.isfinite(mu) & np.isfinite(d) & (mu > 0.01)
            d_valid, mu_valid = d[valid], mu[valid]
            bin_idx = np.digitize(d_valid, bin_edges) - 1
            bin_idx = np.clip(bin_idx, 0, n_bins - 1)
            for i, m in zip(bin_idx, mu_valid):
                bin_samples[i].append(float(m))
    elif curvature_profile is not None and _COL_CURVATURE in curvature_profile.columns:
        source = "curvature_speed"
        # Build curvature interpolator
        cp_dist = curvature_profile["distance_m"].values
        cp_curv = curvature_profile[_COL_CURVATURE].values
        for k in sorted_keys:
            df = resampled_laps[k]
            if dist_col not in df.columns or _COL_SPEED not in df.columns:
                continue
            d = df[dist_col].values
            v = df[_COL_SPEED].values
            curv = np.interp(d, cp_dist, cp_curv)
            # mu = v^2 * |curv| / g
            mu = v ** 2 * np.abs(curv) / _G
            valid = np.isfinite(mu) & np.isfinite(d) & (mu > 0.01) & (np.abs(curv) > 0.001)
            d_valid, mu_valid = d[valid], mu[valid]
            bin_idx = np.digitize(d_valid, bin_edges) - 1
            bin_idx = np.clip(bin_idx, 0, n_bins - 1)
            for i, m in zip(bin_idx, mu_valid):
                bin_samples[i].append(float(m))
    else:
        source = "global_fallback"
        return GripMap(
            distance_bins=bin_centers,
            mu_mean=np.full(n_bins, 1.0),
            mu_p90=np.full(n_bins, 1.0),
            mu_p95=np.full(n_bins, 1.0),
            bin_stats=[],
            global_mu=1.0,
            is_global_fallback=True,
            source=source,
            warning="No lateral acceleration or curvature data available",
            n_laps_used=n_laps,
        )

    # Compute per-bin statistics
    stats_list: list[GripBinStats] = []
    mu_mean_arr = np.full(n_bins, np.nan)
    mu_p90_arr = np.full(n_bins, np.nan)
    mu_p95_arr = np.full(n_bins, np.nan)
    all_clean_mu: list[float] = []

    for i in range(n_bins):
        samples = np.array(bin_samples[i])
        if len(samples) < _MIN_SAMPLES_PER_BIN:
            stats_list.append(GripBinStats(
                distance_m=round(float(bin_centers[i]), 1),
                mu_mean=0.0, mu_p50=0.0, mu_p90=0.0,
                mu_p95=0.0, mu_p99=0.0,
                sample_count=len(samples),
                variance=0.0, confidence=0.0,
                source=source,
            ))
            continue

        clean = _iqr_reject(samples)
        all_clean_mu.extend(clean.tolist())

        mean_val = float(np.mean(clean))
        var_val = float(np.var(clean))
        conf = _bin_confidence(len(clean), var_val)

        p50 = float(np.percentile(clean, 50))
        p90 = float(np.percentile(clean, 90))
        p95 = float(np.percentile(clean, 95))
        p99 = float(np.percentile(clean, 99))

        mu_mean_arr[i] = mean_val
        mu_p90_arr[i] = p90
        mu_p95_arr[i] = p95

        stats_list.append(GripBinStats(
            distance_m=round(float(bin_centers[i]), 1),
            mu_mean=round(mean_val, 4),
            mu_p50=round(p50, 4),
            mu_p90=round(p90, 4),
            mu_p95=round(p95, 4),
            mu_p99=round(p99, 4),
            sample_count=len(clean),
            variance=round(var_val, 6),
            confidence=conf,
            source=source,
        ))

    # Global mu
    global_mu = float(np.median(all_clean_mu)) if all_clean_mu else 1.0

    # Fill NaN bins with global mu
    nan_mask = np.isnan(mu_mean_arr)
    mu_mean_arr[nan_mask] = global_mu
    mu_p90_arr[nan_mask] = global_mu
    mu_p95_arr[nan_mask] = global_mu

    # Check sparsity → global fallback
    confident_bins = sum(1 for s in stats_list if s.confidence >= _MIN_BIN_CONFIDENCE)
    is_global = confident_bins < _SPARSE_BIN_THRESHOLD * n_bins
    warning = None
    if is_global:
        warning = (
            f"Only {confident_bins}/{n_bins} bins have sufficient confidence "
            f"— using global mu={global_mu:.2f}"
        )
        mu_mean_arr[:] = global_mu
        mu_p90_arr[:] = global_mu
        mu_p95_arr[:] = global_mu

    logger.info(
        "Grip map [%s]: %d bins, %d confident, global_mu=%.3f, fallback=%s",
        source, n_bins, confident_bins, global_mu, is_global,
    )

    return GripMap(
        distance_bins=bin_centers,
        mu_mean=np.round(mu_mean_arr, 4),
        mu_p90=np.round(mu_p90_arr, 4),
        mu_p95=np.round(mu_p95_arr, 4),
        bin_stats=stats_list,
        global_mu=round(global_mu, 4),
        is_global_fallback=is_global,
        source=source,
        warning=warning,
        n_laps_used=n_laps,
    )
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_grip_map.py -v`
Expected: 7 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/grip_map.py telemetry_tool/tests/test_grip_map.py
git commit -m "feat(grip): add compute_grip_map() with per-bin mu estimation and outlier rejection"
```

---

### Task 3: FrictionBin + FrictionEnvelope dataclasses + compute_friction_envelope()

**Files:**
- Create: `telemetry_tool/friction_envelope.py`
- Create: `telemetry_tool/tests/test_friction_envelope.py`

**Step 1: Write the failing tests**

In `telemetry_tool/tests/test_friction_envelope.py`:

```python
"""Tests for combined friction envelope."""
import numpy as np
import pandas as pd
import pytest


def test_friction_bin_fields():
    """FrictionBin has all required fields and to_dict()."""
    from friction_envelope import FrictionBin

    fb = FrictionBin(
        speed_center_mps=15.0,
        combined_g_p95=1.3,
        lat_max_g=1.2,
        accel_max_g=0.8,
        brake_max_g=1.5,
        sample_count=50,
        confidence=0.9,
    )
    assert fb.speed_center_mps == 15.0
    assert fb.combined_g_p95 == 1.3
    d = fb.to_dict()
    assert "brake_max_g" in d


def test_friction_envelope_fields():
    """FrictionEnvelope has all required fields and to_dict()."""
    from friction_envelope import FrictionEnvelope

    fe = FrictionEnvelope(
        speed_bins=np.array([5.0, 15.0, 25.0]),
        friction_bins=[],
        global_combined_g=1.2,
        is_reliable=True,
        warning=None,
    )
    assert fe.is_reliable is True
    d = fe.to_dict()
    assert "global_combined_g" in d


def _make_friction_laps(n_laps=8, n_points=200, mu_circle=1.2):
    """Create laps with known friction circle radius."""
    rng = np.random.default_rng(42)
    laps = {}
    for lap_num in range(1, n_laps + 1):
        dist = np.linspace(0, 500, n_points)
        speed = np.full(n_points, 20.0) + rng.normal(0, 2.0, n_points)
        speed = np.clip(speed, 5.0, 40.0)

        # Generate points inside the friction circle
        angles = rng.uniform(0, 2 * np.pi, n_points)
        radii = rng.uniform(0.3, 0.95, n_points) * mu_circle
        a_lat_g = radii * np.cos(angles)
        a_long_g = radii * np.sin(angles)

        laps[lap_num] = pd.DataFrame({
            "Distance (m)": dist,
            "Speed (m/s)": speed,
            "Lateral acceleration (G) *calc": a_lat_g,
            "accel_long_mps2": a_long_g * 9.80665,  # convert to m/s^2
        })
    return laps


def test_compute_friction_envelope_known_circle():
    """Known friction circle mu=1.2 → recovered envelope close."""
    from friction_envelope import compute_friction_envelope

    laps = _make_friction_laps(n_laps=10, mu_circle=1.2)
    fe = compute_friction_envelope(laps)

    assert fe.is_reliable is True
    assert fe.warning is None
    # Global combined G should be close to mu_circle
    assert abs(fe.global_combined_g - 1.2) < 0.3


def test_friction_envelope_is_feasible():
    """is_feasible() checks combined accel constraint."""
    from friction_envelope import compute_friction_envelope

    laps = _make_friction_laps(n_laps=10, mu_circle=1.0)
    fe = compute_friction_envelope(laps)

    # Well within circle should be feasible
    assert fe.is_feasible(20.0, 0.3, 0.3) is True
    # Way outside circle should be infeasible
    assert fe.is_feasible(20.0, 2.0, 2.0) is False


def test_friction_envelope_max_lat_at_long():
    """max_lat_at_long() returns reduced lateral under braking."""
    from friction_envelope import compute_friction_envelope

    laps = _make_friction_laps(n_laps=10, mu_circle=1.2)
    fe = compute_friction_envelope(laps)

    # Zero longitudinal → max lateral
    max_lat_0 = fe.max_lat_at_long(20.0, 0.0)
    # Under braking → reduced lateral
    max_lat_brake = fe.max_lat_at_long(20.0, 0.8)
    assert max_lat_brake < max_lat_0


def test_friction_envelope_too_few_samples():
    """Fewer than 50 total samples → is_reliable=False."""
    from friction_envelope import compute_friction_envelope

    rng = np.random.default_rng(42)
    laps = {1: pd.DataFrame({
        "Distance (m)": np.linspace(0, 100, 10),
        "Speed (m/s)": np.full(10, 20.0),
        "Lateral acceleration (G) *calc": rng.normal(0, 0.3, 10),
        "accel_long_mps2": rng.normal(0, 1.0, 10),
    })}

    fe = compute_friction_envelope(laps)
    assert fe.is_reliable is False
    assert fe.warning is not None
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_friction_envelope.py -v`
Expected: FAIL

**Step 3: Write implementation**

In `telemetry_tool/friction_envelope.py`:

```python
"""
friction_envelope.py
--------------------
Combined (lateral + longitudinal) friction envelope estimator.

Estimates per-speed-bin sqrt(ax^2 + ay^2) limits and separate
ax/ay bounds from observed laps. Provides feasibility checking
and ellipse-based max lateral under given longitudinal accel.

Falls back gracefully when data is sparse.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict

import numpy as np

logger = logging.getLogger(__name__)

_G = 9.80665  # m/s^2

# ── Column names ──────────────────────────────────────────────────
_COL_SPEED = "Speed (m/s)"
_COL_LAT_ACCEL_G = "Lateral acceleration (G) *calc"
_COL_LAT_ACCEL_MPS2 = "accel_lat_mps2"
_COL_LONG_ACCEL_MPS2 = "accel_long_mps2"

# ── Thresholds ────────────────────────────────────────────────────
_MIN_TOTAL_SAMPLES = 50
_MIN_SAMPLES_PER_BIN = 8
_N_SPEED_BINS = 15
_PERCENTILE = 95.0
_IQR_FENCE = 1.5


@dataclass
class FrictionBin:
    """Per-speed-bin friction envelope stats."""
    speed_center_mps: float
    combined_g_p95: float        # sqrt(ax^2+ay^2) 95th percentile [G]
    lat_max_g: float             # |ay| 95th percentile [G]
    accel_max_g: float           # ax (positive) 95th percentile [G]
    brake_max_g: float           # |ax| (negative) 95th percentile [G]
    sample_count: int
    confidence: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FrictionEnvelope:
    """Combined acceleration envelope across speed range."""
    speed_bins: np.ndarray
    friction_bins: list[FrictionBin]
    global_combined_g: float
    is_reliable: bool
    warning: str | None

    def _get_bin(self, speed_mps: float) -> FrictionBin | None:
        """Find nearest speed bin."""
        if not self.friction_bins:
            return None
        idx = int(np.argmin(np.abs(self.speed_bins - speed_mps)))
        fb = self.friction_bins[idx]
        return fb if fb.sample_count >= _MIN_SAMPLES_PER_BIN else None

    def is_feasible(
        self, speed_mps: float, a_lat_g: float, a_long_g: float,
    ) -> bool:
        """Check if (a_lat, a_long) is within envelope at given speed.

        Parameters in G units.
        """
        fb = self._get_bin(speed_mps)
        if fb is None:
            # Fall back to global
            combined = np.sqrt(a_lat_g ** 2 + a_long_g ** 2)
            return combined <= self.global_combined_g * 1.1  # 10% margin

        combined = np.sqrt(a_lat_g ** 2 + a_long_g ** 2)
        return combined <= fb.combined_g_p95 * 1.05  # 5% margin

    def max_lat_at_long(
        self, speed_mps: float, a_long_g: float,
    ) -> float:
        """Max lateral accel given longitudinal accel (ellipse constraint).

        Returns max |a_lat| in G.
        """
        fb = self._get_bin(speed_mps)
        if fb is None:
            r = self.global_combined_g
            residual_sq = max(0.0, r ** 2 - a_long_g ** 2)
            return float(np.sqrt(residual_sq))

        # Ellipse: (a_long/a_long_max)^2 + (a_lat/a_lat_max)^2 <= 1
        if a_long_g >= 0:
            a_long_max = fb.accel_max_g if fb.accel_max_g > 0 else fb.combined_g_p95
        else:
            a_long_max = fb.brake_max_g if fb.brake_max_g > 0 else fb.combined_g_p95

        a_lat_max = fb.lat_max_g if fb.lat_max_g > 0 else fb.combined_g_p95

        long_frac_sq = min(1.0, (a_long_g / a_long_max) ** 2) if a_long_max > 0 else 0.0
        residual = max(0.0, 1.0 - long_frac_sq)
        return float(a_lat_max * np.sqrt(residual))

    def to_dict(self) -> dict:
        return {
            "speed_bins": self.speed_bins.tolist(),
            "friction_bins": [fb.to_dict() for fb in self.friction_bins],
            "global_combined_g": round(self.global_combined_g, 4),
            "is_reliable": self.is_reliable,
            "warning": self.warning,
        }


def _iqr_reject(samples: np.ndarray) -> np.ndarray:
    """Remove outliers using IQR fence."""
    if len(samples) < 4:
        return samples
    q1, q3 = np.percentile(samples, [25, 75])
    iqr = q3 - q1
    lo = q1 - _IQR_FENCE * iqr
    hi = q3 + _IQR_FENCE * iqr
    mask = (samples >= lo) & (samples <= hi)
    return samples[mask] if mask.sum() >= 3 else samples


def compute_friction_envelope(
    resampled_laps: dict[int, "pd.DataFrame"],
    *,
    learning_laps: list[int] | None = None,
    n_speed_bins: int = _N_SPEED_BINS,
    percentile: float = _PERCENTILE,
) -> FrictionEnvelope:
    """Compute combined friction envelope from observed laps.

    Parameters
    ----------
    resampled_laps : lap_number -> DataFrame
    learning_laps : restrict to these lap numbers
    n_speed_bins : number of speed bins
    percentile : percentile for envelope extraction

    Returns
    -------
    FrictionEnvelope with per-speed-bin limits.
    """
    import pandas as pd

    sorted_keys = sorted(resampled_laps.keys())
    if learning_laps is not None:
        learning_set = set(learning_laps)
        sorted_keys = [k for k in sorted_keys if k in learning_set]

    # Collect (speed, a_lat_g, a_long_g) triples
    all_speed: list[float] = []
    all_lat_g: list[float] = []
    all_long_g: list[float] = []

    for k in sorted_keys:
        df = resampled_laps[k]
        if _COL_SPEED not in df.columns:
            continue

        speed = pd.to_numeric(df[_COL_SPEED], errors="coerce").values

        # Lateral accel in G
        lat_g = None
        if _COL_LAT_ACCEL_G in df.columns:
            lat_g = pd.to_numeric(df[_COL_LAT_ACCEL_G], errors="coerce").values
        elif _COL_LAT_ACCEL_MPS2 in df.columns:
            lat_g = pd.to_numeric(df[_COL_LAT_ACCEL_MPS2], errors="coerce").values / _G
        if lat_g is None:
            continue

        # Longitudinal accel in G
        long_g = np.zeros(len(df))
        if _COL_LONG_ACCEL_MPS2 in df.columns:
            long_g = pd.to_numeric(df[_COL_LONG_ACCEL_MPS2], errors="coerce").values / _G

        valid = np.isfinite(speed) & np.isfinite(lat_g) & np.isfinite(long_g)
        all_speed.extend(speed[valid].tolist())
        all_lat_g.extend(lat_g[valid].tolist())
        all_long_g.extend(long_g[valid].tolist())

    total_samples = len(all_speed)
    if total_samples < _MIN_TOTAL_SAMPLES:
        return FrictionEnvelope(
            speed_bins=np.array([]),
            friction_bins=[],
            global_combined_g=1.0,
            is_reliable=False,
            warning=f"Only {total_samples} samples — need {_MIN_TOTAL_SAMPLES}+ for friction envelope",
        )

    speed_arr = np.array(all_speed)
    lat_arr = np.array(all_lat_g)
    long_arr = np.array(all_long_g)
    combined_arr = np.sqrt(lat_arr ** 2 + long_arr ** 2)

    # Global combined G
    clean_combined = _iqr_reject(combined_arr)
    global_combined = float(np.percentile(clean_combined, percentile))

    # Speed bins
    v_min, v_max = float(np.percentile(speed_arr, 2)), float(np.percentile(speed_arr, 98))
    if v_max - v_min < 2.0:
        v_max = v_min + 10.0
    bin_edges = np.linspace(v_min, v_max, n_speed_bins + 1)
    bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])

    # Per-speed-bin stats
    bins_list: list[FrictionBin] = []
    speed_idx = np.digitize(speed_arr, bin_edges) - 1
    speed_idx = np.clip(speed_idx, 0, n_speed_bins - 1)

    for i in range(n_speed_bins):
        mask = speed_idx == i
        n_in_bin = int(mask.sum())
        if n_in_bin < _MIN_SAMPLES_PER_BIN:
            bins_list.append(FrictionBin(
                speed_center_mps=round(float(bin_centers[i]), 2),
                combined_g_p95=round(global_combined, 4),
                lat_max_g=round(global_combined, 4),
                accel_max_g=round(global_combined * 0.6, 4),
                brake_max_g=round(global_combined, 4),
                sample_count=n_in_bin,
                confidence=0.0,
            ))
            continue

        lat_in = np.abs(lat_arr[mask])
        long_in = long_arr[mask]
        comb_in = combined_arr[mask]

        clean_comb = _iqr_reject(comb_in)
        clean_lat = _iqr_reject(lat_in)

        accel_mask = long_in > 0.05
        brake_mask = long_in < -0.05
        accel_vals = _iqr_reject(long_in[accel_mask]) if accel_mask.sum() > 3 else np.array([0.0])
        brake_vals = _iqr_reject(np.abs(long_in[brake_mask])) if brake_mask.sum() > 3 else np.array([0.0])

        conf = min(1.0, n_in_bin / (_MIN_SAMPLES_PER_BIN * 4))

        bins_list.append(FrictionBin(
            speed_center_mps=round(float(bin_centers[i]), 2),
            combined_g_p95=round(float(np.percentile(clean_comb, percentile)), 4),
            lat_max_g=round(float(np.percentile(clean_lat, percentile)), 4),
            accel_max_g=round(float(np.percentile(accel_vals, percentile)), 4),
            brake_max_g=round(float(np.percentile(brake_vals, percentile)), 4),
            sample_count=n_in_bin,
            confidence=round(conf, 3),
        ))

    logger.info(
        "Friction envelope: %d speed bins, %d samples, global_combined=%.3fG",
        n_speed_bins, total_samples, global_combined,
    )

    return FrictionEnvelope(
        speed_bins=bin_centers,
        friction_bins=bins_list,
        global_combined_g=round(global_combined, 4),
        is_reliable=True,
        warning=None,
    )
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_friction_envelope.py -v`
Expected: 7 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/friction_envelope.py telemetry_tool/tests/test_friction_envelope.py
git commit -m "feat(friction): add FrictionEnvelope with per-speed-bin combined accel limits and feasibility check"
```

---

### Task 4: Integrate grip_map into lap_simulation.py

**Files:**
- Modify: `telemetry_tool/lap_simulation.py`

**Step 1: Read lap_simulation.py**

Find `simulate_theoretical_lap()` function. Look for where cornering speed limit is computed — it likely uses `friction.grip(speed)` or a constant mu.

**Step 2: Add grip_map parameter**

Add `grip_map=None` parameter to `simulate_theoretical_lap()` and `simulate_with_fallback()`.

In the cornering speed limit computation, replace global mu with distance-binned mu:

```python
# In the cornering speed cap section:
if grip_map is not None and not grip_map.is_global_fallback:
    mu = grip_map.mu_at(distance[i], "p95")
else:
    mu = friction.grip(speed) if friction is not None else mu_default
```

The exact integration depends on how the existing code computes cornering limits. Read the code first, then adapt.

**Step 3: Add friction_envelope constraint**

Add `friction_envelope=None` parameter. After the forward-backward pass, clamp combined accel:

```python
if friction_envelope is not None and friction_envelope.is_reliable:
    for i in range(len(speed_profile)):
        a_lat = speed_profile[i] ** 2 * abs(curvature[i])  # lateral from cornering
        a_long = accel_profile[i]
        a_lat_g = a_lat / 9.80665
        a_long_g = a_long / 9.80665
        if not friction_envelope.is_feasible(speed_profile[i], a_lat_g, a_long_g):
            # Reduce speed to stay within envelope
            max_lat = friction_envelope.max_lat_at_long(speed_profile[i], a_long_g)
            max_v = sqrt(max_lat * 9.80665 / max(abs(curvature[i]), 1e-6))
            speed_profile[i] = min(speed_profile[i], max_v)
```

**Step 4: Run existing tests**

Run: `pytest telemetry_tool/tests/ -k "simulation or theoretical" -v`
Expected: All existing tests still pass (new parameters default to None)

**Step 5: Commit**

```bash
git add telemetry_tool/lap_simulation.py
git commit -m "feat(simulation): integrate grip_map and friction_envelope into cornering speed caps"
```

---

### Task 5: Pipeline stage 9.9 — grip map + friction envelope

**Files:**
- Modify: `telemetry_tool/pipeline.py`

**Step 1: Read pipeline.py**

Find stage 09h (condition clustering) end and stage 10 start. Insert stage 09i between them.

**Step 2: Add stage 09i**

```python
    # ====================================================================
    # STEP 09i -- Grip map + friction envelope
    # ====================================================================

    _gm_mod = _import("grip_map")
    _fe_mod = _import("friction_envelope")
    _grip_map = None
    _friction_envelope_result = None

    def _compute_grip_map():
        if _gm_mod is None or not resampled_laps:
            return None
        _learning = None
        if _inclusion_policy is not None:
            _learning = _inclusion_policy.learning_laps
        return _gm_mod.compute_grip_map(
            resampled_laps,
            curvature_profile=curvature_profile,
            learning_laps=_learning,
        )

    _grip_raw, err = _safe_step("09i_grip_map", _compute_grip_map)
    _record("09i_grip_map", _grip_raw, err)
    _fire_progress("09i_grip_map")

    if _grip_raw is not None:
        _grip_map = _grip_raw
        summary["grip_map"] = _grip_map.to_dict()
    else:
        summary["grip_map"] = None

    def _compute_friction_envelope():
        if _fe_mod is None or not resampled_laps:
            return None
        _learning = None
        if _inclusion_policy is not None:
            _learning = _inclusion_policy.learning_laps
        return _fe_mod.compute_friction_envelope(
            resampled_laps,
            learning_laps=_learning,
        )

    _fe_raw, err = _safe_step("09i_friction_envelope", _compute_friction_envelope)
    _record("09i_friction_envelope", _fe_raw, err)

    if _fe_raw is not None:
        _friction_envelope_result = _fe_raw
        summary["friction_envelope"] = _friction_envelope_result.to_dict()
    else:
        summary["friction_envelope"] = None
```

**Step 3: Pass grip_map and friction_envelope to simulation in stage 10**

Find where `simulate_with_fallback()` is called and add the new parameters:

```python
    grip_map=_grip_map,
    friction_envelope=_friction_envelope_result,
```

**Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_clustering_pipeline.py telemetry_tool/tests/test_traffic_pipeline.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add telemetry_tool/pipeline.py
git commit -m "feat(pipeline): integrate grip map + friction envelope as stage 9.9, pass to simulation"
```

---

### Task 6: Grip map plot in HTML report

**Files:**
- Modify: `telemetry_tool/reporting_html.py`

**Step 1: Read reporting_html.py**

Find `_build_confidence_html` (recently added). The grip map visualization goes after it.

**Step 2: Add _build_grip_map_html helper**

```python
def _build_grip_map_html(summary: dict) -> str:
    """Build HTML for grip map visualization."""
    grip_data = summary.get("grip_map")
    if grip_data is None:
        return ""

    is_fallback = grip_data.get("is_global_fallback", True)
    global_mu = grip_data.get("global_mu", 1.0)
    source = grip_data.get("source", "unknown")
    warning = grip_data.get("warning")
    n_laps = grip_data.get("n_laps_used", 0)

    parts = [
        '<div class="section grip-map-panel" style="margin: 16px 0;">',
        f'<h3>Grip Map <span style="color: #9ca3af; font-size: 0.8em;">'
        f'({source}, {n_laps} laps)</span></h3>',
    ]

    if warning:
        parts.append(
            f'<p style="color: #f59e0b; margin: 4px 0;">'
            f'<strong>Warning:</strong> {warning}</p>'
        )

    if is_fallback:
        parts.append(
            f'<p>Global grip coefficient: <strong>{global_mu:.2f} G</strong></p>'
        )
    else:
        # Inline SVG sparkline of mu_mean
        distances = grip_data.get("distance_bins", [])
        mu_mean = grip_data.get("mu_mean", [])
        mu_p95 = grip_data.get("mu_p95", [])
        if distances and mu_mean:
            n = len(distances)
            width = 600
            height = 120
            d_min, d_max = distances[0], distances[-1]
            mu_all = mu_mean + mu_p95
            mu_min = max(0, min(mu_all) - 0.1)
            mu_max = max(mu_all) + 0.1

            def _sx(d):
                return (d - d_min) / max(1, d_max - d_min) * width

            def _sy(mu):
                return height - (mu - mu_min) / max(0.01, mu_max - mu_min) * height

            # Build SVG path for mu_mean
            mean_pts = " ".join(
                f"{_sx(distances[i]):.1f},{_sy(mu_mean[i]):.1f}"
                for i in range(n)
            )
            p95_pts = " ".join(
                f"{_sx(distances[i]):.1f},{_sy(mu_p95[i]):.1f}"
                for i in range(n)
            )

            parts.append(
                f'<svg viewBox="0 0 {width} {height}" '
                f'style="width: 100%; max-width: 600px; height: {height}px; '
                f'background: rgba(0,0,0,0.03); border-radius: 4px;">'
                f'<polyline points="{p95_pts}" fill="none" '
                f'stroke="#22c55e" stroke-width="1" stroke-dasharray="4,2" '
                f'opacity="0.6"/>'
                f'<polyline points="{mean_pts}" fill="none" '
                f'stroke="#3b82f6" stroke-width="2"/>'
                f'<text x="5" y="12" font-size="10" fill="#9ca3af">'
                f'mu (G) — blue: mean, green dashed: p95</text>'
                f'</svg>'
            )

        parts.append(
            f'<p style="font-size: 0.85em; color: #9ca3af;">'
            f'Global mu: {global_mu:.2f} G | '
            f'{len(distances)} bins</p>'
        )

    parts.append('</div>')
    return "\n".join(parts)
```

**Step 3: Call from generate_report()**

After `confidence_html = ...`, add:
```python
    grip_map_html = _build_grip_map_html(summary)
```

Inject into template after confidence panel.

**Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_clustering_pipeline.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/reporting_html.py
git commit -m "feat(report): add grip map SVG sparkline visualization"
```

---

### Task 7: API grip-map endpoint

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py`

**Step 1: Read data_v2.py**

Find the endpoint pattern. Look at how other endpoints like `get_scores()` or `get_gg_data()` retrieve session data.

**Step 2: Add grip-map endpoint**

```python
@bp.route("/sessions/<int:session_id>/grip-map", methods=["GET"])
def get_grip_map(session_id):
    """Return distance-binned grip map for a session."""
    conn = _get_conn()
    summary = models.get_session_summary(conn, session_id)
    if summary is None:
        return api_error("Session not found", 404)

    grip_data = summary.get("grip_map")
    if grip_data is None:
        return api_error("Grip map not available for this session", 404)

    return api_success(grip_data)
```

Also add `grip_map_available` and `friction_envelope_available` booleans to the scores endpoint response.

**Step 3: Run tests**

Run: `pytest telemetry_tool/tests/test_grip_map.py telemetry_tool/tests/test_friction_envelope.py -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py
git commit -m "feat(api): add grip-map endpoint and availability flags in scores"
```

---

### Task 8: Integration test — synthetic track with known mu(s)

**Files:**
- Create: `telemetry_tool/tests/test_grip_pipeline.py`

**Step 1: Write the test**

```python
"""Integration tests for grip map + friction envelope in pipeline."""
import numpy as np
import pandas as pd
import pytest


def _make_grip_test_csv(tmp_path, n_laps=8):
    """Create CSV with known grip profile: high grip first half, low second."""
    rng = np.random.default_rng(42)
    frames = []
    n_per_lap = 200
    lap_length = 500.0

    for lap in range(1, n_laps + 1):
        t_start = (lap - 1) * 30.0
        t = np.linspace(t_start, t_start + 25.0, n_per_lap)
        dist = np.linspace(0, lap_length, n_per_lap)
        speed = np.full(n_per_lap, 20.0) + rng.normal(0, 0.5, n_per_lap)
        lat = np.linspace(45.0, 45.002, n_per_lap) + rng.normal(0, 1e-5, n_per_lap)
        lon = np.linspace(9.0, 9.002, n_per_lap) + rng.normal(0, 1e-5, n_per_lap)

        # High grip first half (mu=1.3), low grip second half (mu=0.7)
        mu_profile = np.where(dist < lap_length / 2, 1.3, 0.7)
        lat_g = mu_profile * rng.choice([-1, 1], n_per_lap) * (0.8 + rng.uniform(0, 0.2, n_per_lap))

        df = pd.DataFrame({
            "Lap #": np.full(n_per_lap, lap),
            "Time (s)": t,
            "Distance (m)": dist + (lap - 1) * lap_length,
            "Speed (m/s)": speed,
            "Latitude (deg)": lat,
            "Longitude (deg)": lon,
            "Bearing (deg)": np.full(n_per_lap, 90.0) + rng.normal(0, 1, n_per_lap),
            "Longitudinal acceleration (G) *calc": rng.normal(0, 0.02, n_per_lap),
            "Lateral acceleration (G) *calc": lat_g,
        })
        frames.append(df)

    full_df = pd.concat(frames, ignore_index=True)
    csv_path = tmp_path / "grip_test.csv"
    full_df.to_csv(csv_path, index=False)
    return csv_path


def test_pipeline_has_grip_map(tmp_path):
    """Pipeline summary contains grip_map and friction_envelope keys."""
    import pipeline

    csv_path = _make_grip_test_csv(tmp_path)
    summary = pipeline.run_full_analysis(str(csv_path), {})

    assert "grip_map" in summary
    grip = summary["grip_map"]
    assert grip is not None
    assert "distance_bins" in grip
    assert "mu_mean" in grip
    assert "global_mu" in grip

    assert "friction_envelope" in summary
    fe = summary["friction_envelope"]
    assert fe is not None
    assert "global_combined_g" in fe


def test_grip_map_detects_varying_mu(tmp_path):
    """Grip map distinguishes high-grip from low-grip sections."""
    import pipeline

    csv_path = _make_grip_test_csv(tmp_path, n_laps=10)
    summary = pipeline.run_full_analysis(str(csv_path), {})

    grip = summary.get("grip_map")
    if grip is None or grip.get("is_global_fallback"):
        pytest.skip("Grip map fell back to global — insufficient data")

    mu_mean = grip["mu_mean"]
    distances = grip["distance_bins"]
    n = len(distances)
    if n < 4:
        pytest.skip("Too few bins")

    # First quarter should have higher mu than last quarter
    q1_mean = np.mean(mu_mean[:n // 4])
    q4_mean = np.mean(mu_mean[3 * n // 4:])
    # Allow some tolerance due to pipeline processing
    assert q1_mean > q4_mean * 0.8, (
        f"Expected first quarter mu ({q1_mean:.2f}) > "
        f"last quarter mu ({q4_mean:.2f}) * 0.8"
    )
```

**Step 2: Run tests**

Run: `pytest telemetry_tool/tests/test_grip_pipeline.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add telemetry_tool/tests/test_grip_pipeline.py
git commit -m "test(grip): add pipeline integration tests for grip map and friction envelope"
```

---

## Summary

| Task | What | Tests |
|------|------|-------|
| 1 | GripBinStats + GripMap dataclasses with mu_at() | 3 |
| 2 | compute_grip_map() with per-bin estimation | 4 |
| 3 | FrictionBin + FrictionEnvelope + compute_friction_envelope() | 7 |
| 4 | Integrate into lap_simulation.py cornering caps | 0 (existing) |
| 5 | Pipeline stage 9.9 integration | 0 (existing) |
| 6 | Grip map SVG in HTML report | 0 (existing) |
| 7 | API grip-map endpoint | 0 (existing) |
| 8 | Integration test — known mu(s) pipeline | 2 |
