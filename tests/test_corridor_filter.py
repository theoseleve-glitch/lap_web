"""Day-8 Phase-C tests — RC2 corridor filter (gt-polygon mask + MAD fallback).

Six tests covering the synthetic-geometry correctness of both paths and
the real-session behaviour that must NOT reject the S1 OK tail (D3 lock:
the tail is real geometry; the gt polygon includes it).

Committed FAILING before the corridor_filter.py implementation.
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

from track_surface.frenet import FrenetFrame  # noqa: E402
from track_surface.corridor_filter import filter_samples_in_corridor  # noqa: E402


# ── helpers ────────────────────────────────────────────────────────────


def _circle_centerline(radius: float = 50.0, n: int = 400) -> FrenetFrame:
    theta = np.linspace(0.0, 2 * np.pi, n, endpoint=False)
    xy = np.column_stack([radius * np.cos(theta), radius * np.sin(theta)])
    return FrenetFrame.from_centerline(xy)


def _on_corridor_samples(
    radius: float, half_width: float, n: int, rng_seed: int = 0,
) -> np.ndarray:
    """Random samples within a corridor of half_width around a circle."""
    rng = np.random.default_rng(rng_seed)
    theta = rng.uniform(0, 2 * np.pi, n)
    r = rng.uniform(radius - half_width, radius + half_width, n)
    return np.column_stack([r * np.cos(theta), r * np.sin(theta)])


def _off_track_cluster(
    centroid_x: float, centroid_y: float, n: int, spread: float = 1.0,
    rng_seed: int = 1,
) -> np.ndarray:
    rng = np.random.default_rng(rng_seed)
    return np.column_stack([
        centroid_x + rng.normal(scale=spread, size=n),
        centroid_y + rng.normal(scale=spread, size=n),
    ])


def _gt_polylines_on_circle(
    radius: float, half_width: float, n_pts: int = 50,
) -> tuple[np.ndarray, np.ndarray]:
    """gt LEFT (inner edge) + gt RIGHT (outer edge) for the circle test."""
    theta = np.linspace(0.0, 2 * np.pi, n_pts, endpoint=False)
    inner = np.column_stack([
        (radius - half_width) * np.cos(theta),
        (radius - half_width) * np.sin(theta),
    ])
    outer = np.column_stack([
        (radius + half_width) * np.cos(theta),
        (radius + half_width) * np.sin(theta),
    ])
    return inner, outer


# ── synthetic gt-mask tests ────────────────────────────────────────────


def test_gt_mask_retains_on_corridor_rejects_off_track():
    """Synthetic: 200 on-corridor samples + 50 off-track cluster.
    The gt-mask path (inflate gt polygon by 1m) retains the on-corridor
    and rejects the off-track cluster."""
    frenet = _circle_centerline(radius=50.0, n=400)
    on_track = _on_corridor_samples(radius=50.0, half_width=3.0, n=200, rng_seed=0)
    off_track = _off_track_cluster(centroid_x=80.0, centroid_y=0.0, n=50, spread=1.0)
    samples = np.vstack([on_track, off_track])

    gt_left, gt_right = _gt_polylines_on_circle(radius=50.0, half_width=3.0, n_pts=80)

    mask, meta = filter_samples_in_corridor(
        samples, frenet, gt_left_xy=gt_left, gt_right_xy=gt_right,
        gt_inflation_m=1.0,
    )
    assert meta["method"] == "gt_mask"
    assert mask.shape == (250,)
    assert mask[:200].sum() >= 190, \
        f"on-corridor retention {int(mask[:200].sum())}/200 too low; gt polygon may be too tight"
    assert mask[200:].sum() <= 2, \
        f"off-track retention {int(mask[200:].sum())}/50 too high; gt polygon mask not rejecting outliers"


def test_gt_mask_inflation_includes_boundary_samples():
    """A sample exactly at gt LEFT (radius-h/2) is INSIDE the inflated polygon
    even with inflation=1m (since the polygon already includes that radius)."""
    frenet = _circle_centerline(radius=50.0, n=400)
    gt_left, gt_right = _gt_polylines_on_circle(radius=50.0, half_width=3.0, n_pts=80)

    # Single sample exactly on gt LEFT (radius - 3 = 47m)
    sample = np.array([[47.0, 0.0]])
    mask, _ = filter_samples_in_corridor(
        sample, frenet, gt_left_xy=gt_left, gt_right_xy=gt_right,
        gt_inflation_m=1.0,
    )
    assert bool(mask[0]), "sample on gt LEFT must be inside the corridor"


# ── synthetic MAD-fallback tests ───────────────────────────────────────


def test_mad_fallback_rejects_far_outliers():
    """Without gt: per-s-bin MAD rejects samples > mad_threshold·MAD from
    median n in their bin. Inject 50 far-off samples among 200 corridor
    samples; MAD must reject most of them."""
    frenet = _circle_centerline(radius=50.0, n=400)
    on_track = _on_corridor_samples(radius=50.0, half_width=3.0, n=200, rng_seed=2)
    off_track = _off_track_cluster(centroid_x=80.0, centroid_y=0.0, n=50, spread=1.0)
    samples = np.vstack([on_track, off_track])

    mask, meta = filter_samples_in_corridor(
        samples, frenet,
        gt_left_xy=None, gt_right_xy=None,
        mad_threshold=5.0,
    )
    assert meta["method"] == "mad"
    assert mask[:200].sum() >= 180, \
        f"on-corridor MAD retention {int(mask[:200].sum())}/200 too low"
    assert mask[200:].sum() <= 5, \
        f"off-track MAD retention {int(mask[200:].sum())}/50 too high"


def test_mad_retains_all_when_no_outliers():
    """Uniform on-corridor samples → MAD should retain everything."""
    frenet = _circle_centerline(radius=50.0, n=400)
    samples = _on_corridor_samples(radius=50.0, half_width=3.0, n=500, rng_seed=3)

    mask, meta = filter_samples_in_corridor(samples, frenet, mad_threshold=5.0)
    assert meta["method"] == "mad"
    # On clean data, retention should be very high (slight noise tail)
    assert mask.sum() >= 470, f"MAD over-rejected clean samples: kept {int(mask.sum())}/500"


def test_filter_handles_empty_input():
    frenet = _circle_centerline()
    mask, meta = filter_samples_in_corridor(np.empty((0, 2)), frenet)
    assert mask.shape == (0,)
    assert meta["n_total"] == 0
    assert meta["n_kept"] == 0


# ── real-session tests (S1 tail must be retained) ──────────────────────


def _real_xy_samples_and_frenet(csv_name: str):
    """Run pipeline stages 1-6 and return concatenated XY samples + the
    Day-7 centerline FrenetFrame."""
    from kart_envelope.config import default_config
    from kart_envelope.ingest.columns import normalize_columns
    from kart_envelope.ingest.parser import parse_session_csv_raw
    from kart_envelope.processing.cleaning import clean_and_derive
    from kart_envelope.processing.lap_splitting import split_and_select_laps
    from kart_envelope.processing.outlier_filter import mad_filter_accel
    from kart_envelope.processing.resampler import resample_laps_by_ds
    from track_surface.centerline import extract_centerline
    from track_surface.normalizer import detect_coordinate_system, normalize_positions

    csv_path = _REPO_ROOT / "data" / "raw" / csv_name
    if not csv_path.exists():
        pytest.skip(f"missing CSV: {csv_name}")
    cfg = default_config()
    raw, _ = parse_session_csv_raw(str(csv_path))
    cleaned = clean_and_derive(raw, cfg)
    norm = normalize_columns(cleaned)
    laps = split_and_select_laps(norm, cfg)
    resampled = resample_laps_by_ds(laps, cfg)
    filtered = mad_filter_accel(resampled, cfg) or resampled
    coord_sys = detect_coordinate_system("racechrono")
    xy_list = []
    for _, df in sorted(filtered.items()):
        x, y, _z, _meta = normalize_positions(df, coord_sys)
        m = np.isfinite(x) & np.isfinite(y)
        if m.sum() >= 20:
            xy_list.append(np.column_stack([x[m], y[m]]))
    cl_xy, total = extract_centerline(xy_list, ds_m=0.5)
    frenet = FrenetFrame.from_centerline(cl_xy)
    return np.vstack(xy_list), frenet


def test_ok_r4_gt_mask_retains_s1_tail():
    """OK_R4: with gt_circuit-d-essay (which traces the S1 tail as real
    geometry per D3), the corridor mask must retain samples in the
    bottom-right tail region.
    """
    import json
    samples, frenet = _real_xy_samples_and_frenet("OK_R4.csv")

    # Load gt and project to the SAME local frame using OK_R4's GPS ref
    R = 6_371_000.0
    # Compute lat_ref/lon_ref from samples (use centerline-derived would be
    # cleaner but for this test we approximate from sample centroid)
    # → use the gt's own absolute lat/lon, then project via per-lap mean
    # (mimics builder.py's per-lap normalize_positions). For simplicity,
    # we use samples' x/y range to fit a projection.
    gt_path = _REPO_ROOT.parent / "trackreco-main" / "data" / "ground_truth" / "gt_circuit-d-essay.geojson"
    if not gt_path.exists():
        pytest.skip("gt_circuit-d-essay.geojson missing")
    gt = json.loads(gt_path.read_text(encoding="utf-8"))

    # Project gt to the SAME XY frame as samples: use sample-centroid
    # equirectangular projection (matches normalize_positions behaviour).
    # NB: this is an approximation — for real builder.py wiring the
    # projection is consistent by construction; here we approximate.
    # Centroid in lat/lon: read from gt and align via best-fit.
    gt_left_lonlat = gt_right_lonlat = None
    for feat in gt["features"]:
        role = feat.get("properties", {}).get("role")
        coords = np.asarray(feat["geometry"]["coordinates"])
        if role == "left_boundary_gt": gt_left_lonlat = coords
        elif role == "right_boundary_gt": gt_right_lonlat = coords
    assert gt_left_lonlat is not None and gt_right_lonlat is not None

    # Use the lap-data centroid as projection origin
    # (For a cleaner test we'd pass projection params; here we estimate
    # from data and accept O(few m) residual.)
    lat_ref = float(np.deg2rad(48.55260))
    lon_ref = float(np.deg2rad(0.27474))

    def to_xy(arr):
        lon_r = np.deg2rad(arr[:, 0]); lat_r = np.deg2rad(arr[:, 1])
        x = R * (lon_r - lon_ref) * np.cos(lat_ref)
        y = R * (lat_r - lat_ref)
        return np.column_stack([x, y])
    gt_left_xy = to_xy(gt_left_lonlat)
    gt_right_xy = to_xy(gt_right_lonlat)

    # Identify samples in the bottom-right tail region (x>50, y<-80 in
    # the sample frame). These are the S1 tail samples that MUST be
    # retained per the D3 lock.
    tail_mask = (samples[:, 0] > 50) & (samples[:, 1] < -80)
    n_tail = int(tail_mask.sum())
    assert n_tail > 100, f"too few tail samples to test ({n_tail}); fixture broken"

    mask, meta = filter_samples_in_corridor(
        samples, frenet,
        gt_left_xy=gt_left_xy, gt_right_xy=gt_right_xy,
        gt_inflation_m=1.0,
    )
    tail_kept_frac = float(np.sum(mask & tail_mask) / max(n_tail, 1))
    assert tail_kept_frac >= 0.7, \
        f"OK_R4 S1 tail retained only {100*tail_kept_frac:.1f}% (must be >=70%); " \
        f"gt-polygon mask is rejecting real track geometry — D3 lock violated"


def test_no_gt_falls_back_to_mad():
    """Real OK_R4 samples with track_id=None equivalent (gt_left=None) →
    MAD path runs, retains the bulk of the corridor."""
    samples, frenet = _real_xy_samples_and_frenet("OK_R4.csv")

    mask, meta = filter_samples_in_corridor(
        samples, frenet,
        gt_left_xy=None, gt_right_xy=None,
        mad_threshold=5.0,
    )
    assert meta["method"] == "mad"
    # On real GPS data, MAD should retain the vast majority (>= 90 %).
    assert meta["n_kept"] / meta["n_total"] >= 0.90, \
        f"MAD over-rejected real OK samples: {meta['n_kept']}/{meta['n_total']} kept"
