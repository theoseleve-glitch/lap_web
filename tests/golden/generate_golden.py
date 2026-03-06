"""
generate_golden.py
------------------
Deterministic synthetic telemetry generator for golden regression datasets.

Produces RaceChrono-format CSV files from physics-based track models.
All sessions use fixed numpy seeds for full reproducibility.

Usage:
    python tests/golden/generate_golden.py                  # generate all
    python tests/golden/generate_golden.py --update-snapshots  # re-capture baselines
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve().parent
_SESSIONS_DIR = _HERE / "sessions"
_SNAPSHOTS_DIR = _HERE / "snapshots"
_MANIFEST_PATH = _HERE / "golden_manifest.json"

# ---------------------------------------------------------------------------
# Track geometry builders
# ---------------------------------------------------------------------------


def _oval_track(n_points: int = 1000, lap_length_m: float = 500.0):
    """Two straights + two semicircles."""
    ds = lap_length_m / n_points
    dist = np.arange(n_points) * ds
    kappa = np.zeros(n_points)
    quarter = lap_length_m / 4.0
    for lo, hi in [(quarter, 2 * quarter), (3 * quarter, lap_length_m)]:
        idx = (dist >= lo) & (dist < hi)
        kappa[idx] = 2 * math.pi / lap_length_m  # semicircle curvature
    heading = np.cumsum(kappa * ds)
    x = np.cumsum(np.cos(heading) * ds)
    y = np.cumsum(np.sin(heading) * ds)
    return dist, kappa, heading, x, y, ds


def _figure8_track(n_points: int = 1000, lap_length_m: float = 800.0):
    """Figure-8 with left + right turns."""
    ds = lap_length_m / n_points
    dist = np.arange(n_points) * ds
    kappa = np.zeros(n_points)
    seg = lap_length_m / 4.0
    # Turn 1: left (positive curvature)
    idx1 = (dist >= seg) & (dist < 2 * seg)
    kappa[idx1] = 0.03
    # Turn 2: right (negative curvature)
    idx2 = (dist >= 3 * seg) & (dist < 4 * seg)
    kappa[idx2] = -0.03
    heading = np.cumsum(kappa * ds)
    x = np.cumsum(np.cos(heading) * ds)
    y = np.cumsum(np.sin(heading) * ds)
    return dist, kappa, heading, x, y, ds


def _hairpin_track(n_points: int = 1000, lap_length_m: float = 600.0):
    """Track with one tight hairpin and a long straight."""
    ds = lap_length_m / n_points
    dist = np.arange(n_points) * ds
    kappa = np.zeros(n_points)
    # Hairpin at 40-50% of track
    hairpin_start = int(0.4 * n_points)
    hairpin_end = int(0.5 * n_points)
    kappa[hairpin_start:hairpin_end] = 0.08  # tight
    # Sweeper at 75-85%
    sw_start = int(0.75 * n_points)
    sw_end = int(0.85 * n_points)
    kappa[sw_start:sw_end] = 0.02
    heading = np.cumsum(kappa * ds)
    x = np.cumsum(np.cos(heading) * ds)
    y = np.cumsum(np.sin(heading) * ds)
    return dist, kappa, heading, x, y, ds


_TRACK_BUILDERS = {
    "oval": _oval_track,
    "figure8": _figure8_track,
    "hairpin": _hairpin_track,
}

# ---------------------------------------------------------------------------
# Speed profile from curvature + vehicle limits
# ---------------------------------------------------------------------------


def _compute_speed_profile(
    kappa: np.ndarray,
    ds: float,
    *,
    v_max: float = 20.0,
    ay_max: float = 8.0,
    ax_accel: float = 5.0,
    ax_brake: float = 8.0,
) -> np.ndarray:
    """Forward-backward QSS solver for speed from curvature limits."""
    n = len(kappa)
    # Corner speed limit
    v_corner = np.where(
        np.abs(kappa) > 1e-6,
        np.sqrt(ay_max / np.abs(kappa)),
        v_max,
    )
    v_corner = np.minimum(v_corner, v_max)

    v = v_corner.copy()
    # Forward pass (accel limited)
    for i in range(1, n):
        v_fwd = math.sqrt(max(v[i - 1] ** 2 + 2 * ax_accel * ds, 0.01))
        v[i] = min(v[i], v_fwd)
    # Backward pass (brake limited)
    for i in range(n - 2, -1, -1):
        v_bwd = math.sqrt(max(v[i + 1] ** 2 + 2 * ax_brake * ds, 0.01))
        v[i] = min(v[i], v_bwd)
    return np.maximum(v, 1.0)


# ---------------------------------------------------------------------------
# Session builder
# ---------------------------------------------------------------------------


@dataclass
class GoldenSessionSpec:
    """Specification for a single golden session."""
    session_id: str
    track_shape: str           # oval, figure8, hairpin
    vehicle_type: str          # kart, car
    n_laps: int
    track_state: str           # dry, wet, damp
    gps_quality: str           # clean, noisy, mixed
    seed: int
    lap_length_m: float = 500.0
    n_points_per_lap: int = 1000
    # Vehicle physics
    v_max_mps: float = 20.0
    ay_max_mps2: float = 8.0
    ax_accel_mps2: float = 5.0
    ax_brake_mps2: float = 8.0
    # Expected ranges (for manifest)
    expected_lap_time_range_s: tuple[float, float] = (30.0, 60.0)
    expected_score_range: tuple[int, int] = (40, 100)
    expected_corners_range: tuple[int, int] = (2, 10)


def _add_gps_noise(
    df: pd.DataFrame,
    quality: str,
    rng: np.random.RandomState,
    lap_num: int,
) -> pd.DataFrame:
    """Add GPS noise, satellite drops, accuracy jitter."""
    n = len(df)
    if quality == "clean":
        df["Satellites"] = rng.choice([10, 11, 12, 13, 14], size=n)
        df["Accuracy (m)"] = rng.uniform(0.5, 1.5, n)
    elif quality == "noisy":
        df["Satellites"] = rng.choice([4, 5, 6, 7, 8], size=n)
        df["Accuracy (m)"] = rng.uniform(1.0, 4.0, n)
        # GPS position jitter
        df["Latitude (deg)"] += rng.normal(0, 0.00002, n)
        df["Longitude (deg)"] += rng.normal(0, 0.00002, n)
        # Occasional speed spikes
        spike_mask = rng.random(n) < 0.005
        df.loc[spike_mask, "Speed (m/s)"] *= rng.uniform(1.5, 2.0, spike_mask.sum())
    elif quality == "mixed":
        # First half clean, second half noisy
        mid = n // 2
        df["Satellites"] = np.concatenate([
            rng.choice([10, 11, 12], size=mid),
            rng.choice([4, 5, 6], size=n - mid),
        ])
        df["Accuracy (m)"] = np.concatenate([
            rng.uniform(0.5, 1.5, mid),
            rng.uniform(2.0, 5.0, n - mid),
        ])
        # Dropout in noisy section
        dropout_mask = np.zeros(n, dtype=bool)
        dropout_idx = rng.choice(range(mid, n), size=min(5, n - mid), replace=False)
        dropout_mask[dropout_idx] = True
        df.loc[dropout_mask, "Satellites"] = rng.choice([2, 3], size=dropout_mask.sum())
    return df


def generate_session(spec: GoldenSessionSpec) -> pd.DataFrame:
    """Generate a full RaceChrono-format CSV DataFrame from spec."""
    rng = np.random.RandomState(spec.seed)

    builder = _TRACK_BUILDERS[spec.track_shape]
    dist, kappa, heading, x, y, ds = builder(
        n_points=spec.n_points_per_lap,
        lap_length_m=spec.lap_length_m,
    )

    v_base = _compute_speed_profile(
        kappa, ds,
        v_max=spec.v_max_mps,
        ay_max=spec.ay_max_mps2,
        ax_accel=spec.ax_accel_mps2,
        ax_brake=spec.ax_brake_mps2,
    )

    frames = []
    cum_time = 0.0

    for lap_num in range(1, spec.n_laps + 1):
        # Per-lap variation (driver inconsistency)
        lap_factor = 1.0 + rng.normal(0, 0.01)
        v = v_base * lap_factor + rng.normal(0, 0.15, len(v_base))
        v = np.maximum(v, 1.0)

        # Wet conditions: reduce grip
        if spec.track_state == "wet":
            v *= 0.85
        elif spec.track_state == "damp":
            v *= 0.92

        dt = ds / v
        time_arr = cum_time + np.cumsum(dt)
        cum_time = time_arr[-1] + 0.5  # inter-lap gap

        # Derived channels
        ax = np.gradient(v, time_arr)
        ay = v ** 2 * kappa

        # GPS coordinates (offset from equator to avoid real locations)
        lat = 0.5 + y / 111320.0  # ~1 deg lat = 111.32 km
        lon = 0.5 + x / (111320.0 * math.cos(math.radians(0.5)))

        # Bearing from heading
        bearing = np.degrees(heading) % 360

        df_lap = pd.DataFrame({
            "Lap #": float(lap_num),
            "Time (s)": time_arr,
            "Speed (m/s)": v,
            "Distance (m)": dist + (lap_num - 1) * spec.lap_length_m,
            "Latitude (deg)": lat,
            "Longitude (deg)": lon,
            "Bearing (deg)": bearing,
            "Longitudinal acceleration (G) *calc": ax / 9.80665,
            "Lateral acceleration (G) *calc": ay / 9.80665,
        })

        df_lap = _add_gps_noise(df_lap, spec.gps_quality, rng, lap_num)
        frames.append(df_lap)

    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# Golden session definitions
# ---------------------------------------------------------------------------


GOLDEN_SESSIONS: list[GoldenSessionSpec] = [
    GoldenSessionSpec(
        session_id="kart_clean_gps",
        track_shape="oval",
        vehicle_type="kart",
        n_laps=8,
        track_state="dry",
        gps_quality="clean",
        seed=42,
        lap_length_m=500.0,
        v_max_mps=20.0,
        ay_max_mps2=8.0,
        expected_lap_time_range_s=(24.0, 32.0),
        expected_score_range=(50, 100),
        expected_corners_range=(2, 8),
    ),
    GoldenSessionSpec(
        session_id="car_noisy_gps",
        track_shape="hairpin",
        vehicle_type="car",
        n_laps=5,
        track_state="dry",
        gps_quality="noisy",
        seed=43,
        lap_length_m=600.0,
        v_max_mps=50.0,
        ay_max_mps2=12.0,
        ax_accel_mps2=8.0,
        ax_brake_mps2=12.0,
        expected_lap_time_range_s=(12.0, 22.0),
        expected_score_range=(30, 100),
        expected_corners_range=(2, 6),
    ),
    GoldenSessionSpec(
        session_id="kart_wet_short",
        track_shape="oval",
        vehicle_type="kart",
        n_laps=3,
        track_state="wet",
        gps_quality="clean",
        seed=44,
        lap_length_m=500.0,
        v_max_mps=17.0,
        ay_max_mps2=5.0,
        expected_lap_time_range_s=(28.0, 42.0),
        expected_score_range=(30, 100),
        expected_corners_range=(2, 8),
    ),
    GoldenSessionSpec(
        session_id="car_long_clean",
        track_shape="figure8",
        vehicle_type="car",
        n_laps=12,
        track_state="dry",
        gps_quality="clean",
        seed=45,
        lap_length_m=800.0,
        v_max_mps=45.0,
        ay_max_mps2=10.0,
        ax_accel_mps2=7.0,
        ax_brake_mps2=10.0,
        expected_lap_time_range_s=(25.0, 42.0),
        expected_score_range=(50, 100),
        expected_corners_range=(2, 8),
    ),
    GoldenSessionSpec(
        session_id="kart_mixed_quality",
        track_shape="hairpin",
        vehicle_type="kart",
        n_laps=6,
        track_state="damp",
        gps_quality="mixed",
        seed=46,
        lap_length_m=600.0,
        v_max_mps=18.0,
        ay_max_mps2=6.0,
        expected_lap_time_range_s=(30.0, 52.0),
        expected_score_range=(20, 100),
        expected_corners_range=(2, 6),
    ),
]


# ---------------------------------------------------------------------------
# Manifest + file generation
# ---------------------------------------------------------------------------


def _build_manifest(specs: list[GoldenSessionSpec]) -> list[dict[str, Any]]:
    """Build the golden manifest JSON."""
    entries = []
    for s in specs:
        entries.append({
            "session_id": s.session_id,
            "file": f"sessions/{s.session_id}.csv",
            "track_shape": s.track_shape,
            "vehicle_type": s.vehicle_type,
            "track_state": s.track_state,
            "gps_quality": s.gps_quality,
            "seed": s.seed,
            "expected_laps": s.n_laps,
            "expected_lap_time_range_s": list(s.expected_lap_time_range_s),
            "expected_total_distance_m": [
                s.lap_length_m * s.n_laps * 0.95,
                s.lap_length_m * s.n_laps * 1.05,
            ],
            "expected_derived_channels": [
                "accel_long_mps2", "accel_lat_mps2", "yaw_rate_dps",
                "Distance (m)", "combined_g",
            ],
            "expected_corners_range": list(s.expected_corners_range),
            "expected_score_range": list(s.expected_score_range),
            "expected_vehicle_class": s.vehicle_type,
            "snapshot_file": f"snapshots/{s.session_id}_expected.json",
        })
    return entries


def generate_all(update_snapshots: bool = False) -> None:
    """Generate all golden session CSVs and manifest."""
    _SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    _SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    for spec in GOLDEN_SESSIONS:
        print(f"Generating {spec.session_id}...")
        df = generate_session(spec)
        out_path = _SESSIONS_DIR / f"{spec.session_id}.csv"
        df.to_csv(out_path, index=False)
        size_kb = out_path.stat().st_size / 1024
        print(f"  -> {out_path.name} ({len(df)} rows, {size_kb:.1f} KB)")

    manifest = _build_manifest(GOLDEN_SESSIONS)
    _MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))
    print(f"\nManifest written: {_MANIFEST_PATH}")

    if update_snapshots:
        print("\n--- Capturing baseline snapshots ---")
        _capture_snapshots()


def _capture_snapshots() -> None:
    """Run pipeline on each golden session and save output snapshots."""
    # Add project root to path
    project_root = _HERE.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    telemetry_tool_dir = project_root / "telemetry_tool"
    if str(telemetry_tool_dir) not in sys.path:
        sys.path.insert(0, str(telemetry_tool_dir))

    from telemetry_tool.pipeline import run_full_analysis

    for spec in GOLDEN_SESSIONS:
        csv_path = _SESSIONS_DIR / f"{spec.session_id}.csv"
        if not csv_path.exists():
            print(f"  SKIP {spec.session_id} (CSV not found)")
            continue

        print(f"  Running pipeline on {spec.session_id}...")
        try:
            summary = run_full_analysis(
                str(csv_path),
                session_meta={
                    "session_id": spec.session_id,
                    "session_type": "practice",
                    "track_state": spec.track_state,
                },
                enable_ml=False,
                enable_report=False,
            )
            snapshot = _extract_snapshot(summary, spec)
            snap_path = _SNAPSHOTS_DIR / f"{spec.session_id}_expected.json"
            snap_path.write_text(json.dumps(snapshot, indent=2, default=str))
            print(f"  -> {snap_path.name}")
        except Exception as e:
            print(f"  ERROR on {spec.session_id}: {e}")


def _extract_snapshot(summary: dict, spec: GoldenSessionSpec) -> dict:
    """Extract key fields from pipeline summary for snapshot comparison."""
    lap_dict = summary.get("lap_dict") or {}
    lap_times = summary.get("lap_times") or []
    score = summary.get("score_result")
    corners = summary.get("corners") or []
    vehicle = summary.get("vehicle_params")

    return {
        "_meta": {
            "session_id": spec.session_id,
            "generator_seed": spec.seed,
        },
        "lap_count": len(lap_dict),
        "lap_times_s": [round(t, 3) for t in lap_times] if lap_times else [],
        "best_lap_time_s": round(min(lap_times), 3) if lap_times else None,
        "mean_lap_time_s": round(sum(lap_times) / len(lap_times), 3) if lap_times else None,
        "n_corners": len(corners),
        "steps_ok": summary.get("steps_ok", []),
        "steps_failed": summary.get("steps_failed", []),
        "total_score": score.get("total_score") if isinstance(score, dict) else None,
        "grade": score.get("grade") if isinstance(score, dict) else None,
        "vehicle_class": (
            vehicle.vehicle_class.value
            if vehicle and hasattr(vehicle, "vehicle_class")
            else None
        ),
        "has_enriched_df": summary.get("enriched_df") is not None,
        "has_resampled_laps": bool(summary.get("resampled_laps")),
        "has_delta_segments": bool(summary.get("delta_segments")),
        "has_reference_line": summary.get("reference_line") is not None,
        "tolerances": {
            "lap_count": {"mode": "exact"},
            "best_lap_time_s": {"mode": "range", "abs": 0.5},
            "mean_lap_time_s": {"mode": "range", "abs": 1.0},
            "n_corners": {"mode": "range", "abs": 2},
            "total_score": {"mode": "range", "abs": 5},
            "grade": {"mode": "exact"},
            "vehicle_class": {"mode": "exact"},
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate golden test datasets")
    parser.add_argument(
        "--update-snapshots",
        action="store_true",
        help="Also run pipeline and capture baseline snapshots",
    )
    args = parser.parse_args()
    generate_all(update_snapshots=args.update_snapshots)
