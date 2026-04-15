"""
Estimate steering angle from GPS-only data using the bicycle model.

Uses ONLY Earth-frame (GPS-derived) channels to avoid sensor-mounting
issues.  The RaceBox / phone IMU is typically mounted on the steering
column at ~30-40° tilt — raw gyro axes do NOT align with vehicle yaw.

Approach:
  1. Yaw rate  ← d(GPS bearing) / dt   (Earth frame, no alignment needed)
  2. Speed     ← GPS speed (*calc)
  3. Lat accel ← GPS-derived (*calc)    (already in vehicle travel frame)
  4. Butterworth low-pass at 1.5 Hz     (kart steering bandwidth limit)
  5. Bicycle model:  δ = arctan(L × ψ̇ / V)

Reads a RaceChrono CSV, finds the best lap, plots steering angle vs distance.
"""
import sys, pathlib
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.signal import butter, filtfilt

# ── Config ────────────────────────────────────────────────────────────
WHEELBASE   = 1.0       # metres (kart)
V_MIN       = 2.0       # m/s — blank below this (singularity guard)
LPF_CUTOFF  = 1.5       # Hz — Butterworth cutoff (kart steering bandwidth)
LPF_ORDER   = 2         # 2nd-order Butterworth (12 dB/oct rolloff)

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

df = pd.read_csv(csv_path, skiprows=header_row)
df.columns = df.columns.str.strip()

print(f"Loaded {csv_path}: {len(df)} rows x {len(df.columns)} cols")

# ── Extract GPS-only channels (Earth frame) ───────────────────────────
time_s  = pd.to_numeric(df["Time (s)"], errors="coerce").values
speed   = pd.to_numeric(df.get("Speed (m/s) *calc", df.get("Speed (m/s)")), errors="coerce").values
lap_col = pd.to_numeric(df["Lap #"], errors="coerce").values
dist    = pd.to_numeric(df["Distance (m)"], errors="coerce").values
bearing = pd.to_numeric(df["Bearing (deg)"], errors="coerce").values

# GPS-derived lateral accel (already in vehicle travel frame, not sensor frame)
a_lat_g = pd.to_numeric(df.get("Lateral acceleration (G) *calc",
                                df.get("Lateral acceleration (G)")), errors="coerce").values

# ── Derive yaw rate from GPS bearing (Earth frame) ───────────────────
# This is the key fix: bearing is measured by GPS in the Earth frame,
# so it doesn't matter how the sensor is mounted or tilted.
dt = np.diff(time_s, prepend=time_s[0])
dt[dt == 0] = 1e-6

dbearing = np.diff(bearing, prepend=bearing[0])
# Unwrap heading wrap-around (e.g. 359° → 1° = +2°, not -358°)
dbearing = (dbearing + 180) % 360 - 180

yaw_dps = dbearing / dt
print("Yaw rate derived from GPS bearing (Earth frame — sensor-mount independent)")

# ── Butterworth low-pass filter ──────────────────────────────────────
# GPS bearing at 25 Hz gives a raw yaw rate that's noisy from position
# quantisation.  A kart's steering physically can't change faster than
# ~1.5 Hz (arms + direct steering), so we cut everything above that.
dt_median = np.nanmedian(np.diff(time_s))
fs = 1.0 / dt_median if dt_median > 0 else 25.0

nyquist = fs / 2.0
normalised_cutoff = min(LPF_CUTOFF / nyquist, 0.99)  # guard against edge
b, a = butter(LPF_ORDER, normalised_cutoff, btype="low")

# Fill NaNs before filtering (filtfilt can't handle them)
yaw_clean = pd.Series(yaw_dps).interpolate(limit_direction="both").values
yaw_smooth = filtfilt(b, a, yaw_clean)

# Also smooth the lateral G and speed for a cleaner plot
a_lat_clean = pd.Series(a_lat_g).interpolate(limit_direction="both").values
a_lat_smooth = filtfilt(b, a, a_lat_clean)

speed_clean = pd.Series(speed).interpolate(limit_direction="both").values
speed_smooth = filtfilt(b, a, speed_clean)

