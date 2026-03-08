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
