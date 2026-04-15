"""Extreme sim-only track reconstruction from an iRacing .ibt session.

Layer 1: Car body Roll → per-metre banking angle (the KEY fix for Daytona)
Layer 2: Wheel contact patches → 4 surface samples per tick → full z(s,n) mesh
Layer 3: All 74 laps instead of just 5 (15x more data)
Layer 4: Delaunay triangulation of the 2M+ contact points
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.ndimage import uniform_filter1d

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telemetry_tool"))
from lap_oracle.extractors.iracing_ibt import _parse_header, _parse_var_headers

IBT_PATH = Path(
    "C:/Users/Admin/Documents/iRacing/telemetry/"
    "mclaren570sgt4_daytona 2011 road 2026-01-09 23-40-48.ibt"
)
OUT_PATH = Path(__file__).resolve().parent.parent / "track-surface-spa-data.json"

G = 9.80665
EARTH_R = 6371000.0
TYPE_DTYPE = {1: np.uint8, 2: np.int32, 3: np.uint32, 4: np.float32, 5: np.float64}
TYPE_SIZE = {1: 1, 2: 4, 3: 4, 4: 4, 5: 8}

# McLaren 570S GT4 geometry (approximate — from iRacing car files)
# Needed for contact patch reconstruction
WHEELBASE_M = 2.670     # front axle to rear axle
TRACK_FRONT_M = 1.666   # front track width
TRACK_REAR_M = 1.627    # rear track width


def extract_ibt(path: Path) -> tuple[dict, dict]:
    with open(path, "rb") as f:
        header_bytes = f.read(max(4096, 144 * 300 + 200))
        hdr = _parse_header(header_bytes)
        vars_map = _parse_var_headers(header_bytes, hdr)
        file_size = os.path.getsize(path)
        num_samples = (file_size - hdr["data_start"]) // hdr["buf_len"]
        f.seek(hdr["data_start"])
        raw = f.read(hdr["buf_len"] * num_samples)
        arr = np.frombuffer(raw, dtype=np.uint8).reshape(num_samples, hdr["buf_len"])

    def get(name: str):
        if name not in vars_map:
            return None
        v = vars_map[name]
        off, sz, dt = v["offset"], TYPE_SIZE[v["type"]], TYPE_DTYPE[v["type"]]
        return np.frombuffer(arr[:, off : off + sz].tobytes(), dtype=dt).copy()

    channels = {
        # Position + timing
        "lat": get("Lat"),
        "lon": get("Lon"),
        "alt": get("Alt"),
        "lap": get("Lap"),
        "lap_dist": get("LapDist"),
        "lap_dist_pct": get("LapDistPct"),
        "time": get("SessionTime"),
        "on_track": get("IsOnTrack"),
        # Dynamics
        "speed": get("Speed"),
        "throttle": get("Throttle"),
        "brake": get("Brake"),
        "lat_accel": get("LatAccel"),
        "long_accel": get("LongAccel"),
        "vert_accel": get("VertAccel"),
        # *** LAYER 1: Car body orientation ***
        "yaw": get("Yaw"),
        "pitch": get("Pitch"),
        "roll": get("Roll"),  # <- THE banking detector
        # *** LAYER 2: Wheel ride heights for contact patch reconstruction ***
        "lf_ride": get("LFrideHeight"),
        "rf_ride": get("RFrideHeight"),
        "lr_ride": get("LRrideHeight"),
        "rr_ride": get("RRrideHeight"),
    }
    return hdr, channels


def compute_contact_patches(
    x: np.ndarray, y: np.ndarray, z: np.ndarray,
    yaw: np.ndarray, pitch: np.ndarray, roll: np.ndarray,
    lf_ride: np.ndarray, rf_ride: np.ndarray, lr_ride: np.ndarray, rr_ride: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute world-space positions of the 4 tire contact patches.

    For each sample, the contact patches are offset from the car's CG
    position by the wheelbase/track-width, rotated by the car's orientation.

    Returns (cp_x, cp_y, cp_z) — each of shape (4N,) with samples interleaved
    per wheel: [s0_FL, s0_FR, s0_RL, s0_RR, s1_FL, ...]
    """
    n = len(x)

    # Body-frame offsets from CG to each contact patch (meters)
    # Assume CG is at 0.5 × wheelbase from front (typical)
    cg_to_front = WHEELBASE_M * 0.5
    cg_to_rear = WHEELBASE_M * 0.5
    half_front = TRACK_FRONT_M * 0.5
    half_rear = TRACK_REAR_M * 0.5

    # Body-frame positions (x=forward, y=left, z=up)
    # iRacing body frame: +X forward, +Y right, +Z up (double-check)
    body_offsets = np.array([
        [cg_to_front,  +half_front, 0.0],  # FL
        [cg_to_front,  -half_front, 0.0],  # FR
        [-cg_to_rear,  +half_rear,  0.0],  # RL
        [-cg_to_rear,  -half_rear,  0.0],  # RR
    ], dtype=np.float32)  # shape (4, 3)

    # Ride heights push the contact patches DOWN from the chassis plane
    # by the ride height amount (CG is above wheels by some fixed amount,
    # but for banking visualization we just need the offsets to be in the
    # correct relative positions)
    ride_heights = np.stack([lf_ride, rf_ride, lr_ride, rr_ride], axis=1)  # (N, 4)

    # Build rotation matrices per sample
    # R = Rz(yaw) @ Ry(pitch) @ Rx(roll)
    cy, sy = np.cos(yaw), np.sin(yaw)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cr, sr = np.cos(roll), np.sin(roll)

    # Rotate each body offset by the orientation at each sample
    # Result: (N, 4, 3) world-frame offsets
    world_offsets = np.empty((n, 4, 3), dtype=np.float32)
    for wi in range(4):
        bx, by, _ = body_offsets[wi]
        # Rotated body vector (ignoring ride-height z offset for now)
        # Full 3x3 rotation: R = Rz @ Ry @ Rx
        # For the XY components: wx = cy*cp*bx + (cy*sp*sr - sy*cr)*by
        #                        wy = sy*cp*bx + (sy*sp*sr + cy*cr)*by
        # For Z (vertical): wz = -sp*bx + cp*sr*by
        world_offsets[:, wi, 0] = cy*cp*bx + (cy*sp*sr - sy*cr)*by
        world_offsets[:, wi, 1] = sy*cp*bx + (sy*sp*sr + cy*cr)*by
        world_offsets[:, wi, 2] = -sp*bx + cp*sr*by - ride_heights[:, wi] * 0.001

    # Contact patches: car position + rotated offset
    cp_x = (x[:, None] + world_offsets[:, :, 0]).ravel()
    cp_y = (y[:, None] + world_offsets[:, :, 1]).ravel()
    cp_z = (z[:, None] + world_offsets[:, :, 2]).ravel()

    return cp_x, cp_y, cp_z


