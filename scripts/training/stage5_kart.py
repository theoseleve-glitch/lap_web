"""Stage 5 -- Extract detector features from all kart sessions.

Processes all 29 RaceChrono CSVs in data/raw/, runs handling analysis
on the best lap of each, and extracts features per corner.  Optionally
loads baseline labels from artifacts/kart_corner_baseline.json and
assigns pseudo-labels to corners matching confirmed baselines by GPS
apex proximity.

Output: data/external/kart_features.parquet  (or .csv fallback).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from telemetry_tool.handling.runner import run_handling_analysis  # noqa: E402

RAW_DIR = ROOT / "data" / "raw"
OUTPUT_DIR = ROOT / "data" / "external"
BASELINE_PATH = ROOT / "artifacts" / "kart_corner_baseline.json"
MATCH_RADIUS_M = 20.0

TRACK_MAP = {
    "OK": "Ouest Karting", "KCT": "KCT", "CKS": "CKS",
    "JV": "JV", "MKR": "MKR", "SLK": "SLK", "RKJ": "RKJ",
    "Mitjet": "Mitjet",
}

DETECTOR_NAMES = [
    "apex_timing", "corner_balance", "speed_recovery", "lat_g_jerk",
    "trail_braking", "gg_shape", "path_divergence", "yaw_residual",
    "heading_accel", "friction_asymmetry", "speed_scrub", "throttle_response",
    "steering_corrections", "lat_g_plateau", "braking_distance",
    "pipeline_ensemble", "line_variation",
]


def extract_corner_features(corner: dict, source: str) -> dict:
    """Extract standardized feature dict from a runner corner result."""
    feat = {}
    for det in DETECTOR_NAMES:
        feat[f"{det}_dir"] = 0.0
        feat[f"{det}_conf"] = 0.0

    feat["peak_g"] = corner.get("peak_g", 0.0)
    feat["corner_len_m"] = corner.get("end_m", 0.0) - corner.get("start_m", 0.0)
    feat["n_votes"] = corner.get("n_votes", 0)
    feat["n_events"] = corner.get("n_events", 0)
    feat["fused_direction"] = 0.0
    feat["fused_confidence"] = 0.0

    for event in corner.get("events", []):
        votes = event.get("detector_votes", {})
        for det_name, vote in votes.items():
            if isinstance(vote, dict):
                feat[f"{det_name}_dir"] = vote.get("direction", 0.0)
                feat[f"{det_name}_conf"] = vote.get("confidence", 0.0)
        conf = event.get("confidence", 0.0)
        if conf > feat["fused_confidence"]:
            feat["fused_direction"] = event.get("direction", 0.0)
            feat["fused_confidence"] = conf

    feat["gt_understeer_deg"] = float("nan")
    feat["gt_label"] = float("nan")
    feat["source"] = source
    return feat


def load_racechrono(csv_path: Path) -> dict:
    """Load a RaceChrono CSV, returning dict of numpy arrays."""
    header_row = None
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        for i, line in enumerate(f):
            if line.strip().startswith("Time (s)"):
                header_row = i
                break
    if header_row is None:
        raise ValueError(f"No header row found in {csv_path}")

    df = pd.read_csv(csv_path, skiprows=header_row, low_memory=False)
    df.columns = df.columns.str.strip()

    time_s = pd.to_numeric(df.iloc[:, 0], errors="coerce").values
    speed = pd.to_numeric(
        df.get("Speed (m/s) *calc", df.get("Speed (m/s)")),
        errors="coerce",
    ).values
    a_lat = pd.to_numeric(
        df.get("Lateral acceleration (G) *calc"), errors="coerce"
    ).values
    a_lon = pd.to_numeric(
        df.get("Longitudinal acceleration (G) *calc"), errors="coerce"
    ).values
    bearing = pd.to_numeric(df["Bearing (deg)"], errors="coerce").values
    lat = pd.to_numeric(df["Latitude (deg)"], errors="coerce").values
    lon = pd.to_numeric(df["Longitude (deg)"], errors="coerce").values
    lap_col = pd.to_numeric(df["Lap #"], errors="coerce").values
    dist = pd.to_numeric(df["Distance (m)"], errors="coerce").values

    return {
        "time_s": time_s,
        "dist_m": dist,
        "speed_mps": speed,
        "a_lat_g": a_lat,
        "a_lon_g": a_lon,
        "bearing_deg": bearing,
        "lat_deg": lat,
        "lon_deg": lon,
        "lap_col": lap_col,
    }


def _find_best_lap(data: dict) -> int | None:
    """Return the best (shortest valid) lap number."""
    laps = pd.Series(data["lap_col"]).dropna()
    laps = laps[laps > 0].unique()
    best_lap, best_time = None, np.inf
    for ln in laps:
        m = data["lap_col"] == ln
        t = data["time_s"][m]
        if len(t) < 50:
            continue
        lt = t[-1] - t[0]
        if 10 < lt < best_time:
            best_time, best_lap = lt, int(ln)
    return best_lap


def _parse_track(filename: str) -> str:
    """Parse track abbreviation from filename."""
    stem = Path(filename).stem
    for prefix, name in TRACK_MAP.items():
        if stem.startswith(prefix):
            return name
    return stem


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000.0
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = (np.sin(dlat / 2) ** 2
         + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2))
         * np.sin(dlon / 2) ** 2)
    return R * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


def _corner_apex_gps(corner: dict, data: dict) -> tuple[float, float]:
    """Derive apex lat/lon from a corner summary and session arrays."""
    dist_m = data["dist_m"]
    a_lat_g = data["a_lat_g"]
    s_start = corner.get("start_m", 0.0)
    s_end = corner.get("end_m", 0.0)

    si = int(np.argmin(np.abs(dist_m - s_start)))
    ei = int(np.argmin(np.abs(dist_m - s_end)))
    if ei <= si:
        ei = si + 1

    abs_alat = np.abs(a_lat_g[si:ei])
    if len(abs_alat) == 0:
        return 0.0, 0.0
    apex_idx = si + int(np.argmax(abs_alat))
    return float(data["lat_deg"][apex_idx]), float(data["lon_deg"][apex_idx])


def _load_baseline() -> list[dict] | None:
    """Load confirmed baseline corners, if the file exists."""
    if not BASELINE_PATH.exists():
        return None
    with open(BASELINE_PATH, "r") as f:
        baseline = json.load(f)
    confirmed = [
        c for c in baseline.get("corners", [])
        if c.get("confidence") == "confirmed"
    ]
    return confirmed if confirmed else None


def _match_baseline(apex_lat: float, apex_lon: float,
                    baseline: list[dict]) -> dict | None:
    """Find closest confirmed baseline corner within MATCH_RADIUS_M."""
    best_d, best_c = MATCH_RADIUS_M + 1, None
    for bc in baseline:
        d = _haversine_m(apex_lat, apex_lon,
                         bc.get("apex_lat", 0.0), bc.get("apex_lon", 0.0))
        if d < best_d:
            best_d, best_c = d, bc
    return best_c


def main() -> None:
    csv_files = sorted(RAW_DIR.glob("*.csv"))
    if not csv_files:
        print(f"ERROR: no CSV files in {RAW_DIR}")
        sys.exit(1)

    print(f"Found {len(csv_files)} CSV files in {RAW_DIR}")

    baseline = _load_baseline()
    if baseline:
        print(f"Loaded {len(baseline)} confirmed baseline corners")
    else:
        print("No baseline file found, pseudo-labels disabled")

    all_records: list[dict] = []
    files_ok = 0
    files_err = 0
    pseudo_labeled = 0

    for csv_path in csv_files:
        session_name = csv_path.stem
        track = _parse_track(csv_path.name)
        print(f"  {session_name} ({track}) ...", end=" ", flush=True)

        try:
            data = load_racechrono(csv_path)
            best_lap = _find_best_lap(data)
            if best_lap is None:
                print("no valid laps, skipping")
                files_err += 1
                continue

            result = run_handling_analysis(
                time_s=data["time_s"],
                dist_m=data["dist_m"],
                speed_mps=data["speed_mps"],
                a_lat_g=data["a_lat_g"],
                a_lon_g=data["a_lon_g"],
                bearing_deg=data["bearing_deg"],
                lat_deg=data["lat_deg"],
                lon_deg=data["lon_deg"],
                lap_col=data["lap_col"],
                best_lap=best_lap,
                wheelbase_m=1.0,
                vehicle_class="kart",
            )

            corners = result.get("corners", [])
            if not corners:
                print("0 corners")
                files_ok += 1
                continue

            for corner in corners:
                feat = extract_corner_features(corner, "kart")
                feat["session_name"] = session_name
                feat["track"] = track

                # Attempt baseline pseudo-labeling
                if baseline:
                    apex_lat, apex_lon = _corner_apex_gps(corner, data)
                    match = _match_baseline(apex_lat, apex_lon, baseline)
                    if match is not None:
                        tendency = match.get("tendency", "")
                        if "understeer" in tendency:
                            feat["gt_label"] = 1.0
                            pseudo_labeled += 1
                        elif "oversteer" in tendency:
                            feat["gt_label"] = -1.0
                            pseudo_labeled += 1

                all_records.append(feat)

            files_ok += 1
            print(f"{len(corners)} corners")

        except Exception as exc:
            files_err += 1
            print(f"SKIPPED ({exc})")

    if not all_records:
        print("\nNo corners extracted.")
        sys.exit(1)

    df = pd.DataFrame(all_records)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        out_path = OUTPUT_DIR / "kart_features.parquet"
        df.to_parquet(out_path, index=False)
    except Exception:
        out_path = OUTPUT_DIR / "kart_features.csv"
        df.to_csv(out_path, index=False)
        print("  (pyarrow unavailable -- fell back to CSV)")

    print(f"\nDone. Saved {len(df):,} corners to {out_path}")
    print(f"  Sessions processed: {files_ok}, skipped: {files_err}")
    print(f"  Pseudo-labeled corners: {pseudo_labeled}")
    tracks = df["track"].unique().tolist() if "track" in df.columns else []
    print(f"  Tracks: {tracks}")


if __name__ == "__main__":
    main()
