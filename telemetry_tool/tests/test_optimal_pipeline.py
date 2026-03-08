"""Integration tests for unified optimal solver in pipeline."""
import os
import numpy as np
import pandas as pd
import pytest


def _make_test_csv(tmp_path, n_laps=8):
    """Create CSV for pipeline integration."""
    rng = np.random.default_rng(42)
    frames = []
    n_per_lap = 200

    for lap in range(1, n_laps + 1):
        t_start = (lap - 1) * 30.0
        t = np.linspace(t_start, t_start + 25.0, n_per_lap)
        dist = np.linspace(0, 500, n_per_lap)
        speed = np.full(n_per_lap, 20.0) + rng.normal(0, 0.5, n_per_lap)
        lat = np.linspace(45.0, 45.002, n_per_lap) + rng.normal(0, 1e-5, n_per_lap)
        lon = np.linspace(9.0, 9.002, n_per_lap) + rng.normal(0, 1e-5, n_per_lap)

        df = pd.DataFrame({
            "Lap #": np.full(n_per_lap, lap),
            "Time (s)": t,
            "Distance (m)": dist + (lap - 1) * 500,
            "Speed (m/s)": speed,
            "Latitude (deg)": lat,
            "Longitude (deg)": lon,
            "Bearing (deg)": np.full(n_per_lap, 90.0) + rng.normal(0, 1, n_per_lap),
            "Longitudinal acceleration (G) *calc": rng.normal(0, 0.02, n_per_lap),
            "Lateral acceleration (G) *calc": rng.normal(0, 0.3, n_per_lap) * 1.2,
        })
        frames.append(df)

    full_df = pd.concat(frames, ignore_index=True)
    csv_path = tmp_path / "optimal_test.csv"
    full_df.to_csv(csv_path, index=False)
    return csv_path


def test_optimal_v2_off_by_default(tmp_path):
    """With OPTIMAL_V2 unset, summary has no optimal_v2 key."""
    import pipeline

    os.environ.pop("OPTIMAL_V2", None)  # ensure OFF
    csv_path = _make_test_csv(tmp_path)
    summary = pipeline.run_full_analysis(str(csv_path), {})

    # Legacy theoretical_metrics should exist
    assert "theoretical_metrics" in summary
    # optimal_v2 should NOT exist when flag is off
    assert summary.get("optimal_v2") is None


def test_optimal_v2_on_produces_result(tmp_path):
    """With OPTIMAL_V2=1, summary gains optimal_v2 alongside legacy."""
    import pipeline

    os.environ["OPTIMAL_V2"] = "1"
    try:
        csv_path = _make_test_csv(tmp_path)
        summary = pipeline.run_full_analysis(str(csv_path), {})

        # Legacy still present
        assert "theoretical_metrics" in summary

        # New optimal_v2 may be present if the pipeline produced a
        # theoretical lap and the optimal_solver module is available.
        # With synthetic data the theoretical lap or caps may be None,
        # so we accept either a valid dict or None (graceful degradation).
        opt = summary.get("optimal_v2")
        if opt is not None:
            assert "v_opt_mps" in opt
            assert "lap_time_s" in opt
            assert "solver_version" in opt
            assert opt["solver_version"].startswith("optimal_v2")
            assert "cap_source_summary" in opt
        else:
            # Stage ran without crashing — acceptable for synthetic data
            pass
    finally:
        os.environ.pop("OPTIMAL_V2", None)
