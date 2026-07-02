"""
track_surface/solver_bridge.py
------------------------------
Bridge between TrackSurface and the existing CasADi OCP solver.

Converts a TrackSurface into the lap_oracle's TrackModel format so the
existing solver (ocp.py) can optimise lateral offset + speed using real
track data instead of defaults.
"""
from __future__ import annotations

import logging

import numpy as np

from track_surface.drainage import puddle_footprint_radius
from track_surface.geom_field import build_geom_field
from track_surface.model import TrackSurface

logger = logging.getLogger(__name__)

_DEFAULT_WIDTH_M = 5.0


def surface_to_track_model(surface: TrackSurface):
    """Convert a TrackSurface to the OCP solver's TrackModel.

    Maps surface data to TrackModel fields.  Falls back to sensible
    defaults for any fields that are None (< minimum laps).

    Returns
    -------
    TrackModel instance ready for ocp.solve_minimum_time().
    """
    try:
        from lap_oracle.config import TrackModel
    except ImportError:
        raise ImportError(
            "lap_oracle.config.TrackModel not available — "
            "CasADi solver bridge requires the lap_oracle package"
        )

    n = surface.frenet.n_points

    width_left = (
        surface.width_left if surface.width_left is not None
        else np.full(n, _DEFAULT_WIDTH_M)
    )
    width_right = (
        surface.width_right if surface.width_right is not None
        else np.full(n, _DEFAULT_WIDTH_M)
    )
    elevation = (
        surface.elevation_m if surface.elevation_m is not None
        else np.zeros(n)
    )
    banking = (
        surface.camber_rad if surface.camber_rad is not None
        else np.zeros(n)
    )

    # Grip: use centerline slice from 2D grip, or default ones
    if surface.grip_2d is not None:
        grip_map = surface.grip_2d.centerline_slice()
        # Resample to match centerline point count if needed
        if len(grip_map) != n:
            grip_map = np.interp(
                np.linspace(0, 1, n),
                np.linspace(0, 1, len(grip_map)),
                grip_map,
            )
    else:
        grip_map = np.ones(n)

    # NOTE: grip_map is the centerline (n=0) slice of the 2D grip surface.
    # The OCP solver now modulates this per-distance via `grip[i]` in its
    # friction constraint. Full 2D (lateral-varying) grip would require
    # the solver to look up mu(s, n) inside the NLP — currently not wired
    # because CasADi Opti can't call Python functions inside constraints.
    # The 1D centerline slice is a conservative approximation.

    # Vertical curvature: pass directly to the OCP solver.
    # The solver now uses g_eff = g + V[i]² × κ_v[i] in its friction
    # constraint, making grip truly speed-dependent per its own speed
    # variable.  No need to fold into grip_map as a static approximation.
    vert_curvature = np.zeros(n)
    if surface.vert_curvature_1pm is not None:
        kv = surface.vert_curvature_1pm
        if len(kv) != n:
            kv = np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(kv)), kv)
        vert_curvature = kv

    return TrackModel(
        name=surface.track_id,
        sim=surface.sim_sources[0] if surface.sim_sources else "",
        centerline_xy=surface.frenet.centerline_xy.copy(),
        width_left=width_left,
        width_right=width_right,
        curvature=surface.frenet.curvature_1pm.copy(),
        elevation=elevation,
        banking=banking,
        grip_map=grip_map,
        vert_curvature=vert_curvature,
        total_length_m=surface.frenet.total_length_m,
    )


