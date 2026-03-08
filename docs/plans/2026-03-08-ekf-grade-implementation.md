# EKF Sensor Fusion + Grade Wiring Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an EKF-lite sensor fusion stage (pipeline stage 2.5) that fuses GPS+IMU into stabilized channels, then wire the existing grade/slope correction with altitude quality gating and confidence labels.

**Architecture:** New `fusion_ekf.py` module with 5-state EKF (x, y, v, heading, yaw_rate). Runs before derived_channels so fused signals improve all downstream computation. Grade wiring activates existing `correct_for_slope=True` path with quality checks. Both write metadata to summary JSON.

**Tech Stack:** Python 3.x, NumPy (EKF math — no external KF library), pandas, pytest

---

### Task 1: FusionResult dataclass + sensor detection

**Files:**
- Create: `telemetry_tool/fusion_ekf.py`
- Create: `telemetry_tool/tests/test_fusion_ekf.py`

**Step 1: Write the failing tests**

In `telemetry_tool/tests/test_fusion_ekf.py`:

```python
"""Tests for fusion_ekf module."""
import numpy as np
import pandas as pd
import pytest


def test_fusion_result_fields():
    """FusionResult has all required fields with correct types."""
    from fusion_ekf import FusionResult

    fr = FusionResult(
        method="ekf",
        sensors_used=["gps_pos", "gps_speed", "imu_gyro"],
        confidence=0.85,
        n_samples=1000,
        innovation_rms=0.5,
    )
    assert fr.method == "ekf"
    assert isinstance(fr.sensors_used, list)
    assert 0 <= fr.confidence <= 1
    d = fr.to_dict()
    assert "method" in d
    assert "confidence" in d


def test_detect_sensors_full():
    """DataFrame with GPS + IMU → detects all sensor groups."""
    from fusion_ekf import detect_available_sensors

    df = pd.DataFrame({
        "Latitude (deg)": np.linspace(45, 45.001, 100),
        "Longitude (deg)": np.linspace(9, 9.001, 100),
        "Speed (m/s)": np.full(100, 20.0),
        "Bearing (deg)": np.linspace(0, 90, 100),
        "Longitudinal acceleration (G) *calc": np.zeros(100),
        "Lateral acceleration (G) *calc": np.zeros(100),
        "Yaw rate (deg/s)": np.zeros(100),
        "Time (s)": np.linspace(0, 10, 100),
    })
    sensors = detect_available_sensors(df)
    assert "gps_pos" in sensors
    assert "gps_speed" in sensors
    assert "gps_bearing" in sensors
    assert "imu_accel" in sensors
    assert "imu_gyro" in sensors


def test_detect_sensors_gps_only():
    """DataFrame with only GPS → no IMU sensors detected."""
    from fusion_ekf import detect_available_sensors

    df = pd.DataFrame({
        "Latitude (deg)": np.linspace(45, 45.001, 100),
        "Longitude (deg)": np.linspace(9, 9.001, 100),
        "Speed (m/s)": np.full(100, 20.0),
        "Time (s)": np.linspace(0, 10, 100),
    })
    sensors = detect_available_sensors(df)
    assert "gps_pos" in sensors
    assert "gps_speed" in sensors
    assert "imu_accel" not in sensors
    assert "imu_gyro" not in sensors


def test_detect_sensors_empty():
    """DataFrame with no recognized columns → empty set."""
    from fusion_ekf import detect_available_sensors

    df = pd.DataFrame({"foo": [1, 2, 3]})
    sensors = detect_available_sensors(df)
    assert len(sensors) == 0
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_fusion_ekf.py -v`
Expected: FAIL with "cannot import name 'FusionResult'"

**Step 3: Write minimal implementation**

In `telemetry_tool/fusion_ekf.py`:

