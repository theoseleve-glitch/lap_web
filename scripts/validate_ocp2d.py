"""Validation harness for the 2D minimum-time OCP (Race Brief Lane 1).

Computes the spec's 5 gates per track and writes a JSON report:

  gate1_determinism      : two solves are bit-identical
  gate2_dry_plausibility : median |n_line - n_driven| on fast laps  [target <= 0.5 m]
  gate3_wet_correctness  : mean mu_wet under wet line > under dry line, zero puddle crossings
  gate4_laptime_sanity   : |t_pred - t_best_real| / t_best_real      [target <= 3%]
  gate5_robustness       : solved + solve_time_s                      [< 60 s]

Usage (one track):
  python scripts/validate_ocp2d.py --track kct --sidecar-root /path/to/sidecars \\
      --laps "exports/kct/laps/*.parquet" --best-lap-s 52.3 --out reports/ocp2d_kct.json

  With real vehicle params (required for gate-4 validity):
  python scripts/validate_ocp2d.py --track kct --sidecar-root /path/to/sidecars \\
      --laps "exports/kct/laps/*.parquet" --best-lap-s 52.3 \\
      --vehicle-json params/kart.json --out reports/ocp2d_kct.json

The report is consumed by tests/test_lap_oracle/test_ocp2d_gates.py via the
OCP2D_VALIDATION_REPORT env var (Task 8).
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Make telemetry_tool-internal absolute imports (track_surface.*, lap_oracle.*)
# resolvable when run from the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "telemetry_tool"))

from track_surface.store import load_track_model                    # noqa: E402
from track_surface.drainage import compute_drainage                 # noqa: E402
from track_surface.grip_2d import GripSurface                       # noqa: E402
from track_surface.mu_field import build_wet_mu_field               # noqa: E402
from track_surface.solver_bridge import solve_optimal_line_2d       # noqa: E402


def _load_lap(path: str) -> pd.DataFrame | None:
    df = pd.read_parquet(path) if path.endswith(".parquet") else pd.read_csv(path)
    x = next((c for c in ("pos_x_m", "x_m") if c in df.columns), None)
    y = next((c for c in ("pos_y_m", "y_m") if c in df.columns), None)
    spd = next((c for c in ("speed_mps", "Speed (m/s)") if c in df.columns), None)
    if not (x and y and spd):
        print(f"  skip {path}: missing pos/speed columns ({list(df.columns)[:8]}...)")
        return None
    out = pd.DataFrame({
        "x": pd.to_numeric(df[x], errors="coerce"),
        "y": pd.to_numeric(df[y], errors="coerce"),
        "v": pd.to_numeric(df[spd], errors="coerce"),
    }).dropna()
    return out if len(out) > 50 else None


def _lap_time_estimate(lap: pd.DataFrame) -> float:
    """Approximate lap time from positions + speed (sum ds/v)."""
    dx = np.diff(lap["x"].to_numpy())
    dy = np.diff(lap["y"].to_numpy())
    ds = np.sqrt(dx ** 2 + dy ** 2)
    v = np.maximum(lap["v"].to_numpy()[:-1], 1.0)
    return float(np.sum(ds / v))


def _lap_length(lap: pd.DataFrame) -> float:
    """Total Euclidean path length of a lap (metres)."""
    dx = np.diff(lap["x"].to_numpy())
    dy = np.diff(lap["y"].to_numpy())
    return float(np.sum(np.sqrt(dx ** 2 + dy ** 2)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--track", required=True, help="track_id of the sidecar")
    ap.add_argument("--sidecar-root", required=True)
    ap.add_argument("--vehicle-class", default="kart")
    ap.add_argument("--vehicle-json", default=None,
                    help="path to JSON file of VehicleParams fields "
                         "(e.g. {\"mass_kg\": 170, \"wheelbase_m\": 1.05, ...}); "
                         "required for gate-4 validity")
    ap.add_argument("--condition", default="dry", help="grip sidecar partition to load")
    ap.add_argument("--laps", required=True, help="glob of driven-lap parquet/csv files")
    ap.add_argument("--best-lap-s", type=float, default=None,
                    help="best real lap time; estimated from the fastest lap file if omitted")
    ap.add_argument("--fast-quantile", type=float, default=0.25,
                    help="laps in the fastest quantile define the reference driven line")
    ap.add_argument("--n-points", type=int, default=400)
    ap.add_argument("--max-time-s", type=float, default=60.0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    surface = load_track_model(
        args.track, sidecar_root=args.sidecar_root,
        vehicle_class=args.vehicle_class, condition=args.condition,
    )
    if surface is None or surface.grip_2d is None:
        print(f"FAIL: no sidecar / no grip_2d for track {args.track!r}")
        return 2

    laps = [l for l in (_load_lap(p) for p in sorted(glob.glob(args.laps))) if l is not None]
    if not laps:
        print("FAIL: no usable lap files")
        return 2

    # ── Fix 3: lap-length sanity filter (kills out-lap poisoning) ─────────
    L = surface.frenet.total_length_m
    n_before = len(laps)
    laps = [l for l in laps if 0.9 * L <= _lap_length(l) <= 1.1 * L]
    if not laps:
        print(f"FAIL: no laps within ±10% of track length {L:.0f}m ({n_before} loaded)")
        return 2
    if len(laps) < n_before:
        print(f"  filtered {n_before - len(laps)} partial/out-laps by length")

    lap_times = [_lap_time_estimate(l) for l in laps]
    order = np.argsort(lap_times)
    n_fast = max(1, int(len(laps) * args.fast_quantile))
    fast_laps = [laps[i] for i in order[:n_fast]]
    best_real = args.best_lap_s if args.best_lap_s else float(min(lap_times))

    # ── Fix 1: vehicle params from JSON or default ─────────────────────────
    vehicle_params = None
    if args.vehicle_json is not None:
        from telemetry_tool.lap_oracle.config import VehicleParams
        with open(args.vehicle_json) as fh:
            vehicle_params = VehicleParams.from_dict(json.load(fh))
        vp_label = "from_json"
    else:
        vp_label = "default_gt_warning"

    report: dict = {"track": args.track, "vehicle_class": args.vehicle_class,
                    "condition": args.condition, "n_laps": len(laps),
                    "n_laps_length_filtered": n_before - len(laps),
                    "n_fast_laps": n_fast, "best_real_lap_s": round(best_real, 3),
                    "n_points": args.n_points,
                    "vehicle_params": vp_label,
                    "vehicle_json": args.vehicle_json,
                    "gates": {}}

    # ── Fix 6: partial report on mid-run failure ───────────────────────────
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    current_gate = "pre_gate1"
    exc_info = None
    try:
        # ── Solve dry twice (gate 1 + gate 5) ─────────────────────────────
        current_gate = "gate1"
        dry_a = solve_optimal_line_2d(surface, vehicle_params=vehicle_params,
                                      condition="dry",
                                      n_points=args.n_points, max_time_s=args.max_time_s)
        dry_b = solve_optimal_line_2d(surface, vehicle_params=vehicle_params,
                                      condition="dry",
                                      n_points=args.n_points, max_time_s=args.max_time_s)
        gate1_passed = bool(
            np.array_equal(dry_a.lateral_offset_m, dry_b.lateral_offset_m)
            and np.array_equal(dry_a.speed_mps, dry_b.speed_mps)
        )
        report["gates"]["gate1_determinism"] = {"passed": gate1_passed}

        # ── Gate 2: dry plausibility vs fast driven lines ──────────────────
        current_gate = "gate2"
        devs = []
        for lap in fast_laps:
            s_l, n_l = surface.frenet.xy_to_sn(lap["x"].to_numpy(), lap["y"].to_numpy())
            n_line_at_s = np.interp(
                s_l % surface.frenet.total_length_m,
                dry_a.distance_m, dry_a.lateral_offset_m,
            )
            devs.append(np.abs(n_l - n_line_at_s))
        # Fix 4: lap-equalized median (don't let long laps dominate)
        per_lap_medians = [float(np.median(d)) for d in devs]
        all_dev = np.concatenate(devs)
        median_dev_m = round(float(np.median(per_lap_medians)), 3)
        target_median_m = 0.5
        report["gates"]["gate2_dry_plausibility"] = {
            "median_dev_m": median_dev_m,          # lap-equalized
            "pooled_median_dev_m": round(float(np.median(all_dev)), 3),  # informational
            "p90_dev_m": round(float(np.percentile(all_dev, 90)), 3),
            "target_median_m": target_median_m,
            "passed": median_dev_m <= target_median_m,
        }

        # ── Gate 3: wet correctness ────────────────────────────────────────
        current_gate = "gate3"
        puddles = (compute_drainage(surface.elevation_surface)
                   if surface.elevation_surface is not None else [])
        wet = solve_optimal_line_2d(surface, vehicle_params=vehicle_params,
                                    condition="wet", puddles=puddles,
                                    n_points=args.n_points, max_time_s=args.max_time_s)
        wet_field = build_wet_mu_field(surface.grip_2d, puddles)
        wet_gs = GripSurface(
            s_bins=wet_field.s_bins, n_bins=wet_field.n_bins, mu_grid=wet_field.mu_grid,
            count_grid=np.ones(wet_field.mu_grid.shape, dtype=int),
            confidence=np.ones(wet_field.mu_grid.shape),
        )
        mu_wet_under_wetline = wet_gs.mu_at_batch(wet.distance_m, wet.lateral_offset_m)
        mu_wet_under_dryline = wet_gs.mu_at_batch(dry_a.distance_m, dry_a.lateral_offset_m)
        wet_line_better = bool(mu_wet_under_wetline.mean() > mu_wet_under_dryline.mean())

        # Fix 2: spatial puddle-crossing count (not mu-threshold)
        from track_surface.drainage import puddle_footprint_radius
        crossings = 0
        if puddles:
            s_pts = wet.distance_m
            n_pts = wet.lateral_offset_m
            for p in puddles:
                r = puddle_footprint_radius(p, wet_field.s_bins, wet_field.n_bins)
                inside = ((s_pts - p.s_center) ** 2 + (n_pts - p.n_center) ** 2) <= r ** 2
                crossings += int(np.sum(inside))

        gate3_passed = bool(
            wet_line_better
            and crossings == 0
            and wet.solver_status in ("optimal", "acceptable")
        )
        report["gates"]["gate3_wet_correctness"] = {
            "mean_mu_wet_line": round(float(mu_wet_under_wetline.mean()), 4),
            "mean_mu_dry_line_under_wet_field": round(float(mu_wet_under_dryline.mean()), 4),
            "wet_line_better": wet_line_better,
            "puddle_crossings": crossings,
            "min_mu_wet_line": round(float(mu_wet_under_wetline.min()), 4),
            "n_puddles": len(puddles),
            "wet_solver_status": wet.solver_status,
            "passed": gate3_passed,
        }

        # ── Gate 4: lap-time sanity ────────────────────────────────────────
        current_gate = "gate4"
        if vehicle_params is None:
            # No real vehicle params — gate is invalid
            report["gates"]["gate4_laptime_sanity"] = {
                "status": "invalid_without_vehicle_params",
                "predicted_s": round(dry_a.optimal_lap_time_s, 2),
                "best_real_s": round(best_real, 2),
                "passed": None,
            }
        else:
            pct_err = abs(dry_a.optimal_lap_time_s - best_real) / best_real * 100.0
            report["gates"]["gate4_laptime_sanity"] = {
                "status": "valid",
                "predicted_s": round(dry_a.optimal_lap_time_s, 2),
                "best_real_s": round(best_real, 2),
                "pct_err": round(pct_err, 2),
                "target_pct": 3.0,
                "passed": pct_err <= 3.0,
            }

        # ── Gate 5: robustness ─────────────────────────────────────────────
        current_gate = "gate5"
        solved = dry_a.solver_status == "optimal"
        solve_time_s = round(dry_a.solver_time_s, 2)
        report["gates"]["gate5_robustness"] = {
            "solved": solved,
            "solver_status": dry_a.solver_status,
            "solve_time_s": solve_time_s,
            "passed": solved and solve_time_s < 60.0,
        }

    except Exception as exc:
        exc_info = exc
        partial = {**report, "error": str(exc), "failed_at": current_gate}
        out_path.write_text(json.dumps(partial, indent=2))
        print(f"FAIL at {current_gate}: {exc}")
        return 1

    out_path.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
