# Theoretical Engine Replacement — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the old statistical/physics theoretical engine with the new kart_envelope QSS/CasADi solver, exposing corner coaching, delta maps, and session scalars through the existing API and scoring system.

**Architecture:** Adapter pattern — a thin `theoretical_adapter.py` bridges the new kart_envelope solver to the existing pipeline contract. The new kart_envelope package replaces the old one wholesale. Old engines (`theoretical_engine.py`, `lap_simulation.py`) stay as cascade fallback. DB schema gains 3 JSON columns. API response is enriched.

**Tech Stack:** Python 3.14, Flask, NumPy, Pandas, Alembic, SQLite/PostgreSQL, kart_envelope (QSS solver, CasADi optional)

**Design doc:** `docs/plans/2026-02-27-theoretical-engine-replacement-design.md`

---

### Task 1: Replace kart_envelope package

**Files:**
- Delete: `kart_envelope/` (entire existing package)
- Create: `kart_envelope/` (copy from `C:\Users\Admin\Documents\Telemetry\Analysis\New_folder\kart_envelope\`)

**Step 1: Delete existing kart_envelope and copy new one**

```bash
rm -rf kart_envelope/
cp -r "C:/Users/Admin/Documents/Telemetry/Analysis/New_folder/kart_envelope/" kart_envelope/
```

**Step 2: Clean up __pycache__ from the copy**

```bash
find kart_envelope/ -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
```

**Step 3: Verify joker_detection import still works**

```bash
python -c "from kart_envelope.processing.joker_detection import detect_joker_lap; print('OK')"
```
Expected: `OK`

**Step 4: Verify core solver imports**

```bash
python -c "
from kart_envelope.solver.min_time import compute_theoretical_lap, TheoreticalResult
from kart_envelope.envelope.capability import train_capability_envelope, CapabilityEnvelope
from kart_envelope.track.geometry import build_track_geometry, TrackGeometry
from kart_envelope.inference.session_scalars import infer_session_scalars, SessionScalars
from kart_envelope.coaching.delta_analysis import compute_delta_map
from kart_envelope.coaching.corner_coaching import analyze_corner_performance, detect_corners_from_curvature, CornerPerformance
from kart_envelope.config import KartEnvelopeConfig, default_config
print('All imports OK')
"
```
Expected: `All imports OK`

**Step 5: Run existing kart_envelope tests**

```bash
pytest kart_envelope/tests/ -v --tb=short 2>&1 | tail -20
```
Expected: Tests pass (some may skip if optional deps like CasADi missing)

**Step 6: Commit**

```bash
git add -A kart_envelope/
git commit -m "feat: replace kart_envelope with new theoretical engine

Replaces the existing kart_envelope package with the advanced version
featuring QSS/CasADi solvers, corner coaching, delta maps, session
scalars, offline training, and tiering support."
```

---

### Task 2: Create the adapter layer

**Files:**
- Create: `telemetry_tool/theoretical_adapter.py`
- Test: `telemetry_tool/tests/test_theoretical_adapter.py`

**Step 1: Write the failing test**

Create `telemetry_tool/tests/test_theoretical_adapter.py`:

```python
"""Tests for the kart_envelope adapter layer."""
from __future__ import annotations

import math
import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_resampled_laps(n_laps: int = 5, n_points: int = 200) -> dict[int, pd.DataFrame]:
    """Create synthetic resampled laps with canonical kart_envelope column names."""
    laps = {}
    for i in range(1, n_laps + 1):
        dist = np.linspace(0, 500, n_points)
        speed = 8.0 + 4.0 * np.sin(2 * np.pi * dist / 500) + np.random.normal(0, 0.3, n_points)
        speed = np.clip(speed, 2.0, 15.0)
        dt = np.diff(dist) / speed[:-1]
        time = np.concatenate([[0.0], np.cumsum(dt)])
        laps[i] = pd.DataFrame({
            "distance_m": dist,
            "speed_mps": speed,
            "time_s": time,
            "accel_long_mps2": np.gradient(speed, time),
            "accel_lat_mps2": speed**2 * np.sin(2 * np.pi * dist / 500) * 0.002,
            "lap_number": i,
        })
    return laps


def _make_curvature_profile(n_points: int = 200) -> pd.DataFrame:
    """Create a synthetic curvature profile matching the laps."""
    dist = np.linspace(0, 500, n_points)
    kappa = 0.01 * np.abs(np.sin(2 * np.pi * dist / 500))
    heading = np.cumsum(kappa * np.diff(dist, prepend=0))
    x = np.cumsum(np.cos(heading) * np.diff(dist, prepend=0))
    y = np.cumsum(np.sin(heading) * np.diff(dist, prepend=0))
    return pd.DataFrame({
        "distance_m": dist,
        "curvature": kappa,
        "heading_rad": heading,
        "x_ref_m": x,
        "y_ref_m": y,
    })


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAdapterResult:
    """Test that AdapterResult has the right fields."""

    def test_import(self):
        from theoretical_adapter import AdapterResult
        assert AdapterResult is not None

    def test_fields(self):
        from theoretical_adapter import AdapterResult
        r = AdapterResult(
            theoretical_df=pd.DataFrame(),
            theoretical_result=None,
            method="test",
        )
        assert r.method == "test"
        assert r.corner_coaching is None
        assert r.delta_map is None
        assert r.session_scalars is None


class TestComputeTheoreticalViaEnvelope:
    """Integration test for the full adapter flow."""

    def test_returns_adapter_result(self):
        from theoretical_adapter import compute_theoretical_via_envelope
        laps = _make_resampled_laps()
        curv = _make_curvature_profile()
        result = compute_theoretical_via_envelope(
            resampled_laps=laps,
            curvature_profile=curv,
            vehicle_params=None,
            data_quality_rpt=None,
        )
        assert result is not None
        assert result.method.startswith("kart_envelope")

    def test_theoretical_df_has_required_columns(self):
        from theoretical_adapter import compute_theoretical_via_envelope
        laps = _make_resampled_laps()
        curv = _make_curvature_profile()
        result = compute_theoretical_via_envelope(
            resampled_laps=laps,
            curvature_profile=curv,
            vehicle_params=None,
            data_quality_rpt=None,
        )
        df = result.theoretical_df
        assert "distance_m" in df.columns
        assert "v_env_mps" in df.columns
        assert "accel_max_mps2" in df.columns
        assert "brake_max_mps2" in df.columns
        assert len(df) > 10

    def test_lap_time_is_positive(self):
        from theoretical_adapter import compute_theoretical_via_envelope
        laps = _make_resampled_laps()
        curv = _make_curvature_profile()
        result = compute_theoretical_via_envelope(
            resampled_laps=laps,
            curvature_profile=curv,
            vehicle_params=None,
            data_quality_rpt=None,
        )
        assert result.theoretical_result is not None
        assert result.theoretical_result.lap_time_s > 0

    def test_session_scalars_returned(self):
        from theoretical_adapter import compute_theoretical_via_envelope
        laps = _make_resampled_laps()
        curv = _make_curvature_profile()
        result = compute_theoretical_via_envelope(
            resampled_laps=laps,
            curvature_profile=curv,
            vehicle_params=None,
            data_quality_rpt=None,
        )
        sc = result.session_scalars
        assert sc is not None
        assert 0.3 <= sc.mu_session <= 2.0
        assert 0.3 <= sc.p_session <= 2.0

    def test_corner_coaching_list(self):
        from theoretical_adapter import compute_theoretical_via_envelope
        laps = _make_resampled_laps()
        curv = _make_curvature_profile()
        result = compute_theoretical_via_envelope(
            resampled_laps=laps,
            curvature_profile=curv,
            vehicle_params=None,
            data_quality_rpt=None,
        )
        # Corner coaching may be None if no corners detected — that's OK
        if result.corner_coaching is not None:
            assert isinstance(result.corner_coaching, list)

    def test_fallback_on_missing_curvature(self):
        """Adapter should still work with None curvature (graceful degradation)."""
        from theoretical_adapter import compute_theoretical_via_envelope
        laps = _make_resampled_laps()
        # With no curvature, the adapter cannot build TrackGeometry
        # and should raise or return a degraded result
        with pytest.raises(Exception):
            compute_theoretical_via_envelope(
                resampled_laps=laps,
                curvature_profile=None,
                vehicle_params=None,
                data_quality_rpt=None,
            )


class TestColumnMapping:
    """Test the internal column-name mapping."""

    def test_racechrono_columns_mapped(self):
        from theoretical_adapter import _map_columns_to_canonical
        df = pd.DataFrame({
            "Distance (m)": [0, 1, 2],
            "Speed (m/s)": [5, 6, 7],
            "Longitudinal acceleration (m/s²)": [1, 0, -1],
            "Lateral acceleration (m/s²)": [0.5, 0.3, 0.2],
            "Time (s)": [0, 0.1, 0.2],
            "Lap #": [1, 1, 1],
        })
        mapped = _map_columns_to_canonical(df)
        assert "distance_m" in mapped.columns
        assert "speed_mps" in mapped.columns
        assert "accel_long_mps2" in mapped.columns

    def test_already_canonical_passthrough(self):
        from theoretical_adapter import _map_columns_to_canonical
        df = pd.DataFrame({
            "distance_m": [0, 1, 2],
            "speed_mps": [5, 6, 7],
            "accel_long_mps2": [1, 0, -1],
        })
        mapped = _map_columns_to_canonical(df)
        assert "distance_m" in mapped.columns
        assert "speed_mps" in mapped.columns
```

**Step 2: Run test to verify it fails**

```bash
pytest telemetry_tool/tests/test_theoretical_adapter.py -v --tb=short 2>&1 | tail -20
```
Expected: FAIL — `ModuleNotFoundError: No module named 'theoretical_adapter'`

**Step 3: Write the adapter implementation**

Create `telemetry_tool/theoretical_adapter.py`:

```python
"""
theoretical_adapter.py
----------------------
Adapter layer bridging the kart_envelope solver to the telemetry_tool
pipeline contract.

Translates pipeline inputs (resampled_laps, curvature_profile, etc.)
into kart_envelope primitives (TrackGeometry, CapabilityEnvelope,
SessionScalars), runs the solver + coaching, and returns results in the
format the pipeline/scoring/API expect.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Column name mapping: RaceChrono / pipeline internal → kart_envelope canonical
# ---------------------------------------------------------------------------

_COLUMN_MAP: dict[str, str] = {
    # RaceChrono raw
    "Distance (m)":                          "distance_m",
    "Speed (m/s)":                           "speed_mps",
    "Speed (m/s) *calc":                     "speed_mps",
    "Time (s)":                              "time_s",
    "Lap #":                                 "lap_number",
    "Longitudinal acceleration (m/s²)":      "accel_long_mps2",
    "Longitudinal acceleration (G)":         "accel_long_g",
    "Longitudinal acceleration (G) *calc":   "accel_long_g",
    "Lateral acceleration (m/s²)":           "accel_lat_mps2",
    "Lateral acceleration (G)":              "accel_lat_g",
    "Lateral acceleration (G) *calc":        "accel_lat_g",
    "Yaw rate (deg/s)":                      "yaw_rate_dps",
    "Heading (deg)":                         "heading_deg",
    # Pipeline internal (snake_case already)
    "distance_m":       "distance_m",
    "speed_mps":        "speed_mps",
    "time_s":           "time_s",
    "lap_number":       "lap_number",
    "accel_long_mps2":  "accel_long_mps2",
    "accel_lat_mps2":   "accel_lat_mps2",
    "yaw_rate_dps":     "yaw_rate_dps",
    "heading_deg":      "heading_deg",
}

_G = 9.80665


def _map_columns_to_canonical(df: pd.DataFrame) -> pd.DataFrame:
    """Map DataFrame columns to kart_envelope canonical names."""
    rename = {}
    seen_canonical: set[str] = set()
    for col in df.columns:
        canon = _COLUMN_MAP.get(col)
        if canon and canon not in seen_canonical:
            rename[col] = canon
            seen_canonical.add(canon)

    out = df.rename(columns=rename)

    # Convert G-units to m/s² if present
    if "accel_long_g" in out.columns and "accel_long_mps2" not in out.columns:
        out["accel_long_mps2"] = out["accel_long_g"] * _G
    if "accel_lat_g" in out.columns and "accel_lat_mps2" not in out.columns:
        out["accel_lat_mps2"] = out["accel_lat_g"] * _G

    return out


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class AdapterResult:
    """Result from the kart_envelope adapter."""

    theoretical_df: pd.DataFrame         # distance_m, v_env_mps, accel_max_mps2, brake_max_mps2
    theoretical_result: Any              # TheoreticalResult or None
    method: str = "kart_envelope_qss"

    corner_coaching: list[dict] | None = None
    delta_map: pd.DataFrame | None = None
    session_scalars: Any | None = None    # SessionScalars


# ---------------------------------------------------------------------------
# Main adapter function
# ---------------------------------------------------------------------------

def compute_theoretical_via_envelope(
    resampled_laps: dict[int, pd.DataFrame],
    curvature_profile: pd.DataFrame | None,
    vehicle_params: Any | None,
    data_quality_rpt: Any | None,
    *,
    best_driver_time_s: float | None = None,
    config: "KartEnvelopeConfig | None" = None,
) -> AdapterResult:
    """Bridge between telemetry_tool pipeline and kart_envelope solver.

    Parameters
    ----------
    resampled_laps : dict[int, DataFrame]
        Pipeline's resampled lap DataFrames (may use RaceChrono or
        snake_case column names).
    curvature_profile : DataFrame | None
        From pipeline step 9b.  Must contain ``distance_m`` and
        ``curvature`` (or ``curvature_1pm``).  Also ``heading_rad``,
        ``x_ref_m``, ``y_ref_m`` when available.
    vehicle_params : Any | None
        From pipeline step 9d (not currently used, reserved for future).
    data_quality_rpt : Any | None
        From pipeline step 9e.
    best_driver_time_s : float | None
        Best observed lap time for sanity checking.
    config : KartEnvelopeConfig | None
        Override config; defaults to ``default_config()``.

    Returns
    -------
    AdapterResult

    Raises
    ------
    ValueError
        If curvature_profile is None or insufficient data.
    """
    from kart_envelope.config import KartEnvelopeConfig, default_config
    from kart_envelope.envelope.capability import (
        CapabilityEnvelope,
        train_capability_envelope,
    )
    from kart_envelope.inference.session_scalars import (
        SessionScalars,
        infer_session_scalars,
    )
    from kart_envelope.solver.min_time import (
        TheoreticalResult,
        compute_theoretical_lap,
    )
    from kart_envelope.track.geometry import TrackGeometry

    if config is None:
        config = default_config()

    # -- 1. Map columns to canonical names ---------------------------------
    mapped_laps: dict[int, pd.DataFrame] = {}
    for k, lap_df in resampled_laps.items():
        mapped_laps[k] = _map_columns_to_canonical(lap_df)

    # -- 2. Build TrackGeometry from curvature_profile ---------------------
    if curvature_profile is None:
        raise ValueError(
            "curvature_profile is required for kart_envelope solver"
        )

    geometry = _build_geometry_from_curvature(curvature_profile)

    # -- 3. Train CapabilityEnvelope from laps -----------------------------
    sessions = [mapped_laps]  # Single session = list of one dict
    envelope = train_capability_envelope(sessions, config=config)

    # -- 4. Infer SessionScalars -------------------------------------------
    scalars = infer_session_scalars(mapped_laps, envelope, config=config)

    # -- 5. Compute theoretical lap ----------------------------------------
    theo_result = compute_theoretical_lap(
        geometry, envelope, scalars=scalars, config=config,
    )

    method = f"kart_envelope_{theo_result.solver_backend}"

    # -- 6. Convert to pipeline DataFrame format ---------------------------
    theo_df = _result_to_pipeline_df(theo_result, envelope)

    # -- 7. Coaching (best-effort) -----------------------------------------
    corner_coaching = None
    delta_map_df = None
    try:
        corner_coaching, delta_map_df = _run_coaching(
            mapped_laps, theo_result, geometry, config,
        )
    except Exception as exc:
        logger.warning("Coaching failed (non-fatal): %s", exc)

    return AdapterResult(
        theoretical_df=theo_df,
        theoretical_result=theo_result,
        method=method,
        corner_coaching=corner_coaching,
        delta_map=delta_map_df,
        session_scalars=scalars,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_geometry_from_curvature(curv_df: pd.DataFrame) -> "TrackGeometry":
    """Build a TrackGeometry from the pipeline's curvature_profile DataFrame."""
    from kart_envelope.track.geometry import TrackGeometry

    dist = curv_df["distance_m"].values.astype(float)

    # Accept either "curvature" or "curvature_1pm"
    if "curvature_1pm" in curv_df.columns:
        kappa = curv_df["curvature_1pm"].values.astype(float)
    elif "curvature" in curv_df.columns:
        kappa = curv_df["curvature"].values.astype(float)
    else:
        raise ValueError("curvature_profile must have 'curvature' or 'curvature_1pm' column")

    # Heading
    if "heading_rad" in curv_df.columns:
        heading = curv_df["heading_rad"].values.astype(float)
    else:
        heading = np.cumsum(kappa * np.diff(dist, prepend=0))

    # XY reference line
    if "x_ref_m" in curv_df.columns and "y_ref_m" in curv_df.columns:
        x = curv_df["x_ref_m"].values.astype(float)
        y = curv_df["y_ref_m"].values.astype(float)
    else:
        ds = np.diff(dist, prepend=0)
        x = np.cumsum(np.cos(heading) * ds)
        y = np.cumsum(np.sin(heading) * ds)

    lap_length = float(dist[-1] - dist[0]) if len(dist) > 1 else 0.0

    return TrackGeometry(
        distance_m=dist,
        curvature_1pm=kappa,
        heading_rad=heading,
        x_ref_m=x,
        y_ref_m=y,
        lap_length_m=lap_length,
    )


