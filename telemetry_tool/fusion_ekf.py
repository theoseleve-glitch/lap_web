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
from dataclasses import dataclass, asdict, field
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
        (0.5 * dt) ** 2,        # yaw_rate
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
