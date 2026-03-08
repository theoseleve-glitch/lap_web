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
