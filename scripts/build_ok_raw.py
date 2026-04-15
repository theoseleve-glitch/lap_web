"""Build Ouest Karting track from RAW GPS — bypasses pipeline entirely.

Bronze = 1D observed demand. Silver = 2D observed demand.
Optional: road-attitude correction (gravity removal) on per-sample basis where
mount + attitude estimates are confident. This is a demand-cleaning step, not
a friction estimate. The bronze/silver tier semantics are unchanged.
"""
import sys
import os
import numpy as np
import json
from scipy.signal import savgol_filter

# Wire telemetry_tool/ onto sys.path so we can import the attitude correction
# helper that lives next to phone_mount_estimator/road_attitude_estimator.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TELEMETRY_PKG = os.path.join(_REPO_ROOT, 'telemetry_tool')
if _TELEMETRY_PKG not in sys.path:
    sys.path.insert(0, _TELEMETRY_PKG)

from phone_mount_estimator import estimate_phone_mount  # noqa: E402
from track_surface.attitude_correction import (         # noqa: E402
    MIN_ATTITUDE_QUALITY_FOR_CORRECTION,
    apply_attitude_correction,
    merge_session_diagnostics,
)

_G = 9.80665

# RaceChrono CSV column indices (verified against actual data file headers).
# Channel order: Bearing(9), Speed*calc(18), Lateral G *calc(19), Longitudinal G *calc(20),
# Accel-X(24), Accel-Y(25), Accel-Z(26), Gyro-X(32), Gyro-Y(33), Gyro-Z(34).
_COL_BEARING = 9
_COL_LONG_G_CALC = 20
_COL_ACCEL_X = 24
_COL_ACCEL_Y = 25
_COL_ACCEL_Z = 26
_COL_GYRO_X = 32
_COL_GYRO_Y = 33
_COL_GYRO_Z = 34


def savgol_smooth(arr, window=11, polyorder=3):
    n = len(arr)
    if n < window:
        return arr.copy()
    if window % 2 == 0:
        window += 1
    pad = window
    ext = np.concatenate([arr[-pad:], arr, arr[:pad]])
    sm = savgol_filter(ext, window, polyorder)
    return sm[pad:pad + n]


# Read ALL raw GPS from all 5 sessions
all_laps = []
FILES = [
    'data/raw/OK_FP+Q.csv',
    'data/raw/OK_R1.csv',
    'data/raw/OK_R2.csv',
    'data/raw/OK_R3.csv',
    'data/raw/OK_R4.csv',
]

def _safe_float(parts, idx, default=np.nan):
    """Pull a float at column idx, tolerating short rows / blank cells."""
    if len(parts) <= idx:
        return default
    cell = parts[idx].strip()
    if not cell:
        return default
    try:
        return float(cell)
    except ValueError:
        return default


for f_name in FILES:
    print(f'Reading {f_name.split("/")[-1]}...')
    rows_by_lap = {}
    with open(f_name, 'r', encoding='latin-1') as f:
        for line in f:
            if not line.startswith('17'):
                continue
            parts = line.split(',')
            try:
                lap_str = parts[2].strip()
                if not lap_str:
                    continue
                lap_num = int(lap_str)
                lat = float(parts[12])
                lon = float(parts[13])
                spd = float(parts[7])
                t = float(parts[0])
                alat_g = float(parts[19]) if len(parts) > 19 else 0.0
                alt = float(parts[8]) if len(parts) > 8 else 0.0
                # Extra channels for attitude correction (NaN if column absent).
                bearing_deg = _safe_float(parts, _COL_BEARING)
                along_g_calc = _safe_float(parts, _COL_LONG_G_CALC)
                ax = _safe_float(parts, _COL_ACCEL_X)
                ay = _safe_float(parts, _COL_ACCEL_Y)
                az = _safe_float(parts, _COL_ACCEL_Z)
                gx = _safe_float(parts, _COL_GYRO_X)
                gy = _safe_float(parts, _COL_GYRO_Y)
                gz = _safe_float(parts, _COL_GYRO_Z)
                if abs(lat) < 1 or spd < 1:
                    continue
                if lap_num not in rows_by_lap:
                    rows_by_lap[lap_num] = []
                rows_by_lap[lap_num].append((
                    t, lat, lon, spd, alat_g, alt,
                    bearing_deg, along_g_calc, ax, ay, az, gx, gy, gz,
                ))
            except (ValueError, IndexError):
                pass

    for lap_num, rows in sorted(rows_by_lap.items()):
        if len(rows) < 200:
            continue
        rows.sort(key=lambda r: r[0])
        t_arr = np.array([r[0] for r in rows])
        lap_time = t_arr[-1] - t_arr[0]
        if lap_time < 30 or lap_time > 120:
            continue

        # Build IMU 3D arrays only if every component is finite for >50% of the lap.
        accel_3d = np.column_stack([
            [r[8] for r in rows],   # ax
            [r[9] for r in rows],   # ay
            [r[10] for r in rows],  # az
        ])
        gyro_3d = np.column_stack([
            [r[11] for r in rows],  # gx
            [r[12] for r in rows],  # gy
            [r[13] for r in rows],  # gz
        ])
        bearing_arr = np.array([r[6] for r in rows])
        along_g_calc_arr = np.array([r[7] for r in rows])

        # Drop IMU/bearing if the column is mostly missing.
        accel_finite_frac = np.isfinite(accel_3d).all(axis=1).mean()
        gyro_finite_frac = np.isfinite(gyro_3d).all(axis=1).mean()
        has_imu = accel_finite_frac > 0.5 and gyro_finite_frac > 0.5
        has_bearing = np.isfinite(bearing_arr).mean() > 0.5
        has_along = np.isfinite(along_g_calc_arr).mean() > 0.5

        all_laps.append({
            'lat': np.array([r[1] for r in rows]),
            'lon': np.array([r[2] for r in rows]),
            'speed': np.array([r[3] for r in rows]),
            'alat_g': np.array([r[4] for r in rows]),
            'alt': np.array([r[5] for r in rows]),
            'time': lap_time,
            'time_arr': t_arr,
            'src': f_name.split('/')[-1].split('.')[0],
            'accel_3d': accel_3d if has_imu else None,
            'gyro_3d': gyro_3d if has_imu else None,
            'bearing_deg': bearing_arr if has_bearing else None,
            'along_g_calc': along_g_calc_arr if has_along else None,
        })

