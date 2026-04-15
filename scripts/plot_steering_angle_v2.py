"""
Sensor-fusion approach: extract ACTUAL steering angle from all 3 sensors.

Previous approach (GPS bicycle model):
  - Computes what the steering angle SHOULD HAVE BEEN given the trajectory
  - Smooth but reconstructed — not measured

This approach:
  - Uses raw IMU (accel + gyro) to MEASURE what the steering IS
  - Accelerometer -> detect sensor mounting orientation via gravity at rest
  - Gyroscope     -> raw rotation includes vehicle yaw + steering rotation
  - GPS bearing   -> vehicle yaw rate (Earth frame, no mounting bias)
  - Steering rate = gyro_along_column_axis - vehicle_yaw_projected_onto_column_axis
  - Complementary filter: gyro gives fast detail, GPS anchors against drift
"""
import sys, pathlib
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.signal import butter, filtfilt

# ── Config ────────────────────────────────────────────────────────────
WHEELBASE       = 1.0     # metres (kart)
V_MIN           = 2.0     # m/s — blank below this
LPF_CUTOFF      = 3.0     # Hz — cutoff for final steering signal
LPF_ORDER       = 2       # Butterworth order
COMPL_TAU       = 2.0     # seconds — complementary filter time constant
REST_SPEED_THR  = 0.5     # m/s — "at rest" threshold for gravity calibration
REST_N_SAMPLES  = 200     # how many rest samples to average for gravity

# ── Load CSV ──────────────────────────────────────────────────────────
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
# Pandas appends .1, .2 etc for duplicate column names
cols = list(df.columns)
print(f"Loaded {csv_path}: {len(df)} rows x {len(cols)} cols")

# ── Extract GPS channels (Earth frame) ────────────────────────────────
time_s  = pd.to_numeric(df.iloc[:, 0], errors="coerce").values   # Time (s)
speed   = pd.to_numeric(df.get("Speed (m/s) *calc", df.get("Speed (m/s)")), errors="coerce").values
lap_col = pd.to_numeric(df["Lap #"], errors="coerce").values
dist    = pd.to_numeric(df["Distance (m)"], errors="coerce").values
bearing = pd.to_numeric(df["Bearing (deg)"], errors="coerce").values
a_lat_g = pd.to_numeric(df.get("Lateral acceleration (G) *calc"), errors="coerce").values

# ── Extract raw IMU channels ─────────────────────────────────────────
# Two sensor sets: indices by column position from the header
# Set A (cols 24-27): phone IMU at ~95 Hz
# Set B (cols 28-31): RaceBox IMU at ~25 Hz
# We need to find them by position since names are duplicated

# Find all accel and gyro column indices
acc_x_indices = [i for i, c in enumerate(cols) if "X acceleration" in str(c)]
acc_y_indices = [i for i, c in enumerate(cols) if "Y acceleration" in str(c)]
acc_z_indices = [i for i, c in enumerate(cols) if "Z acceleration" in str(c)]
gyr_x_indices = [i for i, c in enumerate(cols) if "X rate of rotation" in str(c)]
gyr_y_indices = [i for i, c in enumerate(cols) if "Y rate of rotation" in str(c)]
gyr_z_indices = [i for i, c in enumerate(cols) if "Z rate of rotation" in str(c)]

print(f"Found {len(acc_x_indices)} accel sensor sets, {len(gyr_x_indices)} gyro sensor sets")

