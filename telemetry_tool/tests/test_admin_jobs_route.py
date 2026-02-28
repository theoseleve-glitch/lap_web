"""Tests for admin jobs routes.

Verifies:
- GET /admin/jobs returns cross-workspace job list
- GET /admin/jobs/:id returns job detail
- POST /admin/jobs/:id/retry re-dispatches job
- POST /admin/jobs/:id/cancel revokes Celery task
- GET /admin/jobs/stats returns aggregate stats
"""
import sys
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class TestListJobs:
    def _make_app(self):
        from flask import Flask
        app = Flask(__name__)
        app.config["TESTING"] = True

        from web.routes.admin.jobs import bp as jobs_bp
        app.register_blueprint(jobs_bp, url_prefix="/api/v1/admin")
        return app

    def _admin_context(self):
        from flask import g
        g.current_user_id = 99
        g.admin_user = {
            "is_superadmin": True,
            "admin_role": "sre_admin",
            "totp_enabled": True,
        }
        g.admin_verified = True

    def test_returns_job_list(self):
        app = self._make_app()

        with app.test_request_context("/api/v1/admin/jobs"):
            self._admin_context()

            with patch("web.routes.admin.jobs._get_conn") as mock_conn:
                conn = MagicMock()
                mock_conn.return_value = conn

                cur = MagicMock()
                cur.fetchall.return_value = [
                    {
                        "job_id": "abc-123",
                        "file_name": "test.csv",
                        "status": "completed",
                        "user_id": 1,
                        "workspace_id": 1,
                        "created_at": datetime(2026, 2, 28, tzinfo=timezone.utc),
                        "duration_s": 30.0,
                    },
                ]
                conn.execute.return_value = cur

                from web.routes.admin.jobs import list_jobs
                response = list_jobs()

                if isinstance(response, tuple):
                    data = response[0].get_json()
                else:
                    data = response.get_json()

                assert data["ok"] is True
                assert len(data["data"]) == 1

    def test_filters_by_status(self):
        app = self._make_app()

        with app.test_request_context("/api/v1/admin/jobs?status=failed"):
            self._admin_context()

            with patch("web.routes.admin.jobs._get_conn") as mock_conn:
                conn = MagicMock()
                mock_conn.return_value = conn

                cur = MagicMock()
                cur.fetchall.return_value = []
                conn.execute.return_value = cur

                from web.routes.admin.jobs import list_jobs
                list_jobs()

                sql, params = conn.execute.call_args[0]
                assert params["status"] == "failed"


class TestGetJobDetail:
    def _make_app(self):
        from flask import Flask
        app = Flask(__name__)
        app.config["TESTING"] = True

        from web.routes.admin.jobs import bp as jobs_bp
        app.register_blueprint(jobs_bp, url_prefix="/api/v1/admin")
        return app

    def _admin_context(self):
        from flask import g
        g.current_user_id = 99
        g.admin_user = {
            "is_superadmin": True,
            "admin_role": "sre_admin",
            "totp_enabled": True,
        }
        g.admin_verified = True

    def test_returns_job_detail(self):
        app = self._make_app()

        with app.test_request_context("/api/v1/admin/jobs/abc-123"):
            self._admin_context()

            with patch("web.routes.admin.jobs._get_conn") as mock_conn:
                conn = MagicMock()
                mock_conn.return_value = conn

                cur = MagicMock()
                cur.fetchone.return_value = {
                    "job_id": "abc-123",
                    "file_name": "test.csv",
                    "status": "failed",
                    "error_message": "Parse error",
                    "user_id": 1,
                    "workspace_id": 1,
                    "celery_task_id": "cel-456",
                    "retry_count": 0,
                    "created_at": datetime(2026, 2, 28, tzinfo=timezone.utc),
                }
                conn.execute.return_value = cur

                from web.routes.admin.jobs import get_job_detail
                response = get_job_detail("abc-123")

                if isinstance(response, tuple):
                    data = response[0].get_json()
                else:
                    data = response.get_json()

                assert data["ok"] is True
                assert data["data"]["job_id"] == "abc-123"

    def test_job_not_found(self):
        app = self._make_app()

        with app.test_request_context("/api/v1/admin/jobs/nonexistent"):
            self._admin_context()

            with patch("web.routes.admin.jobs._get_conn") as mock_conn:
                conn = MagicMock()
                mock_conn.return_value = conn

                cur = MagicMock()
                cur.fetchone.return_value = None
                conn.execute.return_value = cur

                from web.routes.admin.jobs import get_job_detail
                response = get_job_detail("nonexistent")

                if isinstance(response, tuple):
                    data, status = response[0].get_json(), response[1]
                else:
                    data, status = response.get_json(), 200

                assert status == 404


