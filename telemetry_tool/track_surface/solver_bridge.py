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
    Radius matches build_wet_mu_field's footprint:
      r = max(sqrt(area_cells * cell_area / pi), n_step).
    Returns a list of (s_start, s_end, n_lo, n_hi) tuples (inf bounds mean
    'unconstrained on that side' — use float('inf')/-float('inf')).

    Side selection is deterministic: the available DRY width above the puddle
    is (mean width_left over the window) - (n_c + r + margin); below is
    (mean width_right over the window) + (n_c - r - margin) (width_right is a
    positive distance to the n<0 edge).  The wider side wins.  If BOTH sides
    leave less than ``_MIN_CORRIDOR_M`` of dry corridor, the window is skipped
    entirely and a warning logged — a puddle crossing beats an infeasible NLP.
    """
    if not puddles:
        return []

    s_grid = np.asarray(s_grid, dtype=np.float64)
    width_left = np.asarray(width_left, dtype=np.float64)
    width_right = np.asarray(width_right, dtype=np.float64)

    # Footprint geometry — identical contract to build_wet_mu_field.
    s_bins = np.asarray(grip_2d.s_bins, dtype=np.float64)
    n_bins = np.asarray(grip_2d.n_bins, dtype=np.float64)
    s_step = float(np.median(np.diff(s_bins))) if len(s_bins) > 1 else 5.0
    n_step = float(np.median(np.diff(n_bins))) if len(n_bins) > 1 else 1.0
    cell_area = s_step * n_step

    def _mean_over_window(arr: np.ndarray, s0: float, s1: float) -> float:
        """Mean of a per-s_grid array over [s0, s1] (interpolated)."""
        mask = (s_grid >= s0) & (s_grid <= s1)
        if np.any(mask):
            return float(np.mean(arr[mask]))
        # Window narrower than the s_grid spacing — interpolate at the centre.
        return float(np.interp((s0 + s1) / 2.0, s_grid, arr))

    windows: list[tuple[float, float, float, float]] = []
    for p in puddles:
        r = max(np.sqrt(p.area_cells * cell_area / np.pi), n_step)
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

        if avail_above >= avail_below:
            windows.append((s0, s1, keep_left_lo, float("inf")))   # keep-left
        else:
            windows.append((s0, s1, -float("inf"), keep_right_hi))  # keep-right

    return windows


def solve_optimal_line_2d(
    surface: TrackSurface,
    vehicle_params=None,
    weather=None,
    condition: str = "dry",
    puddles: list | None = None,
    n_points: int = 400,
    max_time_s: float = 120.0,
):
    """Compute the optimal racing line with the TRUE 2D grip field in the NLP.

    condition='dry' -> confidence-shrunk measured grip, single cold start.
    condition='wet' -> rubber-inverted grip; puddles become BOTH soft field
    penalties (mu=0.2 cells via build_wet_mu_field) AND hard corridor
    exclusions (puddles_to_n_windows), with multi-start (0, +2, -2).

    Warm-starts from the casadi-free QSS solve.

    Raises ValueError if surface.grip_2d is None (needs >= 10 laps),
    ImportError if casadi/lap_oracle unavailable.
    """
    if surface.grip_2d is None:
        raise ValueError(
            "solve_optimal_line_2d needs a 2D grip field (surface.grip_2d) — "
            f"got None (quality_tier={surface.quality_tier!r}, needs >= 10 laps "
            "for gold tier). Use solve_optimal_line for the 1D centerline-slice path."
        )
    if condition not in ("dry", "wet"):
        raise ValueError(f"condition must be 'dry' or 'wet', got {condition!r}")

    try:
        from track_surface.mu_field import build_dry_mu_field, build_wet_mu_field
        from lap_oracle.solver.fallback_qss import solve_qss
        from lap_oracle.solver.ocp_2d import solve_minimum_time_2d
    except ImportError as exc:
        raise ImportError(
            "2D OCP solver not available — install casadi and ensure "
            "lap_oracle.solver.ocp_2d / fallback_qss are importable "
            f"({exc})"
        ) from exc

    if vehicle_params is None:
        from lap_oracle.config import VehicleParams
        vehicle_params = VehicleParams()

    track_model = surface_to_track_model(surface)

    # Casadi-free warm start: QSS speed profile (centerline line).
    warm = solve_qss(track_model, vehicle_params, weather)

    if condition == "dry":
        mu_field = build_dry_mu_field(surface.grip_2d)
        n_lat_starts = (0.0,)
        n_windows: list = []
    else:  # wet
        puddle_list = puddles or []
        mu_field = build_wet_mu_field(surface.grip_2d, puddle_list)
        n_lat_starts = (0.0, 2.0, -2.0)
        n = surface.frenet.n_points
        wl = surface.width_left if surface.width_left is not None else np.full(n, 3.0)
        wr = surface.width_right if surface.width_right is not None else np.full(n, 3.0)
        n_windows = puddles_to_n_windows(
            puddle_list, surface.grip_2d, wl, wr, surface.frenet.s_grid,
        )

    return solve_minimum_time_2d(
        track_model,
        vehicle_params,
        mu_field,
        weather=weather,
        n_points=n_points,
        max_time_s=max_time_s,
        warm_start=warm,
        n_lat_starts=n_lat_starts,
        n_windows=n_windows,
    )