# Load both sensor sets
sensors = []
for s in range(min(len(acc_x_indices), len(gyr_x_indices))):
    ax = pd.to_numeric(df.iloc[:, acc_x_indices[s]], errors="coerce").values
    ay = pd.to_numeric(df.iloc[:, acc_y_indices[s]], errors="coerce").values
    az = pd.to_numeric(df.iloc[:, acc_z_indices[s]], errors="coerce").values
    gx = pd.to_numeric(df.iloc[:, gyr_x_indices[s]], errors="coerce").values
    gy = pd.to_numeric(df.iloc[:, gyr_y_indices[s]], errors="coerce").values
    gz = pd.to_numeric(df.iloc[:, gyr_z_indices[s]], errors="coerce").values

    # Check gravity magnitude at rest to identify valid sensor
    rest_mask = speed < REST_SPEED_THR
    rest_idx = np.where(rest_mask)[0][:REST_N_SAMPLES]
    if len(rest_idx) < 20:
        rest_idx = np.arange(min(REST_N_SAMPLES, len(ax)))

    grav = np.array([
        np.nanmedian(ax[rest_idx]),
        np.nanmedian(ay[rest_idx]),
        np.nanmedian(az[rest_idx]),
    ])
    grav_mag = np.linalg.norm(grav)

    sensors.append({
        "ax": ax, "ay": ay, "az": az,
        "gx": gx, "gy": gy, "gz": gz,
        "grav": grav, "grav_mag": grav_mag,
        "label": f"Sensor {s} (col {acc_x_indices[s]})",
    })
    print(f"  Sensor {s}: gravity at rest = [{grav[0]:.3f}, {grav[1]:.3f}, {grav[2]:.3f}] G  |g| = {grav_mag:.3f} G")

# ── Pick the sensor that's on the steering ────────────────────────────
# The one on the steering column has gravity pointing SIDEWAYS (column is tilted)
# i.e. gravity is NOT along Z — it's distributed across axes.
# The chassis-mounted one has gravity ~= [0, 0, 1] (Z pointing up).
#
# Metric: how far is gravity from pure-Z?  Higher = more tilted = likely on steering
tilt_scores = []
for s in sensors:
    g = s["grav"]
    gn = g / (s["grav_mag"] + 1e-9)
    # Angle between gravity and sensor Z-axis
    tilt_from_z = np.degrees(np.arccos(np.clip(abs(gn[2]), 0, 1)))
    s["tilt_from_z"] = tilt_from_z
    tilt_scores.append(tilt_from_z)
    print(f"  {s['label']}: tilt from Z = {tilt_from_z:.1f} deg")

# The more tilted sensor is likely on the steering column
steering_idx = int(np.argmax(tilt_scores))
chassis_idx  = 1 - steering_idx if len(sensors) > 1 else 0
steer_sensor = sensors[steering_idx]
print(f"\n> Using {steer_sensor['label']} as STEERING sensor (tilt={steer_sensor['tilt_from_z']:.1f} deg)")
if len(sensors) > 1:
    print(f"  {sensors[chassis_idx]['label']} appears chassis-mounted (tilt={sensors[chassis_idx]['tilt_from_z']:.1f} deg)")

# ── Step 1: Determine steering column axis from gravity ───────────────
# At rest, the gravity vector in sensor frame tells us the sensor orientation.
# The steering column axis is approximately the sensor's mounting axis.
# For a sensor strapped to the column, gravity direction reveals the tilt.
g_sensor = steer_sensor["grav"]
g_norm = g_sensor / (np.linalg.norm(g_sensor) + 1e-9)

# The column axis in sensor frame: perpendicular to gravity and aligned
# with the axis that has the most gravity component (after Z).
# For a tilted column, gravity has a large component along the "forward"
# axis of the sensor.
#
# Column axis ~= the sensor axis most aligned with "up" minus gravity
# Simplified: we define the column axis as the sensor axis that would
# point UP if the sensor were level. For typical phone/RaceBox mounts,
# this is usually the Y or Z axis.
#
# Actually, the most robust approach: the steering rotation axis is the
# axis around which the gyro shows the MOST variance during corners
# (because that's where steering changes most), after removing vehicle yaw.

# First, let's compute the column tilt angle
column_tilt = np.radians(steer_sensor["tilt_from_z"])
print(f"  Column tilt from vertical: {np.degrees(column_tilt):.1f} deg")

