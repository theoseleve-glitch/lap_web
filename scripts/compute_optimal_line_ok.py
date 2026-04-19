"""Run OCP solver on Ouest Karting data to compute theoretical optimal line."""
import sys
import json
sys.path.insert(0, 'telemetry_tool')

import numpy as np


def min_curvature_warm_start(curvature, width_left, width_right, alpha=3.0):
    """Initial N_lat guess: shift toward inside of each corner.

    Frenet convention: normal points LEFT, positive n_offset = left of centerline.
    Left turn (curvature > 0) -> inside is LEFT -> positive n_offset.
    Right turn (curvature < 0) -> inside is RIGHT -> negative n_offset.
    """
    max_left = width_left * 0.8
    max_right = width_right * 0.8
    n_init = np.sign(curvature) * np.minimum(
        np.abs(curvature) * alpha,
        np.minimum(max_left, max_right),
    )
    return np.clip(n_init, -max_right, max_left)


def validate_optimal_line(driver_xy, optimal_xy):
    """Check if OCP optimal line is meaningfully different from driver's line."""
    t_d = np.linspace(0, 1, len(driver_xy))
    t_o = np.linspace(0, 1, len(optimal_xy))
    t = np.linspace(0, 1, min(len(driver_xy), len(optimal_xy)))
    dx_d = np.interp(t, t_d, driver_xy[:, 0])
    dy_d = np.interp(t, t_d, driver_xy[:, 1])
    dx_o = np.interp(t, t_o, optimal_xy[:, 0])
    dy_o = np.interp(t, t_o, optimal_xy[:, 1])
    dist = np.sqrt((dx_d - dx_o) ** 2 + (dy_d - dy_o) ** 2)
    mean_sep = float(dist.mean())
    max_sep = float(dist.max())
    warnings_ = []
    if mean_sep < 2.0:
        warnings_.append(f'Mean sep {mean_sep:.2f}m < 2.0m - optimal barely distinct')
    if max_sep < 5.0:
        warnings_.append(f'Max sep {max_sep:.2f}m < 5.0m - corridor not explored')
    return {'mean_sep': mean_sep, 'max_sep': max_sep, 'warnings': warnings_}

# Load existing OK data
with open('track-surface-ok-data.json') as f:
    d = json.load(f)

# Build a TrackModel directly from the JSON
from lap_oracle.config import TrackModel, VehicleParams, PacejkaParams

t = d['track']
cx = np.array(t['centerline_x'], dtype=np.float64)
cy = np.array(t['centerline_y'], dtype=np.float64)
curvature = np.array(t['curvature'], dtype=np.float64)
width_left = np.array(d['boundaries']['width_left'], dtype=np.float64)
width_right = np.array(d['boundaries']['width_right'], dtype=np.float64)
elevation = np.array(d['elevation']['values'], dtype=np.float64)
grip = np.array(d['grip_map'], dtype=np.float64)

print(f'Track: {t["name"]}')
print(f'  Length: {t["length_m"]}m')
print(f'  Points: {len(cx)}')
print(f'  Curvature range: {curvature.min():.4f} to {curvature.max():.4f} 1/m')
print(f'  Width: {width_left.min():.1f}-{width_left.max():.1f}m (per side)')
print(f'  Grip: {grip.min():.3f}-{grip.max():.3f} (mean {grip.mean():.3f})')

track_model = TrackModel(
    name='Ouest Karting',
    sim='racechrono',
    centerline_xy=np.column_stack([cx, cy]),
    width_left=width_left,
    width_right=width_right,
    curvature=curvature,
    elevation=elevation,
    banking=np.zeros(len(cx)),
    grip_map=grip,
    vert_curvature=np.zeros(len(cx)),
    total_length_m=float(t['length_m']),
    sector_boundaries=[],
)

# Kart vehicle params
vehicle = VehicleParams(
    sim='racechrono',
    car_name='Kart',
    mass_kg=180.0,
    wheelbase_m=1.05,
    cda=0.5,
    cla=0.0,
    max_power_w=20000.0,
    max_brake_decel=8.0,
    tyre_lat=PacejkaParams(B=12.0, C=1.5, D=1.15, E=-0.3),
    tyre_long=PacejkaParams(B=12.0, C=1.4, D=1.0, E=-0.3),
)

print(f'\nVehicle: kart, {vehicle.mass_kg}kg, {vehicle.max_power_w/1000:.0f}kW')

# Compute warm start from min-curvature heuristic
warm_nlat = min_curvature_warm_start(
    curvature=track_model.curvature,
    width_left=track_model.width_left,
    width_right=track_model.width_right,
    alpha=3.0,
)
print(f'\nWarm start N_lat: [{warm_nlat.min():.2f}, {warm_nlat.max():.2f}]')

# Monkey-patch the solver's internal _solve_casadi to use the warm start.
# We reimplement it here with the warm-start injection.
import lap_oracle.solver.ocp as _ocp_mod
import casadi as ca
from lap_oracle.track.model import resample_track
from lap_oracle.physics.bicycle_model import corner_speed

_G_CONST = 9.80665
_RHO = 1.225


