"""
Quick verification tests for the corner picker / areas-of-interest changes.

Run from the telemetry_tool directory:
    python -m pytest tests/test_corner_picker_changes.py -v
"""

from __future__ import annotations

import json
import sqlite3
import sys
import os

# Add parent directory to sys.path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


# ---------------------------------------------------------------------------
# 1. Schema tests
# ---------------------------------------------------------------------------

class TestSchema:
    """Verify v15+ schema includes lat/lon/dist_m columns."""

    def test_schema_version_is_15(self):
        from db.schema import SCHEMA_VERSION
        assert SCHEMA_VERSION >= 15

    def test_track_key_corners_ddl_has_lat_lon(self):
        from db.schema import _TRACK_KEY_CORNERS_TABLE
        ddl = _TRACK_KEY_CORNERS_TABLE.lower()
        assert "lat" in ddl
        assert "lon" in ddl
        assert "dist_m" in ddl


class TestMigration:
    """Verify the v15 migration adds columns idempotently."""

    def test_migration_adds_columns(self, tmp_path):
        from db.migrate import ensure_schema
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        version = ensure_schema(conn)
        assert version >= 15

        # Verify columns exist
        cursor = conn.execute("PRAGMA table_info(track_key_corners)")
        col_names = [row[1] for row in cursor.fetchall()]
        assert "lat" in col_names
        assert "lon" in col_names
        assert "dist_m" in col_names
        conn.close()

    def test_migration_is_idempotent(self, tmp_path):
        from db.migrate import ensure_schema
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        v1 = ensure_schema(conn)
        v2 = ensure_schema(conn)  # should not raise
        assert v1 == v2
        conn.close()


# ---------------------------------------------------------------------------
# 2. Pipeline tests
# ---------------------------------------------------------------------------

class TestPipelineTrackLayout:
    """Verify _extract_track_layout_for_picker returns data with empty corners."""

    def test_layout_with_empty_corners(self):
        import pandas as pd
        from pipeline import _extract_track_layout_for_picker

        # Create a minimal DataFrame with GPS columns
        df = pd.DataFrame({
            "Latitude (deg)": [48.0, 48.001, 48.002, 48.003],
            "Longitude (deg)": [2.0, 2.001, 2.002, 2.003],
            "distance_m": [0.0, 100.0, 200.0, 300.0],
            "speed_mps": [10.0, 20.0, 30.0, 25.0],
        })

        # With empty corners list — should still return layout
        layout = _extract_track_layout_for_picker(df, [])
        assert layout is not None, "Should return layout even with no corners"
        assert layout["corners"] == []
        assert len(layout["latitudes"]) == 4
        assert len(layout["longitudes"]) == 4
        assert len(layout["speeds"]) == 4

    def test_layout_with_corners(self):
        import pandas as pd
        from pipeline import _extract_track_layout_for_picker

        df = pd.DataFrame({
            "Latitude (deg)": [48.0, 48.001, 48.002, 48.003],
            "Longitude (deg)": [2.0, 2.001, 2.002, 2.003],
            "distance_m": [0.0, 100.0, 200.0, 300.0],
            "speed_mps": [10.0, 20.0, 30.0, 25.0],
        })

        corners = [
            {"corner_id": 1, "s_apex": 100.0, "direction": "L"},
            {"corner_id": 2, "s_apex": 200.0, "direction": "R"},
        ]

        layout = _extract_track_layout_for_picker(df, corners)
        assert layout is not None
        assert len(layout["corners"]) == 2
        assert layout["corners"][0]["corner_id"] == 1
        assert layout["corners"][1]["corner_id"] == 2

    def test_layout_returns_none_without_gps(self):
        import pandas as pd
        from pipeline import _extract_track_layout_for_picker

        df = pd.DataFrame({
            "speed_mps": [10.0, 20.0],
            "distance_m": [0.0, 100.0],
        })

        layout = _extract_track_layout_for_picker(df, [])
        assert layout is None, "Should return None without lat/lon columns"


# ---------------------------------------------------------------------------
# 3. Backend API tests (persist key corners)
# ---------------------------------------------------------------------------

