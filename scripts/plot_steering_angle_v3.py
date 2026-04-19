"""
Steering angle + over/understeer detection from GPS + chassis gyro.

Physics:
  - GPS bearing rate = d(velocity_direction)/dt  (where the car is GOING)
  - Chassis gyro yaw = d(heading)/dt             (where the car is POINTING)
  - When these match: no sideslip (neutral)
  - When gyro > GPS:  car rotating faster than trajectory -> OVERSTEER (rear slip)
  - When gyro < GPS:  car not rotating enough for trajectory -> UNDERSTEER (front slip)

  sideslip_rate = yaw_gyro - yaw_gps
  sideslip_angle = integral(sideslip_rate)

  actual_steering = kinematic_steering + sideslip_correction
  over_understeer = actual_steering - kinematic_steering

Uses:
  - Sensor 1 (RaceBox, chassis-mounted, level, 25 Hz) for yaw rate
  - GPS bearing + speed for kinematic reference
  - NOT the noisy phone gyro on the steering
"""
import sys, pathlib
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.signal import butter, filtfilt

# -- Config ---------------------------------------------------------------
WHEELBASE     = 1.0      # metres (kart)
V_MIN         = 3.0      # m/s - blank below this
LPF_CUTOFF    = 2.0      # Hz - Butterworth cutoff
LPF_ORDER     = 2
DRIFT_TAU     = 3.0      # seconds - sideslip drift correction time constant
REST_SPEED    = 0.5      # m/s

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

# -- GPS channels (Earth frame) -------------------------------------------
time_s  = pd.to_numeric(df.iloc[:, 0], errors="coerce").values
speed   = pd.to_numeric(df.get("Speed (m/s) *calc", df.get("Speed (m/s)")), errors="coerce").values
lap_col = pd.to_numeric(df["Lap #"], errors="coerce").values
dist    = pd.to_numeric(df["Distance (m)"], errors="coerce").values
bearing = pd.to_numeric(df["Bearing (deg)"], errors="coerce").values
a_lat_g = pd.to_numeric(df.get("Lateral acceleration (G) *calc"), errors="coerce").values

# -- Chassis gyro (RaceBox, sensor set 2, level-mounted) -------------------
# Find the SECOND set of gyro columns (RaceBox at ~25Hz, chassis-mounted)
gyr_z_indices = [i for i, c in enumerate(cols) if "Z rate of rotation" in str(c)]
acc_z_indices = [i for i, c in enumerate(cols) if "Z acceleration" in str(c)]

if len(gyr_z_indices) >= 2:
    # Verify which is chassis-mounted: check gravity on Z accel
    for idx, (gz_i, az_i) in enumerate(zip(gyr_z_indices, acc_z_indices)):
        az_vals = pd.to_numeric(df.iloc[:, az_i], errors="coerce").values
        rest_mask = speed < REST_SPEED
        rest_idx = np.where(rest_mask)[0][:200]
        if len(rest_idx) < 10:
            rest_idx = np.arange(min(200, len(az_vals)))
        gz_rest = np.nanmedian(az_vals[rest_idx])
        print(f"  Gyro set {idx} (col {gz_i}): accel_Z at rest = {gz_rest:.3f} G")

    # Use second set (RaceBox, chassis-mounted, Z~=1G)
    chassis_gyro_z_col = gyr_z_indices[1]
    print(f"  Using chassis gyro Z from column {chassis_gyro_z_col}")
else:
    chassis_gyro_z_col = gyr_z_indices[0]
    print(f"  Only 1 gyro set found, using column {chassis_gyro_z_col}")

# -- Auto-detect which chassis gyro axis is vehicle yaw --------------------
# The RaceBox Z might not be yaw — check all 3 axes against GPS yaw rate.
gyr_x_indices = [i for i, c in enumerate(cols) if "X rate of rotation" in str(c)]
gyr_y_indices = [i for i, c in enumerate(cols) if "Y rate of rotation" in str(c)]

