"""Tests for CORS middleware — origin allowlist, preflight, error responses."""
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from web.config import Config


def _make_app(origins: str = "https://lap-coach.racing"):
    """Create a test app with the given CORS allowlist."""
    cfg = Config()
    cfg.CORS_ALLOWED_ORIGINS = origins
    from web.app import create_app
    return create_app(cfg)


def _make_client(origins: str = "https://lap-coach.racing"):
    return _make_app(origins).test_client()


# ── Allowed origin ──────────────────────────────────────────


class TestAllowedOrigin:
    def test_acao_present_for_allowed_origin(self):
        client = _make_client("https://lap-coach.racing")
        resp = client.get("/healthz", headers={"Origin": "https://lap-coach.racing"})
        assert resp.headers.get("Access-Control-Allow-Origin") == "https://lap-coach.racing"

    def test_credentials_header_present(self):
        client = _make_client("https://lap-coach.racing")
        resp = client.get("/healthz", headers={"Origin": "https://lap-coach.racing"})
        assert resp.headers.get("Access-Control-Allow-Credentials") == "true"

    def test_vary_origin_present(self):
        client = _make_client("https://lap-coach.racing")
        resp = client.get("/healthz", headers={"Origin": "https://lap-coach.racing"})
        assert "Origin" in resp.headers.get("Vary", "")

    def test_expose_headers(self):
        client = _make_client("https://lap-coach.racing")
        resp = client.get("/healthz", headers={"Origin": "https://lap-coach.racing"})
        exposed = resp.headers.get("Access-Control-Expose-Headers", "")
        assert "X-Request-Id" in exposed
        assert "Retry-After" in exposed

    def test_multiple_allowed_origins(self):
        client = _make_client("https://lap-coach.racing,https://www.lap-coach.racing")
        for origin in ["https://lap-coach.racing", "https://www.lap-coach.racing"]:
            resp = client.get("/healthz", headers={"Origin": origin})
            assert resp.headers.get("Access-Control-Allow-Origin") == origin


# ── Blocked origin ──────────────────────────────────────────


class TestBlockedOrigin:
    def test_no_acao_for_unknown_origin(self):
        client = _make_client("https://lap-coach.racing")
        resp = client.get("/healthz", headers={"Origin": "http://evil.com"})
        assert "Access-Control-Allow-Origin" not in resp.headers

    def test_no_acao_for_localhost(self):
        client = _make_client("https://lap-coach.racing")
        resp = client.get("/healthz", headers={"Origin": "http://localhost:3000"})
        assert "Access-Control-Allow-Origin" not in resp.headers

    def test_vary_still_present_for_blocked_origin(self):
        client = _make_client("https://lap-coach.racing")
        resp = client.get("/healthz", headers={"Origin": "http://evil.com"})
        assert "Origin" in resp.headers.get("Vary", "")

    def test_no_acao_without_origin_header(self):
        client = _make_client("https://lap-coach.racing")
        resp = client.get("/healthz")
        assert "Access-Control-Allow-Origin" not in resp.headers


# ── Preflight (OPTIONS) ────────────────────────────────────


class TestPreflight:
    def test_preflight_returns_200(self):
        client = _make_client("https://lap-coach.racing")
        resp = client.options("/api/v1/sessions/browse", headers={
            "Origin": "https://lap-coach.racing",
            "Access-Control-Request-Method": "POST",
        })
        assert resp.status_code == 200

    def test_preflight_has_allow_methods(self):
        client = _make_client("https://lap-coach.racing")
        resp = client.options("/api/v1/sessions/browse", headers={
            "Origin": "https://lap-coach.racing",
            "Access-Control-Request-Method": "POST",
        })
        methods = resp.headers.get("Access-Control-Allow-Methods", "")
        for m in ["GET", "POST", "PUT", "DELETE", "OPTIONS"]:
            assert m in methods

    def test_preflight_has_allow_headers(self):
        client = _make_client("https://lap-coach.racing")
        resp = client.options("/api/v1/sessions/browse", headers={
            "Origin": "https://lap-coach.racing",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization,X-Workspace-Id",
        })
        allowed = resp.headers.get("Access-Control-Allow-Headers", "")
        for h in ["Authorization", "X-Workspace-Id", "Idempotency-Key", "X-CSRF-Token"]:
            assert h in allowed

    def test_preflight_has_max_age(self):
        client = _make_client("https://lap-coach.racing")
        resp = client.options("/healthz", headers={
            "Origin": "https://lap-coach.racing",
            "Access-Control-Request-Method": "GET",
        })
        assert resp.headers.get("Access-Control-Max-Age") == "86400"

    def test_preflight_blocked_origin_no_acao(self):
        client = _make_client("https://lap-coach.racing")
        resp = client.options("/healthz", headers={
            "Origin": "http://evil.com",
            "Access-Control-Request-Method": "GET",
        })
        assert "Access-Control-Allow-Origin" not in resp.headers


# ── Error responses ─────────────────────────────────────────


class TestErrorResponseCORS:
    def test_404_has_cors_headers(self):
        client = _make_client("https://lap-coach.racing")
        resp = client.get("/api/v1/nonexistent-route-xyz", headers={
            "Origin": "https://lap-coach.racing",
        })
        assert resp.status_code == 404
        assert resp.headers.get("Access-Control-Allow-Origin") == "https://lap-coach.racing"

    def test_405_has_cors_headers(self):
        client = _make_client("https://lap-coach.racing")
        resp = client.delete("/healthz", headers={
            "Origin": "https://lap-coach.racing",
        })
        # healthz only supports GET — should be 405
        assert resp.headers.get("Access-Control-Allow-Origin") == "https://lap-coach.racing"


# ── Production guard ────────────────────────────────────────


class TestProdGuard:
    def test_prod_rejects_localhost_origin(self, monkeypatch):
        monkeypatch.setenv("AUTH_REQUIRED", "1")
        cfg = Config()
        cfg.ENV = "production"
        cfg.CORS_ALLOWED_ORIGINS = "https://lap-coach.racing,http://localhost:3000"
        cfg.AUTH_REQUIRED = True
        cfg.JWT_SECRET = "a" * 64
        cfg.SECRET_KEY = "b" * 64
        cfg.USE_PG = False
        with pytest.raises(ValueError, match="localhost"):
            cfg.validate()

    def test_prod_rejects_127_origin(self, monkeypatch):
        monkeypatch.setenv("AUTH_REQUIRED", "1")
        cfg = Config()
        cfg.ENV = "production"
        cfg.CORS_ALLOWED_ORIGINS = "https://lap-coach.racing,http://127.0.0.1:5000"
        cfg.AUTH_REQUIRED = True
        cfg.JWT_SECRET = "a" * 64
        cfg.SECRET_KEY = "b" * 64
        cfg.USE_PG = False
        with pytest.raises(ValueError, match="127.0.0.1"):
            cfg.validate()

    def test_prod_allows_real_origins(self, monkeypatch):
        monkeypatch.setenv("AUTH_REQUIRED", "1")
        cfg = Config()
        cfg.ENV = "production"
        cfg.CORS_ALLOWED_ORIGINS = "https://lap-coach.racing,https://www.lap-coach.racing"
        cfg.AUTH_REQUIRED = True
        cfg.JWT_SECRET = "a" * 64
        cfg.SECRET_KEY = "b" * 64
        cfg.USE_PG = False
        # Should not raise for CORS (PG validation will fail but CORS part passes)
        try:
            cfg.validate()
        except ValueError as e:
            assert "localhost" not in str(e) and "127.0.0.1" not in str(e)
