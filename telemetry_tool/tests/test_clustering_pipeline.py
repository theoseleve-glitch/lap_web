"""Integration tests for condition clustering in the pipeline."""
import numpy as np
import pandas as pd
import pytest


def _make_multi_lap_csv(tmp_path, n_laps=8):
    """Create a CSV with multiple laps."""
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

        df = pd.DataFrame({
            "Lap #": np.full(n_per_lap, lap),
            "Time (s)": t,
            "Distance (m)": dist + (lap - 1) * lap_length,
            "Speed (m/s)": speed,
            "Latitude (deg)": lat,
            "Longitude (deg)": lon,
            "Bearing (deg)": np.full(n_per_lap, 90.0) + rng.normal(0, 1, n_per_lap),
            "Longitudinal acceleration (G) *calc": rng.normal(0, 0.02, n_per_lap),
            "Lateral acceleration (G) *calc": rng.normal(0, 0.3, n_per_lap) * 1.2,
        })
        frames.append(df)

    full_df = pd.concat(frames, ignore_index=True)
    csv_path = tmp_path / "cluster_test.csv"
    full_df.to_csv(csv_path, index=False)
    return csv_path


def test_pipeline_has_clustering(tmp_path):
    """Pipeline summary contains clustering key."""
    import pipeline

    csv_path = _make_multi_lap_csv(tmp_path, n_laps=8)
    summary = pipeline.run_full_analysis(str(csv_path), {})

    assert "clustering" in summary
    clustering = summary["clustering"]
    assert "clusters" in clustering
    assert "selected_cluster_id" in clustering
    assert "purity_score" in clustering
    assert "method" in clustering