print(f'\nTotal valid laps: {len(all_laps)}')

# ═══════════════════════════════════════════════════════════════════
# Per-session phone-mount calibration
# ═══════════════════════════════════════════════════════════════════
# The phone mount is a session-scoped property: it's calibrated once on the
# longest available lap (most data, cleanest gravity estimate) and then
# reused for every lap in that session. Computing per-lap would over-fit to
# transient corner conditions.
session_mounts: dict[str, object] = {}
for src in sorted({lap['src'] for lap in all_laps}):
    src_laps = [lap for lap in all_laps if lap['src'] == src and lap.get('accel_3d') is not None]
    if not src_laps:
        session_mounts[src] = None
        print(f'  {src}: no IMU data — attitude correction disabled')
        continue
    cal_lap = max(src_laps, key=lambda lap: len(lap['time_arr']))
    try:
        mount = estimate_phone_mount(
            cal_lap['accel_3d'], cal_lap['gyro_3d'],
            cal_lap['speed'], cal_lap['time_arr'],
        )
        session_mounts[src] = mount
        print(
            f'  {src}: mount calibrated on {len(cal_lap["time_arr"])} samples — '
            f'orientation_quality={mount.orientation_quality:.2f}, '
            f'mount_unstable={mount.mount_unstable}'
        )
    except Exception as exc:
        session_mounts[src] = None
        print(f'  {src}: mount calibration failed ({exc}) — attitude correction disabled')

# Per-lap diagnostics accumulator (filled in the main demand loop below).
per_lap_attitude_diagnostics: list[dict] = []

# Global reference
all_lat = np.concatenate([l['lat'] for l in all_laps])
all_lon = np.concatenate([l['lon'] for l in all_laps])
lat0 = float(np.mean(all_lat))
lon0 = float(np.mean(all_lon))
cos_lat = np.cos(np.radians(lat0))


def to_xy(lat_arr, lon_arr):
    return ((lon_arr - lon0) * cos_lat * 111320,
            (lat_arr - lat0) * 111320)


# Best lap
best_idx = min(range(len(all_laps)), key=lambda i: all_laps[i]['time'])
best = all_laps[best_idx]
print(f'Best: {best["time"]:.3f}s from {best["src"]}')

# Centerline = best lap raw GPS, smoothed
bx, by = to_xy(best['lat'], best['lon'])
bx = savgol_smooth(bx, window=25, polyorder=3)
by = savgol_smooth(by, window=25, polyorder=3)

# Arc-length distance from GPS positions
dx_b = np.diff(bx)
dy_b = np.diff(by)
ds_b = np.sqrt(dx_b ** 2 + dy_b ** 2)
cumul_dist = np.concatenate([[0], np.cumsum(ds_b)])
track_length = float(cumul_dist[-1])
print(f'Track length: {track_length:.0f}m')

# Uniform s-grid
n_bins = 600
s_grid = np.linspace(0, track_length, n_bins)
center_x = np.interp(s_grid, cumul_dist, bx)
center_y = np.interp(s_grid, cumul_dist, by)

# Heading + curvature
dx_c = np.gradient(center_x)
dy_c = np.gradient(center_y)
heading = np.arctan2(dy_c, dx_c)
heading_unwrapped = np.unwrap(heading)
ds_arr = np.sqrt(np.diff(center_x) ** 2 + np.diff(center_y) ** 2)
ds_arr = np.append(ds_arr, ds_arr[-1])
curvature = np.gradient(heading_unwrapped) / np.maximum(ds_arr, 0.01)
curvature = savgol_smooth(curvature, window=11, polyorder=3)
curvature = np.clip(curvature, -0.35, 0.35)

# Normal direction
mag_c = np.sqrt(dx_c ** 2 + dy_c ** 2)
mag_c[mag_c < 1e-9] = 1e-9
nx_c = -dy_c / mag_c
ny_c = dx_c / mag_c

# ═══════════════════════════════════════════════════════════════════
# LATERAL DEMAND MAP (not "grip" — observed demand, not surface friction)
#
# Fixes applied:
#   1. Excitation gate: only near-limit samples update the ceiling
#   2. Centripetal cross-check: flag samples where IMU disagrees with v²κ
#   3. Bank/grade correction: remove gravity contamination from a_lat
#   4. Confidence: per-bin quality metric from sample count + excitation
# ═══════════════════════════════════════════════════════════════════

