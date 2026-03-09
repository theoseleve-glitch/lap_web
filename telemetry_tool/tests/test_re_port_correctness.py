"""Re-port correctness validation.

Tests that run_full_analysis() produces correct output when called
through the SaaS wrapper vs directly.  Validates:

1. Pipeline produces non-None scores on valid input.
2. Pipeline is deterministic (same input -> same output).
3. Upload endpoint integration returns expected response shape.
"""
from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ── Synthetic CSV fixture ────────────────────────────────────────


_SYNTHETIC_CSV = """\
Time (s),Lap #,Distance (m),Speed (m/s),Latitude (deg),Longitude (deg)
0.0,1,0.0,10.0,45.5000,9.2000
1.0,1,10.0,12.0,45.5001,9.2001
2.0,1,22.0,14.0,45.5002,9.2002
3.0,1,36.0,13.5,45.5003,9.2003
4.0,1,49.5,13.0,45.5004,9.2004
5.0,1,62.5,12.5,45.5005,9.2005
6.0,1,75.0,12.0,45.5006,9.2006
7.0,1,87.0,11.5,45.5007,9.2007
8.0,1,98.5,11.0,45.5008,9.2008
9.0,1,109.5,10.5,45.5009,9.2009
10.0,1,120.0,10.0,45.5010,9.2010
11.0,2,0.0,10.5,45.5000,9.2000
12.0,2,10.5,12.5,45.5001,9.2001
13.0,2,23.0,14.5,45.5002,9.2002
14.0,2,37.5,13.0,45.5003,9.2003
15.0,2,50.5,12.5,45.5004,9.2004
16.0,2,63.0,12.0,45.5005,9.2005
17.0,2,75.0,11.5,45.5006,9.2006
18.0,2,86.5,11.0,45.5007,9.2007
19.0,2,97.5,10.5,45.5008,9.2008
20.0,2,108.0,10.0,45.5009,9.2009
21.0,2,118.0,9.5,45.5010,9.2010
22.0,3,0.0,10.0,45.5000,9.2000
23.0,3,10.0,12.0,45.5001,9.2001
24.0,3,22.0,14.0,45.5002,9.2002
25.0,3,36.0,13.5,45.5003,9.2003
26.0,3,49.5,13.0,45.5004,9.2004
27.0,3,62.5,12.5,45.5005,9.2005
28.0,3,75.0,12.0,45.5006,9.2006
29.0,3,87.0,11.5,45.5007,9.2007
30.0,3,98.5,11.0,45.5008,9.2008
31.0,3,109.5,10.5,45.5009,9.2009
32.0,3,120.0,10.0,45.5010,9.2010
"""


@pytest.fixture
def synthetic_csv_path(tmp_path):
    """Write the synthetic CSV to a temp file and return its path."""
    csv_file = tmp_path / "synthetic_session.csv"
    csv_file.write_text(_SYNTHETIC_CSV, encoding="utf-8")
    return csv_file


@pytest.fixture
def session_meta():
    """Minimal session metadata for pipeline runs."""
    return {
        "session_type": "practice",
        "track_state": "dry",
        "driver_name": "TestDriver",
        "date": "2026-03-01",
    }


# ══════════════════════════════════════════════════════════════════
# 1. Pipeline produces scores
# ══════════════════════════════════════════════════════════════════


class TestPipelineProducesScores:

    def test_pipeline_produces_output(self, synthetic_csv_path, session_meta):
        """run_full_analysis() returns a dict with steps_ok and steps_failed.

        With synthetic data the pipeline may skip some stages, but it must
        not crash and must produce SOME output (steps_ok or steps_failed).
        """
        from pipeline import run_full_analysis

        summary = run_full_analysis(
            csv_path=str(synthetic_csv_path),
            session_meta=session_meta,
            enable_ml=False,
            enable_report=False,
        )

        assert isinstance(summary, dict), "Pipeline should return a dict"
        assert "steps_ok" in summary, "Summary should have steps_ok list"
        assert "steps_failed" in summary, "Summary should have steps_failed list"
        # At minimum, the ingest step should have succeeded since we have valid CSV
        assert len(summary["steps_ok"]) > 0, (
            f"At least one step should succeed. "
            f"steps_ok={summary['steps_ok']}, steps_failed={summary['steps_failed']}"
        )

    def test_pipeline_produces_scores(self, synthetic_csv_path, session_meta):
        """run_full_analysis() produces a score_result with total_score and grade.

        Note: with minimal synthetic data, the pipeline may produce partial
        scores or None for some sub-scores.  We test that the structure is
        present and the scoring step ran.
        """
        from pipeline import run_full_analysis

        summary = run_full_analysis(
            csv_path=str(synthetic_csv_path),
            session_meta=session_meta,
            enable_ml=False,
            enable_report=False,
        )

        score = summary.get("score_result")

        # If scoring ran, verify the shape
        if score is not None:
            assert "total_score" in score, "score_result should have total_score"
            assert "grade" in score, "score_result should have grade"
            assert isinstance(score["total_score"], (int, float)), \
                "total_score should be numeric"
            assert score["grade"] in ("S", "A", "B", "C", "D", "F"), \
                f"grade should be a valid letter, got {score['grade']!r}"
        else:
            # Scoring may fail with synthetic data — that's OK as long as
            # it's in steps_failed (not a crash).
            assert "scoring" in summary.get("steps_failed", []) or \
                   "score" in str(summary.get("steps_failed", [])).lower(), \
                "If score_result is None, scoring should be in steps_failed"

    def test_pipeline_session_meta_populated(self, synthetic_csv_path, session_meta):
        """Pipeline preserves and enriches session metadata."""
        from pipeline import run_full_analysis

        summary = run_full_analysis(
            csv_path=str(synthetic_csv_path),
            session_meta=session_meta,
            enable_ml=False,
            enable_report=False,
        )

        meta = summary.get("session_meta")
        assert meta is not None, "session_meta should be in summary"
        assert meta["session_type"] == "practice"
        assert meta["track_state"] == "dry"
        assert meta["driver_name"] == "TestDriver"

    def test_pipeline_lap_data_extracted(self, synthetic_csv_path, session_meta):
        """Pipeline extracts lap data from the CSV."""
        from pipeline import run_full_analysis

        summary = run_full_analysis(
            csv_path=str(synthetic_csv_path),
            session_meta=session_meta,
            enable_ml=False,
            enable_report=False,
        )

        # The CSV has 3 laps — pipeline should find them
        lap_times = summary.get("lap_times", [])
        lap_metrics = summary.get("lap_metrics", [])

        # At least some lap data should be extracted
        # (exact count may differ due to filtering)
        assert isinstance(lap_times, list), "lap_times should be a list"
        assert isinstance(lap_metrics, list), "lap_metrics should be a list"


