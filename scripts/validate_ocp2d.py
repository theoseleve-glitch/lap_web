"""Validation harness for the 2D minimum-time OCP (Race Brief Lane 2).

Runs 5 spec gates (§4) per track and writes a JSON report:

  gate1_determinism      : two solves are bit-identical (hashed arrays)
  gate2_dry_plausibility : median |n_line - n_driven| on fast laps  [target ≤ 0.5 m]
  gate3_wet_correctness  : mean μ_wet under wet line > under dry line; zero puddle crossings
  gate4_laptime_sanity   : |t_pred - t_best_real| / t_best_real      [target ≤ 3 %]
  gate5_robustness       : solver_status == 'optimal' AND solve_time_s < 60 s

Usage (one track):
  python scripts/validate_ocp2d.py --track kct \\
      --laps "exports/kct/laps/*.parquet" --best-lap-s 52.3 \\
      --out reports/ocp2d_kct.json

  With explicit vehicle params (needed for gate-4 validity):
  python scripts/validate_ocp2d.py --track kct \\
      --laps "exports/kct/laps/*.parquet" --best-lap-s 52.3 \\
      --vehicle-json params/kart.json --out reports/ocp2d_kct.json

Sidecar root:
  Reads SIDECAR_ROOT env var (production) or --sidecar-root CLI arg.
  Falls back to the default from track_surface.store._default_sidecar_root()
  (development: <repo_root>/sidecars/).

Exit codes:
  0   all gates passed (or gate4 is an estimate without vehicle JSON)
  1   one or more gates FAILED (report written, partial on exception)
  2   no usable lap files found (when --laps is given)
  3   no gold-tier sidecar data available for the specified track

AUTHORITATIVE RUN: The full 5 gates on real gold-tier data are executed at
Lane 2 deploy time by the controller.  This script is the manual companion
for that deploy step and for CI regression on sidecar-equipped machines.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Resolve imports relative to the worktree root (scripts/ is one level below it).
_WORKTREE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_WORKTREE_ROOT / "telemetry_tool"))

from track_surface.store import load_track_model                         # noqa: E402
from track_surface.drainage import compute_drainage, puddle_footprint_radius  # noqa: E402
from track_surface.grip_2d import GripSurface                            # noqa: E402
from track_surface.mu_field import build_wet_mu_field, build_dry_mu_field  # noqa: E402
from track_surface.solver_bridge import solve_optimal_line_2d            # noqa: E402


def _array_hash(arr: np.ndarray) -> str:
    """SHA-256 hex digest of the array's raw bytes (contiguous C order)."""
    return hashlib.sha256(np.ascontiguousarray(arr).tobytes()).hexdigest()


def _load_lap(path: str) -> "pd.DataFrame | None":
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
    """Approximate lap time from positions + speed (sum ds / v)."""
    dx = np.diff(lap["x"].to_numpy())
    dy = np.diff(lap["y"].to_numpy())
    ds = np.sqrt(dx ** 2 + dy ** 2)
    v = np.maximum(lap["v"].to_numpy()[:-1], 1.0)
    return float(np.sum(ds / v))