# ── Step 2: Vehicle yaw rate from GPS (Earth frame) ───────────────────
dt = np.diff(time_s, prepend=time_s[0])
dt[dt == 0] = 1e-6

dbearing = np.diff(bearing, prepend=bearing[0])
dbearing = (dbearing + 180) % 360 - 180  # unwrap
yaw_gps_dps = dbearing / dt

# ── Step 3: Project vehicle yaw onto each gyro axis ──────────────────
# Vehicle yaw (rotation around Earth Z) projects into sensor frame based
# on how the sensor is tilted.
#
# If sensor Z is tilted by θ from vertical:
#   - Vehicle yaw projects onto sensor Z as: yaw × cos(θ)
#   - Vehicle yaw projects onto sensor X or Y as: yaw × sin(θ)
#
# The steering rotation is AROUND the column axis. For a sensor mounted
# on the steering, the column axis is approximately the sensor axis that
# is most tilted from vertical.
#
# Strategy: try each gyro axis as the potential "steering axis",
# subtract the projected vehicle yaw, and see which gives the most
# physically plausible steering signal.

gx = steer_sensor["gx"]
gy = steer_sensor["gy"]
gz = steer_sensor["gz"]

# Build rotation matrix from gravity to determine axis alignment
# g_norm tells us which way is "down" in sensor frame
# The column/steering axis is the one that captures steering rotation

# For each axis, compute the angle between that axis and gravity
axis_gravity_angles = {
    "X": np.degrees(np.arccos(np.clip(abs(g_norm[0]), 0, 1))),
    "Y": np.degrees(np.arccos(np.clip(abs(g_norm[1]), 0, 1))),
    "Z": np.degrees(np.arccos(np.clip(abs(g_norm[2]), 0, 1))),
}
print(f"  Axis-gravity angles: X={axis_gravity_angles['X']:.1f} deg, "
      f"Y={axis_gravity_angles['Y']:.1f} deg, Z={axis_gravity_angles['Z']:.1f} deg")

# The steering column axis is most perpendicular to gravity (closest to
# horizontal) AND shows the most rotational variance during driving.
# For a kart column tilted ~30-40 deg forward, the column axis is roughly
# the sensor axis closest to 60-70 deg from gravity (i.e., 20-30 deg from horizontal).

# Compute projection of vehicle yaw onto each sensor axis
# Vehicle yaw is around Earth-Z. In sensor frame:
#   projection onto sensor axis i = cos(angle between sensor_i and Earth-Z)
# Earth-Z in sensor frame ~= -g_norm (gravity points down = -Z_earth)
proj_x = abs(g_norm[0])  # cos(angle between sensor X and Earth Z)
proj_y = abs(g_norm[1])
proj_z = abs(g_norm[2])

# For each gyro axis, subtract the projected vehicle yaw
# and compute the steering rate candidate
candidates = {}
for name, gyro_raw, proj_factor in [
    ("X", gx, proj_x), ("Y", gy, proj_y), ("Z", gz, proj_z)
]:
    # Steering rate = raw gyro - vehicle_yaw projected onto this axis
    # The sign depends on axis alignment — we'll check both signs
    steer_rate_pos = gyro_raw - yaw_gps_dps * proj_factor
    steer_rate_neg = gyro_raw + yaw_gps_dps * proj_factor

    # The correct one should have lower variance on straights
    # (where steering ~= 0) and higher variance in corners
    straight_mask = (abs(a_lat_g) < 0.1) & (speed > 5.0)
    corner_mask   = (abs(a_lat_g) > 0.3) & (speed > 5.0)

    for sign_label, sr in [("pos", steer_rate_pos), ("neg", steer_rate_neg)]:
        straight_std = np.nanstd(sr[straight_mask]) if straight_mask.sum() > 100 else 999
        corner_std   = np.nanstd(sr[corner_mask]) if corner_mask.sum() > 100 else 0
        # Good candidate: low straight variance, high corner variance
        ratio = corner_std / (straight_std + 1e-6)
        candidates[f"{name}_{sign_label}"] = {
            "rate": sr,
            "straight_std": straight_std,
            "corner_std": corner_std,
            "ratio": ratio,
        }