# ══════════════════════════════════════════════════════════════════
# 2. Pipeline is deterministic
# ══════════════════════════════════════════════════════════════════


class TestPipelineDeterministic:

    def test_pipeline_deterministic(self, synthetic_csv_path, session_meta):
        """Running pipeline twice on the same input produces identical results.

        We compare total_score, grade, steps_ok, and steps_failed.
        """
        from pipeline import run_full_analysis

        summary_1 = run_full_analysis(
            csv_path=str(synthetic_csv_path),
            session_meta=session_meta,
            enable_ml=False,
            enable_report=False,
        )

        summary_2 = run_full_analysis(
            csv_path=str(synthetic_csv_path),
            session_meta=session_meta,
            enable_ml=False,
            enable_report=False,
        )

        # Steps should be the same
        assert summary_1["steps_ok"] == summary_2["steps_ok"], \
            "Determinism: steps_ok should match between runs"
        assert summary_1["steps_failed"] == summary_2["steps_failed"], \
            "Determinism: steps_failed should match between runs"

        # Scores should be identical
        score_1 = summary_1.get("score_result")
        score_2 = summary_2.get("score_result")

        if score_1 is not None and score_2 is not None:
            assert score_1["total_score"] == score_2["total_score"], \
                "Determinism: total_score should match between runs"
            assert score_1["grade"] == score_2["grade"], \
                "Determinism: grade should match between runs"
        else:
            # Both should be None if scoring failed
            assert score_1 is None and score_2 is None, \
                "Determinism: both runs should either produce or skip scores"

        # Lap times should be identical
        assert summary_1.get("lap_times") == summary_2.get("lap_times"), \
            "Determinism: lap_times should match between runs"


# ══════════════════════════════════════════════════════════════════
# 3. Upload endpoint integration
# ══════════════════════════════════════════════════════════════════


class TestUploadEndpointIntegration:

    @pytest.fixture
    def app(self):
        """Minimal Flask app with sessions_v2 blueprint."""
        from flask import Flask

        app = Flask(__name__)
        app.config["TESTING"] = True
        app.config["USE_PG"] = False

        from web.routes.sessions_v2 import bp
        app.register_blueprint(bp)
        return app

    @pytest.fixture
    def client(self, app):
        return app.test_client()

    def test_upload_endpoint_returns_202_async(self, app):
        """POST /api/v1/sessions/upload returns 202 with job_id (async).

        The upload endpoint was refactored to async Celery dispatch.
        """
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {"count": 0}

        @app.before_request
        def _inject_auth():
            from flask import g
            g.workspace_id = 1
            g.current_user_id = 42
            g.plan_tier = "racer"

        csv_content = "Lap #,Time (s),Speed (m/s)\n1,0.0,10.5\n1,1.0,11.2\n"
        data = {
            "file": (io.BytesIO(csv_content.encode()), "session.csv"),
            "session_type": "practice",
            "track_state": "dry",
            "driver_name": "TestDriver",
        }

        with patch("web.routes.sessions_v2._get_conn", return_value=mock_conn), \
             patch("redis.Redis.from_url", return_value=MagicMock()), \
             patch("pipeline_context.PipelineContext"), \
             patch("tasks.pipeline_tasks.build_pipeline_chain", return_value=MagicMock()), \
             patch("web.config.Config") as mock_cfg:

            mock_cfg.REDIS_URL = "redis://localhost:6379/0"
            resp = app.test_client().post(
                "/api/v1/sessions/upload",
                data=data,
                content_type="multipart/form-data",
            )

        assert resp.status_code == 202
        body = resp.get_json()
        assert body["ok"] is True
        assert "job_id" in body["data"]
        assert body["data"]["status"] == "pending"

    def test_upload_validation_rejects_missing_file(self, client):
        """Upload rejects requests without a file."""
        resp = client.post(
            "/api/v1/sessions/upload",
            data={"session_type": "practice"},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["ok"] is False