```python
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
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_fusion_ekf.py -v`
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/fusion_ekf.py telemetry_tool/tests/test_fusion_ekf.py
git commit -m "feat(fusion): add FusionResult dataclass and detect_available_sensors()"
```

---

### Task 2: EKF predict/update core

**Files:**
- Modify: `telemetry_tool/fusion_ekf.py` (append)
- Modify: `telemetry_tool/tests/test_fusion_ekf.py` (append)

**Step 1: Write the failing tests**

Append to `telemetry_tool/tests/test_fusion_ekf.py`:

```python
def test_ekf_predict_straight_line():
    """Predict step on straight line: x advances, heading unchanged."""
    from fusion_ekf import EKFState, ekf_predict

    state = EKFState(
        x=np.array([0.0, 0.0, 20.0, 0.0, 0.0]),  # x,y,v,heading,yaw_rate
        P=np.eye(5) * 0.1,
    )
    dt = 0.1
    a_long = 0.0
    new_state = ekf_predict(state, dt, a_long)
    assert new_state.x[0] == pytest.approx(2.0, abs=0.01)  # 20 m/s * 0.1s
    assert new_state.x[1] == pytest.approx(0.0, abs=0.01)  # heading=0 → no y motion
    assert new_state.x[2] == pytest.approx(20.0, abs=0.01)  # constant speed
    assert new_state.x[3] == pytest.approx(0.0, abs=0.01)  # heading unchanged


def test_ekf_predict_turning():
    """Predict step with yaw_rate: heading changes."""
    from fusion_ekf import EKFState, ekf_predict

    state = EKFState(
        x=np.array([0.0, 0.0, 20.0, 0.0, np.radians(90.0)]),  # 90 deg/s yaw
        P=np.eye(5) * 0.1,
    )
    dt = 1.0
    new_state = ekf_predict(state, dt, 0.0)
    # After 1s at 90 deg/s, heading should be ~pi/2
    assert new_state.x[3] == pytest.approx(np.radians(90.0), abs=0.1)


def test_ekf_update_corrects_position():
    """Update step: GPS measurement pulls state toward measurement."""
    from fusion_ekf import EKFState, ekf_update

    # State thinks we're at (0,0), GPS says (1, 0)
    state = EKFState(
        x=np.array([0.0, 0.0, 20.0, 0.0, 0.0]),
        P=np.eye(5) * 10.0,  # high uncertainty
    )
    z = np.array([1.0, 0.0])  # GPS position measurement
    H = np.zeros((2, 5))
    H[0, 0] = 1.0  # x
    H[1, 1] = 1.0  # y
    R = np.eye(2) * 1.0  # measurement noise

    new_state, innovation = ekf_update(state, z, H, R)
    # State should move toward (1, 0)
    assert new_state.x[0] > 0.5  # pulled toward GPS
    assert abs(innovation[0]) > 0  # innovation is nonzero
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_fusion_ekf.py::test_ekf_predict_straight_line -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Append to `telemetry_tool/fusion_ekf.py`:

```python
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
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_fusion_ekf.py -v`
Expected: 7 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/fusion_ekf.py telemetry_tool/tests/test_fusion_ekf.py
git commit -m "feat(fusion): add EKF predict/update core with kinematic model"
```

---

### Task 3: Coordinate conversion helpers

**Files:**
- Modify: `telemetry_tool/fusion_ekf.py` (append)
- Modify: `telemetry_tool/tests/test_fusion_ekf.py` (append)

**Step 1: Write the failing tests**

Append to `telemetry_tool/tests/test_fusion_ekf.py`:

```python
def test_latlon_to_local_roundtrip():
    """lat/lon → local x,y → back to lat/lon preserves values."""
    from fusion_ekf import latlon_to_local, local_to_latlon

    lat0, lon0 = 45.0, 9.0
    # Point 100m north, 50m east
    lat1, lon1 = 45.0009, 9.0006

    x, y = latlon_to_local(lat1, lon1, lat0, lon0)
    assert x == pytest.approx(50.0, abs=5.0)  # ~50m east
    assert y == pytest.approx(100.0, abs=5.0)  # ~100m north

    lat_back, lon_back = local_to_latlon(x, y, lat0, lon0)
    assert lat_back == pytest.approx(lat1, abs=1e-4)
    assert lon_back == pytest.approx(lon1, abs=1e-4)
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_fusion_ekf.py::test_latlon_to_local_roundtrip -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Append to `telemetry_tool/fusion_ekf.py`:

```python
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
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_fusion_ekf.py -v`
Expected: 8 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/fusion_ekf.py telemetry_tool/tests/test_fusion_ekf.py
git commit -m "feat(fusion): add lat/lon to local coordinate conversion"
```

---

### Task 4: run_sensor_fusion() orchestrator

**Files:**
- Modify: `telemetry_tool/fusion_ekf.py` (append)
- Modify: `telemetry_tool/tests/test_fusion_ekf.py` (append)

**Step 1: Write the failing tests**

Append to `telemetry_tool/tests/test_fusion_ekf.py`:

```python
def _make_straight_line_df(n=200, speed=20.0, dt=0.1, noise_m=2.0):
    """Synthetic straight-line GPS+IMU data with configurable noise."""
    rng = np.random.default_rng(42)
    t = np.arange(n) * dt
    x_true = speed * t
    y_true = np.zeros(n)

    df = pd.DataFrame({
        "Time (s)": t,
        "Latitude (deg)": 45.0 + (y_true + rng.normal(0, noise_m, n)) / 111_320,
        "Longitude (deg)": 9.0 + (x_true + rng.normal(0, noise_m, n)) / (111_320 * np.cos(np.radians(45))),
        "Speed (m/s)": speed + rng.normal(0, 0.3, n),
        "Bearing (deg)": 90.0 + rng.normal(0, 3.0, n),  # heading east
        "Longitudinal acceleration (G) *calc": rng.normal(0, 0.02, n),
        "Lateral acceleration (G) *calc": rng.normal(0, 0.02, n),
        "Yaw rate (deg/s)": rng.normal(0, 1.0, n),
    })
    return df


def test_run_sensor_fusion_ekf():
    """Full GPS+IMU → EKF fusion produces stable output."""
    from fusion_ekf import run_sensor_fusion

    df = _make_straight_line_df()
    result_df, fusion_result = run_sensor_fusion(df)

    assert fusion_result.method == "ekf"
    assert fusion_result.confidence > 0.0
    assert "gps_pos" in fusion_result.sensors_used
    assert "imu_gyro" in fusion_result.sensors_used

    # Fused yaw_rate should be smoother than raw
    raw_yaw_std = df["Yaw rate (deg/s)"].std()
    fused_yaw_std = result_df["Yaw rate (deg/s)"].std()
    assert fused_yaw_std < raw_yaw_std


def test_run_sensor_fusion_gps_only():
    """GPS only (no IMU) → smoothing_only fallback."""
    from fusion_ekf import run_sensor_fusion

    df = pd.DataFrame({
        "Time (s)": np.linspace(0, 10, 100),
        "Latitude (deg)": np.linspace(45, 45.001, 100),
        "Longitude (deg)": np.linspace(9, 9.001, 100),
        "Speed (m/s)": np.full(100, 20.0),
    })
    result_df, fusion_result = run_sensor_fusion(df)

    assert fusion_result.method == "smoothing_only"
    assert "imu_accel" not in fusion_result.sensors_used
    assert "imu_gyro" not in fusion_result.sensors_used


def test_run_sensor_fusion_passthrough():
    """No usable sensors → passthrough, no modification."""
    from fusion_ekf import run_sensor_fusion

    df = pd.DataFrame({
        "Time (s)": np.linspace(0, 10, 100),
        "Speed (m/s)": np.full(100, 20.0),
    })
    result_df, fusion_result = run_sensor_fusion(df)

    assert fusion_result.method == "passthrough"
    assert fusion_result.confidence == 0.0


def test_noise_reduction():
    """EKF reduces yaw_rate noise compared to raw input."""
    from fusion_ekf import run_sensor_fusion

    df = _make_straight_line_df(n=500, noise_m=5.0)
    result_df, _ = run_sensor_fusion(df)

    raw_yaw_std = df["Yaw rate (deg/s)"].std()
    fused_yaw_std = result_df["Yaw rate (deg/s)"].std()
    # EKF should reduce noise by at least 30%
    assert fused_yaw_std < raw_yaw_std * 0.7, (
        f"EKF noise reduction insufficient: raw={raw_yaw_std:.2f}, "
        f"fused={fused_yaw_std:.2f}"
    )
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_fusion_ekf.py::test_run_sensor_fusion_ekf -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Append to `telemetry_tool/fusion_ekf.py`:

```python
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
            # Wrap innovation for heading
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
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_fusion_ekf.py -v`
Expected: 12 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/fusion_ekf.py telemetry_tool/tests/test_fusion_ekf.py
git commit -m "feat(fusion): add run_sensor_fusion() orchestrator with EKF/smoothing/passthrough"
```

---

### Task 5: Pipeline stage 2.5 integration

**Files:**
- Modify: `telemetry_tool/pipeline.py` (between lines ~819 and ~821)
- Create: `telemetry_tool/tests/test_fusion_pipeline.py`

**Step 1: Write the failing test**

In `telemetry_tool/tests/test_fusion_pipeline.py`:

```python
"""Integration tests for sensor fusion in the pipeline."""
import numpy as np
import pandas as pd
import pytest