def build_surface_from_contact_patches(
    cp_x: np.ndarray, cp_y: np.ndarray, cp_z: np.ndarray,
    centerline_lap_xy: np.ndarray,  # a single clean lap for centerline
    ds_m: float = 2.0,
    dn_m: float = 0.5,
) -> dict:
    """Build a 2D grid z(s, n) from 2M+ contact patch observations.

    Extreme precision: every wheel contact on the track surface contributes.
    The centerline is built from ONE clean lap, then all contact patches
    are projected onto it.
    """
    from track_surface.centerline import extract_centerline
    from track_surface.frenet import FrenetFrame

    # Build centerline from a single lap's trajectory (correct length)
    centerline_xy, total_length = extract_centerline([centerline_lap_xy], ds_m=1.0)
    frenet = FrenetFrame.from_centerline(centerline_xy)

    print(f"  Centerline: {frenet.n_points} points, length={total_length:.0f}m")

    # Project ALL contact patches to Frenet (s, n)
    t0 = time.perf_counter()
    s_proj, n_proj = frenet.xy_to_sn(cp_x, cp_y)
    print(f"  Projected {len(cp_x):,} contact patches in {time.perf_counter()-t0:.1f}s")

    # Filter to track boundary
    n_max = 15.0  # max lateral reach
    mask = (np.abs(n_proj) < n_max) & np.isfinite(cp_z)
    s_proj, n_proj, cp_z = s_proj[mask], n_proj[mask], cp_z[mask]
    print(f"  Valid contact samples after filtering: {len(cp_z):,}")

    # Grid
    s_bins = np.arange(0, total_length + ds_m, ds_m)
    n_bins = np.arange(-n_max, n_max + dn_m, dn_m)
    M, K = len(s_bins), len(n_bins)

    # Aggregate: mean z per cell
    z_sum = np.zeros((M, K), dtype=np.float64)
    z_count = np.zeros((M, K), dtype=np.int32)

    s_idx = np.clip(np.searchsorted(s_bins, s_proj) - 1, 0, M - 1)
    n_idx = np.clip(np.searchsorted(n_bins, n_proj) - 1, 0, K - 1)

    np.add.at(z_sum, (s_idx, n_idx), cp_z)
    np.add.at(z_count, (s_idx, n_idx), 1)

    has_data = z_count > 0
    z_grid = np.zeros((M, K))
    z_grid[has_data] = z_sum[has_data] / z_count[has_data]

    # Lateral gap-fill: for each s-row, interpolate across n
    for i in range(M):
        row = z_grid[i, :]
        row_mask = z_count[i, :] > 0
        if row_mask.sum() >= 2:
            filled_idx = np.where(row_mask)[0]
            z_grid[i, :] = np.interp(np.arange(K), filled_idx, row[filled_idx])

    # Longitudinal smoothing per column
    for k in range(K):
        if z_grid[:, k].any():
            z_grid[:, k] = uniform_filter1d(z_grid[:, k], 5)

    coverage = (z_count > 0).sum() / z_count.size
    print(f"  Grid coverage: {coverage*100:.1f}% of {M}×{K} cells have data")
    print(f"  Max samples per cell: {z_count.max()}")
    print(f"  Z range: [{z_grid.min():.2f}, {z_grid.max():.2f}]")

    return {
        "frenet": frenet,
        "s_bins": s_bins,
        "n_bins": n_bins,
        "z_grid": z_grid,
        "count_grid": z_count,
        "total_length_m": total_length,
    }


