"""Build SPA-format track surface data from Ouest Karting sessions."""
import sys
import json
sys.path.insert(0, 'telemetry_tool')

import numpy as np
from scipy.ndimage import uniform_filter1d

from pipeline.orchestrator import run_full_analysis

_G = 9.80665

SESSIONS = [
    ('data/raw/OK_FP+Q.csv', 'practice'),
    ('data/raw/OK_R1.csv', 'race'),
    ('data/raw/OK_R2.csv', 'race'),
    ('data/raw/OK_R3.csv', 'race'),
    ('data/raw/OK_R4.csv', 'race'),
]

all_valid = []
for csv, stype in SESSIONS:
    meta = {
        'session_type': stype,
        'vehicle_class': 'kart',
        'track_state': 'dry',
        'driver_name': 'Theo',
    }
    try:
        r = run_full_analysis(csv, meta, enable_ml=False, enable_report=False)
    except Exception as e:
        print(f'{csv}: FAILED ({e})')
        continue
    laps = r.get('resampled_laps', {})
    lt = r.get('lap_times', [])
    added = 0
    for k in sorted(laps.keys()):
        if k <= len(lt) and lt[k-1] and 20 < lt[k-1] < 120:
            all_valid.append({
                'df': laps[k],
                'time': lt[k-1],
                'src': csv.split('/')[-1].split('.')[0],
            })
            added += 1
    print(f'{csv.split("/")[-1]}: +{added} valid laps (total {len(lt)})')

print(f'\nTotal valid laps: {len(all_valid)}')
if not all_valid:
    print('No valid laps, aborting')
    sys.exit(1)

best = min(all_valid, key=lambda x: x['time'])
print(f'Best: {best["time"]:.3f}s from {best["src"]}')

# Reference coordinate system
ref_df = best['df']
ref_lat = ref_df['Latitude (deg)'].values
ref_lon = ref_df['Longitude (deg)'].values
lat0 = float(np.mean(ref_lat))
lon0 = float(np.mean(ref_lon))
cos_lat = np.cos(np.radians(lat0))


def to_xy(lat_arr, lon_arr):
    x = (lon_arr - lon0) * cos_lat * 111320.0
    y = (lat_arr - lat0) * 111320.0
    return x, y


# Track length from best lap
track_length = float(ref_df['Distance (m)'].values[-1] - ref_df['Distance (m)'].values[0])
print(f'Track length: {track_length:.0f}m')

# Robust centerline + boundaries (median + Kalman + Savitzky-Golay)
import sys as _sys
from pathlib import Path as _Path
if str(_Path(__file__).parent) not in _sys.path:
    _sys.path.insert(0, str(_Path(__file__).parent))
from envelope_boundaries import (
    refine_centerline_iteratively,
    compute_curvature,
    signed_perp_offset,
    kalman_rts_smooth_2d,
    savgol_smooth,
    reject_imu_outliers,
)

# ═══════════════════════════════════════════════════════════════════
# CENTERLINE = SINGLE BEST LAP (RTK GPS is 0.17m — one lap IS the shape)
# Multiple laps are used ONLY for width envelope and grip aggregation.
# ═══════════════════════════════════════════════════════════════════

# Use best lap as the reference trajectory (the track shape)
ref_lat = best['df']['Latitude (deg)'].values
ref_lon = best['df']['Longitude (deg)'].values
ref_dist = best['df']['Distance (m)'].values
ref_x, ref_y = to_xy(ref_lat, ref_lon)
ref_d = ref_dist - ref_dist[0]

# Savitzky-Golay smooth (preserves corners, kills GPS sub-meter jitter)
ref_x = savgol_smooth(ref_x, window=15, polyorder=3)
ref_y = savgol_smooth(ref_y, window=15, polyorder=3)

# Resample to uniform s-grid
n_bins = 600
s_grid = np.linspace(0, track_length, n_bins)
center_x = np.interp(s_grid, ref_d, ref_x)
center_y = np.interp(s_grid, ref_d, ref_y)
center_x = savgol_smooth(center_x, window=11, polyorder=3)
center_y = savgol_smooth(center_y, window=11, polyorder=3)
print(f'Centerline: best lap GPS, {n_bins} bins, SavGol smoothed')

# Build all laps XY for envelope
all_laps_xy = []
for lap in all_valid:
    df = lap['df']
    lat = df['Latitude (deg)'].values
    lon = df['Longitude (deg)'].values
    dist = df['Distance (m)'].values
    x, y = to_xy(lat, lon)
    all_laps_xy.append((x, y, dist))

