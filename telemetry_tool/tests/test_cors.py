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


@pytest.mark.parametrize("endpoint", [
    "/api/sessions/browse",
    "/api/files/upload",
])
def test_cors_preflight_options_key_endpoints(endpoint):
    """Preflight requests return 2xx and include allowed origin header."""
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

    resp = client.options(endpoint, headers={
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "POST",
    })

    assert 200 <= resp.status_code < 300
    assert resp.headers.get("Access-Control-Allow-Origin") == "http://localhost:3000"
