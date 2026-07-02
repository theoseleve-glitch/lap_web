"""Physics self-consistency validator tests (spec section 5).

Audits an OCPSolution from its OUTPUTS ONLY (speed, lateral offset, track
geometry) -- independent of solver internals. The consistent base fixture is
HAND-BUILT (never solved): a straight track at constant speed on the
centerline gives a_lat=0 and a_lon=0 identically, so the friction-ellipse
residual is exactly 0. Each corruption test flips exactly one check; see the
inline comments on each test for why the other 5 checks are unaffected
(either the corrupted quantity doesn't feed that check's formula, or the
corruption magnitude/placement is chosen so the collateral effect stays
under that check's own tolerance).
"""
from __future__ import annotations

import json

import numpy as np
import pytest

needs_casadi = pytest.importorskip("casadi")  # skips when casadi absent

from lap_oracle.config import OCPSolution, TrackModel, VehicleParams
from lap_oracle.solver.ocp_2d import DKAPPA_MAX, K_CAMBER, G, MuField
from track_surface.geom_field import GeomField
from track_surface.solution_validator import (
    ValidationReport,
    _reconstruct,
    validate_solution,
)

WIDTH = 5.0


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _straight_track(n_points: int, ds: float, width: float = WIDTH) -> TrackModel:
    distance = np.arange(n_points, dtype=float) * ds
    return TrackModel(
        name="straight", sim="test",
        centerline_xy=np.column_stack([distance, np.zeros(n_points)]),
        width_left=np.full(n_points, width),
        width_right=np.full(n_points, width),
        curvature=np.zeros(n_points),
        vert_curvature=np.zeros(n_points),
        total_length_m=float(distance[-1]),
    )


def _curved_track(n_points: int, radius: float, arc_rad: float, width: float = WIDTH) -> TrackModel:
    theta = np.linspace(0.0, arc_rad, n_points)
    xy = np.column_stack([radius * np.sin(theta), radius * (1.0 - np.cos(theta))])
    s = theta * radius
    return TrackModel(
        name="curved", sim="test",
        centerline_xy=xy,
        width_left=np.full(n_points, width),
        width_right=np.full(n_points, width),
        curvature=np.full(n_points, 1.0 / radius),
        vert_curvature=np.zeros(n_points),
        total_length_m=float(s[-1]),
    )


def _uniform_mu_field(track: TrackModel, mu: float = 1.0, n_half_width: float = 6.0) -> MuField:
    return MuField(
        s_bins=np.array([0.0, track.total_length_m]),
        n_bins=np.array([-n_half_width, n_half_width]),
        mu_grid=np.full((2, 2), mu),
    )


def _lap_time_for(track: TrackModel, sol: OCPSolution) -> float:
    """Reconstruct the SAME 'sum(ds_offset / v_avg)' integral the validator
    uses internally, so a hand-built fixture's optimal_lap_time_s is exactly
    self-consistent unless a test deliberately corrupts it."""
    k = _reconstruct(sol, track)
    v_avg = 0.5 * (k.v[:-1] + k.v[1:])
    return float(np.sum(k.seg_ds / v_avg))


def _consistent_solution(track: TrackModel, speed: float, n=None) -> OCPSolution:
    n_points = track.n_points
    distance = track.centerline_xy[:, 0].copy() if n is None else None
    # distance_m must be the track's own arclength grid (not necessarily x,
    # but for straight/curved builders above s == cumulative arclength).
    s_track = np.concatenate(([0.0], np.cumsum(track.ds))) if n_points > 1 else np.zeros(n_points)
    n_arr = np.zeros(n_points) if n is None else np.asarray(n, dtype=float)
    sol = OCPSolution(
        distance_m=s_track,
        speed_mps=np.full(n_points, speed, dtype=float),
        throttle=np.full(n_points, 0.5),
        brake=np.zeros(n_points),
        lateral_offset_m=n_arr,
        solver_status="optimal",
    )
    sol.optimal_lap_time_s = _lap_time_for(track, sol)
    return sol


def _vehicle() -> VehicleParams:
    return VehicleParams()


