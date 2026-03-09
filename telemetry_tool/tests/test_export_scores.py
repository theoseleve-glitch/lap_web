"""Tests for scoring history CSV export (#0198)."""
import csv
import io
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from web.app import create_app


@pytest.fixture
def api_client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def _mock_session(sid="s1", track="Monza", driver="Max", score=85.0, grade="A"):
    return {
        "session_id": sid,
        "session_date": "2026-03-01",
        "track_name": track,
        "driver_name": driver,
        "best_lap_time_s": 62.5,
        "total_score": score,
        "grade": grade,
    }


def _mock_scores():
    return {
        "pace_score": 22.0, "pace_max": 25.0,
        "consistency_score": 20.5, "consistency_max": 25.0,
        "execution_score": 21.0, "execution_max": 25.0,
        "robustness_score": 19.5, "robustness_max": 25.0,
        "adaptation_score": 8.0,
    }


class TestExportScores:
    @patch("web.routes.data_v2.get_db_connection")
    @patch("web.routes.data_v2.models")
    def test_export_csv_success(self, mock_models, mock_conn, api_client):
        mock_models.get_sessions.return_value = [
            _mock_session("s1"), _mock_session("s2", "Spa", "Lewis", 78.0, "B"),
        ]
        mock_models.get_score_details.return_value = _mock_scores()

        resp = api_client.get("/api/v1/export/scores")
        assert resp.status_code == 200
        assert resp.content_type == "text/csv; charset=utf-8"
        assert "scoring_history.csv" in resp.headers.get("Content-Disposition", "")

        reader = csv.reader(io.StringIO(resp.data.decode()))
        rows = list(reader)
        assert rows[0][0] == "session_id"  # header
        assert len(rows) == 3  # header + 2 data rows
        assert rows[1][0] == "s1"
        assert rows[2][0] == "s2"

    @patch("web.routes.data_v2.get_db_connection")
    @patch("web.routes.data_v2.models")
    def test_export_csv_no_sessions(self, mock_models, mock_conn, api_client):
        mock_models.get_sessions.return_value = []

        resp = api_client.get("/api/v1/export/scores")
        assert resp.status_code == 404

    @patch("web.routes.data_v2.get_db_connection")
    @patch("web.routes.data_v2.models")
    def test_export_csv_skips_unscored(self, mock_models, mock_conn, api_client):
        mock_models.get_sessions.return_value = [
            _mock_session("s1"), _mock_session("s2"),
        ]
        mock_models.get_score_details.side_effect = [_mock_scores(), None]

        resp = api_client.get("/api/v1/export/scores")
        assert resp.status_code == 200

        reader = csv.reader(io.StringIO(resp.data.decode()))
        rows = list(reader)
        assert len(rows) == 2  # header + 1 scored session

    @patch("web.routes.data_v2.get_db_connection")
    @patch("web.routes.data_v2.models")
    def test_export_csv_limit_param(self, mock_models, mock_conn, api_client):
        mock_models.get_sessions.return_value = [_mock_session()]
        mock_models.get_score_details.return_value = _mock_scores()

        api_client.get("/api/v1/export/scores?limit=10")
        mock_models.get_sessions.assert_called_once_with(
            mock_conn.return_value, limit=10, offset=0,
        )

    @patch("web.routes.data_v2.get_db_connection")
    @patch("web.routes.data_v2.models")
    def test_export_csv_limit_capped(self, mock_models, mock_conn, api_client):
        mock_models.get_sessions.return_value = [_mock_session()]
        mock_models.get_score_details.return_value = _mock_scores()

        api_client.get("/api/v1/export/scores?limit=9999")
        mock_models.get_sessions.assert_called_once_with(
            mock_conn.return_value, limit=2000, offset=0,
        )

    @patch("web.routes.data_v2.get_db_connection")
    @patch("web.routes.data_v2.models")
    def test_export_csv_column_values(self, mock_models, mock_conn, api_client):
        mock_models.get_sessions.return_value = [_mock_session()]
        mock_models.get_score_details.return_value = _mock_scores()

        resp = api_client.get("/api/v1/export/scores")
        reader = csv.DictReader(io.StringIO(resp.data.decode()))
        row = next(reader)
        assert row["track_name"] == "Monza"
        assert row["pace_score"] == "22.0"
        assert row["adaptation_score"] == "8.0"