def _patched_solve_casadi(track, veh, weather, n_points, max_time_s):
    import time as _time
    t0_p = _time.perf_counter()

    ds_target = track.total_length_m / n_points
    tk = resample_track(track, ds_target=ds_target)
    N = tk.n_points
    ds = tk.ds.astype(np.float64)
    kappa_signed = tk.curvature.astype(np.float64)  # KEEP SIGN for curvature correction
    kappa = np.abs(kappa_signed)

    kv = np.zeros(N, dtype=np.float64)
    if hasattr(track, "vert_curvature") and track.vert_curvature is not None:
        src = np.asarray(track.vert_curvature, dtype=np.float64)
        if len(src) == N:
            kv = src
        elif len(src) > 0:
            kv = np.interp(np.linspace(0, 1, N), np.linspace(0, 1, len(src)), src)

    grip = np.ones(N, dtype=np.float64)
    if hasattr(tk, "grip_map") and tk.grip_map is not None and len(tk.grip_map) == N:
        grip = np.clip(tk.grip_map.astype(np.float64), 0.3, 3.0)
    elif hasattr(track, "grip_map") and track.grip_map is not None and len(track.grip_map) > 0:
        grip = np.interp(np.linspace(0, 1, N), np.linspace(0, 1, len(track.grip_map)), track.grip_map)
        grip = np.clip(grip, 0.3, 3.0)

    m_veh = veh.mass_kg
    cda_veh = veh.cda
    cla_veh = veh.cla
    p_max = veh.max_power_w
    a_brake_max = veh.max_brake_decel
    mu_lat = veh.tyre_lat.D * weather.grip_multiplier
    mu_long = veh.tyre_long.D * weather.grip_multiplier

    v_guess = corner_speed(kappa, veh) * weather.grip_multiplier
    v_guess = np.clip(v_guess, 10.0, 100.0)

    # WARM START: interpolate warm_nlat to the solver's N points
    nlat_init = np.interp(
        np.linspace(0, 1, N),
        np.linspace(0, 1, len(warm_nlat)),
        warm_nlat,
    )

    opti = ca.Opti()
    V = opti.variable(N)
    Nlat = opti.variable(N)
    Ax = opti.variable(N - 1)

    opti.set_initial(V, v_guess)
    opti.set_initial(Nlat, nlat_init)  # WARM START instead of zeros
    opti.set_initial(Ax, np.zeros(N - 1))

    total_time = 0
    for i in range(N - 1):
        v_avg = (V[i] + V[i + 1]) / 2.0
        total_time = total_time + ds[i] / v_avg
    opti.minimize(total_time)

    for i in range(N - 1):
        opti.subject_to(V[i + 1] ** 2 == V[i] ** 2 + 2 * Ax[i] * ds[i])
        kappa_i = kappa[i]
        denom_i = 1.0 - Nlat[i] * kappa_i
        denom_i = ca.fmax(denom_i, 0.1)
        kappa_actual_i = kappa_i / denom_i
        ay_i = V[i] ** 2 * kappa_actual_i
        g_eff_i = _G_CONST + V[i] ** 2 * kv[i]
        g_eff_i = ca.fmax(g_eff_i, 1.0)
        fz_aero = 0.5 * _RHO * cla_veh * V[i] ** 2
        fz_total = m_veh * g_eff_i + fz_aero
        mu_lat_i = mu_lat * grip[i]
        mu_long_i = mu_long * grip[i]
        ax_lim = mu_long_i * fz_total / m_veh
        ay_lim = mu_lat_i * fz_total / m_veh
        opti.subject_to((Ax[i] / ax_lim) ** 2 + (ay_i / ay_lim) ** 2 <= 1.0)
        drag = 0.5 * _RHO * cda_veh * V[i] ** 2 / m_veh
        rr = 0.01 * g_eff_i
        v_safe = ca.fmax(V[i], 5.0)
        opti.subject_to(Ax[i] <= p_max / (m_veh * v_safe) - drag - rr)
        opti.subject_to(Ax[i] >= -(a_brake_max * g_eff_i / _G_CONST + drag + rr))

    opti.subject_to(opti.bounded(5.0, V, 120.0))
    for i in range(N):
        w_left = float(tk.width_left[i]) * 0.9
        w_right = float(tk.width_right[i]) * 0.9
        opti.subject_to(opti.bounded(-w_right, Nlat[i], w_left))
    opti.subject_to(V[0] == V[N - 1])
    opti.subject_to(Nlat[0] == Nlat[N - 1])

    opts = {
        "ipopt.max_iter": 3000,
        "ipopt.max_cpu_time": max_time_s,
        "ipopt.print_level": 0,
        "ipopt.sb": "yes",
        "print_time": 0,
    }
    opti.solver("ipopt", opts)

    status = "optimal"
    try:
        sol_i = opti.solve()
        v_sol = np.array(sol_i.value(V)).flatten()
        n_lat_sol = np.array(sol_i.value(Nlat)).flatten()
        ax_sol = np.array(sol_i.value(Ax)).flatten()
    except RuntimeError:
        status = "suboptimal"
        v_sol = np.array(opti.debug.value(V)).flatten()
        n_lat_sol = np.array(opti.debug.value(Nlat)).flatten()
        ax_sol = np.array(opti.debug.value(Ax)).flatten()
        v_sol = np.clip(v_sol, 5.0, 120.0)

    elapsed = _time.perf_counter() - t0_p
    return _ocp_mod._build_solution(
        track, veh, weather, tk, v_sol, n_lat_sol, ax_sol,
        ds, status, elapsed,
    )


