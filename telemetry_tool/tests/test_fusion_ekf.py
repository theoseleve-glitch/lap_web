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
