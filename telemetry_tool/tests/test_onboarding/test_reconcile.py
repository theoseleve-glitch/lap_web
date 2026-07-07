"""Tests for tasks/onboarding_tasks.py (Task 13c): reconcile_onboarding.

Backstop beat task -- finds requests stuck mid-flight (worker crash between
drafting and emailing leaves a row un-emailable forever) and re-drives them.
Mirrors test_onboarding_tasks.py's style: mock ``onboarding_tasks.repo`` and
``onboarding_tasks.draft_and_notify.delay``, call the plain
``_run_reconcile_onboarding(conn)`` helper directly (no Celery broker
needed).

Also verifies the worker-discovery + beat wiring in celery_app.py: the
``"tasks.onboarding_tasks"`` include entry and the ``reconcile_onboarding``
beat schedule entry. Importing ``celery_app`` has no heavy side effects here
(no live broker connection is opened just by building the Celery app object),
so this asserts directly against the built app's config rather than a
lighter proxy check.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import tasks.onboarding_tasks as onboarding_tasks  # noqa: E402


@pytest.fixture
def _mock_repo(monkeypatch):
    fake = MagicMock(name="repo")
    monkeypatch.setattr(onboarding_tasks, "repo", fake)
    return fake


@pytest.fixture
def _mock_draft_and_notify(monkeypatch):
    fake = MagicMock(name="draft_and_notify")
    monkeypatch.setattr(onboarding_tasks, "draft_and_notify", fake)
    return fake


@pytest.fixture
def conn():
    return MagicMock(name="conn")


class TestReconcileHappyPath:
    def test_two_stale_ids_reset_and_redriven(self, _mock_repo, _mock_draft_and_notify, conn):
        _mock_repo.find_stale_unemailed.return_value = ["req-1", "req-2"]
        _mock_repo.reset_for_retry.return_value = True

        result = onboarding_tasks._run_reconcile_onboarding(conn)

        assert result == {"ok": True, "found": 2, "reset": 2, "resent": 0}
        _mock_repo.find_stale_unemailed.assert_called_once_with(
            conn, older_than_minutes=60
        )
        assert _mock_repo.reset_for_retry.call_args_list == [
            ((conn, "req-1"),), ((conn, "req-2"),),
        ]
        assert _mock_draft_and_notify.delay.call_args_list == [
            (("req-1",),), (("req-2",),),
        ]

    def test_custom_older_than_minutes_forwarded(self, _mock_repo, _mock_draft_and_notify, conn):
        _mock_repo.find_stale_unemailed.return_value = []
        onboarding_tasks._run_reconcile_onboarding(conn, older_than_minutes=120)
        _mock_repo.find_stale_unemailed.assert_called_once_with(
            conn, older_than_minutes=120
        )

    def test_no_stale_ids_is_a_no_op(self, _mock_repo, _mock_draft_and_notify, conn):
        _mock_repo.find_stale_unemailed.return_value = []

        result = onboarding_tasks._run_reconcile_onboarding(conn)

        assert result == {"ok": True, "found": 0, "reset": 0, "resent": 0}
        _mock_repo.reset_for_retry.assert_not_called()
        _mock_draft_and_notify.delay.assert_not_called()


class TestResetForRetryFalseSkipsEnqueue:
    def test_already_progressed_row_is_not_redriven(
        self, _mock_repo, _mock_draft_and_notify, conn,
    ):
        """reset_for_retry returning False (e.g. the row was blessed or
        emailed between find_stale_unemailed and the reset attempt) must
        not enqueue a redundant draft_and_notify."""
        _mock_repo.find_stale_unemailed.return_value = ["req-1", "req-2"]
        _mock_repo.reset_for_retry.side_effect = [False, True]

        result = onboarding_tasks._run_reconcile_onboarding(conn)

        assert result == {"ok": True, "found": 2, "reset": 1, "resent": 0}
        _mock_draft_and_notify.delay.assert_called_once_with("req-2")


class TestOneFailureDoesNotAbortBatch:
    def test_exception_on_one_id_does_not_stop_the_others(
        self, _mock_repo, _mock_draft_and_notify, conn,
    ):
        _mock_repo.find_stale_unemailed.return_value = ["req-1", "req-2", "req-3"]

        def _reset(_conn, request_id):
            if request_id == "req-2":
                raise RuntimeError("boom")
            return True

        _mock_repo.reset_for_retry.side_effect = _reset

        result = onboarding_tasks._run_reconcile_onboarding(conn)

        assert result == {"ok": True, "found": 3, "reset": 2, "resent": 0}
        assert _mock_draft_and_notify.delay.call_args_list == [
            (("req-1",),), (("req-3",),),
        ]

    def test_exception_from_delay_itself_does_not_stop_the_others(
        self, _mock_repo, _mock_draft_and_notify, conn,
    ):
        _mock_repo.find_stale_unemailed.return_value = ["req-1", "req-2"]
        _mock_repo.reset_for_retry.return_value = True

        def _delay(request_id):
            if request_id == "req-1":
                raise RuntimeError("broker down")

        _mock_draft_and_notify.delay.side_effect = _delay

        result = onboarding_tasks._run_reconcile_onboarding(conn)

        # Both were reset (reset happens before .delay), but only req-1's
        # enqueue blew up -- req-2 must still be processed.
        assert result == {"ok": True, "found": 2, "reset": 2, "resent": 0}
        assert _mock_draft_and_notify.delay.call_args_list == [
            (("req-1",),), (("req-2",),),
        ]


class TestCeleryAppWiring:
    """Sanity-check the worker discovery + routing + beat wiring added in
    celery_app.py for Task 13c. Building the Celery app (``make_celery()``)
    has no network/broker side effects -- it only constructs config -- so
    this asserts directly rather than via a lighter proxy."""

    def test_onboarding_tasks_module_in_include_list(self):
        from celery_app import make_celery
        cel = make_celery()
        assert "tasks.onboarding_tasks" in cel.conf.include

    def test_onboarding_queue_routed(self):
        from celery_app import make_celery
        cel = make_celery()
        routes = cel.conf.task_routes
        assert "tasks.onboarding_tasks.*" in routes
        assert routes["tasks.onboarding_tasks.*"]["queue"] == "onboarding"

    def test_reconcile_onboarding_beat_entry_every_30_minutes(self):
        from celery_app import make_celery
        cel = make_celery()
        schedule = cel.conf.beat_schedule
        assert "reconcile-onboarding" in schedule
        entry = schedule["reconcile-onboarding"]
        assert entry["task"] == "tasks.onboarding_tasks.reconcile_onboarding"
        assert entry["schedule"] == 1800
        assert entry["options"]["queue"] == "onboarding"

    def test_draft_and_notify_task_registered_on_the_real_app(self):
        """Confirms worker discovery actually works end-to-end: after
        importing tasks.onboarding_tasks (which decorates against the
        module-level `celery` app), both tasks are visible in the app's
        task registry."""
        import celery_app  # the module-level `celery` app, not a fresh make_celery()
        import tasks.onboarding_tasks  # noqa: F401 -- registers the tasks

        assert "tasks.onboarding_tasks.draft_and_notify" in celery_app.celery.tasks
        assert "tasks.onboarding_tasks.reconcile_onboarding" in celery_app.celery.tasks
