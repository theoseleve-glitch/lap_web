"""
Over/understeer detection via accelerometer cross-coupling.

Physics:
  The chassis-mounted accelerometer measures forces in the BODY frame.
  GPS *calc measures accelerations in the PATH (velocity) frame.
  When the body has sideslip angle beta:

    accel_X_body = a_long_path * cos(beta) + a_lat_path * sin(beta)
    accel_Y_body = a_lat_path * cos(beta) - a_long_path * sin(beta)

  So the lateral GPS force "leaks" into the body's longitudinal axis:
    leakage = accel_X_body - a_long_path ~= a_lat_path * sin(beta)  (small beta)
    beta ~= arcsin(leakage / a_lat_path)

  Positive beta = rear sliding out (oversteer)
  Negative beta = front washing (understeer)

  At 1G cornering, 5 deg sideslip = 0.087G cross-coupling (detectable).

Uses:
  - RaceBox chassis accelerometer (body frame, level-mounted)
  - GPS *calc lateral + longitudinal accel (path frame)
  - Gravity calibration for accelerometer axis alignment
  - NO gyroscope needed
"""
import sys, pathlib
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.signal import butter, filtfilt

# -- Config ---------------------------------------------------------------
WHEELBASE     = 1.0
V_MIN         = 3.0
LPF_CUTOFF    = 1.5     # Hz -- steering/sideslip bandwidth
LPF_ORDER     = 2
MIN_LAT_G     = 0.3     # only compute sideslip above this G (signal too small below)

# -- Load CSV --------------------------------------------------------------
csv_path = sys.argv[1] if len(sys.argv) > 1 else str(
    pathlib.Path(__file__).resolve().parents[1] / "data" / "raw" / "OK_R1.csv"
)

with open(csv_path, "r", encoding="utf-8-sig") as f:
    for i, line in enumerate(f):
        if line.strip().startswith("Time (s)"):
            header_row = i
            break
    else:
        raise ValueError("Could not find 'Time (s)' header row")

df = pd.read_csv(csv_path, skiprows=header_row, low_memory=False)
cols = list(df.columns)
print(f"Loaded: {len(df)} rows x {len(cols)} cols")

# -- GPS channels (path frame) --------------------------------------------
time_s    = pd.to_numeric(df.iloc[:, 0], errors="coerce").values
speed     = pd.to_numeric(df.get("Speed (m/s) *calc", df.get("Speed (m/s)")), errors="coerce").values
lap_col   = pd.to_numeric(df["Lap #"], errors="coerce").values
dist      = pd.to_numeric(df["Distance (m)"], errors="coerce").values
bearing   = pd.to_numeric(df["Bearing (deg)"], errors="coerce").values

# GPS-derived accelerations (PATH frame -- aligned to velocity direction)
a_lat_gps = pd.to_numeric(df.get("Lateral acceleration (G) *calc"), errors="coerce").values
a_lon_gps = pd.to_numeric(df.get("Longitudinal acceleration (G) *calc"), errors="coerce").values

# -- Chassis accelerometer (BODY frame, RaceBox = sensor set 2) -----------
acc_x_indices = [i for i, c in enumerate(cols) if "X acceleration" in str(c)]
acc_y_indices = [i for i, c in enumerate(cols) if "Y acceleration" in str(c)]
acc_z_indices = [i for i, c in enumerate(cols) if "Z acceleration" in str(c)]

# Identify chassis sensor: the one with Z gravity ~1G (level-mounted)
chassis_set = 0
best_z_grav = 0
for s in range(len(acc_z_indices)):
    rest_mask = speed < 0.5
    rest_idx = np.where(rest_mask)[0][:200]
    if len(rest_idx) < 20:
        rest_idx = np.arange(min(200, len(df)))
    az = pd.to_numeric(df.iloc[:, acc_z_indices[s]], errors="coerce").values
    gz = abs(np.nanmedian(az[rest_idx]))
    if gz > best_z_grav:
        best_z_grav = gz
        chassis_set = s

ax_raw = pd.to_numeric(df.iloc[:, acc_x_indices[chassis_set]], errors="coerce").values
ay_raw = pd.to_numeric(df.iloc[:, acc_y_indices[chassis_set]], errors="coerce").values
az_raw = pd.to_numeric(df.iloc[:, acc_z_indices[chassis_set]], errors="coerce").values

# -- Calibrate accelerometer orientation from gravity at rest ---------------
rest_mask = speed < 0.5
rest_idx = np.where(rest_mask)[0][:300]
g_vec = np.array([
    np.nanmedian(ax_raw[rest_idx]),
    np.nanmedian(ay_raw[rest_idx]),
    np.nanmedian(az_raw[rest_idx]),
])
g_mag = np.linalg.norm(g_vec)
g_hat = g_vec / g_mag

