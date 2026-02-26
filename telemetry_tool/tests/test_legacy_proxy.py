"""Tests for legacy endpoint deprecation headers and v1 equivalence."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from flask import Flask

from web.api_utils import init_request_id
from web.routes.api_data import bp as api_bp, _deprecation_headers
from web.routes.api_v1_data import bp as api_v1_data_bp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    """Flask app with both legacy and v1 blueprints."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    init_request_id(app)
    app.register_blueprint(api_bp)
    app.register_blueprint(api_v1_data_bp)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def _mock_conn():
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = None
    conn.execute.return_value.fetchall.return_value = []
    return conn


# ---------------------------------------------------------------------------
# _deprecation_headers helper
# ---------------------------------------------------------------------------

class TestDeprecationHeadersHelper:
    def test_returns_three_headers(self):
        """_deprecation_headers returns Deprecation, Sunset, and Link."""
        headers = _deprecation_headers("/api/v1/sessions/s1/laps/gps")
        assert headers["Deprecation"] == "true"
        assert headers["Sunset"] == "2026-09-01"
        assert "rel=\"successor-version\"" in headers["Link"]
        assert "/api/v1/sessions/s1/laps/gps" in headers["Link"]

    def test_link_format(self):
        """Link header has correct angle-bracket format."""
        headers = _deprecation_headers("/api/v1/tracks/t1/records")
        assert headers["Link"] == '</api/v1/tracks/t1/records>; rel="successor-version"'


# ---------------------------------------------------------------------------
# Legacy endpoints return deprecation headers
# ---------------------------------------------------------------------------

class TestLegacyDeprecationHeaders:
    @patch("web.routes.api_data.get_db_connection")
    @patch("web.routes.api_data.get_gps_lap_numbers", return_value=[1, 2])
    def test_gps_laps_has_deprecation(self, mock_laps, mock_db, client):
        """GET /api/session/<id>/gps_laps includes Deprecation header."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/session/s1/gps_laps")
        assert resp.headers.get("Deprecation") == "true"
        assert resp.headers.get("Sunset") == "2026-09-01"
        assert "/api/v1/" in resp.headers.get("Link", "")

    @patch("web.routes.api_data.get_db_connection")
    @patch("web.routes.api_data.get_laps_for_session", return_value=[])
    def test_lap_times_has_deprecation(self, mock_laps, mock_db, client):
        """GET /api/session/<id>/lap_times includes Deprecation header."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/session/s1/lap_times")
        assert resp.headers.get("Deprecation") == "true"

    @patch("web.routes.api_data.get_db_connection")
    @patch("web.routes.api_data.get_track_records", return_value=[])
    def test_track_records_has_deprecation(self, mock_recs, mock_db, client):
        """GET /api/track/<id>/records includes Deprecation header."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/track/t1/records")
        assert resp.headers.get("Deprecation") == "true"

    @patch("web.routes.api_data.get_db_connection")
    @patch("web.routes.api_data.get_theoretical_data", return_value=None)
    def test_theoretical_has_deprecation(self, mock_theo, mock_db, client):
        """GET /api/session/<id>/theoretical includes Deprecation even on 404."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/session/s1/theoretical")
        assert resp.headers.get("Deprecation") == "true"

    @patch("web.routes.api_data.get_db_connection")
    @patch("web.routes.api_data.get_reference_line", return_value=None)
    def test_reference_line_has_deprecation(self, mock_ref, mock_db, client):
        """GET /api/session/<id>/reference_line includes Deprecation."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/session/s1/reference_line")
        assert resp.headers.get("Deprecation") == "true"


# ---------------------------------------------------------------------------
# Legacy endpoints still return 200 (backward compat)
# ---------------------------------------------------------------------------

class TestLegacyBackwardCompat:
    @patch("web.routes.api_data.get_db_connection")
    @patch("web.routes.api_data.get_gps_lap_numbers", return_value=[1])
    def test_gps_laps_still_returns_200(self, mock_laps, mock_db, client):
        """Legacy endpoint still returns 200 with old format."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/session/s1/gps_laps")
        assert resp.status_code == 200
        body = resp.get_json()
        assert "laps" in body

    @patch("web.routes.api_data.get_db_connection")
    @patch("web.routes.api_data.get_track_records", return_value=[{"time": 60}])
    def test_track_records_still_returns_200(self, mock_recs, mock_db, client):
        """Legacy track records endpoint still returns 200."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/track/t1/records")
        assert resp.status_code == 200
        body = resp.get_json()
        assert "records" in body


# ---------------------------------------------------------------------------
# V1 endpoints do NOT have deprecation headers
# ---------------------------------------------------------------------------

class TestV1NoDeprecation:
    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_gps_lap_numbers", return_value=[1])
    def test_v1_laps_gps_no_deprecation(self, mock_laps, mock_db, client):
        """V1 endpoints do not carry Deprecation header."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/v1/sessions/s1/laps/gps")
        assert resp.headers.get("Deprecation") is None


# ---------------------------------------------------------------------------
# Sunset header correct date
# ---------------------------------------------------------------------------

class TestSunsetDate:
    @patch("web.routes.api_data.get_db_connection")
    @patch("web.routes.api_data.get_gps_lap_numbers", return_value=[])
    def test_sunset_date_is_2026_09_01(self, mock_laps, mock_db, client):
        """Sunset header is set to 2026-09-01."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/session/s1/gps_laps")
        assert resp.headers.get("Sunset") == "2026-09-01"


# ---------------------------------------------------------------------------
# Link header points to correct v1 equivalent
# ---------------------------------------------------------------------------

class TestLinkHeader:
    @patch("web.routes.api_data.get_db_connection")
    @patch("web.routes.api_data.get_gps_lap_numbers", return_value=[])
    def test_gps_laps_link_points_to_v1(self, mock_laps, mock_db, client):
        """Link header for /api/session/<id>/gps_laps points to v1 laps/gps."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/session/s1/gps_laps")
        link = resp.headers.get("Link", "")
        assert "/api/v1/sessions/s1/laps/gps" in link

    @patch("web.routes.api_data.get_db_connection")
    @patch("web.routes.api_data.get_track_records", return_value=[])
    def test_track_records_link_points_to_v1(self, mock_recs, mock_db, client):
        """Link header for /api/track/<id>/records points to v1 tracks/records."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/track/t1/records")
        link = resp.headers.get("Link", "")
        assert "/api/v1/tracks/t1/records" in link
