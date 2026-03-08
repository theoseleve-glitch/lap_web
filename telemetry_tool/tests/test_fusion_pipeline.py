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