print(f"Chassis accel (sensor {chassis_set}): gravity = [{g_vec[0]:.3f}, {g_vec[1]:.3f}, {g_vec[2]:.3f}] G")
print(f"  |g| = {g_mag:.3f} G, tilt = {np.degrees(np.arccos(abs(g_hat[2]))):.1f} deg from Z")

# Build rotation matrix to align sensor with true body frame:
# We want: X_body=forward, Y_body=left, Z_body=up
# Gravity direction in sensor frame tells us "down" = -g_hat
# We assume the sensor's X axis is roughly aligned with forward

# Step 1: Z_body = -gravity direction (up)
z_body = -g_hat

# Step 2: X_body = sensor X projected into the horizontal plane, normalized
x_sensor = np.array([1.0, 0.0, 0.0])
x_proj = x_sensor - np.dot(x_sensor, z_body) * z_body
x_body = x_proj / (np.linalg.norm(x_proj) + 1e-9)

# Step 3: Y_body = Z_body x X_body (right-hand rule)
y_body = np.cross(z_body, x_body)

# Rotation matrix: sensor_frame -> body_frame
R = np.array([x_body, y_body, z_body])  # rows are body axes in sensor coords

print(f"  Rotation applied: pitch correction = {np.degrees(np.arccos(np.dot(x_sensor, x_body))):.1f} deg")

# -- Rotate raw accelerations into body frame & subtract gravity -----------
# body_accel = R @ sensor_accel - [0, 0, 1G]
accel_body_x = R[0, 0] * ax_raw + R[0, 1] * ay_raw + R[0, 2] * az_raw  # forward
accel_body_y = R[1, 0] * ax_raw + R[1, 1] * ay_raw + R[1, 2] * az_raw  # lateral (left)
accel_body_z = R[2, 0] * ax_raw + R[2, 1] * ay_raw + R[2, 2] * az_raw - 1.0  # up (minus gravity)

# -- Filter setup ----------------------------------------------------------
dt_median = np.nanmedian(np.diff(time_s))
fs = 1.0 / dt_median if dt_median > 0 else 25.0
nyquist = fs / 2.0
b_lp, a_lp = butter(LPF_ORDER, min(LPF_CUTOFF / nyquist, 0.99), btype="low")

def filt(signal):
    s = pd.Series(signal).interpolate(limit_direction="both").values
    return filtfilt(b_lp, a_lp, s)

a_lat_gps_f  = filt(a_lat_gps)
a_lon_gps_f  = filt(a_lon_gps)
accel_bx_f   = filt(accel_body_x)
accel_by_f   = filt(accel_body_y)
speed_f      = filt(speed)
bearing_f    = filt(bearing)

# -- Full regression calibration (rotation + scale + bias) -----------------
# Instead of guessing mounting angles, fit a linear model:
#   [accel_body_x]   [a  b] [a_lon_gps]   [cx]
#   [accel_body_y] = [d  e] [a_lat_gps] + [cy]
#
# This captures: yaw rotation, scale factor, axis misalignment, bias.
# The RESIDUALS after removing this model = actual dynamic effects (sideslip).
# Use samples where speed > 5 m/s (ignore stationary vibration).
cal_mask = speed_f > 5.0
valid = cal_mask & ~np.isnan(a_lon_gps_f) & ~np.isnan(a_lat_gps_f)
n_cal = valid.sum()
print(f"\nRegression calibration: {n_cal} samples")

# Build design matrix: [a_lon_gps, a_lat_gps, 1]
A_cal = np.column_stack([a_lon_gps_f[valid], a_lat_gps_f[valid], np.ones(n_cal)])

# Fit body_x = f(gps_lon, gps_lat)
coeffs_x, _, _, _ = np.linalg.lstsq(A_cal, accel_bx_f[valid], rcond=None)
# Fit body_y = f(gps_lon, gps_lat)
coeffs_y, _, _, _ = np.linalg.lstsq(A_cal, accel_by_f[valid], rcond=None)

print(f"  Body X = {coeffs_x[0]:+.3f}*lon_gps {coeffs_x[1]:+.3f}*lat_gps {coeffs_x[2]:+.4f}")
print(f"  Body Y = {coeffs_y[0]:+.3f}*lon_gps {coeffs_y[1]:+.3f}*lat_gps {coeffs_y[2]:+.4f}")

# Extract mounting angle from the rotation matrix
# [a, b; d, e] should be ~[cos, sin; -sin, cos] * scale
mount_angle = np.degrees(np.arctan2(coeffs_x[1], coeffs_x[0]))
scale_x = np.sqrt(coeffs_x[0]**2 + coeffs_x[1]**2)
scale_y = np.sqrt(coeffs_y[0]**2 + coeffs_y[1]**2)
print(f"  Mounting angle: {mount_angle:.1f} deg, scale X={scale_x:.3f}, Y={scale_y:.3f}")

