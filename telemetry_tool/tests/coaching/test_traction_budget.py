"""Tests for traction budget (friction circle utilization) analyzer."""
import pytest
import numpy as np
import pandas as pd
from telemetry_tool.coaching.analyzers.traction_budget import analyze_traction_budget
from telemetry_tool.coaching.models import TractionBudget


class TestTractionBudget:
    def test_basic_computation(self):
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0, "s_apex": 150.0}
        lap = pd.DataFrame({
            "Distance (m)": np.linspace(100, 200, 50),
            "Speed (m/s)": np.full(50, 20.0),
            "Lateral acceleration (m/s2)": np.full(50, 6.0),
            "Longitudinal acceleration (m/s2)": np.linspace(-4, 3, 50),
        })
        # Friction model: max lateral = 10 m/s2 at 20 m/s
        friction_max = 10.0
        result = analyze_traction_budget(corner, lap, friction_max)
        assert isinstance(result, TractionBudget)
        assert 0 <= result.apex_total_pct <= 100
        assert result.apex_remaining_pct == pytest.approx(100 - result.apex_total_pct, abs=0.5)

    def test_remaining_is_complement(self):
        corner = {"corner_id": 1, "s_start": 0.0, "s_end": 100.0, "s_apex": 50.0}
        lap = pd.DataFrame({
            "Distance (m)": np.linspace(0, 100, 50),
            "Speed (m/s)": np.full(50, 25.0),
            "Lateral acceleration (m/s2)": np.full(50, 5.0),
            "Longitudinal acceleration (m/s2)": np.full(50, 0.0),
        })
        result = analyze_traction_budget(corner, lap, 10.0)
        for zone in ("entry", "apex", "exit"):
            total = getattr(result, f"{zone}_total_pct")
            remaining = getattr(result, f"{zone}_remaining_pct")
            assert total + remaining == pytest.approx(100.0, abs=1.0)
