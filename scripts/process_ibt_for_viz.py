"""Process an iRacing .ibt session through the track surface pipeline and
export JSON for the 3D visualizer."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.ndimage import uniform_filter1d

# Add telemetry_tool to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telemetry_tool"))

from lap_oracle.extractors.iracing_ibt import _parse_header, _parse_var_headers
from track_surface.builder import build_track_surface

IBT_PATH = Path(
    "C:/Users/Admin/Documents/iRacing/telemetry/"
    "mclaren570sgt4_daytona 2011 road 2026-01-09 23-40-48.ibt"
)
OUT_PATH = Path(__file__).resolve().parent.parent / "track-surface-spa-data.json"

G = 9.80665
EARTH_R = 6371000.0
TYPE_DTYPE = {1: np.uint8, 2: np.int32, 3: np.uint32, 4: np.float32, 5: np.float64}
TYPE_SIZE = {1: 1, 2: 4, 3: 4, 4: 4, 5: 8}


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
        "lat": get("Lat"),
        "lon": get("Lon"),
        "alt": get("Alt"),
        "speed": get("Speed"),
        "throttle": get("Throttle"),
        "brake": get("Brake"),
        "steer": get("SteeringWheelAngle"),
        "lat_accel": get("LatAccel"),
        "long_accel": get("LongAccel"),
        "vert_accel": get("VertAccel"),
        "lap": get("Lap"),
        "lap_dist": get("LapDist"),
        "lap_dist_pct": get("LapDistPct"),
        "time": get("SessionTime"),
        "rpm": get("RPM"),
        "gear": get("Gear"),
        "on_track": get("IsOnTrack"),
    }
    return hdr, channels


def compute_grip_mu(df: pd.DataFrame) -> np.ndarray:
    dx = np.gradient(df["pos_x_m"].to_numpy())
    dy = np.gradient(df["pos_y_m"].to_numpy())
    dz = np.gradient(df["pos_z_m"].to_numpy())
    ds = np.sqrt(dx * dx + dy * dy)
    ds = np.where(ds > 0.01, ds, 0.01)
    heading = np.unwrap(np.arctan2(dy, dx))
    curvature = np.gradient(heading) / ds
    v = df["speed_mps"].to_numpy()
    a_lat = v * v * np.abs(curvature)
    dz_ds = dz / ds
    kv = uniform_filter1d(np.gradient(dz_ds) / ds, 15)
    g_eff = np.clip(G + v * v * kv, 1.0, 100.0)
    return uniform_filter1d(np.clip(a_lat / g_eff, 0.0, 5.0), 5)


def main() -> None:
    print(f"Processing: {IBT_PATH.name}")
    print(f"Size: {os.path.getsize(IBT_PATH) / 1e6:.0f} MB")

    t0 = time.perf_counter()
    hdr, ch = extract_ibt(IBT_PATH)
    n = len(ch["lat"])
    print(f"Extracted {n} samples in {time.perf_counter() - t0:.1f}s")
    print(f"Max speed: {np.nanmax(ch['speed']) * 3.6:.0f} kph")
    print(f"Max lap: {int(np.nanmax(ch['lap']))}")

    on_track = ch["on_track"].astype(bool)
    lap = ch["lap"]
    time_arr = ch["time"]

    # iRacing Lat/Lon are in DEGREES, with (0,0) as sentinel for invalid samples.
    # Filter those out before averaging.
    valid_gps = on_track & (ch["lat"] != 0.0) & (ch["lon"] != 0.0)

    # Convert degrees → radians, then project to local ENU metres
    lat_rad = np.radians(ch["lat"])
    lon_rad = np.radians(ch["lon"])
    lat_ref = float(np.nanmean(lat_rad[valid_gps]))
    lon_ref = float(np.nanmean(lon_rad[valid_gps]))
    x_m = EARTH_R * (lon_rad - lon_ref) * np.cos(lat_ref)
    y_m = EARTH_R * (lat_rad - lat_ref)
    z_m = ch["alt"] - float(np.nanmin(ch["alt"][valid_gps]))

    # Tighten the on_track filter to exclude GPS sentinels
    on_track = valid_gps

    # Identify valid complete laps
    unique_laps = np.unique(lap[on_track & (lap > 0)])
    print(f"Valid laps: {len(unique_laps)}")

    # Compute per-lap time and length
    lap_info = {}
    for lnum in unique_laps:
        mask = (lap == lnum) & on_track
        if mask.sum() < 500:
            continue
        # Need full lap (0→100% lap_dist_pct)
        pct = ch["lap_dist_pct"][mask]
        if pct.max() - pct.min() < 0.95:
            continue
        lt = float(time_arr[mask][-1] - time_arr[mask][0])
        lap_info[int(lnum)] = lt

    if not lap_info:
        print("No complete laps found!")
        return

    print(f"Complete laps: {len(lap_info)}")
    sorted_laps = sorted(lap_info.items(), key=lambda x: x[1])
    best_lap_num, best_time = sorted_laps[0]
    print(f"Best lap: #{best_lap_num} at {best_time:.2f}s")

    # Build track surface from 5 fastest laps
    top5 = sorted_laps[:5]
    print(f"Top 5 laps: {[(k, f'{v:.1f}s') for k, v in top5]}")
    laps_dict = {}
    for lnum, _ in top5:
        mask = (lap == lnum) & on_track
        df = pd.DataFrame(
            {
                "pos_x_m": x_m[mask],
                "pos_y_m": y_m[mask],
                "pos_z_m": z_m[mask],
                "speed_mps": ch["speed"][mask],
                "accel_lat_mps2": ch["lat_accel"][mask],
                "accel_long_mps2": ch["long_accel"][mask],
                "throttle_pct": ch["throttle"][mask] * 100,
                "brake_pct": ch["brake"][mask] * 100,
                "rpm": ch["rpm"][mask],
                "gear": ch["gear"][mask],
                "distance_m": ch["lap_dist"][mask],
                "time_s": time_arr[mask] - time_arr[mask][0],
            }
        )
        laps_dict[int(lnum)] = df

    # Use f1_game format tag so the normalizer passes through our
    # pre-projected pos_x_m/pos_y_m/pos_z_m as (x, y, z) directly
    surface = build_track_surface(laps_dict, "daytona_road", "f1_game")
    print(
        f"Surface: tier={surface.quality_tier}, "
        f"length={surface.frenet.total_length_m:.0f}m, "
        f"n_points={surface.frenet.n_points}"
    )
    print(f"  has_boundaries={surface.has_boundaries}")
    print(f"  has_elevation={surface.has_elevation}")
    print(f"  has_vert_curvature={surface.has_vert_curvature}")

    best_df = laps_dict[best_lap_num]
    second_lap_num = top5[1][0] if len(top5) >= 2 else best_lap_num
    second_df = laps_dict[second_lap_num]

    best_mu = compute_grip_mu(best_df)
    second_mu = compute_grip_mu(second_df)

    export = {
        "track": {
            "name": "Daytona Road Course — McLaren 570S GT4",
            "length_m": round(surface.frenet.total_length_m, 1),
            "n_points": surface.frenet.n_points,
            "quality": surface.quality_tier,
            "centerline_x": [round(float(v), 2) for v in surface.frenet.centerline_xy[:, 0]],
            "centerline_y": [round(float(v), 2) for v in surface.frenet.centerline_xy[:, 1]],
            "curvature": [round(float(v), 5) for v in surface.frenet.curvature_1pm],
            "heading": [round(float(v), 4) for v in surface.frenet.heading_rad],
        },
        "elevation": {
            "values": [round(float(v), 2) for v in surface.elevation_m]
            if surface.has_elevation
            else [],
            "vert_curvature": [round(float(v), 6) for v in surface.vert_curvature_1pm]
            if surface.has_vert_curvature
            else [],
        },
        "boundaries": {
            "width_left": [round(float(v), 2) for v in surface.width_left]
            if surface.has_boundaries
            else [],
            "width_right": [round(float(v), 2) for v in surface.width_right]
            if surface.has_boundaries
            else [],
        },
        "session_info": {
            "total_laps": len(unique_laps),
            "complete_laps": len(lap_info),
            "best_lap_s": round(best_time, 2),
            "total_duration_s": round(float(time_arr[-1] - time_arr[0]), 0),
        },
        "drivers": {
            # Keep hamilton/verstappen keys for HTML compatibility
            "hamilton": {
                "x": [round(float(v), 2) for v in best_df["pos_x_m"].to_numpy()],
                "y": [round(float(v), 2) for v in best_df["pos_y_m"].to_numpy()],
                "z": [round(float(v), 2) for v in best_df["pos_z_m"].to_numpy()],
                "speed_kph": [
                    round(float(v) * 3.6, 1) for v in best_df["speed_mps"].to_numpy()
                ],
                "throttle": [
                    round(float(v), 1) for v in best_df["throttle_pct"].to_numpy()
                ],
                "grip_mu": [round(float(v), 3) for v in best_mu],
                "driver_name": f"Best Lap #{best_lap_num} ({best_time:.2f}s)",
            },
            "verstappen": {
                "x": [round(float(v), 2) for v in second_df["pos_x_m"].to_numpy()],
                "y": [round(float(v), 2) for v in second_df["pos_y_m"].to_numpy()],
                "z": [round(float(v), 2) for v in second_df["pos_z_m"].to_numpy()],
                "speed_kph": [
                    round(float(v) * 3.6, 1) for v in second_df["speed_mps"].to_numpy()
                ],
                "throttle": [
                    round(float(v), 1) for v in second_df["throttle_pct"].to_numpy()
                ],
                "grip_mu": [round(float(v), 3) for v in second_mu],
                "driver_name": f"2nd Fastest #{second_lap_num} ({top5[1][1] if len(top5) >= 2 else best_time:.2f}s)",
            },
        },
    }

    with open(OUT_PATH, "w") as f:
        json.dump(export, f)
    print(f"\nExported {len(json.dumps(export)) // 1024}KB to {OUT_PATH.name}")


if __name__ == "__main__":
    main()
