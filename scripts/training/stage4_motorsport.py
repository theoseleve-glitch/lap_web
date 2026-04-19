"""Stage 4 -- Extract detector features from the Kaggle motorsport dataset.

Loads data/external/kaggle_motorsport/motorsport_data.csv, filters to
lap 3 (the main complete lap), runs handling analysis, and extracts
features per corner with extra label columns from the motorsport data.

Output: data/external/motorsport_features.parquet  (or .csv fallback).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.adapters.motorsport_adapter import load as motorsport_load  # noqa: E402
from telemetry_tool.handling.runner import run_handling_analysis  # noqa: E402

INPUT_CSV = ROOT / "data" / "external" / "kaggle_motorsport" / "motorsport_data.csv"
OUTPUT_DIR = ROOT / "data" / "external"
LAP_NUMBER = 3

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


def _majority_label(arr: np.ndarray) -> str:
    """Return the most common non-nan value from a string array."""
    valid = arr[arr != "unknown"]
    if len(valid) == 0:
        return "unknown"
    vals, counts = np.unique(valid, return_counts=True)
    return str(vals[np.argmax(counts)])


def main() -> None:
    if not INPUT_CSV.exists():
        print(f"ERROR: input not found: {INPUT_CSV}")
        sys.exit(1)

    print(f"Loading {INPUT_CSV.name}, filtering to lap {LAP_NUMBER} ...")
    data = motorsport_load(INPUT_CSV, lap_number=LAP_NUMBER)
    n = len(data["time_s"])
    print(f"  {n} rows loaded")

    print("Running handling analysis ...")
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
        best_lap=LAP_NUMBER,
        wheelbase_m=2.5,
        vehicle_class="car",
    )

    corners = result.get("corners", [])
    if not corners:
        print("No corners detected.")
        sys.exit(1)

    print(f"  {len(corners)} corners detected")

    # Extract label channels from the adapter data
    driving_phase = data.get("driving_phase", np.full(n, "unknown"))
    sector_type = data.get("sector_type", np.full(n, "unknown"))
    trail_braking_int = data.get("trail_braking_intensity", np.zeros(n))
    dist_m = data["dist_m"]

    records: list[dict] = []
    for corner in corners:
        feat = extract_corner_features(corner, "motorsport")
        s_start = corner.get("start_m", 0.0)
        s_end = corner.get("end_m", 0.0)

        # Find rows within this corner's distance range
        mask = (dist_m >= s_start) & (dist_m <= s_end)

        # Extra motorsport-specific columns
        feat["driving_phase"] = _majority_label(driving_phase[mask]) if np.any(mask) else "unknown"
        feat["sector_type"] = _majority_label(sector_type[mask]) if np.any(mask) else "unknown"
        feat["trail_braking_intensity_mean"] = float(np.nanmean(trail_braking_int[mask])) if np.any(mask) else 0.0

        records.append(feat)

    df = pd.DataFrame(records)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        out_path = OUTPUT_DIR / "motorsport_features.parquet"
        df.to_parquet(out_path, index=False)
    except Exception:
        out_path = OUTPUT_DIR / "motorsport_features.csv"
        df.to_csv(out_path, index=False)
        print("  (pyarrow unavailable -- fell back to CSV)")

    print(f"\nDone. Saved {len(df):,} corners to {out_path}")
    print(f"  Driving phases: {np.unique(df['driving_phase']).tolist()}")
    print(f"  Sector types: {np.unique(df['sector_type']).tolist()}")


if __name__ == "__main__":
    main()