# Use the chassis sensor set (index 1 if two sets, else 0)
chassis_set = 1 if len(gyr_z_indices) >= 2 else 0
gyro_axes = {
    "X": pd.to_numeric(df.iloc[:, gyr_x_indices[chassis_set]], errors="coerce").values,
    "Y": pd.to_numeric(df.iloc[:, gyr_y_indices[chassis_set]], errors="coerce").values,
    "Z": pd.to_numeric(df.iloc[:, gyr_z_indices[chassis_set]], errors="coerce").values,
}
print(f"  Checking all 3 chassis gyro axes for yaw alignment...")

# -- Sampling & filter setup -----------------------------------------------
dt_arr = np.diff(time_s, prepend=time_s[0])
dt_arr[dt_arr <= 0] = 1e-6
dt_median = np.nanmedian(np.diff(time_s))
fs = 1.0 / dt_median if dt_median > 0 else 25.0
nyquist = fs / 2.0

def make_filter(cutoff):
    norm = min(cutoff / nyquist, 0.99)
    return butter(LPF_ORDER, norm, btype="low")

b_lp, a_lp = make_filter(LPF_CUTOFF)
# Tighter filter for sideslip (slow phenomenon, < 0.8 Hz)
b_ss, a_ss = make_filter(0.8)

def clean_and_filter(signal, b=b_lp, a=a_lp):
    """Interpolate NaNs, then Butterworth low-pass."""
    s = pd.Series(signal).interpolate(limit_direction="both").values
    return filtfilt(b, a, s)

# -- GPS yaw rate (velocity vector direction change) -----------------------
dbearing = np.diff(bearing, prepend=bearing[0])
dbearing = (dbearing + 180) % 360 - 180   # unwrap
yaw_gps_dps = dbearing / dt_arr

yaw_gps_filt  = clean_and_filter(yaw_gps_dps)
speed_filt    = clean_and_filter(speed)
a_lat_filt    = clean_and_filter(a_lat_g)

# -- Downsample to gyro native rate before comparison ---------------------
# The RaceBox gyro is at ~25 Hz but data rows are at ~250 Hz (phone rate).
# The gyro value is held constant for ~10 rows between updates, making
# sample-by-sample correlation with GPS meaningless.
# Solution: detect actual gyro update indices (where value changes),
# then resample everything to ~25 Hz for the comparison.

gyro_z_raw = gyro_axes["Z"]
# Find indices where gyro Z actually changes (new sample from RaceBox)
gyro_changes = np.where(np.diff(gyro_z_raw) != 0)[0] + 1
gyro_changes = np.concatenate([[0], gyro_changes])
native_rate = len(gyro_changes) / (time_s[-1] - time_s[0])
print(f"  Chassis gyro native update rate: ~{native_rate:.1f} Hz ({len(gyro_changes)} updates)")

# Resample all signals at gyro update indices
time_ds    = time_s[gyro_changes]
speed_ds   = speed_filt[gyro_changes]
bearing_ds = bearing[gyro_changes]
a_lat_ds   = a_lat_filt[gyro_changes]

dt_ds = np.diff(time_ds, prepend=time_ds[0])
dt_ds[dt_ds <= 0] = 1e-3
fs_ds = 1.0 / np.nanmedian(np.diff(time_ds))
nyq_ds = fs_ds / 2.0
print(f"  Downsampled rate: {fs_ds:.1f} Hz")

# Recompute filters at native rate
b_ds, a_ds = butter(LPF_ORDER, min(LPF_CUTOFF / nyq_ds, 0.99), btype="low")
b_ss_ds, a_ss_ds = butter(LPF_ORDER, min(0.8 / nyq_ds, 0.99), btype="low")

def clean_filt_ds(sig, b=b_ds, a=a_ds):
    s = pd.Series(sig).interpolate(limit_direction="both").values
    return filtfilt(b, a, s)

# GPS yaw rate at native rate
db_ds = np.diff(bearing_ds, prepend=bearing_ds[0])
db_ds = (db_ds + 180) % 360 - 180
yaw_gps_ds = clean_filt_ds(db_ds / dt_ds)