# Absolute curvature at each s-bin for centripetal computation
kappa_abs = np.abs(curvature)

# Grade (longitudinal slope) from elevation for bank estimation later
ds_m_local = track_length / n_bins

# Per-bin accumulators
left_off = [[] for _ in range(n_bins)]
right_off = [[] for _ in range(n_bins)]
demand_samp = [[] for _ in range(n_bins)]          # replaces grip_samp
demand_excited = [[] for _ in range(n_bins)]        # only near-limit samples
centripetal_ratio = [[] for _ in range(n_bins)]     # a_measured / a_centripetal
elev_samp = [[] for _ in range(n_bins)]
combined_demand = [[] for _ in range(n_bins)]       # sqrt(a_lat² + a_lon²)

# First pass: compute per-session excitation threshold (p70 of |a_lat|)
session_thresholds = {}
for lap in all_laps:
    src = lap['src']
    if src not in session_thresholds:
        all_alat_session = []
        for other in all_laps:
            if other['src'] == src:
                all_alat_session.extend(np.abs(other['alat_g'][other['speed'] > 5]).tolist())
        if all_alat_session:
            session_thresholds[src] = float(np.percentile(all_alat_session, 70))
        else:
            session_thresholds[src] = 0.3

print(f'Excitation thresholds per session:')
for src, thresh in sorted(session_thresholds.items()):
    print(f'  {src}: p70 = {thresh:.3f}G')

n_total_samples = 0
n_excited_samples = 0
n_bank_corrected = 0

for lap in all_laps:
    lx, ly = to_xy(lap['lat'], lap['lon'])
    dlx = np.diff(lx)
    dly = np.diff(ly)
    dls = np.sqrt(dlx ** 2 + dly ** 2)
    lap_dist = np.concatenate([[0], np.cumsum(dls)])
    lap_len = lap_dist[-1]
    if abs(lap_len - track_length) > track_length * 0.12:
        continue

    # ── Road-attitude correction (gravity removal) ──
    # Run before resampling so we operate on the native time series. The result
    # gives us both raw and corrected lateral/longitudinal accel; we keep both
    # (raw under lap['alat_g_raw'], corrected under lap['alat_g_corrected']).
    # The correction is applied only on samples where the attitude estimate is
    # stable AND high-confidence — see attitude_correction.py for the gate.
    session_mount = session_mounts.get(lap['src'])
    if lap.get('accel_3d') is not None and session_mount is not None:
        att_result = apply_attitude_correction(
            lap['accel_3d'], lap['gyro_3d'], lap['speed'], lap['time_arr'],
            alat_g_kart=lap['alat_g'].copy(),
            along_g_kart=(
                lap['along_g_calc'].copy() if lap.get('along_g_calc') is not None
                else None
            ),
            gps_heading=lap.get('bearing_deg'),
            mount_estimate=session_mount,
            min_attitude_quality=MIN_ATTITUDE_QUALITY_FOR_CORRECTION,
        )
        lap['alat_g_raw'] = att_result.alat_g_raw
        lap['alat_g_corrected'] = att_result.alat_g_corrected
        lap['along_g_raw'] = att_result.along_g_raw
        lap['along_g_corrected'] = att_result.along_g_corrected
        lap['attitude_applied_mask'] = att_result.applied_mask
        per_lap_attitude_diagnostics.append({
            **att_result.diagnostics,
            'src': lap['src'],
        })
        # Use corrected for downstream demand computation. Raw stays under
        # lap['alat_g_raw'] for diagnostics and never gets overwritten.
        alat_for_demand = lap['alat_g_corrected']
    else:
        # No IMU or mount calibration failed — keep raw end-to-end.
        lap['alat_g_raw'] = lap['alat_g'].copy()
        lap['alat_g_corrected'] = lap['alat_g'].copy()
        lap['along_g_raw'] = None
        lap['along_g_corrected'] = None
        lap['attitude_applied_mask'] = np.zeros(len(lap['alat_g']), dtype=bool)
        alat_for_demand = lap['alat_g']

    lx_s = np.interp(s_grid, lap_dist, lx)
    ly_s = np.interp(s_grid, lap_dist, ly)
    spd_s = np.interp(s_grid, lap_dist, lap['speed'])
    # Resample CORRECTED lateral accel — preserves sign for bank estimation
    # downstream while subtracting any high-confidence gravity contamination.
    alat_s = np.interp(s_grid, lap_dist, alat_for_demand)
    alt_s = np.interp(s_grid, lap_dist, lap['alt'])

    # Longitudinal accel for combined slip (if available)
    # RaceChrono *calc column index 20 is "Longitudinal acceleration (G) *calc"
    # We stored alat_g but not along_g — for now approximate from speed derivative
    dv = np.gradient(spd_s, ds_m_local)
    along_g = dv / _G  # longitudinal accel in G

    excitation_threshold = session_thresholds.get(lap['src'], 0.3)

    for i in range(n_bins):
        ddx = lx_s[i] - center_x[i]
        ddy = ly_s[i] - center_y[i]
        n_off = ddx * nx_c[i] + ddy * ny_c[i]
        if n_off >= 0:
            left_off[i].append(n_off)
        else:
            right_off[i].append(abs(n_off))

        a_lat_raw = abs(alat_s[i])
        speed = spd_s[i]

        if speed < 5.0 or a_lat_raw > 2.5 or not np.isfinite(a_lat_raw):
            continue

        n_total_samples += 1

        # ── Fix 2: Centripetal cross-check ──
        # Expected centripetal accel from GPS speed + curvature
        a_centripetal = speed ** 2 * kappa_abs[i] / _G  # in G
        if a_centripetal > 0.05:
            ratio = a_lat_raw / a_centripetal
            centripetal_ratio[i].append(ratio)

        # ── Fix 3: Curvature-derived demand substitution ──
        # In corners: use GPS-derived centripetal (v²κ/g) instead of phone IMU.
        # This sidesteps phone pose, gravity contamination, and bank/roll effects.
        # NOT a bank correction — it's a full substitution of the demand source.
        if a_centripetal > 0.1:
            a_lat_corrected = a_centripetal
            n_bank_corrected += 1
        else:
            # On straights, centripetal ≈ 0 — IMU is the only source (low-demand, low-risk)
            a_lat_corrected = a_lat_raw

        # ── Combined demand (lateral + longitudinal) ──
        a_combined = np.sqrt(a_lat_corrected ** 2 + along_g[i] ** 2)
        combined_demand[i].append(float(a_combined))

        # ── All samples (lateral demand, corrected) ──
        demand_samp[i].append(float(a_lat_corrected))

        # ── Fix 1: Excitation gate — only near-limit samples ──
        if a_lat_corrected > excitation_threshold:
            demand_excited[i].append(float(a_lat_corrected))
            n_excited_samples += 1

        if np.isfinite(alt_s[i]):
            elev_samp[i].append(alt_s[i])

