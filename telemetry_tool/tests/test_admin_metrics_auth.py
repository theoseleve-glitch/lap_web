"""/admin/metrics must require an allowed superadmin JWT.

Regression guard for the pre-existing gap: the metrics blueprint is registered
at /admin (outside the /api/v1 auth chain), so it was reachable unauthenticated
and exposed job/webhook/billing metrics.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["USE_PG"] = False
    app.config["JWT_SECRET"] = "test-secret"
    from web.metrics import init_metrics
    init_metrics(app)
    return app.test_client()


def _conn_for(user_row):
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = user_row
    return conn


def test_no_token_is_unauthorized(client):
    resp = client.get("/admin/metrics")
    assert resp.status_code == 401


def test_non_superadmin_is_forbidden(client):
    with patch("auth.service.decode_access_token", return_value={"user_id": 7}), \
         patch("web.routes.admin.middleware._get_admin_conn",
               return_value=_conn_for({"is_superadmin": False, "email": "theos.eleve@gmail.com"})):
        resp = client.get("/admin/metrics", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 403


def test_superadmin_but_wrong_email_is_forbidden(client):
    with patch("auth.service.decode_access_token", return_value={"user_id": 7}), \
         patch("web.routes.admin.middleware._get_admin_conn",
               return_value=_conn_for({"is_superadmin": True, "email": "attacker@evil.com"})):
        resp = client.get("/admin/metrics", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 403


def test_allowed_superadmin_passes_the_gate(client):
    # A valid admin gets past auth; without Redis the route then returns 503.
    # The point is it is NOT 401/403 — the gate let it through.
    with patch("auth.service.decode_access_token", return_value={"user_id": 1}), \
         patch("web.routes.admin.middleware._get_admin_conn",
               return_value=_conn_for({"is_superadmin": True, "email": "theos.eleve@gmail.com"})):
        resp = client.get("/admin/metrics", headers={"Authorization": "Bearer x"})
        assert resp.status_code not in (401, 403)