# -- Find which gyro axis best tracks vehicle yaw (at native rate) ---------
straight_ds = (np.abs(a_lat_ds) < 0.1) & (speed_ds > 8.0)
n_straight = straight_ds.sum()
print(f"  Straight-line samples (native rate): {n_straight}")

best_axis = "Z"
best_corr = 0
best_scale = 1.0
best_offset = 0.0

for axis_name, axis_data in gyro_axes.items():
    axis_ds = clean_filt_ds(axis_data[gyro_changes])
    if n_straight > 50:
        gps_s  = yaw_gps_ds[straight_ds]
        gyro_s = axis_ds[straight_ds]
        valid  = ~(np.isnan(gps_s) | np.isnan(gyro_s))
        if valid.sum() > 50:
            corr = abs(np.corrcoef(gps_s[valid], gyro_s[valid])[0, 1])
            coeffs = np.polyfit(gps_s[valid], gyro_s[valid], 1)
            print(f"  Axis {axis_name}: corr={corr:.3f}, scale={coeffs[0]:.3f}, offset={coeffs[1]:.3f}")
            if corr > best_corr:
                best_corr = corr
                best_axis = axis_name
                best_scale = coeffs[0]
                best_offset = coeffs[1]

print(f"\n  Best yaw axis: {best_axis} (corr={best_corr:.3f}, scale={best_scale:.3f})")

# -- Compute sideslip at native rate, then upsample back -------------------
yaw_gyro_ds = clean_filt_ds(gyro_axes[best_axis][gyro_changes])

# Calibrate gyro to GPS reference frame
if abs(best_scale) > 0.1 and best_corr > 0.3:
    yaw_gyro_cal_ds = (yaw_gyro_ds - best_offset) / best_scale
    print(f"  Gyro calibrated: scale={best_scale:.3f}, offset={best_offset:.3f}")
else:
    # Fallback: just remove offset, assume scale ~1
    yaw_gyro_cal_ds = yaw_gyro_ds - best_offset
    print(f"  Low correlation ({best_corr:.3f}) -- using offset-only calibration")

# Sideslip rate at native gyro rate
sideslip_rate_ds = clean_filt_ds(yaw_gyro_cal_ds - yaw_gps_ds, b_ss_ds, a_ss_ds)

# Integrate with drift correction at native rate
alpha_drift = (1.0 / fs_ds) / (DRIFT_TAU + 1.0 / fs_ds)
sideslip_ds = np.zeros(len(time_ds))
for i in range(1, len(time_ds)):
    raw_update = sideslip_ds[i-1] + sideslip_rate_ds[i] * dt_ds[i]
    sideslip_ds[i] = (1 - alpha_drift) * raw_update

sideslip_ds = clean_filt_ds(sideslip_ds, b_ss_ds, a_ss_ds)

# Upsample back to full rate via interpolation
sideslip_deg = np.interp(time_s, time_ds, sideslip_ds)
yaw_gyro_cal = np.interp(time_s, time_ds, yaw_gyro_cal_ds)

print(f"Filter: order={LPF_ORDER}, cutoff={LPF_CUTOFF} Hz, sideslip cutoff=0.8 Hz")

# -- Kinematic steering angle (GPS bicycle model, no-slip) -----------------
speed_safe = np.where(speed_filt > V_MIN, speed_filt, np.nan)
yaw_gps_rps = np.deg2rad(yaw_gps_filt)
kinematic_steer = np.rad2deg(np.arctan(WHEELBASE * yaw_gps_rps / speed_safe))

# -- Actual steering = kinematic + sideslip correction ---------------------
actual_steer = np.where(np.isnan(kinematic_steer),
                        np.nan,
                        kinematic_steer + sideslip_deg)

# -- Over/understeer indicator = sideslip angle ----------------------------
# Positive: UNDERSTEER (front tires slipping, driver adds more lock)
# Negative: OVERSTEER  (rear tires slipping, car rotates past steering)
over_under = sideslip_deg.copy()

# Sanity check: clip extreme values (real sideslip > 10 deg = spin, not cornering)
over_under = np.clip(over_under, -10, 10)

