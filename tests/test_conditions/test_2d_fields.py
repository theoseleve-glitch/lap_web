"""Day-13 Phase D — per-tile 2D field producer tests.

Covers ``conditions.mesh_geometry.compute_tile_geometry`` +
``conditions.spatial_producer._compute_2d_fields`` against three
synthetic ElevationSurface scenarios:

1. Flat — all 2D fields uniform (no cross-track variation introduced).
2. Banked corner — drainage shows cross-track variation; sun shows
   incidence variation; wind shows windward/lee variation.
3. 1D↔2D parity on degenerate (longitudinal-only) meshes — row means
   of 2D fields ≈ 1D *_components within tolerance. On banked meshes
   the 2D fields lawfully exceed 1D (banking adds gradient the
   longitudinal-only 1D path can't see), so the parity invariant is
   ≥-not-= on those.

Anchored on OK_R4 Phase-H synthetic numbers where applicable.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_TELEMETRY_PKG = _REPO_ROOT / "telemetry_tool"
for _p in (_REPO_ROOT, _TELEMETRY_PKG):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from telemetry_tool.conditions.mesh_geometry import (
    compute_tile_geometry,
    wind_bank_modulator,
)
from telemetry_tool.conditions.spatial_factors import (
    drainage_factor,
    sun_factor,
    wind_factor,
)


# ── Synthetic fixture helpers ────────────────────────────────────────


def _make_es(z: np.ndarray, *, s_bin_m: float = 5.0, n_bin_m: float = 1.0):
    """Minimal ElevationSurface stand-in. Only the fields the producer
    consumes are populated; we don't need kv_grid / count_grid / etc."""
    M, K = z.shape
    s_bins = np.arange(M, dtype=np.float64) * s_bin_m
    n_bins = (np.arange(K, dtype=np.float64) - (K - 1) / 2) * n_bin_m
    return SimpleNamespace(s_bins=s_bins, n_bins=n_bins, z_grid=z)


def _make_frenet(M: int, heading_rad: float = 0.0):
    """Minimal FrenetFrame stand-in with constant heading."""
    s_grid = np.arange(M, dtype=np.float64) * 5.0
    headings = np.full(M, heading_rad, dtype=np.float64)
    return SimpleNamespace(s_grid=s_grid, heading_rad=headings)


# ── compute_tile_geometry: shape + axis sanity ───────────────────────


def test_geometry_shape_matches_grid():
    """normals (M, K, 3), slope_pct (M, K)."""
    M, K = 20, 17
    z = np.zeros((M, K))
    geom = compute_tile_geometry(_make_es(z), _make_frenet(M))
    assert geom.normals.shape == (M, K, 3)
    assert geom.slope_pct.shape == (M, K)
    assert geom.s_bins.shape == (M,)
    assert geom.n_bins.shape == (K,)


def test_flat_mesh_yields_vertical_normals():
    """Flat z=0 → every tile normal is (0, 0, 1), slope ≈ 0."""
    M, K = 20, 17
    z = np.zeros((M, K))
    geom = compute_tile_geometry(_make_es(z), _make_frenet(M))
    np.testing.assert_allclose(geom.normals[..., 2], 1.0, atol=1e-6)
    np.testing.assert_allclose(geom.normals[..., 0], 0.0, atol=1e-6)
    np.testing.assert_allclose(geom.normals[..., 1], 0.0, atol=1e-6)
    np.testing.assert_allclose(geom.slope_pct, 0.0, atol=1e-9)


def test_longitudinal_slope_only_yields_x_tilted_normal():
    """z = 0.05 · s (5% climb, east heading): normal tilts west."""
    M, K = 20, 17
    s_bin_m = 5.0
    z = (np.arange(M, dtype=np.float64) * s_bin_m * 0.05)[:, None] * np.ones((1, K))
    geom = compute_tile_geometry(_make_es(z, s_bin_m=s_bin_m), _make_frenet(M))
    # heading=0 (east), longitudinal climb → world normal tilts west (-x).
    # Interior cells (away from edges) should have nx < 0, ny ≈ 0.
    interior = geom.normals[3:-3, 3:-3, :]
    assert np.all(interior[..., 0] < 0)
    np.testing.assert_allclose(interior[..., 1], 0.0, atol=1e-6)
    # Slope ≈ 5% in the interior.
    assert np.all(geom.slope_pct[3:-3, 3:-3] >= 4.0)
    assert np.all(geom.slope_pct[3:-3, 3:-3] <= 6.0)