# Compute residuals (what the linear model can't explain)
predicted_bx = coeffs_x[0] * a_lon_gps_f + coeffs_x[1] * a_lat_gps_f + coeffs_x[2]
predicted_by = coeffs_y[0] * a_lon_gps_f + coeffs_y[1] * a_lat_gps_f + coeffs_y[2]
resid_x = accel_bx_f - predicted_bx  # longitudinal residual
resid_y = accel_by_f - predicted_by  # lateral residual

# R-squared (how well the linear model fits)
ss_res_x = np.sum(resid_x[valid]**2)
ss_tot_x = np.sum((accel_bx_f[valid] - np.mean(accel_bx_f[valid]))**2)
r2_x = 1 - ss_res_x / (ss_tot_x + 1e-12)
ss_res_y = np.sum(resid_y[valid]**2)
ss_tot_y = np.sum((accel_by_f[valid] - np.mean(accel_by_f[valid]))**2)
r2_y = 1 - ss_res_y / (ss_tot_y + 1e-12)
print(f"  R-squared: X={r2_x:.4f}, Y={r2_y:.4f}")
print(f"  Residual RMS: X={np.sqrt(np.mean(resid_x[valid]**2)):.4f} G, Y={np.sqrt(np.mean(resid_y[valid]**2)):.4f} G")

# -- GPS yaw rate and kinematic steering angle (for reference) -------------
dt_arr = np.diff(time_s, prepend=time_s[0])
dt_arr[dt_arr <= 0] = 1e-6
dbearing = np.diff(bearing, prepend=bearing[0])
dbearing = (dbearing + 180) % 360 - 180
yaw_gps_dps = filt(dbearing / dt_arr)

speed_safe = np.where(speed_f > V_MIN, speed_f, np.nan)
kinematic_steer = np.rad2deg(np.arctan(WHEELBASE * np.deg2rad(yaw_gps_dps) / speed_safe))

# -- Sideslip angle from cross-coupling -----------------------------------
# body_accel_x = a_lon_gps * cos(beta) + a_lat_gps * sin(beta)
# So: body_accel_x - a_lon_gps = a_lat_gps * sin(beta)  (for small beta)
# beta = arcsin((body_accel_x - a_lon_gps) / a_lat_gps)

# Cross-coupling: the longitudinal RESIDUAL after removing the linear model.
# This is what the mounting model can't explain = dynamic sideslip effect.
# beta ~ arcsin(resid_x / a_lat_gps)  (the lateral force leaking into long axis)
cross_coupling = resid_x

# Only compute beta where lateral G is high enough for meaningful signal
a_lat_abs = np.abs(a_lat_gps_f)
beta_raw = np.where(
    a_lat_abs > MIN_LAT_G,
    np.degrees(np.arcsin(np.clip(cross_coupling / (a_lat_abs + 1e-6), -1, 1))),
    0.0
)

# Correct sign: RaceChrono convention for lateral accel sign
# Positive a_lat = right turn. Positive beta = rear slides right (oversteer in right turn)
# We want: positive = oversteer, negative = understeer
# Need to flip sign based on turn direction
beta_signed = np.where(a_lat_gps_f > 0, beta_raw, -beta_raw)

# Final filter on sideslip angle
b_ss, a_ss = butter(LPF_ORDER, min(0.8 / nyquist, 0.99), btype="low")
beta_final = filtfilt(b_ss, a_ss,
                      pd.Series(beta_signed).interpolate(limit_direction="both").values)

# Clip to physically reasonable range (-15 to +15 deg)
beta_final = np.clip(beta_final, -15, 15)

# Stats
corner_mask = a_lat_abs > 0.5
if corner_mask.sum() > 0:
    print(f"\nSideslip stats (corners > 0.5G):")
    print(f"  Mean |beta| = {np.nanmean(np.abs(beta_final[corner_mask])):.2f} deg")
    print(f"  Max  |beta| = {np.nanmax(np.abs(beta_final[corner_mask])):.2f} deg")
    print(f"  Std  beta   = {np.nanstd(beta_final[corner_mask]):.2f} deg")

# -- Actual steering (kinematic + sideslip) --------------------------------
actual_steer = np.where(np.isnan(kinematic_steer), np.nan,
                        kinematic_steer + beta_final)

# -- Find best lap ---------------------------------------------------------
valid_laps = pd.Series(lap_col).dropna()
valid_laps = valid_laps[valid_laps > 0].unique()
best_lap, best_time = None, np.inf
for lap_num in valid_laps:
    m = lap_col == lap_num
    t = time_s[m]
    if len(t) < 10:
        continue
    lt = t[-1] - t[0]
    if 10 < lt < best_time:
        best_time = lt
        best_lap = int(lap_num)

