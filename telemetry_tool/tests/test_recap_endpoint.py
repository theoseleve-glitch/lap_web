"""Tests for GET /api/v1/recap/latest (Task 16).

The endpoint mirrors /quests: same blueprint + @_safe_api + get_db_connection
(GUC-pinned per-request connection).

All DB interaction is mocked — no real DB required.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def app():
    """Minimal Flask app with the data_v2 blueprint registered."""
    from flask import Flask

    application = Flask(__name__)
    application.config["TESTING"] = True
    application.config["USE_PG"] = False

    from web.routes.data_v2 import bp
    application.register_blueprint(bp)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _mock_conn(row=None):
    """Return a MagicMock that mimics PgConnectionWrapper / sqlite for execute().fetchone()."""
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = row
    return conn


# ── Tests ─────────────────────────────────────────────────────────


class TestLatestRecapEndpoint:
    """GET /api/v1/recap/latest"""

    def test_returns_latest_recap_when_row_exists(self, client):
        """When a weekly_recap row exists, the endpoint returns iso_week + payload fields."""
        row = {
            "iso_week": "2026-W23",
            "payload": json.dumps({
                "quests_completed": 2,
                "current_streak": 5,
                "next_focus": "Carry 58 km/h through T5",
                "week_start": "2026-06-02",
                "week_end": "2026-06-09",
            }),
            "created_at": "2026-06-09T06:00:00+00:00",
            "emailed": False,
        }
        mock_conn = _mock_conn(row)
        with patch("web.routes.data_v2.get_db_connection", return_value=mock_conn):
            resp = client.get("/api/v1/recap/latest?driver_id=1")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        recap = data["data"]["recap"]
        assert recap is not None
        assert recap["iso_week"] == "2026-W23"
        assert recap["quests_completed"] == 2
        assert recap["current_streak"] == 5
        assert recap["next_focus"] == "Carry 58 km/h through T5"
        assert recap["created_at"] == "2026-06-09T06:00:00+00:00"

    def test_returns_null_recap_when_no_row_exists(self, client):
        """When no weekly_recap row exists yet, recap is null — NOT a 404.

        The RecapCard self-hides until the Monday beat task has run.
        """
        mock_conn = _mock_conn(row=None)
        with patch("web.routes.data_v2.get_db_connection", return_value=mock_conn):
            resp = client.get("/api/v1/recap/latest?driver_id=1")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["data"]["recap"] is None

    def test_default_driver_id_when_param_missing(self, client):
        """driver_id defaults to 1 when the query param is absent."""
        mock_conn = _mock_conn(row=None)
        with patch("web.routes.data_v2.get_db_connection", return_value=mock_conn):
            resp = client.get("/api/v1/recap/latest")

        assert resp.status_code == 200
        # Verify execute was called with drv=1
        call_kwargs = mock_conn.execute.call_args
        assert call_kwargs[0][1]["drv"] == 1

    def test_default_driver_id_when_param_invalid(self, client):
        """driver_id defaults to 1 when the query param cannot be parsed as int."""
        mock_conn = _mock_conn(row=None)
        with patch("web.routes.data_v2.get_db_connection", return_value=mock_conn):
            resp = client.get("/api/v1/recap/latest?driver_id=abc")

        assert resp.status_code == 200
        call_kwargs = mock_conn.execute.call_args
        assert call_kwargs[0][1]["drv"] == 1

    def test_payload_dict_decoded_when_stored_as_string(self, client):
        """payload stored as JSON string (sqlite) is decoded to a dict in the response."""
        row = {
            "iso_week": "2026-W22",
            "payload": '{"quests_completed": 1, "current_streak": 3, "next_focus": null}',
            "created_at": None,
            "emailed": False,
        }
        mock_conn = _mock_conn(row)
        with patch("web.routes.data_v2.get_db_connection", return_value=mock_conn):
            resp = client.get("/api/v1/recap/latest?driver_id=1")

        assert resp.status_code == 200
        recap = resp.get_json()["data"]["recap"]
        # payload fields must be decoded — not a raw string
        assert recap["quests_completed"] == 1
        assert recap["next_focus"] is None

    def test_payload_dict_passthrough_when_already_decoded(self, client):
        """payload stored as dict (PgConnectionWrapper JSONB) passes through unchanged."""
        row = {
            "iso_week": "2026-W22",
            "payload": {"quests_completed": 3, "current_streak": 7, "next_focus": "Keep lap-time spread under 5%"},
            "created_at": None,
            "emailed": True,
        }
        mock_conn = _mock_conn(row)
        with patch("web.routes.data_v2.get_db_connection", return_value=mock_conn):
            resp = client.get("/api/v1/recap/latest?driver_id=1")

        assert resp.status_code == 200
        recap = resp.get_json()["data"]["recap"]
        assert recap["quests_completed"] == 3
        assert recap["emailed"] is True

    def test_created_at_datetime_serialized_to_iso(self, client):
        """created_at datetime objects (from PG) are serialized to ISO strings."""
        from datetime import datetime, timezone

        dt = datetime(2026, 6, 9, 6, 0, 0, tzinfo=timezone.utc)
        row = {
            "iso_week": "2026-W23",
            "payload": {},
            "created_at": dt,
            "emailed": False,
        }
        mock_conn = _mock_conn(row)
        with patch("web.routes.data_v2.get_db_connection", return_value=mock_conn):
            resp = client.get("/api/v1/recap/latest")

        assert resp.status_code == 200
        recap = resp.get_json()["data"]["recap"]
        assert recap["created_at"] == dt.isoformat()

    def test_query_is_parameterized_with_driver_id(self, client):
        """SQL is called with a :drv parameter (not string interpolation)."""
        mock_conn = _mock_conn(row=None)
        with patch("web.routes.data_v2.get_db_connection", return_value=mock_conn):
            resp = client.get("/api/v1/recap/latest?driver_id=42")

        assert resp.status_code == 200
        call_args = mock_conn.execute.call_args
        sql = call_args[0][0]
        params = call_args[0][1]
        assert ":drv" in sql
        assert params["drv"] == 42
        assert "weekly_recap" in sql
        assert "ORDER BY created_at DESC LIMIT 1" in sql
