"""Day-10 RC6 — sensor_quality producer module unit tests.

The producer is meant to be safe to call on any per-session resampled-laps
input that comes out of the lap_web pipeline (stage s10d). These tests
cover:

  * graceful return-None on insufficient inputs
  * structural contract of the returned dict
  * per-bin array length matches track_surface.frenet.n_points
  * orientation_quality saturates in ``[0, 1]``
  * bank_sensitivity_deg saturates in ``[-5, +5]``
  * curvature_agreement is finite (0 where no samples)
  * map_confidence.excited_sample_frac is in ``[0, 1]``
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TELEMETRY_PKG = _REPO_ROOT / "telemetry_tool"
for _p in (_REPO_ROOT, _TELEMETRY_PKG):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from track_surface.sensor_quality import compute_session_sensor_quality  # noqa: E402


# ── synthetic fixtures ─────────────────────────────────────────────────


def _make_circle_centerline(radius: float = 50.0, n: int = 200):
    """Build a TrackSurface-like stub from a circle. Just exposes frenet
    with centerline_xy + s_grid + n_points — what the producer reads."""
    from track_surface.frenet import FrenetFrame
    theta = np.linspace(0, 2 * np.pi, n, endpoint=False)
    xy = np.column_stack([radius * np.cos(theta), radius * np.sin(theta)])
    frenet = FrenetFrame.from_centerline(xy)

    class _Surface:
        def __init__(self, fr):
            self.frenet = fr
            # Mimic the real TrackSurface's lat/lon ref attrs (not required;
            # producer falls back to lap-mean projection if absent).

    return _Surface(frenet)


def _make_lap_df(
    radius: float, n_samples: int, v_mps: float, alat_g_const: float,
    seed: int = 0,
) -> pd.DataFrame:
    """One lap of a circular track at constant speed + constant a_lat."""
    rng = np.random.default_rng(seed)
    theta = np.linspace(0, 2 * np.pi, n_samples, endpoint=False)
    lat = 48.0 + radius * np.cos(theta) / 111_320.0
    lon = 1.0 + radius * np.sin(theta) / (111_320.0 * np.cos(np.radians(48.0)))
    speed = np.full(n_samples, v_mps) + rng.normal(0, 0.5, n_samples)
    alat = np.full(n_samples, alat_g_const) + rng.normal(0, 0.02, n_samples)
    return pd.DataFrame({
        "lat_deg": lat,
        "lon_deg": lon,
        "speed_mps": speed,
        "accel_lat_g": alat,
        "time_s": np.linspace(0, n_samples * 0.1, n_samples),
    })


# ── tests ──────────────────────────────────────────────────────────────


def test_returns_none_on_empty_laps():
    surface = _make_circle_centerline()
    assert compute_session_sensor_quality({}, surface) is None
    assert compute_session_sensor_quality(None, surface) is None


def test_returns_none_on_no_surface():
    df = _make_lap_df(50.0, 200, 15.0, 0.5)
    assert compute_session_sensor_quality({1: df}, None) is None


def test_returns_none_on_missing_required_columns():
    """If lat/lon/speed/a_lat are absent, the lap is dropped; with no laps
    the producer returns None."""
    surface = _make_circle_centerline()
    bad_df = pd.DataFrame({"unrelated": [1.0, 2.0]})
    assert compute_session_sensor_quality({1: bad_df}, surface) is None


def test_structural_contract_per_bin_arrays_match_n_points():
    surface = _make_circle_centerline(radius=50.0, n=200)
    laps = {i: _make_lap_df(50.0, 200, 15.0, 0.5, seed=i) for i in range(1, 4)}
    out = compute_session_sensor_quality(laps, surface)
    assert out is not None
    n = surface.frenet.n_points
    assert len(out["orientation_quality"]) == n
    assert len(out["curvature_agreement"]) == n
    assert len(out["bank_sensitivity_deg"]) == n
    assert len(out["map_confidence"]["confidence_per_bin"]) == n


def test_orientation_quality_in_unit_interval():
    surface = _make_circle_centerline(radius=50.0, n=200)
    laps = {i: _make_lap_df(50.0, 200, 15.0, 0.5, seed=i) for i in range(1, 4)}
    out = compute_session_sensor_quality(laps, surface)
    arr = np.asarray(out["orientation_quality"])
    assert (arr >= 0.0).all()
    assert (arr <= 1.0).all()


def test_bank_sensitivity_clamped_to_plusminus_5_deg():
    surface = _make_circle_centerline(radius=50.0, n=200)
    laps = {i: _make_lap_df(50.0, 200, 15.0, 0.5, seed=i) for i in range(1, 4)}
    out = compute_session_sensor_quality(laps, surface)
    arr = np.asarray(out["bank_sensitivity_deg"])
    assert (arr >= -5.0).all()
    assert (arr <= +5.0).all()


def test_excited_sample_frac_is_unit_interval():
    surface = _make_circle_centerline(radius=50.0, n=200)
    laps = {i: _make_lap_df(50.0, 200, 15.0, 0.5, seed=i) for i in range(1, 4)}
    out = compute_session_sensor_quality(laps, surface)
    f = out["map_confidence"]["excited_sample_frac"]
    assert 0.0 <= f <= 1.0


def test_curvature_agreement_is_finite():
    """All values must be finite — 0.0 where insufficient samples, a real
    median ratio elsewhere."""
    surface = _make_circle_centerline(radius=50.0, n=200)
    laps = {i: _make_lap_df(50.0, 200, 15.0, 0.5, seed=i) for i in range(1, 4)}
    out = compute_session_sensor_quality(laps, surface)
    arr = np.asarray(out["curvature_agreement"])
    assert np.isfinite(arr).all()


def test_constant_lap_replicas_give_high_confidence():
    """3 perfectly clean replicas of the same lap → confidence should be
    high in the steady-state region (lots of samples, consistent calibration)."""
    surface = _make_circle_centerline(radius=50.0, n=200)
    # Sufficient samples per bin: 3 laps × 200 samples = 600 samples across
    # 200 bins ≈ 3 per bin on average. Push lap_samples high so we exceed
    # the n_all > 30 saturation point for count_score.
    laps = {i: _make_lap_df(50.0, 2000, 15.0, 0.5, seed=i) for i in range(1, 6)}
    out = compute_session_sensor_quality(laps, surface)
    arr = np.asarray(out["orientation_quality"])
    # At least the median bin should be > 0.5 with this much data.
    assert float(np.median(arr)) >= 0.5


# ── Real-session integration test (skipped when CSV fixtures absent) ──


def _resolve_csv(session: str) -> Path | None:
    """Same multi-candidate resolver as test_boundary_geometric_correctness."""
    import os
    env = os.environ.get("LAP_DATA_RAW")
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env) / session)
    candidates.append(_REPO_ROOT / "data" / "raw" / session)
    candidates.append(_REPO_ROOT.parent / "Analysis" / "V2_claude_ai" / "data" / "raw" / session)
    for c in candidates:
        if c.exists():
            return c
    return None


def test_integration_ok_r4_produces_non_null_metrics():
    """Run the full pipeline from CSV → track_surface → sensor_quality
    on OK_R4 and check the producer returns non-null structured output.

    Skips if the CSV fixture is unavailable. This is the closest thing to
    an end-to-end RC6 chain test we can run as a unit test."""
    csv = _resolve_csv("OK_R4.csv")
    if csv is None:
        pytest.skip("OK_R4.csv not available (set $LAP_DATA_RAW)")

    from kart_envelope.config import default_config
    from kart_envelope.ingest.columns import normalize_columns
    from kart_envelope.ingest.parser import parse_session_csv_raw
    from kart_envelope.processing.cleaning import clean_and_derive
    from kart_envelope.processing.lap_splitting import split_and_select_laps
    from kart_envelope.processing.outlier_filter import mad_filter_accel
    from kart_envelope.processing.resampler import resample_laps_by_ds
    from track_surface.builder import build_track_surface

    cfg = default_config()
    raw_df, _ = parse_session_csv_raw(str(csv))
    cleaned = clean_and_derive(raw_df, cfg)
    df = normalize_columns(cleaned)
    laps = split_and_select_laps(df, cfg)
    resampled = resample_laps_by_ds(laps, cfg)
    filtered = mad_filter_accel(resampled, cfg) or resampled

    surface = build_track_surface(filtered, "ok", "racechrono")

    out = compute_session_sensor_quality(filtered, surface)
    assert out is not None, "sensor_quality should run on OK_R4 with proper IMU columns"
    # Structural contract
    assert "orientation_quality" in out
    assert "curvature_agreement" in out
    assert "bank_sensitivity_deg" in out
    assert "map_confidence" in out
    # Per-bin arrays match n_points
    n = surface.frenet.n_points
    assert len(out["orientation_quality"]) == n
    assert len(out["curvature_agreement"]) == n
    assert len(out["bank_sensitivity_deg"]) == n
    # Confidence reasonable on real data
    conf_arr = np.asarray(out["orientation_quality"])
    assert (conf_arr >= 0.0).all() and (conf_arr <= 1.0).all()
    # Bound the lower edge — the algorithm produces ~0.25-0.4 on OK_R4
    # (most bins clear count_score but excitation fraction is naturally
    # lower than the saturation gate; this is the algorithm's faithful
    # behavior, not a degenerate result).
    assert float(np.median(conf_arr)) >= 0.20, (
        f"median confidence {np.median(conf_arr):.2f} too low on OK_R4 — "
        "producer likely degenerate"
    )
    # Confidence should vary across bins (real-data signal, not a constant).
    assert float(np.std(conf_arr)) > 0.005, (
        f"confidence std {np.std(conf_arr):.4f} too low — array is essentially flat"
    )
    # map_confidence has the four expected fields
    mc = out["map_confidence"]
    assert 0.0 <= mc["excited_sample_frac"] <= 1.0
    assert mc["sample_density_per_bin"] > 0
    assert mc["n_bins"] == n