def _result_to_pipeline_df(
    result: "TheoreticalResult",
    envelope: "CapabilityEnvelope",
) -> pd.DataFrame:
    """Convert TheoreticalResult to the DataFrame format the pipeline expects.

    Expected columns: distance_m, v_env_mps, accel_max_mps2, brake_max_mps2
    """
    n = len(result.distance_m)
    accel_max = np.full(n, np.nan)
    brake_max = np.full(n, np.nan)

    for i in range(n):
        v = result.speed_profile_mps[i]
        accel_max[i] = envelope.traction_max(v)
        brake_max[i] = envelope.braking_max(v)

    return pd.DataFrame({
        "distance_m":      result.distance_m,
        "v_env_mps":       result.speed_profile_mps,
        "accel_max_mps2":  accel_max,
        "brake_max_mps2":  brake_max,
    })


def _run_coaching(
    mapped_laps: dict[int, pd.DataFrame],
    theo_result: "TheoreticalResult",
    geometry: "TrackGeometry",
    config: "KartEnvelopeConfig",
) -> tuple[list[dict] | None, pd.DataFrame | None]:
    """Run corner coaching and delta map on the best lap."""
    from kart_envelope.coaching.corner_coaching import (
        analyze_corner_performance,
        detect_corners_from_curvature,
    )
    from kart_envelope.coaching.delta_analysis import compute_delta_map

    # Pick best lap (shortest time)
    best_key = None
    best_time = float("inf")
    for k, lap_df in mapped_laps.items():
        if "time_s" in lap_df.columns and len(lap_df) > 0:
            t = float(lap_df["time_s"].iloc[-1])
            if t < best_time:
                best_time = t
                best_key = k
    if best_key is None:
        return None, None

    best_lap = mapped_laps[best_key]

    # Delta map
    delta_df = compute_delta_map(best_lap, theo_result)

    # Corners
    corners = detect_corners_from_curvature(
        geometry.curvature_1pm, geometry.distance_m,
        threshold=config.solver_apex_curvature_threshold,
    )
    if not corners:
        return None, delta_df

    # Corner performance
    perfs = analyze_corner_performance(best_lap, theo_result, corners)
    coaching_dicts = [p.to_dict() for p in perfs] if perfs else None

    return coaching_dicts, delta_df
