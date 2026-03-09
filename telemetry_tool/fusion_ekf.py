"""
fusion_ekf.py
-------------
EKF-lite sensor fusion for GPS + IMU telemetry data.

Fuses GPS position/velocity with IMU accel/gyro into a stabilized
5-state estimate: [x, y, v, heading, yaw_rate].

Inserted as pipeline stage 2.5 — after GPS filtering (stage 2),
before derived channels (stage 3). Overwrites raw columns in-place
so downstream consumers get fused signals for free.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── Column name constants ──────────────────────────────────────────
_COL_LAT = "Latitude (deg)"
_COL_LON = "Longitude (deg)"
_COL_SPEED = "Speed (m/s)"
_COL_BEARING = "Bearing (deg)"
_COL_TIME = "Time (s)"
_COL_ACCEL_LONG = "Longitudinal acceleration (G) *calc"
_COL_ACCEL_LAT = "Lateral acceleration (G) *calc"
_COL_YAW = "Yaw rate (deg/s)"

_G = 9.80665  # m/s^2


@dataclass
class FusionResult:
    """Metadata from sensor fusion run."""
    method: str                         # "ekf" | "smoothing_only" | "passthrough"
    sensors_used: list[str] = field(default_factory=list)
    confidence: float = 0.0             # 0-1
    n_samples: int = 0
    innovation_rms: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def detect_available_sensors(df: "pd.DataFrame") -> set[str]:
    """Detect which sensor groups are available in the DataFrame.

    Returns a set of sensor group names:
    - "gps_pos": Latitude + Longitude present
    - "gps_speed": Speed present
    - "gps_bearing": Bearing present
    - "imu_accel": Longitudinal + Lateral accel present
    - "imu_gyro": Yaw rate present
    """
    cols = set(df.columns)
    sensors: set[str] = set()

    if _COL_LAT in cols and _COL_LON in cols:
        sensors.add("gps_pos")
    if _COL_SPEED in cols:
        sensors.add("gps_speed")
    if _COL_BEARING in cols:
        sensors.add("gps_bearing")
    if _COL_ACCEL_LONG in cols and _COL_ACCEL_LAT in cols:
        sensors.add("imu_accel")
    if _COL_YAW in cols:
        sensors.add("imu_gyro")

    return sensors


@dataclass
class EKFState:
    """EKF state: x=[x, y, v, heading, yaw_rate], P=covariance."""
    x: np.ndarray      # shape (5,)
    P: np.ndarray       # shape (5, 5)


def ekf_predict(state: EKFState, dt: float, a_long: float,
                process_noise_scale: float = 1.0) -> EKFState:
    """EKF predict step using constant-yaw-rate kinematic model.

    State: [x, y, v, heading, yaw_rate]
    x' = x + v*cos(heading)*dt
    y' = y + v*sin(heading)*dt
    v' = v + a_long*dt
    heading' = heading + yaw_rate*dt
    yaw_rate' = yaw_rate
    """
    x, y, v, hdg, yr = state.x

    # State transition
    x_new = np.array([
        x + v * np.cos(hdg) * dt,
        y + v * np.sin(hdg) * dt,
        v + a_long * dt,
        hdg + yr * dt,
        yr,
    ])

    # Jacobian F = df/dx
    F = np.eye(5)
    F[0, 2] = np.cos(hdg) * dt        # dx/dv
    F[0, 3] = -v * np.sin(hdg) * dt   # dx/dhdg
    F[1, 2] = np.sin(hdg) * dt        # dy/dv
    F[1, 3] = v * np.cos(hdg) * dt    # dy/dhdg
    F[3, 4] = dt                       # dhdg/dyr

    # Process noise Q — scaled by dt
    q = process_noise_scale
    Q = np.diag([
        (q * dt) ** 2 * 0.5,    # position x
        (q * dt) ** 2 * 0.5,    # position y
        (1.0 * dt) ** 2,        # velocity
        (0.1 * dt) ** 2,        # heading
        (0.1 * dt) ** 2,        # yaw_rate
    ])

    P_new = F @ state.P @ F.T + Q

    return EKFState(x=x_new, P=P_new)


def ekf_update(state: EKFState, z: np.ndarray,
               H: np.ndarray, R: np.ndarray
               ) -> tuple[EKFState, np.ndarray]:
    """EKF update (measurement correction) step.

    Parameters
    ----------
    state : Current EKF state.
    z : Measurement vector.
    H : Measurement matrix (maps state to measurement space).
    R : Measurement noise covariance.

    Returns
    -------
    (updated_state, innovation)
    """
    # Innovation
    y = z - H @ state.x
    S = H @ state.P @ H.T + R

    # Kalman gain
    K = state.P @ H.T @ np.linalg.inv(S)

    # State update
    x_new = state.x + K @ y
    P_new = (np.eye(len(state.x)) - K @ H) @ state.P

    return EKFState(x=x_new, P=P_new), y


# ── Coordinate conversion ──────────────────────────────────────────
_R_EARTH = 6_371_000.0  # metres


def latlon_to_local(lat: float, lon: float,
                    lat0: float, lon0: float) -> tuple[float, float]:
    """Convert lat/lon to local x,y (metres) relative to reference point.

    Uses equirectangular approximation (accurate within ~10km).
    x = east, y = north.
    """
    lat_r = np.radians(lat)
    lat0_r = np.radians(lat0)
    lon_r = np.radians(lon)
    lon0_r = np.radians(lon0)

    x = _R_EARTH * (lon_r - lon0_r) * np.cos((lat0_r + lat_r) / 2)
    y = _R_EARTH * (lat_r - lat0_r)
    return float(x), float(y)


def local_to_latlon(x: float, y: float,
                    lat0: float, lon0: float) -> tuple[float, float]:
    """Convert local x,y (metres) back to lat/lon."""
    lat0_r = np.radians(lat0)
    lat = lat0 + np.degrees(y / _R_EARTH)
    lon = lon0 + np.degrees(x / (_R_EARTH * np.cos(lat0_r)))
    return float(lat), float(lon)


def _estimate_measurement_noise(df: "pd.DataFrame", sensors: set[str]) -> dict[str, float]:
    """Estimate measurement noise from first ~100 samples."""
    import pandas as pd
    n = min(100, len(df))
    noise = {}

    if "gps_pos" in sensors:
        lat = pd.to_numeric(df[_COL_LAT].iloc[:n], errors="coerce")
        lon = pd.to_numeric(df[_COL_LON].iloc[:n], errors="coerce")
        # Position noise ~ std of second differences (removes trend)
        if len(lat) > 10:
            lat_dd = np.diff(np.diff(lat.values))
            noise["pos_m"] = max(float(np.nanstd(lat_dd)) * 111_320, 1.0)
        else:
            noise["pos_m"] = 5.0

    if "gps_speed" in sensors:
        spd = pd.to_numeric(df[_COL_SPEED].iloc[:n], errors="coerce")
        noise["speed_mps"] = max(float(spd.diff().std()), 0.1)

    if "gps_bearing" in sensors:
        brg = pd.to_numeric(df[_COL_BEARING].iloc[:n], errors="coerce")
        noise["bearing_deg"] = max(float(brg.diff().std()), 1.0)

    if "imu_gyro" in sensors:
        yaw = pd.to_numeric(df[_COL_YAW].iloc[:n], errors="coerce")
        noise["yaw_dps"] = max(float(yaw.std()), 0.5)

    return noise


def _smoothing_only(df: "pd.DataFrame", sensors: set[str]) -> "pd.DataFrame":
    """Fallback: Gaussian smoothing when no IMU for EKF."""
    result = df.copy()

    if "gps_bearing" in sensors and _COL_BEARING in result.columns:
        import pandas as pd
        brg = pd.to_numeric(result[_COL_BEARING], errors="coerce").values
        result[_COL_BEARING] = _gaussian_smooth(brg, 3)

    if _COL_SPEED in result.columns:
        import pandas as pd
        spd = pd.to_numeric(result[_COL_SPEED], errors="coerce").values
        result[_COL_SPEED] = _gaussian_smooth(spd, 2)

    return result


def _gaussian_smooth(arr: np.ndarray, half_window: int) -> np.ndarray:
    """Simple 1-D Gaussian smoothing."""
    if half_window < 1 or len(arr) < 3:
        return arr.copy()
    k = 2 * half_window + 1
    w = np.exp(-0.5 * (np.arange(k) - half_window) ** 2 / max(half_window / 2, 0.5) ** 2)
    w /= w.sum()

    finite = np.isfinite(arr)
    working = arr.copy()
    if not finite.all() and finite.sum() >= 2:
        working[~finite] = np.interp(
            np.where(~finite)[0], np.where(finite)[0], arr[finite])

    padded = np.pad(working, half_window, mode="reflect")
    out = np.convolve(padded, w, mode="valid")[:len(arr)]
    out[~finite] = np.nan
    return out


def run_sensor_fusion(
    df: "pd.DataFrame",
    *,
    config: "Optional[dict]" = None,
) -> "tuple[pd.DataFrame, FusionResult]":
    """Run EKF sensor fusion on a telemetry DataFrame.

    Detects available sensors, runs EKF if GPS+IMU available,
    falls back to smoothing-only if GPS-only, or passthrough
    if neither.

    Overwrites sensor columns in-place with fused values.

    Returns
    -------
    (fused_df, FusionResult)
    """
    import pandas as pd

    sensors = detect_available_sensors(df)
    has_imu = "imu_accel" in sensors or "imu_gyro" in sensors
    has_gps = "gps_pos" in sensors

    if not has_gps:
        logger.info("Sensor fusion: no GPS position — passthrough.")
        return df.copy(), FusionResult(
            method="passthrough", sensors_used=sorted(sensors),
            confidence=0.0, n_samples=len(df),
        )

    if not has_imu:
        logger.info("Sensor fusion: GPS only — smoothing fallback.")
        result = _smoothing_only(df, sensors)
        return result, FusionResult(
            method="smoothing_only", sensors_used=sorted(sensors),
            confidence=0.3, n_samples=len(df),
        )

    # Full EKF
    logger.info("Sensor fusion: GPS + IMU — running EKF.")
    result = df.copy()
    noise = _estimate_measurement_noise(df, sensors)

    time = pd.to_numeric(result[_COL_TIME], errors="coerce").values.astype(float)
    lat = pd.to_numeric(result[_COL_LAT], errors="coerce").values.astype(float)
    lon = pd.to_numeric(result[_COL_LON], errors="coerce").values.astype(float)
    speed = pd.to_numeric(result[_COL_SPEED], errors="coerce").values.astype(float)
    bearing = pd.to_numeric(result.get(_COL_BEARING, pd.Series(dtype=float)),
                            errors="coerce").values.astype(float)

    # IMU channels
    a_long = np.zeros(len(df))
    a_lat = np.zeros(len(df))
    yaw_raw = np.zeros(len(df))

    if "imu_accel" in sensors:
        a_long = pd.to_numeric(result[_COL_ACCEL_LONG], errors="coerce").values * _G
        a_lat = pd.to_numeric(result[_COL_ACCEL_LAT], errors="coerce").values * _G
    if "imu_gyro" in sensors:
        yaw_raw = pd.to_numeric(result[_COL_YAW], errors="coerce").values

    # Convert GPS to local coordinates
    lat0, lon0 = float(np.nanmean(lat[:10])), float(np.nanmean(lon[:10]))
    n = len(df)
    gps_x = np.zeros(n)
    gps_y = np.zeros(n)
    for i in range(n):
        if np.isfinite(lat[i]) and np.isfinite(lon[i]):
            gps_x[i], gps_y[i] = latlon_to_local(lat[i], lon[i], lat0, lon0)

    # Initial state from first valid GPS
    hdg0 = np.radians(bearing[0]) if np.isfinite(bearing[0]) else 0.0
    state = EKFState(
        x=np.array([gps_x[0], gps_y[0], speed[0] if np.isfinite(speed[0]) else 0.0,
                     hdg0, np.radians(yaw_raw[0]) if np.isfinite(yaw_raw[0]) else 0.0]),
        P=np.diag([25.0, 25.0, 1.0, 0.1, 0.01]),
    )

    # Storage for fused outputs
    fused_x = np.zeros(n)
    fused_y = np.zeros(n)
    fused_v = np.zeros(n)
    fused_hdg = np.zeros(n)
    fused_yr = np.zeros(n)
    innovations_sum = 0.0
    innov_count = 0

    r_pos = noise.get("pos_m", 5.0) ** 2
    r_spd = noise.get("speed_mps", 0.3) ** 2
    r_hdg = np.radians(noise.get("bearing_deg", 3.0)) ** 2
    r_yaw = np.radians(noise.get("yaw_dps", 1.0)) ** 2

    for i in range(n):
        if i > 0:
            dt = time[i] - time[i - 1]
            if not np.isfinite(dt) or dt <= 0:
                dt = 0.01

            # Speed-adaptive process noise
            v_now = max(abs(state.x[2]), 1.0)
            q_scale = 1.0 + 5.0 / v_now  # more noise at low speed

            a_pred = a_long[i] if np.isfinite(a_long[i]) else 0.0
            state = ekf_predict(state, dt, a_pred, process_noise_scale=q_scale)

        # GPS position update
        if np.isfinite(gps_x[i]) and np.isfinite(gps_y[i]):
            z = np.array([gps_x[i], gps_y[i]])
            H = np.zeros((2, 5))
            H[0, 0] = 1.0
            H[1, 1] = 1.0
            R = np.diag([r_pos, r_pos])
            state, innov = ekf_update(state, z, H, R)
            innovations_sum += float(np.sum(innov ** 2))
            innov_count += len(innov)

        # GPS speed update
        if np.isfinite(speed[i]):
            z = np.array([speed[i]])
            H = np.zeros((1, 5))
            H[0, 2] = 1.0
            R = np.array([[r_spd]])
            state, innov = ekf_update(state, z, H, R)
            innovations_sum += float(np.sum(innov ** 2))
            innov_count += len(innov)

        # GPS bearing update
        if np.isfinite(bearing[i]) and "gps_bearing" in sensors:
            z = np.array([np.radians(bearing[i])])
            H = np.zeros((1, 5))
            H[0, 3] = 1.0
            R = np.array([[r_hdg]])
            state, innov = ekf_update(state, z, H, R)
            innovations_sum += float(np.sum(innov ** 2))
            innov_count += len(innov)

        # IMU gyro update
        if "imu_gyro" in sensors and np.isfinite(yaw_raw[i]):
            z = np.array([np.radians(yaw_raw[i])])
            H = np.zeros((1, 5))
            H[0, 4] = 1.0
            R = np.array([[r_yaw]])
            state, innov = ekf_update(state, z, H, R)
            innovations_sum += float(np.sum(innov ** 2))
            innov_count += len(innov)

        fused_x[i] = state.x[0]
        fused_y[i] = state.x[1]
        fused_v[i] = state.x[2]
        fused_hdg[i] = state.x[3]
        fused_yr[i] = state.x[4]

    # Overwrite columns with fused values
    result[_COL_SPEED] = fused_v
    result[_COL_BEARING] = np.degrees(fused_hdg) % 360
    if _COL_YAW in result.columns:
        result[_COL_YAW] = np.degrees(fused_yr)

    # Convert fused x,y back to lat/lon
    for i in range(n):
        lat_f, lon_f = local_to_latlon(fused_x[i], fused_y[i], lat0, lon0)
        lat[i] = lat_f
        lon[i] = lon_f
    result[_COL_LAT] = lat
    result[_COL_LON] = lon

    # Confidence from covariance trace + innovation RMS
    trace_mean = float(np.mean([np.trace(state.P)])) if state is not None else 10.0
    innov_rms = float(np.sqrt(innovations_sum / max(innov_count, 1)))
    confidence = max(0.0, min(1.0, 1.0 - trace_mean / 100.0))

    logger.info(
        "EKF fusion complete: %d samples, innovation_rms=%.3f, confidence=%.3f",
        n, innov_rms, confidence,
    )

    return result, FusionResult(
        method="ekf",
        sensors_used=sorted(sensors),
        confidence=round(confidence, 3),
        n_samples=n,
        innovation_rms=round(innov_rms, 4),
    )
