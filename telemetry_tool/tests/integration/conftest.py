"""Shared fixtures for integration tests.

Integration tests exercise full auth → billing → entitlements flows.
Most tests mock the DB layer; PG-dependent tests are marked and skipped
when TELEMETRY_PG_URL is not set.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------

PG_URL = os.environ.get("TELEMETRY_PG_URL")
pg_required = pytest.mark.skipif(
    not PG_URL, reason="TELEMETRY_PG_URL not set -- skipping PostgreSQL tests"
)

_TEST_SECRET = "integration-test-jwt-secret-minimum-32-bytes-long"


# ---------------------------------------------------------------------------
# Flask app fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    """Create a minimal Flask app with auth + billing blueprints."""
    from flask import Flask

    application = Flask(__name__)
    application.config["TESTING"] = True
    application.config["USE_PG"] = False
    application.config["AUTH_REQUIRED"] = False
    application.config["TELEMETRY_JWT_SECRET"] = _TEST_SECRET
    application.config["SECRET_KEY"] = "test-secret-key-for-sessions-32bytes"
    return application


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()
