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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--track", required=True, help="track_id of the sidecar")
    ap.add_argument("--sidecar-root", required=True)
    ap.add_argument("--vehicle-class", default="kart")
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
    lap_times = [_lap_time_estimate(l) for l in laps]
    order = np.argsort(lap_times)
    n_fast = max(1, int(len(laps) * args.fast_quantile))
    fast_laps = [laps[i] for i in order[:n_fast]]
    best_real = args.best_lap_s if args.best_lap_s else float(min(lap_times))

    report: dict = {"track": args.track, "vehicle_class": args.vehicle_class,
                    "condition": args.condition, "n_laps": len(laps),
                    "n_fast_laps": n_fast, "best_real_lap_s": round(best_real, 3),
                    "n_points": args.n_points, "vehicle_params": "default_gt_warning",
                    "gates": {}}

    # ── Solve dry twice (gate 1 + gate 5) ──────────────────────────────
    dry_a = solve_optimal_line_2d(surface, condition="dry",
                                  n_points=args.n_points, max_time_s=args.max_time_s)
    dry_b = solve_optimal_line_2d(surface, condition="dry",
                                  n_points=args.n_points, max_time_s=args.max_time_s)
    report["gates"]["gate1_determinism"] = bool(
        np.array_equal(dry_a.lateral_offset_m, dry_b.lateral_offset_m)
        and np.array_equal(dry_a.speed_mps, dry_b.speed_mps)
    )
    report["gates"]["gate5_robustness"] = {
        "solved": dry_a.solver_status == "optimal",
        "solver_status": dry_a.solver_status,
        "solve_time_s": round(dry_a.solver_time_s, 2),
    }

    # ── Gate 2: dry plausibility vs fast driven lines ──────────────────
    devs = []
    for lap in fast_laps:
        s_l, n_l = surface.frenet.xy_to_sn(lap["x"].to_numpy(), lap["y"].to_numpy())
        n_line_at_s = np.interp(
            s_l % surface.frenet.total_length_m,
            dry_a.distance_m, dry_a.lateral_offset_m,
        )
        devs.append(np.abs(n_l - n_line_at_s))
    all_dev = np.concatenate(devs)
    report["gates"]["gate2_dry_plausibility"] = {
        "median_dev_m": round(float(np.median(all_dev)), 3),
        "p90_dev_m": round(float(np.percentile(all_dev, 90)), 3),
        "target_median_m": 0.5,
    }

    # ── Gate 3: wet correctness ────────────────────────────────────────
    puddles = (compute_drainage(surface.elevation_surface)
               if surface.elevation_surface is not None else [])
    wet = solve_optimal_line_2d(surface, condition="wet", puddles=puddles,
                                n_points=args.n_points, max_time_s=args.max_time_s)
    wet_field = build_wet_mu_field(surface.grip_2d, puddles)
    wet_gs = GripSurface(
        s_bins=wet_field.s_bins, n_bins=wet_field.n_bins, mu_grid=wet_field.mu_grid,
        count_grid=np.ones(wet_field.mu_grid.shape, dtype=int),
        confidence=np.ones(wet_field.mu_grid.shape),
    )
    mu_wet_under_wetline = wet_gs.mu_at_batch(wet.distance_m, wet.lateral_offset_m)
    mu_wet_under_dryline = wet_gs.mu_at_batch(dry_a.distance_m, dry_a.lateral_offset_m)
    report["gates"]["gate3_wet_correctness"] = {
        "mean_mu_wet_line": round(float(mu_wet_under_wetline.mean()), 4),
        "mean_mu_dry_line_under_wet_field": round(float(mu_wet_under_dryline.mean()), 4),
        "wet_line_better": bool(mu_wet_under_wetline.mean() > mu_wet_under_dryline.mean()),
        "puddle_crossings": int(np.sum(mu_wet_under_wetline <= 0.25)),
        "n_puddles": len(puddles),
        "wet_solver_status": wet.solver_status,
    }

    # ── Gate 4: lap-time sanity ────────────────────────────────────────
    pct_err = abs(dry_a.optimal_lap_time_s - best_real) / best_real * 100.0
    report["gates"]["gate4_laptime_sanity"] = {
        "predicted_s": round(dry_a.optimal_lap_time_s, 2),
        "best_real_s": round(best_real, 2),
        "pct_err": round(pct_err, 2),
        "target_pct": 3.0,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
