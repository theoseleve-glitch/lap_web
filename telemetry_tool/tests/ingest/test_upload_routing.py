"""Integration test: upload → profiler → handler registry → dispatch.

Verifies that `/api/v1/sessions/upload` profiles the uploaded file, picks
the right handler, and delegates.  Follows the minimal-app pattern used in
`tests/test_upload_sync.py` — avoid create_app() so CORS/Redis/tenant
middleware don't interfere with unit-scope routing assertions.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture
def app():
    """Minimal Flask app with only the sessions_v2 blueprint."""
    from flask import Flask, g

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["USE_PG"] = True

    from web.routes.sessions_v2 import bp
    app.register_blueprint(bp)

    @app.before_request
    def _inject_auth() -> None:
        g.workspace_id = 1
        g.plan_tier = "racer"  # skips session-count limit + large file size cap

    return app


@pytest.fixture
def client(app):
    return app.test_client()


def _upload(client, data: bytes, filename: str):
    return client.post(
        "/api/v1/sessions/upload",
        data={"file": (io.BytesIO(data), filename), "driver_name": "Theo"},
        content_type="multipart/form-data",
    )


def _mock_conn() -> MagicMock:
    """Mock connection that satisfies tier-limits and insert calls."""
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = {"cnt": 0}
    return conn


def _preflight_ok() -> MagicMock:
    """Stand-in for preflight.run_preflight — always passes.

    Preflight is orthogonal to routing. These tests assert only that a
    recognised-format file reaches the right handler; preflight behaviour
    is covered by its own suite.
    """
    result = MagicMock()
    result.ok = True
    result.failure = None
    return result


@patch("preflight.run_preflight", return_value=_preflight_ok())
@patch("telemetry_tool.ingest.handlers_real_life._redis_from_url")
@patch("telemetry_tool.ingest.handlers_real_life.PipelineContext")
@patch("telemetry_tool.ingest.handlers_real_life.build_pipeline_chain")
def test_rc_csv_routes_to_real_life_handler(
    mock_chain, mock_ctx, mock_redis, mock_preflight, client,
):
    """RaceChrono CSV → RealLifeHandler → build_pipeline_chain called."""
    with patch("web.routes.sessions_v2._get_conn", return_value=_mock_conn()):
        payload = (
            b'Session "x"\n'
            b'"Lap","Time","Lat","Lon","Speed (m/s)","LatAcc (G)"\n'
            b'1,0.0,43.1,5.6,12.0,0.0\n'
        )
        resp = _upload(client, payload, "sample.csv")

    assert resp.status_code == 202, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["ok"] is True
    assert body["data"]["status"] == "pending"
    assert mock_chain.called  # real-life handler ran


@patch("preflight.run_preflight", return_value=_preflight_ok())
@patch("telemetry_tool.ingest.handlers_real_life._redis_from_url")
@patch("telemetry_tool.ingest.handlers_real_life.PipelineContext")
@patch("telemetry_tool.ingest.handlers_real_life.build_pipeline_chain")
def test_ibt_routes_to_iracing_stub_and_5xx(
    mock_chain, mock_ctx, mock_redis, mock_preflight, client,
):
    """IBT file → IRacingStubHandler → NotImplementedError → 501."""
    with patch("web.routes.sessions_v2._get_conn", return_value=_mock_conn()):
        # Magic bytes only; adapter detect succeeds; stub raises NotImplementedError.
        resp = _upload(client, b"\x03\x00" + b"\x00" * 254, "sample.ibt")

    assert resp.status_code in (501, 502, 503), resp.get_data(as_text=True)
    assert not mock_chain.called


@patch("preflight.run_preflight", return_value=_preflight_ok())
@patch("telemetry_tool.ingest.handlers_real_life._redis_from_url")
@patch("telemetry_tool.ingest.handlers_real_life.PipelineContext")
@patch("telemetry_tool.ingest.handlers_real_life.build_pipeline_chain")
def test_ac_csv_routes_to_ac_stub_and_501s(
    mock_chain, mock_ctx, mock_redis, mock_preflight, client,
):
    """AC-style telemetry CSV → AC source → ACStubHandler → 501.

    Detection classifies this sample as `motec` (heuristic match on the
    `# AC Telemetry` comment + RPM/Gear columns). Both `motec` and `acc`
    route to SourceLiteral.AC via _PARSER_ROUTING, so the assertion is on
    the source-level outcome, not the specific parser name.
    """
    payload = (
        b"# AC Telemetry\n"
        b"Time,Speed,Throttle,Brake,Steer,RPM,Gear\n"
        b"0.0,12.3,0.8,0.0,-0.1,6500,3\n"
    )
    with patch("web.routes.sessions_v2._get_conn", return_value=_mock_conn()):
        resp = _upload(client, payload, "sample.ac.csv")

    assert resp.status_code == 501, resp.get_data(as_text=True)
    assert not mock_chain.called


@patch("preflight.run_preflight", return_value=_preflight_ok())
@patch("telemetry_tool.ingest.handlers_real_life._redis_from_url")
@patch("telemetry_tool.ingest.handlers_real_life.PipelineContext")
@patch("telemetry_tool.ingest.handlers_real_life.build_pipeline_chain")
def test_three_sample_uploads_distinct_routes(
    mock_chain, mock_ctx, mock_redis, mock_preflight, client,
):
    """Acceptance-criteria test: each sample routes to its correct handler."""
    rc_payload = (
        b'Session "x"\n"Lap","Time","Lat","Lon","Speed (m/s)","LatAcc (G)"\n'
        b'1,0.0,43.1,5.6,12.0,0.0\n'
    )
    ibt_payload = b"\x03\x00" + b"\x00" * 254
    ac_payload = (
        b"# AC Telemetry\nTime,Speed,Throttle,Brake,Steer,RPM,Gear\n"
        b"0.0,12.3,0.8,0.0,-0.1,6500,3\n"
    )
    with patch("web.routes.sessions_v2._get_conn", return_value=_mock_conn()):
        r1 = _upload(client, rc_payload, "x.csv")
        r2 = _upload(client, ibt_payload, "x.ibt")
        r3 = _upload(client, ac_payload, "x.ac.csv")

    assert r1.status_code == 202, r1.get_data(as_text=True)   # real-life OK
    assert r2.status_code == 501, r2.get_data(as_text=True)   # iRacing stub
    assert r3.status_code == 501, r3.get_data(as_text=True)   # AC stub
    assert mock_chain.call_count == 1  # only the real-life upload dispatches
