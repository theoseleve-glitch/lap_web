"""Build physics-robust grip ceiling and (optionally) animated grip frames
from an iRacing .ibt session, patching track-surface-spa-data.json and
re-embedding into the visualization HTML.

Phase 1 of this script: static physics grip ceiling only (no animation yet).
Phase 2 adds the rolling-window animation in a follow-up edit.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.ndimage import uniform_filter1d

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "telemetry_tool"))

from lap_oracle.extractors.iracing_ibt import _parse_header, _parse_var_headers
from track_surface.adaptive_model import AdaptiveVehicleModel
from track_surface.animated_grip import build_animation_frames, build_lap_slices
from track_surface.physics_validation import validate_physics_model
from track_surface.grip_binary_encoder import encode_frames
from track_surface.physics_grip import (
    build_physics_grip_grid,
    build_vehicle_geometry,
    compute_mu_per_wheel,
    compute_per_wheel_normal_loads,
    compute_per_wheel_tangential_forces,
    propagate_physics_grip,
)

IBT_PATH = Path(
    "C:/Users/Admin/Documents/iRacing/telemetry/"
    "mclaren570sgt4_daytona 2011 road 2026-01-09 23-40-48.ibt"
)
JSON_PATH = _PROJECT_ROOT / "track-surface-spa-data.json"
HTML_PATH = _PROJECT_ROOT / "track-surface-spa.html"

G = 9.80665
EARTH_R = 6371000.0
TYPE_DTYPE = {1: np.uint8, 2: np.int32, 3: np.uint32, 4: np.float32, 5: np.float64}
TYPE_SIZE = {1: 1, 2: 4, 3: 4, 4: 4, 5: 8}


def extract_all_channels(path: Path) -> tuple[dict, pd.DataFrame]:
    """Extract ALL float channels from the .ibt as (raw_dict, irsdk_df).

    raw_dict has bare channel names (e.g. "Speed", "LatAccel").
    irsdk_df has columns prefixed with "irsdk__" for optimize_session().
    """
    with open(path, "rb") as f:
        header_bytes = f.read(max(4096, 144 * 500 + 200))
        hdr = _parse_header(header_bytes)
        vars_map = _parse_var_headers(header_bytes, hdr)
        file_size = os.path.getsize(path)
        num_samples = (file_size - hdr["data_start"]) // hdr["buf_len"]
        f.seek(hdr["data_start"])
        raw = f.read(hdr["buf_len"] * num_samples)
        arr = np.frombuffer(raw, dtype=np.uint8).reshape(num_samples, hdr["buf_len"])

    data: dict[str, np.ndarray] = {}
    irsdk_cols: dict[str, np.ndarray] = {}
    for name, info in vars_map.items():
        if info.get("count", 1) != 1:
            continue
        t = info["type"]
        if t not in TYPE_SIZE:
            continue
        off = info["offset"]
        sz = TYPE_SIZE[t]
        dt = TYPE_DTYPE[t]
        buf = np.frombuffer(arr[:, off : off + sz].tobytes(), dtype=dt)
        data[name] = buf.astype(np.float64)
        irsdk_cols[f"irsdk__{name}"] = buf.astype(np.float64)

    return data, pd.DataFrame(irsdk_cols)


def project_to_world_meters(
    lat_deg: np.ndarray, lon_deg: np.ndarray, alt_m: np.ndarray, valid_mask: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Equirectangular projection to local ENU metres."""
    lat_rad = np.radians(lat_deg)
    lon_rad = np.radians(lon_deg)
    lat_ref = float(np.nanmean(lat_rad[valid_mask]))
    lon_ref = float(np.nanmean(lon_rad[valid_mask]))
    x_m = EARTH_R * (lon_rad - lon_ref) * np.cos(lat_ref)
    y_m = EARTH_R * (lat_rad - lat_ref)
    z_m = alt_m - float(np.nanmin(alt_m[valid_mask]))
    return x_m, y_m, z_m


