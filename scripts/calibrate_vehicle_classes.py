"""Generate calibration profiles for vehicle classes (kart / car).

Loads all TUMFTM CSVs, runs handling analysis on each, collects raw
detector vote distributions, and writes calibration_profiles.json
into the handling package directory.

Usage:
    python scripts/calibrate_vehicle_classes.py
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import numpy as np

# Ensure project root importable
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.adapters.tumftm_adapter import load as load_tumftm  # noqa: E402
from telemetry_tool.handling.runner import run_handling_analysis  # noqa: E402

logging.basicConfig(level=logging.WARNING)
log = logging.getLogger(__name__)

TUMFTM_DIR = ROOT / "data" / "external" / "tumftm"
OUTPUT_PATH = ROOT / "telemetry_tool" / "handling" / "calibration_profiles.json"

# ---------------------------------------------------------------------------
# Kart calibration values (from existing hardcoded constants in detectors)
# ---------------------------------------------------------------------------
KART_PROFILE: dict = {
    "apex_timing": {"neutral": -0.036, "std": 0.262, "dead_zone": 0.05, "scale": 0.20},
    "corner_balance": {"neutral": 1.0, "std": 0.85, "dead_zone_lo": 0.8, "dead_zone_hi": 1.2, "scale": 0.8},
    "speed_recovery": {"neutral": 0.091, "std": 0.138, "dead_zone": 0.04, "scale": 0.12},
    "lat_g_jerk": {"neutral": 0.35, "std": 0.20, "dead_zone": 0.10, "scale": 0.30},
    "trail_braking": {"dead_zone": 0.15, "scale": 0.25},
    "gg_shape": {"dead_zone": 0.15, "scale": 1.0},
    "yaw_residual": {"dead_zone": 0.10, "scale": 0.30},
    "heading_accel": {
        "mid_neutral": 1.27, "exit_neutral": 1.05,
        "mid_dead": 0.25, "exit_dead": 0.20, "scale": 0.50,
    },
    # Detectors below: no car-specific data yet, kart defaults used
    "path_divergence": {"scale": 500.0},
    "friction_asymmetry": {"dead_zone_lo": 0.85, "dead_zone_hi": 1.15, "scale": 0.30},
    "speed_scrub": {"dead_zone_lo": 2.0, "dead_zone_hi": 3.0, "scale": 1.5},
    "throttle_response": {"dead_zone_lo": 0.15, "dead_zone_hi": 0.35, "scale": 0.20},
    "steering_corrections": {"dead_zone": 2.0, "scale": 4.0},
    "lat_g_plateau": {"dead_zone_lo": 0.8, "dead_zone_hi": 1.2, "scale": 0.50},
    "braking_distance": {"neutral": 0.25, "dead_zone_lo": 0.15, "dead_zone_hi": 0.35, "scale": 0.15},
    "line_variation": {"spread_cap": 3.0, "max_reduction": 0.80},
}

# Detectors whose car profile can be computed from TUMFTM vote distributions
_COMPUTABLE = {
    "apex_timing", "corner_balance", "speed_recovery", "lat_g_jerk",
    "trail_braking", "gg_shape", "yaw_residual", "heading_accel",
}


def _collect_votes(csv_dir: Path) -> dict[str, list[float]]:
    """Run handling analysis on every TUMFTM CSV and collect raw votes."""
    csv_files = sorted(csv_dir.glob("*.csv"))
    if not csv_files:
        log.error("No CSV files found in %s", csv_dir)
        return {}

    votes: dict[str, list[float]] = {}
    for fp in csv_files:
        print(f"  Processing {fp.name} ...", end=" ", flush=True)
        try:
            d = load_tumftm(fp)
            result = run_handling_analysis(
                d["time_s"], d["dist_m"], d["speed_mps"],
                d["a_lat_g"], d["a_lon_g"], d["bearing_deg"],
                d["lat_deg"], d["lon_deg"], d["lap_col"],
                best_lap=1, wheelbase_m=2.6, vehicle_class="car",
            )
            for corner in result.get("corners", []):
                for ev in corner.get("events", []):
                    for det_name, dv in ev.get("detector_votes", {}).items():
                        votes.setdefault(det_name, []).append(dv["direction"])
            n_corners = len(result.get("corners", []))
            print(f"{n_corners} corners, {len(result.get('events', []))} events")
        except Exception as exc:
            print(f"SKIPPED ({exc})")
            log.warning("Failed on %s: %s", fp.name, exc, exc_info=True)
    return votes


def _compute_car_profile(votes: dict[str, list[float]]) -> dict:
    """Derive car calibration from vote distributions."""
    car: dict = {}
    for det_name, kart_cal in KART_PROFILE.items():
        if det_name not in _COMPUTABLE or det_name not in votes or len(votes[det_name]) < 5:
            # Not enough data -- copy kart defaults
            car[det_name] = dict(kart_cal)
            continue

        vals = np.array(votes[det_name])
        median = float(np.median(vals))
        std = float(np.std(vals))
        q25, q75 = float(np.percentile(vals, 25)), float(np.percentile(vals, 75))
        iqr = q75 - q25
        dead_zone = round(iqr / 2.0, 4)

        if det_name == "apex_timing":
            car[det_name] = {
                "neutral": round(median, 4), "std": round(std, 4),
                "dead_zone": dead_zone, "scale": round(1.5 * std, 4),
            }
        elif det_name == "corner_balance":
            car[det_name] = {
                "neutral": round(median, 4), "std": round(std, 4),
                "dead_zone_lo": round(median - dead_zone, 4),
                "dead_zone_hi": round(median + dead_zone, 4),
                "scale": round(std, 4),
            }
        elif det_name == "speed_recovery":
            car[det_name] = {
                "neutral": round(median, 4), "std": round(std, 4),
                "dead_zone": dead_zone, "scale": round(1.0 * std, 4),
            }
        elif det_name == "lat_g_jerk":
            car[det_name] = {
                "neutral": round(median, 4), "std": round(std, 4),
                "dead_zone": dead_zone, "scale": round(1.5 * std, 4),
            }
        elif det_name in ("trail_braking", "gg_shape", "yaw_residual"):
            car[det_name] = {
                "dead_zone": dead_zone,
                "scale": round(1.5 * std, 4) if std > 0.01 else kart_cal.get("scale", 0.3),
            }
        elif det_name == "heading_accel":
            car[det_name] = {
                "mid_neutral": round(median, 4),
                "exit_neutral": round(median * 0.83, 4),
                "mid_dead": round(dead_zone, 4),
                "exit_dead": round(dead_zone * 0.8, 4),
                "scale": round(1.5 * std, 4) if std > 0.01 else 0.50,
            }
        else:
            car[det_name] = dict(kart_cal)

    return car


def _print_comparison(kart: dict, car: dict) -> None:
    """Print a comparison table for kart vs car calibration."""
    print("\n" + "=" * 72)
    print(f"{'Detector':<24} {'Parameter':<16} {'Kart':>10} {'Car':>10}")
    print("-" * 72)
    all_keys = sorted(set(list(kart.keys()) + list(car.keys())))
    for det in all_keys:
        k = kart.get(det, {})
        c = car.get(det, {})
        params = sorted(set(list(k.keys()) + list(c.keys())))
        for i, p in enumerate(params):
            det_col = det if i == 0 else ""
            kv = k.get(p, "---")
            cv = c.get(p, "---")
            kv_s = f"{kv:.4f}" if isinstance(kv, float) else str(kv)
            cv_s = f"{cv:.4f}" if isinstance(cv, float) else str(cv)
            print(f"{det_col:<24} {p:<16} {kv_s:>10} {cv_s:>10}")
    print("=" * 72)


def main() -> None:
    print(f"Scanning TUMFTM data in {TUMFTM_DIR} ...")
    votes = _collect_votes(TUMFTM_DIR)

    if not votes:
        print("No votes collected. Writing kart-only profile.")
        car_profile: dict = dict(KART_PROFILE)
    else:
        total_votes = sum(len(v) for v in votes.values())
        print(f"\nCollected {total_votes} votes across {len(votes)} detectors.")
        car_profile = _compute_car_profile(votes)

    profiles = {"kart": KART_PROFILE, "car": car_profile}

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(profiles, f, indent=2)
    print(f"\nWrote calibration profiles to {OUTPUT_PATH}")

    _print_comparison(KART_PROFILE, car_profile)


if __name__ == "__main__":
    main()