def test_lateral_bank_only_yields_y_tilted_normal():
    """z = 0.05 · n (banked corner, east heading): normal tilts south."""
    M, K = 20, 17
    n_bin_m = 1.0
    n_grid = np.tile(
        (np.arange(K, dtype=np.float64) - (K - 1) / 2) * n_bin_m,
        (M, 1),
    )
    z = 0.05 * n_grid  # 5% lateral bank
    geom = compute_tile_geometry(
        _make_es(z, n_bin_m=n_bin_m), _make_frenet(M)
    )
    # heading=0 (east), positive lateral bank → world normal tilts south (-y).
    # Interior cells (away from lateral edges where smoothing tapers).
    interior = geom.normals[3:-3, 5:-5, :]
    assert np.all(interior[..., 1] < 0)
    np.testing.assert_allclose(interior[..., 0], 0.0, atol=1e-6)


# ── 1D↔2D parity ─────────────────────────────────────────────────────


def test_parity_flat_mesh_drainage():
    """Flat 2D ↔ flat 1D: drainage_factor(0) = 1.30 on both paths."""
    M, K = 20, 17
    z = np.zeros((M, K))
    geom = compute_tile_geometry(_make_es(z), _make_frenet(M))
    d2 = drainage_factor(geom.slope_pct)
    np.testing.assert_allclose(d2, 1.30, atol=1e-9)
    # 1D would compute drainage(slope_pct_1d=0) = 1.30 too.
    np.testing.assert_allclose(d2.mean(axis=1), 1.30, atol=1e-9)


