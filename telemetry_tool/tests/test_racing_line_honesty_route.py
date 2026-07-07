"""Tests for the racing-line honesty gate on GET /sessions/<id>/optimal-line
(fix #3 — confirmed BLOCKER).

Before this fix the route returned ``pipeline.get("optimal_line")`` RAW with
full authority, even when it was built from unverified geometry or a
non-converged solver. The honesty layer (``track_surface/honesty.py``) already
existed but no web route consumed it.

The route now resolves the session's canonical track id and reads the gated
``track_racing_lines`` row (populated by ``decide_tier`` at compute time in
``tasks.racing_line_tasks.compute_racing_lines``). Only a row whose tier is
``optimal_line`` (``is_drawable_as_line(tier) is True``) may be returned as a
drawable, full-authority line; everything else — a lower gated tier, or no
gated row at all — degrades to the pre-existing ``available: false`` shape,
now also carrying ``tier`` / ``tier_reason`` / ``drawable``.

The DB-level gated lookup (``_lookup_gated_racing_line``) is mocked directly:
its own correctness (SQL, connection handling, JSONB decoding) is already
covered by test_racing_line_repo.py / test_migration_078.py / test_migration_080.py.
These tests exercise the ROUTE's honesty decision given a resolved gated row
(or the deliberate absence of one).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def app():
    """Minimal Flask app with just the data_v2 blueprint."""
    from flask import Flask

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["USE_PG"] = False

    from web.routes.data_v2 import bp
    app.register_blueprint(bp)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


# ── Sample data builders ─────────────────────────────────────────


def _session():
    return {
        "session_id": "s1",
        "track_id": "t1",
        "vehicle_class": "car",
    }


def _analysis(*, pipeline_optimal=None):
    return {
        "track_id": "t1",
        "vehicle_class": "car",
        "track_state": "dry",
        "pipeline": {"optimal_line": pipeline_optimal} if pipeline_optimal is not None else {},
    }


def _gated_row(*, tier, provenance=None, points=None, condition="dry"):
    return {
        "condition": condition,
        "status": "ok",
        "points": points if points is not None else [
            {"d": 0.0, "n": 0.10, "v": 30.0},
            {"d": 10.0, "n": -0.20, "v": 32.5},
        ],
        "lap_time_s": 61.234,
        "solver_version": "ocp2d-stitched-v1",
        "grip_snapshot_hash": "abc123",
        "n_laps_used": 12,
        "computed_at": "2026-07-01T00:00:00Z",
        "tier": tier,
        "geometry_source": "gt_anchored_native",
        "provenance": provenance or {},
    }


# ══════════════════════════════════════════════════════════════════
# (a) gated tier == optimal_line -> drawable line
# ══════════════════════════════════════════════════════════════════


class TestGatedOptimalLine:

    @patch("web.routes.data_v2._lookup_gated_racing_line")
    @patch("web.routes.data_v2.models")
    @patch("web.routes.data_v2.get_db_connection")
    def test_optimal_tier_returns_drawable_line(self, mock_conn, mock_models, mock_lookup, client):
        mock_models.get_session_by_id.return_value = _session()
        mock_models.get_analysis_json.return_value = _analysis()
        mock_lookup.return_value = _gated_row(tier="optimal_line", provenance={})

        resp = client.get("/api/v1/sessions/s1/optimal-line")
        assert resp.status_code == 200
        body = resp.get_json()
        data = body["data"]

        assert data["tier"] == "optimal_line"
        assert data["tier_reason"] is None
        assert data["drawable"] is True
        assert data["points"] == [
            {"distance_m": 0.0, "lateral_offset_m": 0.10, "speed_mps": 30.0},
            {"distance_m": 10.0, "lateral_offset_m": -0.20, "speed_mps": 32.5},
        ]
        assert data["lap_time_s"] == 61.234

        # Session -> canonical track id resolution actually happened.
        mock_lookup.assert_called_once_with("t1", "car", "dry")

    @patch("web.routes.data_v2._lookup_gated_racing_line")
    @patch("web.routes.data_v2.models")
    @patch("web.routes.data_v2.get_db_connection")
    def test_no_session_404(self, mock_conn, mock_models, mock_lookup, client):
        mock_models.get_session_by_id.return_value = None
        resp = client.get("/api/v1/sessions/nosuch/optimal-line")
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════
# (b) gated tier == speed_profile_only -> degrade, never drawable
# ══════════════════════════════════════════════════════════════════


class TestGatedSpeedProfileOnly:

    @patch("web.routes.data_v2._lookup_gated_racing_line")
    @patch("web.routes.data_v2.models")
    @patch("web.routes.data_v2.get_db_connection")
    def test_speed_profile_only_degrades(self, mock_conn, mock_models, mock_lookup, client):
        mock_models.get_session_by_id.return_value = _session()
        mock_models.get_analysis_json.return_value = _analysis()
        mock_lookup.return_value = _gated_row(
            tier="speed_profile_only",
            provenance={"tier_reason": "below_grip_floor"},
        )

        resp = client.get("/api/v1/sessions/s1/optimal-line")
        assert resp.status_code == 200
        body = resp.get_json()
        data = body["data"]

        assert data["available"] is False
        assert data["drawable"] is False
        assert data["tier"] == "speed_profile_only"
        assert data["tier_reason"] == "below_grip_floor"
        # No authoritative points payload may be emitted for a non-optimal tier.
        assert "points" not in data


# ══════════════════════════════════════════════════════════════════
# (c) tier == refused, OR no gated row at all -> degrade safely
# ══════════════════════════════════════════════════════════════════


class TestRefusedOrAbsent:

    @patch("web.routes.data_v2._lookup_gated_racing_line")
    @patch("web.routes.data_v2.models")
    @patch("web.routes.data_v2.get_db_connection")
    def test_refused_tier_degrades(self, mock_conn, mock_models, mock_lookup, client):
        mock_models.get_session_by_id.return_value = _session()
        mock_models.get_analysis_json.return_value = _analysis()
        mock_lookup.return_value = _gated_row(
            tier="refused",
            provenance={"reason": "solver_infeasible"},
        )

        resp = client.get("/api/v1/sessions/s1/optimal-line")
        assert resp.status_code == 200
        data = resp.get_json()["data"]

        assert data["available"] is False
        assert data["drawable"] is False
        assert data["tier"] == "refused"
        assert data["tier_reason"] == "solver_infeasible"
        assert "points" not in data

    @patch("web.routes.data_v2._lookup_gated_racing_line")
    @patch("web.routes.data_v2.models")
    @patch("web.routes.data_v2.get_db_connection")
    def test_no_gated_row_but_raw_pipeline_line_exists_degrades(
        self, mock_conn, mock_models, mock_lookup, client
    ):
        """A raw, ungated pipeline.optimal_line (no decide_tier signals on it)
        must NOT be presented as authoritative just because no gated row
        exists yet for this track."""
        mock_models.get_session_by_id.return_value = _session()
        mock_models.get_analysis_json.return_value = _analysis(pipeline_optimal={
            "points": [{"distance_m": 0.0, "lateral_offset_m": 0.0, "speed_mps": 28.0}],
            "lap_time_s": 65.0,
        })
        mock_lookup.return_value = None

        resp = client.get("/api/v1/sessions/s1/optimal-line")
        assert resp.status_code == 200
        data = resp.get_json()["data"]

        assert data["available"] is False
        assert data["drawable"] is False
        assert "points" not in data


# ══════════════════════════════════════════════════════════════════
# (d) existing missing-optimal-line precedent must survive unchanged
# ══════════════════════════════════════════════════════════════════


class TestExistingMissingOptimalLinePrecedent:

    @patch("web.routes.data_v2._lookup_gated_racing_line")
    @patch("web.routes.data_v2.models")
    @patch("web.routes.data_v2.get_db_connection")
    def test_pipeline_never_ran_unchanged(self, mock_conn, mock_models, mock_lookup, client):
        mock_models.get_session_by_id.return_value = _session()
        mock_models.get_analysis_json.return_value = _analysis(pipeline_optimal=None)
        mock_lookup.return_value = None

        resp = client.get("/api/v1/sessions/s1/optimal-line")
        assert resp.status_code == 200
        data = resp.get_json()["data"]

        # Precedent shape, unchanged.
        assert data["available"] is False
        assert data["reason_code"] == "optimal_line_not_computed"
        # Additive honesty fields.
        assert data["drawable"] is False
        assert data.get("tier") is None


# ══════════════════════════════════════════════════════════════════
# (e) EXCEPTION fallback: pipeline.optimal_line itself carries decide_tier's
#     4 signals -> gate on those inline rather than blanket-degrading.
# ══════════════════════════════════════════════════════════════════


class TestInlineFallbackWhenSignalsPresent:

    @patch("web.routes.data_v2._lookup_gated_racing_line")
    @patch("web.routes.data_v2.models")
    @patch("web.routes.data_v2.get_db_connection")
    def test_inline_signals_all_green_is_drawable(self, mock_conn, mock_models, mock_lookup, client):
        mock_models.get_session_by_id.return_value = _session()
        mock_models.get_analysis_json.return_value = _analysis(pipeline_optimal={
            "points": [{"distance_m": 0.0, "lateral_offset_m": 0.0, "speed_mps": 28.0}],
            "lap_time_s": 65.0,
            "boundary_source": "gt_anchored_native",
            "grip_tier": "gold",
            "validation_ok": True,
            "solve_status": "ok",
        })
        mock_lookup.return_value = None

        resp = client.get("/api/v1/sessions/s1/optimal-line")
        assert resp.status_code == 200
        data = resp.get_json()["data"]

        assert data["tier"] == "optimal_line"
        assert data["drawable"] is True
        assert data["points"] == [{"distance_m": 0.0, "lateral_offset_m": 0.0, "speed_mps": 28.0}]

    @patch("web.routes.data_v2._lookup_gated_racing_line")
    @patch("web.routes.data_v2.models")
    @patch("web.routes.data_v2.get_db_connection")
    def test_inline_signals_below_floor_degrades(self, mock_conn, mock_models, mock_lookup, client):
        mock_models.get_session_by_id.return_value = _session()
        mock_models.get_analysis_json.return_value = _analysis(pipeline_optimal={
            "points": [{"distance_m": 0.0, "lateral_offset_m": 0.0, "speed_mps": 28.0}],
            "lap_time_s": 65.0,
            "boundary_source": "derived_midline",
            "grip_tier": "bronze",
            "validation_ok": True,
            "solve_status": "ok",
        })
        mock_lookup.return_value = None

        resp = client.get("/api/v1/sessions/s1/optimal-line")
        assert resp.status_code == 200
        data = resp.get_json()["data"]

        assert data["available"] is False
        assert data["drawable"] is False
        assert data["tier"] == "speed_profile_only"
        assert "points" not in data


# ══════════════════════════════════════════════════════════════════
# /line-delta — investigated, no gated racing line of its own to leak.
# pipeline.line_delta is only ever produced from an already-gated optimal
# line; today it is never populated (dead producer), so the pre-existing
# available:false degrade already can't leak an unverified line.
# ══════════════════════════════════════════════════════════════════


class TestLineDeltaUnaffected:

    @patch("web.routes.data_v2.models")
    @patch("web.routes.data_v2.get_db_connection")
    def test_line_delta_still_degrades_when_absent(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = _session()
        mock_models.get_analysis_json.return_value = _analysis()

        resp = client.get("/api/v1/sessions/s1/line-delta")
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["available"] is False
        assert data["reason_code"] == "requires_optimal_line"
