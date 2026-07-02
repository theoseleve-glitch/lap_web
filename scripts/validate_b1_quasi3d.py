"""
scripts/validate_b1_quasi3d.py
-------------------------------
B1 acceptance harness: quasi-3D solve (real elevation-driven geom_field) vs.
the forced-2D baseline (``force_no_geom=True``), using the A/B knob added to
``solver_bridge.solve_optimal_line_2d`` in Task 6.

Three modes:

  --track-id X --sidecar-root PATH [--condition dry]
      Loads the surface via ``store.load_track_model``, solves TWICE through
      the bridge (quasi-3D, then forced-2D), builds the SAME validator inputs
      the bridge itself used for each solve, and prints a table:
        mode | geometry mode | lap time | solve wall time | validator | worst friction residual
      Exits 0 iff both solves validate. If neither solve activates a real
      quasi-3D geometry field (e.g. the track has no elevation_surface -
      always true today, since store.load_track_model never populates that
      field), this is the HONEST FALLBACK case: the acceptance criterion
      becomes "quasi-3D run == forced-2D run" (identical lap time within
      1e-3), printed and folded into the exit code.

  --demo
      Runs the Task-2 banked-stadium synthetic (imported from
      test_quasi3d_solver.py's own fixtures) directly through
      solve_minimum_time_2d: flat geom vs. banked geom. Banked must be
      faster than flat by > 0.05 s and both must validate. This is what
      carries the quasi-3D PHYSICS proof (the real-track run above proves
      only the fallback wiring, since real elevation data isn't available).

  --mu-divergence --track-id X --sidecar-root PATH
      Task-5 follow-up: samples a 200x20 (s, n) grid over the loaded real
      grip field and prints max|mu_linear - mu_bspline| between
      ``_make_mu_interpolant`` (what solution_validator.py's audit uses) and
      ``_make_mu_interpolant_smooth`` (what the solver's NLP uses
      internally) - bounding how much the validator's friction-ellipse check
      can diverge from the solver's own view of grip, purely from the
      interpolant choice. PASS if < 0.01 (half of eps=0.02) else WARN.

Sidecar root resolution matches store.py: pass --sidecar-root explicitly
(always wins over the SIDECAR_ROOT env var; see _track_model_dir).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

# scripts/ is one level below the worktree root; telemetry_tool/ holds the
# actual packages (track_surface, lap_oracle). Both must be on sys.path:
# telemetry_tool/ for bare `track_surface.*` / `lap_oracle.*` imports (matches
# scripts/validate_ocp2d.py's convention), and the worktree root itself so
# `--demo` can import the fully-qualified `telemetry_tool.tests.test_lap_oracle
# .test_quasi3d_solver` - a BARE `tests.test_lap_oracle...` import resolves to
# an unrelated, empty `tests/` package at the worktree root instead (the same
# gotcha test_quasi3d_solver.py itself documents).
_WORKTREE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_WORKTREE_ROOT / "telemetry_tool"))
sys.path.insert(0, str(_WORKTREE_ROOT))

from lap_oracle.config import VehicleParams                              # noqa: E402
from track_surface.geom_field import build_geom_field                    # noqa: E402
from track_surface.mu_field import build_dry_mu_field                    # noqa: E402
from track_surface.solution_validator import validate_solution           # noqa: E402
from track_surface.solver_bridge import (                                # noqa: E402
    solve_optimal_line_2d,
    surface_to_track_model,
)
from track_surface.store import load_track_model                        # noqa: E402

_TABLE_HEADERS = (
    "mode", "geometry mode", "lap time (s)", "solve wall (s)",
    "validator", "worst friction",
)
_TABLE_WIDTHS = (10, 28, 14, 16, 10, 15)

# Honest-fallback acceptance: quasi-3D run vs. forced-2D run must be
# identical to within this absolute tolerance when no real geometry field
# was ever built on either side (both collapse to the exact same NLP).
_FALLBACK_LAP_TIME_TOL_S = 1e-3

# Half of solution_validator's default eps=0.02 friction-ellipse slack -
# the mu-divergence bound this harness records for Task 5's follow-up.
_MU_DIVERGENCE_THRESHOLD = 0.01


def _fmt_row(vals) -> str:
    return " | ".join(str(v).ljust(w) for v, w in zip(vals, _TABLE_WIDTHS))


def _print_table(rows: list[dict]) -> None:
    print(_fmt_row(_TABLE_HEADERS))
    print("-+-".join("-" * w for w in _TABLE_WIDTHS))
    for r in rows:
        print(_fmt_row([
            r["mode"],
            r["geometry_mode"],
            f"{r['lap_time_s']:.3f}",
            f"{r['solve_wall_s']:.2f}",
            "PASSED" if r["validator_passed"] else "FAILED",
            f"{r['worst_friction']:.4f}",
        ]))


def _print_report_detail(label: str, report) -> None:
    for c in report.checks:
        flag = "ok" if c.passed else "FAIL"
        print(f"    [{flag}] {label}.{c.check}: {c.detail}")


def _geometry_mode_label(force_no_geom: bool, geom_field) -> str:
    if force_no_geom:
        return "forced-2D"
    if geom_field is None:
        return "no-elevation fallback"
    m, k = geom_field.kv_grid.shape
    return f"quasi-3D active {m}x{k}"


def _friction_worst(report) -> float:
    return next(c.worst for c in report.checks if c.check == "friction_ellipse")


# ---------------------------------------------------------------------------
# --track-id mode
# ---------------------------------------------------------------------------

def run_track(
    track_id: str,
    sidecar_root: str | None,
    condition: str,
    vehicle_class: str,
    n_points: int,
    max_time_s: float,
) -> int:
    if condition != "dry":
        print(
            f"error: --condition {condition!r} not supported by this harness - "
            "validator-input construction (build_dry_mu_field) is dry-only; "
            "wet needs puddles/build_wet_mu_field wiring this harness doesn't "
            "attempt. Use --condition dry."
        )
        return 2

    surface = load_track_model(
        track_id, sidecar_root=sidecar_root, vehicle_class=vehicle_class,
        condition=condition,
    )
    if surface is None:
        print(f"FAIL: no sidecar found for track {track_id!r} under {sidecar_root!r}")
        return 1
    if surface.grip_2d is None:
        print(
            f"FAIL: track {track_id!r} has no 2D grip field "
            f"(quality_tier={surface.quality_tier!r})"
        )
        return 1

    vehicle_params = VehicleParams()
    track_model = surface_to_track_model(surface)
    mu_field = build_dry_mu_field(surface.grip_2d)
    camber_s = (
        np.abs(np.asarray(surface.camber_rad, dtype=float))
        if surface.camber_rad is not None else None
    )

    print(f"track={track_id} condition={condition} vehicle_class={vehicle_class} "
          f"n_points={n_points} max_time_s={max_time_s}")
    print(f"surface.elevation_surface is None: {surface.elevation_surface is None}")

    rows: list[dict] = []
    solutions: dict[str, object] = {}
    reports: dict[str, object] = {}
    for label, force_no_geom in (("quasi-3D", False), ("forced-2D", True)):
        t0 = time.perf_counter()
        sol = solve_optimal_line_2d(
            surface, vehicle_params=vehicle_params, condition=condition,
            n_points=n_points, max_time_s=max_time_s, force_no_geom=force_no_geom,
        )
        wall_s = time.perf_counter() - t0

        geom_field = None if force_no_geom else build_geom_field(
            getattr(surface, "elevation_surface", None)
        )
        report = validate_solution(
            sol, track_model, mu_field, vehicle_params,
            geom_field=geom_field, camber_s=camber_s,
        )
        mode_label = _geometry_mode_label(force_no_geom, geom_field)

        solutions[label] = sol
        reports[label] = report
        rows.append({
            "mode": label, "geometry_mode": mode_label,
            "lap_time_s": sol.optimal_lap_time_s, "solve_wall_s": wall_s,
            "validator_passed": report.passed, "worst_friction": _friction_worst(report),
        })
        print(f"  [{label}] solver_status={sol.solver_status!r} wall={wall_s:.2f}s "
              f"geometry_mode={mode_label}")
        _print_report_detail(label, report)

    print()
    _print_table(rows)

    both_validate = reports["quasi-3D"].passed and reports["forced-2D"].passed

    quasi_active = "quasi-3D active" in rows[0]["geometry_mode"]
    if quasi_active:
        print("\nquasi-3D geometry field was ACTIVE - physics comparison, no "
              "identical-lap-time expectation (see --demo for the physics proof).")
        fallback_ok = True
    else:
        delta = abs(rows[0]["lap_time_s"] - rows[1]["lap_time_s"])
        fallback_ok = delta < _FALLBACK_LAP_TIME_TOL_S
        print(
            f"\nHONEST FALLBACK CHECK (no elevation_surface -> geom_field=None "
            f"on both paths): quasi-3D lap={rows[0]['lap_time_s']:.6f}s "
            f"forced-2D lap={rows[1]['lap_time_s']:.6f}s delta={delta:.6f}s "
            f"(tol={_FALLBACK_LAP_TIME_TOL_S}) -> "
            f"{'PASS' if fallback_ok else 'FAIL'}"
        )

    passed = both_validate and fallback_ok
    print(f"\nOVERALL: {'PASS' if passed else 'FAIL'} "
          f"(both validate={both_validate}, fallback/physics check={fallback_ok})")
    return 0 if passed else 1


# ---------------------------------------------------------------------------
# --demo mode (Task-2 banked-stadium synthetic)
# ---------------------------------------------------------------------------

def run_demo() -> int:
    from telemetry_tool.tests.test_lap_oracle.test_quasi3d_solver import (
        _geom, _mu, _solve, _track,
    )

    track = _track()
    mu = _mu(track)
    vehicle_params = VehicleParams()

    print(f"demo: banked-stadium synthetic, track total_length_m={track.total_length_m:.1f}")

    rows: list[dict] = []
    solutions: dict[str, object] = {}
    reports: dict[str, object] = {}
    for label, camber_gain in (("flat", 0.0), ("banked", 0.08)):
        geom = _geom(camber_gain)
        t0 = time.perf_counter()
        sol = _solve(track, mu, geom)
        wall_s = time.perf_counter() - t0
        report = validate_solution(sol, track, mu, vehicle_params, geom_field=geom)
        mode_label = _geometry_mode_label(False, geom)

        solutions[label] = sol
        reports[label] = report
        rows.append({
            "mode": label, "geometry_mode": mode_label,
            "lap_time_s": sol.optimal_lap_time_s, "solve_wall_s": wall_s,
            "validator_passed": report.passed, "worst_friction": _friction_worst(report),
        })
        print(f"  [{label}] solver_status={sol.solver_status!r} wall={wall_s:.2f}s")
        _print_report_detail(label, report)

    print()
    _print_table(rows)

    both_validate = reports["flat"].passed and reports["banked"].passed
    flat_t = solutions["flat"].optimal_lap_time_s
    banked_t = solutions["banked"].optimal_lap_time_s
    banked_faster = banked_t < flat_t - 0.05
    print(
        f"\nDEMO ACCEPTANCE: banked faster than flat by > 0.05s -> "
        f"{'PASS' if banked_faster else 'FAIL'} (flat={flat_t:.3f}s, "
        f"banked={banked_t:.3f}s, delta={flat_t - banked_t:.3f}s)"
    )

    passed = both_validate and banked_faster
    print(f"\nOVERALL: {'PASS' if passed else 'FAIL'} "
          f"(both validate={both_validate}, banked_faster={banked_faster})")
    return 0 if passed else 1


# ---------------------------------------------------------------------------
# --mu-divergence mode (Task-5 follow-up)
# ---------------------------------------------------------------------------

def run_mu_divergence(
    track_id: str, sidecar_root: str | None, condition: str, vehicle_class: str,
) -> int:
    import casadi as ca
    from lap_oracle.solver.ocp_2d import _make_mu_interpolant, _make_mu_interpolant_smooth

    if condition != "dry":
        print(f"error: --mu-divergence is dry-only (got condition={condition!r})")
        return 2

    surface = load_track_model(
        track_id, sidecar_root=sidecar_root, vehicle_class=vehicle_class,
        condition=condition,
    )
    if surface is None or surface.grip_2d is None:
        print(f"FAIL: no usable 2D grip field for track {track_id!r} under {sidecar_root!r}")
        return 1

    mu_field = build_dry_mu_field(surface.grip_2d)
    lut_linear = _make_mu_interpolant(mu_field)
    lut_smooth = _make_mu_interpolant_smooth(mu_field)

    s_grid = np.linspace(float(mu_field.s_bins[0]), float(mu_field.s_bins[-1]), 200)
    n_grid = np.linspace(float(mu_field.n_bins[0]), float(mu_field.n_bins[-1]), 20)
    ss, nn = np.meshgrid(s_grid, n_grid, indexing="ij")
    s_flat, n_flat = ss.ravel(), nn.ravel()

    diffs = np.array([
        abs(float(lut_linear(ca.DM([float(s), float(n)])))
            - float(lut_smooth(ca.DM([float(s), float(n)]))))
        for s, n in zip(s_flat, n_flat)
    ])
    worst_i = int(np.argmax(diffs))
    max_diff = float(diffs[worst_i])
    worst_s, worst_n = float(s_flat[worst_i]), float(n_flat[worst_i])

    passed = max_diff < _MU_DIVERGENCE_THRESHOLD
    print(
        f"mu-divergence: max|mu_linear - mu_bspline| over 200x20 (s,n) grid "
        f"= {max_diff:.6f} at s={worst_s:.2f}, n={worst_n:.3f} "
        f"(mean={float(diffs.mean()):.6f})"
    )
    print(
        f"{'PASS' if passed else 'WARN'}: threshold {_MU_DIVERGENCE_THRESHOLD} "
        f"(half of solution_validator's default eps=0.02)"
    )
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--track-id", default=None, help="track_id of the sidecar")
    ap.add_argument(
        "--sidecar-root", default=None,
        help="path to sidecar directory; falls back to SIDECAR_ROOT env var "
             "then the store default (sidecars/) when omitted",
    )
    ap.add_argument("--condition", default="dry", help="grip sidecar partition (dry-only; default: dry)")
    ap.add_argument("--vehicle-class", default="generic", help="vehicle class subdir (default: generic)")
    ap.add_argument("--n-points", type=int, default=400, help="NLP discretisation points (default: 400)")
    ap.add_argument("--max-time-s", type=float, default=120.0,
                    help="IPOPT per-solve wall-clock cap in seconds (default: 120, matches "
                         "solve_optimal_line_2d's own default)")
    ap.add_argument("--demo", action="store_true",
                    help="run the Task-2 banked-stadium synthetic acceptance instead of a real track")
    ap.add_argument("--mu-divergence", action="store_true",
                    help="run the Task-5 follow-up mu-interpolant divergence probe instead of an A/B solve")
    return ap


def main() -> int:
    args = _build_argparser().parse_args()

    if args.demo:
        return run_demo()

    if args.mu_divergence:
        if not args.track_id:
            print("error: --mu-divergence requires --track-id")
            return 2
        return run_mu_divergence(
            args.track_id, args.sidecar_root, args.condition, args.vehicle_class,
        )

    if not args.track_id:
        print("error: --track-id is required (or use --demo)")
        return 2

    return run_track(
        args.track_id, args.sidecar_root, args.condition, args.vehicle_class,
        args.n_points, args.max_time_s,
    )


if __name__ == "__main__":
    raise SystemExit(main())
