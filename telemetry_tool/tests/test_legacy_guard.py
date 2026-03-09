"""Tests for legacy route blocking middleware."""
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture
def app_with_guard():
    """Flask app with legacy guard active (AUTH_REQUIRED=True)."""
    from web.config import Config
    cfg = Config()
    cfg.ENV = "development"  # Guard against module-reload pollution from other tests
    cfg.USE_PG = False
    cfg.AUTH_REQUIRED = True
    cfg.JWT_SECRET = "a" * 64  # 64-char strong secret for validation
    cfg.SECRET_KEY = "b" * 64
    from web.app import create_app
    app = create_app(cfg)
    # Since USE_PG=False, the guard isn't auto-registered. Register manually.
    from web.middleware.legacy_guard import init_legacy_guard
    init_legacy_guard(app)
    return app


@pytest.fixture
def app_without_guard():
    """Flask app without legacy guard (AUTH_REQUIRED=False)."""
    from web.config import Config
    cfg = Config()
    cfg.USE_PG = False
    cfg.AUTH_REQUIRED = False
    from web.app import create_app
    return create_app(cfg)


class TestLegacyGuard:
    def test_blocks_sessions_route(self, app_with_guard):
        """Legacy /sessions returns 404 when guard active."""
        with app_with_guard.test_client() as client:
            resp = client.get("/sessions")
            assert resp.status_code == 404

    def test_blocks_drivers_route(self, app_with_guard):
        """Legacy /drivers returns 404 when guard active."""
        with app_with_guard.test_client() as client:
            resp = client.get("/drivers/1")
            assert resp.status_code == 404

    def test_blocks_compare_route(self, app_with_guard):
        """Legacy /compare returns 404 when guard active."""
        with app_with_guard.test_client() as client:
            resp = client.get("/compare/sessions")
            assert resp.status_code == 404

    def test_allows_healthz(self, app_with_guard):
        """Health check is NOT blocked."""
        with app_with_guard.test_client() as client:
            resp = client.get("/healthz")
            assert resp.status_code != 404

    def test_allows_static_prefix(self):
        """Verify /static is not in legacy prefixes."""
        from web.middleware.legacy_guard import _LEGACY_PREFIXES
        assert not any("/static".startswith(p) for p in _LEGACY_PREFIXES)

    def test_allows_api_v1_prefix(self):
        """Verify /api/v1 is not in legacy prefixes."""
        from web.middleware.legacy_guard import _LEGACY_PREFIXES
        assert not any("/api/v1".startswith(p) for p in _LEGACY_PREFIXES)