print(f'\nDemand map:')
print(f'  Total samples: {n_total_samples}')
print(f'  Excited samples: {n_excited_samples} ({n_excited_samples/max(n_total_samples,1)*100:.1f}%)')
print(f'  Curvature-substituted: {n_bank_corrected} ({n_bank_corrected/max(n_total_samples,1)*100:.1f}%)')

# ── Attitude-correction validation stats ──
if per_lap_attitude_diagnostics:
    sess_diag = merge_session_diagnostics(per_lap_attitude_diagnostics)
    print(f'\nRoad-attitude correction (demand cleaning, NOT friction):')
    print(f'  Laps analyzed:                    {sess_diag["n_laps_analyzed"]}')
    print(f'  Mean estimated bank:              {sess_diag["mean_estimated_bank_deg"]:+.2f}°')
    print(f'  Mean estimated grade:             {sess_diag["mean_estimated_grade_deg"]:+.2f}°')
    print(f'  Correction applied to:            {sess_diag["attitude_correction_active_frac"]*100:.1f}% of samples')
    print(f'  Skipped (low confidence):         {sess_diag["attitude_low_confidence_frac"]*100:.1f}%')
    print(f'  Skipped (mount/attitude unstable):{sess_diag["attitude_unstable_frac"]*100:.1f}%')
    print(f'  Mean |delta a_lat| raw vs corrected:   {sess_diag["mean_abs_delta_alat_g"]:.4f} G')
    print(f'  Mean |delta a_long| raw vs corrected:  {sess_diag["mean_abs_delta_along_g"]:.4f} G')
    print(f'  Mean |delta a_combined| raw vs corr.:  {sess_diag["mean_abs_delta_combined_g"]:.4f} G')
else:
    print(f'\nRoad-attitude correction: skipped (no IMU-equipped laps)')

# Width — use MAX of all driven offsets + buffer so every lap fits inside
width_left = np.array([
    max(o) + 1.0 if len(o) > 0 else 4.0
    for o in left_off
])
width_right = np.array([
    max(o) + 1.0 if len(o) > 0 else 4.0
    for o in right_off
])
for i in range(n_bins):
    total = width_left[i] + width_right[i]
    if total < 7:
        expand = (7 - total) / 2
        width_left[i] += expand
        width_right[i] += expand
width_left = np.clip(savgol_smooth(width_left, 15, 2), 2.0, 12.0)
width_right = np.clip(savgol_smooth(width_right, 15, 2), 2.0, 12.0)
print(f'Width: {(width_left + width_right).min():.1f}-{(width_left + width_right).max():.1f}m')

# ── Lateral demand: all-sample p90 (what you typically pulled) ──
lat_demand_all = np.array([
    float(np.percentile(s, 90)) if len(s) > 5 else 0.0
    for s in demand_samp
])
lat_demand_all = np.clip(savgol_smooth(lat_demand_all, 11, 2), 0.0, 2.0)

# ── Lateral demand ceiling: excited-only p90 (near-limit events only) ──
lat_demand_ceiling = np.array([
    float(np.percentile(s, 90)) if len(s) > 3 else lat_demand_all[i]
    for i, s in enumerate(demand_excited)
])
lat_demand_ceiling = np.clip(savgol_smooth(lat_demand_ceiling, 11, 2), 0.0, 2.0)