def vehicle_model_to_params(vm) -> "VehicleParams":
    """Convert sim_optimizer VehicleModel to lap_oracle VehicleParams.

    Maps identified sub-models (tyre, aero, powertrain, brake, mass)
    to the VehicleParams dataclass used by the OCP solver.

    Parameters
    ----------
    vm : sim_optimizer.param_id.vehicle_model.VehicleModel

    Returns
    -------
    VehicleParams
    """
    try:
        from lap_oracle.config import VehicleParams, PacejkaParams
    except ImportError:
        raise ImportError("lap_oracle.config not available")

    # Mass
    mass_kg = vm.mass.total_mass_kg(fuel_level_l=0) if hasattr(vm, 'mass') else 1300.0

    # Aero
    cda = vm.aero.cda if hasattr(vm, 'aero') and hasattr(vm.aero, 'cda') else 0.8
    cla = vm.aero.cla if hasattr(vm, 'aero') and hasattr(vm.aero, 'cla') else 0.0

    # Power — estimate from powertrain model torque maps.
    # gear_torque_maps values are (rpm_array, torque_array) tuples.
    max_power_w = 400_000.0  # default GT car
    if hasattr(vm, 'powertrain') and hasattr(vm.powertrain, 'gear_torque_maps'):
        max_torques = []
        for gear, map_tuple in vm.powertrain.gear_torque_maps.items():
            if map_tuple is not None and len(map_tuple) == 2:
                rpm_arr, torque_arr = map_tuple
                # P = T * omega = T * RPM * 2*pi / 60
                power_arr = torque_arr * rpm_arr * 2 * 3.14159 / 60.0
                if len(power_arr) > 0:
                    max_torques.append(float(power_arr.max()))
        if max_torques:
            eff = getattr(vm.powertrain, 'transmission_efficiency', 0.9)
            max_power_w = max(max_torques) * eff

    # Braking
    max_brake_decel = 10.0
    if hasattr(vm, 'brake') and hasattr(vm.brake, 'max_decel_mps2'):
        max_brake_decel = vm.brake.max_decel_mps2

    # Tyre grip — extract peak mu from TyreModel fields
    mu_lat = 1.0
    mu_long = 1.0
    if hasattr(vm, 'tyre'):
        # TyreModel stores mu_lat / mu_long directly
        if hasattr(vm.tyre, 'mu_lat'):
            mu_lat = vm.tyre.mu_lat
        elif hasattr(vm, 'max_lateral_g'):
            # Estimate from the vehicle's max lateral G at a reference speed
            try:
                ay_max = vm.max_lateral_g(30.0)  # at 30 m/s
                mu_lat = ay_max / 9.80665
            except Exception:
                pass

        if hasattr(vm.tyre, 'mu_long'):
            mu_long = vm.tyre.mu_long
        else:
            mu_long = mu_lat * 0.95  # typical ratio

    tyre_lat = PacejkaParams(D=mu_lat)
    tyre_long = PacejkaParams(B=12.0, C=1.4, D=mu_long, E=-0.3)

    # Wheelbase — estimate from mass (karts are light)
    wheelbase_m = 2.65  # default
    if mass_kg < 250:
        wheelbase_m = 1.05  # kart

    return VehicleParams(
        mass_kg=mass_kg,
        wheelbase_m=wheelbase_m,
        cda=cda,
        cla=cla,
        max_power_w=max_power_w,
        max_brake_decel=max_brake_decel,
        tyre_lat=tyre_lat,
        tyre_long=tyre_long,
    )


def solve_optimal_line(
    surface: TrackSurface,
    vehicle_params=None,
    weather=None,
    n_points: int = 500,
    max_time_s: float = 120.0,
):
    """Compute the optimal racing line through the track surface.

    Bridges TrackSurface to the existing CasADi OCP solver, which
    already optimises N_lat (lateral offset) as a decision variable.

    Parameters
    ----------
    surface : TrackSurface with at least a centerline.
    vehicle_params : VehicleParams (from lap_oracle.config).
    weather : WeatherConditions (from lap_oracle.config), optional.
    n_points : discretisation points for the OCP solver.
    max_time_s : IPOPT time limit.

    Returns
    -------
    OCPSolution with lateral_offset_m, speed_mps, etc.

    Raises
    ------
    ImportError : if casadi or lap_oracle not available.
    """
    try:
        from lap_oracle.solver.ocp import solve_minimum_time
    except ImportError:
        raise ImportError(
            "CasADi OCP solver not available — "
            "install casadi and ensure lap_oracle.solver.ocp is importable"
        )

    track_model = surface_to_track_model(surface)

    return solve_minimum_time(
        track_model,
        vehicle_params,
        weather=weather,
        n_points=n_points,
        max_time_s=max_time_s,
    )


