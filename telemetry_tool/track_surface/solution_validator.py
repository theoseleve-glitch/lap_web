"""Physics self-consistency validator (spec section 5).

Audits an already-solved :class:`OCPSolution` from its OUTPUTS ONLY --
speed, lateral offset, and track geometry -- independent of solver
internals. This is the program's honesty instrument: it never reads a
solver's internal decision variables (there are none available on
``OCPSolution`` anyway) and never trusts the track's precomputed planar
``curvature`` array either; every geometric quantity (offset path, its
curvature, its arc length) is reconstructed from the reported
``distance_m``/``lateral_offset_m`` arrays by finite differences, so a
solver bug that corrupts its own internal bookkeeping cannot also corrupt
the audit.

The friction-ellipse limits (fz, mu, camber boost) mirror
``lap_oracle.solver.ocp_2d._solve_once`` exactly -- module constants
(G, RHO_AIR, EPS_GRIP, K_CAMBER, DKAPPA_MAX) and the mu lookup
(``_make_mu_interpolant``) are imported and reused, never re-hardcoded.
"""
from __future__ import annotations

from dataclasses import dataclass

import casadi as ca
import numpy as np

from lap_oracle.config import OCPSolution, TrackModel, VehicleParams
from lap_oracle.solver.ocp_2d import (
    DKAPPA_MAX,
    EPS_GRIP,
    G,
    K_CAMBER,
    RHO_AIR,
    MuField,
    _make_mu_interpolant,
    central_second_diff_periodic,
)
from track_surface.geom_field import GeomField

# Task 6's smoothness rail check is 1.2x the solver's own hard cap on |d2n|
# (DKAPPA_MAX) -- generous enough to never bind the clean line, tight enough
# to catch a real seam kink. Derived from the imported constant, never a
# copied literal.
SMOOTHNESS_BOUND: float = 1.2 * DKAPPA_MAX

# Nodes excluded from the friction_ellipse residual at each end of the array:
# finite-difference curvature/dv-ds stencils are least accurate there.
_EDGE_EXCLUDE: int = 3


@dataclass
class CheckResult:
    check: str
    passed: bool
    worst: float
    detail: str


@dataclass
class ValidationReport:
    passed: bool
    checks: list[CheckResult]

    def to_dict(self) -> dict:
        return {
            "passed": bool(self.passed),
            "checks": [
                {
                    "check": c.check,
                    "passed": bool(c.passed),
                    "worst": float(c.worst),
                    "detail": c.detail,
                }
                for c in self.checks
            ],
        }


# ---------------------------------------------------------------------------
# Geometry reconstruction helpers (pure numpy)
# ---------------------------------------------------------------------------

def _track_s(track: TrackModel) -> np.ndarray:
    """Cumulative arclength at each centerline node (0 at the first node)."""
    if track.n_points == 0:
        return np.zeros(0)
    if track.n_points == 1:
        return np.zeros(1)
    return np.concatenate(([0.0], np.cumsum(track.ds)))


def _heading(xy: np.ndarray) -> np.ndarray:
    """Tangent heading (radians) via central differences; one-sided at ends.

    Mirrors track_surface.frenet._compute_heading's stencil exactly (kept
    local/self-contained so this module reconstructs geometry from OUTPUTS
    only, without importing FrenetFrame machinery it doesn't otherwise need).
    """
    n = len(xy)
    if n == 0:
        return np.zeros(0)
    if n == 1:
        return np.zeros(1)
    dx = np.empty(n)
    dy = np.empty(n)
    dx[1:-1] = xy[2:, 0] - xy[:-2, 0]
    dy[1:-1] = xy[2:, 1] - xy[:-2, 1]
    dx[0] = xy[1, 0] - xy[0, 0]
    dy[0] = xy[1, 1] - xy[0, 1]
    dx[-1] = xy[-1, 0] - xy[-2, 0]
    dy[-1] = xy[-1, 1] - xy[-2, 1]
    return np.arctan2(dy, dx)


def _central_diff_ds(y: np.ndarray, s: np.ndarray) -> np.ndarray:
    """d(y)/ds via central differences at interior nodes, one-sided at ends."""
    y = np.asarray(y, dtype=float)
    s = np.asarray(s, dtype=float)
    n = len(y)
    out = np.zeros(n)
    if n < 2:
        return out
    ds = np.diff(s)
    ds_safe = np.where(np.abs(ds) > 1e-9, ds, 1e-9)
    dy = np.diff(y)
    mid = dy / ds_safe
    if n == 2:
        out[:] = mid[0]
        return out
    out[1:-1] = 0.5 * (mid[:-1] + mid[1:])
    out[0] = mid[0]
    out[-1] = mid[-1]
    return out