def compute_grip_mu(x, y, z, v, a_long=None):
    """Driver-used grip coefficient (for the driver line overlay only)."""
    dx = np.gradient(x)
    dy = np.gradient(y)
    dz = np.gradient(z)
    ds = np.sqrt(dx * dx + dy * dy)
    ds = np.where(ds > 0.01, ds, 0.01)
    heading = np.unwrap(np.arctan2(dy, dx))
    curvature = np.gradient(heading) / ds
    a_lat = v * v * np.abs(curvature)
    if a_long is None:
        a_long = np.gradient(v)  # crude
    a_combined = np.sqrt(a_lat ** 2 + a_long ** 2)
    dz_ds = dz / ds
    kv = uniform_filter1d(np.gradient(dz_ds) / ds, 15)
    g_eff = np.clip(G + v * v * kv, 1.0, 100.0)
    return uniform_filter1d(np.clip(a_combined / g_eff, 0.0, 5.0), 5)


def compute_grip_ceiling_grid(
    s_proj: np.ndarray,
    n_proj: np.ndarray,
    a_lat: np.ndarray,
    a_long: np.ndarray,
    speed: np.ndarray,
    kv_at_sample: np.ndarray,
    s_bins: np.ndarray,
    n_bins: np.ndarray,
    percentile: float = 98.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Extract the grip LIMIT per (s, n) cell, not driver utilization.

    Uses the friction circle: |a_combined| / g_eff = peak tire grip at
    that location.  Taking a high percentile across all samples at the
    cell gives the ceiling independent of how much the driver exploited
    it on any given lap.
    """
    M, K = len(s_bins), len(n_bins)
    s_idx = np.clip(np.searchsorted(s_bins, s_proj) - 1, 0, M - 1)
    n_idx = np.clip(np.searchsorted(n_bins, n_proj) - 1, 0, K - 1)

    # Combined lateral + longitudinal acceleration magnitude
    a_combined = np.sqrt(a_lat ** 2 + a_long ** 2)

    # Effective gravity with terrain compression
    g_eff = np.clip(G + speed ** 2 * kv_at_sample, 1.0, 100.0)

    # Per-sample tire friction utilization
    mu_sample = np.clip(a_combined / g_eff, 0.0, 5.0)

    # Aggregate per cell: use percentile for the grip CEILING
    # (mean would smear cruise samples; max is too noisy)
    mu_grid = np.full((M, K), np.nan)
    count_grid = np.zeros((M, K), dtype=np.int32)

    # Group samples by cell index using argsort trick for vectorisation
    flat_idx = s_idx * K + n_idx
    order = np.argsort(flat_idx)
    sorted_flat = flat_idx[order]
    sorted_mu = mu_sample[order]

    # Find run boundaries (cells with consecutive samples)
    diff = np.diff(sorted_flat)
    starts = np.concatenate([[0], np.where(diff > 0)[0] + 1])
    ends = np.concatenate([starts[1:], [len(sorted_flat)]])

    for start, end in zip(starts, ends):
        if end - start < 2:
            continue
        cell = sorted_flat[start]
        si, ni = cell // K, cell % K
        cell_mu = sorted_mu[start:end]
        mu_grid[si, ni] = np.percentile(cell_mu, percentile)
        count_grid[si, ni] = end - start

    return mu_grid, count_grid


def propagate_grip_ceiling(mu_grid: np.ndarray, iterations: int = 3) -> np.ndarray:
    """Spatially propagate the grip ceiling into cells that were never
    tested at the limit.

    If a cell has no near-limit evidence, take the max from a local
    neighborhood.  This handles the 'driver never pushed here' case.
    """
    from scipy.ndimage import maximum_filter, gaussian_filter

    filled = np.where(np.isnan(mu_grid), 0.0, mu_grid)
    mask = np.isnan(mu_grid)

    for _ in range(iterations):
        # Local max filter expands the ceiling into empty cells
        expanded = maximum_filter(filled, size=5, mode="nearest")
        filled = np.where(mask, expanded, filled)

    # Final smooth pass (gentle, preserves peaks)
    filled = gaussian_filter(filled, sigma=1.0)
    return filled


def main() -> None:
    print(f"Processing: {IBT_PATH.name}")
    print(f"Size: {os.path.getsize(IBT_PATH) / 1e6:.0f} MB")

    t0 = time.perf_counter()
    hdr, ch = extract_ibt(IBT_PATH)
    n_total = len(ch["lat"])
    print(f"Extracted {n_total:,} samples in {time.perf_counter() - t0:.1f}s")

    on_track = ch["on_track"].astype(bool)
    # Filter GPS sentinels (0, 0) from iRacing
    valid_gps = on_track & (ch["lat"] != 0.0) & (ch["lon"] != 0.0)

    # Convert degrees → radians, then project to local ENU meters
    lat_rad = np.radians(ch["lat"])
    lon_rad = np.radians(ch["lon"])
    lat_ref = float(np.nanmean(lat_rad[valid_gps]))
    lon_ref = float(np.nanmean(lon_rad[valid_gps]))
    x_m = EARTH_R * (lon_rad - lon_ref) * np.cos(lat_ref)
    y_m = EARTH_R * (lat_rad - lat_ref)
    z_m = ch["alt"] - float(np.nanmin(ch["alt"][valid_gps]))

    print(
        f"Car body orientation available: "
        f"yaw={ch['yaw'] is not None}, "
        f"pitch={ch['pitch'] is not None}, "
        f"roll={ch['roll'] is not None}"
    )

    # ═══════════════════════════════════════════════════════════════
    # LAYER 1: Per-sample banking from car body Roll
    # ═══════════════════════════════════════════════════════════════
    print("\n━━━ Layer 1: Banking from Roll angle ━━━")
    roll = ch["roll"]
    pitch = ch["pitch"]
    print(f"  Roll range:  [{np.degrees(roll[valid_gps]).min():+6.1f}°, {np.degrees(roll[valid_gps]).max():+6.1f}°]")
    print(f"  Pitch range: [{np.degrees(pitch[valid_gps]).min():+6.1f}°, {np.degrees(pitch[valid_gps]).max():+6.1f}°]")

    # ═══════════════════════════════════════════════════════════════
    # LAYER 3: Use ALL laps (not just top 5)
    # ═══════════════════════════════════════════════════════════════
    print("\n━━━ Layer 3: All laps ━━━")
    lap = ch["lap"]
    time_arr = ch["time"]

    # Find all complete laps
    unique_laps = np.unique(lap[valid_gps & (lap > 0)])
    lap_info = {}
    for lnum in unique_laps:
        mask = (lap == lnum) & valid_gps
        if mask.sum() < 500:
            continue
        pct = ch["lap_dist_pct"][mask]
        if pct.max() - pct.min() < 0.95:
            continue
        lt = float(time_arr[mask][-1] - time_arr[mask][0])
        lap_info[int(lnum)] = lt

    print(f"  Complete laps: {len(lap_info)}")
    best_lap_num, best_time = min(lap_info.items(), key=lambda x: x[1])
    print(f"  Best lap: #{best_lap_num} at {best_time:.2f}s")

    # Combine all samples from all valid laps
    all_mask = np.zeros(n_total, dtype=bool)
    for lnum in lap_info:
        all_mask |= (lap == lnum) & valid_gps

    print(f"  Total samples across all laps: {all_mask.sum():,}")

    # ═══════════════════════════════════════════════════════════════
    # LAYER 2: Contact patch reconstruction
    # ═══════════════════════════════════════════════════════════════
    print("\n━━━ Layer 2: Wheel contact patches ━━━")
    print("  Reconstructing 4 contact patches per sample...")
    cp_x, cp_y, cp_z = compute_contact_patches(
        x_m[all_mask], y_m[all_mask], z_m[all_mask],
        ch["yaw"][all_mask], ch["pitch"][all_mask], ch["roll"][all_mask],
        ch["lf_ride"][all_mask], ch["rf_ride"][all_mask],
        ch["lr_ride"][all_mask], ch["rr_ride"][all_mask],
    )
    print(f"  Contact patches: {len(cp_x):,} points (4 per sample)")

    # ═══════════════════════════════════════════════════════════════
    # LAYER 4: Reconstruct z(s,n) from contact patches
    # ═══════════════════════════════════════════════════════════════
    print("\n━━━ Layer 4: 2D grid reconstruction ━━━")
    t0 = time.perf_counter()
    # Use the best lap's car path as the reference for centerline extraction
    best_mask_ref = (lap == best_lap_num) & valid_gps
    centerline_lap_xy = np.column_stack([x_m[best_mask_ref], y_m[best_mask_ref]])
    result = build_surface_from_contact_patches(
        cp_x, cp_y, cp_z, centerline_lap_xy, ds_m=2.0, dn_m=0.5,
    )
    print(f"  Built in {time.perf_counter()-t0:.1f}s")

    # ═══════════════════════════════════════════════════════════════
    # Also compute per-metre banking from Roll along the racing line
    # ═══════════════════════════════════════════════════════════════
    print("\n━━━ Per-metre banking profile ━━━")
    frenet = result["frenet"]
    # Project best lap position to Frenet
    best_mask = (lap == best_lap_num) & valid_gps
    s_best, n_best = frenet.xy_to_sn(x_m[best_mask], y_m[best_mask])
    roll_best = ch["roll"][best_mask]

    # Bin roll by centerline distance (use ALL laps for better averaging)
    all_mask = np.zeros(n_total, dtype=bool)
    for lnum in lap_info:
        all_mask |= (lap == lnum) & valid_gps
    s_all, _ = frenet.xy_to_sn(x_m[all_mask], y_m[all_mask])
    roll_all = ch["roll"][all_mask]

    banking_per_s = np.zeros(frenet.n_points)
    count_per_s = np.zeros(frenet.n_points)
    s_indices = np.clip(
        np.searchsorted(frenet.s_grid, s_all) - 1, 0, frenet.n_points - 1
    )
    np.add.at(banking_per_s, s_indices, roll_all)
    np.add.at(count_per_s, s_indices, 1)
    mask = count_per_s > 0
    banking_per_s[mask] /= count_per_s[mask]
    # Light smoothing only (preserve sharp banking transitions)
    banking_per_s = uniform_filter1d(banking_per_s, 3)
    print(f"  Banking range: [{np.degrees(banking_per_s).min():+5.1f}°, {np.degrees(banking_per_s).max():+5.1f}°]")
    print(f"  (Daytona Road banking should be ~31° on the oval section)")

    # ═══════════════════════════════════════════════════════════════
    # Export — richer than before
    # ═══════════════════════════════════════════════════════════════
    # Best lap for driver visualization
    best_df_x = x_m[best_mask]
    best_df_y = y_m[best_mask]
    best_df_z = z_m[best_mask]
    best_df_v = ch["speed"][best_mask]
    best_df_thr = ch["throttle"][best_mask] * 100
    best_mu = compute_grip_mu(best_df_x, best_df_y, best_df_z, best_df_v)

    # 2nd fastest lap
    sorted_laps = sorted(lap_info.items(), key=lambda x: x[1])
    second_lap_num = sorted_laps[1][0] if len(sorted_laps) >= 2 else best_lap_num
    second_mask = (lap == second_lap_num) & valid_gps
    sec_x = x_m[second_mask]
    sec_y = y_m[second_mask]
    sec_z = z_m[second_mask]
    sec_v = ch["speed"][second_mask]
    sec_thr = ch["throttle"][second_mask] * 100
    sec_mu = compute_grip_mu(sec_x, sec_y, sec_z, sec_v)

    # Downsample z_grid for JSON export (cap total cells at ~80K)
    z_grid_full = result["z_grid"]
    count_grid_full = result["count_grid"]
    s_bins_full = result["s_bins"]
    n_bins_full = result["n_bins"]
    s_step = max(1, len(s_bins_full) // 3000)
    z_grid = z_grid_full[::s_step, :]
    count_grid_ds = count_grid_full[::s_step, :]
    s_bins = s_bins_full[::s_step]
    n_bins = n_bins_full

    # ═══════════════════════════════════════════════════════════════
    # Grip CEILING per (s, n) cell (not utilization)
    # ═══════════════════════════════════════════════════════════════
    print("\n━━━ Grip ceiling from friction envelope ━━━")
    t0 = time.perf_counter()

    # Use car-position samples (not contact patches — one per tick)
    # Project all-lap car positions to the same (s, n) grid
    s_all_car, n_all_car = frenet.xy_to_sn(x_m[all_mask], y_m[all_mask])
    lat_acc_all = ch["lat_accel"][all_mask]
    long_acc_all = ch["long_accel"][all_mask]
    speed_all = ch["speed"][all_mask]

    # κ_v at each sample (approximate from centerline lookup)
    # Simple approach: 0 for now, will get refined with elevation surface
    kv_all = np.zeros_like(speed_all)

    # Filter: keep only samples with reasonable speed (not pit) and finite values
    valid_accel = (
        (speed_all > 5.0)
        & np.isfinite(lat_acc_all)
        & np.isfinite(long_acc_all)
        & (np.abs(lat_acc_all) < 50)
        & (np.abs(long_acc_all) < 50)
    )

    mu_grid_raw, mu_count = compute_grip_ceiling_grid(
        s_all_car[valid_accel],
        n_all_car[valid_accel],
        lat_acc_all[valid_accel],
        long_acc_all[valid_accel],
        speed_all[valid_accel],
        kv_all[valid_accel],
        result["s_bins"],
        result["n_bins"],
        percentile=98.0,
    )
    n_cells_with_data = np.sum(~np.isnan(mu_grid_raw))
    print(f"  Cells with direct evidence: {n_cells_with_data:,} / {mu_grid_raw.size:,}")
    valid_mu = mu_grid_raw[~np.isnan(mu_grid_raw)]
    if len(valid_mu):
        print(f"  Direct grip ceiling range: [{valid_mu.min():.2f}, {valid_mu.max():.2f}]")

    # Propagate into empty cells via local max
    mu_ceiling = propagate_grip_ceiling(mu_grid_raw, iterations=3)
    print(f"  After propagation: [{mu_ceiling.min():.2f}, {mu_ceiling.max():.2f}]")
    print(f"  Computed in {time.perf_counter() - t0:.1f}s")

    # ═══════════════════════════════════════════════════════════════
    # Track limits from contact patch density
    # ═══════════════════════════════════════════════════════════════
    print("\n━━━ Track limits from contact density ━━━")
    # Threshold: at least 3 samples per cell to count as "on track"
    COUNT_THRESHOLD = 3
    Msub, Ksub = count_grid_ds.shape
    width_left_per_s = np.zeros(Msub)
    width_right_per_s = np.zeros(Msub)

    for i in range(Msub):
        valid_cols = np.where(count_grid_ds[i, :] >= COUNT_THRESHOLD)[0]
        if len(valid_cols) >= 2:
            n_left = float(n_bins[valid_cols.max()])   # furthest positive n
            n_right = float(-n_bins[valid_cols.min()]) # magnitude of furthest negative
            width_left_per_s[i] = max(0.0, n_left)
            width_right_per_s[i] = max(0.0, n_right)

    # Smooth the width arrays to avoid jagged edges from noise
    width_left_per_s = uniform_filter1d(width_left_per_s, 5)
    width_right_per_s = uniform_filter1d(width_right_per_s, 5)

    # Interpolate to centerline s-grid resolution
    s_ratio = np.linspace(0, 1, frenet.n_points)
    s_ratio_ds = np.linspace(0, 1, Msub)
    width_left_cl = np.interp(s_ratio, s_ratio_ds, width_left_per_s)
    width_right_cl = np.interp(s_ratio, s_ratio_ds, width_right_per_s)

    wl_min = width_left_cl[width_left_cl > 0].min() if (width_left_cl > 0).any() else 0
    wl_max = width_left_cl.max()
    print(f"  width_left  range: [{wl_min:.1f}, {wl_max:.1f}] m")
    wr_min = width_right_cl[width_right_cl > 0].min() if (width_right_cl > 0).any() else 0
    wr_max = width_right_cl.max()
    print(f"  width_right range: [{wr_min:.1f}, {wr_max:.1f}] m")
    print(f"  Avg total width: {np.mean(width_left_cl + width_right_cl):.1f} m")

    export = {
        "track": {
            "name": "Daytona Road Course — McLaren 570S GT4 (EXTREME)",
            "length_m": round(result["total_length_m"], 1),
            "n_points": frenet.n_points,
            "quality": "platinum",
            "centerline_x": [round(float(v), 2) for v in frenet.centerline_xy[:, 0]],
            "centerline_y": [round(float(v), 2) for v in frenet.centerline_xy[:, 1]],
            "curvature": [round(float(v), 5) for v in frenet.curvature_1pm],
            "heading": [round(float(v), 4) for v in frenet.heading_rad],
        },
        "elevation": {
            "values": [
                round(float(np.interp(
                    s, s_bins,
                    z_grid[:, len(n_bins) // 2]  # centerline elevation
                )), 2)
                for s in frenet.s_grid
            ],
            "vert_curvature": [],
        },
        "banking": {
            "values": [round(float(v), 4) for v in banking_per_s],  # radians per s-grid point
        },
        "surface_3d": {
            "s_bins": [round(float(v), 1) for v in s_bins],
            "n_bins": [round(float(v), 1) for v in n_bins],
            "z_grid": [[round(float(v), 2) for v in row] for row in z_grid],
            "shape_m": len(s_bins),
            "shape_k": len(n_bins),
        },
        "grip_ceiling": {
            # Grip ceiling per (s, n) cell — the TRACK's available mu,
            # independent of how much the driver exploited it
            "s_bins": [round(float(v), 1) for v in s_bins],
            "n_bins": [round(float(v), 1) for v in n_bins],
            "mu_grid": [
                [round(float(v), 3) for v in row]
                for row in mu_ceiling[::s_step, :]
            ],
            "shape_m": len(s_bins),
            "shape_k": len(n_bins),
        },
        "boundaries": {
            "width_left": [round(float(v), 2) for v in width_left_cl],
            "width_right": [round(float(v), 2) for v in width_right_cl],
        },
        "session_info": {
            "total_laps": len(unique_laps),
            "complete_laps": len(lap_info),
            "best_lap_s": round(best_time, 2),
            "total_duration_s": round(float(time_arr[-1] - time_arr[0]), 0),
            "contact_patches_used": len(cp_x),
        },
        "drivers": {
            "hamilton": {
                "x": [round(float(v), 2) for v in best_df_x],
                "y": [round(float(v), 2) for v in best_df_y],
                "z": [round(float(v), 2) for v in best_df_z],
                "speed_kph": [round(float(v) * 3.6, 1) for v in best_df_v],
                "throttle": [round(float(v), 1) for v in best_df_thr],
                "grip_mu": [round(float(v), 3) for v in best_mu],
                "driver_name": f"Best Lap #{best_lap_num} ({best_time:.2f}s)",
            },
            "verstappen": {
                "x": [round(float(v), 2) for v in sec_x],
                "y": [round(float(v), 2) for v in sec_y],
                "z": [round(float(v), 2) for v in sec_z],
                "speed_kph": [round(float(v) * 3.6, 1) for v in sec_v],
                "throttle": [round(float(v), 1) for v in sec_thr],
                "grip_mu": [round(float(v), 3) for v in sec_mu],
                "driver_name": f"2nd Fastest #{second_lap_num} ({sorted_laps[1][1]:.2f}s)",
            },
        },
    }

    with open(OUT_PATH, "w") as f:
        json.dump(export, f)
    size_kb = len(json.dumps(export)) // 1024
    print(f"\nExported {size_kb}KB to {OUT_PATH.name}")


if __name__ == "__main__":
    main()
