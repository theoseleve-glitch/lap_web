"""Stage 1 — Extract event-centric features from the DTM simulated dataset.

Reads data/external/kaggle_simulated/simulated_dataset.csv (961 MB, 2.6M rows)
in 200K-row chunks.  For each "Loss of Traction" or "Lock-up" event, extracts
a +/-100-row window and computes 22 features directly from the raw columns
(no detector run — too slow for millions of rows).  An equal number of
"Normal" windows are sampled for balance.

Output: data/external/dtm_events.parquet  (or .csv if pyarrow unavailable).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
INPUT_CSV = ROOT / "data" / "external" / "kaggle_simulated" / "simulated_dataset.csv"
OUTPUT_DIR = ROOT / "data" / "external"
CHUNK_SIZE = 200_000
WINDOW_HALF = 100          # +/- 100 rows around event
NORMAL_STRIDE = 500        # sample one Normal window every N rows
WINDOW_LEN = WINDOW_HALF * 2 + 1
PROGRESS_ROWS = 500_000


def _features_from_window(win: pd.DataFrame, center_idx: int, label: int) -> dict | None:
    """Compute 22 features from a window DataFrame centred on *center_idx*."""
    if len(win) < 20:
        return None
    try:
        ci = min(max(center_idx - win.index[0], 0), len(win) - 1)
        lat_g = win["Lateral_G_Force"].to_numpy(dtype=np.float64)
        lon_g = win["Longitudinal_G_Force"].to_numpy(dtype=np.float64)
        speed = win["Speed"].to_numpy(dtype=np.float64)
        steer = win["Steering_Position"].to_numpy(dtype=np.float64)
        brake = win["Brake"].to_numpy(dtype=np.float64)
        throttle = win["Throttle"].to_numpy(dtype=np.float64)

        # Estimate dt from row count — ~20 Hz assumed (200 rows ~ 10s)
        dt = 0.05

        abs_lat = np.abs(lat_g)
        abs_lon = np.abs(lon_g)

        return {
            "peak_lat_g":          float(np.nanmax(abs_lat)),
            "peak_lon_g":          float(np.nanmax(abs_lon)),
            "speed_at_event":      float(speed[ci]),
            "speed_min":           float(np.nanmin(speed)),
            "speed_delta":         float(speed[0] - speed[-1]),
            "steering_at_event":   float(steer[ci]),
            "steering_range":      float(np.nanmax(steer) - np.nanmin(steer)),
            "steering_rate":       float(np.nanmax(np.abs(np.diff(steer)))) if len(steer) > 1 else 0.0,
            "brake_at_event":      float(brake[ci]),
            "throttle_at_event":   float(throttle[ci]),
            "tire_friction":       float(win["Tire_Friction_Coefficient"].iat[ci]),
            "tire_wear":           float(win["cumilative_Tire_Wear"].iat[ci]),
            "tire_tread":          float(win["Tire_Tread_Depth"].iat[ci]),
            "g_total_peak":        float(np.nanmax(np.sqrt(lat_g ** 2 + lon_g ** 2))),
            "lat_g_mean":          float(np.nanmean(abs_lat)),
            "lon_g_mean":          float(np.nanmean(abs_lon)),
            "lat_g_jerk":          float(np.nanmax(np.abs(np.diff(lat_g))) / dt) if len(lat_g) > 1 else 0.0,
            "speed_recovery_rate": float((speed[-1] - np.nanmin(speed)) / (len(speed) * dt + 1e-9)),
            "braking_fraction":    float(np.mean(brake > 0.5)),
            "throttle_fraction":   float(np.mean(throttle > 0.5)),
            "driving_style":       1 if win["Driving_Style"].iat[ci] == "Aggressive" else 0,
            "label":               label,
        }
    except Exception:
        return None


def main() -> None:
    if not INPUT_CSV.exists():
        print(f"ERROR: input not found: {INPUT_CSV}")
        sys.exit(1)

    event_map = {"Loss of Traction": -1, "Lock-up": 1}
    rows_read = 0
    events_found = {"Loss of Traction": 0, "Lock-up": 0, "Normal": 0}
    records: list[dict] = []

    reader = pd.read_csv(INPUT_CSV, chunksize=CHUNK_SIZE, low_memory=False)
    for chunk_i, chunk in enumerate(reader):
        chunk_start = chunk.index[0]
        chunk_end = chunk.index[-1]
        rows_read += len(chunk)

        # --- Event windows ---
        for evt_name, lbl in event_map.items():
            hits = chunk.index[chunk["Event"] == evt_name]
            for idx in hits:
                lo = max(idx - WINDOW_HALF, chunk_start)
                hi = min(idx + WINDOW_HALF, chunk_end)
                win = chunk.loc[lo:hi]
                feat = _features_from_window(win, idx, lbl)
                if feat:
                    records.append(feat)
                    events_found[evt_name] += 1

        # --- Normal sampling (one window every NORMAL_STRIDE rows) ---
        normal_mask = chunk["Event"] == "Normal"
        normal_idx = chunk.index[normal_mask]
        target_normal = events_found["Loss of Traction"] + events_found["Lock-up"] - events_found["Normal"]
        if target_normal > 0 and len(normal_idx) > 0:
            sampled = normal_idx[::NORMAL_STRIDE]
            for idx in sampled:
                if events_found["Normal"] >= events_found["Loss of Traction"] + events_found["Lock-up"]:
                    break
                lo = max(idx - WINDOW_HALF, chunk_start)
                hi = min(idx + WINDOW_HALF, chunk_end)
                win = chunk.loc[lo:hi]
                feat = _features_from_window(win, idx, 0)
                if feat:
                    records.append(feat)
                    events_found["Normal"] += 1

        if rows_read % PROGRESS_ROWS < CHUNK_SIZE:
            print(f"  ... {rows_read:,} rows processed, {len(records):,} features so far")

    if not records:
        print("No events extracted.")
        sys.exit(1)

    df = pd.DataFrame(records)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        out_path = OUTPUT_DIR / "dtm_events.parquet"
        df.to_parquet(out_path, index=False)
    except Exception:
        out_path = OUTPUT_DIR / "dtm_events.csv"
        df.to_csv(out_path, index=False)
        print(f"  (pyarrow unavailable — fell back to CSV)")

    print(f"\nDone. Saved {len(df):,} feature rows to {out_path}")
    print(f"  Loss of Traction (OS, label=-1): {events_found['Loss of Traction']:,}")
    print(f"  Lock-up          (US, label=+1): {events_found['Lock-up']:,}")
    print(f"  Normal           (label= 0):     {events_found['Normal']:,}")
    print(f"  Feature columns: {list(df.columns)}")


if __name__ == "__main__":
    main()