def test_parity_longitudinal_mesh_drainage():
    """Longitudinal-only slope: row mean of 2D drainage_factor matches
    the 1D drainage_factor on the same per-row slope_pct."""
    M, K = 20, 17
    s_bin_m = 5.0
    slope_per_row = np.linspace(0.0, 0.08, M)  # 0..8% climb
    z = (slope_per_row[:, None] * (np.arange(M, dtype=np.float64) * s_bin_m)[:, None]).astype(np.float64)
    z = np.broadcast_to(z, (M, K)).copy()
    geom = compute_tile_geometry(_make_es(z, s_bin_m=s_bin_m), _make_frenet(M))
    d2 = drainage_factor(geom.slope_pct)
    # Compare ONLY in the interior where smoothing edge effects are
    # negligible; row mean of 2D drainage should match 1D drainage on
    # the row's effective slope.
    for i in range(5, M - 5):
        d2_row_mean = d2[i, 5:-5].mean()
        # 1D slope at this row ≈ geom.slope_pct[i, K//2]
        slope_1d = geom.slope_pct[i, K // 2]
        d1 = drainage_factor(np.array([slope_1d]))[0]
        # Buckets are quantized; row mean is within one bucket-width.
        assert abs(d2_row_mean - d1) <= 0.16, (
            f"row {i}: mean={d2_row_mean:.3f} 1D={d1:.3f} slope={slope_1d:.3f}%"
        )


def test_parity_banked_mesh_drainage_meets_or_exceeds_1d():
    """Lateral bank adds gradient that longitudinal-only 1D can't see.
    Row mean of 2D drainage ≤ 1D drainage (more drainage / lower factor
    on the lateral side) — the inequality holds because slope_pct
    monotonically increases drainage from 1.30→1.10→1.00→0.85.
    """
    M, K = 20, 17
    n_bin_m = 1.0
    n_grid = np.tile(
        (np.arange(K, dtype=np.float64) - (K - 1) / 2) * n_bin_m,
        (M, 1),
    )
    z = 0.05 * n_grid  # 5% lateral bank, no longitudinal slope
    geom = compute_tile_geometry(
        _make_es(z, n_bin_m=n_bin_m), _make_frenet(M),
    )
    d2 = drainage_factor(geom.slope_pct)
    # 1D would see slope_pct ≈ 0 (no longitudinal gradient) → drainage 1.30.
    # 2D sees full lateral gradient → drainage closer to 1.00 in the interior.
    assert d2[5:-5, 5:-5].mean() <= 1.30
    assert d2[5:-5, 5:-5].mean() < 1.20  # demonstrable reduction


# ── Sun + wind 2D behaviour ──────────────────────────────────────────


def test_sun_2d_varies_with_normal_on_banked_mesh():
    """Banked mesh: sun_factor 2D varies across n (normal orientation
    differs from cross-track edge to cross-track edge, so the angle of
    incidence to the sun does too)."""
    M, K = 20, 17
    n_bin_m = 1.0
    n_grid = np.tile(
        (np.arange(K, dtype=np.float64) - (K - 1) / 2) * n_bin_m,
        (M, 1),
    )
    z = 0.15 * n_grid  # 15% lateral bank — meaningful
    geom = compute_tile_geometry(
        _make_es(z, n_bin_m=n_bin_m), _make_frenet(M),
    )
    # Use a fixed sun position: noon at the equator → directly overhead.
    when = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
    sun = sun_factor(when, 0.0, 0.0, geom.normals.reshape(-1, 3)).reshape(M, K)
    # Sun varies across n: shallowest tile (z minimum) has different
    # normal alignment to the sun than steepest.
    row_var = sun[5:-5, 5:-5].std(axis=1)
    assert row_var.mean() > 0.0 or sun[5:-5, 5:-5].std() > 0, (
        f"sun 2D should vary across n on banked mesh; got std={sun.std()}"
    )


def test_wind_modulator_neutral_on_flat_mesh():
    """Flat mesh → normal is purely vertical → wind_bank_modulator = 1.0
    everywhere → wind 2D = wind 1D broadcast across n (no spurious
    cross-track variation)."""
    M, K = 20, 17
    z = np.zeros((M, K))
    geom = compute_tile_geometry(_make_es(z), _make_frenet(M))
    mod = wind_bank_modulator(geom.normals, wind_direction_deg=180.0)
    np.testing.assert_allclose(mod, 1.0, atol=1e-6)


def test_wind_modulator_varies_on_banked_mesh():
    """Banked mesh + wind FROM specific direction → modulator < 1 on
    one side (windward — wind hits face), > 1 on the other (leeward —
    sheltered)."""
    M, K = 20, 17
    n_bin_m = 1.0
    n_grid = np.tile(
        (np.arange(K, dtype=np.float64) - (K - 1) / 2) * n_bin_m,
        (M, 1),
    )
    z = 0.15 * n_grid  # bank tilts up to the north
    geom = compute_tile_geometry(
        _make_es(z, n_bin_m=n_bin_m), _make_frenet(M),
    )
    # Wind FROM south (180°): horizontal wind_from_xy = (0, -1).
    # Normal horizontal points south (-y) on this bank → alignment > 0
    # → modulator < 1 (windward-side reduction).
    mod = wind_bank_modulator(geom.normals, wind_direction_deg=180.0)
    interior = mod[3:-3, 5:-5]
    assert interior.min() < 1.0  # windward face → modulator < 1
    # The variation is small per the alpha=0.10 design (banking-aware,
    # scaled by horizontal-strength); document the magnitude as a
    # smoke check, don't enforce a tight bound.
    assert (1.0 - interior.min()) > 0.001


def test_wind_modulator_no_wind_still_returns_unity_on_flat():
    """Edge case: 0 km/h wind + flat mesh → modulator = 1.0."""
    M, K = 8, 9
    z = np.zeros((M, K))
    geom = compute_tile_geometry(_make_es(z), _make_frenet(M))
    mod = wind_bank_modulator(geom.normals, wind_direction_deg=0.0)
    np.testing.assert_allclose(mod, 1.0, atol=1e-6)


# ── Degenerate mesh guards ───────────────────────────────────────────


def test_geometry_rejects_degenerate_grid():
    """M < 2 or K < 2 → ValueError (can't differentiate)."""
    with pytest.raises(ValueError, match="too small"):
        compute_tile_geometry(_make_es(np.zeros((1, 5))), _make_frenet(1))
    with pytest.raises(ValueError, match="too small"):
        compute_tile_geometry(_make_es(np.zeros((5, 1))), _make_frenet(5))


# ── Coverage-gated drainage slope ────────────────────────────────────
#
# Real karting sessions only populate the driven racing line (~3 of
# 13+ lateral bins), so the lateral gradient ∂z/∂n on off-line bins is
# sparse-sampling noise, not real camber — and it dominates the full
# ‖∇z‖ slope that drainage uses. `slope_pct_drainage` drops the lateral
# term where cross-track coverage is absent (per `count_grid`) and
# falls back to the well-sampled longitudinal grade, while preserving
# the full slope where coverage genuinely supports the banking.


def _make_es_with_counts(z, counts, *, s_bin_m=5.0, n_bin_m=1.0):
    es = _make_es(z, s_bin_m=s_bin_m, n_bin_m=n_bin_m)
    es.count_grid = np.asarray(counts, dtype=np.float64)
    return es


def test_drainage_slope_falls_back_to_longitudinal_where_lateral_coverage_thin():
    """Pure lateral bank, but only the centre 3 bins were driven: off-line
    bins have no cross-track data support, so the drainage slope drops the
    (noise) lateral term and uses the ~0 longitudinal grade → pooling (1.30)."""
    M, K = 20, 17
    n_bin_m = 1.0
    n_grid = np.tile(
        (np.arange(K, dtype=np.float64) - (K - 1) / 2) * n_bin_m, (M, 1)
    )
    z = 0.05 * n_grid  # 5% lateral bank, zero longitudinal slope
    c = K // 2
    counts = np.zeros((M, K))
    counts[:, c - 1:c + 2] = 40.0  # only the driven line (3 centre bins)
    geom = compute_tile_geometry(
        _make_es_with_counts(z, counts, n_bin_m=n_bin_m), _make_frenet(M)
    )
    d = drainage_factor(geom.slope_pct_drainage)
    offline = np.r_[0:c - 1, c + 2:K]  # bins outside the driven strip
    np.testing.assert_allclose(d[5:-5][:, offline], 1.30, atol=1e-9)


def test_drainage_slope_keeps_lateral_where_coverage_full():
    """Same banked mesh but with full cross-track coverage → lateral term
    retained → genuine banking still drains (< 1.20), matching legacy."""
    M, K = 20, 17
    n_bin_m = 1.0
    n_grid = np.tile(
        (np.arange(K, dtype=np.float64) - (K - 1) / 2) * n_bin_m, (M, 1)
    )
    z = 0.05 * n_grid
    counts = np.full((M, K), 40.0)
    geom = compute_tile_geometry(
        _make_es_with_counts(z, counts, n_bin_m=n_bin_m), _make_frenet(M)
    )
    d = drainage_factor(geom.slope_pct_drainage)
    assert d[5:-5, 5:-5].mean() < 1.20


def test_drainage_slope_defaults_to_full_when_no_count_grid():
    """No count_grid (synthetic/legacy meshes) → assume full support →
    slope_pct_drainage is identical to the full slope_pct (no regression)."""
    M, K = 20, 17
    n_grid = np.tile(
        (np.arange(K, dtype=np.float64) - (K - 1) / 2), (M, 1)
    )
    z = 0.05 * n_grid
    geom = compute_tile_geometry(_make_es(z), _make_frenet(M))  # no count_grid
    np.testing.assert_allclose(
        geom.slope_pct_drainage, geom.slope_pct, atol=1e-9
    )


def test_2d_drainage_field_uses_coverage_gated_slope():
    """Producer wiring: _compute_2d_fields drives drainage_field_2d from the
    coverage-gated slope, so a sparse-coverage banked mesh leaves off-line
    tiles pooling (1.30) instead of noise-driven drainage."""
    from datetime import datetime, timezone

    from telemetry_tool.conditions.spatial_producer import _compute_2d_fields

    M, K = 20, 17
    n_bin_m = 1.0
    n_grid = np.tile(
        (np.arange(K, dtype=np.float64) - (K - 1) / 2) * n_bin_m, (M, 1)
    )
    z = 0.05 * n_grid
    c = K // 2
    counts = np.zeros((M, K))
    counts[:, c - 1:c + 2] = 40.0
    es = _make_es_with_counts(z, counts, n_bin_m=n_bin_m)
    frenet = _make_frenet(M)
    fields = _compute_2d_fields(
        track_surface=SimpleNamespace(elevation_surface=es, frenet=frenet),
        weather_condition=SimpleNamespace(label="wet"),
        session_inputs=SimpleNamespace(
            started_at_utc=datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
        ),
        lat=48.55,
        lon=0.27,
        wind_dir_deg=180.0,
        wind_speed_kmh=10.0,
        wind_1d=np.ones(M),
    )
    Ms, Kn = fields["tile_grid_shape"]
    drain = np.asarray(fields["drainage_field_2d"]).reshape(Ms, Kn)
    offline = np.r_[0:c - 1, c + 2:Kn]
    np.testing.assert_allclose(drain[5:-5][:, offline], 1.30, atol=1e-9)


# ── Producer: boundary_source → mesh_source mapping ──────────────────
#
# SpatialMuModifier.mesh_source is a fixed Literal, but TrackSurface
# emits a wider boundary_source vocabulary ("gt_anchored_native",
# "hand_traced", "data_derived", None). The producer must map onto the
# Literal — "gt_anchored_native" is gt ground truth → "hand_traced".


@pytest.mark.parametrize(
    "boundary, expected",
    [
        ("gt_anchored_native", "hand_traced"),  # gt geojson, native resample
        ("hand_traced", "hand_traced"),
        ("data_derived", "data_derived"),
        ("multihead", "multihead"),
        (None, "data_derived"),                 # no boundaries → conservative
        ("something_unforeseen", "data_derived"),  # unknown → conservative
    ],
)
def test_mesh_source_maps_boundary_source_to_literal(boundary, expected):
    from telemetry_tool.conditions.spatial_producer import (
        _mesh_source_from_boundary,
    )

    assert _mesh_source_from_boundary(boundary) == expected


# ── Producer: per-tile confidence field ──────────────────────────────
#
# confidence_field_2d surfaces the elevation surface's per-cell coverage
# confidence (clip(count/20, 0, 1)) so downstream weighting can discount
# off-line tiles whose drainage fell back to the longitudinal grade.


def test_2d_confidence_field_reflects_elevation_coverage():
    """confidence_field_2d mirrors ElevationSurface.confidence: ~1.0 on the
    driven line, ~0.0 on unsampled off-line bins."""
    from datetime import datetime, timezone

    from telemetry_tool.conditions.spatial_producer import _compute_2d_fields

    M, K = 20, 17
    es = _make_es(np.zeros((M, K)))
    c = K // 2
    conf = np.zeros((M, K))
    conf[:, c - 1:c + 2] = 1.0
    es.confidence = conf
    es.count_grid = (conf > 0).astype(float) * 40.0
    fields = _compute_2d_fields(
        track_surface=SimpleNamespace(elevation_surface=es, frenet=_make_frenet(M)),
        weather_condition=SimpleNamespace(label="dry"),
        session_inputs=SimpleNamespace(
            started_at_utc=datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
        ),
        lat=48.55,
        lon=0.27,
        wind_dir_deg=0.0,
        wind_speed_kmh=5.0,
        wind_1d=np.ones(M),
    )
    Ms, Kn = fields["tile_grid_shape"]
    cf = np.asarray(fields["confidence_field_2d"]).reshape(Ms, Kn)
    np.testing.assert_allclose(cf[:, c], 1.0, atol=1e-9)
    np.testing.assert_allclose(cf[:, 0], 0.0, atol=1e-9)


def test_2d_confidence_field_none_without_elevation_surface():
    """No elevation surface → the whole 2D block (incl. confidence) is None."""
    from datetime import datetime, timezone

    from telemetry_tool.conditions.spatial_producer import _compute_2d_fields

    fields = _compute_2d_fields(
        track_surface=SimpleNamespace(elevation_surface=None, frenet=_make_frenet(5)),
        weather_condition=SimpleNamespace(label="dry"),
        session_inputs=SimpleNamespace(
            started_at_utc=datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
        ),
        lat=48.55,
        lon=0.27,
        wind_dir_deg=0.0,
        wind_speed_kmh=5.0,
        wind_1d=np.ones(5),
    )
    assert fields["confidence_field_2d"] is None