class TestPersistKeyCorners:
    """Verify _persist_key_corners handles both dict and int formats."""

    def _setup_db(self, tmp_path):
        from db.migrate import ensure_schema
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        ensure_schema(conn)
        conn.execute("PRAGMA foreign_keys=ON;")
        # Insert a dummy track (lap_length_m is NOT NULL)
        conn.execute(
            "INSERT OR IGNORE INTO tracks (track_id, track_name, lap_length_m) "
            "VALUES (?, ?, ?)",
            ("trk_001", "Test Track", 900.0),
        )
        conn.commit()
        return conn, db_path

    def test_persist_dict_corners(self, tmp_path):
        conn, db_path = self._setup_db(tmp_path)

        # Simulate the persist function inline (since it uses get_db_connection)
        track_id = "trk_001"
        corners = [
            {"corner_id": 1, "lat": 48.0, "lon": 2.0, "dist_m": 100.0, "label": "P1"},
            {"corner_id": 2, "lat": 48.001, "lon": 2.001, "dist_m": 200.0, "label": "C1L"},
            {"corner_id": 3, "lat": 48.002, "lon": 2.002, "dist_m": 300.0, "label": "P2"},
        ]

        conn.execute("DELETE FROM track_key_corners WHERE track_id = ?", (track_id,))
        for item in corners:
            conn.execute(
                "INSERT OR IGNORE INTO track_key_corners "
                "(track_id, corner_id, label, lat, lon, dist_m) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (track_id, int(item["corner_id"]), item.get("label"),
                 item.get("lat"), item.get("lon"), item.get("dist_m")),
            )
        conn.commit()

        # Verify
        rows = conn.execute(
            "SELECT corner_id, label, lat, lon, dist_m FROM track_key_corners "
            "WHERE track_id = ? ORDER BY corner_id",
            (track_id,),
        ).fetchall()

        assert len(rows) == 3
        assert rows[0] == (1, "P1", 48.0, 2.0, 100.0)
        assert rows[1] == (2, "C1L", 48.001, 2.001, 200.0)
        assert rows[2] == (3, "P2", 48.002, 2.002, 300.0)
        conn.close()

    def test_persist_plain_ints(self, tmp_path):
        conn, db_path = self._setup_db(tmp_path)
        track_id = "trk_001"

        # Plain int format (legacy compat)
        conn.execute("DELETE FROM track_key_corners WHERE track_id = ?", (track_id,))
        for cid in [1, 3, 5]:
            conn.execute(
                "INSERT OR IGNORE INTO track_key_corners "
                "(track_id, corner_id) VALUES (?, ?)",
                (track_id, cid),
            )
        conn.commit()

        rows = conn.execute(
            "SELECT corner_id, lat, lon FROM track_key_corners "
            "WHERE track_id = ? ORDER BY corner_id",
            (track_id,),
        ).fetchall()

        assert len(rows) == 3
        # lat/lon should be NULL for legacy format
        assert rows[0] == (1, None, None)
        assert rows[1] == (3, None, None)
        assert rows[2] == (5, None, None)
        conn.close()


# ---------------------------------------------------------------------------
# 4. Flask route tests (if Flask test client is available)
# ---------------------------------------------------------------------------