def test_pipeline_includes_fusion_result(tmp_path):
    """Full pipeline summary contains sensor_fusion dict."""
    import pipeline

    rng = np.random.default_rng(42)
    n = 400
    laps = np.repeat([1, 2], n // 2)
    t = np.linspace(0, 60, n)
    speed = rng.uniform(15, 25, n)
    dist = np.cumsum(speed * np.diff(np.concatenate([[0], t])))
    lat = np.linspace(45.0, 45.002, n) + rng.normal(0, 1e-5, n)
    lon = np.linspace(9.0, 9.002, n) + rng.normal(0, 1e-5, n)

    df = pd.DataFrame({
        "Lap #": laps,
        "Time (s)": t,
        "Speed (m/s)": speed,
        "Distance (m)": dist,
        "Latitude (deg)": lat,
        "Longitude (deg)": lon,
        "Bearing (deg)": np.full(n, 45.0) + rng.normal(0, 2, n),
        "Longitudinal acceleration (G) *calc": rng.normal(0, 0.02, n),
        "Lateral acceleration (G) *calc": rng.normal(0, 0.02, n),
        "Yaw rate (deg/s)": rng.normal(0, 0.5, n),
    })
    csv_path = tmp_path / "fusion_test.csv"
    df.to_csv(csv_path, index=False)

    summary = pipeline.run_full_analysis(str(csv_path), {})
    assert "sensor_fusion" in summary
    sf = summary["sensor_fusion"]
    assert sf["method"] in ("ekf", "smoothing_only", "passthrough")
    assert isinstance(sf["confidence"], float)
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_fusion_pipeline.py -v`
Expected: FAIL (no sensor_fusion key)

**Step 3: Modify pipeline.py**

In `telemetry_tool/pipeline.py`, between the GPS filter step (line ~819, `summary["filtered_df"] = None`) and the derived channels step (line ~821, `# STEP 3 -- Derived channels`), insert:

```python
        # STEP 2.5 -- Sensor fusion (EKF)
        #
        _fusion_mod = _import("fusion_ekf")

        def _fusion():
            if _fusion_mod is None:
                logger.info("fusion_ekf module absent; skipping sensor fusion.")
                return filtered_df, None
            return _fusion_mod.run_sensor_fusion(filtered_df)

        _fusion_result, err = _safe_step("02b_sensor_fusion", _fusion)
        _record("02b_sensor_fusion", _fusion_result, err)
        _fire_progress("02b_sensor_fusion")
        if _fusion_result is not None:
            filtered_df, _fusion_meta = _fusion_result
            summary["sensor_fusion"] = _fusion_meta.to_dict() if hasattr(_fusion_meta, "to_dict") else _fusion_meta
        else:
            _fusion_meta = None
            summary["sensor_fusion"] = None
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_fusion_pipeline.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/pipeline.py telemetry_tool/tests/test_fusion_pipeline.py
git commit -m "feat(fusion): integrate sensor fusion as pipeline stage 2.5"
```

---

### Task 6: Grade wiring — altitude quality check + labels

**Files:**
- Modify: `telemetry_tool/derived_channels.py` (lines ~660-750)
- Create: `telemetry_tool/tests/test_grade_wiring.py`

**Step 1: Write the failing tests**

In `telemetry_tool/tests/test_grade_wiring.py`:

```python
"""Tests for grade wiring and altitude quality gating."""
import numpy as np
import pandas as pd
import pytest


def test_grade_unavailable_flat_altitude():
    """Altitude with < 0.5m range → grade_status='grade_unavailable'."""
    from derived_channels import compute_elevation_profile_with_quality

    n = 200
    df = pd.DataFrame({
        "Altitude (m)": np.full(n, 100.0) + np.random.default_rng(42).uniform(-0.1, 0.1, n),
        "Distance (m)": np.linspace(0, 500, n),
        "Time (s)": np.linspace(0, 30, n),
        "Speed (m/s)": np.full(n, 20.0),
    })
    grade, status = compute_elevation_profile_with_quality(df)
    assert status == "grade_unavailable"
    # Grade should be zeros
    assert np.allclose(grade.values, 0.0, atol=0.1)


def test_grade_low_confidence_noisy():
    """Very noisy altitude → grade_status='grade_low_confidence'."""
    from derived_channels import compute_elevation_profile_with_quality

    n = 200
    rng = np.random.default_rng(42)
    # Real elevation change + huge noise
    alt = np.linspace(100, 110, n) + rng.normal(0, 10, n)
    df = pd.DataFrame({
        "Altitude (m)": alt,
        "Distance (m)": np.linspace(0, 500, n),
        "Time (s)": np.linspace(0, 30, n),
        "Speed (m/s)": np.full(n, 20.0),
    })
    grade, status = compute_elevation_profile_with_quality(df)
    assert status == "grade_low_confidence"


def test_grade_used_clean_altitude():
    """Clean altitude with real elevation → grade_status='grade_used'."""
    from derived_channels import compute_elevation_profile_with_quality

    n = 200
    # 5% grade = 25m rise over 500m
    alt = np.linspace(100, 125, n) + np.random.default_rng(42).normal(0, 0.5, n)
    df = pd.DataFrame({
        "Altitude (m)": alt,
        "Distance (m)": np.linspace(0, 500, n),
        "Time (s)": np.linspace(0, 30, n),
        "Speed (m/s)": np.full(n, 20.0),
    })
    grade, status = compute_elevation_profile_with_quality(df)
    assert status == "grade_used"
    # Mean grade should be around 5%
    assert 3.0 < grade.mean() < 7.0


def test_grade_unavailable_no_altitude_col():
    """No altitude column at all → grade_status='grade_unavailable'."""
    from derived_channels import compute_elevation_profile_with_quality

    df = pd.DataFrame({
        "Distance (m)": np.linspace(0, 500, 200),
        "Speed (m/s)": np.full(200, 20.0),
    })
    grade, status = compute_elevation_profile_with_quality(df)
    assert status == "grade_unavailable"
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_grade_wiring.py -v`
Expected: FAIL with "cannot import name 'compute_elevation_profile_with_quality'"

**Step 3: Modify derived_channels.py**

Add a new wrapper function after `compute_elevation_profile()` (after line ~750):

```python
_ALT_RANGE_THRESHOLD = 0.5     # metres — below this, altitude is flat/useless
_ALT_NOISE_THRESHOLD = 5.0     # metres — rolling std above this is too noisy


def compute_elevation_profile_with_quality(
    df: pd.DataFrame,
    *,
    smoothing_window: int = 15,
) -> tuple[pd.Series, str]:
    """Compute grade with altitude quality assessment.

    Returns
    -------
    (grade_pct, grade_status)
        grade_status is one of:
        - "grade_used": clean altitude, grade computed normally
        - "grade_low_confidence": noisy altitude, grade computed but unreliable
        - "grade_unavailable": no altitude or flat terrain, returns zeros
    """
    alt_col = _find_altitude_col(df)

    if alt_col is None:
        logger.info("Grade quality: no altitude column — grade_unavailable.")
        return (pd.Series(np.zeros(len(df)), index=df.index, name=OUT_GRADE_PCT),
                "grade_unavailable")

    alt = pd.to_numeric(df[alt_col], errors="coerce").values.astype(float)
    finite_alt = alt[np.isfinite(alt)]

    if len(finite_alt) < 10:
        return (pd.Series(np.zeros(len(df)), index=df.index, name=OUT_GRADE_PCT),
                "grade_unavailable")

    alt_range = float(np.ptp(finite_alt))

    if alt_range < _ALT_RANGE_THRESHOLD:
        logger.info("Grade quality: altitude range %.2fm < %.1fm — grade_unavailable.",
                     alt_range, _ALT_RANGE_THRESHOLD)
        return (pd.Series(np.zeros(len(df)), index=df.index, name=OUT_GRADE_PCT),
                "grade_unavailable")

    # Check noise via rolling std (window = 20 samples)
    window = min(20, len(finite_alt) // 3)
    if window >= 3:
        rolling_std = pd.Series(finite_alt).rolling(window, center=True).std()
        median_noise = float(rolling_std.median())
    else:
        median_noise = 0.0

    grade = compute_elevation_profile(df, smoothing_window=smoothing_window)

    if median_noise > _ALT_NOISE_THRESHOLD:
        logger.info("Grade quality: altitude noise %.2fm > %.1fm — grade_low_confidence.",
                     median_noise, _ALT_NOISE_THRESHOLD)
        return grade, "grade_low_confidence"

    logger.info("Grade quality: clean altitude (range=%.1fm, noise=%.2fm) — grade_used.",
                alt_range, median_noise)
    return grade, "grade_used"
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_grade_wiring.py -v`
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/derived_channels.py telemetry_tool/tests/test_grade_wiring.py
git commit -m "feat(grade): add compute_elevation_profile_with_quality() with altitude quality gating"
```

---

### Task 7: Wire slope correction + grade_status into pipeline

**Files:**
- Modify: `telemetry_tool/pipeline.py` (the derived channels step, ~line 826-835)
- Modify: `telemetry_tool/tests/test_grade_wiring.py` (append tests)

**Step 1: Write the failing tests**

Append to `telemetry_tool/tests/test_grade_wiring.py`:

```python
def test_slope_correction_uphill():
    """Synthetic 5% uphill: corrected accel removes gravity bias."""
    from derived_channels import compute_longitudinal_accel, compute_elevation_profile

    n = 200
    grade_pct = 5.0  # 5% uphill
    grade_rad = np.arctan(grade_pct / 100.0)
    gravity_bias = 9.80665 * np.sin(grade_rad)  # ~0.49 m/s^2

    df = pd.DataFrame({
        "Longitudinal acceleration (G) *calc": np.full(n, gravity_bias / 9.80665),  # biased reading
        "Speed (m/s)": np.full(n, 20.0),
        "Time (s)": np.linspace(0, 10, n),
        "Distance (m)": np.linspace(0, 200, n),
        "Altitude (m)": np.linspace(0, 10, n),  # 10m rise over 200m = 5%
    })

    result = compute_longitudinal_accel(df, correct_for_slope=True)
    accel = result["accel_long_mps2"].values
    # After correction, accel should be near zero (bias removed)
    assert np.nanmean(np.abs(accel)) < 0.3, (
        f"Slope correction should remove gravity bias, got mean |accel|={np.nanmean(np.abs(accel)):.3f}"
    )


def test_slope_correction_downhill():
    """Synthetic -5% downhill: corrected accel removes negative bias."""
    from derived_channels import compute_longitudinal_accel

    n = 200
    grade_pct = -5.0
    grade_rad = np.arctan(grade_pct / 100.0)
    gravity_bias = 9.80665 * np.sin(grade_rad)  # ~-0.49 m/s^2

    df = pd.DataFrame({
        "Longitudinal acceleration (G) *calc": np.full(n, gravity_bias / 9.80665),
        "Speed (m/s)": np.full(n, 20.0),
        "Time (s)": np.linspace(0, 10, n),
        "Distance (m)": np.linspace(0, 200, n),
        "Altitude (m)": np.linspace(10, 0, n),  # 10m drop
    })

    result = compute_longitudinal_accel(df, correct_for_slope=True)
    accel = result["accel_long_mps2"].values
    assert np.nanmean(np.abs(accel)) < 0.3
```

**Step 2: Run tests to verify they pass**

These should already pass since `correct_for_slope=True` is already implemented. Run to confirm:

Run: `pytest telemetry_tool/tests/test_grade_wiring.py -v`
Expected: 6 PASSED

**Step 3: Modify pipeline.py derived channels step**

In `telemetry_tool/pipeline.py`, modify the `_derived()` function (around line 826-835) to:
1. Call `compute_elevation_profile_with_quality()` for grade
2. Pass `correct_for_slope=True` when grade is available
3. Store `grade_status` in summary

Find the existing `_derived()` function:
```python
        def _derived() -> pd.DataFrame:
            if dc_mod is None:
                logger.info("Derived channels skipped (module absent).")
                return filtered_df
            df = dc_mod.compute_longitudinal_accel(filtered_df)
            df = dc_mod.compute_lateral_accel_from_xy(df)
            df = dc_mod.compute_yaw_rate_from_heading(df)
            return df
```

Replace with:
```python
        def _derived() -> pd.DataFrame:
            if dc_mod is None:
                logger.info("Derived channels skipped (module absent).")
                return filtered_df

            # Grade quality check + elevation profile
            _grade_status = "grade_unavailable"
            _do_slope_correct = False
            if hasattr(dc_mod, "compute_elevation_profile_with_quality"):
                try:
                    _grade_series, _grade_status = dc_mod.compute_elevation_profile_with_quality(filtered_df)
                    if _grade_status == "grade_used":
                        filtered_df[dc_mod.OUT_GRADE_PCT] = _grade_series.values
                        _do_slope_correct = True
                    elif _grade_status == "grade_low_confidence":
                        filtered_df[dc_mod.OUT_GRADE_PCT] = _grade_series.values
                        # Still compute grade but don't use for correction
                except Exception as _ge:
                    logger.warning("Grade estimation failed: %s", _ge)
            summary["grade_status"] = _grade_status

            df = dc_mod.compute_longitudinal_accel(
                filtered_df, correct_for_slope=_do_slope_correct)
            df = dc_mod.compute_lateral_accel_from_xy(df)
            df = dc_mod.compute_yaw_rate_from_heading(df)
            return df
```

**Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_grade_wiring.py telemetry_tool/tests/test_fusion_pipeline.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add telemetry_tool/pipeline.py telemetry_tool/tests/test_grade_wiring.py
git commit -m "feat(grade): wire slope correction + grade_status into pipeline derived channels"
```

---

### Task 8: Data quality — fusion_confidence extension

**Files:**
- Modify: `telemetry_tool/data_quality.py` (DataQualityReport + score_data_quality)
- Modify: `telemetry_tool/tests/test_grade_wiring.py` (append test)

**Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_grade_wiring.py`:

```python
def test_data_quality_has_fusion_confidence():
    """DataQualityReport includes fusion_confidence field."""
    from data_quality import DataQualityReport

    report = DataQualityReport(
        n_laps=5,
        gps_quality=0.9,
        accel_quality=0.8,
        yaw_quality=0.7,
        sample_rate_hz=25.0,
        lap_time_consistency=0.95,
        overall_confidence=0.85,
        recommended_speed_percentile=90.0,
        recommended_accel_percentile=91.0,
        fusion_confidence=0.75,
    )
    assert report.fusion_confidence == 0.75
    d = report.to_dict()
    assert "fusion_confidence" in d
    assert d["fusion_confidence"] == 0.75
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_grade_wiring.py::test_data_quality_has_fusion_confidence -v`
Expected: FAIL (unexpected keyword argument 'fusion_confidence')

**Step 3: Modify data_quality.py**

3a. Add field to `DataQualityReport` (after `warnings` field, line ~141):

```python
    fusion_confidence:            float = -1.0  # -1 = not computed
```

3b. Add to `to_dict()` (after the warnings line, ~line 154):

```python
            "fusion_confidence":            round(self.fusion_confidence, 3),
```

3c. In `score_data_quality()`, after the overall confidence computation (line ~836), add:

```python
    # Incorporate fusion confidence if available (passed via kwargs)
    fusion_conf = kwargs.get("fusion_confidence", -1.0)
```

And pass it to the DataQualityReport constructor (line ~845):

```python
        fusion_confidence=fusion_conf,
```

Note: The `score_data_quality()` function signature needs `**kwargs` added if not already present. Check the actual signature before modifying.

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_grade_wiring.py -v`
Expected: 7 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/data_quality.py telemetry_tool/tests/test_grade_wiring.py
git commit -m "feat(quality): add fusion_confidence field to DataQualityReport"
```

---

### Task 9: Pipeline integration test — grade_status in summary

**Files:**
- Modify: `telemetry_tool/tests/test_fusion_pipeline.py` (append)

**Step 1: Write the test**

Append to `telemetry_tool/tests/test_fusion_pipeline.py`:

```python
def test_pipeline_includes_grade_status(tmp_path):
    """Full pipeline summary contains grade_status string."""
    import pipeline

    rng = np.random.default_rng(42)
    n = 400
    laps = np.repeat([1, 2], n // 2)
    t = np.linspace(0, 60, n)
    speed = rng.uniform(15, 25, n)
    dist = np.cumsum(speed * np.diff(np.concatenate([[0], t])))

    df = pd.DataFrame({
        "Lap #": laps,
        "Time (s)": t,
        "Speed (m/s)": speed,
        "Distance (m)": dist,
        "Latitude (deg)": np.linspace(45.0, 45.002, n),
        "Longitude (deg)": np.linspace(9.0, 9.002, n),
        "Altitude (m)": np.linspace(100, 120, n),  # 20m elevation
    })
    csv_path = tmp_path / "grade_test.csv"
    df.to_csv(csv_path, index=False)

    summary = pipeline.run_full_analysis(str(csv_path), {})
    assert "grade_status" in summary
    assert summary["grade_status"] in ("grade_used", "grade_low_confidence", "grade_unavailable")
```

**Step 2: Run all integration tests**

Run: `pytest telemetry_tool/tests/test_fusion_pipeline.py -v`
Expected: 2 PASSED

**Step 3: Commit**

```bash
git add telemetry_tool/tests/test_fusion_pipeline.py
git commit -m "test(fusion): add pipeline integration test for grade_status"
```

---

### Task 10: Speed-adaptive noise test

**Files:**
- Modify: `telemetry_tool/tests/test_fusion_ekf.py` (append)

**Step 1: Write the test**

Append to `telemetry_tool/tests/test_fusion_ekf.py`:

```python
def _make_circular_motion_df(n=300, radius=50.0, speed=15.0, dt=0.1, noise_m=2.0):
    """Synthetic circular motion with GPS+IMU noise."""
    rng = np.random.default_rng(42)
    t = np.arange(n) * dt
    omega = speed / radius  # rad/s
    theta = omega * t

    x_true = radius * np.cos(theta)
    y_true = radius * np.sin(theta)
    heading_true = theta + np.pi / 2  # tangent direction

    lat0, lon0 = 45.0, 9.0
    scale_lat = 1.0 / 111_320
    scale_lon = 1.0 / (111_320 * np.cos(np.radians(lat0)))

    df = pd.DataFrame({
        "Time (s)": t,
        "Latitude (deg)": lat0 + (y_true + rng.normal(0, noise_m, n)) * scale_lat,
        "Longitude (deg)": lon0 + (x_true + rng.normal(0, noise_m, n)) * scale_lon,
        "Speed (m/s)": speed + rng.normal(0, 0.3, n),
        "Bearing (deg)": (np.degrees(heading_true) + rng.normal(0, 3, n)) % 360,
        "Longitudinal acceleration (G) *calc": rng.normal(0, 0.02, n),
        "Lateral acceleration (G) *calc": (speed ** 2 / radius / 9.80665) + rng.normal(0, 0.03, n),
        "Yaw rate (deg/s)": np.degrees(omega) + rng.normal(0, 1.5, n),
    })
    return df


def test_circular_motion_yaw_rate():
    """EKF recovers correct yaw_rate from noisy circular motion data."""
    from fusion_ekf import run_sensor_fusion

    radius = 50.0
    speed = 15.0
    expected_yaw_dps = np.degrees(speed / radius)  # ~17.2 deg/s

    df = _make_circular_motion_df(radius=radius, speed=speed)
    result_df, fusion_result = run_sensor_fusion(df)

    assert fusion_result.method == "ekf"
    fused_yaw = result_df["Yaw rate (deg/s)"].values
    # Trim first 50 samples (EKF convergence)
    mean_yaw = np.mean(fused_yaw[50:])
    assert mean_yaw == pytest.approx(expected_yaw_dps, abs=3.0), (
        f"Expected yaw ~{expected_yaw_dps:.1f} deg/s, got {mean_yaw:.1f}"
    )
```

**Step 2: Run all EKF tests**

Run: `pytest telemetry_tool/tests/test_fusion_ekf.py -v`
Expected: 13 PASSED

**Step 3: Commit**

```bash
git add telemetry_tool/tests/test_fusion_ekf.py
git commit -m "test(fusion): add circular motion yaw recovery test"
```

---

## Summary

| Task | What | Tests |
|------|------|-------|
| 1 | FusionResult + sensor detection | 4 |
| 2 | EKF predict/update core | 3 |
| 3 | Coordinate conversion | 1 |
| 4 | run_sensor_fusion() orchestrator | 4 |
| 5 | Pipeline stage 2.5 | 1 |
| 6 | Grade altitude quality check + labels | 4 |
| 7 | Wire slope correction + grade_status | 2 |
| 8 | DataQualityReport fusion_confidence | 1 |
| 9 | Pipeline grade_status integration test | 1 |
| 10 | Circular motion yaw recovery test | 1 |
| **Total** | | **22** |