def build_frenet_from_best_lap(
    x_m, y_m, lap, valid_mask, best_lap_num
):
    """Build Frenet frame from one clean lap."""
    from track_surface.centerline import extract_centerline
    from track_surface.frenet import FrenetFrame

    best_mask = (lap == best_lap_num) & valid_mask
    centerline_xy = np.column_stack([x_m[best_mask], y_m[best_mask]])
    cl, total_length = extract_centerline([centerline_xy], ds_m=1.0)
    return FrenetFrame.from_centerline(cl), total_length


def identify_complete_laps(
    lap: np.ndarray, valid_mask: np.ndarray, time_arr: np.ndarray, lap_dist_pct: np.ndarray
) -> dict[int, float]:
    """Return dict of {lap_number: lap_time_s} for laps that completed >=95%."""
    lap_info = {}
    unique_laps = np.unique(lap[valid_mask & (lap > 0)])
    for lnum in unique_laps:
        mask = (lap == lnum) & valid_mask
        if mask.sum() < 500:
            continue
        pct = lap_dist_pct[mask]
        if pct.max() - pct.min() < 0.95:
            continue
        lt = float(time_arr[mask][-1] - time_arr[mask][0])
        lap_info[int(lnum)] = lt
    return lap_info


def compute_shock_means(
    ch: dict, valid_mask: np.ndarray, a_long: np.ndarray, a_lat: np.ndarray,
    speed: np.ndarray,
) -> tuple[float, float, float, float] | None:
    """Mean steady-state shock deflection per wheel for weight dist inference."""
    required = ["LFshockDefl", "RFshockDefl", "LRshockDefl", "RRshockDefl"]
    if not all(k in ch for k in required):
        return None
    steady = (
        valid_mask
        & (speed > 20.0)
        & (np.abs(a_long) < 1.5)
        & (np.abs(a_lat) < 1.5)
    )
    if steady.sum() < 100:
        return None
    return (
        float(np.mean(ch["LFshockDefl"][steady])),
        float(np.mean(ch["RFshockDefl"][steady])),
        float(np.mean(ch["LRshockDefl"][steady])),
        float(np.mean(ch["RRshockDefl"][steady])),
    )


def get_vehicle_defaults(fitted_vehicle) -> dict:
    """Extract usable values from the fitted VehicleModel with sane fallbacks."""
    defaults = {
        "mass_kg": 1300.0,
        "aero_cla": 1.5,
        "aero_cda": 0.95,
        "brake_bias_front": 0.50,
    }
    if fitted_vehicle is None:
        return defaults
    try:
        defaults["mass_kg"] = fitted_vehicle.total_mass_kg(30.0)
    except Exception:
        pass
    try:
        cla = fitted_vehicle.aero.cla
        defaults["aero_cla"] = cla if cla > 0.1 else 1.5
    except Exception:
        pass
    try:
        defaults["aero_cda"] = fitted_vehicle.aero.cda
    except Exception:
        pass
    try:
        bbf = fitted_vehicle.brake.brake_bias_front
        if 0.3 <= bbf <= 0.8:
            defaults["brake_bias_front"] = float(bbf)
    except Exception:
        pass
    return defaults


def build_per_wheel_brake_pressure(ch: dict, valid_mask_for_slice: np.ndarray) -> np.ndarray | None:
    """Return (N, 4) brake-line pressure or None if channels absent."""
    required = ["LFbrakeLinePress", "RFbrakeLinePress", "LRbrakeLinePress", "RRbrakeLinePress"]
    if not all(k in ch for k in required):
        return None
    return np.column_stack([
        ch["LFbrakeLinePress"][valid_mask_for_slice],
        ch["RFbrakeLinePress"][valid_mask_for_slice],
        ch["LRbrakeLinePress"][valid_mask_for_slice],
        ch["RRbrakeLinePress"][valid_mask_for_slice],
    ])