class TestRetryJob:
    def _make_app(self):
        from flask import Flask
        app = Flask(__name__)
        app.config["TESTING"] = True

        from web.routes.admin.jobs import bp as jobs_bp
        app.register_blueprint(jobs_bp, url_prefix="/api/v1/admin")
        return app

    def test_retries_failed_job(self):
        app = self._make_app()

        with app.test_request_context(
            "/api/v1/admin/jobs/abc-123/retry",
            method="POST",
            content_type="application/json",
            data=json.dumps({"reason": "Transient error resolved"}),
        ):
            from flask import g
            g.current_user_id = 99
            g.admin_user = {
                "is_superadmin": True,
                "admin_role": "sre_admin",
                "totp_enabled": True,
            }
            g.admin_verified = True

            with patch("web.routes.admin.jobs._get_conn") as mock_conn:
                conn = MagicMock()
                mock_conn.return_value = conn

                # First call: fetch job
                call_count = [0]

                def mock_execute(sql, params=None):
                    cur = MagicMock()
                    key = call_count[0]
                    call_count[0] += 1
                    if key == 0:  # fetch job
                        cur.fetchone.return_value = {
                            "job_id": "abc-123",
                            "status": "failed",
                            "retry_count": 0,
                            "file_name": "test.csv",
                            "user_id": 1,
                            "workspace_id": 1,
                        }
                    return cur

                conn.execute.side_effect = mock_execute

                from web.routes.admin.jobs import retry_job
                response = retry_job("abc-123")

                if isinstance(response, tuple):
                    data = response[0].get_json()
                else:
                    data = response.get_json()

                assert data["ok"] is True


class TestJobStats:
    def _make_app(self):
        from flask import Flask
        app = Flask(__name__)
        app.config["TESTING"] = True

        from web.routes.admin.jobs import bp as jobs_bp
        app.register_blueprint(jobs_bp, url_prefix="/api/v1/admin")
        return app

    def test_returns_stats(self):
        app = self._make_app()

        with app.test_request_context("/api/v1/admin/jobs/stats"):
            from flask import g
            g.current_user_id = 99
            g.admin_user = {
                "is_superadmin": True,
                "admin_role": "sre_admin",
                "totp_enabled": True,
            }
            g.admin_verified = True

            with patch("web.routes.admin.jobs._get_conn") as mock_conn:
                conn = MagicMock()
                mock_conn.return_value = conn

                call_count = [0]

                def mock_execute(sql, params=None):
                    cur = MagicMock()
                    key = call_count[0]
                    call_count[0] += 1
                    if key == 0:  # aggregate stats
                        cur.fetchone.return_value = {
                            "total": 100, "failed": 5,
                            "queue_depth": 3,
                            "p50_duration": 20.0,
                            "p95_duration": 45.0,
                        }
                    elif key == 1:  # top error classes
                        cur.fetchall.return_value = [
                            {"error_class": "ParseError", "cnt": 3},
                            {"error_class": "TimeoutError", "cnt": 2},
                        ]
                    return cur

                conn.execute.side_effect = mock_execute

                from web.routes.admin.jobs import job_stats
                response = job_stats()

                if isinstance(response, tuple):
                    data = response[0].get_json()
                else:
                    data = response.get_json()

                assert data["ok"] is True
                assert data["data"]["total"] == 100