def _offset_path_xy(track: TrackModel, distance_m: np.ndarray, n: np.ndarray) -> np.ndarray:
    """Reconstruct the actually-driven path: centerline + n * unit normal.

    Same convention as track_surface.frenet.FrenetFrame.sn_to_xy (normal =
    90 deg CCW from tangent, + = track-left): interpolate the centerline
    position and heading to the solution's own ``distance_m`` grid, then
    offset laterally by ``n``.
    """
    s_track = _track_s(track)
    cxy = track.centerline_xy
    if len(s_track) < 2:
        return cxy.copy()
    heading = _heading(cxy)
    d = np.clip(np.asarray(distance_m, dtype=float), s_track[0], s_track[-1])
    x_c = np.interp(d, s_track, cxy[:, 0])
    y_c = np.interp(d, s_track, cxy[:, 1])
    h = np.interp(d, s_track, heading)
    nx, ny = -np.sin(h), np.cos(h)
    n = np.asarray(n, dtype=float)
    return np.column_stack([x_c + n * nx, y_c + n * ny])


def _bilinear(s_bins: np.ndarray, n_bins: np.ndarray, grid: np.ndarray,
              s: np.ndarray, n: np.ndarray) -> np.ndarray:
    """Vectorised bilinear lookup -- same formula as GripSurface.mu_at,
    generalised to arbitrary (s_bins, n_bins, grid) and array queries.
    Used for GeomField kv/camber (pure-numpy geometry path); the mu lookup
    itself uses the solver's own casadi interpolant (see _check_friction_ellipse)."""
    s_bins = np.asarray(s_bins, dtype=float)
    n_bins = np.asarray(n_bins, dtype=float)
    s = np.clip(np.asarray(s, dtype=float), s_bins[0], s_bins[-1])
    n = np.clip(np.asarray(n, dtype=float), n_bins[0], n_bins[-1])
    si = np.clip(np.searchsorted(s_bins, s) - 1, 0, len(s_bins) - 2)
    ni = np.clip(np.searchsorted(n_bins, n) - 1, 0, len(n_bins) - 2)
    s0, s1 = s_bins[si], s_bins[si + 1]
    n0, n1 = n_bins[ni], n_bins[ni + 1]
    ws = (s - s0) / np.maximum(s1 - s0, 1e-9)
    wn = (n - n0) / np.maximum(n1 - n0, 1e-9)
    v00 = grid[si, ni]
    v10 = grid[si + 1, ni]
    v01 = grid[si, ni + 1]
    v11 = grid[si + 1, ni + 1]
    return v00 * (1 - ws) * (1 - wn) + v10 * ws * (1 - wn) + v01 * (1 - ws) * wn + v11 * ws * wn


@dataclass
class _Kinematics:
    """Reconstructed-from-outputs bundle shared by friction_ellipse and
    lap_time_consistent so the offset path is computed exactly once."""
    d: np.ndarray
    n: np.ndarray
    v: np.ndarray
    xy: np.ndarray
    seg_ds: np.ndarray
    s_off: np.ndarray
    kappa_path: np.ndarray
    a_lat: np.ndarray
    a_lon: np.ndarray


def _reconstruct(sol: OCPSolution, track: TrackModel) -> _Kinematics:
    d = np.asarray(sol.distance_m, dtype=float)
    n = np.asarray(sol.lateral_offset_m, dtype=float)
    v = np.asarray(sol.speed_mps, dtype=float)
    xy = _offset_path_xy(track, d, n)
    if len(xy) >= 2:
        seg = np.diff(xy, axis=0)
        seg_ds = np.sqrt((seg ** 2).sum(axis=1))
        s_off = np.concatenate(([0.0], np.cumsum(seg_ds)))
    else:
        seg_ds = np.zeros(0)
        s_off = np.zeros(len(xy))
    heading = np.unwrap(_heading(xy)) if len(xy) else np.zeros(0)
    kappa_path = _central_diff_ds(heading, s_off)
    dv_ds = _central_diff_ds(v, s_off)
    a_lat = v ** 2 * kappa_path
    a_lon = v * dv_ds
    return _Kinematics(d=d, n=n, v=v, xy=xy, seg_ds=seg_ds, s_off=s_off,
                        kappa_path=kappa_path, a_lat=a_lat, a_lon=a_lon)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def _check_finite_speed(sol: OCPSolution) -> CheckResult:
    v = np.asarray(sol.speed_mps, dtype=float)
    if v.size == 0:
        return CheckResult("finite_speed", False, 0.0, "speed array is empty")
    bad = ~np.isfinite(v) | (v <= 0)
    n_bad = int(np.count_nonzero(bad))
    passed = n_bad == 0
    detail = (
        f"all {v.size} nodes finite and positive (min={float(v.min()):.3f} m/s)"
        if passed else
        f"{n_bad}/{v.size} nodes have non-finite or non-positive speed"
    )
    return CheckResult("finite_speed", passed, float(n_bad), detail)


