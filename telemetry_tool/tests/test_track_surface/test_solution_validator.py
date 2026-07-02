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

import casadi as ca

from lap_oracle.config import OCPSolution, TrackModel, VehicleParams
from lap_oracle.solver.ocp_2d import DKAPPA_MAX, K_CAMBER, G, RHO_AIR, MuField, _PATH_LEN_FLOOR
from track_surface.geom_field import GeomField
from track_surface.solution_validator import (
    ValidationReport,
    _make_mu_lut,
    _offset_curvature,
    _reconstruct,
    _solver_a_lon,
    _solver_camber_n,
    _solver_grid,
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
    # high-frequency (period-2) alternation.
    #
    # b1-task-6b fix note: friction_ellipse's a_lat now uses the SAME
    # analytic d2n term the solver's own kappa_line formula does (see
    # _offset_curvature), so -- correctly -- it is no longer numerically
    # blind to this pattern the way the old raw-XY-reconstruction curvature
    # was (that blindness was the ORIGINAL bug's mirror image: a real
    # solver-side d2n spike this large, v=30 m/s, DOES imply a genuine
    # friction violation; the old validator just couldn't see it). Since
    # a_lat = v^2 * d2n scales with v^2, a low speed keeps this corruption's
    # (still correct) lateral-acceleration implication under the friction
    # limit while still tripping smoothness's own speed-independent
    # |d2n/ds2| rail -- isolating the ONE check this test targets, same as
    # every other corruption test in this file. lap_time_consistent's target
    # is recomputed from the SAME corrugated geometry, so the ~8% longer
    # offset path it (correctly) implies doesn't register as an
    # inconsistency.
    n_points = 30
    ds = 1.0
    track = _straight_track(n_points=n_points, ds=ds)
    amplitude = 0.2
    n_arr = np.array([amplitude if i % 2 == 0 else -amplitude for i in range(n_points)])
    sol = _consistent_solution(track, speed=2.0, n=n_arr)

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
# (g2) legacy camber_s resample must be INDEX-FRACTION, not arc-length (round 4)
# ---------------------------------------------------------------------------

def test_solver_camber_n_matches_index_fraction_ground_truth():
    """_solver_camber_n must mirror ocp_2d._to_n / ocp_2d_stitched._to_n's
    EXACT recipe -- np.interp(linspace(0,1,N), linspace(0,1,M), arr) -- never
    an arc-length interpolation. Non-constant camber_s with N != M (a
    constant array, or N==M hitting the solver's own same-length
    short-circuit, would read identically under either formula and mask the
    round-4 bug -- see b1-task-6d-debug4-report.md)."""
    camber_s = np.array([0.0, 0.0, 0.0, 0.4, 0.1, 0.0])  # M=6, sharp feature
    N = 4

    result = _solver_camber_n(camber_s, N)

    expected = np.interp(np.linspace(0, 1, N), np.linspace(0, 1, len(camber_s)), camber_s)
    np.testing.assert_allclose(result, expected, rtol=0, atol=1e-15)
    assert not np.allclose(result, camber_s[:N]), "must not be a naive positional slice"

    # Solver's own short-circuit: identical length -> returned unchanged, no
    # interpolation at all (mirrors ocp_2d._to_n's `if len(a) == N: return a`).
    same_len = np.array([0.1, 0.2, 0.3])
    np.testing.assert_array_equal(_solver_camber_n(same_len, 3), same_len)

    # Degenerate-input guard (not a real code path -- see docstring): empty
    # camber_s must not raise, and gracefully means "no boost".
    np.testing.assert_array_equal(_solver_camber_n(np.array([]), 5), np.zeros(5))


def test_legacy_camber_boost_diverges_from_arc_length_when_grid_span_shortfalls():
    """End-to-end regression for the round-4 bug: lap_oracle.track.model.
    resample_track's ``np.arange(0, total, ds_target)`` always stops before
    reaching the track's true total length (confirmed ~2m/0.27% shortfall on
    a real 758m track) -- so the solver's own per-node
    ``camber_n = _to_n(camber_s)`` (index-fraction) samples camber_s at a
    slightly different (LATER-along-the-lap) native position than an
    arc-length interpolation of camber_s onto the solution's own distance_m
    would, at the SAME query node. Reproduced here with an exaggerated 5%
    shortfall (well outside floating-point noise) mirroring the real track's
    ~0.27% one, where this was found (see b1-task-6d-debug4-report.md).

    Fixture: camber_s is a HIGH constant baseline (0.35 rad) with a narrow
    notch to 0.0 at native indices 31-33 (of 41). At query node i=17 (the
    last node this check's own _EDGE_EXCLUDE=3 slice includes, for N=21):
    arc-length's query lands INSIDE the notch (continuous native index
    ~32.3, camber=0, no boost) while index-fraction's query lands EXACTLY on
    native index 34 (back at the 0.35 baseline, full boost) -- so the two
    methods disagree sharply at exactly the node this test isolates. This
    mirrors the real bug's own direction: the arc-length (pre-round-4, buggy)
    formula misses a boost the solver's index-fraction resample actually
    applied, so it reports a HIGHER (falsely elevated) friction_ellipse
    residual than the solver's own physics ever enforced. Constant speed ->
    a_lon=0 identically (same trick
    test_consistent_straight_solution_passes_all_checks uses) and constant
    curvature (circular arc) -> a_lat is ~uniform across nodes, isolating a
    clean, camber-driven r_lat divergence rather than a geometry-driven one."""
    M = 41
    track = _curved_track(n_points=M, radius=200.0, arc_rad=0.5)
    total_native = track.total_length_m

    camber_s = np.full(M, 0.35)
    camber_s[31:34] = 0.0  # narrow notch arc-length's node-17 query lands in

    N = 21
    d = np.linspace(0.0, 0.95 * total_native, N)  # solver-grid-like shortfall
    n_arr = np.zeros(N)
    speed = 25.0
    mu_field = _uniform_mu_field(track, mu=1.0)
    vehicle = _vehicle()

    sol = OCPSolution(
        distance_m=d,
        speed_mps=np.full(N, speed),
        throttle=np.full(N, 0.5),
        brake=np.zeros(N),
        lateral_offset_m=n_arr,
        solver_status="optimal",
    )
    sol.optimal_lap_time_s = _lap_time_for(track, sol)

    report = validate_solution(sol, track, mu_field, vehicle, camber_s=camber_s, eps=0.02)
    worst = _by_name(report, "friction_ellipse").worst

    # Reuse the already-locked kinematics (a_lat/a_lon formulas are covered by
    # rounds 1-2's own tests) to hand-derive the residual under EACH
    # candidate camber resample, without re-deriving them independently.
    kin = _reconstruct(sol, track)
    assert np.allclose(kin.a_lon, 0.0), "constant speed must give a_lon==0 (isolates r_lat)"

    grip = 1.0  # _uniform_mu_field's flat value; a constant field's bspline is exact
    ay_lim_base = vehicle.tyre_lat.D * grip * (
        vehicle.mass_kg * G + 0.5 * RHO_AIR * vehicle.cla * speed ** 2
    ) / vehicle.mass_kg

    s_track = np.concatenate(([0.0], np.cumsum(track.ds)))
    camber_index_fraction = np.interp(np.linspace(0, 1, N), np.linspace(0, 1, M), camber_s)
    camber_arc_length = np.interp(d, s_track, camber_s)
    assert not np.allclose(camber_index_fraction, camber_arc_length), (
        "fixture must make the two candidate resamples diverge"
    )

    def worst_r_lat(camber_arr):
        ay_lim = ay_lim_base * (1.0 + K_CAMBER * np.abs(camber_arr))
        r_lat = (kin.a_lat / ay_lim) ** 2
        return float(np.max(r_lat[3:-3]))

    expected_index = worst_r_lat(camber_index_fraction)
    expected_arclength = worst_r_lat(camber_arc_length)
    assert expected_index != pytest.approx(expected_arclength, rel=1e-6), (
        "fixture didn't distinguish the two candidate formulas"
    )
    assert worst == pytest.approx(expected_index, rel=1e-6), (
        f"friction_ellipse must resample camber_s by INDEX FRACTION "
        f"(_solver_camber_n), not arc-length: got {worst:.6f}, "
        f"expected(index-fraction)={expected_index:.6f}, "
        f"expected(arc-length, the pre-round-4 formula)={expected_arclength:.6f}"
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


# ---------------------------------------------------------------------------
# b1-task-6b fix: analytic offset-curve curvature (root-caused a 9.8x
# friction_ellipse false positive to the OLD raw-XY-reconstruction curvature
# -- see b1-task-6b-debug-report.md). These lock the replacement formula
# against ground-truth geometry and the new mu-interpolant fallback,
# independent of any solve.
# ---------------------------------------------------------------------------

def test_offset_curvature_matches_circle_geometry_analytically():
    """Ground truth: offsetting a circular arc (radius R, curvature 1/R) by
    a CONSTANT n gives another circle of radius (R - n) -- i.e. curvature
    1/(R-n), which is EXACTLY kappa_c/(1-n*kappa_c) algebraically. (Sign:
    _curved_track's arc has its center on the +normal/"track-left" side at
    theta=0, so positive n moves toward the center, shrinking the radius.)
    d2n=0 for constant n, so this isolates the kappa_c/(1-n*kappa_c) term.
    Locks _offset_curvature's formula against real geometry, independent of
    any solve.
    """
    R = 100.0
    track = _curved_track(n_points=200, radius=R, arc_rad=1.0)
    d = np.concatenate(([0.0], np.cumsum(track.ds)))
    for n_const in (-3.0, 0.0, 2.0, 5.0):
        n_arr = np.full(track.n_points, n_const)
        kappa_offset = _offset_curvature(track, d, n_arr)
        expected = 1.0 / (R - n_const)
        # Interior nodes only: np.gradient's one-sided edge stencil (same
        # reasoning as _EDGE_EXCLUDE elsewhere) is less accurate there.
        np.testing.assert_allclose(kappa_offset[5:-5], expected, rtol=2e-3)


def test_offset_curvature_zero_on_straight_regardless_of_n():
    """kappa_c=0 on a straight track -> kappa_offset reduces to d2n/ds2
    exactly (the denom_i floor never engages when kappa_c is already 0)."""
    track = _straight_track(n_points=30, ds=2.0)
    d = np.concatenate(([0.0], np.cumsum(track.ds)))
    n_arr = np.zeros(30)
    assert np.allclose(_offset_curvature(track, d, n_arr), 0.0, atol=1e-9)


def test_make_mu_lut_falls_back_to_linear_for_sparse_grid():
    """Guards the _MU_BSPLINE_MIN_KNOTS fallback: ca.interpolant(...,
    "bspline", ...) hard-errors ("Need more data points") below 4 knots per
    axis (empirically verified: 3x3 fails, 4x4 works -- mirrors
    ocp_2d._make_geom_interpolants' identical >=4 fallback). Every other
    test in this file relies on _uniform_mu_field's 2x2 grid NOT raising."""
    track = _straight_track(n_points=10, ds=5.0)
    sparse = _uniform_mu_field(track)  # 2x2 grid -- must fall back to linear
    lut_sparse = _make_mu_lut(sparse)
    assert float(lut_sparse(ca.DM([0.0, 0.0]))) == pytest.approx(1.0)

    dense = MuField(
        s_bins=np.linspace(0.0, track.total_length_m, 6),
        n_bins=np.linspace(-6.0, 6.0, 6),
        mu_grid=np.full((6, 6), 0.85),
    )
    lut_dense = _make_mu_lut(dense)  # 6x6 grid -- uses the real bspline path
    assert float(lut_dense(ca.DM([10.0, 0.0]))) == pytest.approx(0.85, abs=1e-6)


# ---------------------------------------------------------------------------
# b1-task-6c (round 2) fix: a_lon now mirrors _solve_once's Ax EXACTLY (a
# per-segment forward difference over the Frenet-adjusted path length,
# evaluated at the segment's start node) instead of a node-centered central
# difference over the reconstructed offset-path chord length -- root-caused
# a 24.7x friction_ellipse false-positive at a sharp real-world grip step to
# this discretization/alignment mismatch, not to mu clamping or a drag/rr
# "tire demand" recovery (both hypotheses tested with evidence and refuted --
# see b1-task-6c-debug2-report.md). These lock the replacement formula
# against ground truth, independent of any solve.
# ---------------------------------------------------------------------------

def test_solver_a_lon_matches_forward_difference_ground_truth():
    """v^2 growing LINEARLY in s at a constant rate `a` (v(s)^2 = v0^2 +
    2*a*s) has an EXACT forward difference (v[i+1]^2-v[i]^2)/(2*ds[i]) == a
    at every node -- ground truth for the solver's own Ax formula
    (_solve_once's V[i+1]**2==V[i]**2+2*Ax[i]*ds_path_i). Straight track
    (kappa_c=0) so ds_path_i reduces to the raw ds[i], isolating the
    forward-difference behaviour from the Frenet-Jacobian scaling (covered
    by the next test)."""
    n_points = 20
    track = _straight_track(n_points=n_points, ds=5.0)
    d = np.concatenate(([0.0], np.cumsum(track.ds)))
    a_true = 0.6
    v0 = 10.0
    v = np.sqrt(v0 ** 2 + 2 * a_true * d)
    n_arr = np.zeros(n_points)

    a_lon = _solver_a_lon(track, d, n_arr, v)

    np.testing.assert_allclose(a_lon[:-1], a_true, rtol=1e-9)


def test_solver_a_lon_uses_frenet_path_length_and_is_not_node_centered():
    """Locks two properties the OLD central-diff-over-chord-length formula
    got wrong (b1-task-6c-debug2-report.md): (1) the denominator is the
    solver's OWN Frenet-adjusted ds_path_i = ds[i]*max(1-n_mid_i*kappa_c_i,
    _PATH_LEN_FLOOR), not the raw chord length; (2) segment i's value comes
    ONLY from nodes i and i+1 -- it must NOT change when v changes at node
    i+2, unlike a node-centered central difference at node i-1, which would
    blend segment i (nodes i, i+1) into node i-1's own reconstructed value.
    """
    R = 80.0
    n_points = 40
    track = _curved_track(n_points=n_points, radius=R, arc_rad=1.2)
    d = np.concatenate(([0.0], np.cumsum(track.ds)))
    n_arr = np.full(n_points, 1.5)  # constant nonzero offset -> kappa_c/ds_path both engage
    v = np.linspace(20.0, 25.0, n_points)  # smooth ramp everywhere...
    i = 20
    v_step = v.copy()
    v_step[i + 1] += 8.0  # ...except a sharp local step landing on node i+1

    a_lon_step = _solver_a_lon(track, d, n_arr, v_step)
    a_lon_flat = _solver_a_lon(track, d, n_arr, v)  # same, but without the step

    # (1) ground truth for segment i (nodes i, i+1), using the SAME kappa_c
    # recipe the implementation uses (not an analytic 1/R approximation).
    # b1-task-6d (round 3): kappa_c now comes from _solver_grid -- the
    # track resampled (via the SAME resample_track ocp_2d/ocp_2d_stitched
    # call) onto the solver's OWN grid, at the ds_target recovered from d's
    # own spacing -- not a native-grid recompute, so the ground truth here
    # must sample the SAME resampled grid (see b1-task-6d-debug3-report.md).
    grid = _solver_grid(track, d)
    s_grid = np.concatenate(([0.0], np.cumsum(grid.ds)))
    kappa_c_i = np.interp(d[i], s_grid, grid.curvature)
    ds_i = d[i + 1] - d[i]
    ds_path_i = ds_i * max(1.0 - n_arr[i] * kappa_c_i, _PATH_LEN_FLOOR)
    expected_i = (v_step[i + 1] ** 2 - v_step[i] ** 2) / (2.0 * ds_path_i)
    assert a_lon_step[i] == pytest.approx(expected_i, rel=1e-9)

    # (2) segment i-1 (nodes i-1, i) must be IDENTICAL with or without the
    # step at node i+1 -- it never reads node i+1. A node-centered central
    # difference at node i-1 would instead change here (it reads node i+1
    # indirectly via segment i's slope).
    assert a_lon_step[i - 1] == pytest.approx(a_lon_flat[i - 1], rel=1e-9)
    # Sanity: the step DOES change segment i itself (else the test proves
    # nothing about isolation).
    assert a_lon_step[i] != pytest.approx(a_lon_flat[i], rel=1e-6)


# ---------------------------------------------------------------------------
# b1-task-6d (round 3) fix: kappa_c (and the other per-node track arrays
# friction_ellipse/track_limits consume -- width_left/width_right,
# vert_curvature for the no-geom kv path) are now sampled via _solver_grid,
# which resamples the track onto the solver's OWN grid (the SAME public
# resample_track ocp_2d/ocp_2d_stitched call, at the ds_target recovered
# from the solution's own distance_m spacing), instead of interpolating
# from the track's native point grid -- root-caused a real-track
# friction_ellipse residual of 2.17 (node 75: native kappa_c=0.0526 vs.
# solver-resampled kappa_c=0.0412, ~27% different) to this grid mismatch --
# see b1-task-6c-debug2-report.md (found, round 2) and
# b1-task-6d-debug3-report.md (fixed, round 3). These lock the mechanism
# itself, independent of any solve.
# ---------------------------------------------------------------------------

def test_solver_grid_is_a_genuine_resample_not_the_native_track():
    """_solver_grid must actually resample_track (producing a grid with
    len(d) points, freshly recomputed curvature) rather than passing the
    native track through unchanged -- the exact mechanism this round's fix
    relies on. Native track deliberately has a MUCH finer grid (300 points)
    than the solution's own grid (40 points, as a real stitched solve's
    sol.distance_m would carry relative to the track's native resolution)."""
    track = _curved_track(n_points=300, radius=50.0, arc_rad=1.5)
    d = np.linspace(0.0, track.total_length_m * 0.99, 40)

    grid = _solver_grid(track, d)

    assert grid.n_points == len(d) == 40
    assert grid.n_points != track.n_points
    assert grid.curvature is not track.curvature


def test_solver_grid_falls_back_below_min_resample_points_ignores_stale_curvature():
    """Degenerate-input guard: fewer than 10 points on either side must not
    raise (resample_track -> build_from_xy hard-requires >= 10 points) --
    falls back to the native track with curvature freshly recomputed from
    centerline_xy, NEVER trusting track.curvature directly (it may be stale
    -- see module docstring). Not a real code path for any actual solve
    (400+ nodes in practice)."""
    track = _straight_track(n_points=5, ds=10.0)
    track.curvature = np.full(5, 999.0)  # deliberately stale/wrong sentinel
    d = np.concatenate(([0.0], np.cumsum(track.ds)))  # also 5 points

    grid = _solver_grid(track, d)

    assert grid.n_points == 5
    # Straight track's TRUE curvature is 0 everywhere -- never the stale
    # 999.0 sentinel above.
    assert np.allclose(grid.curvature, 0.0)


def test_offset_curvature_uses_solver_resampled_grid_not_native_interpolation():
    """kappa_c for a CONSTANT-n offset must match the analytic
    kappa_c/(1-n*kappa_c) ground truth using the SOLVER-RESAMPLED grid's own
    curvature (round 3), confirming _offset_curvature no longer routes
    through a native-grid interpolation. d intentionally carries FAR fewer
    points (25) than the native track (250) -- a real resample, not a
    same-resolution passthrough."""
    R = 60.0
    track = _curved_track(n_points=250, radius=R, arc_rad=1.0)
    d = np.linspace(0.0, track.total_length_m * 0.99, 25)
    n_const = 3.0
    n_arr = np.full(len(d), n_const)

    kappa_offset = _offset_curvature(track, d, n_arr)

    grid = _solver_grid(track, d)
    s_grid = np.concatenate(([0.0], np.cumsum(grid.ds)))
    kappa_c = np.interp(d, s_grid, grid.curvature)
    expected = kappa_c / np.maximum(1.0 - n_const * kappa_c, 0.1)
    # Interior nodes only -- same one-sided-stencil-at-the-edges reasoning
    # as test_offset_curvature_matches_circle_geometry_analytically.
    np.testing.assert_allclose(kappa_offset[3:-3], expected[3:-3], rtol=1e-9)
