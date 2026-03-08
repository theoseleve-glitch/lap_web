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


def test_theoretical_not_slower_with_traffic(tmp_path):
    """Envelope from learning set >= envelope from all laps at every point.

    When traffic laps are excluded, the theoretical should never be slower
    than when they're included.
    """
    import theoretical_engine

    rng = np.random.default_rng(42)
    n = 200
    base_speed = 25.0

    # 5 clean laps
    laps = []
    for i in range(5):
        laps.append(pd.DataFrame({
            "distance_m": np.linspace(0, 500, n),
            "speed_mps": np.full(n, base_speed) + rng.normal(0, 0.3, n),
        }))

    # Add 2 traffic-contaminated laps (speed drops on 100-300m)
    for i in range(2):
        df = pd.DataFrame({
            "distance_m": np.linspace(0, 500, n),
            "speed_mps": np.full(n, base_speed) + rng.normal(0, 0.3, n),
        })
        dist = df["distance_m"].values
        mask = (dist >= 100) & (dist <= 300)
        df.loc[mask, "speed_mps"] = df.loc[mask, "speed_mps"] * 0.6
        laps.append(df)

    # Envelope with all laps (contaminated)
    env_all = theoretical_engine.compute_speed_percentile_envelope(
        laps, percentile=90.0,
    )

    # Envelope with only clean laps (first 5)
    env_clean = theoretical_engine.compute_speed_percentile_envelope(
        laps[:5], percentile=90.0,
    )

    # Clean envelope should be >= contaminated at every point
    # (within smoothing tolerance)
    diff = env_clean["v_env_mps"].values - env_all["v_env_mps"].values
    assert np.all(diff >= -0.5), (
        f"Clean envelope should not be slower than contaminated. "
        f"Min diff: {diff.min():.2f} m/s"
    )