print(f"\nBest lap: #{best_lap}  ({best_time:.3f}s)")

# -- Extract best lap data -------------------------------------------------
m = lap_col == best_lap
lap_dist     = dist[m] - dist[m][0]
lap_kin      = kinematic_steer[m]
lap_actual   = actual_steer[m]
lap_beta     = beta_final[m]
lap_speed    = speed_f[m]
lap_a_lat    = a_lat_gps_f[m]
lap_cross    = cross_coupling[m]

# -- Plot: 4 panels --------------------------------------------------------
fig, axes = plt.subplots(4, 1, figsize=(14, 10), sharex=True,
                         gridspec_kw={"height_ratios": [2.5, 1.5, 1.5, 1.5]})
fig.patch.set_facecolor("#0a0a0a")

for ax in axes:
    ax.set_facecolor("#141414")
    ax.tick_params(colors="#949494")
    ax.spines["bottom"].set_color("#333")
    ax.spines["left"].set_color("#333")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

# Panel 1: Kinematic vs Actual steering
ax1 = axes[0]
ax1.plot(lap_dist, lap_kin, color="#949494", linewidth=0.7, alpha=0.5,
         label="Kinematic (GPS, no-slip)")
ax1.plot(lap_dist, lap_actual, color="#F0EDE5", linewidth=0.9,
         label="Actual (with sideslip correction)")
ax1.fill_between(lap_dist, lap_kin, lap_actual,
                 where=(~np.isnan(lap_actual)) & (~np.isnan(lap_kin)) & (lap_beta > 0.5),
                 color="#FF2A2A", alpha=0.3, label="Oversteer")
ax1.fill_between(lap_dist, lap_kin, lap_actual,
                 where=(~np.isnan(lap_actual)) & (~np.isnan(lap_kin)) & (lap_beta < -0.5),
                 color="#8B5CF6", alpha=0.3, label="Understeer")
ax1.axhline(0, color="#949494", linewidth=0.4, linestyle="--")
ax1.set_ylabel("Steering (deg)", color="#F0EDE5", fontsize=10)
ax1.set_title(
    f"Steering + Over/Understeer via Accel Cross-Coupling -- Lap #{best_lap}  ({best_time:.2f}s)\n"
    f"Sideslip from body-frame vs path-frame accelerometer comparison",
    color="#F0EDE5", fontsize=12, pad=10
)
ax1.legend(loc="upper right", facecolor="#1a1a1a", edgecolor="#333",
           labelcolor="#F0EDE5", fontsize=8, ncol=2)

# Panel 2: Sideslip angle (beta)
ax2 = axes[1]
ax2.fill_between(lap_dist, lap_beta, 0,
                 where=lap_beta > 0.5, color="#FF2A2A", alpha=0.4, label="Oversteer")
ax2.fill_between(lap_dist, lap_beta, 0,
                 where=lap_beta < -0.5, color="#8B5CF6", alpha=0.4, label="Understeer")
ax2.plot(lap_dist, lap_beta, color="#F0EDE5", linewidth=0.7)
ax2.axhline(0, color="#949494", linewidth=0.4, linestyle="--")
ax2.set_ylabel("Sideslip (deg)", color="#F0EDE5", fontsize=10)
ax2.legend(loc="upper right", facecolor="#1a1a1a", edgecolor="#333",
           labelcolor="#F0EDE5", fontsize=8)

# Panel 3: Speed
ax3 = axes[2]
ax3.plot(lap_dist, lap_speed * 3.6, color="#22C55E", linewidth=0.8)
ax3.set_ylabel("Speed (km/h)", color="#F0EDE5", fontsize=10)

# Panel 4: Lateral G (shows where sideslip data is meaningful)
ax4 = axes[3]
ax4.plot(lap_dist, lap_a_lat, color="#C9A84C", linewidth=0.8, label="Lat G (GPS)")
ax4.axhline(MIN_LAT_G, color="#FF2A2A", linewidth=0.4, linestyle=":", alpha=0.5)
ax4.axhline(-MIN_LAT_G, color="#FF2A2A", linewidth=0.4, linestyle=":", alpha=0.5)
ax4.set_ylabel("Lat G", color="#F0EDE5", fontsize=10)
ax4.set_xlabel("Distance (m)", color="#F0EDE5", fontsize=11)

plt.tight_layout()
out_path = str(pathlib.Path(__file__).resolve().parents[1] / "artifacts" / "steering_v4_cross_coupling.png")
plt.savefig(out_path, dpi=150, facecolor=fig.get_facecolor())
plt.close()
print(f"Saved to {out_path}")