# Width from percentile envelope of other laps around the reference centerline
from envelope_boundaries import percentile_envelope, apply_min_width
left_edge, right_edge = percentile_envelope(
    all_laps_xy, center_x, center_y, s_grid, track_length,
    p_low=5.0, p_high=95.0, buffer_m=0.5,
)
width_left, width_right = apply_min_width(left_edge, right_edge, min_total_width=7.0)
width_left = np.clip(width_left, 0.5, 8.0)
width_right = np.clip(-right_edge if (right_edge < 0).all() else right_edge, 0.5, 8.0)
# Ensure positive
width_left = np.abs(width_left)
width_right = np.abs(width_right)
width_left = savgol_smooth(width_left, window=15, polyorder=2)
width_right = savgol_smooth(width_right, window=15, polyorder=2)

total_w = width_left + width_right
print(f'Width: {total_w.min():.1f}-{total_w.max():.1f}m')

# Curvature from the reference centerline (clean GPS derivatives)
curvature, heading_unwrapped = compute_curvature(center_x, center_y)

# Grip map with outlier rejection and speed filter
# Reject samples where |a_lat| > 2.5G (kart max) or speed < 5 m/s (unreliable)
lat_accel_samples = [[] for _ in range(n_bins)]
rejected_grip = 0
for lap in all_valid:
    df = lap['df']
    dist_raw = df['Distance (m)'].values
    dist = dist_raw - dist_raw[0]
    if abs(dist[-1] - track_length) > track_length * 0.15:
        continue
    a_lat = (df['accel_lat_mps2'].values
             if 'accel_lat_mps2' in df.columns
             else np.zeros(len(df)))
    speed_vals = df['Speed (m/s)'].values if 'Speed (m/s)' in df.columns else np.ones(len(df)) * 20
    # Convert to G, clip outliers, reject slow samples
    mu_lat = np.abs(a_lat) / _G
    mu_lat = np.where(
        (mu_lat < 2.5) & (speed_vals > 5.0) & np.isfinite(mu_lat),
        mu_lat,
        np.nan,
    )
    rejected_grip += int(np.sum(np.isnan(mu_lat)))
    mu_at_s = np.interp(s_grid, dist, np.nan_to_num(mu_lat, nan=0.0))
    for i in range(n_bins):
        if mu_at_s[i] > 0.05:  # ignore zeros from NaN replacement
            lat_accel_samples[i].append(float(mu_at_s[i]))

# Use p90 instead of p95 (less sensitive to residual spikes)
grip_mu_p95 = np.array([
    float(np.percentile(samples, 90)) if len(samples) > 5 else 0.7
    for samples in lat_accel_samples
])
grip_mu_p95 = savgol_smooth(grip_mu_p95, window=11, polyorder=2)
grip_mu_p95 = np.clip(grip_mu_p95, 0.3, 2.0)
print(f'Grip p90: min={grip_mu_p95.min():.3f}, '
      f'max={grip_mu_p95.max():.3f}, mean={grip_mu_p95.mean():.3f} '
      f'(rejected {rejected_grip} outlier samples)')

# Elevation from averaged GPS altitude across all laps
# Raw phone GPS altitude has ~5m noise; averaged over 42 laps, noise drops to ~0.8m
altitude_sum = np.zeros(n_bins)
altitude_count = np.zeros(n_bins)
for lap in all_valid:
    df = lap['df']
    if 'Altitude (m)' not in df.columns:
        continue
    dist_raw = df['Distance (m)'].values
    dist = dist_raw - dist_raw[0]
    if abs(dist[-1] - track_length) > track_length * 0.15:
        continue
    alt = df['Altitude (m)'].values.astype(float)
    valid_mask = np.isfinite(alt)
    if valid_mask.sum() < 10:
        continue
    alt_interp = np.interp(s_grid, dist[valid_mask], alt[valid_mask])
    altitude_sum += alt_interp
    altitude_count += 1

if altitude_count.max() > 0:
    elevation = altitude_sum / np.maximum(altitude_count, 1)
    elevation = elevation - elevation.mean()
    # Savitzky-Golay preserves real elevation features
    elevation = savgol_smooth(elevation, window=21, polyorder=3)
    print(f'Elevation: {elevation.min():.2f} to {elevation.max():.2f}m '
          f'(range {elevation.max()-elevation.min():.1f}m)')
else:
    elevation = np.zeros(n_bins)
    print('No altitude data available')

ds_m = track_length / n_bins
d_elev = np.gradient(elevation, ds_m)
vert_curvature = np.gradient(d_elev, ds_m)
vert_curvature = savgol_smooth(vert_curvature, window=21, polyorder=2)