# Pick the axis+sign with the best corner/straight ratio
best_key = max(candidates, key=lambda k: candidates[k]["ratio"])
best_cand = candidates[best_key]
steer_rate_raw = best_cand["rate"]

print(f"\n  Best steering axis: {best_key}")
print(f"    Straight std = {best_cand['straight_std']:.1f} deg/s")
print(f"    Corner std   = {best_cand['corner_std']:.1f} deg/s")
print(f"    Ratio       = {best_cand['ratio']:.2f}")

# Show all candidates for reference
print("\n  All candidates (corner/straight ratio):")
for k, v in sorted(candidates.items(), key=lambda x: -x[1]["ratio"]):
    marker = " <- SELECTED" if k == best_key else ""
    print(f"    {k}: ratio={v['ratio']:.2f}  (straight={v['straight_std']:.1f}, corner={v['corner_std']:.1f}){marker}")

# ── Step 4: Filter + integrate steering rate -> angle ──────────────────
dt_median = np.nanmedian(np.diff(time_s))
fs = 1.0 / dt_median if dt_median > 0 else 25.0
nyquist = fs / 2.0

# Low-pass the steering rate to remove high-freq vibration
cutoff_norm = min(LPF_CUTOFF / nyquist, 0.99)
b_lp, a_lp = butter(LPF_ORDER, cutoff_norm, btype="low")
steer_rate_clean = pd.Series(steer_rate_raw).interpolate(limit_direction="both").values
steer_rate_filt  = filtfilt(b_lp, a_lp, steer_rate_clean)

# Integrate rate -> angle (trapezoidal)
dt_arr = np.diff(time_s, prepend=time_s[0])
dt_arr[dt_arr <= 0] = dt_median
steer_angle_integrated = np.cumsum(steer_rate_filt * dt_arr)

# ── Step 5: Complementary filter with GPS bicycle model ───────────────
# The integrated gyro drifts over time. The GPS bicycle model doesn't
# drift but has lower bandwidth.
#
# Complementary filter:
#   steer_final = HPF(gyro_integrated) + LPF(gps_bicycle_model)
#
# This gives us:
#   - High-frequency detail from the actual sensor measurement
#   - Absolute reference from GPS (no drift)

# GPS bicycle model (same as v1 but used only as drift anchor)
yaw_gps_clean = pd.Series(yaw_gps_dps).interpolate(limit_direction="both").values
yaw_gps_smooth = filtfilt(b_lp, a_lp, yaw_gps_clean)
yaw_rps = np.deg2rad(yaw_gps_smooth)
speed_clean = pd.Series(speed).interpolate(limit_direction="both").values
speed_smooth = filtfilt(b_lp, a_lp, speed_clean)
speed_safe = np.where(speed_smooth > V_MIN, speed_smooth, np.nan)
gps_steer_rad = np.arctan(WHEELBASE * yaw_rps / speed_safe)
gps_steer_deg = np.rad2deg(gps_steer_rad)
# Fill NaNs (low speed) with 0
gps_steer_deg = np.nan_to_num(gps_steer_deg, nan=0.0)

# Complementary filter coefficients
alpha_compl = dt_median / (COMPL_TAU + dt_median)  # ~0.002 for tau=2s, dt=0.004s

steer_fused = np.zeros(len(time_s))
steer_fused[0] = gps_steer_deg[0]
for i in range(1, len(time_s)):
    # High-pass: integrate gyro rate for fast changes
    gyro_update = steer_fused[i-1] + steer_rate_filt[i] * dt_arr[i]
    # Low-pass: pull toward GPS model to kill drift
    steer_fused[i] = (1 - alpha_compl) * gyro_update + alpha_compl * gps_steer_deg[i]

print(f"\nComplementary filter: tau={COMPL_TAU}s, alpha={alpha_compl:.4f}")