# -- Find best lap ---------------------------------------------------------
valid_laps = pd.Series(lap_col).dropna()
valid_laps = valid_laps[valid_laps > 0].unique()
best_lap, best_time = None, np.inf
for lap_num in valid_laps:
    mask = lap_col == lap_num
    t = time_s[mask]
    if len(t) < 10:
        continue
    lt = t[-1] - t[0]
    if 10 < lt < best_time:
        best_time = lt
        best_lap = int(lap_num)

print(f"Best lap: #{best_lap}  ({best_time:.3f}s)")

# -- Extract best lap ------------------------------------------------------
m = lap_col == best_lap
lap_dist     = dist[m] - dist[m][0]
lap_kin      = kinematic_steer[m]
lap_actual   = actual_steer[m]
lap_ou       = over_under[m]
lap_speed    = speed_filt[m]
lap_a_lat    = a_lat_filt[m]
lap_ss_rate  = np.interp(time_s, time_ds, sideslip_rate_ds)[m]

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
ax1.plot(lap_dist, lap_kin, color="#949494", linewidth=0.7, alpha=0.6,
         label="Kinematic (GPS, no-slip)")
ax1.plot(lap_dist, lap_actual, color="#F0EDE5", linewidth=0.9,
         label="Actual (GPS + gyro sideslip)")
ax1.fill_between(lap_dist, lap_kin, lap_actual,
                 where=lap_actual > lap_kin,
                 color="#FF2A2A", alpha=0.25, label="Understeer")
ax1.fill_between(lap_dist, lap_kin, lap_actual,
                 where=lap_actual < lap_kin,
                 color="#8B5CF6", alpha=0.25, label="Oversteer")
ax1.axhline(0, color="#949494", linewidth=0.4, linestyle="--")
ax1.set_ylabel("Steering (deg)", color="#F0EDE5", fontsize=10)
ax1.set_title(
    f"Kinematic vs Actual Steering + Over/Understeer -- Lap #{best_lap}  ({best_time:.2f}s)\n"
    f"Sideslip from chassis gyro Z vs GPS bearing rate",
    color="#F0EDE5", fontsize=12, pad=10
)
ax1.legend(loc="upper right", facecolor="#1a1a1a", edgecolor="#333",
           labelcolor="#F0EDE5", fontsize=8, ncol=2)

# Panel 2: Over/understeer magnitude
ax2 = axes[1]
ax2.fill_between(lap_dist, lap_ou, 0,
                 where=lap_ou > 0, color="#FF2A2A", alpha=0.4, label="Understeer")
ax2.fill_between(lap_dist, lap_ou, 0,
                 where=lap_ou < 0, color="#8B5CF6", alpha=0.4, label="Oversteer")
ax2.plot(lap_dist, lap_ou, color="#F0EDE5", linewidth=0.6)
ax2.axhline(0, color="#949494", linewidth=0.4, linestyle="--")
ax2.set_ylabel("Over/Under (deg)", color="#F0EDE5", fontsize=10)
ax2.legend(loc="upper right", facecolor="#1a1a1a", edgecolor="#333",
           labelcolor="#F0EDE5", fontsize=8)

# Panel 3: Speed
ax3 = axes[2]
ax3.plot(lap_dist, lap_speed * 3.6, color="#22C55E", linewidth=0.8)
ax3.set_ylabel("Speed (km/h)", color="#F0EDE5", fontsize=10)

# Panel 4: Lateral G
ax4 = axes[3]
ax4.plot(lap_dist, lap_a_lat, color="#C9A84C", linewidth=0.8)
ax4.set_ylabel("Lat G", color="#F0EDE5", fontsize=10)
ax4.set_xlabel("Distance (m)", color="#F0EDE5", fontsize=11)

plt.tight_layout()
out_path = str(pathlib.Path(__file__).resolve().parents[1] / "artifacts" / "steering_v3_over_understeer.png")
plt.savefig(out_path, dpi=150, facecolor=fig.get_facecolor())
plt.close()
print(f"\nSaved to {out_path}")
