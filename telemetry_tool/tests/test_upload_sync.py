"""Tests for the synchronous session upload endpoint (POST /api/v1/sessions/upload).

Task 1.1 of the controlled re-port.  These tests mock ``run_full_analysis``
so no real pipeline execution happens.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _make_pipeline_summary(session_id: str = "test-session-001") -> dict:
    """Return a minimal pipeline summary dict matching run_full_analysis output."""
    return {
        "csv_path": "/tmp/test.csv",
        "session_meta": {
            "session_id": session_id,
            "session_type": "practice",
            "track_state": "dry",
            "driver_name": "TestDriver",
            "date": "2026-03-01",
        },
        "track_id": "t1",
        "lap_metrics": [
            {"lap_number": 1, "lap_time_s": 62.1},
            {"lap_number": 2, "lap_time_s": 61.5},
            {"lap_number": 3, "lap_time_s": 60.8},
        ],
        "lap_times": [62.1, 61.5, 60.8],
        "resampled_laps": {},
        "score_result": {
            "total_score": 75.0,
            "grade": "B",
            "sub_scores": {
                "pace": {"score": 18, "max": 25},
                "consistency": {"score": 20, "max": 25},
                "execution": {"score": 19, "max": 25},
                "robustness": {"score": 18, "max": 25},
            },
            "strengths": ["Good consistency"],
            "weaknesses": ["Brake too late"],
        },
        "steps_ok": ["ingest", "gps_filter", "corners", "scoring"],
        "steps_failed": ["ml_training"],
        "errors": {"ml_training": "Not enough data"},
        "trim_report": {},
    }


@pytest.fixture
def app():
    """Minimal Flask app with sessions_v2 blueprint."""
    from flask import Flask

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["USE_PG"] = False

    from web.routes.sessions_v2 import bp
    app.register_blueprint(bp)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestUploadSync:
    """POST /api/v1/sessions/upload"""

    def test_upload_returns_session_id(self, client):
        """POST with a valid CSV returns 200 with session_id and score info."""
        summary = _make_pipeline_summary()

        csv_content = (
            "Lap #,Time (s),Speed (m/s)\n"
            "1,0.0,10.5\n"
            "1,1.0,11.2\n"
        )
        data = {
            "file": (io.BytesIO(csv_content.encode()), "session.csv"),
            "session_type": "practice",
            "track_state": "dry",
            "driver_name": "TestDriver",
        }

        with patch("web.routes.sessions_v2.run_full_analysis", return_value=summary) as mock_rfa, \
             patch("web.routes.sessions_v2.get_db_connection") as mock_db, \
             patch("web.routes.sessions_v2.upsert_driver", return_value=1) as mock_ud, \
             patch("web.routes.sessions_v2.upsert_session", return_value="test-session-001") as mock_us, \
             patch("web.routes.sessions_v2.insert_laps", return_value=3) as mock_il, \
             patch("web.routes.sessions_v2.insert_score_details") as mock_isd, \
             patch("web.routes.sessions_v2.insert_gps_traces", return_value=0) as mock_igt:

            mock_conn = MagicMock()
            mock_db.return_value = mock_conn

            resp = client.post(
                "/api/v1/sessions/upload",
                data=data,
                content_type="multipart/form-data",
            )

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.data}"
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["session_id"] == "test-session-001"
        assert body["data"]["grade"] == "B"
        assert body["data"]["total_score"] == 75.0
        assert "ingest" in body["data"]["steps_ok"]
        assert "ml_training" in body["data"]["steps_failed"]

        # Verify the pipeline was called with correct args
        mock_rfa.assert_called_once()
        call_kwargs = mock_rfa.call_args.kwargs
        # csv_path: temp file
        assert str(call_kwargs["csv_path"]).endswith(".csv")
        # session_meta dict
        meta = call_kwargs["session_meta"]
        assert meta["session_type"] == "practice"
        assert meta["track_state"] == "dry"
        assert meta["driver_name"] == "TestDriver"

        # Verify persistence calls
        mock_ud.assert_called_once_with(mock_conn, "TestDriver")
        mock_us.assert_called_once_with(mock_conn, summary, 1)
        mock_il.assert_called_once_with(mock_conn, "test-session-001", summary)
        mock_isd.assert_called_once_with(mock_conn, "test-session-001", summary)
        mock_igt.assert_called_once_with(mock_conn, "test-session-001", summary)
        mock_conn.commit.assert_called()

    def test_upload_rejects_missing_file(self, client):
        """POST without a file returns 400."""
        resp = client.post(
            "/api/v1/sessions/upload",
            data={"session_type": "practice"},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["ok"] is False
        assert "file" in body["error"]["message"].lower()

    def test_upload_rejects_non_csv(self, client):
        """POST with a non-CSV file (.exe) returns 400."""
        data = {
            "file": (io.BytesIO(b"\x00\x01\x02"), "malware.exe"),
        }
        resp = client.post(
            "/api/v1/sessions/upload",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["ok"] is False
        assert "csv" in body["error"]["message"].lower()

    def test_upload_with_lap_range(self, client):
        """POST with lap_range parameter passes it to run_full_analysis."""
        summary = _make_pipeline_summary()
        csv_content = "Lap #,Time (s)\n1,0.0\n"
        data = {
            "file": (io.BytesIO(csv_content.encode()), "test.csv"),
            "session_type": "practice",
            "lap_range": "3-15",
        }

        with patch("web.routes.sessions_v2.run_full_analysis", return_value=summary) as mock_rfa, \
             patch("web.routes.sessions_v2.get_db_connection") as mock_db, \
             patch("web.routes.sessions_v2.upsert_driver", return_value=1), \
             patch("web.routes.sessions_v2.upsert_session", return_value="test-session-001"), \
             patch("web.routes.sessions_v2.insert_laps", return_value=3), \
             patch("web.routes.sessions_v2.insert_score_details"), \
             patch("web.routes.sessions_v2.insert_gps_traces", return_value=0):

            mock_db.return_value = MagicMock()
            resp = client.post(
                "/api/v1/sessions/upload",
                data=data,
                content_type="multipart/form-data",
            )

        assert resp.status_code == 200
        assert mock_rfa.call_args.kwargs["lap_range"] == (3, 15)

    def test_upload_with_exclude_laps(self, client):
        """POST with exclude_laps parameter is stored in session_meta."""
        summary = _make_pipeline_summary()
        csv_content = "Lap #,Time (s)\n1,0.0\n"
        data = {
            "file": (io.BytesIO(csv_content.encode()), "test.csv"),
            "session_type": "race",
            "exclude_laps": "1,2,16",
        }

        with patch("web.routes.sessions_v2.run_full_analysis", return_value=summary) as mock_rfa, \
             patch("web.routes.sessions_v2.get_db_connection") as mock_db, \
             patch("web.routes.sessions_v2.upsert_driver", return_value=1), \
             patch("web.routes.sessions_v2.upsert_session", return_value="test-session-001"), \
             patch("web.routes.sessions_v2.insert_laps", return_value=3), \
             patch("web.routes.sessions_v2.insert_score_details"), \
             patch("web.routes.sessions_v2.insert_gps_traces", return_value=0):

            mock_db.return_value = MagicMock()
            resp = client.post(
                "/api/v1/sessions/upload",
                data=data,
                content_type="multipart/form-data",
            )

        assert resp.status_code == 200
        meta = mock_rfa.call_args.kwargs["session_meta"]
        assert meta["exclude_laps"] == [1, 2, 16]

    def test_upload_pipeline_failure_returns_partial(self, client):
        """When pipeline raises an exception, return 500 with error details."""
        csv_content = "Lap #,Time (s)\n1,0.0\n"
        data = {
            "file": (io.BytesIO(csv_content.encode()), "test.csv"),
        }

        with patch("web.routes.sessions_v2.run_full_analysis",
                    side_effect=Exception("Pipeline exploded")):
            resp = client.post(
                "/api/v1/sessions/upload",
                data=data,
                content_type="multipart/form-data",
            )

        assert resp.status_code == 500
        body = resp.get_json()
        assert body["ok"] is False
        assert "pipeline" in body["error"]["message"].lower() or \
               "analysis" in body["error"]["message"].lower()

    def test_upload_accepts_txt_extension(self, client):
        """POST with .txt extension is also accepted (some tools export as .txt)."""
        summary = _make_pipeline_summary()
        csv_content = "Lap #,Time (s)\n1,0.0\n"
        data = {
            "file": (io.BytesIO(csv_content.encode()), "session.txt"),
        }

        with patch("web.routes.sessions_v2.run_full_analysis", return_value=summary), \
             patch("web.routes.sessions_v2.get_db_connection") as mock_db, \
             patch("web.routes.sessions_v2.upsert_driver", return_value=1), \
             patch("web.routes.sessions_v2.upsert_session", return_value="test-session-001"), \
             patch("web.routes.sessions_v2.insert_laps", return_value=3), \
             patch("web.routes.sessions_v2.insert_score_details"), \
             patch("web.routes.sessions_v2.insert_gps_traces", return_value=0):

            mock_db.return_value = MagicMock()
            resp = client.post(
                "/api/v1/sessions/upload",
                data=data,
                content_type="multipart/form-data",
            )

        assert resp.status_code == 200
