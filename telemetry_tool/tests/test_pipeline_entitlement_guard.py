"""Tests that pipeline tasks verify entitlements before processing.

Tests for:
- _verify_task_entitlements helper (paid, zero-report, unlimited, fail-open)
- pipeline_ingest integration: guard blocks when user_id present and entitlement fails
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class TestVerifyTaskEntitlements:
    """Tests for _verify_task_entitlements helper."""

    @patch("tasks.pipeline_tasks._get_pg_connection")
    def test_returns_true_for_paid_tier(self, mock_get_pg):
        """Paid tiers with reports_per_month > 0 return True."""
        from tasks.pipeline_tasks import _verify_task_entitlements

        mock_conn = MagicMock()
        mock_get_pg.return_value = mock_conn

        with patch(
            "auth.entitlements.get_user_plan_tier", return_value="racer"
        ), patch(
            "auth.entitlements.get_plan_entitlements",
            return_value={"reports_per_month": 10},
        ):
            assert _verify_task_entitlements(1, 1) is True

    @patch("tasks.pipeline_tasks._get_pg_connection")
    def test_returns_false_for_zero_reports(self, mock_get_pg):
        """Plans with reports_per_month=0 return False."""
        from tasks.pipeline_tasks import _verify_task_entitlements

        mock_conn = MagicMock()
        mock_get_pg.return_value = mock_conn

        with patch(
            "auth.entitlements.get_user_plan_tier", return_value="demo"
        ), patch(
            "auth.entitlements.get_plan_entitlements",
            return_value={"reports_per_month": 0},
        ):
            assert _verify_task_entitlements(1, 1) is False

    @patch("tasks.pipeline_tasks._get_pg_connection")
    def test_returns_true_for_unlimited(self, mock_get_pg):
        """Plans with reports_per_month=-1 (unlimited) return True."""
        from tasks.pipeline_tasks import _verify_task_entitlements

        mock_conn = MagicMock()
        mock_get_pg.return_value = mock_conn

        with patch(
            "auth.entitlements.get_user_plan_tier", return_value="world_class"
        ), patch(
            "auth.entitlements.get_plan_entitlements",
            return_value={"reports_per_month": -1},
        ):
            assert _verify_task_entitlements(1, 1) is True

    def test_fails_open_on_exception(self):
        """If DB check fails, allow the task (fail open)."""
        from tasks.pipeline_tasks import _verify_task_entitlements

        with patch(
            "tasks.pipeline_tasks._get_pg_connection",
            side_effect=Exception("DB down"),
        ):
            assert _verify_task_entitlements(1, 1) is True

    @patch("tasks.pipeline_tasks._get_pg_connection")
    def test_returns_false_for_free_tier(self, mock_get_pg):
        """Free tier now aliases the zero-access 'locked' floor → blocked.

        There is no 1-report free tier anymore; 'free' resolves to zero
        report generation, so the worker guard must return False.
        """
        from tasks.pipeline_tasks import _verify_task_entitlements

        mock_conn = MagicMock()
        mock_get_pg.return_value = mock_conn

        with patch(
            "auth.entitlements.get_user_plan_tier", return_value="free"
        ), patch(
            "auth.entitlements.get_plan_entitlements",
            return_value={"reports_per_month": 0},
        ):
            assert _verify_task_entitlements(1, 1) is False

    @patch("tasks.pipeline_tasks._get_pg_connection")
    def test_returns_true_when_key_missing(self, mock_get_pg):
        """If reports_per_month key is missing from plan, fails open (True)."""
        from tasks.pipeline_tasks import _verify_task_entitlements

        mock_conn = MagicMock()
        mock_get_pg.return_value = mock_conn

        with patch(
            "auth.entitlements.get_user_plan_tier", return_value="custom"
        ), patch(
            "auth.entitlements.get_plan_entitlements",
            return_value={},  # no reports_per_month key
        ):
            # .get("reports_per_month") returns None, which != 0, so True
            assert _verify_task_entitlements(1, 1) is True


class TestPipelineIngestEntitlementGuard:
    """Integration: pipeline_ingest checks entitlements when ctx has user_id."""

    @patch("tasks.pipeline_tasks._update_job_progress")
    @patch("tasks.pipeline_tasks._get_redis")
    @patch("tasks.pipeline_tasks._verify_task_entitlements", return_value=False)
    def test_blocks_when_entitlement_fails(
        self, mock_verify, mock_redis, mock_progress
    ):
        """pipeline_ingest returns None and marks job failed when entitlement denied."""
        from tasks.pipeline_tasks import pipeline_ingest

        # Build a mock context WITH user_id
        mock_ctx = MagicMock()
        mock_ctx.job_id = "job-1"
        mock_ctx.workspace_id = "ws-1"
        mock_ctx.session_id = "sess-1"
        mock_ctx.user_id = 42  # user_id present and truthy

        mock_redis_client = MagicMock()
        mock_redis.return_value = mock_redis_client

        with patch(
            "tasks.pipeline_tasks.PipelineContext.load", return_value=mock_ctx
        ):
            result = pipeline_ingest("job-1")

        assert result is None
        mock_verify.assert_called_once_with(42, "ws-1")
        # Check that _update_job_progress was called with entitlement error
        mock_progress.assert_called_with(
            job_id="job-1",
            status="failed",
            error_message="Plan does not allow report generation",
            error_class="entitlement",
        )

    @patch("tasks.pipeline_tasks.release_workspace_lock")
    @patch("tasks.pipeline_tasks.acquire_workspace_lock", return_value=True)
    @patch("tasks.pipeline_tasks._run_ingest_stages")
    @patch("tasks.pipeline_tasks._update_job_progress")
    @patch("tasks.pipeline_tasks._get_redis")
    @patch("tasks.pipeline_tasks._verify_task_entitlements", return_value=True)
    def test_proceeds_when_entitlement_passes(
        self,
        mock_verify,
        mock_redis,
        mock_progress,
        mock_run,
        mock_lock,
        mock_release,
    ):
        """pipeline_ingest continues when entitlement check passes."""
        from tasks.pipeline_tasks import pipeline_ingest

        mock_ctx = MagicMock()
        mock_ctx.job_id = "job-1"
        mock_ctx.workspace_id = "ws-1"
        mock_ctx.session_id = "sess-1"
        mock_ctx.user_id = 42

        mock_redis_client = MagicMock()
        mock_redis.return_value = mock_redis_client

        with patch(
            "tasks.pipeline_tasks.PipelineContext.load", return_value=mock_ctx
        ):
            result = pipeline_ingest("job-1")

        assert result == "job-1"
        mock_verify.assert_called_once_with(42, "ws-1")
        mock_run.assert_called_once()

    @patch("tasks.pipeline_tasks.release_workspace_lock")
    @patch("tasks.pipeline_tasks.acquire_workspace_lock", return_value=True)
    @patch("tasks.pipeline_tasks._run_ingest_stages")
    @patch("tasks.pipeline_tasks._update_job_progress")
    @patch("tasks.pipeline_tasks._get_redis")
    @patch("tasks.pipeline_tasks._verify_task_entitlements")
    def test_skips_check_when_no_user_id(
        self,
        mock_verify,
        mock_redis,
        mock_progress,
        mock_run,
        mock_lock,
        mock_release,
    ):
        """pipeline_ingest skips entitlement check when ctx has no user_id."""
        from tasks.pipeline_tasks import pipeline_ingest

        # Use a simple namespace object (not MagicMock) to control hasattr
        class FakeCtx:
            job_id = "job-1"
            workspace_id = "ws-1"
            session_id = "sess-1"
            file_path = "/data/test.csv"
            current_stage = None
            stage_status = None
            errors = []

            def save(self):
                pass

            def update_stage(self, name, status):
                pass

        mock_redis_client = MagicMock()
        mock_redis.return_value = mock_redis_client

        with patch(
            "tasks.pipeline_tasks.PipelineContext.load",
            return_value=FakeCtx(),
        ):
            result = pipeline_ingest("job-1")

        assert result == "job-1"
        mock_verify.assert_not_called()  # No user_id → guard skipped
