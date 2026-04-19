"""Stage 3 -- Extract detector features from F1 qualifying laps.

Reads season ZIP archives from c:/Users/Admin/Downloads (2022-2026),
lists qualifying telemetry files, picks the largest per GP+driver
(= hot lap), runs handling analysis, and extracts the shared 34+6
feature schema per corner.

Output: data/external/f1_features.parquet  (or .csv fallback).
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.adapters.f1_adapter import load_from_zip, list_laps_in_zip  # noqa: E402
from telemetry_tool.handling.runner import run_handling_analysis  # noqa: E402

ZIPS_DIR = Path("c:/Users/Admin/Downloads")
OUTPUT_DIR = ROOT / "data" / "external"
DRIVERS = ["VER", "HAM", "NOR", "LEC", "SAI"]
MAX_PER_SEASON = 150
SEASONS = range(2022, 2027)

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
    # Init detector columns to 0
    for det in DETECTOR_NAMES:
        feat[f"{det}_dir"] = 0.0
        feat[f"{det}_conf"] = 0.0

    feat["peak_g"] = corner.get("peak_g", 0.0)
    feat["corner_len_m"] = corner.get("end_m", 0.0) - corner.get("start_m", 0.0)
    feat["n_votes"] = corner.get("n_votes", 0)
    feat["n_events"] = corner.get("n_events", 0)
    feat["fused_direction"] = 0.0
    feat["fused_confidence"] = 0.0

    # Extract detector votes from events
    for event in corner.get("events", []):
        votes = event.get("detector_votes", {})
        for det_name, vote in votes.items():
            if isinstance(vote, dict):
                feat[f"{det_name}_dir"] = vote.get("direction", 0.0)
                feat[f"{det_name}_conf"] = vote.get("confidence", 0.0)
        # Use highest-confidence event for fused values
        conf = event.get("confidence", 0.0)
        if conf > feat["fused_confidence"]:
            feat["fused_direction"] = event.get("direction", 0.0)
            feat["fused_confidence"] = conf

    feat["gt_understeer_deg"] = float("nan")
    feat["gt_label"] = float("nan")
    feat["source"] = source
    return feat


def _find_season_zip(year: int) -> Path | None:
    """Find a ZIP in ZIPS_DIR whose name contains the year."""
    for p in ZIPS_DIR.glob("*.zip"):
        if str(year) in p.name:
            return p
    return None


def _pick_hot_laps(zip_path: Path) -> list[str]:
    """Select qualifying hot-lap tel paths: largest file per GP+driver."""
    all_qual = list_laps_in_zip(zip_path, session="qualifying")
    if not all_qual:
        all_qual = list_laps_in_zip(zip_path, session="quali")

    # Group by (GP, driver)
    groups: dict[tuple[str, str], list[tuple[str, int]]] = defaultdict(list)
    with ZipFile(zip_path, "r") as zf:
        info_map = {i.filename: i.file_size for i in zf.infolist()}

    for tel_path in all_qual:
        parts = tel_path.replace("\\", "/").split("/")
        # Typical structure: GP_Name/Session/DRIVER/lap_N_tel.json
        driver = None
        gp = parts[0] if parts else "unknown"
        for p in parts:
            if p.upper() in DRIVERS:
                driver = p.upper()
                break
        if driver is None:
            for drv in DRIVERS:
                if drv.lower() in tel_path.lower():
                    driver = drv
                    break
        if driver is None:
            continue

        size = info_map.get(tel_path, 0)
        groups[(gp, driver)].append((tel_path, size))

    # Pick largest file per group (= most data = hot lap)
    selected = []
    for (gp, drv), files in groups.items():
        best = max(files, key=lambda x: x[1])
        selected.append(best[0])

    return selected


def main() -> None:
    all_records: list[dict] = []
    total_laps = 0
    total_errors = 0

    for year in SEASONS:
        zip_path = _find_season_zip(year)
        if zip_path is None:
            print(f"  {year}: no ZIP found in {ZIPS_DIR}, skipping")
            continue

        print(f"\n--- {year}: {zip_path.name} ---")
        hot_laps = _pick_hot_laps(zip_path)
        if not hot_laps:
            print(f"  No qualifying laps found for target drivers")
            continue

        # Cap at MAX_PER_SEASON
        if len(hot_laps) > MAX_PER_SEASON:
            hot_laps = hot_laps[:MAX_PER_SEASON]
        print(f"  Selected {len(hot_laps)} laps")

        for tel_path in hot_laps:
            total_laps += 1
            try:
                data = load_from_zip(zip_path, tel_path)
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
                    wheelbase_m=3.6,
                    vehicle_class="car",
                )

                # Parse metadata from path
                parts = tel_path.replace("\\", "/").split("/")
                track = parts[0] if parts else "unknown"
                driver = "unknown"
                for p in parts:
                    if p.upper() in DRIVERS:
                        driver = p.upper()
                        break

                for corner in result.get("corners", []):
                    feat = extract_corner_features(corner, "f1")
                    feat["year"] = year
                    feat["track"] = track
                    feat["driver"] = driver
                    feat["session"] = "qualifying"
                    all_records.append(feat)

            except Exception as exc:
                total_errors += 1
                if total_errors <= 5:
                    print(f"  [SKIP] {tel_path}: {exc}")

            if total_laps % 50 == 0:
                print(f"  ... {total_laps} laps processed, "
                      f"{len(all_records)} corners so far")

    if not all_records:
        print("\nNo corners extracted.")
        sys.exit(1)

    df = pd.DataFrame(all_records)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        out_path = OUTPUT_DIR / "f1_features.parquet"
        df.to_parquet(out_path, index=False)
    except Exception:
        out_path = OUTPUT_DIR / "f1_features.csv"
        df.to_csv(out_path, index=False)
        print("  (pyarrow unavailable -- fell back to CSV)")

    print(f"\nDone. Saved {len(df):,} corners to {out_path}")
    print(f"  Laps processed: {total_laps}, errors: {total_errors}")
    print(f"  Seasons: {list(SEASONS)}")
    print(f"  Drivers: {DRIVERS}")


if __name__ == "__main__":
    main()
