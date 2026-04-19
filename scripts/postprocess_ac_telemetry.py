#!/usr/bin/env python
"""Post-process AC telemetry: replace noisy AI inputs with solver-optimized curves.

Takes raw AC telemetry CSV (positions, speed, g-forces from real physics),
reconstructs smooth optimized throttle/brake/steering using the QSS solver,
then adds controlled human-like variation.

Output columns:
  - All original physics columns (pos, vel, g-forces, tyres, etc.)
  - opt_throttle, opt_brake, opt_steer  — smooth solver reference (coaching target)
  - human_throttle, human_brake, human_steer — solver + realistic human noise
  - driver_skill — synthetic skill level (0.7-1.0) for this "driver"

Usage
-----
    python scripts/postprocess_ac_telemetry.py                    # all CSVs
    python scripts/postprocess_ac_telemetry.py --file <path.csv>  # single file
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from telemetry_tool.lap_oracle.config import ORACLE_DATA

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [postprocess] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("postprocess")

TEL_DIR = ORACLE_DATA / "telemetry" / "ac"
OUT_DIR = ORACLE_DATA / "telemetry" / "processed"


# ---------------------------------------------------------------------------
# Optimal input reconstruction from physics
# ---------------------------------------------------------------------------

def reconstruct_optimal_inputs(df: pd.DataFrame) -> pd.DataFrame:
    """Reconstruct smooth optimized inputs from physics data.

    Uses the actual driven trajectory (speed, position, g-forces) to compute
    what the ideal inputs SHOULD have been — smooth trail-braking, progressive
    throttle, clean steering.

    This is the inverse of what our QSS solver does: given the actual speed
    profile, compute the inputs that would produce it.
    """
    n = len(df)
    dt = np.diff(df["timestamp"].values, prepend=df["timestamp"].values[0])
    dt[0] = dt[1] if len(dt) > 1 else 0.016

    speed = df["speed_ms"].values.copy()
    g_lon = df["g_lon"].values.copy()  # forward/backward g
    g_lat = df["g_lat"].values.copy()  # lateral g

    # --- Optimal throttle/brake from longitudinal acceleration ---
    # g_lon > 0 = accelerating (throttle), g_lon < 0 = decelerating (brake)
    # Normalize to 0-1 range based on typical car limits
    max_accel_g = 0.6   # typical car max accel ~0.5-0.7g
    max_brake_g = 1.2    # typical car max brake ~1.0-1.4g

    raw_throttle = np.clip(g_lon / max_accel_g, 0, 1)
    raw_brake = np.clip(-g_lon / max_brake_g, 0, 1)

    # --- Smooth the inputs (remove ALL high-frequency jitter) ---
    # At 60Hz, use 2-second window (120 frames) for coaching-quality smoothness
    window = min(121, max(31, n // 50))
    if window % 2 == 0:
        window += 1

    opt_throttle = _smooth(raw_throttle, window)
    opt_brake = _smooth(raw_brake, window)

    # Ensure mutual exclusivity with trail-brake overlap zone
    # Trail braking: allow brief overlap where both are nonzero (realistic)
    for i in range(n):
        if opt_throttle[i] > 0.1 and opt_brake[i] > 0.1:
            # In overlap zone: blend based on which is dominant
            total = opt_throttle[i] + opt_brake[i]
            if opt_brake[i] > opt_throttle[i]:
                # Braking dominant: trail-brake (some throttle OK)
                opt_throttle[i] *= 0.3
            else:
                # Throttle dominant: small brake drag OK
                opt_brake[i] *= 0.3

    # --- Optimal steering from lateral acceleration + speed ---
    # steer ≈ atan(lateral_accel * wheelbase / speed²)
    # Simplified: normalize lateral g to steering angle
    wheelbase = 2.5  # typical
    speed_safe = np.maximum(speed, 3.0)  # avoid div by zero
    raw_steer_rad = np.arctan2(g_lat * 9.81 * wheelbase, speed_safe ** 2)

    # Convert to normalized steering (-1 to 1)
    max_steer_rad = 0.5  # ~28 degrees
    raw_steer = np.clip(raw_steer_rad / max_steer_rad, -1, 1)
    opt_steer = _smooth(raw_steer, window)

    # --- Clamp final values ---
    opt_throttle = np.clip(opt_throttle, 0, 1)
    opt_brake = np.clip(opt_brake, 0, 1)
    opt_steer = np.clip(opt_steer, -1, 1)

    df["opt_throttle"] = opt_throttle
    df["opt_brake"] = opt_brake
    df["opt_steer"] = opt_steer

    return df


def _smooth(arr: np.ndarray, window: int) -> np.ndarray:
    """Double-pass smoothing for coaching-quality traces.

    Pass 1: forward causal moving average (removes jitter)
    Pass 2: backward pass (removes phase lag from pass 1)
    Result: zero-phase, very smooth output.
    """
    if len(arr) < window:
        return arr.copy()
    kernel = np.ones(window) / window
    # Forward pass
    padded = np.concatenate([np.full(window - 1, arr[0]), arr])
    fwd = np.convolve(padded, kernel, mode="valid")[:len(arr)]
    # Backward pass (reverse, smooth, reverse — removes lag)
    padded2 = np.concatenate([fwd[::-1], np.full(window - 1, fwd[-1])])
    bwd = np.convolve(padded2, kernel, mode="valid")[:len(arr)]
    return bwd[::-1]


# ---------------------------------------------------------------------------
# Human-like noise injection
# ---------------------------------------------------------------------------

def add_human_variation(
    df: pd.DataFrame,
    skill: float = 0.85,
    seed: int | None = None,
) -> pd.DataFrame:
    """Add realistic human-like variation to optimal inputs.

    Models common human driving behaviors:
    - Late braking (reaction delay)
    - Imprecise throttle application
    - Steering corrections (small oscillations)
    - Trail-brake inconsistency
    - Corner entry overshoot

    Parameters
    ----------
    skill : float
        Driver skill level 0.0 (novice) to 1.0 (pro). Controls noise magnitude.
    """
    rng = np.random.RandomState(seed)
    n = len(df)

    opt_thr = df["opt_throttle"].values.copy()
    opt_brk = df["opt_brake"].values.copy()
    opt_str = df["opt_steer"].values.copy()

    # Noise magnitudes scale inversely with skill
    noise_scale = 1.0 - skill  # 0.0 for perfect, 0.3 for 70% skill

    # All human noise is LOW frequency — humans can't oscillate at 60Hz.
    # Model noise as slow-varying offsets (0.5-2 Hz), not per-sample jitter.
    t = np.arange(n) / 60.0  # time in seconds

    def _slow_noise(amplitude: float, freq_range: tuple = (0.3, 1.5)) -> np.ndarray:
        """Generate smooth, low-frequency noise (human muscle bandwidth)."""
        # Sum of 3 slow sinusoids at random phases
        result = np.zeros(n)
        for _ in range(3):
            f = rng.uniform(*freq_range)
            phase = rng.uniform(0, 2 * np.pi)
            result += np.sin(2 * np.pi * f * t + phase)
        return result * amplitude / 3.0

    # --- Throttle: reaction delay + slow magnitude variation ---
    delay_frames = int(rng.uniform(2, 4 + noise_scale * 10))
    human_thr = np.roll(opt_thr, delay_frames)
    human_thr[:delay_frames] = opt_thr[:delay_frames]
    # Slow amplitude variation (±3-10% depending on skill)
    human_thr = human_thr * (1.0 + _slow_noise(0.03 + noise_scale * 0.07))
    human_thr = _smooth(np.clip(human_thr, 0, 1), 15)

    # --- Brake: late braking + pressure modulation ---
    brake_delay = int(rng.uniform(1, 3 + noise_scale * 8))
    human_brk = np.roll(opt_brk, brake_delay)
    human_brk[:brake_delay] = opt_brk[:brake_delay]
    # Slow pressure variation
    human_brk = human_brk * (1.0 + _slow_noise(0.04 + noise_scale * 0.08))
    human_brk = _smooth(np.clip(human_brk, 0, 1), 15)

    # --- Steering: slow corrections + reaction delay ---
    steer_delay = int(rng.uniform(1, 3 + noise_scale * 5))
    human_str = np.roll(opt_str, steer_delay)
    human_str[:steer_delay] = opt_str[:steer_delay]
    # Low-frequency steering corrections (0.3-1Hz — human correction bandwidth)
    human_str = human_str + _slow_noise(0.02 + noise_scale * 0.04, (0.3, 1.0))
    human_str = _smooth(np.clip(human_str, -1, 1), 15)

    df["human_throttle"] = np.clip(human_thr, 0, 1)
    df["human_brake"] = np.clip(human_brk, 0, 1)
    df["human_steer"] = np.clip(human_str, -1, 1)
    df["driver_skill"] = skill

    return df


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def process_file(csv_path: Path, out_dir: Path) -> Path | None:
    """Process one AC telemetry CSV.

    Pipeline per car:
      1. reconstruct_optimal_inputs() → opt_throttle, opt_brake, opt_steer (eventless)
      2. generate_human_laps() → human_* + event labels (event_type, event_id, etc.)

    Returns path to processed file, or None on error.
    """
    log.info("Processing %s (%.1f MB)", csv_path.name, csv_path.stat().st_size / 1e6)

    try:
        df = pd.read_csv(csv_path)
    except Exception as exc:
        log.error("Failed to read %s: %s", csv_path.name, exc)
        return None

    if len(df) < 100:
        log.warning("Skipping %s — only %d rows", csv_path.name, len(df))
        return None

    required = {"speed_ms", "g_lat", "g_lon", "timestamp"}
    if not required.issubset(df.columns):
        log.warning("Skipping %s — missing columns: %s", csv_path.name, required - set(df.columns))
        return None

    # Process each car separately (different car_index)
    if "car_index" in df.columns:
        cars = df["car_index"].unique()
    else:
        cars = [0]
        df["car_index"] = 0

    results = []
    rng = np.random.RandomState(42)

    for car_idx in cars:
        car_df = df[df["car_index"] == car_idx].copy().reset_index(drop=True)
        if len(car_df) < 50:
            continue

        # Stage 1: Reconstruct EVENTLESS optimal inputs from physics
        car_df = reconstruct_optimal_inputs(car_df)

        # Stage 2: Data-driven human model (learned from TUMFTM + kaggle)
        try:
            from scripts.human_driving_model import HumanDrivingModel

            model_path = ORACLE_DATA / "human_model.npz"
            if model_path.exists():
                model = HumanDrivingModel.load(model_path)
            else:
                log.info("  Training human model from real data (first run)...")
                model = HumanDrivingModel.from_real_data()
                model.save(model_path)

            skill = round(rng.uniform(0.65, 0.95), 2)
            human_result = model.humanize(
                opt_thr=car_df["opt_throttle"].values,
                opt_brk=car_df["opt_brake"].values,
                opt_steer=car_df["opt_steer"].values,
                speed_ms=car_df["speed_ms"].values,
                skill=skill,
                seed=rng.randint(0, 100000),
            )
            for col, vals in human_result.items():
                car_df[col] = vals

        except Exception as exc:
            log.warning("  car %d: human model failed (%s), using legacy", car_idx, exc)
            skill = round(rng.uniform(0.65, 0.98), 2)
            car_df = add_human_variation(car_df, skill=skill, seed=rng.randint(0, 100000))

        # Stage 3: Event labels (corner detection + lap structure)
        try:
            from scripts.driving_events import generate_human_laps

            lap_col = car_df["lap"].values if "lap" in car_df.columns else np.zeros(len(car_df))
            event_result = generate_human_laps(
                opt_thr=car_df["opt_throttle"].values,
                opt_brk=car_df["opt_brake"].values,
                opt_str=car_df["opt_steer"].values,
                speed_ms=car_df["speed_ms"].values,
                g_lat=car_df["g_lat"].values,
                lap_ids=lap_col,
                seed=rng.randint(0, 100000),
            )
            # Only take the label columns, not the human_* (already set by data-driven model)
            for col in ["event_type", "event_id", "event_severity", "event_phase", "lap_type", "corner_id"]:
                if col in event_result:
                    car_df[col] = event_result[col]

            n_events = (car_df["event_id"] > 0).sum() if "event_id" in car_df.columns else 0
            n_corners = car_df["corner_id"].max() if "corner_id" in car_df.columns else 0
            log.info("  car %d: skill=%.2f, %d events, %d corners",
                     car_idx, skill, n_events, n_corners)

        except Exception as exc:
            log.warning("  car %d: event labels failed (%s)", car_idx, exc)

        results.append(car_df)

    if not results:
        log.warning("No valid car data in %s", csv_path.name)
        return None

    out_df = pd.concat(results, ignore_index=True)

    # Save
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / csv_path.name
    out_df.to_csv(out_path, index=False)

    n_cars = len(out_df["car_index"].unique()) if "car_index" in out_df.columns else 1
    event_cols = [c for c in out_df.columns if c.startswith("event_") or c in ("lap_type", "corner_id")]
    log.info(
        "Saved %s — %d rows, %d cars, opt_* (eventless) + human_* (events) + %d label cols",
        out_path.name, len(out_df), n_cars, len(event_cols),
    )
    return out_path


def process_new_files(
    tel_dir: Path | None = None,
    out_dir: Path | None = None,
) -> int:
    """Process only CSV files that haven't been post-processed yet.

    Skips files where the output already exists in out_dir.
    Returns the number of newly processed files.
    """
    tel_dir = tel_dir or TEL_DIR
    out_dir = out_dir or OUT_DIR

    if not tel_dir.exists():
        return 0

    raw_files = sorted(tel_dir.glob("*.csv"))
    new_files = [f for f in raw_files if not (out_dir / f.name).exists()]

    if not new_files:
        log.info("All %d CSVs already have smooth inputs", len(raw_files))
        return 0

    log.info("Processing %d new files (skipping %d already done) → %s",
             len(new_files), len(raw_files) - len(new_files), out_dir)

    processed = 0
    for f in new_files:
        result = process_file(f, out_dir)
        if result:
            processed += 1

    log.info("Done — %d/%d new files processed", processed, len(new_files))
    return processed


def main() -> None:
    parser = argparse.ArgumentParser(description="Post-process AC telemetry")
    parser.add_argument("--file", type=str, help="Process single CSV file")
    parser.add_argument("--out-dir", type=str, default=str(OUT_DIR))
    parser.add_argument("--incremental", action="store_true",
                        help="Only process files not already in out-dir")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)

    if args.incremental:
        process_new_files(TEL_DIR, out_dir)
        return

    if args.file:
        files = [Path(args.file)]
    else:
        files = sorted(TEL_DIR.glob("*.csv"))

    log.info("Processing %d files → %s", len(files), out_dir)

    processed = 0
    for f in files:
        result = process_file(f, out_dir)
        if result:
            processed += 1

    log.info("Done — %d/%d files processed", processed, len(files))


if __name__ == "__main__":
    main()
