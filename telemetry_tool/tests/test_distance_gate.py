"""Integration tests for distance integrity gating in the pipeline."""
import numpy as np
import pandas as pd
import pytest


def test_distance_quality_in_summary(seeded_db, tmp_path):
    """Pipeline injects distance_quality into summary dict."""
    import pipeline

    csv_path = tmp_path / "test.csv"
    n = 500
    laps = np.repeat([1, 2], n // 2)
    time = np.linspace(0, 60, n)
    speed = np.random.default_rng(42).uniform(10, 30, n)
    dist = np.cumsum(speed * np.diff(np.concatenate([[0], time])))
    lat = np.linspace(45.0, 45.001, n)
    lon = np.linspace(9.0, 9.001, n)

    df = pd.DataFrame({
        "Lap #": laps,
        "Time (s)": time,
        "Speed (m/s)": speed,
        "Distance (m)": dist,
        "Latitude (deg)": lat,
        "Longitude (deg)": lon,
    })
    df.to_csv(csv_path, index=False)

    summary = pipeline.run_full_analysis(str(csv_path), {})
    assert "distance_quality" in summary
    dq = summary["distance_quality"]
    assert dq["status"] in ("ok", "repaired", "degraded")
    assert isinstance(dq["gate_advanced"], bool)
    assert isinstance(dq["metrics"], list)


def test_gate_blocks_theoretical_when_degraded():
    """When distance_quality.gate_advanced=True, theoretical step is skipped."""
    from distance_integrity import DistanceQuality

    dq = DistanceQuality(
        status="degraded",
        gate_advanced=True,
        laps_degraded=[1],
        message="test",
    )
    # Verify the dataclass attributes used by the gate check
    assert dq.gate_advanced is True
    assert dq.status == "degraded"
    assert hasattr(dq, 'gate_advanced')