def _check_track_limits(sol: OCPSolution, track: TrackModel) -> CheckResult:
    n = np.asarray(sol.lateral_offset_m, dtype=float)
    d = np.asarray(sol.distance_m, dtype=float)
    s_track = _track_s(track)
    if track.n_points < 2 or n.size == 0 or len(s_track) < 2:
        return CheckResult("track_limits", True, 0.0, "insufficient track/solution data -- skipped")
    d_c = np.clip(d, s_track[0], s_track[-1])
    w_left = np.interp(d_c, s_track, track.width_left)
    w_right = np.interp(d_c, s_track, track.width_right)
    hi = w_left + 0.05
    lo = -w_right - 0.05
    viol = np.maximum(np.maximum(n - hi, lo - n), 0.0)
    worst = float(np.max(viol))
    passed = bool(worst <= 1e-9)
    detail = f"max excursion beyond corridor (+/-0.05 m margin) = {worst:.4f} m"
    return CheckResult("track_limits", passed, worst, detail)


def _check_controls_bounded(sol: OCPSolution) -> CheckResult:
    lo, hi = -0.01, 1.01
    arrays = []
    if sol.throttle is not None and len(sol.throttle) > 0:
        arrays.append(np.asarray(sol.throttle, dtype=float))
    if sol.brake is not None and len(sol.brake) > 0:
        arrays.append(np.asarray(sol.brake, dtype=float))
    if not arrays:
        return CheckResult("controls_bounded", True, 0.0, "no throttle/brake arrays present -- skipped")
    combined = np.concatenate(arrays)
    viol = np.maximum(np.maximum(combined - hi, lo - combined), 0.0)
    worst = float(np.max(viol))
    passed = bool(worst <= 1e-9)
    detail = f"max out-of-[{lo}, {hi}] margin = {worst:.4f}"
    return CheckResult("controls_bounded", passed, worst, detail)


def _check_smoothness(sol: OCPSolution) -> CheckResult:
    d = np.asarray(sol.distance_m, dtype=float)
    n = np.asarray(sol.lateral_offset_m, dtype=float)
    if n.size < 3:
        return CheckResult("smoothness", True, 0.0, "too few nodes -- skipped")
    ds = np.diff(d)
    ds = np.where(np.abs(ds) > 1e-9, ds, 1e-9)
    d2n = central_second_diff_periodic(n, ds)
    if not np.all(np.isfinite(d2n)):
        finite = d2n[np.isfinite(d2n)]
        worst = float(np.max(np.abs(finite))) if finite.size else 0.0
        return CheckResult("smoothness", True, worst,
                            "skipped: non-finite lateral_offset_m upstream (see finite_speed/track_limits)")
    worst = float(np.max(np.abs(d2n)))
    passed = bool(worst <= SMOOTHNESS_BOUND)
    detail = f"max |d2n/ds2| = {worst:.4f} (threshold {SMOOTHNESS_BOUND:.4f} = 1.2 x DKAPPA_MAX)"
    return CheckResult("smoothness", passed, worst, detail)


def _check_lap_time_consistent(kin: _Kinematics, sol: OCPSolution, *, eps: float) -> CheckResult:
    if kin.v.size < 2:
        return CheckResult("lap_time_consistent", True, 0.0, "too few nodes -- skipped")
    v_avg = 0.5 * (kin.v[:-1] + kin.v[1:])
    with np.errstate(divide="ignore", invalid="ignore"):
        lap_time = float(np.sum(kin.seg_ds / v_avg))
    target = float(sol.optimal_lap_time_s)
    if not np.isfinite(lap_time) or not np.isfinite(target) or target == 0.0:
        return CheckResult("lap_time_consistent", True, 0.0,
                            "reconstructed or reported lap time non-finite/zero -- skipped "
                            "(see finite_speed for the likely root cause)")
    rel_err = abs(lap_time - target) / abs(target)
    passed = bool(rel_err <= eps)
    detail = (f"reconstructed {lap_time:.4f}s vs reported {target:.4f}s "
              f"({rel_err * 100:.2f}% rel. error, tolerance {eps * 100:.1f}%)")
    return CheckResult("lap_time_consistent", passed, float(rel_err), detail)