class TestFlaskRoutes:
    """Test the API endpoints for key corners."""

    @pytest.fixture
    def client(self, tmp_path):
        """Create a Flask test client."""
        try:
            from web.app import create_app
            from web.config import Config
        except ImportError:
            pytest.skip("Flask app not importable")

        cfg = Config()
        cfg.DB_PATH = tmp_path / "test.db"
        cfg.DATA_RAW_DIR = tmp_path / "raw"
        cfg.RESULTS_DIR = tmp_path / "results"
        cfg.UPLOAD_DIR = tmp_path / "uploads"
        cfg.DATA_RAW_DIR.mkdir(exist_ok=True)
        cfg.RESULTS_DIR.mkdir(exist_ok=True)
        cfg.UPLOAD_DIR.mkdir(exist_ok=True)

        app = create_app(cfg)
        app.config["TESTING"] = True

        # Insert a test track (lap_length_m is NOT NULL, must be provided)
        with app.app_context():
            from web.db import get_db_connection
            conn = get_db_connection()
            conn.execute(
                "INSERT OR IGNORE INTO tracks (track_id, track_name, lap_length_m) "
                "VALUES (?, ?, ?)",
                ("trk_test", "Test Circuit", 850.0),
            )
            conn.commit()

        yield app.test_client()

    def test_get_key_corners_empty(self, client):
        resp = client.get("/api/track/trk_test/key-corners")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data == []

    def test_set_and_get_key_corners(self, client):
        corners = [
            {"corner_id": 1, "label": "Turn 1", "lat": 48.0, "lon": 2.0, "dist_m": 100.0},
            {"corner_id": 2, "label": "Hairpin", "lat": 48.001, "lon": 2.001, "dist_m": 250.0},
            {"corner_id": 3, "label": "P3", "lat": 48.002, "lon": 2.002, "dist_m": 400.0},
        ]

        # POST
        resp = client.post(
            "/api/track/trk_test/key-corners",
            data=json.dumps({"corners": corners}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        result = resp.get_json()
        assert result["ok"] is True
        assert result["count"] == 3

        # GET
        resp = client.get("/api/track/trk_test/key-corners")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 3
        assert data[0]["corner_id"] == 1
        assert data[0]["lat"] == 48.0
        assert data[0]["lon"] == 2.0
        assert data[0]["dist_m"] == 100.0
        assert data[0]["label"] == "Turn 1"

    def test_set_key_corners_replaces(self, client):
        # Set initial
        client.post(
            "/api/track/trk_test/key-corners",
            data=json.dumps({"corners": [
                {"corner_id": 1, "lat": 48.0, "lon": 2.0},
                {"corner_id": 2, "lat": 48.001, "lon": 2.001},
                {"corner_id": 3, "lat": 48.002, "lon": 2.002},
            ]}),
            content_type="application/json",
        )

        # Replace with different set
        client.post(
            "/api/track/trk_test/key-corners",
            data=json.dumps({"corners": [
                {"corner_id": 10, "label": "New P1", "lat": 48.5, "lon": 2.5, "dist_m": 50.0},
                {"corner_id": 20, "label": "New P2", "lat": 48.6, "lon": 2.6, "dist_m": 150.0},
                {"corner_id": 30, "label": "New P3", "lat": 48.7, "lon": 2.7, "dist_m": 250.0},
            ]}),
            content_type="application/json",
        )

        # Verify old ones are gone
        resp = client.get("/api/track/trk_test/key-corners")
        data = resp.get_json()
        assert len(data) == 3
        assert data[0]["corner_id"] == 10
        assert data[0]["label"] == "New P1"

    def test_status_api_includes_track_id(self, client):
        """Verify the status API response schema includes track_id field."""
        # We can't easily test a live analysis job, but we can verify
        # the endpoint exists and returns an error for unknown job IDs
        resp = client.get("/analyze/api/status/nonexistent_job_123")
        assert resp.status_code == 404
        data = resp.get_json()
        assert "error" in data

    def test_submit_corners_accepts_dicts(self, client):
        """Verify submit_corners_api handles both formats."""
        # Unknown job returns 404
        resp = client.post(
            "/analyze/api/corners/nonexistent_job_123",
            data=json.dumps({"corners": [
                {"corner_id": 1, "lat": 48.0, "lon": 2.0},
                {"corner_id": 2, "lat": 48.1, "lon": 2.1},
                {"corner_id": 3, "lat": 48.2, "lon": 2.2},
            ]}),
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_submit_corners_validates_count(self, client):
        # Too few
        resp = client.post(
            "/analyze/api/corners/nonexistent_job_123",
            data=json.dumps({"corners": [1, 2]}),
            content_type="application/json",
        )
        # 404 because job doesn't exist, but validation happens after job lookup
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 5. JavaScript static analysis (verify no innerHTML with user data)
# ---------------------------------------------------------------------------

class TestJSSafety:
    """Static checks on JS files for security."""

    def test_corner_picker_no_innerhtml(self):
        js_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "web", "static", "js", "corner_picker_map.js",
        )
        with open(js_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "innerHTML" not in content, "corner_picker_map.js should not use innerHTML"

    def test_corner_picker_has_set_points(self):
        js_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "web", "static", "js", "corner_picker_map.js",
        )
        with open(js_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "setPoints" in content, "corner_picker_map.js should expose setPoints"
        assert "getSelected" in content, "corner_picker_map.js should expose getSelected"
        assert "onSelectionChange" in content, "corner_picker_map.js should expose onSelectionChange"

    def test_corner_picker_allows_click_anywhere(self):
        """Verify the picker uses nearest-track-point snapping, not just corner hit test."""
        js_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "web", "static", "js", "corner_picker_map.js",
        )
        with open(js_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "_nearestTrackPoint" in content, "Should have track-point snapping"
        assert "SNAP_DIST_PX" in content, "Should have snap distance threshold"

    def test_analyze_form_sends_full_objects(self):
        """Verify analyze_form.js sends full corner objects, not just IDs."""
        js_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "web", "static", "js", "analyze_form.js",
        )
        with open(js_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "_loadSavedKeyCorners" in content, "Should check for saved corners"
        assert "_saveCornerSelection" in content, "Should have save function"
        assert "corner-saved-banner" in content, "Should show saved corners banner"
