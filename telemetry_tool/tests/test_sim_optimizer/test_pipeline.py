"""Tests for the sim optimizer pipeline orchestrator."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSafeStep:
    def test_catches_exceptions(self):
        from telemetry_tool.sim_optimizer.pipeline import _safe_step

        result = _safe_step("test", lambda: 1 / 0)
        assert result is None

    def test_returns_value_on_success(self):
        from telemetry_tool.sim_optimizer.pipeline import _safe_step

        result = _safe_step("test", lambda: 42)
        assert result == 42


class TestPipeline:
    def test_pipeline_produces_result(self, synthetic_raw_df, sim_config):
        from telemetry_tool.sim_optimizer.pipeline import optimize_session

        result = optimize_session(synthetic_raw_df, config=sim_config)
        assert result.success is True
        assert result.theoretical is not None
        assert result.theoretical.lap_time_s > 0

    def test_pipeline_has_vehicle_model(self, synthetic_raw_df, sim_config):
        from telemetry_tool.sim_optimizer.pipeline import optimize_session

        result = optimize_session(synthetic_raw_df, config=sim_config)
        assert result.vehicle_model is not None

    def test_pipeline_graceful_on_minimal_data(self, sim_config):
        from telemetry_tool.sim_optimizer.pipeline import optimize_session

        # Minimal DF with only Speed and LapDist — should not crash
        n = 100
        df = pd.DataFrame({
            "irsdk__Speed": np.linspace(20, 30, n),
            "irsdk__LapDist": np.linspace(0, 500, n),
        })
        result = optimize_session(df, config=sim_config)
        # Pipeline should degrade gracefully — may fail geometry or solver
        assert len(result.errors) > 0 or result.success is False
