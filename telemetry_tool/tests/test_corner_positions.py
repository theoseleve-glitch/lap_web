"""Tests for corner position GPS enrichment in data_v2._build_corner_positions."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import MagicMock, patch


def _make_gps_trace(n=100, track_len=500.0):
    """Create a fake GPS trace with monotonic distances."""
    import math
    dists = [i * track_len / (n - 1) for i in range(n)]
    lats = [45.0 + 0.001 * math.sin(2 * math.pi * i / n) for i in range(n)]
    lons = [7.0 + 0.001 * math.cos(2 * math.pi * i / n) for i in range(n)]
    return {
        "distances": dists,
        "latitudes": lats,
        "longitudes": lons,
        "speeds": [15.0] * n,
    }


class TestFirstNotNone:
    def test_returns_first_present_key(self):
        from web.routes.data_v2 import _first_not_none
        d = {"a": None, "b": 42, "c": 99}
        assert _first_not_none(d, "a", "b", "c") == 42

    def test_returns_none_when_all_missing(self):
        from web.routes.data_v2 import _first_not_none
        d = {"x": 1}
        assert _first_not_none(d, "a", "b") is None

    def test_zero_is_not_none(self):
        from web.routes.data_v2 import _first_not_none
        d = {"a": 0.0, "b": 5.0}
        assert _first_not_none(d, "a", "b") == 0.0

    def test_empty_string_is_not_none(self):
        from web.routes.data_v2 import _first_not_none
        d = {"a": "", "b": "hello"}
        assert _first_not_none(d, "a", "b") == ""


class TestBuildCornerPositions:
    """Test _build_corner_positions with different corner_coaching field shapes."""

    def _make_conn(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {"session_id": "s1"}
        return conn

    @patch("web.routes.data_v2.models")
    @patch("web.routes.data_v2._resolve_lap_number", return_value=1)
    def test_kart_envelope_fields_have_s_apex(self, mock_lap, mock_models):
        """kart_envelope CornerPerformance.to_dict() includes s_apex — should work."""
        from web.routes.data_v2 import _build_corner_positions

        mock_models.get_theoretical_data.return_value = {
            "corner_coaching": [
                {"corner_id": 0, "s_start": 50.0, "s_end": 100.0, "s_apex": 75.0, "direction": "L"},
                {"corner_id": 1, "s_start": 200.0, "s_end": 250.0, "s_apex": 225.0, "direction": "R"},
            ],
        }
        mock_models.get_gps_trace.return_value = _make_gps_trace()
        mock_models.get_corner_metrics_summary.return_value = []

        corners = _build_corner_positions(self._make_conn(), "s1")

        assert len(corners) == 2
        assert corners[0]["s_apex"] == 75.0
        assert corners[1]["s_apex"] == 225.0
        # GPS enrichment should have set lat/lon
        assert corners[0]["lat"] is not None
        assert corners[0]["lon"] is not None
        assert corners[1]["lat"] is not None

    @patch("web.routes.data_v2.models")
    @patch("web.routes.data_v2._resolve_lap_number", return_value=1)
    def test_telemetry_tool_fields_missing_s_apex(self, mock_lap, mock_models):
        """telemetry_tool CornerPerformance.to_dict() has s_start/s_end but NO s_apex.
        Midpoint fallback should kick in."""
        from web.routes.data_v2 import _build_corner_positions

        mock_models.get_theoretical_data.return_value = {
            "corner_coaching": [
                {"corner_id": 0, "s_start": 50.0, "s_end": 100.0, "direction": "L"},
                {"corner_id": 1, "s_start": 200.0, "s_end": 250.0, "direction": "R"},
            ],
        }
        mock_models.get_gps_trace.return_value = _make_gps_trace()
        mock_models.get_corner_metrics_summary.return_value = []

        corners = _build_corner_positions(self._make_conn(), "s1")

        assert len(corners) == 2
        # Midpoint fallback: (50+100)/2 = 75, (200+250)/2 = 225
        assert corners[0]["s_apex"] == 75.0
        assert corners[1]["s_apex"] == 225.0
        # GPS enrichment should have worked via midpoint
        assert corners[0]["lat"] is not None
        assert corners[0]["lon"] is not None
        # Corners should NOT be at the same position
        assert corners[0]["lat"] != corners[1]["lat"]

    @patch("web.routes.data_v2.models")
    @patch("web.routes.data_v2._resolve_lap_number", return_value=1)
    def test_apex_distance_m_field_recognized(self, mock_lap, mock_models):
        """apex_distance_m (from analysis_json corners) should be recognized."""
        from web.routes.data_v2 import _build_corner_positions

        mock_models.get_theoretical_data.return_value = {
            "corner_coaching": [
                {"corner_id": 0, "s_start": 50.0, "s_end": 100.0,
                 "apex_distance_m": 72.0, "direction": "L"},
            ],
        }
        mock_models.get_gps_trace.return_value = _make_gps_trace()
        mock_models.get_corner_metrics_summary.return_value = []

        corners = _build_corner_positions(self._make_conn(), "s1")

        assert corners[0]["s_apex"] == 72.0
        assert corners[0]["lat"] is not None

    @patch("web.routes.data_v2.models")
    @patch("web.routes.data_v2._resolve_lap_number", return_value=1)
    def test_zero_distance_not_treated_as_none(self, mock_lap, mock_models):
        """s_start=0 (start/finish corner) should NOT be treated as None."""
        from web.routes.data_v2 import _build_corner_positions

        mock_models.get_theoretical_data.return_value = {
            "corner_coaching": [
                {"corner_id": 0, "s_start": 0.0, "s_end": 30.0, "direction": "R"},
            ],
        }
        mock_models.get_gps_trace.return_value = _make_gps_trace()
        mock_models.get_corner_metrics_summary.return_value = []

        corners = _build_corner_positions(self._make_conn(), "s1")

        assert corners[0]["s_start"] == 0.0
        # Midpoint: (0+30)/2 = 15
        assert corners[0]["s_apex"] == 15.0
        assert corners[0]["lat"] is not None

    @patch("web.routes.data_v2.models")
    @patch("web.routes.data_v2._resolve_lap_number", return_value=None)
    def test_no_gps_trace_still_returns_corners(self, mock_lap, mock_models):
        """Without GPS trace, corners are returned with lat/lon = None."""
        from web.routes.data_v2 import _build_corner_positions

        mock_models.get_theoretical_data.return_value = {
            "corner_coaching": [
                {"corner_id": 0, "s_start": 50.0, "s_end": 100.0, "direction": "L"},
            ],
        }
        mock_models.get_gps_trace.return_value = None
        mock_models.get_corner_metrics_summary.return_value = []

        corners = _build_corner_positions(self._make_conn(), "s1")

        assert len(corners) == 1
        assert corners[0]["s_apex"] == 75.0
        assert corners[0]["lat"] is None


class TestCornerPositionsDistinct:
    """Verify that multiple corners end up at DIFFERENT positions."""

    @patch("web.routes.data_v2.models")
    @patch("web.routes.data_v2._resolve_lap_number", return_value=1)
    def test_three_corners_three_distinct_positions(self, mock_lap, mock_models):
        from web.routes.data_v2 import _build_corner_positions

        mock_models.get_theoretical_data.return_value = {
            "corner_coaching": [
                {"corner_id": 0, "s_start": 30.0, "s_end": 80.0},
                {"corner_id": 1, "s_start": 150.0, "s_end": 200.0},
                {"corner_id": 2, "s_start": 350.0, "s_end": 400.0},
            ],
        }
        mock_models.get_gps_trace.return_value = _make_gps_trace()
        mock_models.get_corner_metrics_summary.return_value = []

        conn = MagicMock()
        corners = _build_corner_positions(conn, "s1")

        assert len(corners) == 3
        lats = [c["lat"] for c in corners]
        lons = [c["lon"] for c in corners]
        # All should have GPS coords
        assert all(lat is not None for lat in lats)
        # All should be at DIFFERENT positions
        assert len(set(zip(lats, lons))) == 3, \
            f"Expected 3 distinct positions, got {set(zip(lats, lons))}"
