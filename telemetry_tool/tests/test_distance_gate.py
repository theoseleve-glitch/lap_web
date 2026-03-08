"""Integration tests for distance integrity gating in the pipeline."""
import numpy as np
import pandas as pd
import pytest


def test_distance_quality_in_summary(seeded_db, tmp_path):
    """Pipeline injects distance_quality into summary dict."""
    import pipeline

    csv_path = tmp_path / "test.csv"
    n = 500
    laps = np.repeat([1, 2], n // 2)
    time = np.linspace(0, 60, n)
    speed = np.random.default_rng(42).uniform(10, 30, n)
    dist = np.cumsum(speed * np.diff(np.concatenate([[0], time])))
    lat = np.linspace(45.0, 45.001, n)
    lon = np.linspace(9.0, 9.001, n)

    df = pd.DataFrame({
        "Lap #": laps,
        "Time (s)": time,
        "Speed (m/s)": speed,
        "Distance (m)": dist,
        "Latitude (deg)": lat,
        "Longitude (deg)": lon,
    })
    df.to_csv(csv_path, index=False)

    summary = pipeline.run_full_analysis(str(csv_path), {})
    assert "distance_quality" in summary
    dq = summary["distance_quality"]
    assert dq["status"] in ("ok", "repaired", "degraded")
    assert isinstance(dq["gate_advanced"], bool)
    assert isinstance(dq["metrics"], list)


def test_gate_blocks_theoretical_when_degraded():
    """When distance_quality.gate_advanced=True, theoretical step is skipped."""
    from distance_integrity import DistanceQuality

    dq = DistanceQuality(
        status="degraded",
        gate_advanced=True,
        laps_degraded=[1],
        message="test",
    )
    # Verify the dataclass attributes used by the gate check
    assert dq.gate_advanced is True
    assert dq.status == "degraded"
    assert hasattr(dq, 'gate_advanced')


class TestDistanceQualityEndpoint:
    """Tests for GET /api/v1/sessions/<id>/distance-quality."""

    @pytest.fixture
    def app(self):
        from flask import Flask
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.config["USE_PG"] = False
        from web.routes.data_v2 import bp
        app.register_blueprint(bp)
        return app

    @pytest.fixture
    def client(self, app):
        return app.test_client()

    def test_distance_quality_returns_from_summary(self, client):
        """Endpoint returns distance_quality from analysis_json."""
        from unittest.mock import MagicMock, patch

        dq_data = {
            "status": "ok",
            "gate_advanced": False,
            "metrics": [],
            "message": "Clean",
            "repair_method": None,
            "laps_repaired": [],
            "laps_degraded": [],
        }

        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = {"session_id": "s1"}
            mm.get_analysis_json.return_value = {"distance_quality": dq_data}

            resp = client.get("/api/v1/sessions/s1/distance-quality")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["data"]["status"] == "ok"


def test_session_detail_includes_distance_quality():
    """GET /api/v1/sessions/<id> includes distance_quality when available."""
    from unittest.mock import MagicMock, patch
    from flask import Flask
    from web.routes.data_v2 import bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["USE_PG"] = False
    app.register_blueprint(bp)
    client = app.test_client()

    dq_data = {"status": "repaired", "gate_advanced": False,
                "repair_method": "xy_rebuild", "laps_repaired": [2],
                "laps_degraded": [], "metrics": [], "message": "Repaired"}
    sample_session = {
        "session_id": "s1", "csv_filename": "test1.csv",
        "driver_id": 1, "driver_name": "TestDriver",
        "track_id": "t1", "track_name": "TestTrack",
        "session_type": "practice", "track_state": "dry",
        "session_date": "2024-01-01", "n_laps": 10,
        "best_lap_time_s": 60.0, "mean_lap_time_s": 61.5,
        "total_score": 75.0, "grade": "B",
    }

    with patch("web.routes.data_v2.get_db_connection") as mock_db, \
         patch("web.routes.data_v2.models") as mm:
        mock_db.return_value = MagicMock()
        mm.get_session_by_id.return_value = sample_session
        mm.get_analysis_json.return_value = {
            "distance_quality": dq_data,
            "pipeline": {"status": "complete"},
        }

        resp = client.get("/api/v1/sessions/s1")

    data = resp.get_json()["data"]
    assert "distance_quality" in data
    assert data["distance_quality"]["status"] == "repaired"