# ---------------------------------------------------------------------------
# Task 6: true-2D bridge + hard puddle corridor exclusions
# ---------------------------------------------------------------------------
_MIN_CORRIDOR_M = 0.5  # below this dry width on BOTH sides, skip the exclusion


def puddles_to_n_windows(
    puddles,
    grip_2d,
    width_left,
    width_right,
    s_grid,
    margin_m: float = 0.5,
):
    """Convert known puddle zones into hard corridor exclusions.

    For each puddle (disk of radius r at (s_c, n_c)): over the s-window
    [s_c - r - margin, s_c + r + margin], the allowed lateral corridor is
    the side of the puddle with MORE remaining track width:
      keep-left  -> (s0, s1, n_c + r + margin, +inf)
      keep-right -> (s0, s1, -inf, n_c - r - margin)
    Radius matches build_wet_mu_field's footprint via puddle_footprint_radius:
      r = max(sqrt(area_cells * cell_area / pi), n_step).
    Returns a list of (s_start, s_end, n_lo, n_hi) tuples (inf bounds mean
    'unconstrained on that side' — use float('inf')/-float('inf')).

    Side selection is deterministic: the available DRY width above the puddle
    is (mean width_left over the window) - (n_c + r + margin); below is
    (mean width_right over the window) + (n_c - r - margin) (width_right is a
    positive distance to the n<0 edge).  The wider side wins.  If BOTH sides
    leave less than ``_MIN_CORRIDOR_M`` of dry corridor, the window is skipped
    entirely and a warning logged — a puddle crossing beats an infeasible NLP.

    Conflict resolution (C1): puddles are processed deepest-first (by
    depth_score DESC; ties broken by (s_center, n_center) for determinism).
    Before appending, the candidate window is checked against all already-
    accepted windows for s-overlap with an OPPOSITE side (keep-left vs
    keep-right).  An OPPOSITE-side pair conflicts when the new keep-left n_lo
    exceeds an accepted keep-right n_hi (or vice versa) over the overlapping
    s-range — i.e. the intersection would be empty.  On conflict the SHALLOWER
    puddle's window (the one being evaluated, since we go deepest-first) is
    dropped with a warning; the deeper puddle's corridor survives.  This is
    the same degradation philosophy as the both-sides-narrow skip: a one-sided
    corridor from the deeper hazard beats an infeasible NLP.

    Note: s-windows do NOT wrap across start/finish; a puddle straddling s=0
    is handled one-sided (consistent with build_wet_mu_field); revisit if real
    data shows start/finish puddles.
    """
    if not puddles:
        return []

    s_grid = np.asarray(s_grid, dtype=np.float64)
    width_left = np.asarray(width_left, dtype=np.float64)
    width_right = np.asarray(width_right, dtype=np.float64)

    s_bins = np.asarray(grip_2d.s_bins, dtype=np.float64)
    n_bins = np.asarray(grip_2d.n_bins, dtype=np.float64)

    def _mean_over_window(arr: np.ndarray, s0: float, s1: float) -> float:
        """Mean of a per-s_grid array over [s0, s1] (interpolated)."""
        mask = (s_grid >= s0) & (s_grid <= s1)
        if np.any(mask):
            return float(np.mean(arr[mask]))
        # Window narrower than the s_grid spacing — interpolate at the centre.
        return float(np.interp((s0 + s1) / 2.0, s_grid, arr))

    # Deepest-first: deterministic tie-break by (s_center, n_center).
    sorted_puddles = sorted(
        puddles,
        key=lambda p: (-p.depth_score, p.s_center, p.n_center),
    )

    windows: list[tuple[float, float, float, float]] = []
    for p in sorted_puddles:
        r = puddle_footprint_radius(p, s_bins, n_bins)
        s0 = p.s_center - r - margin_m
        s1 = p.s_center + r + margin_m

        keep_left_lo = p.n_center + r + margin_m   # corridor ABOVE the puddle
        keep_right_hi = p.n_center - r - margin_m  # corridor BELOW the puddle

        mean_wl = _mean_over_window(width_left, s0, s1)
        mean_wr = _mean_over_window(width_right, s0, s1)

        # Remaining dry width on each side (positive = corridor exists).
        avail_above = mean_wl - keep_left_lo
        avail_below = keep_right_hi - (-mean_wr)  # = n_c - r - margin + mean_wr

        if avail_above < _MIN_CORRIDOR_M and avail_below < _MIN_CORRIDOR_M:
            logger.warning(
                "puddles_to_n_windows: puddle at s=%.1f n=%.2f (r=%.2f) leaves "
                "< %.2f m dry on both sides (above=%.2f, below=%.2f) — skipping "
                "exclusion (a puddle crossing beats an infeasible NLP)",
                p.s_center, p.n_center, r, _MIN_CORRIDOR_M, avail_above, avail_below,
            )
            continue

        is_keep_left = avail_above >= avail_below
        new_lo = keep_left_lo if is_keep_left else -float("inf")
        new_hi = float("inf") if is_keep_left else keep_right_hi

        # Conflict check (C1): scan accepted windows for s-overlap + opposite side.
        conflict = False
        for a_s0, a_s1, a_lo, a_hi in windows:
            # s-overlap?
            if a_s0 >= s1 or s0 >= a_s1:
                continue
            # Opposite sides? (one keep-left: n_hi==inf, other keep-right: n_lo==-inf)
            a_is_keep_left = (a_hi == float("inf"))
            if a_is_keep_left == is_keep_left:
                continue
            # Intersection over the s-overlap would be empty when:
            #   new keep-left n_lo > accepted keep-right n_hi, or
            #   accepted keep-left n_lo > new keep-right n_hi.
            if is_keep_left:
                # new = keep-left, accepted = keep-right
                if new_lo > a_hi:
                    conflict = True
                    break
            else:
                # new = keep-right, accepted = keep-left
                if a_lo > new_hi:
                    conflict = True
                    break

        if conflict:
            logger.warning(
                "puddles_to_n_windows: puddle at s=%.1f n=%.2f (depth=%.3f) "
                "conflicts with a deeper accepted window (opposite corridors, "
                "empty intersection) — dropping shallower puddle's window "
                "(a puddle crossing beats an infeasible NLP)",
                p.s_center, p.n_center, p.depth_score,
            )
            continue

        windows.append((s0, s1, new_lo, new_hi))

    return windows