# ── Combined demand: sqrt(a_lat^2 + a_lon^2) p90 ──
combined_demand_p90 = np.array([
    float(np.percentile(s, 90)) if len(s) > 5 else 0.0
    for s in combined_demand
])
combined_demand_p90 = np.clip(savgol_smooth(combined_demand_p90, 11, 2), 0.0, 2.5)

# ── Fix 4: Confidence per bin ──
# confidence = f(sample_count, excitation_fraction, calibration_consistency)
confidence = np.zeros(n_bins)
cal_bias = np.zeros(n_bins)     # median centripetal ratio (1.0 = perfect calibration)
for i in range(n_bins):
    n_all = len(demand_samp[i])
    n_exc = len(demand_excited[i])

    # Sample count score (0-1, saturates at 30 samples)
    count_score = min(1.0, n_all / 30.0)

    # Excitation fraction (what % of samples were near-limit?)
    exc_frac = n_exc / max(n_all, 1)
    exc_score = min(1.0, exc_frac / 0.3)  # saturates when 30%+ are excited

    # Calibration consistency (centripetal cross-check)
    cal_score = 0.5  # default: unknown
    if len(centripetal_ratio[i]) > 3:
        ratios = np.array(centripetal_ratio[i])
        median_ratio = float(np.median(ratios))
        cal_bias[i] = median_ratio
        # Perfect calibration: ratio = 1.0. Penalize deviation.
        cal_score = max(0.0, 1.0 - abs(median_ratio - 1.0))

    confidence[i] = 0.4 * count_score + 0.35 * exc_score + 0.25 * cal_score

confidence = savgol_smooth(confidence, 11, 2)
confidence = np.clip(confidence, 0.0, 1.0)

# ── Bank angle estimate ──
# Only estimate bank in real corners (demand > 0.3G) where the cross-check
# is meaningful. Clamp to +-5 deg (realistic for kart tracks).
bank_estimate_deg = np.zeros(n_bins)
for i in range(n_bins):
    if len(centripetal_ratio[i]) > 5 and lat_demand_all[i] > 0.3:
        median_r = float(np.median(centripetal_ratio[i]))
        excess_g = (median_r - 1.0) * lat_demand_all[i]
        excess_g = np.clip(excess_g, -0.09, 0.09)  # max ~5 deg
        bank_estimate_deg[i] = float(np.degrees(np.arcsin(excess_g)))
bank_estimate_deg = savgol_smooth(bank_estimate_deg, 21, 2)
bank_estimate_deg = np.clip(bank_estimate_deg, -5.0, 5.0)

print(f'\nLateral demand map:')
print(f'  All-sample p90:    {lat_demand_all.min():.3f}-{lat_demand_all.max():.3f}G')
print(f'  Excited-only p90:  {lat_demand_ceiling.min():.3f}-{lat_demand_ceiling.max():.3f}G')
print(f'  Combined demand:   {combined_demand_p90.min():.3f}-{combined_demand_p90.max():.3f}G')
print(f'  Confidence:        {confidence.min():.2f}-{confidence.max():.2f} (mean {confidence.mean():.2f})')
print(f'  Bank estimate:     {bank_estimate_deg.min():.1f} to {bank_estimate_deg.max():.1f} deg')
print(f'  Cal bias (median): {cal_bias[cal_bias != 0].mean():.3f}' if (cal_bias != 0).any() else '  Cal bias: no data')

# Elevation
elevation = np.array([
    float(np.median(s)) if len(s) > 3 else 0
    for s in elev_samp
])
elevation = elevation - np.mean(elevation)
elevation = savgol_smooth(elevation, 21, 3)
print(f'Elevation: {elevation.min():.2f} to {elevation.max():.2f}m '
      f'({elevation.max() - elevation.min():.1f}m)')

ds_m = track_length / n_bins
vert_curvature = savgol_smooth(
    np.gradient(np.gradient(elevation, ds_m), ds_m), 21, 2,
)


# ═══════════════════════════════════════════════════════════════════
# SILVER TIER: 2D demand field demand(s, n)
# Uses Frenet frame for (x,y) → (s,n) projection, applies bronze
# corrections per cell. Additive layer — does not touch bronze outputs.
# ═══════════════════════════════════════════════════════════════════

demand_2d_dict = None
try:
    import sys as _s2
    _s2.path.insert(0, 'telemetry_tool')
    from track_surface.frenet import FrenetFrame
    from track_surface.demand_2d import build_demand_surface_2d

    # Build Frenet frame from the centerline
    cl_xy = np.column_stack([center_x, center_y])
    frenet = FrenetFrame.from_centerline(cl_xy)

    # Prepare lap data for 2D demand builder
    laps_for_2d = []
    for lap in all_laps:
        lx, ly = to_xy(lap['lat'], lap['lon'])
        laps_for_2d.append({
            'x': lx, 'y': ly,
            'speed': lap['speed'],
            'alat_g': lap['alat_g'],
            'src': lap['src'],
        })

    demand_2d = build_demand_surface_2d(
        frenet, laps_for_2d, curvature, session_thresholds,
        s_bin_m=4.0, n_bin_m=1.0, n_range_m=8.0,
    )

    if demand_2d is not None:
        demand_2d_dict = demand_2d.to_dict()
        print(f'\nSilver 2D demand: {demand_2d_dict["grid_shape"]} grid')
        print(f'  On-line mean:  {demand_2d_dict["on_line_mean_demand"]:.3f}G')
        print(f'  Off-line mean: {demand_2d_dict["off_line_mean_demand"]:.3f}G')
        print(f'  Racing line cells: {sum(sum(r) for r in demand_2d_dict["racing_line_mask"])}')
    else:
        print('\nSilver 2D demand: insufficient data')