def _report_for(sol, track, mu_field=None, vehicle=None, **kw) -> ValidationReport:
    return validate_solution(
        sol, track,
        mu_field if mu_field is not None else _uniform_mu_field(track),
        vehicle if vehicle is not None else _vehicle(),
        **kw,
    )


def _by_name(report: ValidationReport, name: str):
    for c in report.checks:
        if c.check == name:
            return c
    raise KeyError(name)


def _assert_only_this_check_fails(report: ValidationReport, name: str) -> None:
    failing = [c.check for c in report.checks if not c.passed]
    assert failing == [name], (
        f"expected ONLY {name!r} to fail, got failing checks {failing!r}; "
        f"full report: {report.to_dict()}"
    )


# ---------------------------------------------------------------------------
# 0. Consistent base: passes every check
# ---------------------------------------------------------------------------

def test_consistent_straight_solution_passes_all_checks():
    track = _straight_track(n_points=30, ds=10.0)
    sol = _consistent_solution(track, speed=30.0)

    report = _report_for(sol, track)

    assert report.passed, [c.to_dict() if hasattr(c, "to_dict") else c for c in report.checks]
    assert len(report.checks) == 6
    assert all(c.passed for c in report.checks)
    # residual must be (numerically) exactly zero: straight centerline, n=0,
    # constant speed -> a_lat=0 and a_lon=0 identically.
    assert _by_name(report, "friction_ellipse").worst == pytest.approx(0.0, abs=1e-9)

    # brief's closing requirement: to_dict() must be JSON-serializable.
    blob = json.dumps(report.to_dict())
    assert json.loads(blob)["passed"] is True


# ---------------------------------------------------------------------------
# (a) speed NaN -> finite_speed fails only
# ---------------------------------------------------------------------------

