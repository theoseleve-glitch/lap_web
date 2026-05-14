"""Day-8 Phase-D tests — RC3 robust MAD-based boundary estimator.

The data_derived path now produces a RACING-LINE CORRIDOR envelope:
  width_side = median(n_side) + K * max(MAD(n_side), MAD_FLOOR) + margin
  (K=3.0, MAD_FLOOR=0.5m, margin=1.0m)

These tests verify three properties RC3 must hold for it to be a useful
fallback for tracks without hand-traced gt:

  1. Returns positive, finite, smooth widths on real racing-line data.
  2. Robust to a single outlier lap — MAD-based, not mean-pulled.
  3. Bounded by the racing-line corridor envelope (no wild over-estimation;
     does NOT reach gt track-edge widths on tracks where the racing line
     is conservative — that's hand_traced's job).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TELEMETRY_PKG = _REPO_ROOT / "telemetry_tool"
for _p in (_REPO_ROOT, _TELEMETRY_PKG):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from track_surface.frenet import FrenetFrame  # noqa: E402
from track_surface.boundary import _data_derived_boundaries  # noqa: E402


def _straight_centerline(length: float = 100.0, n: int = 200) -> FrenetFrame:
    return FrenetFrame.from_centerline(np.column_stack([
        np.linspace(0, length, n), np.zeros(n),
    ]))


def _gen_lap_sn(
    frenet: FrenetFrame, sigma: float, mean_offset: float = 0.0,
    rng_seed: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """Synthetic lap (s, n) with Gaussian-spread n around mean_offset."""
    rng = np.random.default_rng(rng_seed)
    s = frenet.s_grid.copy()
    n = rng.normal(mean_offset, sigma, len(s))
    return s, n


# ── 1. Basic shape & smoothness ────────────────────────────────────────


def test_rc3_returns_positive_finite_smooth_widths():
    """Synthetic 12-lap track with σ=2m racing-line spread → positive,
    finite, reasonably-smooth widths around the corridor envelope. 12 laps
    so each per-bin side has ~6 samples (above _RC3_MIN_PER_SIDE=3 threshold)."""
    frenet = _straight_centerline()
    laps_sn = [_gen_lap_sn(frenet, sigma=2.0, rng_seed=i) for i in range(12)]
    result = _data_derived_boundaries(
        frenet, laps_sn, percentile=99.0, min_laps=3,
    )
    assert result is not None
    wl, wr = result
    assert wl.shape == (frenet.n_points,)
    assert wr.shape == (frenet.n_points,)
    assert np.all(np.isfinite(wl)), "width_left contains NaN/inf"
    assert np.all(np.isfinite(wr)), "width_right contains NaN/inf"
    assert np.all(wl > 0), "width_left should be strictly positive"
    assert np.all(wr > 0), "width_right should be strictly positive"
    # For σ=2m Gaussian split at 0:
    #   half-normal mean of |n_side| = σ*sqrt(2/π) ≈ 1.6m
    #   MAD of half-normal ≈ 0.95σ ≈ 1.9m → robust_max ≈ 1.6+3*1.9+1 ≈ 8.3m
    # Smoothing + small samples bring it ~6-8m.
    assert 4.0 < wl.mean() < 10.0, f"WL mean {wl.mean():.2f}m outside expected band"
    assert 4.0 < wr.mean() < 10.0, f"WR mean {wr.mean():.2f}m outside expected band"


def test_rc3_returns_none_when_too_few_laps():
    """min_laps=3 honoured."""
    frenet = _straight_centerline()
    laps_sn = [_gen_lap_sn(frenet, sigma=2.0, rng_seed=i) for i in range(2)]
    assert _data_derived_boundaries(frenet, laps_sn, percentile=99.0, min_laps=3) is None


# ── 2. Robustness to outlier lap (MAD core property) ───────────────────


def test_rc3_robust_to_single_outlier_lap():
    """A single outlier lap with wide off-track samples should NOT inflate
    widths anywhere near as much as the mean-driven baseline would.
    MAD-based estimators are by design unaffected by a single outlier in
    a population of >= 5."""
    frenet = _straight_centerline()
    # 9 well-behaved laps (σ=1.5m) + 1 wild outlier (σ=8m)
    laps_normal = [_gen_lap_sn(frenet, sigma=1.5, rng_seed=i) for i in range(9)]
    laps_outlier = [_gen_lap_sn(frenet, sigma=8.0, rng_seed=99)]

    result_clean = _data_derived_boundaries(
        frenet, laps_normal, percentile=99.0, min_laps=3,
    )
    result_dirty = _data_derived_boundaries(
        frenet, laps_normal + laps_outlier, percentile=99.0, min_laps=3,
    )
    assert result_clean is not None and result_dirty is not None
    wl_clean, _ = result_clean
    wl_dirty, _ = result_dirty

    # MAD inflation from one wild lap among 10 should be modest — well
    # under 2m on the mean width (vs >5m if percentile-driven).
    inflation = float(wl_dirty.mean() - wl_clean.mean())
    assert inflation < 2.0, \
        f"RC3 inflated by {inflation:.2f}m from one outlier lap; not robust"


# ── 3. Real OK_R4 racing-line corridor envelope ────────────────────────


def _ok_r4_laps_sn_filtered():
    """Run OK_R4 through the pipeline + corridor filter (gt-mask) and
    return per-lap (s, n) tuples + Frenet frame."""
    from kart_envelope.config import default_config
    from kart_envelope.ingest.columns import normalize_columns
    from kart_envelope.ingest.parser import parse_session_csv_raw
    from kart_envelope.processing.cleaning import clean_and_derive
    from kart_envelope.processing.lap_splitting import split_and_select_laps
    from kart_envelope.processing.outlier_filter import mad_filter_accel
    from kart_envelope.processing.resampler import resample_laps_by_ds
    from track_surface.boundary import _gt_project_to_xy
    from track_surface.centerline import extract_centerline
    from track_surface.corridor_filter import filter_samples_in_corridor
    from track_surface.gt_loader import load_gt, resolve_track_id
    from track_surface.normalizer import (
        detect_coordinate_system, normalize_positions,
    )

    csv_path = _REPO_ROOT / "data" / "raw" / "OK_R4.csv"
    if not csv_path.exists():
        pytest.skip("OK_R4.csv missing")

    import pandas as pd
    cfg = default_config()
    raw, _ = parse_session_csv_raw(str(csv_path))
    cleaned = clean_and_derive(raw, cfg)
    norm = normalize_columns(cleaned)
    laps_dict = split_and_select_laps(norm, cfg)
    resampled = resample_laps_by_ds(laps_dict, cfg)
    filtered = mad_filter_accel(resampled, cfg) or resampled

    coord_sys = detect_coordinate_system("racechrono")
    xy_list: list[np.ndarray] = []
    for _, df in sorted(filtered.items()):
        x, y, _z, _meta = normalize_positions(df, coord_sys)
        m = np.isfinite(x) & np.isfinite(y)
        if m.sum() >= 20:
            xy_list.append(np.column_stack([x[m], y[m]]))

    cl_xy, _ = extract_centerline(xy_list, ds_m=0.5)
    frenet = FrenetFrame.from_centerline(cl_xy)
    laps_sn = []
    for xy in xy_list:
        s, n = frenet.xy_to_sn(xy[:, 0], xy[:, 1])
        laps_sn.append((s, n))

    # Reproduce builder.py step 4b: project gt, run corridor filter,
    # apply per-lap mask.
    lats, lons = [], []
    for df in filtered.values():
        if "lat_deg" in df.columns:
            lats.append(pd.to_numeric(df["lat_deg"], errors="coerce").to_numpy())
            lons.append(pd.to_numeric(df["lon_deg"], errors="coerce").to_numpy())
    all_lat = np.concatenate(lats); all_lon = np.concatenate(lons)
    finite = np.isfinite(all_lat) & np.isfinite(all_lon)
    lat_ref = float(np.deg2rad(np.mean(all_lat[finite])))
    lon_ref = float(np.deg2rad(np.mean(all_lon[finite])))

    canonical = resolve_track_id("ok")
    gt = load_gt(canonical) if canonical else None
    if gt is None:
        pytest.skip("gt for OK missing — test requires it for corridor filter")
    gt_left_xy = _gt_project_to_xy(gt.left_polyline, lat_ref, lon_ref)
    gt_right_xy = _gt_project_to_xy(gt.right_polyline, lat_ref, lon_ref)

    lap_sizes = [xy.shape[0] for xy in xy_list]
    all_xy = np.vstack(xy_list)
    kept, _meta = filter_samples_in_corridor(
        all_xy, frenet,
        gt_left_xy=gt_left_xy, gt_right_xy=gt_right_xy,
    )
    laps_sn_filt = []
    cursor = 0
    for i, n_samples in enumerate(lap_sizes):
        m = kept[cursor: cursor + n_samples]
        s_i, n_i = laps_sn[i]
        laps_sn_filt.append((s_i[m], n_i[m]))
        cursor += n_samples
    return frenet, laps_sn_filt


def test_rc3_ok_r4_widths_match_racing_line_corridor():
    """On OK_R4 (gt-mask corridor filter active), RC3 widths should fall
    in the 2-4m range — the racing-line corridor envelope. They will NOT
    reach gt's 5m LEFT / 3.35m RIGHT because the racing line is
    conservative and doesn't visit the full track width. This test
    documents the corridor-estimator semantics."""
    frenet, laps_sn_filt = _ok_r4_laps_sn_filtered()
    result = _data_derived_boundaries(
        frenet, laps_sn_filt, percentile=99.0, min_laps=3,
    )
    assert result is not None
    wl, wr = result

    # No NaN/inf, all positive.
    assert np.all(np.isfinite(wl))
    assert np.all(np.isfinite(wr))
    assert np.all(wl > 0)
    assert np.all(wr > 0)

    # Racing-line corridor envelope on OK_R4: ~3m each side (median+3*MAD+1m
    # of samples that span ~1m past centerline).
    assert 2.0 < wl.mean() < 4.5, \
        f"WL mean {wl.mean():.2f}m outside racing-line corridor range [2, 4.5]m"
    assert 2.0 < wr.mean() < 4.5, \
        f"WR mean {wr.mean():.2f}m outside racing-line corridor range [2, 4.5]m"

    # No wild per-bin spikes (max width sanity).
    assert wl.max() < 8.0, f"WL max {wl.max():.2f}m exceeds racing-line cap"
    assert wr.max() < 8.0, f"WR max {wr.max():.2f}m exceeds racing-line cap"

    # Smoothness: per-bin step changes (after _smooth_1d) shouldn't exceed
    # ~0.3m anywhere (5-bin Gaussian smooth on a robust estimator).
    assert np.max(np.abs(np.diff(wl))) < 0.5, "WL has unsmooth spikes"
    assert np.max(np.abs(np.diff(wr))) < 0.5, "WR has unsmooth spikes"