def _check_friction_ellipse(
    kin: _Kinematics, track: TrackModel, mu_field: MuField, vehicle: VehicleParams,
    weather_grip_multiplier: float, *, geom_field: GeomField | None, eps: float,
) -> CheckResult:
    v, n, d = kin.v, kin.n, kin.d
    N = len(v)
    if N <= 2 * _EDGE_EXCLUDE:
        lo_i, hi_i = 0, N
    else:
        lo_i, hi_i = _EDGE_EXCLUDE, N - _EDGE_EXCLUDE

    s_track = _track_s(track)
    d_c = np.clip(d, s_track[0], s_track[-1]) if len(s_track) else d

    # g_eff from vertical curvature: geom_field at (s, n) if given, else the
    # track's own vert_curvature interpolated to distance_m, else flat (kv=0
    # -> g_eff falls back to plain G). Mirrors _solve_once's kv_i/g_eff_i.
    if geom_field is not None:
        kv = _bilinear(geom_field.s_bins, geom_field.n_bins, geom_field.kv_grid, d_c, n)
        camber = _bilinear(geom_field.s_bins, geom_field.n_bins, geom_field.camber_grid, d_c, n)
    else:
        if track.vert_curvature is not None and len(track.vert_curvature) == len(s_track) and len(s_track):
            kv = np.interp(d_c, s_track, track.vert_curvature)
        else:
            kv = np.zeros(N)
        camber = np.zeros(N)

    g_eff = np.maximum(G + v ** 2 * kv, 1.0)
    fz_total = vehicle.mass_kg * g_eff + 0.5 * RHO_AIR * vehicle.cla * v ** 2

    # mu(s, n): the solver's own numeric lookup, evaluated pointwise (not
    # inside an Opti) -- float(lut(ca.DM([s, n]))) is the documented pattern.
    mu_lut = _make_mu_interpolant(mu_field)
    s_mu = np.clip(d, mu_field.s_bins[0], mu_field.s_bins[-1])
    n_mu = np.clip(n, mu_field.n_bins[0], mu_field.n_bins[-1])
    grip_raw = np.array([float(mu_lut(ca.DM([float(si), float(ni)]))) for si, ni in zip(s_mu, n_mu)])
    mu_ceiling = max(float(mu_field.mu_grid.max()), EPS_GRIP)
    grip = np.clip(grip_raw, EPS_GRIP, mu_ceiling)

    mu_lat = vehicle.tyre_lat.D * weather_grip_multiplier * grip
    mu_long = vehicle.tyre_long.D * weather_grip_multiplier * grip
    ax_lim = mu_long * fz_total / vehicle.mass_kg
    ay_lim = mu_lat * fz_total / vehicle.mass_kg
    if geom_field is not None:
        ay_lim = ay_lim * (1.0 + K_CAMBER * np.abs(camber))

    with np.errstate(divide="ignore", invalid="ignore"):
        r = (kin.a_lon / ax_lim) ** 2 + (kin.a_lat / ay_lim) ** 2

    r_interior = r[lo_i:hi_i]
    if r_interior.size == 0:
        return CheckResult("friction_ellipse", True, 0.0, "no interior nodes to check")
    if not np.all(np.isfinite(r_interior)):
        # A non-finite residual here means an upstream input (speed, offset
        # path) was already invalid -- that is finite_speed's (or another
        # check's) finding to report, not a friction-ellipse violation in
        # its own right.
        finite = r_interior[np.isfinite(r_interior)]
        worst = float(np.max(finite)) if finite.size else 0.0
        return CheckResult("friction_ellipse", True, worst,
                            "skipped: non-finite inputs upstream (see finite_speed)")

    worst = float(np.max(r_interior))
    passed = bool(worst <= 1.0 + eps)
    detail = (f"max (a_lon/ax_lim)^2+(a_lat/ay_lim)^2 = {worst:.4f} over "
              f"{r_interior.size} interior nodes (threshold {1.0 + eps:.4f})")
    return CheckResult("friction_ellipse", passed, worst, detail)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def validate_solution(
    sol: OCPSolution,
    track: TrackModel,
    mu_field: MuField,
    vehicle: VehicleParams,
    *,
    geom_field: GeomField | None = None,
    eps: float = 0.02,
) -> ValidationReport:
    """Audit ``sol`` from its outputs only. ``eps`` is the shared slack: the
    friction-ellipse residual tolerance (pass iff max(r) <= 1+eps) and the
    lap-time relative tolerance both default to the same 2%."""
    weather = getattr(sol, "weather", None)
    grip_multiplier = float(weather.grip_multiplier) if weather is not None else 1.0

    kin = _reconstruct(sol, track)

    checks = [
        _check_finite_speed(sol),
        _check_track_limits(sol, track),
        _check_friction_ellipse(
            kin, track, mu_field, vehicle, grip_multiplier,
            geom_field=geom_field, eps=eps,
        ),
        _check_controls_bounded(sol),
        _check_lap_time_consistent(kin, sol, eps=eps),
        _check_smoothness(sol),
    ]
    return ValidationReport(passed=all(c.passed for c in checks), checks=checks)