def solve_optimal_line_2d(
    surface: TrackSurface,
    vehicle_params=None,
    weather=None,
    condition: str = "dry",
    puddles: list | None = None,
    n_points: int = 400,
    max_time_s: float = 120.0,
    envelope_caps: dict | None = None,
    force_no_geom: bool = False,
):
    """Compute the optimal racing line with the TRUE 2D grip field in the NLP.

    condition='dry' -> confidence-shrunk measured grip, single cold start.
    condition='wet' -> rubber-inverted grip; puddles become BOTH soft field
    penalties (mu=0.2 cells via build_wet_mu_field) AND hard corridor
    exclusions (puddles_to_n_windows), with multi-start (0, +2, -2).

    Warm-starts from the casadi-free QSS solve.

    Note: ``damp``/``heavy_wet`` from the store vocabulary must be bucketed
    to ``wet`` by the caller — this bridge uses a binary wet model
    (dry vs. wet), intentionally.

    envelope_caps: optional demonstrated longitudinal limits (from
    vehicle_profile.resolve_vehicle_params) — bounds drive/brake per speed;
    None uses the vehicle's power/brake scalars.

    force_no_geom: when True, skip quasi-3D geom_field construction entirely
    and solve with the legacy centerline-only geometry modifiers, even if
    surface.elevation_surface is present. For the A/B harness comparing
    quasi-3D against the 2D baseline on the same surface.

    Raises ValueError if surface.grip_2d is None (needs >= 10 laps),
    ImportError if casadi/lap_oracle unavailable.
    """
    if surface.grip_2d is None:
        raise ValueError(
            "solve_optimal_line_2d needs a 2D grip field (surface.grip_2d) — "
            f"got None (quality_tier={surface.quality_tier!r}, needs >= 10 laps "
            "for gold tier). Use solve_optimal_line for the 1D centerline-slice path."
        )
    if condition not in ("dry", "damp", "wet"):
        raise ValueError(
            f"condition must be 'dry', 'damp' or 'wet', got {condition!r}"
        )

    # Guard degenerate geometry: some tracks carry a valid 2D grip field but a
    # coincident / zero-length centerline (frenet has points yet ~0 m arc
    # length), which yields a 0 m TrackModel. Building the OCP on it makes the
    # curvature-rate constraint fabs(d2n) <= DKAPPA_MAX collapse to a constant,
    # tripping casadi's "you passed a constant to subject_to" assertion (a hard
    # crash, not a solve failure). Fail cleanly here so compute_racing_lines
    # records status=failed with a legible reason instead of raising an
    # unhandled RuntimeError. Real circuits are hundreds of metres.
    _MIN_TRACK_LENGTH_M = 50.0
    _tm_probe = surface_to_track_model(surface)
    if _tm_probe.total_length_m < _MIN_TRACK_LENGTH_M:
        raise ValueError(
            "degenerate track geometry: centerline length "
            f"{_tm_probe.total_length_m:.1f} m < {_MIN_TRACK_LENGTH_M:.0f} m minimum "
            f"(frenet has {surface.frenet.n_points} points but ~zero arc length) — "
            "cannot build a well-posed OCP"
        )

    try:
        from track_surface.mu_field import build_dry_mu_field, build_wet_mu_field
        from track_surface.spatial_to_grid import resample_spatial_to_grid
        from lap_oracle.solver.fallback_qss import solve_qss
        from lap_oracle.solver.ocp_2d_stitched import (
            solve_minimum_time_2d_stitched,
        )
    except ImportError as exc:
        raise ImportError(
            "2D OCP solver not available — install casadi and ensure "
            "lap_oracle.solver.ocp_2d / fallback_qss are importable "
            f"({exc})"
        ) from exc

    if vehicle_params is None:
        logger.warning(
            "solve_optimal_line_2d: no vehicle_params given — defaulting to a "
            "1300 kg GT car; pass real params for non-GT vehicles (e.g. karts)"
        )
        from lap_oracle.config import VehicleParams
        vehicle_params = VehicleParams()

    # The 2D grid stores ABSOLUTE road mu; the OCP multiplies tyre_lat.D * grip.
    # If D materially deviates from 1.0, grip is double-counted (D=1.5 * limit
    # 1.4 -> 2.1, dangerously optimistic). Warn; some callers may scale on purpose.
    try:
        tyre_d = float(vehicle_params.tyre_lat.D)
        if abs(tyre_d - 1.0) > 0.1:
            logger.warning(
                "solve_optimal_line_2d: tyre_lat.D=%.2f but the 2D grip grid "
                "already encodes absolute road friction — D should be ~1.0 to "
                "avoid double-counting grip.", tyre_d,
            )
    except (AttributeError, TypeError):
        pass

    track_model = surface_to_track_model(surface)

    # Casadi-free warm start: QSS speed profile (centerline line).
    warm = solve_qss(track_model, vehicle_params, weather)

    # Meteo spatial field for undriven-cell grip (None -> uniform; works for every track).
    # No surface carries a conditions modifier today (Part C attaches it); the getattr
    # chain keeps this None-safe and activates automatically when present.
    spatial = None
    cond = getattr(surface, "conditions", None) or getattr(surface, "weather_condition", None)
    modifier = getattr(cond, "spatial_modifier", None) if cond is not None else None
    if modifier is not None and surface.grip_2d is not None:
        spatial = resample_spatial_to_grid(modifier, surface.grip_2d.s_bins, surface.grip_2d.n_bins)

    # Elevation terms for the friction ellipse (None when absent -> no effect).
    # grade: radians from slope %. camber: banking MAGNITUDE (the solver's
    # ay_lim boost uses |camber|; pass abs of the signed camber_rad).
    grade_s = None
    if surface.slope_pct is not None:
        grade_s = np.arctan(np.asarray(surface.slope_pct, dtype=float) / 100.0)
    camber_s = None
    if surface.camber_rad is not None:
        camber_s = np.abs(np.asarray(surface.camber_rad, dtype=float))

    # Quasi-3D geometry field: (s, n) kv/camber/grade grids built from the
    # surface's accumulated elevation data (build_geom_field, Task 1), so the
    # stitched solver samples geometry at the LINE's actual lateral position
    # instead of only the frozen centerline (grade_s/camber_s above).
    # getattr-safe: elevation_surface may be absent entirely on older/stub
    # surfaces, not just None. force_no_geom short-circuits construction for
    # the A/B harness's forced-2D baseline. None either way is safe — the
    # stitched solver's geom_field=None path is byte-compatible with the
    # pre-quasi-3D solve.
    if force_no_geom:
        geom_field = None
        logger.info(
            "solve_optimal_line_2d: forced-2D — geom_field construction "
            "skipped (force_no_geom=True); centerline geometry modifiers"
        )
    else:
        geom_field = build_geom_field(getattr(surface, "elevation_surface", None))
        if geom_field is not None:
            logger.info(
                "solve_optimal_line_2d: quasi-3D geometry field active (%dx%d)",
                geom_field.kv_grid.shape[0], geom_field.kv_grid.shape[1],
            )
        else:
            logger.info(
                "solve_optimal_line_2d: no elevation surface — centerline "
                "geometry modifiers"
            )

    if condition in ("dry", "damp"):
        # 'damp' is a real tier, not a wet alias: the caller loads the measured
        # damp-session grip sidecar and we solve it exactly like dry — real
        # measured grip, no rubber-line inversion, no model. (Wet, by contrast,
        # is derived from the dry sidecar because prod rarely has wet laps.)
        mu_field = build_dry_mu_field(surface.grip_2d, spatial=spatial)
    else:  # wet
        # Puddles enter as SOFT mu=0.2 penalties inside build_wet_mu_field. The
        # old single-shot path ALSO excluded puddle cells with hard n_windows
        # corridors + a full-width multi-start sweep; the stitched solver takes
        # neither, so wet puddle avoidance is soft-only here. Revisit if the
        # spec's zero-puddle-crossing gate (§4 gate 3) needs hard in-sector
        # exclusion — that would be a stitched-solver extension.
        puddle_list = puddles or []
        mu_field = build_wet_mu_field(surface.grip_2d, puddle_list)

    # Stitched sub-sector solver: ~8-9x faster than the single-shot full-lap
    # NLP AND reaches `optimal` within the Celery time budget, where the
    # single-shot hit the CPU cap and returned suboptimal (measured on a 758 m
    # track: 1595 s/suboptimal -> ~185 s/optimal). Sector decomposition also
    # subsumes the single-shot's multi-start local-minimum escape.
    return solve_minimum_time_2d_stitched(
        track_model,
        vehicle_params,
        mu_field,
        weather=weather,
        n_points=n_points,
        max_time_s=max_time_s,
        warm_start=warm,
        envelope_caps=envelope_caps,
        grade_s=grade_s,
        camber_s=camber_s,
        geom_field=geom_field,
    )
