"""Tests for the /api/v1/dev-plans JSON API endpoints."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture()
def app(test_db):
    """Minimal Flask app with api_v1_entities blueprint + patched DB connection."""
    from flask import Flask
    app = Flask(__name__)
    app.config["TESTING"] = True

    from web.routes.api_v1_entities import bp
    app.register_blueprint(bp)
    return app


@pytest.fixture()
def client(app, test_db):
    with patch("web.routes.api_v1_entities._get_conn", return_value=test_db):
        with app.test_client() as c:
            yield c


@pytest.fixture()
def seeded_client(client, test_db):
    """Client with a driver already inserted."""
    test_db.execute(
        "INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test Driver')"
    )
    test_db.commit()
    return client


class TestDevPlansAPI:
    """Tests for development plans CRUD."""

    def test_list_empty(self, seeded_client):
        resp = seeded_client.get("/api/v1/dev-plans")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"] == []

    def test_list_templates(self, seeded_client):
        resp = seeded_client.get("/api/v1/dev-plans/templates")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert len(body["data"]) == 5  # 5 templates

    def test_create_custom_plan(self, seeded_client):
        resp = seeded_client.post(
            "/api/v1/dev-plans",
            data=json.dumps({"driver_id": 1, "plan_name": "My Plan"}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["plan_name"] == "My Plan"
        assert body["data"]["driver_id"] == 1
        assert body["data"]["status"] == "active"

    def test_create_from_template(self, seeded_client):
        resp = seeded_client.post(
            "/api/v1/dev-plans",
            data=json.dumps({
                "driver_id": 1,
                "plan_name": "Beginner Plan",
                "template_id": "beginner",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["data"]["template_id"] == "beginner"
        assert body["data"]["level"] == "beginner"
        assert len(body["data"]["weeks"]) == 4

    def test_create_missing_fields(self, seeded_client):
        resp = seeded_client.post(
            "/api/v1/dev-plans",
            data=json.dumps({"plan_name": "No driver"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_get_plan_detail(self, seeded_client, test_db):
        test_db.execute(
            "INSERT INTO development_plans (id, driver_id, plan_name, weeks_json, progress_json) "
            "VALUES (99, 1, 'Detail Test', '[]', '[]')"
        )
        test_db.commit()

        resp = seeded_client.get("/api/v1/dev-plans/99")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["id"] == 99
        assert body["data"]["plan_name"] == "Detail Test"
        assert "progress_json" in body["data"]
        assert "weeks" in body["data"]

    def test_get_plan_not_found(self, seeded_client):
        resp = seeded_client.get("/api/v1/dev-plans/9999")
        assert resp.status_code == 404

    def test_patch_progress(self, seeded_client, test_db):
        test_db.execute(
            "INSERT INTO development_plans (id, driver_id, plan_name, weeks_json, progress_json) "
            "VALUES (50, 1, 'Patch Me', '[]', '[]')"
        )
        test_db.commit()

        new_progress = json.dumps({"items": [{"text": "Done", "done": True}]})
        resp = seeded_client.patch(
            "/api/v1/dev-plans/50",
            data=json.dumps({"progress_json": new_progress}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["progress_json"] == new_progress

    def test_patch_status_and_name(self, seeded_client, test_db):
        test_db.execute(
            "INSERT INTO development_plans (id, driver_id, plan_name, weeks_json, progress_json) "
            "VALUES (51, 1, 'Old Name', '[]', '[]')"
        )
        test_db.commit()

        resp = seeded_client.patch(
            "/api/v1/dev-plans/51",
            data=json.dumps({"plan_name": "New Name", "status": "completed"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["plan_name"] == "New Name"
        assert body["data"]["status"] == "completed"

    def test_patch_no_fields(self, seeded_client, test_db):
        test_db.execute(
            "INSERT INTO development_plans (id, driver_id, plan_name, weeks_json, progress_json) "
            "VALUES (52, 1, 'No Patch', '[]', '[]')"
        )
        test_db.commit()

        resp = seeded_client.patch(
            "/api/v1/dev-plans/52",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_delete_plan(self, seeded_client, test_db):
        test_db.execute(
            "INSERT INTO development_plans (id, driver_id, plan_name, weeks_json, progress_json) "
            "VALUES (60, 1, 'Delete Me', '[]', '[]')"
        )
        test_db.commit()

        resp = seeded_client.delete("/api/v1/dev-plans/60")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["deleted"] is True

        # Verify gone
        resp2 = seeded_client.get("/api/v1/dev-plans/60")
        assert resp2.status_code == 404

    def test_delete_not_found(self, seeded_client):
        resp = seeded_client.delete("/api/v1/dev-plans/9999")
        assert resp.status_code == 404

    def test_list_with_driver_filter(self, seeded_client, test_db):
        test_db.execute(
            "INSERT INTO drivers (driver_id, driver_name) VALUES (2, 'Other Driver')"
        )
        test_db.execute(
            "INSERT INTO development_plans (driver_id, plan_name, weeks_json, progress_json) "
            "VALUES (1, 'Plan A', '[]', '[]')"
        )
        test_db.execute(
            "INSERT INTO development_plans (driver_id, plan_name, weeks_json, progress_json) "
            "VALUES (2, 'Plan B', '[]', '[]')"
        )
        test_db.commit()

        resp = seeded_client.get("/api/v1/dev-plans?driver_id=1")
        body = resp.get_json()
        assert len(body["data"]) == 1
        assert body["data"][0]["plan_name"] == "Plan A"
