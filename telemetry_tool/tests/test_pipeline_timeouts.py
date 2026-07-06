"""Tests for per-tier Celery timeout threading + stuck-job reconciliation.

Fix #6 (customer readiness, HIGH): the per-tier processing grace used to be
passed as a chain-level ``apply_async(soft_time_limit=...)`` kwarg, which
Celery only binds to the FIRST task in a chain. ``pipeline_analyze`` and
``pipeline_finalize`` silently fell back to the worker's blanket
``--soft-time-limit``/``--time-limit`` (docker-compose.prod.yml), so a b2b
customer's paid-for longer grace never reached the stages that actually need
it, and a hard kill (SIGKILL on the worker child, no Python exception raised)
mid-stage left the job row stuck 'running' forever.

Covers:
(a) every stage signature in the built chain carries the tier's soft AND
    hard limits.
(b) the default/fallback tier still gets sane limits.
(c) build_pipeline_chain() with no tier info leaves stage options untouched
    (unchanged behaviour for retry/admin-retry/sync-upload dispatch paths
    that don't know the tier).
(d) the stuck-job reconciliation flips an over-ceiling 'running' job to
    'failed' (mocked DB/cursor — no Postgres in dev).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on path (matches tests/test_pipeline_entitlement_guard.py)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tasks.pipeline_tasks import (
    HARD_LIMIT_MARGIN_S,
    TIER_TIMEOUTS_S,
    build_pipeline_chain,
)

_STAGE_NAMES = (
    "tasks.pipeline_tasks.pipeline_ingest",
    "tasks.pipeline_tasks.pipeline_analyze",
    "tasks.pipeline_tasks.pipeline_finalize",
)


class TestBuildPipelineChainTierLimits:
    """(a) every stage signature carries the tier's soft AND hard limits."""

    @pytest.mark.parametrize("tier", ["locked", "racer", "world-class", "world_class", "b2b"])
    def test_every_stage_gets_soft_and_hard_limit(self, tier):
        soft = TIER_TIMEOUTS_S[tier]
        expected_hard = soft + HARD_LIMIT_MARGIN_S

        built = build_pipeline_chain("job-tier-test", soft_time_limit=soft)
        sigs = built.tasks

        assert [s.task for s in sigs] == list(_STAGE_NAMES)
        for sig in sigs:
            assert sig.options.get("soft_time_limit") == soft, (
                f"stage {sig.task} missing tier soft_time_limit"
            )
            assert sig.options.get("time_limit") == expected_hard, (
                f"stage {sig.task} missing derived hard time_limit"
            )

    def test_b2b_grace_reaches_analyze_and_finalize(self):
        """Regression guard for the exact bug: b2b's 3600s must reach ALL
        stages, not just the first (pipeline_ingest)."""
        soft = TIER_TIMEOUTS_S["b2b"]
        built = build_pipeline_chain("job-b2b", soft_time_limit=soft)
        analyze_sig = built.tasks[1]
        finalize_sig = built.tasks[2]
        assert analyze_sig.options.get("soft_time_limit") == 3600
        assert finalize_sig.options.get("soft_time_limit") == 3600

    def test_explicit_time_limit_overrides_derived_margin(self):
        """An explicit time_limit is honoured verbatim (not soft + margin)."""
        built = build_pipeline_chain("job-explicit", soft_time_limit=100, time_limit=500)
        for sig in built.tasks:
            assert sig.options.get("soft_time_limit") == 100
            assert sig.options.get("time_limit") == 500


class TestBuildPipelineChainDefaults:
    """(b) default/fallback tier still gets sane limits."""

    def test_default_fallback_tier_gets_sane_limits(self):
        """Mirrors sessions_v2.py's TIER_TIMEOUTS_S.get(plan_tier, locked)
        fallback for an unrecognised/missing plan_tier."""
        soft = TIER_TIMEOUTS_S.get("some_unknown_tier", TIER_TIMEOUTS_S["locked"])
        assert soft == TIER_TIMEOUTS_S["locked"] == 120

        built = build_pipeline_chain("job-default", soft_time_limit=soft)
        for sig in built.tasks:
            assert sig.options.get("soft_time_limit") == 120
            assert sig.options.get("time_limit") == 120 + HARD_LIMIT_MARGIN_S

    def test_no_tier_info_leaves_stage_options_untouched(self):
        """Callers that don't know the tier yet (retry / admin-retry /
        sync-upload dispatch) must keep falling back to the worker's blanket
        --soft-time-limit/--time-limit, unchanged from prior behaviour."""
        built = build_pipeline_chain("job-no-tier")
        for sig in built.tasks:
            assert "soft_time_limit" not in sig.options
            assert "time_limit" not in sig.options


