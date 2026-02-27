"""End-to-end entitlement policy tests across Demo/Racer/World-Class/B2B tiers."""
from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask, jsonify, g

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from auth.entitlements import get_policy_for_tier, report_quota_remaining
from web.middleware.entitlements import require_feature, require_report_quota, require_upload_size


@pytest.mark.parametrize(
    "tier,expected",
    [
        ("demo", {"quota": 5, "upload_mb": 200, "api": False, "live": False, "exports": False}),
        ("racer", {"quota": 40, "upload_mb": 1024, "api": True, "live": False, "exports": True}),
        ("world-class", {"quota": 200, "upload_mb": 4096, "api": True, "live": True, "exports": True}),
        ("b2b", {"quota": 10_000, "upload_mb": 12 * 1024, "api": True, "live": True, "exports": True}),
    ],
)
def test_tier_policy_matrix(tier, expected):
    policy = get_policy_for_tier(tier)
    assert policy.report_quota_monthly == expected["quota"]
    assert policy.max_upload_size_mb == expected["upload_mb"]
    assert policy.api_access is expected["api"]
    assert policy.strategy_live is expected["live"]
    assert policy.exports is expected["exports"]


def test_report_quota_boundary_conditions():
    demo = get_policy_for_tier("demo")
    assert report_quota_remaining(demo, 4) == 1
    assert report_quota_remaining(demo, 5) == 0
    assert report_quota_remaining(demo, 6) == 0


def _make_app():
    app = Flask(__name__)
    app.config.update(USE_PG=False, DEFAULT_WORKSPACE_ID=1)

    @app.before_request
    def _inject_user():
        g.user_id = 1

    @app.route("/exports", methods=["POST"])
    @require_feature("exports")
    @require_report_quota
    def exports_route():
        return jsonify({"ok": True})

    @app.route("/upload", methods=["POST"])
    @require_upload_size("file")
    def upload_route():
        return jsonify({"ok": True})

    return app


def test_demo_blocks_exports_and_racer_allows():
    app = _make_app()
    with app.test_client() as client:
        with patch("web.middleware.entitlements.entitlement_snapshot", return_value={"exports": False, "tier_key": "demo", "max_upload_size_mb": 200}):
            resp = client.post("/exports")
            assert resp.status_code == 403

        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {"cnt": 1}
        with patch("web.middleware.entitlements.entitlement_snapshot", return_value={"exports": True, "tier_key": "racer", "max_upload_size_mb": 1024}), \
             patch("web.middleware.entitlements._get_conn", return_value=conn):
            resp = client.post("/exports")
            assert resp.status_code == 200


def test_quota_boundary_blocks_at_limit():
    app = _make_app()
    with app.test_client() as client:
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {"cnt": 5}
        with patch("web.middleware.entitlements.entitlement_snapshot", return_value={"exports": True, "tier_key": "demo", "max_upload_size_mb": 200}), \
             patch("web.middleware.entitlements._get_conn", return_value=conn):
            resp = client.post("/exports")
            assert resp.status_code == 429


def test_upload_size_boundary():
    app = _make_app()
    with app.test_client() as client:
        # Boundary check at 2 MB and 1-byte overflow
        with patch("web.middleware.entitlements.entitlement_snapshot", return_value={"max_upload_size_mb": 2}):
            resp = client.post(
                "/upload",
                data={"file": (io.BytesIO(b"a" * (2 * 1024 * 1024)), "laps.csv")},
                content_type="multipart/form-data",
            )
            assert resp.status_code == 200

        with patch("web.middleware.entitlements.entitlement_snapshot", return_value={"max_upload_size_mb": 2}):
            resp = client.post(
                "/upload",
                data={"file": (io.BytesIO(b"a" * (2 * 1024 * 1024 + 1)), "laps.csv")},
                content_type="multipart/form-data",
            )
            assert resp.status_code == 413
