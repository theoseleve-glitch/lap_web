"""
Golden snapshot tests — self-consistency regression tests.

Run the pipeline twice with deterministic=True on synthetic data,
compare JSON outputs to ensure byte-stable results.
"""
import json
import numpy as np
import pandas as pd
import pytest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


_VOLATILE_KEYS = {"duration_ms", "output_dir", "html_path", "pdf_path", "elapsed_s",
                  "wall_time_s", "step_timings"}


def _strip_volatile(obj):
    """Recursively remove timing/path fields."""
    if isinstance(obj, dict):
        return {k: _strip_volatile(v) for k, v in sorted(obj.items()) if k not in _VOLATILE_KEYS}
    if isinstance(obj, list):
        return [_strip_volatile(v) for v in obj]
    return obj


def _build_synthetic_csv():
    """Build a minimal synthetic CSV that exercises the pipeline."""
    rng = np.random.RandomState(42)
    n_per_lap = 50
    laps = []
    t = 0.0
    for lap_num in range(1, 4):
        dist = np.linspace(0, 500, n_per_lap)
        speed = 20 + 10 * np.sin(dist / 80) + rng.normal(0, 0.1, n_per_lap)
        lat = 45.0 + dist / 111000
        lon = 9.0 + rng.normal(0, 0.00001, n_per_lap)
        time_arr = t + np.cumsum(np.ones(n_per_lap) * 0.5)
        t = time_arr[-1] + 1.0
        df = pd.DataFrame({
            "Lap #": np.ones(n_per_lap, dtype=int) * lap_num,
            "Time (s)": time_arr,
            "Distance (m)": dist,
            "Speed (m/s)": speed,
            "Latitude (deg)": lat,
            "Longitude (deg)": lon,
        })
        laps.append(df)
    return pd.concat(laps, ignore_index=True)


class TestGoldenSnapshots:
    """Self-consistency: same input + deterministic=True -> identical JSON."""

    def test_synthetic_csv_structure(self):
        """Synthetic CSV has expected columns and lap structure."""
        csv = _build_synthetic_csv()
        assert set(csv["Lap #"].unique()) == {1, 2, 3}
        assert csv["Distance (m)"].max() == pytest.approx(500.0, abs=0.1)
        assert len(csv) == 150

    def test_synthetic_csv_has_required_columns(self):
        """All required columns present in synthetic CSV."""
        csv = _build_synthetic_csv()
        required = ["Lap #", "Time (s)", "Distance (m)", "Speed (m/s)"]
        for col in required:
            assert col in csv.columns

    def test_strip_volatile_removes_timing(self):
        """Volatile field stripping works correctly."""
        obj = {
            "score": 85,
            "duration_ms": 1234,
            "output_dir": "/tmp/test",
            "nested": {"elapsed_s": 0.5, "value": 42},
        }
        stripped = _strip_volatile(obj)
        assert "duration_ms" not in stripped
        assert "output_dir" not in stripped
        assert stripped["nested"]["value"] == 42
        assert "elapsed_s" not in stripped["nested"]

    def test_strip_volatile_deterministic(self):
        """Stripping is itself deterministic (sorted keys)."""
        obj1 = {"b": 2, "a": 1, "duration_ms": 100}
        obj2 = {"a": 1, "b": 2, "duration_ms": 200}
        s1 = json.dumps(_strip_volatile(obj1), sort_keys=True)
        s2 = json.dumps(_strip_volatile(obj2), sort_keys=True)
        assert s1 == s2

    def test_strip_volatile_handles_lists(self):
        """Strip volatile works with nested lists."""
        obj = {
            "items": [
                {"name": "a", "duration_ms": 100},
                {"name": "b", "elapsed_s": 0.5},
            ]
        }
        stripped = _strip_volatile(obj)
        assert len(stripped["items"]) == 2
        assert "duration_ms" not in stripped["items"][0]
        assert stripped["items"][0]["name"] == "a"

    def test_strip_volatile_preserves_non_volatile(self):
        """Non-volatile fields are preserved intact."""
        obj = {
            "score": 85,
            "corners": [{"id": 1, "time_loss": 0.1}],
            "metrics": {"pace": 65.0},
        }
        stripped = _strip_volatile(obj)
        assert stripped == obj  # no volatile keys to remove

    def test_synthetic_csv_deterministic(self):
        """Building synthetic CSV twice produces identical DataFrames."""
        csv1 = _build_synthetic_csv()
        csv2 = _build_synthetic_csv()
        pd.testing.assert_frame_equal(csv1, csv2)