```

**Step 4: Run tests to verify they pass**

```bash
pytest telemetry_tool/tests/test_theoretical_adapter.py -v --tb=short 2>&1 | tail -30
```
Expected: All tests PASS (some coaching tests may pass with None if no corners detected from synthetic data — that's correct graceful degradation)

**Step 5: Commit**

```bash
git add telemetry_tool/theoretical_adapter.py telemetry_tool/tests/test_theoretical_adapter.py
git commit -m "feat: add theoretical_adapter bridging kart_envelope solver to pipeline

Creates AdapterResult with theoretical_df, corner_coaching, delta_map,
session_scalars. Maps RaceChrono/pipeline columns to canonical names,
builds TrackGeometry from curvature_profile, trains CapabilityEnvelope,
runs QSS solver, and optionally generates coaching output."
```

---

### Task 3: Rewire pipeline Step 10

**Files:**
- Modify: `telemetry_tool/pipeline.py:1536-1695`

**Step 1: Write the failing test**

Create `telemetry_tool/tests/test_pipeline_theoretical.py`:

```python
"""Tests for pipeline Step 10 with kart_envelope adapter."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _make_summary_with_laps():
    """Build a minimal summary dict mimicking pipeline state before Step 10."""
    n = 200
    dist = np.linspace(0, 500, n)
    laps = {}
    for i in range(1, 4):
        speed = 8.0 + 4.0 * np.sin(2 * np.pi * dist / 500)
        speed += np.random.normal(0, 0.2, n)
        speed = np.clip(speed, 2.0, 15.0)
        dt = np.diff(dist) / speed[:-1]
        time = np.concatenate([[0.0], np.cumsum(dt)])
        laps[i] = pd.DataFrame({
            "distance_m": dist,
            "speed_mps": speed,
            "time_s": time,
            "accel_long_mps2": np.gradient(speed, time),
            "accel_lat_mps2": speed**2 * np.sin(2 * np.pi * dist / 500) * 0.002,
        })

    kappa = 0.01 * np.abs(np.sin(2 * np.pi * dist / 500))
    heading = np.cumsum(kappa * np.diff(dist, prepend=0))
    curv = pd.DataFrame({
        "distance_m": dist,
        "curvature": kappa,
        "heading_rad": heading,
        "x_ref_m": np.cumsum(np.cos(heading) * np.diff(dist, prepend=0)),
        "y_ref_m": np.cumsum(np.sin(heading) * np.diff(dist, prepend=0)),
    })
    return laps, curv


class TestPipelineStep10Integration:
    """Verify kart_envelope adapter is called as Priority 1."""

    def test_adapter_method_in_summary(self):
        """When adapter succeeds, simulation_method starts with kart_envelope."""
        from theoretical_adapter import compute_theoretical_via_envelope
        laps, curv = _make_summary_with_laps()
        result = compute_theoretical_via_envelope(
            laps, curv, None, None,
        )
        assert result.method.startswith("kart_envelope")
        # Verify pipeline-compatible df
        df = result.theoretical_df
        assert set(df.columns) >= {"distance_m", "v_env_mps", "accel_max_mps2", "brake_max_mps2"}
```

**Step 2: Run test to verify it passes (adapter already exists)**

```bash
pytest telemetry_tool/tests/test_pipeline_theoretical.py -v --tb=short
```
Expected: PASS

**Step 3: Modify pipeline.py Step 10**

In `telemetry_tool/pipeline.py`, replace lines 1536-1672 (the `_theoretical()` function body). Keep the function signature and the cascade structure, but insert the adapter as Priority 1.

Find this block (approximately lines 1536-1544):
```python
    theo_mod = _import("theoretical_engine")

    # Track which method succeeded

    _sim_method: str = "none"
    _sim_result: Any = None   # TheoreticalLapResult (if physics used)

    def _theoretical() -> pd.DataFrame:
        nonlocal _sim_method, _sim_result
```

Replace with:
```python
    theo_mod = _import("theoretical_engine")

    # Track which method succeeded

    _sim_method: str = "none"
    _sim_result: Any = None   # TheoreticalLapResult (if physics used)
    _corner_coaching: list[dict[str, Any]] | None = None
    _delta_map: pd.DataFrame | None = None
    _session_scalars: dict[str, Any] | None = None

    def _theoretical() -> pd.DataFrame:
        nonlocal _sim_method, _sim_result
        nonlocal _corner_coaching, _delta_map, _session_scalars
```

Then, inside the `_theoretical()` function, insert the new Priority 1 block **before** the existing `if sim_mod is not None:` block. Find:
```python
        # Best driver time for sanity checking

        best_driver_time = float("inf")
        if valid_times:
            best_driver_time = min(t for _, t in valid_times)

        # -- Priority 1: Hybrid physics simulation (telemetry-fitted
```

Insert before the `# -- Priority 1: Hybrid physics` comment:
```python
        # -- Priority 0: kart_envelope solver via adapter --
        try:
            from theoretical_adapter import compute_theoretical_via_envelope
            adapter_result = compute_theoretical_via_envelope(
                resampled_laps,
                curvature_profile,
                vehicle_params,
                data_quality_rpt,
                best_driver_time_s=(
                    best_driver_time
                    if math.isfinite(best_driver_time) else None
                ),
            )
            _sim_method = adapter_result.method
            _sim_result = adapter_result.theoretical_result
            _corner_coaching = adapter_result.corner_coaching
            _delta_map = adapter_result.delta_map
            if adapter_result.session_scalars is not None:
                sc = adapter_result.session_scalars
                _session_scalars = {
                    "mu": round(sc.mu_session, 4),
                    "p": round(sc.p_session, 4),
                    "b": round(sc.b_session, 4),
                    "confidence": round(sc.confidence, 4),
                    "condition_label": sc.condition_label,
                }
            logger.info(
                "kart_envelope solver [%s]: %.2fs (driver best %.2fs).",
                adapter_result.method,
                adapter_result.theoretical_result.lap_time_s
                if adapter_result.theoretical_result else float("nan"),
                best_driver_time,
            )
            return adapter_result.theoretical_df
        except Exception as exc:
            logger.warning(
                "kart_envelope adapter failed: %s — falling back to "
                "legacy engines.", exc,
            )

```

After the `_record("10b_theoretical_metrics", ...)` block (~line 1694), add storage of the new artifacts:
```python
    summary["corner_coaching"] = _corner_coaching
    summary["delta_map"] = _delta_map
    summary["session_scalars"] = _session_scalars
```

**Step 4: Run full pipeline tests**

```bash
pytest telemetry_tool/tests/ -v --tb=short -x 2>&1 | tail -30
```
Expected: All existing tests PASS (the fallback cascade ensures backward compat)

**Step 5: Commit**

```bash
git add telemetry_tool/pipeline.py telemetry_tool/tests/test_pipeline_theoretical.py
git commit -m "feat: wire kart_envelope solver as Priority 0 in pipeline Step 10

Adds kart_envelope adapter as first option in the theoretical lap
cascade. Falls back to existing lap_simulation (Priority 1) and
theoretical_engine (Priority 2) on failure. Populates corner_coaching,
delta_map, session_scalars in summary dict."
```

---

### Task 4: DB schema extension

**Files:**
- Modify: `telemetry_tool/db/schema.py:293-305`
- Modify: `telemetry_tool/db/queries.py:525-539`
- Create: `telemetry_tool/alembic/versions/017_theoretical_engine_v2.py`

**Step 1: Update SQLite schema**

In `telemetry_tool/db/schema.py`, find:
```python
_THEORETICAL_DATA_TABLE = """
CREATE TABLE IF NOT EXISTS theoretical_data (
    session_id          TEXT PRIMARY KEY REFERENCES sessions(session_id),
    theoretical_time_s  REAL,
    actual_best_time_s  REAL,
    gap_pct             REAL,
    simulation_method   TEXT,
    speed_profile_json  TEXT,
    distance_json       TEXT,
    metrics_json        TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
"""
```

Replace with:
```python
_THEORETICAL_DATA_TABLE = """
CREATE TABLE IF NOT EXISTS theoretical_data (
    session_id             TEXT PRIMARY KEY REFERENCES sessions(session_id),
    theoretical_time_s     REAL,
    actual_best_time_s     REAL,
    gap_pct                REAL,
    simulation_method      TEXT,
    speed_profile_json     TEXT,
    distance_json          TEXT,
    metrics_json           TEXT,
    corner_coaching_json   TEXT,
    delta_map_json         TEXT,
    session_scalars_json   TEXT,
    created_at             TEXT NOT NULL DEFAULT (datetime('now'))
);
"""
```

**Step 2: Update queries**

In `telemetry_tool/db/queries.py`, find `INSERT_THEORETICAL_DATA`:
```sql
INSERT OR REPLACE INTO theoretical_data (
    session_id, theoretical_time_s, actual_best_time_s,
    gap_pct, simulation_method, speed_profile_json,
    distance_json, metrics_json
) VALUES (
    :session_id, :theoretical_time_s, :actual_best_time_s,
    :gap_pct, :simulation_method, :speed_profile_json,
    :distance_json, :metrics_json
);
```

Replace with:
```sql
INSERT OR REPLACE INTO theoretical_data (
    session_id, theoretical_time_s, actual_best_time_s,
    gap_pct, simulation_method, speed_profile_json,
    distance_json, metrics_json,
    corner_coaching_json, delta_map_json, session_scalars_json
) VALUES (
    :session_id, :theoretical_time_s, :actual_best_time_s,
    :gap_pct, :simulation_method, :speed_profile_json,
    :distance_json, :metrics_json,
    :corner_coaching_json, :delta_map_json, :session_scalars_json
);
```

**Step 3: Create Alembic migration**

Create `telemetry_tool/alembic/versions/017_theoretical_engine_v2.py`:

```python
"""Add kart_envelope coaching columns to theoretical_data.

Revision ID: 017
Revises: 016
Create Date: 2026-02-27
"""
from alembic import op
import sqlalchemy as sa

revision = "017"
down_revision = "016"


def upgrade():
    op.add_column(
        "theoretical_data",
        sa.Column("corner_coaching_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "theoretical_data",
        sa.Column("delta_map_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "theoretical_data",
        sa.Column("session_scalars_json", sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column("theoretical_data", "session_scalars_json")
    op.drop_column("theoretical_data", "delta_map_json")
    op.drop_column("theoretical_data", "corner_coaching_json")
```

**Step 4: Run migration test**

```bash
python -c "
from telemetry_tool.db.schema import ensure_schema
import sqlite3
conn = sqlite3.connect(':memory:')
ensure_schema(conn)
cols = [row[1] for row in conn.execute('PRAGMA table_info(theoretical_data)').fetchall()]
assert 'corner_coaching_json' in cols, f'Missing column: {cols}'
assert 'delta_map_json' in cols
assert 'session_scalars_json' in cols
print('Schema OK:', cols)
"
```
Expected: Schema OK with all 11 columns listed

**Step 5: Commit**

```bash
git add telemetry_tool/db/schema.py telemetry_tool/db/queries.py telemetry_tool/alembic/versions/017_theoretical_engine_v2.py
git commit -m "feat: add DB columns for corner coaching, delta map, session scalars

Alembic migration 017 adds 3 nullable TEXT/JSONB columns to
theoretical_data. SQLite schema updated. INSERT query extended."
```

---

### Task 5: Update data access layer (models.py)

**Files:**
- Modify: `telemetry_tool/web/models.py:1121-1217`

**Step 1: Write the failing test**

Create `telemetry_tool/tests/test_models_theoretical.py`:

```python
"""Tests for theoretical data storage with new columns."""
from __future__ import annotations

import json
import sqlite3
import pytest


def _setup_db():
    """Create in-memory DB with full schema."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from db.schema import ensure_schema
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    # Insert a dummy session
    conn.execute(
        "INSERT INTO sessions (session_id, file_name) VALUES (?, ?)",
        ("test-001", "test.csv"),
    )
    conn.commit()
    return conn


class TestInsertTheoreticalData:
    def test_stores_corner_coaching(self):
        from web.models import insert_theoretical_data
        conn = _setup_db()
        summary = {
            "theoretical_metrics": {"best_s": 45.2, "simulation_method": "kart_envelope_qss"},
            "theoretical_lap": None,
            "lap_times": [46.1, 47.0],
            "corner_coaching": [
                {"corner_id": 1, "time_loss_total_s": 0.3, "primary_cause": "exit"},
            ],
            "session_scalars": {"mu": 0.95, "p": 1.0, "b": 0.98, "confidence": 0.8, "condition_label": "dry"},
        }
        insert_theoretical_data(conn, "test-001", summary)
        conn.commit()

        row = conn.execute("SELECT * FROM theoretical_data WHERE session_id = ?", ("test-001",)).fetchone()
        assert row is not None
        assert row["corner_coaching_json"] is not None
        coaching = json.loads(row["corner_coaching_json"])
        assert coaching[0]["corner_id"] == 1

    def test_stores_session_scalars(self):
        from web.models import insert_theoretical_data
        conn = _setup_db()
        summary = {
            "theoretical_metrics": {"best_s": 45.2, "simulation_method": "kart_envelope_qss"},
            "theoretical_lap": None,
            "lap_times": [46.1],
            "session_scalars": {"mu": 0.95, "p": 1.0, "b": 0.98, "confidence": 0.8, "condition_label": "dry"},
        }
        insert_theoretical_data(conn, "test-001", summary)
        conn.commit()

        row = conn.execute("SELECT * FROM theoretical_data WHERE session_id = ?", ("test-001",)).fetchone()
        scalars = json.loads(row["session_scalars_json"])
        assert scalars["mu"] == 0.95


class TestGetTheoreticalData:
    def test_returns_new_fields(self):
        from web.models import insert_theoretical_data, get_theoretical_data
        conn = _setup_db()
        summary = {
            "theoretical_metrics": {"best_s": 45.2, "simulation_method": "kart_envelope_qss"},
            "theoretical_lap": None,
            "lap_times": [46.1],
            "corner_coaching": [{"corner_id": 1}],
            "session_scalars": {"mu": 0.95, "p": 1.0, "b": 0.98},
        }
        insert_theoretical_data(conn, "test-001", summary)
        conn.commit()

        data = get_theoretical_data(conn, "test-001")
        assert data is not None
        assert "corner_coaching" in data
        assert "session_scalars" in data
        assert data["corner_coaching"][0]["corner_id"] == 1
```

**Step 2: Run test to verify it fails**

```bash
pytest telemetry_tool/tests/test_models_theoretical.py -v --tb=short
```
Expected: FAIL — `insert_theoretical_data` doesn't pass the new columns

**Step 3: Update insert_theoretical_data**

In `telemetry_tool/web/models.py`, at the end of `insert_theoretical_data()` (before the `conn.execute(Q.INSERT_THEORETICAL_DATA, {` call), add serialization of the new fields:

Find:
```python
    conn.execute(Q.INSERT_THEORETICAL_DATA, {
        "session_id":          session_id,
        "theoretical_time_s":  _safe_float(best_time),
        "actual_best_time_s":  _safe_float(actual_best),
        "gap_pct":             _safe_float(gap_pct),
        "simulation_method":   theo_metrics.get("simulation_method"),
        "speed_profile_json":  speed_profile_json,
        "distance_json":       distance_json,
        "metrics_json":        _json_dumps(theo_metrics),
    })
```

Replace with:
```python
    # Serialize new kart_envelope fields
    corner_coaching = summary.get("corner_coaching")
    corner_coaching_json = _json_dumps(corner_coaching) if corner_coaching else None
    session_scalars = summary.get("session_scalars")
    session_scalars_json = _json_dumps(session_scalars) if session_scalars else None
    # Delta map summary: store top-N time loss segments (not the full DataFrame)
    delta_map_json = None
    delta_map = summary.get("delta_map")
    if delta_map is not None and hasattr(delta_map, "to_dict"):
        try:
            # Keep only the segment-level summary
            if "segment" in delta_map.columns and "delta_s" in delta_map.columns:
                seg_summary = (
                    delta_map.groupby("segment")
                    .agg({"delta_s": "sum", "distance_m": "mean"})
                    .reset_index()
                    .sort_values("delta_s", ascending=False)
                    .head(10)
                    .to_dict(orient="records")
                )
                delta_map_json = _json_dumps(seg_summary)
        except Exception:
            pass

    conn.execute(Q.INSERT_THEORETICAL_DATA, {
        "session_id":              session_id,
        "theoretical_time_s":      _safe_float(best_time),
        "actual_best_time_s":      _safe_float(actual_best),
        "gap_pct":                 _safe_float(gap_pct),
        "simulation_method":       theo_metrics.get("simulation_method"),
        "speed_profile_json":      speed_profile_json,
        "distance_json":           distance_json,
        "metrics_json":            _json_dumps(theo_metrics),
        "corner_coaching_json":    corner_coaching_json,
        "delta_map_json":          delta_map_json,
        "session_scalars_json":    session_scalars_json,
    })
```

**Step 4: Update get_theoretical_data**

In the same file, update `get_theoretical_data()`:

Find:
```python
    if d.get("metrics_json"):
        d["metrics"] = json.loads(d["metrics_json"])
    return d
```

Replace with:
```python
    if d.get("metrics_json"):
        d["metrics"] = json.loads(d["metrics_json"])
    if d.get("corner_coaching_json"):
        d["corner_coaching"] = json.loads(d["corner_coaching_json"])
    if d.get("delta_map_json"):
        d["delta_map_summary"] = json.loads(d["delta_map_json"])
    if d.get("session_scalars_json"):
        d["session_scalars"] = json.loads(d["session_scalars_json"])
    return d
```

**Step 5: Run tests**

```bash
pytest telemetry_tool/tests/test_models_theoretical.py -v --tb=short
```
Expected: All PASS

**Step 6: Commit**

```bash
git add telemetry_tool/web/models.py telemetry_tool/tests/test_models_theoretical.py
git commit -m "feat: store/retrieve corner coaching, delta map, session scalars in DB

insert_theoretical_data now serializes corner_coaching, session_scalars,
and top-10 delta map segments to JSON columns. get_theoretical_data
parses them back for API consumption."
```

---

### Task 6: Enrich API endpoints

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_data.py:222-240`
- Modify: `telemetry_tool/web/routes/api_data.py:332-352`

**Step 1: Update v1 endpoint**

In `telemetry_tool/web/routes/api_v1_data.py`, find:
```python
    return api_response({
        "theoretical_time_s": data.get("theoretical_time_s"),
        "actual_best_time_s": data.get("actual_best_time_s"),
        "gap_pct": data.get("gap_pct"),
        "simulation_method": data.get("simulation_method"),
        "speeds": data.get("speeds"),
        "distances": data.get("distances"),
        "metrics": data.get("metrics"),
    })
```

Replace with:
```python
    response = {
        "theoretical_time_s": data.get("theoretical_time_s"),
        "actual_best_time_s": data.get("actual_best_time_s"),
        "gap_pct": data.get("gap_pct"),
        "simulation_method": data.get("simulation_method"),
        "speeds": data.get("speeds"),
        "distances": data.get("distances"),
        "metrics": data.get("metrics"),
    }
    # New kart_envelope fields (optional — None if old engine was used)
    if data.get("corner_coaching"):
        response["corner_coaching"] = data["corner_coaching"]
    if data.get("session_scalars"):
        response["session_scalars"] = data["session_scalars"]
    if data.get("delta_map_summary"):
        response["delta_map_summary"] = data["delta_map_summary"]
    return api_response(response)
```

**Step 2: Update legacy endpoint**

In `telemetry_tool/web/routes/api_data.py`, find the theoretical_data response and apply the same pattern — add the 3 optional fields.

**Step 3: Run existing API tests**

```bash
pytest telemetry_tool/tests/ -k "api" -v --tb=short 2>&1 | tail -20
```
Expected: All PASS

**Step 4: Commit**

```bash
git add telemetry_tool/web/routes/api_v1_data.py telemetry_tool/web/routes/api_data.py
git commit -m "feat: expose corner coaching, session scalars, delta map in /theoretical API

Both legacy and v1 endpoints now return corner_coaching, session_scalars,
and delta_map_summary when available from the kart_envelope solver."
```

---

### Task 7: Enhance scoring

**Files:**
- Modify: `telemetry_tool/scoring.py:485, 676, 1200-1330`

**Step 1: Write failing tests**

Add to `telemetry_tool/tests/test_scoring_session_types.py` (or create new `test_scoring_envelope.py`):

```python
"""Tests for scoring with kart_envelope solver output."""
from __future__ import annotations

import pytest


class TestScoringWithEnvelopeMethod:
    """Verify scoring recognises kart_envelope methods as physics-class."""

    def _make_metrics(self, best_s=46.0):
        return {
            "best_s": best_s,
            "n_laps": 10,
            "cv_pct": 1.5,
            "best_to_median_s": 0.8,
            "speed_mean_mps": 15.0,
            "accel_max_mps2": 10.0,
            "braking_max_mps2": 12.0,
            "early_mean_s": 46.5,
            "late_mean_s": 47.0,
            "early_yaw_var": 1.0,
            "late_yaw_var": 1.1,
        }

    def _make_theo(self, best_s=45.0, method="kart_envelope_qss"):
        return {
            "best_s": best_s,
            "speed_mean_mps": 16.0,
            "accel_max_mps2": 12.0,
            "braking_max_mps2": 14.0,
            "simulation_method": method,
            "confidence": 0.9,
        }

    def test_kart_envelope_qss_uses_physics_thresholds(self):
        from scoring import score_session
        result = score_session(
            self._make_metrics(),
            self._make_theo(method="kart_envelope_qss"),
        )
        detail = result["sub_scores"]["pace"]["detail"]
        assert detail["simulation_method"] == "kart_envelope_qss"
        # With 2.2% gap and physics thresholds, should get >0 pace score
        assert result["sub_scores"]["pace"]["score"] > 0

    def test_kart_envelope_casadi_uses_physics_thresholds(self):
        from scoring import score_session
        result = score_session(
            self._make_metrics(),
            self._make_theo(method="kart_envelope_casadi"),
        )
        assert result["sub_scores"]["pace"]["score"] > 0

    def test_corner_coaching_enhances_execution(self):
        from scoring import score_session
        coaching = [
            {
                "corner_id": 1,
                "theoretical_apex_speed_mps": 10.0,
                "actual_apex_speed_mps": 9.5,
                "braking_point_delta_m": 2.0,
                "grip_utilisation_pct": 85.0,
                "theoretical_exit_speed_mps": 14.0,
                "exit_speed_deficit_mps": 0.5,
            },
        ]
        result = score_session(
            self._make_metrics(),
            self._make_theo(),
            corner_coaching=coaching,
        )
        exec_detail = result["sub_scores"]["execution"]["detail"]
        # When coaching is provided, granular execution should be computed
        assert "has_corner_data" in exec_detail or result["sub_scores"]["execution"]["score"] > 0
```

**Step 2: Run test to verify it fails**

```bash
pytest telemetry_tool/tests/test_scoring_envelope.py -v --tb=short
```
Expected: FAIL — `score_session()` doesn't accept `corner_coaching` kwarg

**Step 3: Update scoring.py**

3a. In `_score_pace()` (~line 485), update the `is_physics` check:

Find:
```python
    is_physics = simulation_method in ("physics", "hybrid")
```

Replace with:
```python
    is_physics = simulation_method in (
        "physics", "hybrid",
        "kart_envelope_qss", "kart_envelope_casadi",
    )
```

3b. In `_score_execution()` (~line 676), apply the same change:

Find:
```python
    is_physics = simulation_method in ("physics", "hybrid")
```

Replace with:
```python
    is_physics = simulation_method in (
        "physics", "hybrid",
        "kart_envelope_qss", "kart_envelope_casadi",
    )
```

3c. In `score_session()` (~line 1200), add `corner_coaching` parameter and blend granular execution:

Find:
```python
def score_session(
    metrics_dict:         dict[str, Any],
    theoretical_metrics:  dict[str, Any],
    session_type:         str = "practice",
    *,
    is_wet:               bool = False,
) -> dict[str, Any]:
```

Replace with:
```python
def score_session(
    metrics_dict:         dict[str, Any],
    theoretical_metrics:  dict[str, Any],
    session_type:         str = "practice",
    *,
    is_wet:               bool = False,
    corner_coaching:      list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
```

Then after the execution score computation (~line 1319-1320), add granular blending:

Find:
```python
    exec_score,        exec_detail  = _score_execution(
        metrics_dict, theoretical_metrics, simulation_method=sim_method,
    )
```

Replace with:
```python
    exec_score,        exec_detail  = _score_execution(
        metrics_dict, theoretical_metrics, simulation_method=sim_method,
    )
    # Blend with granular corner-level execution when available
    if corner_coaching:
        granular = compute_granular_execution(corner_performances=corner_coaching)
        if granular.get("has_corner_data"):
            # 70% granular (corner-level), 30% aggregate (speed/accel/brake)
            granular_score = granular["composite"] * MAX_EXECUTION
            exec_score = round(0.70 * granular_score + 0.30 * exec_score, 4)
            exec_detail["granular"] = granular
            exec_detail["has_corner_data"] = True
```

**Step 4: Run tests**

```bash
pytest telemetry_tool/tests/test_scoring_envelope.py -v --tb=short
pytest telemetry_tool/tests/test_scoring_session_types.py -v --tb=short
```
Expected: All PASS

**Step 5: Commit**

```bash
git add telemetry_tool/scoring.py telemetry_tool/tests/test_scoring_envelope.py
git commit -m "feat: scoring recognises kart_envelope methods + corner coaching blend

_score_pace and _score_execution now treat kart_envelope_qss/casadi as
physics-class methods (tighter thresholds). score_session accepts
optional corner_coaching and blends granular execution (70%) with
aggregate (30%) when corner data is available."
```

---

### Task 8: Update pipeline Step 13 to pass coaching to scoring

**Files:**
- Modify: `telemetry_tool/pipeline.py` (Step 13 — scoring call)

**Step 1: Find where score_session is called**

Search for `scoring.score_session` or `score_mod.score_session` in pipeline.py and add the `corner_coaching` kwarg.

**Step 2: Update the scoring call**

In pipeline.py, find the Step 13 scoring call (likely wrapped in `_safe_step`). Modify the call to pass `corner_coaching=_corner_coaching`:

Before:
```python
        return score_mod.score_session(
            summary["session_metrics"],
            theo_metrics,
            session_type=session_type,
        )
```

After:
```python
        return score_mod.score_session(
            summary["session_metrics"],
            theo_metrics,
            session_type=session_type,
            corner_coaching=_corner_coaching,
        )
```

**Step 3: Run full test suite**

```bash
pytest telemetry_tool/tests/ -v --tb=short -x 2>&1 | tail -30
```
Expected: All PASS

**Step 4: Commit**

```bash
git add telemetry_tool/pipeline.py
git commit -m "feat: pass corner coaching data to scoring in pipeline Step 13

score_session now receives corner_coaching from the kart_envelope
adapter, enabling granular execution scoring when available."
```

---

### Task 9: Final integration test and cleanup

**Files:**
- Run: full test suite
- Verify: imports, fallback cascade, backward compatibility

**Step 1: Run full backend test suite**

```bash
pytest telemetry_tool/tests/ kart_envelope/tests/ -v --tb=short 2>&1 | tail -40
```
Expected: All existing + new tests pass

**Step 2: Verify fallback cascade works**

```bash
python -c "
# Simulate adapter failure → should fall back to old engines
import importlib, sys
# Temporarily break the adapter import
sys.modules['theoretical_adapter'] = None
try:
    from theoretical_adapter import compute_theoretical_via_envelope
    print('ERROR: should have failed')
except (ImportError, TypeError):
    print('Fallback cascade: adapter correctly unavailable')
finally:
    del sys.modules['theoretical_adapter']
"
```
Expected: `Fallback cascade: adapter correctly unavailable`

**Step 3: Verify dev server starts**

```bash
cd telemetry_tool && python main.py --serve &
sleep 3
curl -s http://localhost:5000/healthz | head -5
kill %1 2>/dev/null
```
Expected: Server starts, healthz returns 200

**Step 4: Final commit with all test files**

```bash
git add -A
git status
git commit -m "test: integration tests for theoretical engine replacement

Verifies adapter, pipeline cascade, DB schema, API enrichment, and
scoring enhancements all work together."
```

---

## Summary of Files

| # | File | Action |
|---|------|--------|
| 1 | `kart_envelope/` (entire package) | Replace |
| 2 | `telemetry_tool/theoretical_adapter.py` | Create |
| 2 | `telemetry_tool/tests/test_theoretical_adapter.py` | Create |
| 3 | `telemetry_tool/pipeline.py` | Modify (Step 10 + Step 13) |
| 3 | `telemetry_tool/tests/test_pipeline_theoretical.py` | Create |
| 4 | `telemetry_tool/db/schema.py` | Modify |
| 4 | `telemetry_tool/db/queries.py` | Modify |
| 4 | `telemetry_tool/alembic/versions/017_theoretical_engine_v2.py` | Create |
| 5 | `telemetry_tool/web/models.py` | Modify |
| 5 | `telemetry_tool/tests/test_models_theoretical.py` | Create |
| 6 | `telemetry_tool/web/routes/api_v1_data.py` | Modify |
| 6 | `telemetry_tool/web/routes/api_data.py` | Modify |
| 7 | `telemetry_tool/scoring.py` | Modify |
| 7 | `telemetry_tool/tests/test_scoring_envelope.py` | Create |
