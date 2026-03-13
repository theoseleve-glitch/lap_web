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
        assert set(df.columns) == {"distance_m", "speed_mps", "time_s", "accel_long_mps2", "accel_lat_mps2"}
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


# ── Task 4: Connection leak prevention ──


class TestConnectionLeakPrevention:
    def test_load_session_data_closes_conn_on_db_error(self):
        """Connection must be closed if _load_session_data raises internally."""
        from tasks.ocp_tasks import _load_session_data

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = RuntimeError("DB gone")

        with patch("tasks.ocp_tasks.get_db_connection" if False else
                   "web.db.get_db_connection", return_value=mock_conn):
            with pytest.raises(RuntimeError, match="DB gone"):
                _load_session_data("sess-X", workspace_id=None)
        mock_conn.close.assert_called_once()

    def test_load_session_data_closes_conn_on_bad_json(self):
        """Connection closed when analysis_json column contains bad JSON."""
        from tasks.ocp_tasks import _load_session_data

        mock_conn = MagicMock()
        mock_row = {"analysis_json": "{INVALID JSON"}
        mock_conn.execute.return_value.fetchone.return_value = mock_row

        with patch("web.db.get_db_connection", return_value=mock_conn):
            with pytest.raises(Exception):
                _load_session_data("sess-X", workspace_id=None)
        mock_conn.close.assert_called_once()

    def test_run_ocp_impl_does_not_double_close(self):
        """If _load_session_data succeeds, _run_ocp_impl manages the conn."""
        from tasks.ocp_tasks import _run_ocp_impl

        with patch("tasks.ocp_tasks._load_session_data") as mock_load:
            mock_conn = MagicMock()
            mock_load.return_value = (mock_conn, {}, None, None, None)

            result = _run_ocp_impl("sess-1")
            # Should return None (no best_lap_df) and close once
            assert result is None
            mock_conn.close.assert_called_once()


# ── Task 5: VehicleClass fault tolerance ──


class TestVehicleClassFaultTolerance:
    def test_bad_vehicle_class_uses_fallback(self):
        """Invalid vehicle_class in analysis_json should not crash loading."""
        from tasks.ocp_tasks import _load_session_data

        mock_conn = MagicMock()
        analysis = {
            "vehicle_params": {
                "vehicle_class": "NONEXISTENT_CLASS_XYZ",
                "peak_lateral_g": 1.0,
                "rolling_resistance_est": 0.015,
                "aero_drag_factor_est": 0.0,
            }
        }
        import json as _json
        mock_row = {"analysis_json": _json.dumps(analysis)}
        mock_conn.execute.return_value.fetchone.return_value = mock_row

        with patch("web.db.get_db_connection", return_value=mock_conn):
            with patch("web.repos.lap_repo.get_laps_for_session", return_value=[]):
                with patch("web.repos.theoretical_repo.get_reference_line", return_value=None):
                    conn, aj, bldf, cp, vp = _load_session_data("sess-1", None)
        # Should not crash; vehicle_params falls back gracefully
        assert conn is mock_conn


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


# ── Task 8: Corner time computation ──


class TestComputeCornerTimes:
    def test_computes_times_for_corners(self):
        from tasks.ocp_tasks import _compute_corner_times

        result = _FakeResult(n=200, lap_time=70.0)
        analysis_json = _make_analysis_json()

        corner_times = _compute_corner_times(result, analysis_json)
        assert len(corner_times) == 2
        assert corner_times[0]["corner_id"] == 0
        assert corner_times[1]["corner_id"] == 1
        # Each corner traversal must take positive time
        assert corner_times[0]["time_s"] > 0
        assert corner_times[1]["time_s"] > 0
        # Apex speed should be positive
        assert corner_times[0]["apex_speed_mps"] > 0
        assert corner_times[0]["min_speed_mps"] > 0

    def test_returns_empty_for_no_corners(self):
        from tasks.ocp_tasks import _compute_corner_times

        result = _FakeResult(n=50)
        corner_times = _compute_corner_times(result, {"corners": []})
        assert corner_times == []

    def test_skips_corners_without_distances(self):
        from tasks.ocp_tasks import _compute_corner_times

        result = _FakeResult(n=50)
        # Corner missing s_start/s_end
        analysis_json = {"corners": [{"corner_id": 0}]}
        corner_times = _compute_corner_times(result, analysis_json)
        assert corner_times == []


# ── Task 9: Corner target field-name aliasing ──