print(f"Butterworth LP: order={LPF_ORDER}, cutoff={LPF_CUTOFF} Hz, fs={fs:.1f} Hz")

# ── Bicycle model: steering angle ────────────────────────────────────
yaw_rps = np.deg2rad(yaw_smooth)   # deg/s → rad/s
speed_safe = np.where(speed_smooth > V_MIN, speed_smooth, np.nan)

# δ = arctan(L × ψ̇ / V)   — no understeer correction for kart (K_us ≈ 0)
steer_rad = np.arctan(WHEELBASE * yaw_rps / speed_safe)
steer_deg = np.rad2deg(steer_rad)

# ── Find best lap ────────────────────────────────────────────────────
laps = pd.Series(lap_col)
valid_laps = laps[laps > 0].dropna().unique()

best_lap = None
best_time = np.inf

for lap_num in valid_laps:
    mask = lap_col == lap_num
    t = time_s[mask]
    if len(t) < 10:
        continue
    lap_time = t[-1] - t[0]
    if 10 < lap_time < best_time:   # sanity: at least 10s
        best_time = lap_time
        best_lap = int(lap_num)

print(f"\nBest lap: #{best_lap}  ({best_time:.3f}s)")

# ── Extract best lap data ────────────────────────────────────────────
mask = lap_col == best_lap
lap_dist  = dist[mask]
lap_steer = steer_deg[mask]
lap_speed = speed_smooth[mask]
lap_time  = time_s[mask]
lap_a_lat = a_lat_smooth[mask]

# Normalise distance to start at 0
lap_dist = lap_dist - lap_dist[0]

# ── Plot ─────────────────────────────────────────────────────────────
fig, axes = plt.subplots(3, 1, figsize=(14, 8), sharex=True,
                         gridspec_kw={"height_ratios": [3, 1.5, 1.5]})
fig.patch.set_facecolor("#0a0a0a")

for ax in axes:
    ax.set_facecolor("#141414")
    ax.tick_params(colors="#949494")
    ax.spines["bottom"].set_color("#333")
    ax.spines["left"].set_color("#333")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

# --- Steering angle ---
ax1 = axes[0]
ax1.fill_between(lap_dist, lap_steer, 0, where=lap_steer > 0,
                 color="#C9A84C", alpha=0.3, label="Right")
ax1.fill_between(lap_dist, lap_steer, 0, where=lap_steer < 0,
                 color="#8B5CF6", alpha=0.3, label="Left")
ax1.plot(lap_dist, lap_steer, color="#F0EDE5", linewidth=0.8)
ax1.axhline(0, color="#949494", linewidth=0.5, linestyle="--")
ax1.set_ylabel("Estimated Steering Angle (deg)", color="#F0EDE5", fontsize=11)
ax1.set_title(
    f"Estimated Steering Angle — Best Lap #{best_lap}  ({best_time:.2f}s)\n"
    f"GPS-only bicycle model: δ = arctan(L·ψ̇/V),  L = {WHEELBASE}m,  LP {LPF_CUTOFF}Hz",
    color="#F0EDE5", fontsize=13, pad=12
)
ax1.legend(loc="upper right", facecolor="#1a1a1a", edgecolor="#333",
           labelcolor="#F0EDE5", fontsize=9)

# --- Speed ---
ax2 = axes[1]
ax2.plot(lap_dist, lap_speed * 3.6, color="#22C55E", linewidth=0.8)
ax2.set_ylabel("Speed (km/h)", color="#F0EDE5", fontsize=10)

# --- Lateral G ---
ax3 = axes[2]
ax3.plot(lap_dist, lap_a_lat, color="#C9A84C", linewidth=0.8)
ax3.set_ylabel("Lat G", color="#F0EDE5", fontsize=10)
ax3.set_xlabel("Distance (m)", color="#F0EDE5", fontsize=11)

plt.tight_layout()
plt.savefig(str(pathlib.Path(__file__).resolve().parents[1] / "artifacts" / "steering_angle_best_lap.png"),
            dpi=150, facecolor=fig.get_facecolor())
plt.show()
print("\nSaved to artifacts/steering_angle_best_lap.png")