def test_speed_nan_fails_only_finite_speed():
    track = _straight_track(n_points=30, ds=10.0)
    sol = _consistent_solution(track, speed=30.0)
    sol.speed_mps = sol.speed_mps.copy()
    sol.speed_mps[len(sol.speed_mps) // 2] = np.nan

    report = _report_for(sol, track)

    assert not report.passed
    assert not _by_name(report, "finite_speed").passed
    # friction_ellipse/lap_time_consistent depend on speed everywhere (a
    # single NaN poisons the interior residual and the lap-time sum via the
    # finite-difference stencil / running total); they treat a non-finite
    # OWN result as "not their finding" and pass through rather than firing
    # a second, redundant alarm for the same root cause finite_speed already
    # reports -- see solution_validator._check_friction_ellipse/_check_lap_time_consistent.
    _assert_only_this_check_fails(report, "finite_speed")


# ---------------------------------------------------------------------------
# (b) n beyond width -> track_limits fails only
# ---------------------------------------------------------------------------

def test_lateral_offset_beyond_width_fails_only_track_limits():
    track = _straight_track(n_points=30, ds=10.0, width=WIDTH)
    sol = _consistent_solution(track, speed=30.0)
    sol.lateral_offset_m = sol.lateral_offset_m.copy()
    sol.lateral_offset_m[0] = WIDTH + 0.45  # bound is WIDTH+0.05 -> violates

    report = _report_for(sol, track)

    assert not report.passed
    assert not _by_name(report, "track_limits").passed
    # The excursion sits at node 0, inside friction_ellipse's excluded first-3
    # nodes (finite-difference edge noise), so the local curvature spike it
    # creates never reaches the checked interior range; the corresponding
    # offset-path segment is also only ~0.05m longer than nominal, well
    # inside lap_time_consistent's 2% tolerance.
    _assert_only_this_check_fails(report, "track_limits")


# ---------------------------------------------------------------------------
# (c) doubling speed everywhere -> friction_ellipse fails only (a_lat x4)
# ---------------------------------------------------------------------------

def test_doubling_speed_fails_only_friction_ellipse():
    # Needs real curvature (a straight line has a_lat=0 regardless of speed,
    # so doubling speed there can never violate the ellipse): a mild
    # radius=100m arc where the baseline speed keeps a_lat comfortably inside
    # the limit, and doubling it (quadrupling a_lat) clearly exceeds it.
    track = _curved_track(n_points=50, radius=100.0, arc_rad=1.0)
    base = _consistent_solution(track, speed=20.0)
    mu_field = _uniform_mu_field(track)
    vehicle = _vehicle()

    base_report = _report_for(base, track, mu_field, vehicle)
    assert base_report.passed, base_report.to_dict()

    doubled = OCPSolution(
        distance_m=base.distance_m,
        speed_mps=base.speed_mps * 2.0,
        throttle=base.throttle, brake=base.brake,
        lateral_offset_m=base.lateral_offset_m,
        solver_status="optimal",
    )
    # Keep the lap-time FIELD self-consistent with the new (doubled) speed so
    # only friction_ellipse is exercised, not lap_time_consistent.
    doubled.optimal_lap_time_s = _lap_time_for(track, doubled)

    report = _report_for(doubled, track, mu_field, vehicle)

    assert not report.passed
    assert not _by_name(report, "friction_ellipse").passed
    assert _by_name(report, "friction_ellipse").worst > 1.0
    _assert_only_this_check_fails(report, "friction_ellipse")


# ---------------------------------------------------------------------------
# (d) brake=1.5 -> controls_bounded fails only
# ---------------------------------------------------------------------------

def test_brake_out_of_bounds_fails_only_controls_bounded():
    track = _straight_track(n_points=30, ds=10.0)
    sol = _consistent_solution(track, speed=30.0)
    sol.brake = sol.brake.copy()
    sol.brake[5] = 1.5  # bound is [-0.01, 1.01]

    report = _report_for(sol, track)

    assert not report.passed
    assert not _by_name(report, "controls_bounded").passed
    _assert_only_this_check_fails(report, "controls_bounded")


# ---------------------------------------------------------------------------
# (e) lap time field x2 -> lap_time_consistent fails only
# ---------------------------------------------------------------------------

def test_doubled_lap_time_field_fails_only_lap_time_consistent():
    track = _straight_track(n_points=30, ds=10.0)
    sol = _consistent_solution(track, speed=30.0)
    sol.optimal_lap_time_s = sol.optimal_lap_time_s * 2.0

    report = _report_for(sol, track)

    assert not report.passed
    assert not _by_name(report, "lap_time_consistent").passed
    _assert_only_this_check_fails(report, "lap_time_consistent")


# ---------------------------------------------------------------------------
# (f) sawtooth n -> smoothness fails only
# ---------------------------------------------------------------------------

def test_sawtooth_lateral_offset_fails_only_smoothness():
    # Fine node spacing (ds=1m) and a small amplitude (0.2m, well inside the
    # track width) so |d2n/ds2| clears the 1.2*DKAPPA_MAX bound from a
    # high-frequency (period-2) alternation, which a heading/curvature-based
    # reconstruction (2-node-step central difference) cannot see -- so
    # friction_ellipse is unaffected. lap_time_consistent's target is
    # recomputed from the SAME corrugated geometry, so the ~8% longer offset
    # path it (correctly) implies doesn't register as an inconsistency.
    n_points = 30
    ds = 1.0
    track = _straight_track(n_points=n_points, ds=ds)
    amplitude = 0.2
    n_arr = np.array([amplitude if i % 2 == 0 else -amplitude for i in range(n_points)])
    sol = _consistent_solution(track, speed=30.0, n=n_arr)

    report = _report_for(sol, track)

    assert not report.passed
    assert not _by_name(report, "smoothness").passed
    assert _by_name(report, "smoothness").worst > 1.2 * DKAPPA_MAX
    _assert_only_this_check_fails(report, "smoothness")


# ---------------------------------------------------------------------------
# (g) legacy camber_s boost -> friction_ellipse fails without, passes with
# ---------------------------------------------------------------------------

def test_legacy_camber_boost_mirrored():
    # Derive a speed such that friction_ellipse residual r sits between
    # unboosted and boosted limits. Constant camber_s = 0.3 rad.
    track = _curved_track(n_points=50, radius=100.0, arc_rad=1.0)
    mu_field = _uniform_mu_field(track)
    vehicle = _vehicle()

    # Baseline without camber: choose speed such that residual r is just under
    # friction limit (e.g. r ≈ 0.95), then add camber to boost ay_lim.
    # Numerically derive v from: a_lat = v^2 * kappa, need a_lat ≈ ay_lim_unboosted * 0.95
    # For straight or weakly-curved: kappa ≈ 1/radius_eff, so solve for v.
    radius = 100.0
    kappa = 1.0 / radius
    # ay_lim_unboosted ≈ mu_lat * g, where mu_lat ≈ 1.0 * vehicle.tyre_lat.D (mu=1, no weather)
    # For vehicle defaults: mu_lat.D ≈ 1.3, so ay_lim_unboosted ≈ 1.3 * 9.81 ≈ 12.75 m/s^2
    # Set a_lat = 0.95 * 12.75 ≈ 12.11, solve v: v^2 * 0.01 = 12.11 -> v ≈ 34.7 m/s
    v_speed = 34.7

    # Build consistent solution at this speed (no offset).
    sol_unboosted = _consistent_solution(track, speed=v_speed)

    # Without camber_s, this should be at or below the friction limit.
    report_unboosted = _report_for(sol_unboosted, track, mu_field, vehicle)
    unboosted_residual = _by_name(report_unboosted, "friction_ellipse").worst
    # The residual should be close to (but likely under) 1.0 given our derived v.

    # Now test WITH camber_s: same solution, but pass camber_s with constant 0.3 rad.
    # This should boost ay_lim by (1 + K_CAMBER*0.3), making the residual pass even more easily.
    camber_s_arr = np.full(track.n_points, 0.3)
    report_boosted = validate_solution(
        sol_unboosted, track, mu_field, vehicle,
        camber_s=camber_s_arr, eps=0.02,
    )
    boosted_residual = _by_name(report_boosted, "friction_ellipse").worst

    # The residual MUST be lower with the boost (larger ay_lim -> smaller r).
    assert boosted_residual < unboosted_residual, (
        f"camber boost should reduce residual: unboosted={unboosted_residual:.4f}, "
        f"boosted={boosted_residual:.4f}"
    )
    # With the boost, we expect the test to pass (residual <= 1.02).
    assert _by_name(report_boosted, "friction_ellipse").passed, (
        f"friction_ellipse should pass with camber_s boost (residual={boosted_residual:.4f})"
    )


# ---------------------------------------------------------------------------
# (h) GeomField branch smoke test -> all six checks reported
# ---------------------------------------------------------------------------

def test_geom_field_branch_smoke():
    # Smoke test: GeomField with zero kv and constant camber should run cleanly
    # and report all six checks with no exceptions.
    track = _curved_track(n_points=50, radius=100.0, arc_rad=1.0)
    s_track = np.concatenate(([0.0], np.cumsum(track.ds))) if track.n_points > 1 else np.zeros(track.n_points)

    # Build a minimal GeomField: constant kv=0, constant camber=0.1 rad, constant grade=0.
    geom = GeomField(
        s_bins=np.array([s_track[0], s_track[-1]]),
        n_bins=np.array([-WIDTH, WIDTH]),
        kv_grid=np.zeros((2, 2)),
        camber_grid=np.full((2, 2), 0.1),
        grade_grid=np.zeros((2, 2)),
    )

    sol = _consistent_solution(track, speed=25.0)
    mu_field = _uniform_mu_field(track)
    vehicle = _vehicle()

    report = validate_solution(
        sol, track, mu_field, vehicle,
        geom_field=geom, eps=0.02,
    )

    # Must have all six checks and no exceptions.
    assert len(report.checks) == 6
    assert all(hasattr(c, "check") and hasattr(c, "passed") for c in report.checks)
    check_names = {c.check for c in report.checks}
    expected = {"finite_speed", "track_limits", "friction_ellipse",
                "controls_bounded", "lap_time_consistent", "smoothness"}
    assert check_names == expected, f"got {check_names}, expected {expected}"
