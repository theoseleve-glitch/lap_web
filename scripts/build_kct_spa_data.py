"""Build SPA-format track surface data from KCT karting sessions."""
import sys
import json
sys.path.insert(0, 'telemetry_tool')

import numpy as np
from scipy.ndimage import uniform_filter1d

from pipeline.orchestrator import run_full_analysis

_G = 9.80665
meta = {
    'session_type': 'practice',
    'vehicle_class': 'kart',
    'track_state': 'dry',
    'driver_name': 'Theo',
}

# Process all 3 KCT sessions
all_valid = []
for csv in ['data/raw/KCT_FP1.csv', 'data/raw/KCT_FP2.csv', 'data/raw/KCT_FP3.csv']:
    r = run_full_analysis(csv, meta, enable_ml=False, enable_report=False)
    laps = r.get('resampled_laps', {})
    lt = r.get('lap_times', [])
    for k in sorted(laps.keys()):
        if k <= len(lt) and lt[k-1] and 20 < lt[k-1] < 60:
            all_valid.append({
                'df': laps[k],
                'time': lt[k-1],
                'src': csv.split('/')[-1].split('.')[0],
            })

print(f'Total valid laps: {len(all_valid)}')
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


# Distance grid
track_length = float(ref_df['Distance (m)'].values[-1] - ref_df['Distance (m)'].values[0])
print(f'Track length: {track_length:.0f}m')

# Envelope-based centerline + boundaries
import sys as _sys
from pathlib import Path as _Path
if str(_Path(__file__).parent) not in _sys.path:
    _sys.path.insert(0, str(_Path(__file__).parent))
from envelope_boundaries import (
    refine_centerline_iteratively,
    compute_curvature,
    signed_perp_offset,
)

all_laps_xy = []
for lap in all_valid:
    df = lap['df']
    lat = df['Latitude (deg)'].values
    lon = df['Longitude (deg)'].values
    dist = df['Distance (m)'].values
    x, y = to_xy(lat, lon)
    all_laps_xy.append((x, y, dist))

n_bins = 500  # smaller track
center_x, center_y, s_grid, width_left, width_right = refine_centerline_iteratively(
    all_laps_xy, n_bins, track_length,
    n_iterations=2, buffer_m=1.0, min_total_width=8.0,
)
print(f'Centerline: {n_bins} bins (envelope-based)')
print(f'Width left:  {width_left.min():.1f}-{width_left.max():.1f}m')
print(f'Width right: {width_right.min():.1f}-{width_right.max():.1f}m')
total_w = width_left + width_right
print(f'Total width: {total_w.min():.1f}-{total_w.max():.1f}m')

curvature, heading_unwrapped = compute_curvature(center_x, center_y)

# Grip map
lat_accel_samples = [[] for _ in range(n_bins)]
for lap in all_valid:
    df = lap['df']
    dist_raw = df['Distance (m)'].values
    dist = dist_raw - dist_raw[0]
    if abs(dist[-1] - track_length) > track_length * 0.15:
        continue
    a_lat = (df['accel_lat_mps2'].values
             if 'accel_lat_mps2' in df.columns
             else np.zeros(len(df)))
    alat_interp = np.interp(s_grid, dist, np.abs(a_lat))
    for i in range(n_bins):
        lat_accel_samples[i].append(float(alat_interp[i] / _G))

grip_mu_p95 = np.array([
    float(np.percentile(samples, 95)) if len(samples) > 3 else 0.7
    for samples in lat_accel_samples
])
grip_mu_p95 = uniform_filter1d(grip_mu_p95, 5, mode='wrap')
print(f'Grip p95: min={grip_mu_p95.min():.3f}, '
      f'max={grip_mu_p95.max():.3f}, mean={grip_mu_p95.mean():.3f}')

# Elevation (zeros — GPS altitude too noisy for 376m kart track)
elevation = np.zeros(n_bins)
vert_curvature = np.zeros(n_bins)


def build_driver(lap_data):
    """Build driver trace in SPA format."""
    df = lap_data['df']
    lat = df['Latitude (deg)'].values
    lon = df['Longitude (deg)'].values
    dist = df['Distance (m)'].values - df['Distance (m)'].values[0]
    speed_kph = df['Speed (m/s)'].values * 3.6
    a_lat = (df['accel_lat_mps2'].values
             if 'accel_lat_mps2' in df.columns
             else np.zeros(len(df)))

    x, y = to_xy(lat, lon)
    z = np.zeros(len(x))

    # n_offset from envelope helper
    dist_raw_drv = df['Distance (m)'].values
    dist_lap_drv = dist_raw_drv - dist_raw_drv[0]
    offsets_at_s = signed_perp_offset(
        x, y, dist_raw_drv, center_x, center_y, s_grid,
    )
    n_offset = np.interp(dist_lap_drv, s_grid, offsets_at_s)

    # Throttle proxy from speed gradient (positive accel → throttle)
    dv = np.gradient(speed_kph)
    throttle = np.clip((dv + 2) * 20, 0, 100)

    # Subsample to ~500 points
    step = max(1, len(x) // 500)
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

print(f'Best:   {driver_best["lap_time"]}s ({len(driver_best["x"])} pts)')
print(f'Median: {driver_median["lap_time"]}s ({len(driver_median["x"])} pts)')
print(f'Worst:  {driver_worst["lap_time"]}s ({len(driver_worst["x"])} pts)')

# Compute time gain estimate (theoretical using p95 grip)
v_actual = np.array(driver_best['speed_kph']) / 3.6
mu_actual = np.array(driver_best['grip_mu'])
# Interpolate grip_p95 to driver positions
driver_d_approx = np.linspace(0, track_length, len(v_actual))
mu_p95_at = np.interp(driver_d_approx, s_grid, grip_mu_p95)

# Where driver is cornering (mu > 0.2), could carry sqrt(mu_p95/mu_actual) more speed
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

# Build final JSON matching SPA format
spa_data = {
    'track': {
        'name': 'KCT - Kart Circuit Tours',
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
        'best': driver_best,
        'median': driver_median,
        'worst': driver_worst,
    },
    'stats': {
        'best_lap_time_s': round(best_lap['time'], 3),
        'median_lap_time_s': round(median_lap['time'], 3),
        'worst_lap_time_s': round(worst_lap['time'], 3),
        'n_laps_total': len(all_valid),
        'n_sessions': 3,
        'mu_p95_global': round(float(grip_mu_p95.mean()), 3),
        'time_gain_s': round(time_gain, 2),
        'theoretical_lap_s': round(theoretical, 3),
    },
}

out_path = 'track-surface-kct-data.json'
with open(out_path, 'w') as f:
    json.dump(spa_data, f)

import os
sz = os.path.getsize(out_path) / 1024
print(f'\nSaved {out_path} ({sz:.0f} KB)')