# ── Find best lap ────────────────────────────────────────────────────
laps = pd.Series(lap_col)
valid_laps = laps[laps > 0].dropna().unique()
best_lap, best_time = None, np.inf
for lap_num in valid_laps:
    mask = lap_col == lap_num
    t = time_s[mask]
    if len(t) < 10:
        continue
    lap_time = t[-1] - t[0]
    if 10 < lap_time < best_time:
        best_time = lap_time
        best_lap = int(lap_num)

print(f"Best lap: #{best_lap}  ({best_time:.3f}s)")

# ── Extract best lap data ────────────────────────────────────────────
mask = lap_col == best_lap
lap_dist       = dist[mask] - dist[mask][0]
lap_fused      = steer_fused[mask]
lap_gps        = gps_steer_deg[mask]
lap_speed      = speed_smooth[mask]
lap_a_lat      = pd.Series(a_lat_g).interpolate(limit_direction="both").values[mask]
lap_a_lat_filt = filtfilt(b_lp, a_lp,
                          pd.Series(a_lat_g).interpolate(limit_direction="both").values)[mask]

# ── Plot: 3 panels ───────────────────────────────────────────────────
fig, axes = plt.subplots(3, 1, figsize=(14, 9), sharex=True,
                         gridspec_kw={"height_ratios": [3, 1.5, 1.5]})
fig.patch.set_facecolor("#0a0a0a")

for ax in axes:
    ax.set_facecolor("#141414")
    ax.tick_params(colors="#949494")
    ax.spines["bottom"].set_color("#333")
    ax.spines["left"].set_color("#333")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

# --- Steering angle: fused (measured) vs GPS-only (reconstructed) ---
ax1 = axes[0]
# GPS bicycle model (ghost, for comparison)
ax1.plot(lap_dist, lap_gps, color="#949494", linewidth=0.6, alpha=0.4,
         label="GPS bicycle model (reconstructed)")
# Fused: actual measurement
ax1.fill_between(lap_dist, lap_fused, 0, where=lap_fused > 0,
                 color="#C9A84C", alpha=0.3)
ax1.fill_between(lap_dist, lap_fused, 0, where=lap_fused < 0,
                 color="#8B5CF6", alpha=0.3)
ax1.plot(lap_dist, lap_fused, color="#F0EDE5", linewidth=0.9,
         label="Sensor-fused (measured)")
ax1.axhline(0, color="#949494", linewidth=0.5, linestyle="--")
ax1.set_ylabel("Steering Angle (deg)", color="#F0EDE5", fontsize=11)
ax1.set_title(
    f"Measured vs Reconstructed Steering — Best Lap #{best_lap}  ({best_time:.2f}s)\n"
    f"IMU sensor fusion (accel+gyro+GPS complementary filter, τ={COMPL_TAU}s)",
    color="#F0EDE5", fontsize=12, pad=12
)
ax1.legend(loc="upper right", facecolor="#1a1a1a", edgecolor="#333",
           labelcolor="#F0EDE5", fontsize=9)

# --- Speed ---
ax2 = axes[1]
ax2.plot(lap_dist, lap_speed * 3.6, color="#22C55E", linewidth=0.8)
ax2.set_ylabel("Speed (km/h)", color="#F0EDE5", fontsize=10)

# --- Lateral G ---
ax3 = axes[2]
ax3.plot(lap_dist, lap_a_lat_filt, color="#C9A84C", linewidth=0.8)
ax3.set_ylabel("Lat G", color="#F0EDE5", fontsize=10)
ax3.set_xlabel("Distance (m)", color="#F0EDE5", fontsize=11)

plt.tight_layout()
out_path = str(pathlib.Path(__file__).resolve().parents[1] / "artifacts" / "steering_angle_v2_fused.png")
plt.savefig(out_path, dpi=150, facecolor=fig.get_facecolor())
plt.show()
print(f"\nSaved to {out_path}")
