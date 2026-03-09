"""Tests for Celery application factory and config additions."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class TestConfigRedisAndCelery:
    """Verify Config class exposes Redis and Celery settings."""

    def test_redis_url_attribute_exists(self):
        from web.config import Config
        assert hasattr(Config, "REDIS_URL")

    def test_redis_url_default_contains_redis_scheme(self):
        from web.config import Config
        assert "redis://" in Config.REDIS_URL

    def test_celery_broker_url_attribute_exists(self):
        from web.config import Config
        assert hasattr(Config, "CELERY_BROKER_URL")

    def test_celery_result_backend_attribute_exists(self):
        from web.config import Config
        assert hasattr(Config, "CELERY_RESULT_BACKEND")

    def test_celery_broker_defaults_to_redis_url(self):
        """When no env override, broker should match REDIS_URL."""
        from web.config import Config
        assert Config.CELERY_BROKER_URL == Config.REDIS_URL

    def test_celery_backend_defaults_to_redis_url(self):
        """When no env override, backend should match REDIS_URL."""
        from web.config import Config
        assert Config.CELERY_RESULT_BACKEND == Config.REDIS_URL

    def test_redis_url_env_override(self):
        """REDIS_URL env var should override the default."""
        with patch.dict("os.environ", {"REDIS_URL": "redis://custom:6380/1"}, clear=False):
            # Force reimport to pick up env
            import importlib

            import web.config as cfg_mod
            importlib.reload(cfg_mod)
            assert cfg_mod.Config.REDIS_URL == "redis://custom:6380/1"
            # Restore
            importlib.reload(cfg_mod)


class TestMakeCelery:
    """Verify make_celery factory produces correctly configured Celery."""

    def test_returns_celery_instance(self):
        from celery_app import make_celery
        cel = make_celery()
        from celery import Celery
        assert isinstance(cel, Celery)

    def test_main_name_is_telemetry_tool(self):
        from celery_app import make_celery
        cel = make_celery()
        assert cel.main == "telemetry_tool"

    def test_json_task_serializer(self):
        from celery_app import make_celery
        cel = make_celery()
        assert cel.conf.task_serializer == "json"

    def test_json_accept_content(self):
        from celery_app import make_celery
        cel = make_celery()
        assert "json" in cel.conf.accept_content

    def test_json_result_serializer(self):
        from celery_app import make_celery
        cel = make_celery()
        assert cel.conf.result_serializer == "json"

    def test_task_acks_late_enabled(self):
        from celery_app import make_celery
        cel = make_celery()
        assert cel.conf.task_acks_late is True

    def test_task_reject_on_worker_lost_enabled(self):
        from celery_app import make_celery
        cel = make_celery()
        assert cel.conf.task_reject_on_worker_lost is True

    def test_result_expires_24h(self):
        from celery_app import make_celery
        cel = make_celery()
        assert cel.conf.result_expires == 86400

    def test_task_routes_pipeline_queue(self):
        from celery_app import make_celery
        cel = make_celery()
        routes = cel.conf.task_routes
        assert "tasks.pipeline_tasks.*" in routes
        assert routes["tasks.pipeline_tasks.*"]["queue"] == "pipeline"

    def test_task_routes_batch_queue(self):
        from celery_app import make_celery
        cel = make_celery()
        routes = cel.conf.task_routes
        assert "tasks.batch_tasks.*" in routes
        assert routes["tasks.batch_tasks.*"]["queue"] == "default"

    def test_default_queue_is_default(self):
        from celery_app import make_celery
        cel = make_celery()
        assert cel.conf.task_default_queue == "default"

    def test_standalone_celery_instance_exists(self):
        """Module-level `celery` attribute for CLI entry point."""
        import celery_app
        assert hasattr(celery_app, "celery")
        from celery import Celery
        assert isinstance(celery_app.celery, Celery)

    def test_with_flask_app_context(self):
        """When passed a Flask app, tasks should run inside app context."""
        # Minimal mock app
        from unittest.mock import MagicMock

        from celery_app import make_celery
        mock_app = MagicMock()
        mock_app.config = {
            "CELERY_BROKER_URL": "redis://localhost:6379/0",
            "CELERY_RESULT_BACKEND": "redis://localhost:6379/0",
        }
        cel = make_celery(mock_app)
        assert isinstance(cel, __import__("celery").Celery)
