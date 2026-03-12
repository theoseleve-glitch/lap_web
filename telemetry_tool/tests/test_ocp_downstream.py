"""Tests for OCP downstream update chain in tasks/ocp_tasks.py."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock


class _FakeResult:
    """Minimal stand-in for solver.result.TheoreticalResult."""
    def __init__(self, n=100, lap_time=70.0, converged=True):
        self.distance_profile = np.linspace(0, 500, max(n, 2))[:n]
        self.speed_profile = (15.0 + 5.0 * np.sin(np.linspace(0, 4 * np.pi, max(n, 2))))[:n]
        if n >= 2:
            self.a_long_profile = np.gradient(self.speed_profile ** 2 / 2, self.distance_profile)
        else:
            self.a_long_profile = np.zeros(n)
        self.a_lat_profile = self.speed_profile ** 2 * 0.01  # fake curvature
        self.lap_time_s = lap_time
        self.converged = converged
        self.solver_meta = {"wall_time_s": 1.5, "iterations": 200, "converged": converged, "nodes": n}

    def to_dict(self):
        return {
            "lap_time_s": self.lap_time_s,
            "speed_profile": [
                {"distance_m": round(float(self.distance_profile[i]), 2),
                 "speed_mps": round(float(self.speed_profile[i]), 3)}
                for i in range(len(self.speed_profile))
            ],
            "converged": self.converged,
            "solver_meta": self.solver_meta,
            "vehicle_params_used": {},
            "calibration": {},
            "corner_times": [],
            "tier": 1,
        }


# ── Task 1: _ocp_result_to_dataframe + _build_theoretical_result_dict ──


class TestOcpResultToDataframe:
    def test_produces_correct_columns(self):
        from tasks.ocp_tasks import _ocp_result_to_dataframe

        result = _FakeResult(n=50)
        df = _ocp_result_to_dataframe(result)

        assert isinstance(df, pd.DataFrame)
        assert set(df.columns) == {"distance_m", "speed_mps", "time_s", "a_long", "a_lat"}
        assert len(df) == 50

    def test_cumulative_time_increases(self):
        from tasks.ocp_tasks import _ocp_result_to_dataframe

        result = _FakeResult(n=50)
        df = _ocp_result_to_dataframe(result)

        assert df["time_s"].iloc[0] == 0.0
        assert df["time_s"].iloc[-1] > 0.0
        assert (df["time_s"].diff().iloc[1:] > 0).all()

    def test_returns_none_for_short_profile(self):
        from tasks.ocp_tasks import _ocp_result_to_dataframe

        result = _FakeResult(n=1)
        assert _ocp_result_to_dataframe(result) is None


class TestBuildTheoreticalResultDict:
    def test_produces_correct_shape(self):
        from tasks.ocp_tasks import _build_theoretical_result_dict

        result = _FakeResult(n=50)
        d = _build_theoretical_result_dict(result)

        assert isinstance(d, dict)
        assert "speed_profile" in d
        assert "track_length_m" in d
        assert isinstance(d["speed_profile"], list)
        assert len(d["speed_profile"]) == 50
        assert "distance_m" in d["speed_profile"][0]
        assert "speed_mps" in d["speed_profile"][0]
        assert d["track_length_m"] == pytest.approx(500.0, abs=1.0)


# ── Task 2: Full _update_downstream chain ──


def _make_best_lap_df():
    """Minimal best-lap DataFrame with columns expected by corner analysis."""
    return pd.DataFrame({
        "distance_m": np.linspace(0, 500, 500),
        "speed_mps": 15.0 + 0.01 * np.arange(500),
        "a_lat": np.zeros(500),
        "a_long": np.zeros(500),
    })


def _make_analysis_json():
    """Minimal analysis_json with required keys."""
    return {
        "lap_times": [74.3, 75.1, 76.0],
        "speed_trace_best": [
            {"distance_m": float(i), "speed_mps": 15.0 + 0.01 * i}
            for i in range(500)
        ],
        "corners": [
            {"corner_id": 0, "s_start": 50.0, "s_apex": 75.0, "s_end": 100.0,
             "apex_speed_mps": 12.0, "apex_distance_m": 75.0},
            {"corner_id": 1, "s_start": 200.0, "s_apex": 225.0, "s_end": 250.0,
             "apex_speed_mps": 14.0, "apex_distance_m": 225.0},
        ],
        "corner_coaching": [
            {"corner_id": 0, "apex_distance_m": 75.0, "entry_distance_m": 50.0,
             "exit_distance_m": 100.0, "actual_apex_speed_mps": 12.0},
            {"corner_id": 1, "apex_distance_m": 225.0, "entry_distance_m": 200.0,
             "exit_distance_m": 250.0, "actual_apex_speed_mps": 14.0},
        ],
        "friction_model": {"max_lateral_g": 1.2},
        "session_type": "practice",
    }


class TestUpdateDownstream:
    @patch("tasks.ocp_tasks._persist_all")
    def test_calls_score_session_with_ocp_method(self, mock_persist):
        from tasks.ocp_tasks import _update_downstream

        result = _FakeResult(n=100, lap_time=68.5)
        result_dict = result.to_dict()
        analysis_json = _make_analysis_json()
        conn = MagicMock()

        _update_downstream(conn, "sess-1", result, result_dict, analysis_json)

        # Verify scoring was run and stored
        assert analysis_json["simulation_method"] == "ocp"
        assert analysis_json["theoretical_metrics"]["best_s"] == 68.5
        assert analysis_json["theoretical_metrics"]["simulation_method"] == "ocp"
        assert "score_result" in analysis_json
        assert analysis_json["score_result"]["total_score"] >= 0

        # Verify persist was called
        mock_persist.assert_called_once()

    @patch("tasks.ocp_tasks._persist_all")
    def test_calls_corner_analysis_when_corners_exist(self, mock_persist):
        from tasks.ocp_tasks import _update_downstream

        result = _FakeResult(n=100, lap_time=68.5)
        result_dict = result.to_dict()
        analysis_json = _make_analysis_json()
        conn = MagicMock()

        with patch("pipeline.stages.s10b_corners.run_corner_analysis") as mock_ca:
            mock_ca.return_value = [
                {"corner_id": 0, "time_loss_s": 0.3},
                {"corner_id": 1, "time_loss_s": 0.5},
            ]
            _update_downstream(conn, "sess-1", result, result_dict, analysis_json,
                               best_lap_df=_make_best_lap_df())
            mock_ca.assert_called_once()
            # Verify theoretical_lap arg is a DataFrame (3rd positional arg)
            call_args = mock_ca.call_args
            theo_arg = call_args[0][2]
            assert isinstance(theo_arg, pd.DataFrame)
            assert "distance_m" in theo_arg.columns

    @patch("tasks.ocp_tasks._persist_all")
    def test_graceful_degradation_preserves_ocp_data(self, mock_persist):
        """If corner analysis or coaching throws, scoring + OCP data should still be stored."""
        from tasks.ocp_tasks import _update_downstream

        result = _FakeResult(n=100, lap_time=68.5)
        result_dict = result.to_dict()
        analysis_json = _make_analysis_json()
        conn = MagicMock()

        with patch("pipeline.stages.s10b_corners.run_corner_analysis", side_effect=RuntimeError("boom")):
            # Should NOT raise — graceful degradation
            _update_downstream(conn, "sess-1", result, result_dict, analysis_json,
                               best_lap_df=_make_best_lap_df())

        # Scoring should still be updated even if corners failed
        assert analysis_json["simulation_method"] == "ocp"
        assert "score_result" in analysis_json
        mock_persist.assert_called_once()

    def test_no_crash_when_no_lap_times(self):
        """analysis_json with no lap_times should exit early without error."""
        from tasks.ocp_tasks import _update_downstream

        result = _FakeResult(n=100, lap_time=68.5)
        result_dict = result.to_dict()
        analysis_json = {"corners": [], "corner_coaching": []}
        conn = MagicMock()

        # Should not raise
        _update_downstream(conn, "sess-1", result, result_dict, analysis_json)


# ── Task 3: RLS workspace context ──


class TestRlsContext:
    @patch.dict(os.environ, {"USE_PG": "1"})
    @patch("tasks.ocp_tasks._persist_all")
    def test_workspace_context_set_before_persist(self, mock_persist):
        from tasks.ocp_tasks import _update_downstream

        result = _FakeResult(n=100, lap_time=68.5)
        result_dict = result.to_dict()
        analysis_json = _make_analysis_json()
        conn = MagicMock()

        with patch("tasks.ocp_tasks._set_rls_if_pg") as mock_rls:
            _update_downstream(conn, "sess-1", result, result_dict, analysis_json, workspace_id=1)
            mock_rls.assert_called_once_with(conn, 1)


# ── Task 7: End-to-end smoke test ──


class TestEndToEndSmoke:
    """Verify the full chain doesn't crash with realistic-ish data."""

    def test_full_chain_smoke(self):
        from tasks.ocp_tasks import (
            _ocp_result_to_dataframe,
            _build_theoretical_result_dict,
            _extract_observed_metrics,
        )

        result = _FakeResult(n=200, lap_time=70.0)
        analysis_json = _make_analysis_json()

        # DataFrame conversion
        theo_df = _ocp_result_to_dataframe(result)
        assert theo_df is not None
        assert len(theo_df) == 200
        assert theo_df["time_s"].iloc[-1] > 0

        # Dict conversion
        theo_dict = _build_theoretical_result_dict(result)
        assert theo_dict["track_length_m"] > 0
        assert len(theo_dict["speed_profile"]) == 200

        # Observed metrics
        obs = _extract_observed_metrics(analysis_json)
        assert obs["best_s"] == 74.3
        assert obs["n_laps"] == 3
        assert obs["cv_pct"] > 0
