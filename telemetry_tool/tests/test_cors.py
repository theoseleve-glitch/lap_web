"""Tests for CORS configuration."""
import pytest
from flask import Flask


def test_cors_headers_present():
    """CORS headers are returned for configured origins."""
    import sys
    from pathlib import Path
    _PROJECT_ROOT = Path(__file__).resolve().parent.parent
    if str(_PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(_PROJECT_ROOT))

    from web.app import create_app
    from web.config import Config

    cfg = Config()
    cfg.CORS_ALLOWED_ORIGINS = "http://localhost:3000"
    app = create_app(cfg)
    client = app.test_client()

    resp = client.get("/api/v1/sessions/browse", headers={
        "Origin": "http://localhost:3000"
    })
    # CORS headers should be present
    assert "Access-Control-Allow-Origin" in resp.headers


def test_cors_rejects_unknown_origin():
    """Unknown origins don't get CORS headers."""
    import sys
    from pathlib import Path
    _PROJECT_ROOT = Path(__file__).resolve().parent.parent
    if str(_PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(_PROJECT_ROOT))

    from web.app import create_app
    from web.config import Config

    cfg = Config()
    cfg.CORS_ALLOWED_ORIGINS = "http://localhost:3000"
    app = create_app(cfg)
    client = app.test_client()

    resp = client.get("/api/v1/sessions/browse", headers={
        "Origin": "http://evil.com"
    })
    # Should NOT have the evil origin in CORS header
    cors_header = resp.headers.get("Access-Control-Allow-Origin", "")
    assert "evil.com" not in cors_header


def _make_client():
    """Helper: create a test client with CORS configured for localhost:3000."""
    import sys
    from pathlib import Path
    _PROJECT_ROOT = Path(__file__).resolve().parent.parent
    if str(_PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(_PROJECT_ROOT))

    from web.app import create_app
    from web.config import Config

    cfg = Config()
    cfg.CORS_ALLOWED_ORIGINS = "http://localhost:3000"
    app = create_app(cfg)
    return app.test_client()


def test_cors_allows_custom_headers():
    """CORS preflight must allow X-Workspace-Id, Idempotency-Key, X-CSRF-Token."""
    client = _make_client()
    resp = client.options("/healthz", headers={
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "Authorization,X-Workspace-Id,Idempotency-Key,X-CSRF-Token"
    })
    assert resp.status_code in (200, 204)
    allowed = resp.headers.get("Access-Control-Allow-Headers", "")
    for h in ["X-Workspace-Id", "Idempotency-Key", "X-CSRF-Token"]:
        assert h.lower() in allowed.lower(), f"Missing {h} in CORS Allow-Headers"


def test_cors_exposes_response_headers():
    """Frontend JS must be able to read X-Request-Id and Retry-After."""
    client = _make_client()
    resp = client.get("/healthz", headers={"Origin": "http://localhost:3000"})
    exposed = resp.headers.get("Access-Control-Expose-Headers", "")
    assert "x-request-id" in exposed.lower()