except Exception as e:
    print(f'\nSilver 2D demand: skipped ({e})')


# ═══════════════════════════════════════════════════════════════════
# GOLD-ALPHA (SHADOW ONLY): Track-space Road Attitude Field
#
# Multi-lap aggregated bank(s)/grade(s) on the Frenet s-grid.
# This is a DIAGNOSTIC PHYSICS OVERLAY. It is NOT read by the bronze
# or silver demand accumulators — those remain untouched.
# Bank is gated as ready for shadow-mode visualization. Grade is
# exposed but explicitly marked as diagnostic-only.
# ═══════════════════════════════════════════════════════════════════

road_attitude_field_dict = None
try:
    from track_surface.road_attitude_field import (
        LapSamples,
        RoadAttitudeFieldConfig,
        estimate_road_attitude_field,
    )

    # Reuse the Frenet frame built above for silver (if available).
    if 'frenet' not in dir() or frenet is None:
        # Silver tier errored out — build a fresh one here so the field can still run.
        from track_surface.frenet import FrenetFrame as _FF
        frenet = _FF.from_centerline(np.column_stack([center_x, center_y]))

    # Build LapSamples from existing all_laps + session mount estimates.
    lap_samples = []
    for lap in all_laps:
        lx, ly = to_xy(lap['lat'], lap['lon'])
        dt_lap = 0.04
        ts = lap.get('time_arr')
        if ts is not None and len(ts) > 1:
            dt_lap = float(np.median(np.diff(ts)))
            if not np.isfinite(dt_lap) or dt_lap <= 0:
                dt_lap = 0.04
        # Prefer RaceChrono *calc longitudinal; fall back to speed gradient.
        along = lap.get('along_g_calc')
        if along is None or not np.all(np.isfinite(along)):
            along = np.gradient(lap['speed']) / max(dt_lap, 1e-6) / _G
        mount = session_mounts.get(lap['src'])
        orient_q = float(getattr(mount, 'orientation_quality', 0.5)) if mount else 0.5
        mount_unstable = bool(getattr(mount, 'mount_unstable', False)) if mount else True
        lap_samples.append(LapSamples(
            x=lx, y=ly,
            speed=lap['speed'],
            alat_g=lap['alat_g'],           # signed kart-y from RaceChrono *calc
            along_g=along,                  # signed kart-x
            dt=dt_lap,
            orientation_quality=orient_q,
            mount_unstable=mount_unstable,
            source=lap['src'],
        ))

    raf_cfg = RoadAttitudeFieldConfig(
        s_bin_m=5.0,
        min_samples_per_bin=30,
        min_laps_per_bin=3,
        bank_min_centripetal_g=0.15,
        grade_max_transient_g=0.25,
        bank_clamp_deg=8.0,
        grade_clamp_deg=8.0,
        smooth_window_bins=3,
    )
    raf = estimate_road_attitude_field(lap_samples, frenet, raf_cfg)
    raf_dict = raf.to_dict()
    # Wrap with tier metadata and explicit shadow-mode disclaimer.
    road_attitude_field_dict = {
        'tier': 'gold_alpha_shadow',
        'production_ready': {'bank': True, 'grade': False},
        'disclaimer': (
            'Shadow-only diagnostic physics overlay. Does NOT affect demand '
            'computation. Bronze (excited_p90) and Silver (demand_2d) remain '
            'the canonical demand products. Bank is ready for visualization; '
            'grade is diagnostic-only and not production-ready.'
        ),
        **raf_dict,
    }
    diag = road_attitude_field_dict.get('diagnostics', {})
    print(f'\nGold-alpha shadow: RoadAttitudeField')
    print(f'  bins: {diag.get("n_bins")}, '
          f'bank valid: {diag.get("n_bins_bank_valid")} '
          f'({diag.get("bank_coverage_frac", 0)*100:.1f}%)')
    print(f'  mean bank on valid bins:  {diag.get("mean_bank_on_valid_deg", 0):+.2f} deg')
    print(f'  mean grade on valid bins: {diag.get("mean_grade_on_valid_deg", 0):+.2f} deg  [diagnostic-only]')
    print(f'  laps used for bank: {diag.get("n_laps_used_bank")}/{diag.get("n_laps_total")}')
except Exception as e:
    print(f'\nGold-alpha shadow: skipped ({type(e).__name__}: {e})')
    # Emit a safe empty structure so downstream consumers can always rely
    # on data.road_attitude_field being present with expected keys.
    road_attitude_field_dict = {
        'tier': 'gold_alpha_shadow',
        'production_ready': {'bank': False, 'grade': False},
        'disclaimer': 'Shadow-only diagnostic. Field computation failed — empty scaffold.',
        's_bins': [],
        'bank_mean_deg': [], 'bank_std_deg': [],
        'bank_confidence': [], 'bank_evidence_count': [], 'bank_lap_coverage': [],
        'grade_mean_deg': [], 'grade_std_deg': [],
        'grade_confidence': [], 'grade_evidence_count': [], 'grade_lap_coverage': [],
        'confidence': [], 'evidence_count': [], 'lap_coverage': [],
        'diagnostics': {'empty': True, 'reason': f'{type(e).__name__}: {e}'},
    }


