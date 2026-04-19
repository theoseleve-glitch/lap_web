"""Phase 3a: Extract detector features from DTM dataset for ML training.

Reads the 2.6M row DTM dataset in chunks, detects corners, runs all 16
detectors on each corner, and saves the feature matrix with labels.

Output: data/external/dtm_features.csv
  32 detector features + 5 metadata + 1 label per corner
"""
import sys, pathlib, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=RuntimeWarning)

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.adapters.dtm_adapter import iter_laps
from telemetry_tool.handling.runner import run_handling_analysis
from telemetry_tool.handling.detectors.base import DetectorRegistry
from telemetry_tool.handling.detectors.apex_timing import ApexTimingDetector
from telemetry_tool.handling.detectors.corner_balance import CornerBalanceDetector
from telemetry_tool.handling.detectors.speed_recovery import SpeedRecoveryDetector
from telemetry_tool.handling.detectors.lat_g_jerk import LatGJerkDetector
from telemetry_tool.handling.detectors.trail_braking import TrailBrakingDetector
from telemetry_tool.handling.detectors.gg_shape import GGShapeDetector
from telemetry_tool.handling.detectors.path_divergence import PathDivergenceDetector
from telemetry_tool.handling.detectors.yaw_residual import YawResidualDetector
from telemetry_tool.handling.detectors.heading_accel import HeadingAccelDetector
from telemetry_tool.handling.detectors.friction_asymmetry import FrictionAsymmetryDetector
from telemetry_tool.handling.detectors.speed_scrub import SpeedScrubDetector
from telemetry_tool.handling.detectors.throttle_response import ThrottleResponseDetector
from telemetry_tool.handling.detectors.steering_corrections import SteeringCorrectionsDetector
from telemetry_tool.handling.detectors.lat_g_plateau import LatGPlateauDetector
from telemetry_tool.handling.detectors.braking_distance import BrakingDistanceDetector
from telemetry_tool.handling.detectors.line_variation import LineVariationDetector
from telemetry_tool.handling.calibration import build_corner_window, calibrate_session
from telemetry_tool.handling.types import SessionContext
from scipy.signal import butter, filtfilt

ALL_DETECTORS = [
    ApexTimingDetector, CornerBalanceDetector, SpeedRecoveryDetector,
    LatGJerkDetector, TrailBrakingDetector, GGShapeDetector,
    PathDivergenceDetector, YawResidualDetector, HeadingAccelDetector,
    FrictionAsymmetryDetector, SpeedScrubDetector, ThrottleResponseDetector,
    SteeringCorrectionsDetector, LatGPlateauDetector, BrakingDistanceDetector,
    LineVariationDetector,
]

DETECTOR_NAMES = [cls().name for cls in ALL_DETECTORS]


def extract_features_from_lap(data: dict) -> list[dict]:
    """Run all detectors on one lap, return per-corner feature dicts."""
    n = len(data["time_s"])
    if n < 200:
        return []

    try:
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
            best_lap=int(data["lap_col"][0]) if len(data["lap_col"]) > 0 else 1,
            wheelbase_m=2.6,
            vehicle_class="car",
            use_dynamic_weights=False,
        )
    except Exception:
        return []

    corners = result.get("corners", [])
    if not corners:
        return []

    # Get event labels from the data
    event_labels = data.get("event_labels", np.full(n, "Normal"))

    rows = []
    for ci, corner in enumerate(corners):
        start_m = corner["start_m"]
        end_m = corner["end_m"]

        # Extract detector votes for this corner
        corner_events = corner.get("events", [])

        # Build feature vector: direction + confidence per detector
        feat = {}
        for dname in DETECTOR_NAMES:
            feat[f"{dname}_dir"] = 0.0
            feat[f"{dname}_conf"] = 0.0

        for ev in corner_events:
            votes = ev.get("detector_votes", {})
            for dname, vote_data in votes.items():
                if isinstance(vote_data, dict):
                    feat[f"{dname}_dir"] = vote_data.get("direction", 0)
                    feat[f"{dname}_conf"] = vote_data.get("confidence", 0)

        # Metadata features
        feat["peak_g"] = corner.get("peak_g", 0)
        feat["corner_len_m"] = end_m - start_m
        feat["n_votes"] = corner.get("n_votes", 0)
        feat["n_events"] = corner.get("n_events", 0)

        # Fused result
        if corner_events:
            best = max(corner_events, key=lambda e: e.get("confidence", 0))
            feat["fused_direction"] = best.get("direction", 0)
            feat["fused_confidence"] = best.get("confidence", 0)
        else:
            feat["fused_direction"] = 0
            feat["fused_confidence"] = 0

        # Label from Event column: find dominant event in this corner
        mask = (data["dist_m"] >= start_m) & (data["dist_m"] <= end_m)
        if mask.sum() > 0:
            corner_events_raw = event_labels[mask]
            if hasattr(corner_events_raw, 'value_counts'):
                dominant = corner_events_raw.value_counts().idxmax()
            else:
                unique, counts = np.unique(corner_events_raw, return_counts=True)
                dominant = unique[np.argmax(counts)]
            feat["label"] = dominant

            # Numeric label: Loss of Traction=-1, Lock-up=+1, Normal=0
            if dominant == "Loss of Traction":
                feat["label_numeric"] = -1
            elif dominant == "Lock-up":
                feat["label_numeric"] = 1
            else:
                feat["label_numeric"] = 0
        else:
            feat["label"] = "unknown"
            feat["label_numeric"] = 0

        rows.append(feat)

    return rows


def main():
    dtm_path = ROOT / "data" / "external" / "kaggle_simulated" / "simulated_dataset.csv"
    if not dtm_path.exists():
        print(f"DTM dataset not found at {dtm_path}")
        return

    print(f"Extracting features from DTM dataset...")
    print(f"File: {dtm_path} ({dtm_path.stat().st_size / 1e6:.0f} MB)")

    all_rows = []
    max_laps = 69  # process all 69 laps (only ~23 are real laps with 200+ samples)

    for i, lap_data in enumerate(iter_laps(str(dtm_path), max_laps=max_laps)):
        lap_num = int(lap_data["lap_col"][0]) if len(lap_data["lap_col"]) > 0 else i
        print(f"  Lap {lap_num}: {len(lap_data['time_s'])} samples...", end=" ", flush=True)

        features = extract_features_from_lap(lap_data)
        all_rows.extend(features)
        print(f"{len(features)} corners")

    if not all_rows:
        print("No features extracted!")
        return

    # Save
    df = pd.DataFrame(all_rows)
    out_path = ROOT / "data" / "external" / "dtm_features.csv"
    df.to_csv(out_path, index=False)

    print(f"\n{'='*60}")
    print(f"FEATURE EXTRACTION SUMMARY")
    print(f"{'='*60}")
    print(f"Laps processed:   {max_laps}")
    print(f"Corners found:    {len(df)}")
    print(f"Features:         {len(df.columns)}")
    print(f"Label distribution:")
    if "label" in df.columns:
        print(df["label"].value_counts().to_string(header=False))
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
