"""End-to-end entitlement policy tests across demo/racer/world_class tiers."""
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

from auth.entitlements import get_plan_entitlements, check_usage_limit
from web.middleware.entitlements import require_feature, require_report_quota, require_upload_size


@pytest.mark.parametrize(
    "tier,key,expected",
    [
        ("free", "reports_per_month", 1),
        ("free", "api_access", False),
        ("free", "coaching_drills", False),
        ("racer", "reports_per_month", 10),
        ("racer", "coaching_drills", True),
        ("racer", "api_access", False),
        ("world_class", "reports_per_month", -1),
        ("world_class", "api_access", True),
        ("world_class", "comparison_progress", True),
    ],
)
def test_tier_policy_matrix(tier, key, expected):
    policy = get_plan_entitlements(tier)
    assert policy[key] == expected


def test_report_quota_boundary_conditions():
    # free tier has 1 report/month
    allowed, info = check_usage_limit("free", "reports", 0)
    assert allowed is True
    assert info["remaining"] == 1

    allowed, info = check_usage_limit("free", "reports", 1)
    assert allowed is False
    assert info["remaining"] == 0

    allowed, info = check_usage_limit("free", "reports", 5)
    assert allowed is False
    assert info["remaining"] == 0


def test_unlimited_quota():
    # world_class has -1 (unlimited) reports
    allowed, info = check_usage_limit("world_class", "reports", 9999)
    assert allowed is True
    assert info["remaining"] == -1


def _make_app():
    app = Flask(__name__)
    app.config.update(USE_PG=False, DEFAULT_WORKSPACE_ID=1)

    @app.before_request
    def _inject_user():
        g.user_id = 1
        g.current_user_id = 1

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


def test_demo_blocks_feature_and_racer_allows():
    app = _make_app()
    with app.test_client() as client:
        with patch("web.middleware.entitlements.entitlement_snapshot", return_value={"exports": False, "plan_tier": "demo", "max_upload_size_mb": 200}):
            resp = client.post("/exports")
            assert resp.status_code == 403

        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {"cnt": 0}
        with patch("web.middleware.entitlements.entitlement_snapshot", return_value={"exports": True, "plan_tier": "racer", "max_upload_size_mb": 1024}), \
             patch("web.middleware.entitlements._get_conn", return_value=conn):
            resp = client.post("/exports")
            assert resp.status_code == 200


def test_quota_boundary_blocks_at_limit():
    app = _make_app()
    with app.test_client() as client:
        conn = MagicMock()
        # racer has 10 reports/month — at limit should block
        conn.execute.return_value.fetchone.return_value = {"cnt": 10}
        with patch("web.middleware.entitlements.entitlement_snapshot", return_value={"exports": True, "plan_tier": "racer", "max_upload_size_mb": 1024}), \
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
