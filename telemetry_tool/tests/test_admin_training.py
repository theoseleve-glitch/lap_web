"""Tests for admin training blueprint.

Verifies:
- _get_training_status reads latest audit manifest
- _get_training_status handles missing/empty audit dir
- _get_training_config returns defaults when Redis unavailable
- _get_training_config reads from Redis hash
- _trigger_training dispatches Celery task
- _list_audit_manifests returns sorted list
- Config update rejects invalid values
- Config update rejects unknown keys
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from web.routes.admin.training import (
    _DEFAULT_CONFIG,
    _get_training_config,
    _get_training_status,
    _list_audit_manifests,
    _trigger_training,
)

# ---------------------------------------------------------------------------
# _list_audit_manifests
# ---------------------------------------------------------------------------


class TestListAuditManifests:
    def test_returns_empty_when_dir_missing(self):
        """Returns empty list when audit dir does not exist."""
        with patch("web.routes.admin.training._AUDIT_DIR", Path("/nonexistent/path")):
            result = _list_audit_manifests()
        assert result == []

    def test_returns_sorted_filenames(self):
        """Returns manifest filenames sorted newest first."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_dir = Path(tmpdir)
            (audit_dir / "training_20260101.json").write_text("{}")
            (audit_dir / "training_20260215.json").write_text("{}")
            (audit_dir / "training_20260301.json").write_text("{}")

            with patch("web.routes.admin.training._AUDIT_DIR", audit_dir):
                result = _list_audit_manifests()

            assert result == [
                "training_20260301.json",
                "training_20260215.json",
                "training_20260101.json",
            ]

    def test_ignores_non_training_files(self):
        """Only files matching training_*.json are returned."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_dir = Path(tmpdir)
            (audit_dir / "training_20260101.json").write_text("{}")
            (audit_dir / "other_file.json").write_text("{}")
            (audit_dir / "readme.txt").write_text("hi")

            with patch("web.routes.admin.training._AUDIT_DIR", audit_dir):
                result = _list_audit_manifests()

            assert result == ["training_20260101.json"]


# ---------------------------------------------------------------------------
# _get_training_status
# ---------------------------------------------------------------------------


class TestGetTrainingStatus:
    def test_returns_no_training_runs_when_empty(self):
        """Returns 'no_training_runs' when no manifests exist."""
        with patch("web.routes.admin.training._AUDIT_DIR", Path("/nonexistent")):
            result = _get_training_status()
        assert result["status"] == "no_training_runs"
        assert result["latest"] is None

    def test_reads_latest_manifest(self):
        """Reads and returns content of the latest manifest."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_dir = Path(tmpdir)
            manifest_data = {
                "started_at": "2026-03-01T00:00:00Z",
                "tiers": {"envelopes": {"trained": 2}},
            }
            (audit_dir / "training_20260228.json").write_text(json.dumps({"old": True}))
            (audit_dir / "training_20260301.json").write_text(json.dumps(manifest_data))

            with patch("web.routes.admin.training._AUDIT_DIR", audit_dir):
                result = _get_training_status()

            assert result["status"] == "ok"
            assert result["latest"]["started_at"] == "2026-03-01T00:00:00Z"
            assert result["manifest_file"] == "training_20260301.json"

    def test_handles_corrupt_manifest(self):
        """Returns error status when manifest is not valid JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_dir = Path(tmpdir)
            (audit_dir / "training_20260301.json").write_text("not valid json {{{")

            with patch("web.routes.admin.training._AUDIT_DIR", audit_dir):
                result = _get_training_status()

            assert result["status"] == "error"
            assert "error" in result


# ---------------------------------------------------------------------------
# _get_training_config
# ---------------------------------------------------------------------------


class TestGetTrainingConfig:
    def test_returns_defaults_when_redis_unavailable(self):
        """Falls back to default config when Redis is not available."""
        with patch("web.routes.admin.training._get_redis", return_value=None):
            config = _get_training_config()
        assert config == _DEFAULT_CONFIG

    def test_returns_defaults_when_redis_empty(self):
        """Falls back to defaults when Redis hash is empty."""
        mock_redis = MagicMock()
        mock_redis.hgetall.return_value = {}
        with patch("web.routes.admin.training._get_redis", return_value=mock_redis):
            config = _get_training_config()
        assert config == _DEFAULT_CONFIG

    def test_reads_stored_values_from_redis(self):
        """Reads values from Redis hash and converts to int."""
        mock_redis = MagicMock()
        mock_redis.hgetall.return_value = {
            "schedule_hour": "6",
            "reprocess_batch_size": "20",
        }
        with patch("web.routes.admin.training._get_redis", return_value=mock_redis):
            config = _get_training_config()

        assert config["schedule_hour"] == 6
        assert config["reprocess_batch_size"] == 20
        # Defaults for unset keys
        assert config["schedule_day_of_week"] == 0
        assert config["min_sessions_per_group"] == 3

    def test_handles_redis_exception(self):
        """Returns defaults if Redis raises an exception."""
        mock_redis = MagicMock()
        mock_redis.hgetall.side_effect = RuntimeError("connection refused")
        with patch("web.routes.admin.training._get_redis", return_value=mock_redis):
            config = _get_training_config()
        assert config == _DEFAULT_CONFIG


# ---------------------------------------------------------------------------
# _trigger_training
# ---------------------------------------------------------------------------


class TestTriggerTraining:
    def test_dispatches_celery_task(self):
        """Calls apply_async and returns task_id."""
        mock_result = MagicMock()
        mock_result.id = "abc-123"

        with patch(
            "web.routes.admin.training.weekly_retrain_and_reprocess",
            create=True,
        ) as mock_task:
            # We need to patch the import inside the function
            with patch.dict("sys.modules", {"tasks.training_tasks": MagicMock()}) as _:
                import importlib

                import web.routes.admin.training as training_mod

                # Directly mock the function behavior
                mock_task_obj = MagicMock()
                mock_task_obj.apply_async.return_value = mock_result

                with patch.object(
                    training_mod,
                    "_trigger_training",
                    wraps=None,
                ):
                    # Test the inner logic directly
                    pass

        # Simpler approach: mock the import inside the function
        mock_weekly = MagicMock()
        mock_weekly.apply_async.return_value = mock_result

        with patch.dict(
            "sys.modules",
            {"tasks.training_tasks": MagicMock(weekly_retrain_and_reprocess=mock_weekly)},
        ):
            result = _trigger_training()

        assert result["task_id"] == "abc-123"
        assert result["status"] == "dispatched"
        mock_weekly.apply_async.assert_called_once()


# ---------------------------------------------------------------------------
# Route-level tests
# ---------------------------------------------------------------------------


class TestTrainingRoutes:
    def _make_app(self):
        from flask import Flask
        app = Flask(__name__)
        app.config["TESTING"] = True

        from web.routes.admin.training import bp as training_bp
        app.register_blueprint(training_bp, url_prefix="/api/v1/admin")
        return app

    def _admin_context(self, app):
        from flask import g
        g.current_user_id = 1
        g.admin_user = {
            "is_superadmin": True,
            "admin_role": "root_admin",
            "totp_enabled": True,
        }
        g.admin_verified = True

    def test_config_update_rejects_unknown_keys(self):
        """PUT /training/config rejects unknown config keys."""
        app = self._make_app()

        with app.test_request_context(
            "/api/v1/admin/training/config",
            method="PUT",
            json={"unknown_key": 5},
        ):
            self._admin_context(app)

            mock_redis = MagicMock()
            with patch("web.routes.admin.training._get_redis", return_value=mock_redis):
                from web.routes.admin.training import training_config_update
                response = training_config_update()

            if isinstance(response, tuple):
                data = response[0].get_json()
                status = response[1]
            else:
                data = response.get_json()
                status = 200

            assert data["ok"] is False
            assert status == 400

    def test_config_update_rejects_negative_values(self):
        """PUT /training/config rejects negative integer values."""
        app = self._make_app()

        with app.test_request_context(
            "/api/v1/admin/training/config",
            method="PUT",
            json={"schedule_hour": -1},
        ):
            self._admin_context(app)

            mock_redis = MagicMock()
            with patch("web.routes.admin.training._get_redis", return_value=mock_redis):
                from web.routes.admin.training import training_config_update
                response = training_config_update()

            if isinstance(response, tuple):
                data = response[0].get_json()
                status = response[1]
            else:
                data = response.get_json()
                status = 200

            assert data["ok"] is False
            assert status == 400

    def test_config_update_rejects_non_integer_values(self):
        """PUT /training/config rejects non-integer values."""
        app = self._make_app()

        with app.test_request_context(
            "/api/v1/admin/training/config",
            method="PUT",
            json={"schedule_hour": "abc"},
        ):
            self._admin_context(app)

            mock_redis = MagicMock()
            with patch("web.routes.admin.training._get_redis", return_value=mock_redis):
                from web.routes.admin.training import training_config_update
                response = training_config_update()

            if isinstance(response, tuple):
                data = response[0].get_json()
                status = response[1]
            else:
                data = response.get_json()
                status = 200

            assert data["ok"] is False
            assert status == 400

    def test_config_update_accepts_valid_values(self):
        """PUT /training/config writes valid values to Redis."""
        app = self._make_app()

        with app.test_request_context(
            "/api/v1/admin/training/config",
            method="PUT",
            json={"schedule_hour": 6, "reprocess_batch_size": 20},
        ):
            self._admin_context(app)

            mock_redis = MagicMock()
            mock_redis.hgetall.return_value = {
                "schedule_hour": "6",
                "reprocess_batch_size": "20",
            }

            with patch("web.routes.admin.training._get_redis", return_value=mock_redis), \
                 patch("web.routes.admin.training._get_conn") as mock_conn:
                mock_conn.return_value = MagicMock()

                from web.routes.admin.training import training_config_update
                response = training_config_update()

            if isinstance(response, tuple):
                data = response[0].get_json()
                status = response[1]
            else:
                data = response.get_json()
                status = 200

            assert data["ok"] is True
            assert status == 200
            mock_redis.hset.assert_called_once()

    def test_status_endpoint(self):
        """GET /training/status returns training status."""
        app = self._make_app()

        with app.test_request_context("/api/v1/admin/training/status"):
            self._admin_context(app)

            with patch(
                "web.routes.admin.training._get_training_status",
                return_value={"status": "no_training_runs", "latest": None},
            ):
                from web.routes.admin.training import training_status
                response = training_status()

            if isinstance(response, tuple):
                data = response[0].get_json()
            else:
                data = response.get_json()

            assert data["ok"] is True
            assert data["data"]["status"] == "no_training_runs"

    def test_history_endpoint(self):
        """GET /training/history returns manifest list."""
        app = self._make_app()

        with app.test_request_context("/api/v1/admin/training/history"):
            self._admin_context(app)

            with patch(
                "web.routes.admin.training._list_audit_manifests",
                return_value=["training_20260301.json", "training_20260228.json"],
            ):
                from web.routes.admin.training import training_history
                response = training_history()

            if isinstance(response, tuple):
                data = response[0].get_json()
            else:
                data = response.get_json()

            assert data["ok"] is True
            assert data["data"]["count"] == 2