class TestStuckJobReconciliation:
    """(c) stuck-job reconciliation flips an over-ceiling 'running' job to
    'failed'. Mocks the DB connection/cursor per the pattern already used in
    tests/test_billing_tasks.py (no Postgres in dev)."""

    def test_over_ceiling_running_job_is_marked_failed(self):
        from tasks.alerting_tasks import _reconcile_stuck_jobs

        conn = MagicMock()
        # racer ceiling = 600 + 300 = 900s; this job has run for 2000s.
        conn.execute.return_value.fetchall.return_value = [
            {"job_id": "job-abc123", "running_seconds": 2000.0, "plan_tier": "racer"},
        ]

        reconciled = _reconcile_stuck_jobs(conn)

        assert len(reconciled) == 1
        assert reconciled[0]["job_id"] == "job-abc123"

        # Second execute() call is the UPDATE ... SET status = 'failed' ...
        update_call = conn.execute.call_args_list[1]
        update_sql = update_call.args[0]
        update_params = update_call.args[1]
        assert "UPDATE ingestion_jobs" in update_sql
        assert "'failed'" in update_sql
        assert update_params["jid"] == "job-abc123"
        conn.commit.assert_called_once()

    def test_under_ceiling_running_job_is_left_alone(self):
        from tasks.alerting_tasks import _reconcile_stuck_jobs

        conn = MagicMock()
        # b2b ceiling = 3600 + 300 = 3900s; this job has only run for 100s.
        conn.execute.return_value.fetchall.return_value = [
            {"job_id": "job-fresh", "running_seconds": 100.0, "plan_tier": "b2b"},
        ]

        reconciled = _reconcile_stuck_jobs(conn)

        assert reconciled == []
        # Only the SELECT ran — no UPDATE, no commit.
        assert conn.execute.call_count == 1
        conn.commit.assert_not_called()

    def test_unresolvable_tier_uses_conservative_max_ceiling(self):
        """A job whose workspace/owner can't be resolved (plan_tier is None
        from the LEFT JOIN) must use the most generous ceiling across all
        tiers, so an unresolved lookup never wrongly fails a job that could
        still be legitimately running under a long-grace tier."""
        from tasks.alerting_tasks import _reconcile_stuck_jobs

        conn = MagicMock()
        max_ceiling = max(TIER_TIMEOUTS_S.values()) + HARD_LIMIT_MARGIN_S
        conn.execute.return_value.fetchall.return_value = [
            {"job_id": "job-orphan", "running_seconds": max_ceiling - 10, "plan_tier": None},
        ]

        reconciled = _reconcile_stuck_jobs(conn)

        assert reconciled == []  # still under the conservative max ceiling
        conn.commit.assert_not_called()

    def test_check_stuck_jobs_reports_reconciled_count(self):
        """_check_stuck_jobs (the periodic beat-scheduled check) surfaces the
        reconciled count alongside its existing alert fields."""
        from tasks import alerting_tasks

        conn = MagicMock()

        def _fake_execute(sql, params=None):
            result = MagicMock()
            if "LEFT JOIN workspaces" in sql:
                result.fetchall.return_value = [
                    {"job_id": "job-stuck", "running_seconds": 99999.0, "plan_tier": "racer"},
                ]
            elif sql.strip().startswith("UPDATE"):
                result.fetchall.return_value = []
            else:
                result.fetchall.return_value = []
            return result

        conn.execute.side_effect = _fake_execute

        with patch.object(alerting_tasks, "_get_pg", return_value=conn), \
             patch("web.db_pg.return_pg_connection"):
            result = alerting_tasks._check_stuck_jobs()

        assert result["reconciled_count"] == 1