class TestUpdateCornerTargets:
    def test_uses_coaching_field_names(self):
        """corner_coaching entries use entry_distance_m/exit_distance_m/apex_distance_m."""
        from tasks.ocp_tasks import _update_corner_targets

        result = _FakeResult(n=200, lap_time=70.0)
        analysis_json = {
            "corners": [],
            "corner_coaching": [
                {"corner_id": 0, "apex_distance_m": 75.0,
                 "entry_distance_m": 50.0, "exit_distance_m": 100.0,
                 "actual_apex_speed_mps": 12.0},
            ],
        }

        _update_corner_targets(analysis_json, result, [])

        cc = analysis_json["corner_coaching"][0]
        # Speed targets must be populated (not None / missing)
        assert "apex_speed_target_kmh" in cc
        assert cc["apex_speed_target_kmh"] > 0
        assert "entry_speed_target_kmh" in cc
        assert "exit_speed_target_kmh" in cc
        assert "theoretical_apex_mps" in cc

    def test_uses_corner_detection_field_names(self):
        """corner_coaching entries seeded from raw corners use s_start/s_end/s_apex."""
        from tasks.ocp_tasks import _update_corner_targets

        result = _FakeResult(n=200, lap_time=70.0)
        analysis_json = {
            "corners": [
                {"corner_id": 0, "s_start": 50.0, "s_apex": 75.0, "s_end": 100.0},
            ],
            "corner_coaching": [],  # empty → seeds from corners
        }

        _update_corner_targets(analysis_json, result, analysis_json["corners"])

        cc = analysis_json["corner_coaching"][0]
        assert "apex_speed_target_kmh" in cc
        assert cc["apex_speed_target_kmh"] > 0


# ── Task 10: Warm start monotonicity ──


class TestWarmStartMonotonicity:
    def test_non_monotonic_distances_handled(self):
        """Non-monotonic QSS distances should not crash or give NaN."""
        from tasks.ocp_tasks import _extract_warm_start

        class FakeMesh:
            s = np.linspace(0, 100, 50)

        # Intentionally non-monotonic distances
        analysis_json = {
            "optimal_v2": {
                "speed_profile": [
                    {"distance_m": 0.0, "speed_mps": 10.0},
                    {"distance_m": 50.0, "speed_mps": 20.0},
                    {"distance_m": 30.0, "speed_mps": 15.0},  # out of order
                    {"distance_m": 70.0, "speed_mps": 25.0},
                    {"distance_m": 100.0, "speed_mps": 10.0},
                ] + [{"distance_m": float(i), "speed_mps": 15.0} for i in range(5, 100, 10)]
            }
        }

        warm = _extract_warm_start(analysis_json, FakeMesh())
        assert warm is not None
        assert len(warm) == 50
        assert np.all(np.isfinite(warm))
        # Should be monotonically sensible after sorting
        assert np.all(warm >= 2.0)


# ── Task 11: Paired braking distance extraction ──


class TestPairedBrakingDists:
    def test_paired_lists_same_length(self):
        """actual and theoretical braking dists must always be the same length."""
        from tasks.ocp_tasks import _extract_paired_braking_dists

        result = _FakeResult(n=200, lap_time=70.0)
        analysis_json = {
            "corner_performances": [
                {"corner_id": 0, "s_start": 50.0, "braking_point_actual_m": 30.0},
                {"corner_id": 1, "s_start": 200.0, "braking_point_actual_m": 180.0},
                {"corner_id": 2, "s_start": 350.0, "braking_point_actual_m": 349.5},  # tiny actual (< 1m)
            ],
        }

        actual, theo = _extract_paired_braking_dists(result, analysis_json)
        assert len(actual) == len(theo)
        # Corner 2 has actual dist < 1m, so both lists should exclude it
        # (actual or theoretical might also be < 1m depending on OCP profile)

    def test_returns_empty_for_no_corner_perfs(self):
        from tasks.ocp_tasks import _extract_paired_braking_dists

        result = _FakeResult(n=50)
        actual, theo = _extract_paired_braking_dists(result, {})
        assert actual == []
        assert theo == []


# ── Task 12: Curvature periodicity ──


class TestCurvaturePeriodicity:
    def test_start_end_curvatures_match(self):
        from tasks.ocp_tasks import _curvature_from_reference_line
        import numpy as np

        # Simulate an oval track (closed circuit) — curvatures at
        # start and end should match after periodicity enforcement.
        n = 200
        distances = np.linspace(0, 500, n)
        # Circle: offset so start ≠ end in raw lat/lon
        theta = np.linspace(0, 2 * np.pi, n, endpoint=False)
        lats = 45.0 + 0.001 * np.cos(theta)
        lons = 9.0 + 0.001 * np.sin(theta)

        cp = _curvature_from_reference_line(distances, lats, lons)
        assert cp is not None
        kappa = cp["curvature_1pm"].to_numpy()
        # Start and end curvature must be identical
        assert kappa[0] == kappa[-1]