def build_driver(lap_data):
    df = lap_data['df']
    lat = df['Latitude (deg)'].values
    lon = df['Longitude (deg)'].values
    dist = df['Distance (m)'].values - df['Distance (m)'].values[0]
    speed_kph = df['Speed (m/s)'].values * 3.6
    a_lat = (df['accel_lat_mps2'].values
             if 'accel_lat_mps2' in df.columns
             else np.zeros(len(df)))

    x, y = to_xy(lat, lon)
    # z from the lap's own altitude (relative to track mean, not absolute)
    if 'Altitude (m)' in df.columns:
        z_raw = df['Altitude (m)'].values.astype(float)
        # Reference to the same zero as the track mean
        z = z_raw - z_raw.mean()
    else:
        z = np.zeros(len(x))

    # n_offset from envelope helper (evaluates signed perp offset per s-bin)
    dist_raw_drv = df['Distance (m)'].values
    dist_lap_drv = dist_raw_drv - dist_raw_drv[0]
    offsets_at_s = signed_perp_offset(
        x, y, dist_raw_drv, center_x, center_y, s_grid,
    )
    n_offset = np.interp(dist_lap_drv, s_grid, offsets_at_s)

    dv = np.gradient(speed_kph)
    throttle = np.clip((dv + 2) * 20, 0, 100)

    step = max(1, len(x) // 600)
    idx = list(range(0, len(x), step))
    if idx[-1] != len(x) - 1:
        idx.append(len(x) - 1)

    return {
        'x': [round(float(x[i]), 2) for i in idx],
        'y': [round(float(y[i]), 2) for i in idx],
        'z': [round(float(z[i]), 2) for i in idx],
        'speed_kph': [round(float(speed_kph[i]), 1) for i in idx],
        'throttle': [round(float(throttle[i]), 0) for i in idx],
        'n_offset': [round(float(n_offset[i]), 2) for i in idx],
        'grip_mu': [round(float(abs(a_lat[i]) / _G), 3) for i in idx],
        'lap_time': round(lap_data['time'], 3),
        'src': lap_data['src'],
    }


sorted_laps = sorted(all_valid, key=lambda x: x['time'])
best_lap = sorted_laps[0]
median_lap = sorted_laps[len(sorted_laps) // 2]
worst_lap = sorted_laps[-1]

driver_best = build_driver(best_lap)
driver_median = build_driver(median_lap)
driver_worst = build_driver(worst_lap)

print(f'Best:   {driver_best["lap_time"]}s ({driver_best["src"]}, {len(driver_best["x"])} pts)')
print(f'Median: {driver_median["lap_time"]}s ({driver_median["src"]}, {len(driver_median["x"])} pts)')
print(f'Worst:  {driver_worst["lap_time"]}s ({driver_worst["src"]}, {len(driver_worst["x"])} pts)')

# Time gain estimate
v_actual = np.array(driver_best['speed_kph']) / 3.6
mu_actual = np.array(driver_best['grip_mu'])
driver_d_approx = np.linspace(0, track_length, len(v_actual))
mu_p95_at = np.interp(driver_d_approx, s_grid, grip_mu_p95)

v_ceiling = np.copy(v_actual)
for i in range(len(v_ceiling)):
    if mu_actual[i] > 0.2:
        ratio = mu_p95_at[i] / max(mu_actual[i], 0.01)
        v_ceiling[i] = v_actual[i] * np.sqrt(min(ratio, 2.0))

ds_drv = np.diff(driver_d_approx)
dt_a = ds_drv / np.maximum(v_actual[:-1], 1.0)
dt_c = ds_drv / np.maximum(v_ceiling[:-1], 1.0)
time_gain = float(np.sum(dt_a - dt_c))
theoretical = best_lap['time'] - time_gain
print(f'Time gain: {time_gain:.2f}s -> theoretical {theoretical:.2f}s')

spa_data = {
    'track': {
        'name': 'Ouest Karting',
        'length_m': round(track_length, 1),
        'n_points': n_bins,
        'quality': 'silver',
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
    'grip_map': [round(float(v), 3) for v in grip_mu_p95],
    'drivers': {
        'hamilton': driver_best,
        'verstappen': driver_median,
    },
    'stats': {
        'best_lap_time_s': round(best_lap['time'], 3),
        'median_lap_time_s': round(median_lap['time'], 3),
        'worst_lap_time_s': round(worst_lap['time'], 3),
        'n_laps_total': len(all_valid),
        'n_sessions': len(SESSIONS),
        'mu_p95_global': round(float(grip_mu_p95.mean()), 3),
        'time_gain_s': round(time_gain, 2),
        'theoretical_lap_s': round(theoretical, 3),
    },
}

with open('track-surface-ok-data.json', 'w') as f:
    json.dump(spa_data, f)

import os
sz = os.path.getsize('track-surface-ok-data.json') / 1024
print(f'\nSaved track-surface-ok-data.json ({sz:.0f} KB)')