def _lap_length(lap: pd.DataFrame) -> float:
    dx = np.diff(lap["x"].to_numpy())
    dy = np.diff(lap["y"].to_numpy())
    return float(np.sum(np.sqrt(dx ** 2 + dy ** 2)))


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--track", required=True, help="track_id of the sidecar")
    ap.add_argument(
        "--sidecar-root", default=None,
        help="path to sidecar directory; falls back to SIDECAR_ROOT env var "
             "then the store default (sidecars/)",
    )
    ap.add_argument("--vehicle-class", default="kart",
                    help="vehicle class for the default VehicleParams path (default: kart)")
    ap.add_argument(
        "--vehicle-json", default=None,
        help="OPTIONAL path to JSON of VehicleParams fields "
             "(e.g. {\"mass_kg\": 170, \"wheelbase_m\": 1.05}). "
             "Required for gate4 to be a pass/fail check; without it gate4 "
             "is reported as an estimate only.",
    )
    ap.add_argument("--condition", default="dry", help="grip sidecar partition (default: dry)")
    ap.add_argument(
        "--laps", default=None,
        help="glob of driven-lap parquet/csv files — required for gate2; "
             "gate2 is skipped when omitted",
    )
    ap.add_argument("--best-lap-s", type=float, default=None,
                    help="best real lap time in seconds; estimated from --laps if omitted")
    ap.add_argument("--fast-quantile", type=float, default=0.25,
                    help="top-X fraction of laps used as the reference driven line (default: 0.25)")
    ap.add_argument("--n-points", type=int, default=400,
                    help="NLP discretisation points (default: 400)")
    ap.add_argument("--max-time-s", type=float, default=60.0,
                    help="IPOPT wall-clock time limit per solve in seconds (default: 60)")
    ap.add_argument("--out", required=True, help="output JSON report path")
    args = ap.parse_args()

    # ── Load sidecar ───────────────────────────────────────────────────────────
    surface = load_track_model(
        args.track,
        sidecar_root=args.sidecar_root,
        vehicle_class=args.vehicle_class,
        condition=args.condition,
    )
    if surface is None:
        print(f"no gold-tier data available: sidecar not found for track {args.track!r}")
        return 3
    if surface.grip_2d is None:
        print(
            f"no gold-tier data available: track {args.track!r} has "
            f"quality_tier={surface.quality_tier!r} (need 'gold', i.e. ≥10 laps + 2D grip)"
        )
        return 3

    # ── Vehicle params ─────────────────────────────────────────────────────────
    if args.vehicle_json is not None:
        from lap_oracle.config import VehicleParams
        with open(args.vehicle_json) as fh:
            vehicle_params = VehicleParams(**json.load(fh))
        vp_label = "from_json"
    else:
        from lap_oracle.config import VehicleParams
        vehicle_params = VehicleParams()
        vp_label = f"class_default:{args.vehicle_class}"

    # ── Lap loading (gate 2 only) ──────────────────────────────────────────────
    fast_laps: list[pd.DataFrame] = []
    best_real: float | None = args.best_lap_s
    n_laps_loaded = 0
    n_laps_length_filtered = 0
    if args.laps:
        laps = [l for l in (_load_lap(p) for p in sorted(glob.glob(args.laps)))
                if l is not None]
        n_laps_loaded = len(laps)
        if not laps:
            print("FAIL: no usable lap files found")
            return 2
        L = surface.frenet.total_length_m
        n_before = len(laps)
        laps = [l for l in laps if 0.9 * L <= _lap_length(l) <= 1.1 * L]
        n_laps_length_filtered = n_before - len(laps)
        if not laps:
            print(f"FAIL: no laps within ±10% of track length {L:.0f}m ({n_before} loaded)")
            return 2
        lap_times = [_lap_time_estimate(l) for l in laps]
        order = np.argsort(lap_times)
        n_fast = max(1, int(len(laps) * args.fast_quantile))
        fast_laps = [laps[i] for i in order[:n_fast]]
        if best_real is None:
            best_real = float(min(lap_times))

    report: dict = {
        "track": args.track,
        "vehicle_class": args.vehicle_class,
        "condition": args.condition,
        "n_laps": n_laps_loaded,
        "n_laps_length_filtered": n_laps_length_filtered,
        "quality_tier": surface.quality_tier,
        "n_points": args.n_points,
        "vehicle_params": vp_label,
        "vehicle_json": args.vehicle_json,
        "gates": {},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    current_gate = "pre_gate1"

    try:
        # ── Gate 1: determinism ────────────────────────────────────────────────
        current_gate = "gate1"
        dry_a = solve_optimal_line_2d(
            surface, vehicle_params=vehicle_params, condition="dry",
            n_points=args.n_points, max_time_s=args.max_time_s,
        )
        dry_b = solve_optimal_line_2d(
            surface, vehicle_params=vehicle_params, condition="dry",
            n_points=args.n_points, max_time_s=args.max_time_s,
        )
        hash_a_lat = _array_hash(dry_a.lateral_offset_m)
        hash_b_lat = _array_hash(dry_b.lateral_offset_m)
        gate1_passed = bool(hash_a_lat == hash_b_lat and
                            _array_hash(dry_a.speed_mps) == _array_hash(dry_b.speed_mps))
        report["gates"]["gate1_determinism"] = {
            "passed": gate1_passed,
            "lateral_hash_a": hash_a_lat[:16],
            "lateral_hash_b": hash_b_lat[:16],
            "solver_status": dry_a.solver_status,
        }

        # ── Gate 2: dry plausibility vs driven lines ───────────────────────────
        current_gate = "gate2"
        if fast_laps:
            devs = []
            for lap in fast_laps:
                s_l, n_l = surface.frenet.xy_to_sn(lap["x"].to_numpy(), lap["y"].to_numpy())
                n_line_at_s = np.interp(
                    s_l % surface.frenet.total_length_m,
                    dry_a.distance_m, dry_a.lateral_offset_m,
                )
                devs.append(np.abs(n_l - n_line_at_s))
            per_lap_medians = [float(np.median(d)) for d in devs]
            all_dev = np.concatenate(devs)
            median_dev_m = round(float(np.median(per_lap_medians)), 3)
            target_median_m = 0.5
            report["gates"]["gate2_dry_plausibility"] = {
                "median_dev_m": median_dev_m,
                "pooled_median_dev_m": round(float(np.median(all_dev)), 3),
                "p90_dev_m": round(float(np.percentile(all_dev, 90)), 3),
                "target_median_m": target_median_m,
                "n_fast_laps": len(fast_laps),
                "passed": median_dev_m <= target_median_m,
            }
        else:
            report["gates"]["gate2_dry_plausibility"] = {
                "passed": None,
                "note": "skipped — no --laps provided; deploy-time gate only",
            }

        # ── Gate 3: wet correctness ────────────────────────────────────────────
        current_gate = "gate3"
        puddles = (compute_drainage(surface.elevation_surface)
                   if surface.elevation_surface is not None else [])
        wet = solve_optimal_line_2d(
            surface, vehicle_params=vehicle_params, condition="wet", puddles=puddles,
            n_points=args.n_points, max_time_s=args.max_time_s,
        )
        wet_field = build_wet_mu_field(surface.grip_2d, puddles)
        # Build a GripSurface wrapper around the wet MuField for mu_at_batch interpolation.
        wet_gs = GripSurface(
            s_bins=wet_field.s_bins, n_bins=wet_field.n_bins, mu_grid=wet_field.mu_grid,
            count_grid=np.ones(wet_field.mu_grid.shape, dtype=int),
            confidence=np.ones(wet_field.mu_grid.shape),
        )
        mu_wet_under_wetline = wet_gs.mu_at_batch(wet.distance_m, wet.lateral_offset_m)
        mu_wet_under_dryline = wet_gs.mu_at_batch(dry_a.distance_m, dry_a.lateral_offset_m)
        wet_line_better = bool(mu_wet_under_wetline.mean() > mu_wet_under_dryline.mean())

        # Spatial puddle-crossing count.
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
            and wet.solver_status in ("optimal", "acceptable", "solved", "Solve_Succeeded")
        )
        report["gates"]["gate3_wet_correctness"] = {
            "mean_mu_wet_line": round(float(mu_wet_under_wetline.mean()), 4),
            "mean_mu_dry_line_under_wet_field": round(float(mu_wet_under_dryline.mean()), 4),
            "wet_line_better": wet_line_better,
            "puddle_crossings": crossings,
            "n_puddles": len(puddles),
            "wet_solver_status": wet.solver_status,
            "passed": gate3_passed,
        }

        # ── Gate 4: lap-time sanity ────────────────────────────────────────────
        current_gate = "gate4"
        if vp_label == "from_json" and best_real is not None:
            pct_err = abs(dry_a.optimal_lap_time_s - best_real) / best_real * 100.0
            report["gates"]["gate4_laptime_sanity"] = {
                "status": "valid",
                "longitudinal_source": "from_json",
                "predicted_s": round(dry_a.optimal_lap_time_s, 2),
                "best_real_s": round(best_real, 2),
                "pct_err": round(pct_err, 2),
                "target_pct": 3.0,
                "passed": pct_err <= 3.0,
            }
        else:
            report["gates"]["gate4_laptime_sanity"] = {
                "status": "estimate_class_default",
                "longitudinal_source": vp_label,
                "predicted_s": round(dry_a.optimal_lap_time_s, 2),
                "best_real_s": round(best_real, 2) if best_real is not None else None,
                "note": (
                    "gate4 pass/fail requires --vehicle-json for an honest longitudinal model; "
                    "using class defaults, prediction is illustrative only"
                ),
                "passed": None,
            }

        # ── Gate 5: robustness ─────────────────────────────────────────────────
        current_gate = "gate5"
        solved = dry_a.solver_status in ("optimal", "solved", "Solve_Succeeded")
        solve_time_s = round(dry_a.solver_time_s, 2)
        report["gates"]["gate5_robustness"] = {
            "solved": solved,
            "solver_status": dry_a.solver_status,
            "solve_time_s": solve_time_s,
            "passed": solved and solve_time_s < 60.0,
        }

    except Exception as exc:
        partial = {**report, "error": str(exc), "failed_at": current_gate}
        out_path.write_text(json.dumps(partial, indent=2))
        print(f"FAIL at {current_gate}: {exc}")
        return 1

    out_path.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))

    any_failed = any(
        g.get("passed") is False
        for g in report["gates"].values()
    )
    return 1 if any_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
