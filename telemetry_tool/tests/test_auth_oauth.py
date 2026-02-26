"""Tests for OAuth integration (Tasks 13-15).

These tests do NOT require PostgreSQL or real OAuth providers.  They verify
the configuration plumbing, middleware allowlisting, and the
``get_or_create_oauth_user`` function using mocks.

All PG-dependent tests skip gracefully when ``TELEMETRY_PG_URL`` is not set.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so we can import auth/web modules.
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# OAuth config tests (no PG required)
# ---------------------------------------------------------------------------

class TestOAuthConfig:
    """Verify OAuth settings are added to Config and propagated to app.config."""

    def test_config_has_oauth_attrs(self):
        from web.config import Config
        cfg = Config()
        assert hasattr(cfg, "GOOGLE_CLIENT_ID")
        assert hasattr(cfg, "GOOGLE_CLIENT_SECRET")
        assert hasattr(cfg, "GITHUB_CLIENT_ID")
        assert hasattr(cfg, "GITHUB_CLIENT_SECRET")
        assert hasattr(cfg, "OAUTH_REDIRECT_BASE")

    def test_config_defaults_empty(self):
        from web.config import Config
        cfg = Config()
        assert cfg.GOOGLE_CLIENT_ID == ""
        assert cfg.GOOGLE_CLIENT_SECRET == ""
        assert cfg.GITHUB_CLIENT_ID == ""
        assert cfg.GITHUB_CLIENT_SECRET == ""
        assert cfg.OAUTH_REDIRECT_BASE == "http://localhost:5000"

    def test_config_reads_env(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "goog-id")
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "goog-secret")
        monkeypatch.setenv("GITHUB_CLIENT_ID", "gh-id")
        monkeypatch.setenv("GITHUB_CLIENT_SECRET", "gh-secret")
        monkeypatch.setenv("OAUTH_REDIRECT_BASE", "https://example.com")

        # Re-import to pick up monkeypatched env
        import importlib
        import web.config
        importlib.reload(web.config)
        cfg = web.config.Config()

        assert cfg.GOOGLE_CLIENT_ID == "goog-id"
        assert cfg.GOOGLE_CLIENT_SECRET == "goog-secret"
        assert cfg.GITHUB_CLIENT_ID == "gh-id"
        assert cfg.GITHUB_CLIENT_SECRET == "gh-secret"
        assert cfg.OAUTH_REDIRECT_BASE == "https://example.com"

        # Reload again to restore defaults for other tests
        for key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
                     "GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET",
                     "OAUTH_REDIRECT_BASE"):
            monkeypatch.delenv(key, raising=False)
        importlib.reload(web.config)


class TestInitOAuth:
    """Verify ``init_oauth`` registers providers based on config."""

    def test_no_providers_when_no_config(self):
        """init_oauth should not register anything when client IDs are empty."""
        from auth.oauth import init_oauth, oauth

        app = MagicMock()
        app.config = {
            "GOOGLE_CLIENT_ID": "",
            "GOOGLE_CLIENT_SECRET": "",
            "GITHUB_CLIENT_ID": "",
            "GITHUB_CLIENT_SECRET": "",
        }

        with patch.object(oauth, "init_app") as mock_init, \
             patch.object(oauth, "register") as mock_register:
            init_oauth(app)
            mock_init.assert_called_once_with(app)
            mock_register.assert_not_called()

    def test_google_registered_when_configured(self):
        """init_oauth should register Google when GOOGLE_CLIENT_ID is set."""
        from auth.oauth import init_oauth, oauth

        app = MagicMock()
        app.config = {
            "GOOGLE_CLIENT_ID": "goog-123",
            "GOOGLE_CLIENT_SECRET": "goog-secret",
            "GITHUB_CLIENT_ID": "",
            "GITHUB_CLIENT_SECRET": "",
        }

        with patch.object(oauth, "init_app"), \
             patch.object(oauth, "register") as mock_register:
            init_oauth(app)
            mock_register.assert_called_once()
            call_kwargs = mock_register.call_args[1]
            assert call_kwargs["name"] == "google"
            assert call_kwargs["client_id"] == "goog-123"

    def test_github_registered_when_configured(self):
        """init_oauth should register GitHub when GITHUB_CLIENT_ID is set."""
        from auth.oauth import init_oauth, oauth

        app = MagicMock()
        app.config = {
            "GOOGLE_CLIENT_ID": "",
            "GOOGLE_CLIENT_SECRET": "",
            "GITHUB_CLIENT_ID": "gh-456",
            "GITHUB_CLIENT_SECRET": "gh-secret",
        }

        with patch.object(oauth, "init_app"), \
             patch.object(oauth, "register") as mock_register:
            init_oauth(app)
            mock_register.assert_called_once()
            call_kwargs = mock_register.call_args[1]
            assert call_kwargs["name"] == "github"
            assert call_kwargs["client_id"] == "gh-456"

    def test_both_providers_registered(self):
        """init_oauth should register both providers when both are configured."""
        from auth.oauth import init_oauth, oauth

        app = MagicMock()
        app.config = {
            "GOOGLE_CLIENT_ID": "goog-123",
            "GOOGLE_CLIENT_SECRET": "goog-secret",
            "GITHUB_CLIENT_ID": "gh-456",
            "GITHUB_CLIENT_SECRET": "gh-secret",
        }

        with patch.object(oauth, "init_app"), \
             patch.object(oauth, "register") as mock_register:
            init_oauth(app)
            assert mock_register.call_count == 2
            names = [c[1]["name"] for c in mock_register.call_args_list]
            assert "google" in names
            assert "github" in names


# ---------------------------------------------------------------------------
# Middleware allowlist tests (no PG required)
# ---------------------------------------------------------------------------

class TestMiddlewareAllowlist:
    """Verify OAuth and verify-email paths are in the middleware allowlist."""

    def test_oauth_paths_allowed(self):
        """The auth middleware should skip /auth/oauth/* paths."""
        from web.middleware.auth import auth_middleware

        # The middleware reads request.path from Flask's request proxy.
        # We just verify the source code contains the correct allowlist.
        import inspect
        source = inspect.getsource(auth_middleware)
        assert "/auth/verify-email" in source
        assert "/auth/oauth/" in source

    def test_verify_email_in_public_paths(self):
        """verify-email should be in the explicit allowlist set."""
        import inspect
        from web.middleware.auth import auth_middleware
        source = inspect.getsource(auth_middleware)
        assert "verify-email" in source


# ---------------------------------------------------------------------------
# get_or_create_oauth_user tests (mocked DB, no PG required)
# ---------------------------------------------------------------------------

class TestGetOrCreateOAuthUser:
    """Test get_or_create_oauth_user with a mocked DB connection."""

    def _make_mock_conn(self):
        """Create a mock connection that simulates cursor behavior."""
        conn = MagicMock()

        # Track execute calls and return appropriate cursors
        cursors = []

        def make_cursor(*args, **kwargs):
            cur = MagicMock()
            cur.fetchone.return_value = None  # default: no results
            cursors.append(cur)
            return cur

        conn.execute.side_effect = make_cursor
        conn._cursors = cursors
        return conn

    def test_creates_new_user_and_connection(self):
        """When no existing user or OAuth connection, creates both."""
        from auth.oauth import get_or_create_oauth_user

        conn = self._make_mock_conn()

        # Set up cursor returns:
        # 1st call (oauth_connections lookup) -> None
        # 2nd call (users email lookup) -> None
        # 3rd call (INSERT users) -> returns {"id": 42}
        # 4th call (INSERT oauth_connections) -> ok
        # 5th call (INSERT refresh_tokens) -> ok
        # 6th call (SELECT user) -> returns user dict
        call_count = [0]

        def execute_side_effect(sql, params=None):
            cur = MagicMock()
            call_count[0] += 1
            idx = call_count[0]

            if idx == 1:  # oauth_connections lookup
                cur.fetchone.return_value = None
            elif idx == 2:  # users email lookup
                cur.fetchone.return_value = None
            elif idx == 3:  # INSERT users RETURNING id
                cur.fetchone.return_value = {"id": 42}
            elif idx == 4:  # INSERT oauth_connections
                cur.fetchone.return_value = None
            elif idx == 5:  # INSERT refresh_tokens
                cur.fetchone.return_value = None
            elif idx == 6:  # SELECT user
                cur.fetchone.return_value = {
                    "id": 42,
                    "email": "test@example.com",
                    "display_name": "Test User",
                }
            return cur

        conn.execute.side_effect = execute_side_effect

        profile = {
            "id": "oauth-123",
            "email": "test@example.com",
            "name": "Test User",
        }

        result = get_or_create_oauth_user(conn, "google", profile, "test-secret")

        assert result["user"]["id"] == 42
        assert result["user"]["email"] == "test@example.com"
        assert "access_token" in result
        assert "refresh_token" in result
        conn.commit.assert_called()

    def test_links_existing_user(self):
        """When user email already exists, links OAuth connection to existing user."""
        from auth.oauth import get_or_create_oauth_user

        conn = self._make_mock_conn()
        call_count = [0]

        def execute_side_effect(sql, params=None):
            cur = MagicMock()
            call_count[0] += 1
            idx = call_count[0]

            if idx == 1:  # oauth_connections lookup
                cur.fetchone.return_value = None
            elif idx == 2:  # users email lookup -> found!
                cur.fetchone.return_value = {"id": 99}
            elif idx == 3:  # INSERT oauth_connections
                cur.fetchone.return_value = None
            elif idx == 4:  # INSERT refresh_tokens
                cur.fetchone.return_value = None
            elif idx == 5:  # SELECT user
                cur.fetchone.return_value = {
                    "id": 99,
                    "email": "existing@example.com",
                    "display_name": "Existing",
                }
            return cur

        conn.execute.side_effect = execute_side_effect

        profile = {
            "id": "oauth-456",
            "email": "existing@example.com",
            "name": "Existing",
        }

        result = get_or_create_oauth_user(conn, "github", profile, "test-secret")

        assert result["user"]["id"] == 99

    def test_returns_existing_oauth_user(self):
        """When OAuth connection already exists, returns the linked user."""
        from auth.oauth import get_or_create_oauth_user

        conn = self._make_mock_conn()
        call_count = [0]

        def execute_side_effect(sql, params=None):
            cur = MagicMock()
            call_count[0] += 1
            idx = call_count[0]

            if idx == 1:  # oauth_connections lookup -> found!
                cur.fetchone.return_value = {"user_id": 77}
            elif idx == 2:  # INSERT refresh_tokens
                cur.fetchone.return_value = None
            elif idx == 3:  # SELECT user
                cur.fetchone.return_value = {
                    "id": 77,
                    "email": "returning@example.com",
                    "display_name": "Returning",
                }
            return cur

        conn.execute.side_effect = execute_side_effect

        profile = {
            "id": "oauth-789",
            "email": "returning@example.com",
            "name": "Returning",
        }

        result = get_or_create_oauth_user(conn, "google", profile, "test-secret")

        assert result["user"]["id"] == 77
        assert result["user"]["email"] == "returning@example.com"


# ---------------------------------------------------------------------------
# Migration file structure test (no PG required)
# ---------------------------------------------------------------------------

class TestMigrationFile:
    """Verify the 003 migration file exists and has correct structure."""

    def test_migration_003_exists(self):
        migration_path = (
            Path(__file__).resolve().parent.parent
            / "alembic" / "versions" / "003_oauth_tables.py"
        )
        assert migration_path.exists(), f"Migration file not found: {migration_path}"

    def test_migration_003_revision_chain(self):
        """003 should chain from 002."""
        import importlib.util
        migration_path = (
            Path(__file__).resolve().parent.parent
            / "alembic" / "versions" / "003_oauth_tables.py"
        )
        spec = importlib.util.spec_from_file_location("m003", migration_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.revision == "003"
        assert mod.down_revision == "002"

    def test_migration_003_has_upgrade_downgrade(self):
        """003 must have upgrade() and downgrade() functions."""
        import importlib.util
        migration_path = (
            Path(__file__).resolve().parent.parent
            / "alembic" / "versions" / "003_oauth_tables.py"
        )
        spec = importlib.util.spec_from_file_location("m003", migration_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert callable(getattr(mod, "upgrade", None))
        assert callable(getattr(mod, "downgrade", None))
