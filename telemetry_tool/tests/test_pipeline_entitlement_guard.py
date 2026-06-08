"""Tests that pipeline tasks verify entitlements before processing.

Tests for:
- _verify_task_entitlements helper (paid, zero-report, unlimited, fail-closed,
  status-aware, no-user-id resolution)
- pipeline_ingest integration: guard blocks when entitlement fails, allows when
  it passes, checks even when ctx.user_id is absent.
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

from pipeline_errors import TransientError


class TestVerifyTaskEntitlements:
    """Tests for _verify_task_entitlements helper — new fail-closed semantics."""

    # ------------------------------------------------------------------
    # (a) locked/unpaid owner → denied
    # ------------------------------------------------------------------

    def test_locked_owner_is_denied(self):
        """Owner with analyses_per_month=0 (locked floor) is denied."""
        from tasks.pipeline_tasks import _verify_task_entitlements

        mock_conn = MagicMock()
        locked_ents = {
            "analyses_per_month": 0,
            "plan_tier": "locked",
            "subscription_status": "free",
        }
        with patch(
            "tasks.pipeline_tasks.get_user_entitlements", return_value=locked_ents
        ):
            result = _verify_task_entitlements(
                user_id=1, workspace_id=1, conn=mock_conn
            )
        assert result is False

    def test_unpaid_subscription_status_is_denied(self):
        """Unpaid status collapses to analyses_per_month=0 → denied."""
        from tasks.pipeline_tasks import _verify_task_entitlements

        mock_conn = MagicMock()
        # get_user_entitlements (cfe9cbf) returns 0 for unpaid statuses
        unpaid_ents = {
            "analyses_per_month": 0,
            "plan_tier": "racer",
            "subscription_status": "unpaid",
        }
        with patch(
            "tasks.pipeline_tasks.get_user_entitlements", return_value=unpaid_ents
        ):
            result = _verify_task_entitlements(
                user_id=1, workspace_id=1, conn=mock_conn
            )
        assert result is False

    def test_expired_subscription_is_denied(self):
        """Expired subscription → analyses_per_month=0 → denied."""
        from tasks.pipeline_tasks import _verify_task_entitlements

        mock_conn = MagicMock()
        expired_ents = {
            "analyses_per_month": 0,
            "plan_tier": "racer",
            "subscription_status": "expired",
        }
        with patch(
            "tasks.pipeline_tasks.get_user_entitlements", return_value=expired_ents
        ):
            result = _verify_task_entitlements(
                user_id=1, workspace_id=1, conn=mock_conn
            )
        assert result is False

    # ------------------------------------------------------------------
    # (b) world_class + active → allowed
    # ------------------------------------------------------------------

    def test_world_class_active_is_allowed(self):
        """world_class tier with active status → analyses_per_month=-1 → allowed."""
        from tasks.pipeline_tasks import _verify_task_entitlements

        mock_conn = MagicMock()
        wc_ents = {
            "analyses_per_month": -1,   # unlimited
            "plan_tier": "world_class",
            "subscription_status": "active",
        }
        with patch(
            "tasks.pipeline_tasks.get_user_entitlements", return_value=wc_ents
        ):
            result = _verify_task_entitlements(
                user_id=1, workspace_id=1, conn=mock_conn
            )
        assert result is True

    def test_racer_active_is_allowed(self):
        """racer tier with active status → analyses_per_month=10 → allowed."""
        from tasks.pipeline_tasks import _verify_task_entitlements

        mock_conn = MagicMock()
        racer_ents = {
            "analyses_per_month": 10,
            "plan_tier": "racer",
            "subscription_status": "active",
        }
        with patch(
            "tasks.pipeline_tasks.get_user_entitlements", return_value=racer_ents
        ):
            result = _verify_task_entitlements(
                user_id=1, workspace_id=1, conn=mock_conn
            )
        assert result is True

    def test_racer_trialing_is_allowed(self):
        """Trialing is an allowed status → analyses > 0 → allowed."""
        from tasks.pipeline_tasks import _verify_task_entitlements

        mock_conn = MagicMock()
        trial_ents = {
            "analyses_per_month": 10,
            "plan_tier": "racer",
            "subscription_status": "trialing",
        }
        with patch(
            "tasks.pipeline_tasks.get_user_entitlements", return_value=trial_ents
        ):
            result = _verify_task_entitlements(
                user_id=1, workspace_id=1, conn=mock_conn
            )
        assert result is True

    # ------------------------------------------------------------------
    # (c) exception during check → fails CLOSED (not granted)
    # ------------------------------------------------------------------

    def test_exception_during_entitlements_fails_closed(self):
        """If get_user_entitlements raises, guard raises TransientError (not True)."""
        from tasks.pipeline_tasks import _verify_task_entitlements

        mock_conn = MagicMock()
        with patch(
            "tasks.pipeline_tasks.get_user_entitlements",
            side_effect=Exception("DB timeout"),
        ):
            with pytest.raises(TransientError):
                _verify_task_entitlements(
                    user_id=1, workspace_id=1, conn=mock_conn
                )

    def test_db_connection_failure_fails_closed(self):
        """If we need to open our own connection and it fails, raises TransientError."""
        from tasks.pipeline_tasks import _verify_task_entitlements

        with patch(
            "tasks.pipeline_tasks._get_pg_connection",
            side_effect=Exception("Connection pool exhausted"),
        ):
            with pytest.raises(TransientError):
                # conn=None forces the guard to open its own connection
                _verify_task_entitlements(user_id=1, workspace_id=1, conn=None)

    # ------------------------------------------------------------------
    # (d) ctx.user_id absent but session owner resolvable → uses owner tier
    # ------------------------------------------------------------------

    def test_resolves_session_owner_when_user_id_absent(self):
        """When user_id=None, guard resolves session owner and checks their tier."""
        from tasks.pipeline_tasks import _verify_task_entitlements

        mock_conn = MagicMock()
        # Simulate _resolve_session_owner returning (workspace_id=5, user_id=99)
        owner_ents = {
            "analyses_per_month": 10,
            "plan_tier": "racer",
            "subscription_status": "active",
        }
        with patch(
            "tasks.pipeline_tasks._resolve_session_owner",
            return_value=(5, 99),
        ), patch(
            "tasks.pipeline_tasks.get_user_entitlements", return_value=owner_ents
        ) as mock_ents:
            result = _verify_task_entitlements(
                user_id=None,
                workspace_id=None,
                conn=mock_conn,
                session_id="sess-abc",
            )

        assert result is True
        # Must check the resolved owner (user_id=99, workspace_id=5)
        mock_ents.assert_called_once_with(mock_conn, 99, 5)

    def test_resolves_locked_session_owner_is_denied(self):
        """Resolved session owner with locked entitlements → denied."""
        from tasks.pipeline_tasks import _verify_task_entitlements

        mock_conn = MagicMock()
        locked_ents = {
            "analyses_per_month": 0,
            "plan_tier": "locked",
            "subscription_status": "free",
        }
        with patch(
            "tasks.pipeline_tasks._resolve_session_owner",
            return_value=(5, 99),
        ), patch(
            "tasks.pipeline_tasks.get_user_entitlements", return_value=locked_ents
        ):
            result = _verify_task_entitlements(
                user_id=None,
                workspace_id=None,
                conn=mock_conn,
                session_id="sess-abc",
            )

        assert result is False

    def test_unresolvable_session_owner_is_denied(self):
        """If session/workspace lookup returns None, guard denies (not retries)."""
        from tasks.pipeline_tasks import _verify_task_entitlements

        mock_conn = MagicMock()
        with patch(
            "tasks.pipeline_tasks._resolve_session_owner",
            return_value=(None, None),
        ):
            result = _verify_task_entitlements(
                user_id=None,
                workspace_id=None,
                conn=mock_conn,
                session_id="orphan-sess",
            )

        assert result is False


class TestPipelineIngestEntitlementGuard:
    """Integration: pipeline_ingest checks entitlements in all paths."""

    @patch("tasks.pipeline_tasks._open_task_conn")
    @patch("tasks.pipeline_tasks._update_job_progress")
    @patch("tasks.pipeline_tasks._get_redis")
    @patch("tasks.pipeline_tasks._verify_task_entitlements", return_value=False)
    def test_blocks_when_entitlement_fails(
        self, mock_verify, mock_redis, mock_progress, mock_open_conn
    ):
        """pipeline_ingest returns None and marks job failed when entitlement denied."""
        from tasks.pipeline_tasks import pipeline_ingest

        mock_ctx = MagicMock()
        mock_ctx.job_id = "job-1"
        mock_ctx.workspace_id = "ws-1"
        mock_ctx.session_id = "sess-1"
        mock_ctx.user_id = 42

        mock_redis.return_value = MagicMock()
        mock_conn = MagicMock()
        mock_open_conn.return_value = mock_conn

        with patch("tasks.pipeline_tasks.PipelineContext.load", return_value=mock_ctx):
            result = pipeline_ingest("job-1")

        assert result is None
        # Guard must be called with user_id, workspace_id, conn, and session_id
        mock_verify.assert_called_once_with(
            user_id=42,
            workspace_id="ws-1",
            conn=mock_conn,
            session_id="sess-1",
        )
        mock_progress.assert_called_with(
            job_id="job-1",
            status="failed",
            error_message="Plan does not allow report generation",
            error_class="entitlement",
            conn=mock_conn,
        )

    @patch("tasks.pipeline_tasks._open_task_conn")
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
        mock_open_conn,
    ):
        """pipeline_ingest continues when entitlement check passes."""
        from tasks.pipeline_tasks import pipeline_ingest

        mock_ctx = MagicMock()
        mock_ctx.job_id = "job-1"
        mock_ctx.workspace_id = "ws-1"
        mock_ctx.session_id = "sess-1"
        mock_ctx.user_id = 42

        mock_redis.return_value = MagicMock()
        mock_open_conn.return_value = MagicMock()

        with patch("tasks.pipeline_tasks.PipelineContext.load", return_value=mock_ctx):
            result = pipeline_ingest("job-1")

        assert result == "job-1"
        mock_verify.assert_called_once()
        mock_run.assert_called_once()

    @patch("tasks.pipeline_tasks._open_task_conn")
    @patch("tasks.pipeline_tasks.release_workspace_lock")
    @patch("tasks.pipeline_tasks.acquire_workspace_lock", return_value=True)
    @patch("tasks.pipeline_tasks._run_ingest_stages")
    @patch("tasks.pipeline_tasks._update_job_progress")
    @patch("tasks.pipeline_tasks._get_redis")
    @patch("tasks.pipeline_tasks._verify_task_entitlements", return_value=True)
    def test_checks_even_when_no_user_id(
        self,
        mock_verify,
        mock_redis,
        mock_progress,
        mock_run,
        mock_lock,
        mock_release,
        mock_open_conn,
    ):
        """pipeline_ingest calls the guard even when ctx has no user_id
        (reprocess/batch path) — guard is NOT skipped."""
        from tasks.pipeline_tasks import pipeline_ingest

        # Use a plain object so user_id is genuinely absent / None
        class FakeCtx:
            job_id = "job-1"
            workspace_id = "ws-1"
            session_id = "sess-1"
            user_id = None
            file_path = "/data/test.csv"
            current_stage = None
            stage_status = None
            errors = []

            def save(self):
                pass

            def update_stage(self, name, status):
                pass

        mock_redis.return_value = MagicMock()
        mock_conn = MagicMock()
        mock_open_conn.return_value = mock_conn

        with patch(
            "tasks.pipeline_tasks.PipelineContext.load", return_value=FakeCtx()
        ):
            result = pipeline_ingest("job-1")

        assert result == "job-1"
        # Guard MUST be called — with user_id=None and session_id passed
        mock_verify.assert_called_once_with(
            user_id=None,
            workspace_id="ws-1",
            conn=mock_conn,
            session_id="sess-1",
        )

    @patch("tasks.pipeline_tasks._open_task_conn")
    @patch("tasks.pipeline_tasks._update_job_progress")
    @patch("tasks.pipeline_tasks._get_redis")
    @patch(
        "tasks.pipeline_tasks._verify_task_entitlements",
        side_effect=TransientError("DB blip"),
    )
    def test_transient_error_propagates_for_retry(
        self, mock_verify, mock_redis, mock_progress, mock_open_conn
    ):
        """TransientError from the guard propagates so Celery retries the task."""
        from tasks.pipeline_tasks import pipeline_ingest

        mock_ctx = MagicMock()
        mock_ctx.job_id = "job-1"
        mock_ctx.workspace_id = "ws-1"
        mock_ctx.session_id = "sess-1"
        mock_ctx.user_id = 42

        mock_redis.return_value = MagicMock()
        mock_open_conn.return_value = MagicMock()

        with patch(
            "tasks.pipeline_tasks.PipelineContext.load", return_value=mock_ctx
        ):
            with pytest.raises(TransientError):
                pipeline_ingest("job-1")
