"""Tests for device token authentication middleware."""
import hashlib
import re
from datetime import datetime, timezone

import flask
import pytest


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _pg_to_sqlite(sql):
    """Convert %(name)s placeholders to :name for SQLite."""
    return re.sub(r"%\((\w+)\)s", r":\1", sql)


class _SqliteCompat:
    """Wraps a SQLite conn so PG-style %(name)s queries work."""
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        return self._conn.execute(_pg_to_sqlite(sql), params or {})


# ---------------------------------------------------------------------------
# Unit tests for _extract_device_token (need Flask request context)
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    """Minimal Flask app for request-context tests."""
    _app = flask.Flask(__name__)
    _app.config["TESTING"] = True
    return _app


def test_extract_device_token_valid_header(app):
    from web.middleware.device_auth import _extract_device_token
    with app.test_request_context(headers={"Authorization": "DeviceToken abc123def456"}):
        assert _extract_device_token() == "abc123def456"


def test_extract_device_token_missing(app):
    from web.middleware.device_auth import _extract_device_token
    with app.test_request_context():
        assert _extract_device_token() is None


def test_extract_device_token_wrong_scheme(app):
    from web.middleware.device_auth import _extract_device_token
    with app.test_request_context(headers={"Authorization": "Bearer jwt_token_here"}):
        assert _extract_device_token() is None


# ---------------------------------------------------------------------------
# DB tests for validate_device_token (use SQLite test_db)
# ---------------------------------------------------------------------------

@pytest.fixture
def device_db(test_db):
    """test_db extended with device_pairings table."""
    test_db.execute("""
        CREATE TABLE IF NOT EXISTS device_pairings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            workspace_id INTEGER,
            pairing_code TEXT,
            pairing_id TEXT,
            device_token_hash TEXT,
            device_name TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            confirmed_at TEXT,
            revoked_at TEXT,
            last_seen_at TEXT,
            expires_at TEXT NOT NULL
        )
    """)
    test_db.commit()
    return test_db


def test_validate_device_token_confirmed(device_db):
    """A confirmed, non-revoked token resolves to user_id + workspace_id."""
    from web.middleware.device_auth import validate_device_token
    token = "test_device_token_abc123"
    token_hash = _hash_token(token)
    device_db.execute(
        "INSERT INTO device_pairings (user_id, workspace_id, device_token_hash, status, expires_at) "
        "VALUES (?, ?, ?, 'confirmed', ?)",
        (1, 1, token_hash, datetime(2099, 1, 1, tzinfo=timezone.utc).isoformat()),
    )
    device_db.commit()

    result = validate_device_token(_SqliteCompat(device_db), token)
    assert result is not None
    assert result["user_id"] == 1
    assert result["workspace_id"] == 1


def test_validate_device_token_revoked(device_db):
    """A revoked token returns None."""
    from web.middleware.device_auth import validate_device_token
    token = "revoked_token_xyz"
    token_hash = _hash_token(token)
    device_db.execute(
        "INSERT INTO device_pairings (user_id, workspace_id, device_token_hash, status, "
        "revoked_at, expires_at) "
        "VALUES (?, ?, ?, 'revoked', ?, ?)",
        (1, 1, token_hash,
         datetime.now(timezone.utc).isoformat(),
         datetime(2099, 1, 1, tzinfo=timezone.utc).isoformat()),
    )
    device_db.commit()

    result = validate_device_token(_SqliteCompat(device_db), token)
    assert result is None
