"""Integration tests for traffic detection in the pipeline."""
import numpy as np
import pandas as pd
import pytest


def _make_multi_lap_csv(tmp_path, n_laps=5, inject_traffic_lap=None):
    """Create a CSV with multiple laps, optionally injecting traffic on one."""
    rng = np.random.default_rng(42)
    frames = []
    n_per_lap = 200
    lap_length = 500.0

    for lap in range(1, n_laps + 1):
        t_start = (lap - 1) * 30.0
        t = np.linspace(t_start, t_start + 25.0, n_per_lap)
        dist = np.linspace(0, lap_length, n_per_lap)
        speed = np.full(n_per_lap, 20.0) + rng.normal(0, 0.3, n_per_lap)
        lat = np.linspace(45.0, 45.002, n_per_lap) + rng.normal(0, 1e-5, n_per_lap)
        lon = np.linspace(9.0, 9.002, n_per_lap) + rng.normal(0, 1e-5, n_per_lap)

        if lap == inject_traffic_lap:
            traffic_mask = (dist >= 100) & (dist <= 250)
            speed[traffic_mask] = speed[traffic_mask] * 0.6

        df = pd.DataFrame({
            "Lap #": np.full(n_per_lap, lap),
            "Time (s)": t,
            "Distance (m)": dist + (lap - 1) * lap_length,
            "Speed (m/s)": speed,
            "Latitude (deg)": lat,
            "Longitude (deg)": lon,
            "Bearing (deg)": np.full(n_per_lap, 90.0) + rng.normal(0, 1, n_per_lap),
            "Longitudinal acceleration (G) *calc": rng.normal(0, 0.02, n_per_lap),
            "Lateral acceleration (G) *calc": rng.normal(0, 0.02, n_per_lap),
        })
        frames.append(df)

    full_df = pd.concat(frames, ignore_index=True)
    csv_path = tmp_path / "traffic_test.csv"
    full_df.to_csv(csv_path, index=False)
    return csv_path


def test_pipeline_has_traffic_and_inclusion(tmp_path):
    """Pipeline summary contains traffic and lap_inclusion keys."""
    import pipeline

    csv_path = _make_multi_lap_csv(tmp_path, n_laps=5)
    summary = pipeline.run_full_analysis(str(csv_path), {})

    assert "traffic" in summary
    assert "lap_inclusion" in summary

    traffic = summary["traffic"]
    assert "per_lap_score" in traffic
    assert "n_laps_affected" in traffic

    inclusion = summary["lap_inclusion"]
    assert "learning_laps" in inclusion
    assert "display_laps" in inclusion
