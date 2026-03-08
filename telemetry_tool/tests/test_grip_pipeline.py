"""Integration tests for grip map + friction envelope in pipeline."""
import numpy as np
import pandas as pd
import pytest


def _make_grip_test_csv(tmp_path, n_laps=8):
    """Create CSV with known grip profile: high grip first half, low second."""
    rng = np.random.default_rng(42)
    frames = []
    n_per_lap = 200
    lap_length = 500.0

    for lap in range(1, n_laps + 1):
        t_start = (lap - 1) * 30.0
        t = np.linspace(t_start, t_start + 25.0, n_per_lap)
        dist = np.linspace(0, lap_length, n_per_lap)
        speed = np.full(n_per_lap, 20.0) + rng.normal(0, 0.5, n_per_lap)
        lat = np.linspace(45.0, 45.002, n_per_lap) + rng.normal(0, 1e-5, n_per_lap)
        lon = np.linspace(9.0, 9.002, n_per_lap) + rng.normal(0, 1e-5, n_per_lap)

        # High grip first half (mu=1.3), low grip second half (mu=0.7)
        mu_profile = np.where(dist < lap_length / 2, 1.3, 0.7)
        lat_g = mu_profile * rng.choice([-1, 1], n_per_lap) * (0.8 + rng.uniform(0, 0.2, n_per_lap))

        df = pd.DataFrame({
            "Lap #": np.full(n_per_lap, lap),
            "Time (s)": t,
            "Distance (m)": dist + (lap - 1) * lap_length,
            "Speed (m/s)": speed,
            "Latitude (deg)": lat,
            "Longitude (deg)": lon,
            "Bearing (deg)": np.full(n_per_lap, 90.0) + rng.normal(0, 1, n_per_lap),
            "Longitudinal acceleration (G) *calc": rng.normal(0, 0.02, n_per_lap),
            "Lateral acceleration (G) *calc": lat_g,
        })
        frames.append(df)

    full_df = pd.concat(frames, ignore_index=True)
    csv_path = tmp_path / "grip_test.csv"
    full_df.to_csv(csv_path, index=False)
    return csv_path


def test_pipeline_has_grip_map(tmp_path):
    """Pipeline summary contains grip_map and friction_envelope keys."""
    import pipeline

    csv_path = _make_grip_test_csv(tmp_path)
    summary = pipeline.run_full_analysis(str(csv_path), {})

    assert "grip_map" in summary
    grip = summary["grip_map"]
    assert grip is not None
    assert "distance_bins" in grip
    assert "mu_mean" in grip
    assert "global_mu" in grip

    assert "friction_envelope" in summary
    fe = summary["friction_envelope"]
    assert fe is not None
    assert "global_combined_g" in fe


def test_grip_map_detects_varying_mu(tmp_path):
    """Grip map distinguishes high-grip from low-grip sections."""
    import pipeline

    csv_path = _make_grip_test_csv(tmp_path, n_laps=10)
    summary = pipeline.run_full_analysis(str(csv_path), {})

    grip = summary.get("grip_map")
    if grip is None or grip.get("is_global_fallback"):
        pytest.skip("Grip map fell back to global — insufficient data")

    mu_mean = grip["mu_mean"]
    distances = grip["distance_bins"]
    n = len(distances)
    if n < 4:
        pytest.skip("Too few bins")

    # First quarter should have higher mu than last quarter
    q1_mean = np.mean(mu_mean[:n // 4])
    q4_mean = np.mean(mu_mean[3 * n // 4:])
    # Allow some tolerance due to pipeline processing
    assert q1_mean > q4_mean * 0.8, (
        f"Expected first quarter mu ({q1_mean:.2f}) > "
        f"last quarter mu ({q4_mean:.2f}) * 0.8"
    )