# Build driver traces
def build_driver(lap):
    lx, ly = to_xy(lap['lat'], lap['lon'])
    lz = lap['alt'] - np.mean(lap['alt'])
    lx = savgol_smooth(lx, 15, 3)
    ly = savgol_smooth(ly, 15, 3)
    spd_kph = lap['speed'] * 3.6

    n_off = np.zeros(len(lx))
    for i in range(len(lx)):
        d2 = (center_x - lx[i]) ** 2 + (center_y - ly[i]) ** 2
        nearest = int(np.argmin(d2))
        ddx = lx[i] - center_x[nearest]
        ddy = ly[i] - center_y[nearest]
        n_off[i] = ddx * nx_c[nearest] + ddy * ny_c[nearest]

    dv = np.gradient(spd_kph)
    throttle = np.clip((dv + 2) * 20, 0, 100)

    step = max(1, len(lx) // 800)
    idx = list(range(0, len(lx), step))
    return {
        'x': [round(float(lx[i]), 2) for i in idx],
        'y': [round(float(ly[i]), 2) for i in idx],
        'z': [round(float(lz[i]), 2) for i in idx],
        'speed_kph': [round(float(spd_kph[i]), 1) for i in idx],
        'throttle': [round(float(throttle[i]), 0) for i in idx],
        'n_offset': [round(float(n_off[i]), 2) for i in idx],
        'grip_mu': [round(float(abs(lap['alat_g'][i])), 3) for i in idx],  # legacy name for viz compat
        'lat_demand_g': [round(float(abs(lap['alat_g'][i])), 3) for i in idx],
        'lap_time': round(lap['time'], 3),
        'src': lap['src'],
    }


sorted_laps = sorted(all_laps, key=lambda l: l['time'])
drv_best = build_driver(sorted_laps[0])
drv_median = build_driver(sorted_laps[len(sorted_laps) // 2])
print(f'Best: {drv_best["lap_time"]}s ({len(drv_best["x"])} pts)')
print(f'Median: {drv_median["lap_time"]}s')

# JSON
data = {
    'track': {
        'name': 'Ouest Karting',
        'length_m': round(track_length, 1),
        'n_points': n_bins,
        'quality': 'gold',
        'centerline_x': [round(float(v), 2) for v in center_x],
        'centerline_y': [round(float(v), 2) for v in center_y],
        'curvature': [round(float(v), 5) for v in curvature],
        'heading': [round(float(v), 4) for v in heading_unwrapped],
    },
    'elevation': {
        'values': [round(float(v), 2) for v in elevation],
        'vert_curvature': [round(float(v), 6) for v in vert_curvature],
    },
    'boundaries': {
        'width_left': [round(float(v), 2) for v in width_left],
        'width_right': [round(float(v), 2) for v in width_right],
    },
    # DEPRECATED: legacy key for viz compatibility. Do not build new features on this.
    # Use lateral_demand.excited_p90 instead. Removal target: next major version.
    'grip_map': [round(float(v), 3) for v in lat_demand_ceiling],
    # Honest data layers
    'lateral_demand': {
        'all_p90': [round(float(v), 3) for v in lat_demand_all],
        'excited_p90': [round(float(v), 3) for v in lat_demand_ceiling],
        'combined_p90': [round(float(v), 3) for v in combined_demand_p90],
        'formula': 'excited_p90 = p90(|a_lat_corrected|) from excited samples only; '
                   'combined_p90 = p90(sqrt(a_lat^2 + a_lon^2))',
    },
    'sensor_quality': {
        'orientation_quality': [round(float(v), 3) for v in confidence],
        'curvature_agreement': [round(float(v), 3) for v in cal_bias],
        'bank_sensitivity_deg': [round(float(v), 2) for v in bank_estimate_deg],
        # ── Road-attitude correction diagnostics (session-aggregated) ──
        # These describe the gravity-removal correction applied to observed
        # lateral/longitudinal demand. They are NOT friction estimates and
        # NOT a measurement of "true bank/grade". They report the estimator's
        # mean output and how often the correction was actually used.
        **{
            f'attitude_correction.{k}': round(float(v), 4) if isinstance(v, float)
                                        else (int(v) if isinstance(v, (int, np.integer)) else v)
            for k, v in merge_session_diagnostics(per_lap_attitude_diagnostics).items()
        },
    },
    'map_confidence': {
        'excited_sample_frac': round(n_excited_samples / max(n_total_samples, 1), 3),
        'sample_density_per_bin': round(n_total_samples / n_bins, 1),
        'session_coverage': len(set(l['src'] for l in all_laps)),
        'confidence_per_bin': [round(float(v), 3) for v in confidence],
    },
    'drivers': {
        'hamilton': drv_best,
        'verstappen': drv_median,
    },
    'stats': {
        'best_lap_time_s': drv_best['lap_time'],
        'median_lap_time_s': drv_median['lap_time'],
        'n_laps_total': len(all_laps),
        'lat_demand_p90_mean': round(float(lat_demand_all.mean()), 3),
        'lat_demand_excited_mean': round(float(lat_demand_ceiling.mean()), 3),
        'confidence_mean': round(float(confidence.mean()), 2),
        'bank_range_deg': f'{bank_estimate_deg.min():.1f} to {bank_estimate_deg.max():.1f}',
    },
}

# Silver: add 2D demand field if available
if demand_2d_dict is not None:
    data['lateral_demand_2d'] = demand_2d_dict

# Gold-alpha shadow: track-space road attitude field.
# SHADOW-ONLY. Do not feed into bronze or silver. See disclaimer field.
if road_attitude_field_dict is not None:
    data['road_attitude_field'] = road_attitude_field_dict

with open('track-surface-ok-data.json', 'w') as f:
    json.dump(data, f)
print(f'\nSaved track-surface-ok-data.json')

# Diagnostic overlay
raw_pts = []
for lap in all_laps:
    lx, ly = to_xy(lap['lat'], lap['lon'])
    step = max(1, len(lx) // 400)
    for i in range(0, len(lx), step):
        raw_pts.append({'x': round(float(lx[i]), 1), 'y': round(float(ly[i]), 1)})

if len(raw_pts) > 15000:
    step2 = max(1, len(raw_pts) // 15000)
    raw_pts = raw_pts[::step2]

cl_pts = [{'x': round(float(center_x[i]), 1), 'y': round(float(center_y[i]), 1)}
          for i in range(n_bins)]
drv_pts = [{'x': round(float(drv_best['x'][i]), 1), 'y': round(float(drv_best['y'][i]), 1)}
           for i in range(len(drv_best['x']))]

diag_html = (
    '<!DOCTYPE html><html><head><style>'
    'body{background:#000;margin:0;overflow:hidden}canvas{display:block}'
    '.info{position:fixed;top:10px;left:10px;color:#f0ede5;font:12px monospace;z-index:10;line-height:1.8}'
    '</style></head><body>'
    '<div class="info">'
    '<span style="color:#3B82F6">Blue = raw GPS (all laps, NO pipeline)</span><br>'
    '<span style="color:#C9A84C">Gold = centerline (best lap raw GPS)</span><br>'
    '<span style="color:#22C55E">Green = driver best lap</span>'
    '</div>'
    '<canvas id="c"></canvas><script>'
    'const raw=' + json.dumps(raw_pts) + ';'
    'const cl=' + json.dumps(cl_pts) + ';'
    'const drv=' + json.dumps(drv_pts) + ';'
    'const c=document.getElementById("c"),ctx=c.getContext("2d");'
    'function draw(){'
    'const dpr=devicePixelRatio||1;c.width=innerWidth*dpr;c.height=innerHeight*dpr;'
    'c.style.width=innerWidth+"px";c.style.height=innerHeight+"px";'
    'ctx.setTransform(dpr,0,0,dpr,0,0);ctx.fillStyle="#000";ctx.fillRect(0,0,innerWidth,innerHeight);'
    'const all=[...raw,...cl,...drv];'
    'const xMin=Math.min(...all.map(p=>p.x)),xMax=Math.max(...all.map(p=>p.x));'
    'const yMin=Math.min(...all.map(p=>p.y)),yMax=Math.max(...all.map(p=>p.y));'
    'const pad=60,w=innerWidth-pad*2,h=innerHeight-pad*2;'
    'const scale=Math.min(w/(xMax-xMin||1),h/(yMax-yMin||1));'
    'const ox=pad+(w-(xMax-xMin)*scale)/2,oy=pad+(h-(yMax-yMin)*scale)/2;'
    'const xp=x=>ox+(x-xMin)*scale,yp=y=>oy+(yMax-y)*scale;'
    'ctx.fillStyle="rgba(59,130,246,0.12)";for(const p of raw){ctx.fillRect(xp(p.x),yp(p.y),1.5,1.5);}'
    'ctx.strokeStyle="#C9A84C";ctx.lineWidth=2.5;ctx.beginPath();'
    'for(let i=0;i<cl.length;i++){i===0?ctx.moveTo(xp(cl[i].x),yp(cl[i].y)):ctx.lineTo(xp(cl[i].x),yp(cl[i].y));}'
    'ctx.stroke();'
    'ctx.strokeStyle="#22C55E";ctx.lineWidth=1.5;ctx.globalAlpha=0.7;ctx.beginPath();'
    'for(let i=0;i<drv.length;i++){i===0?ctx.moveTo(xp(drv[i].x),yp(drv[i].y)):ctx.lineTo(xp(drv[i].x),yp(drv[i].y));}'
    'ctx.stroke();ctx.globalAlpha=1;'
    '}'
    'draw();onresize=draw;'
    '</script></body></html>'
)

with open('diag-raw-vs-centerline.html', 'w') as f:
    f.write(diag_html)
print('Wrote diag-raw-vs-centerline.html')

# Rebuild viewer
import re
with open('track-surface-ok.html', 'r', encoding='utf-8') as f:
    html = f.read()
pat = re.compile(r'const INLINE_DATA = (\{.*?\});', re.DOTALL)
m = pat.search(html)
new_json = json.dumps(data, separators=(',', ':'))
new_html = html[:m.start(1)] + new_json + html[m.end(1):]
with open('ouest-karting-live.html', 'w', encoding='utf-8') as f:
    f.write(new_html)
print('Wrote ouest-karting-live.html')
