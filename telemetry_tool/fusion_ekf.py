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
