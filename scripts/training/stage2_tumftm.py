"""Stage 2 — Extract detector features + ground truth from TUMFTM data.

Processes all 14+ CSVs in data/external/tumftm/ through the full handling
analysis pipeline (run_handling_analysis) and pairs each detected corner
with ground-truth understeer angle from the TUMFTM simulation.

Output: data/external/tumftm_features.parquet  (or .csv fallback).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.adapters.tumftm_adapter import load as tumftm_load  # noqa: E402
from telemetry_tool.handling.runner import run_handling_analysis  # noqa: E402

TUMFTM_DIR = ROOT / "data" / "external" / "tumftm"
OUTPUT_DIR = ROOT / "data" / "external"

# All 17 detectors in registration order
DETECTOR_NAMES = [
    "apex_timing", "corner_balance", "speed_recovery", "lat_g_jerk",
    "trail_braking", "gg_shape", "path_divergence", "yaw_residual",
    "heading_accel", "friction_asymmetry", "speed_scrub", "throttle_response",
    "steering_corrections", "lat_g_plateau", "braking_distance",
    "pipeline_ensemble", "line_variation",
]

GT_US_THRESH = 0.3   # degrees — above = understeer
GT_OS_THRESH = -0.3   # degrees — below = oversteer


def _gt_for_range(understeer_deg: np.ndarray, dist_m: np.ndarray,
                  s_start: float, s_end: float) -> tuple[float, int]:
    """Return (mean_understeer_deg, label) for a distance range."""
    mask = (dist_m >= s_start) & (dist_m <= s_end)
    if not np.any(mask):
        return 0.0, 0
    mean_ua = float(np.nanmean(understeer_deg[mask]))
    if mean_ua > GT_US_THRESH:
        label = 1
    elif mean_ua < GT_OS_THRESH:
        label = -1
    else:
        label = 0
    return mean_ua, label


def _extract_file(filepath: Path) -> list[dict]:
    """Process one TUMFTM file, return list of feature dicts."""
    data = tumftm_load(filepath)
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
        best_lap=1,
        wheelbase_m=2.6,
        vehicle_class="car",
    )

    understeer_deg = data["understeer_angle_deg"]
    dist_m = data["dist_m"]
    records = []

    for corner in result.get("corners", []):
        row: dict = {}
        # Detector votes — fill from events
        vote_accum: dict[str, tuple[float, float]] = {}
        for ev in corner.get("events", []):
            for det_name, v in ev.get("detector_votes", {}).items():
                # Keep the vote with highest confidence per detector
                d, c = v["direction"], v["confidence"]
                if det_name not in vote_accum or c > vote_accum[det_name][1]:
                    vote_accum[det_name] = (d, c)

        for det in DETECTOR_NAMES:
            d_val, c_val = vote_accum.get(det, (0.0, 0.0))
            row[f"{det}_dir"] = d_val
            row[f"{det}_conf"] = c_val

        # Corner metadata
        row["peak_g"] = corner.get("peak_g", 0.0)
        row["corner_len_m"] = corner.get("end_m", 0.0) - corner.get("start_m", 0.0)
        row["n_votes"] = corner.get("n_votes", 0)
        row["n_events"] = corner.get("n_events", 0)

        # Fused direction/confidence from first event (or 0 if none)
        if corner["events"]:
            dirs = [e["direction"] for e in corner["events"]]
            confs = [e["confidence"] for e in corner["events"]]
            row["fused_direction"] = float(np.mean(dirs))
            row["fused_confidence"] = float(np.mean(confs))
        else:
            row["fused_direction"] = 0.0
            row["fused_confidence"] = 0.0

        # Ground truth
        s_start = corner.get("start_m", 0.0)
        s_end = corner.get("end_m", 0.0)
        gt_deg, gt_label = _gt_for_range(understeer_deg, dist_m, s_start, s_end)
        row["gt_understeer_deg"] = gt_deg
        row["gt_label"] = gt_label
        row["source"] = "tumftm"

        records.append(row)

    return records


def main() -> None:
    if not TUMFTM_DIR.exists():
        print(f"ERROR: TUMFTM directory not found: {TUMFTM_DIR}")
        sys.exit(1)

    csv_files = sorted(TUMFTM_DIR.glob("*.csv"))
    if not csv_files:
        print(f"ERROR: no CSV files in {TUMFTM_DIR}")
        sys.exit(1)

    all_records: list[dict] = []
    files_ok = 0
    files_err = 0

    for fp in csv_files:
        print(f"  Processing {fp.name} ...", end=" ", flush=True)
        try:
            recs = _extract_file(fp)
            all_records.extend(recs)
            files_ok += 1
            print(f"{len(recs)} corners")
        except Exception as exc:
            files_err += 1
            print(f"SKIPPED ({exc})")

    if not all_records:
        print("No corners extracted.")
        sys.exit(1)

    df = pd.DataFrame(all_records)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        out_path = OUTPUT_DIR / "tumftm_features.parquet"
        df.to_parquet(out_path, index=False)
    except Exception:
        out_path = OUTPUT_DIR / "tumftm_features.csv"
        df.to_csv(out_path, index=False)
        print("  (pyarrow unavailable — fell back to CSV)")

    gt_counts = df["gt_label"].value_counts().to_dict()
    gt_range = (df["gt_understeer_deg"].min(), df["gt_understeer_deg"].max())

    print(f"\nDone. Saved {len(df):,} corners to {out_path}")
    print(f"  Files processed: {files_ok}, skipped: {files_err}")
    print(f"  Ground truth: US(+1)={gt_counts.get(1, 0)}, "
          f"Neutral(0)={gt_counts.get(0, 0)}, OS(-1)={gt_counts.get(-1, 0)}")
    print(f"  Understeer angle range: [{gt_range[0]:.2f}, {gt_range[1]:.2f}] deg")


if __name__ == "__main__":
    main()