_ocp_mod._solve_casadi = _patched_solve_casadi

print(f'\nRunning CasADi OCP solver (with warm start)...')

from lap_oracle.solver.ocp import solve_minimum_time
import time
t0 = time.time()
sol = solve_minimum_time(track_model, vehicle, n_points=150, max_time_s=60.0)
print(f'Solved in {time.time()-t0:.1f}s')
print(f'  Status: {sol.solver_status}')
print(f'  Optimal lap time: {sol.optimal_lap_time_s:.3f}s')
print(f'  Lateral offset range: {sol.lateral_offset_m.min():.2f} to {sol.lateral_offset_m.max():.2f}m')
print(f'  Speed range: {sol.speed_mps.min()*3.6:.0f} to {sol.speed_mps.max()*3.6:.0f} kph')

# Convert lateral offset + centerline to world (x, y)
# We need heading at each point to compute normal direction
n = len(sol.distance_m)
# Interpolate centerline + heading to the solver's distance grid
s_centerline = np.linspace(0, track_model.total_length_m, len(cx))
# Smooth centerline-relative frame
dx_c = np.gradient(cx)
dy_c = np.gradient(cy)
heading_c = np.arctan2(dy_c, dx_c)

# Interpolate to solver points (the solver used a different grid)
cx_sol = np.interp(sol.distance_m, s_centerline, cx)
cy_sol = np.interp(sol.distance_m, s_centerline, cy)
heading_sol = np.interp(sol.distance_m, s_centerline, np.unwrap(heading_c))

# Normal (perpendicular to heading, pointing left = positive offset)
nx = -np.sin(heading_sol)
ny = np.cos(heading_sol)

optimal_x = cx_sol + nx * sol.lateral_offset_m
optimal_y = cy_sol + ny * sol.lateral_offset_m

# Validate the optimal line is meaningfully different from driver
driver_best = d['drivers']['hamilton']
bx = np.array(driver_best['x'])
by = np.array(driver_best['y'])
best_time = driver_best['lap_time']

driver_xy = np.column_stack([bx, by])
optimal_xy = np.column_stack([optimal_x, optimal_y])
val = validate_optimal_line(driver_xy, optimal_xy)
print(f'\nValidation:')
print(f'  Mean separation: {val["mean_sep"]:.2f}m')
print(f'  Max separation:  {val["max_sep"]:.2f}m')
for w in val['warnings']:
    print(f'  WARNING: {w}')
if val['mean_sep'] >= 2.0 and val['max_sep'] >= 5.0:
    print('  PASSED: optimal line is meaningfully different')
else:
    print('  FAILED: optimal line does not meet thresholds')

# Find nearest optimal point for each driver point
driver_to_opt_dist = []
for i in range(len(bx)):
    dxa = optimal_x - bx[i]
    dya = optimal_y - by[i]
    driver_to_opt_dist.append(float(np.sqrt((dxa*dxa + dya*dya).min())))
driver_to_opt_dist = np.array(driver_to_opt_dist)
print(f'\nDriver best vs OCP optimal:')
print(f'  Mean separation: {driver_to_opt_dist.mean():.2f}m')
print(f'  Max separation: {driver_to_opt_dist.max():.2f}m')
print(f'  Time gap: driver {best_time:.2f}s - optimal {sol.optimal_lap_time_s:.2f}s = {best_time - sol.optimal_lap_time_s:.2f}s gain')

# Build the optimal driver trace for the visualizer
# Interpolate throttle, brake, steering onto our standard output shape
optimal_driver = {
    'x': [round(float(v), 2) for v in optimal_x],
    'y': [round(float(v), 2) for v in optimal_y],
    'z': [0.0] * n,
    'speed_kph': [round(float(v*3.6), 1) for v in sol.speed_mps],
    'throttle': [round(float(v*100), 0) for v in sol.throttle],
    'n_offset': [round(float(v), 2) for v in sol.lateral_offset_m],
    'grip_mu': [round(float(g), 3) for g in np.interp(sol.distance_m, s_centerline, grip)],
    'lap_time': round(float(sol.optimal_lap_time_s), 3),
    'src': 'OCP_optimal',
}

# Update the data file with the optimal as "median" (so the viz compares best vs optimal)
d['drivers']['verstappen'] = optimal_driver
d['stats']['theoretical_lap_s'] = round(float(sol.optimal_lap_time_s), 3)
d['stats']['time_gain_s'] = round(best_time - float(sol.optimal_lap_time_s), 2)

with open('track-surface-ok-data.json', 'w') as f:
    json.dump(d, f)

print('\nUpdated track-surface-ok-data.json with OCP optimal line')