def main() -> None:
    t_total = time.perf_counter()
    print(f"Processing: {IBT_PATH.name}")
    print(f"Size: {os.path.getsize(IBT_PATH) / 1e6:.0f} MB")

    # ── 1. Extract channels ─────────────────────────────────────────
    t0 = time.perf_counter()
    ch, df_irsdk = extract_all_channels(IBT_PATH)
    print(f"Extracted {len(df_irsdk):,} samples in {time.perf_counter() - t0:.1f}s")

    valid_gps = (
        ch["IsOnTrack"].astype(bool)
        & (ch["Lat"] != 0.0)
        & (ch["Lon"] != 0.0)
    )
    print(f"Valid on-track samples: {valid_gps.sum():,}")

    # ── 2. Fit VehicleModel ──────────────────────────────────────────
    t0 = time.perf_counter()
    print("\nFitting vehicle model via optimize_session()…")
    try:
        from sim_optimizer.pipeline import optimize_session
        sim_result = optimize_session(df_irsdk)
        vehicle = sim_result.vehicle_model
        print(f"  Fit in {time.perf_counter() - t0:.1f}s — success={sim_result.success}")
    except Exception as exc:
        print(f"  optimize_session failed: {exc}")
        vehicle = None

    defaults = get_vehicle_defaults(vehicle)
    print(f"Vehicle parameters (fitted + fallback):")
    for k, v in defaults.items():
        print(f"  {k:20} = {v}")

    # ── 3. Project to local meters ─────────────────────────────────
    x_m, y_m, z_m = project_to_world_meters(
        ch["Lat"], ch["Lon"], ch["Alt"], valid_gps
    )

    # ── 4. Best lap & Frenet frame ─────────────────────────────────
    lap_info = identify_complete_laps(
        ch["Lap"], valid_gps, ch["SessionTime"], ch["LapDistPct"]
    )
    if not lap_info:
        print("No complete laps found — cannot proceed")
        return
    best_lap_num = min(lap_info.keys(), key=lambda k: lap_info[k])
    best_time = lap_info[best_lap_num]
    print(f"\nBest lap: #{best_lap_num} at {best_time:.2f}s ({len(lap_info)} complete laps)")

    frenet, total_length = build_frenet_from_best_lap(
        x_m, y_m, ch["Lap"], valid_gps, best_lap_num
    )
    print(f"Frenet frame: {frenet.n_points} points, {total_length:.0f}m")

    # ── 5. Use all laps, build per-sample physics ─────────────────
    all_mask = np.zeros(len(ch["Lat"]), dtype=bool)
    for lnum in lap_info:
        all_mask |= (ch["Lap"] == lnum) & valid_gps
    n_all = all_mask.sum()
    print(f"Total samples across {len(lap_info)} complete laps: {n_all:,}")

    shock_means = compute_shock_means(
        ch, valid_gps, ch["LongAccel"], ch["LatAccel"], ch["Speed"]
    )
    if shock_means is not None:
        front_frac = (shock_means[0] + shock_means[1]) / sum(shock_means)
        print(f"Mean shock deflection (steady): front fraction = {front_frac:.3f}")
    else:
        print("Shock deflection data unavailable — using default weight distribution")

    geom = build_vehicle_geometry(
        vehicle,
        shock_defl_mean=shock_means,
    )
    print(
        f"Geometry: wb={geom.wheelbase_m}m, "
        f"tf={geom.track_front_m}m, tr={geom.track_rear_m}m, "
        f"h_cg={geom.cg_height_m}m, wd_f={geom.weight_dist_front:.3f}, "
        f"brake_bias_f={geom.brake_bias_front:.2f}"
    )

    # Slice arrays
    speed_all = ch["Speed"][all_mask]
    a_long_all = ch["LongAccel"][all_mask]
    a_lat_all = ch["LatAccel"][all_mask]
    roll_all = ch["Roll"][all_mask]
    pitch_all = ch["Pitch"][all_mask]

    # Per-wheel brake pressure (optional)
    brake_press = build_per_wheel_brake_pressure(ch, all_mask)
    if brake_press is not None:
        print(f"Using per-wheel brake pressures (max: {brake_press.max():.0f})")
    else:
        print("No per-wheel brake pressure — using bias fallback")

    # ── Build ride heights array (used by both calibration and validation) ──
    rh_available = all(k in ch for k in ["LFrideHeight", "RFrideHeight", "LRrideHeight", "RRrideHeight"])
    ride_heights = None
    if rh_available:
        ride_heights = np.column_stack([
            ch["LFrideHeight"][all_mask],
            ch["RFrideHeight"][all_mask],
            ch["LRrideHeight"][all_mask],
            ch["RRrideHeight"][all_mask],
        ])
        print(f"Ride heights available: {ride_heights.shape}")

    # ── Adaptive model calibration ───────────────────────────────
    if ride_heights is not None:
        print("\nRunning adaptive model calibration (ride-height feedback)…")
        t0 = time.perf_counter()
        adaptive = AdaptiveVehicleModel.from_vehicle_geometry(
            geom,
            spring_rates=np.array([
                getattr(vehicle.suspension, "spring_rate_lf", 100000),
                getattr(vehicle.suspension, "spring_rate_rf", 100000),
                getattr(vehicle.suspension, "spring_rate_lr", 100000),
                getattr(vehicle.suspension, "spring_rate_rr", 100000),
            ]) if vehicle and vehicle.suspension else None,
            aero_cla=defaults["aero_cla"],
        )
        brake_pct_all = ch["Brake"][all_mask] * 100.0
        throttle_pct_all = ch["Throttle"][all_mask] * 100.0

        cal_diag = adaptive.calibrate_from_session(
            mass_kg=defaults["mass_kg"],
            speed=speed_all,
            a_long=a_long_all,
            a_lat=a_lat_all,
            roll=roll_all,
            pitch=pitch_all,
            ride_heights=ride_heights,
            brake_pct=brake_pct_all,
            throttle_pct=throttle_pct_all,
            max_iterations=8,
        )
        geom = adaptive.to_geometry()
        defaults["brake_bias_front"] = adaptive.brake_bias_front
        defaults["aero_cla"] = adaptive.aero_cla

        print(f"  Calibrated in {time.perf_counter() - t0:.1f}s")
        init = cal_diag["initial"]
        final = cal_diag["final"]
        print(f"  {'Parameter':<28} {'Initial':>10} {'Final':>10} {'Delta':>10}")
        print(f"  {'-'*60}")
        for key in final:
            iv = init.get(key)
            fv = final[key]
            if isinstance(fv, float):
                delta = fv - iv if isinstance(iv, float) else 0
                print(f"  {key:<28} {iv:>10.4f} {fv:>10.4f} {delta:>+10.4f}")
            elif isinstance(fv, list):
                print(f"  {key:<28} {str(iv):<25} → {str(fv)}")
        print(f"  converged: {cal_diag['converged']}")
    else:
        print("\nNo ride height data — skipping adaptive calibration")

    print("\nComputing per-wheel normal loads…")
    t0 = time.perf_counter()
    loads = compute_per_wheel_normal_loads(
        mass_kg=defaults["mass_kg"],
        speed_mps=speed_all,
        a_long_body=a_long_all,
        a_lat_body=a_lat_all,
        roll_rad=roll_all,
        pitch_rad=pitch_all,
        aero_cla=defaults["aero_cla"],
        air_density=1.225,
        geom=geom,
    )
    print(f"  Done in {time.perf_counter() - t0:.1f}s")
    print(f"  Mean Fz: LF={loads.fz[:,0].mean():.0f} RF={loads.fz[:,1].mean():.0f} "
          f"LR={loads.fz[:,2].mean():.0f} RR={loads.fz[:,3].mean():.0f} N")
    print(f"  Mean total Fz: {loads.fz_total.mean():.0f} N "
          f"(aero factor {loads.aero_factor.mean():.2f})")

    print("Computing per-wheel tangential forces…")
    t0 = time.perf_counter()
    f_tang = compute_per_wheel_tangential_forces(
        mass_kg=defaults["mass_kg"],
        fz_per_wheel=loads.fz,
        a_long_body=a_long_all,
        a_lat_body=a_lat_all,
        brake_line_press=brake_press,
        brake_bias_front=defaults["brake_bias_front"],
        drive_rear_only=True,
    )
    print(f"  Done in {time.perf_counter() - t0:.1f}s")

    print("Computing per-wheel mu…")
    mu_wheels = compute_mu_per_wheel(loads.fz, f_tang)
    valid_mu = mu_wheels[np.isfinite(mu_wheels)]
    print(f"  Direct μ samples: {len(valid_mu):,}")
    print(f"  μ range: [{valid_mu.min():.3f}, {valid_mu.max():.3f}]")
    print(f"  μ mean/p95/p99: {valid_mu.mean():.3f} / "
          f"{np.percentile(valid_mu, 95):.3f} / {np.percentile(valid_mu, 99):.3f}")

    # ── 5b. Physics model validation ──────────────────────────────
    print("\nRunning physics model validation...")
    # ride_heights already computed above (before calibration step)

    spring_rates = None
    if vehicle is not None and hasattr(vehicle, "suspension") and vehicle.suspension is not None:
        sr = vehicle.suspension
        rates = []
        for attr in ("spring_rate_lf", "spring_rate_rf", "spring_rate_lr", "spring_rate_rr"):
            v = getattr(sr, attr, None)
            if v is not None and v > 0:
                rates.append(float(v))
        if len(rates) == 4:
            spring_rates = np.array(rates)

    # Tire temps (average across zones to single per-wheel value)
    tt_available = all(f"irsdk__{w}tempCM" in df_irsdk.columns for w in ["LF", "RF", "LR", "RR"])
    tire_temps = None
    if tt_available:
        tire_temps = np.column_stack([
            df_irsdk[f"irsdk__{w}tempCM"].values[all_mask]
            for w in ["LF", "RF", "LR", "RR"]
        ])

    valid_for_val = (speed_all > 5.0) & np.isfinite(a_lat_all)
    report = validate_physics_model(
        fz_per_wheel=loads.fz,
        aero_factor=loads.aero_factor,
        mu_per_wheel=mu_wheels,
        mass_kg=defaults["mass_kg"],
        geom=geom,
        a_lat=a_lat_all,
        speed=speed_all,
        ride_heights_mm=ride_heights,
        spring_rates_npm=spring_rates,
        tire_temps_c=tire_temps,
        valid_mask=valid_for_val,
    )
    report.print_report()

    # ── 6. Project to Frenet + build grid ──────────────────────────
    print("\nProjecting to Frenet and building physics grip grid…")
    t0 = time.perf_counter()
    s_all, n_proj_all = frenet.xy_to_sn(x_m[all_mask], y_m[all_mask])

    # Effective gravity (terrain correction, same as extreme script)
    g_eff_all = np.full(n_all, G)  # simple constant for now; compression via κ_v
    a_body_mag = np.sqrt(a_long_all ** 2 + a_lat_all ** 2)

    # Grid: match the extreme script's (s, n) binning for consistent display
    ds_m = 2.0
    dn_m = 0.5
    n_range_m = 15.0
    s_bins = np.arange(0, total_length + ds_m, ds_m)
    n_bins = np.arange(-n_range_m, n_range_m + dn_m, dn_m)

    mu_grid_raw = build_physics_grip_grid(
        s_proj=s_all,
        n_proj=n_proj_all,
        mu_per_wheel=mu_wheels,
        a_body_mag=a_body_mag,
        g_eff=g_eff_all,
        s_bins=s_bins,
        n_bins=n_bins,
        util_threshold=0.55,
        percentile=95.0,
    )
    print(f"  Raw grid built in {time.perf_counter() - t0:.1f}s")
    direct_cells = np.sum(~np.isnan(mu_grid_raw))
    print(f"  Cells with direct evidence: {direct_cells:,} / {mu_grid_raw.size:,}")

    mu_grid_filled = propagate_physics_grip(mu_grid_raw, iterations=3)
    print(f"  After propagation: μ range "
          f"[{mu_grid_filled.min():.3f}, {mu_grid_filled.max():.3f}]")

    # ── 6b. Animated grip frames (one per lap, rolling window) ────
    print("\nBuilding animated grip frames (rolling 5-lap window)…")
    t0 = time.perf_counter()
    # Lap indexing across the all_mask arrays
    # Build slices against the original full-length arrays so we can index
    # into the same mu_per_wheel arrays computed above
    lap_full = ch["Lap"]
    time_full = ch["SessionTime"]
    # We need valid_mask aligned to the slice of samples we used (all_mask)
    # Easiest: re-index into the all_mask slice with local indices
    lap_local = lap_full[all_mask]
    time_local = time_full[all_mask]
    valid_local = np.ones(len(lap_local), dtype=bool)

    lap_slices = build_lap_slices(lap_local, valid_local, time_local)
    print(f"  Found {len(lap_slices)} lap slices from animated indexing")

    # Downsample for animation size budget (~400 × 20 = 8000 cells/frame)
    # At 74 frames this yields ~590 KB raw → ~790 KB base64 payload
    ds_s_anim = max(1, len(s_bins) // 400)
    ds_n_anim = max(1, len(n_bins) // 20)

    frames, lap_numbers, lap_times = build_animation_frames(
        lap_slices=lap_slices,
        s_proj=s_all,
        n_proj=n_proj_all,
        mu_per_wheel=mu_wheels,
        a_body_mag=a_body_mag,
        g_eff=g_eff_all,
        s_bins=s_bins,
        n_bins=n_bins,
        window_laps=5,
        decay=0.5,
        util_threshold=0.55,
        percentile=95.0,
        downsample_s=ds_s_anim,
        downsample_n=ds_n_anim,
    )
    print(
        f"  Built {len(lap_numbers)} frames, shape {frames.shape} "
        f"in {time.perf_counter() - t0:.1f}s"
    )

    # Encode to base64
    t0 = time.perf_counter()
    encoded = encode_frames(
        frames=frames,
        lap_numbers=lap_numbers,
        lap_times_s=lap_times,
        mu_range=(0.0, 2.55),
    )
    payload_kb = len(encoded.base64_payload) // 1024
    print(
        f"  Encoded to {payload_kb} KB base64 "
        f"({frames.nbytes / 1024:.0f} KB raw) in {time.perf_counter() - t0:.1f}s"
    )

    # ── 7. Patch JSON ──────────────────────────────────────────────
    print(f"\nPatching {JSON_PATH.name}…")
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Downsample for JSON size match with existing surface_3d
    # Match the existing extreme export's s_step reasoning
    s_step = max(1, len(s_bins) // 3000)
    mu_grid_export = mu_grid_filled[::s_step, :]
    s_bins_export = s_bins[::s_step]

    data["grip_ceiling_phys"] = {
        "s_bins": [round(float(v), 1) for v in s_bins_export[: mu_grid_export.shape[0]]],
        "n_bins": [round(float(v), 1) for v in n_bins[: mu_grid_export.shape[1]]],
        "mu_grid": [
            [round(float(v), 3) for v in row]
            for row in mu_grid_export
        ],
        "shape_m": mu_grid_export.shape[0],
        "shape_k": mu_grid_export.shape[1],
    }
    data["vehicle_model_fitted"] = {
        "mass_kg": round(defaults["mass_kg"], 1),
        "aero_cla": round(defaults["aero_cla"], 3),
        "aero_cda": round(defaults["aero_cda"], 3),
        "brake_bias_front": round(defaults["brake_bias_front"], 3),
        "weight_dist_front": round(geom.weight_dist_front, 3),
        "cg_height_m": geom.cg_height_m,
        "wheelbase_m": geom.wheelbase_m,
    }
    data["grip_animation"] = encoded.to_export_dict()

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f)
    json_kb = len(json.dumps(data)) // 1024
    print(f"  JSON patched: {json_kb} KB")

    # ── 8. Re-inline into HTML ────────────────────────────────────
    print(f"Re-embedding into {HTML_PATH.name}…")
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        raw_data = f.read()
    html = re.sub(
        r"<script>const INLINE_DATA = .*?</script>\s*",
        "",
        html,
        flags=re.DOTALL,
    )
    html = html.replace(
        '<script type="importmap">',
        f"<script>const INLINE_DATA = {raw_data};</script>\n"
        '<script type="importmap">',
    )
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  HTML size: {len(html) // 1024} KB")

    print(f"\nTotal time: {time.perf_counter() - t_total:.1f}s")


if __name__ == "__main__":
    main()
