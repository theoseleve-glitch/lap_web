"""Tests for Fix #2 (customer-readiness BLOCKER): endurance jobs isolated
off the shared pipeline queue so they can never stall ordinary uploads.

Root cause: tasks/endurance_tasks.py declared only ``soft_time_limit=3600``
with no explicit hard ``time_limit``, so Celery fell back to the WORKER's
blanket ``--time-limit`` for the hard kill. On the shared ``pipeline`` queue
that was 2100s (35 min) — well under this task's own 60-minute soft limit —
so the hard SIGKILL always fired first, the soft limit's graceful-failure
path never ran, and (with ``task_acks_late``/``task_reject_on_worker_lost``)
Celery redelivered the killed task forever, with no job ever marked failed.

Covers:
(a) the task carries explicit soft AND hard time limits, hard > soft.
(b) tasks.endurance_tasks.* is routed to its own `endurance` queue.
(c) broker visibility_timeout covers the endurance hard limit.
(d) SoftTimeLimitExceeded raised mid-stint is NOT swallowed as a per-stint
    error (old behaviour let the loop continue to the next stint) — it
    propagates, and the task-level handler marks the whole job 'failed'
    with a clear customer-facing message, then returns normally (does not
    re-raise) so Celery acks the message instead of redelivering it.
(e) the /process route rejects over-cap stint counts, over-cap lap counts,
    and over-budget submissions with a clear 4xx.
(f) the per-job idempotency lock prevents a duplicate concurrent run
    (double submit / broker redelivery), and is released after both
    success and failure.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from flask import g

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Helpers: mock Redis — mirrors tests/test_concurrency.py's Lua-aware mock so
# the SAME atomic acquire/release scripts (reused from tasks.concurrency) are
# exercised for real, just keyed by job_id instead of workspace_id.
# ---------------------------------------------------------------------------

def _make_mock_redis(initial: dict | None = None):
    store: dict = dict(initial or {})
    mock = MagicMock()

    def _lua_handler(script, numkeys, *args):
        key = args[0]
        value = args[1] if len(args) > 1 else None
        if "set" in script and "expire" in script:
            # _ACQUIRE_LOCK_LUA: set-if-absent or refresh-if-same-owner
            current = store.get(key)
            if current is None:
                store[key] = value
                return 1
            elif current == value:
                return 1
            return 0
        # _RELEASE_LOCK_LUA: compare-and-delete
        if store.get(key) == value:
            store.pop(key, None)
            return 1
        return 0

    def _get(key):
        return store.get(key)

    def _set(key, value, **kwargs):
        store[key] = value
        return True

    def _delete(*keys):
        for k in keys:
            store.pop(k, None)

    # ── customer-readiness fixes #2/#4/#6: SET ops (active-job signal),
    # INCR/EXPIRE (redelivery-attempts bound), and scan_iter (stuck-job
    # reconciler) on top of the pre-existing GET/SET/DELETE/eval above.
    def _sadd(key, *members):
        s = store.setdefault(key, set())
        if not isinstance(s, set):
            s = store[key] = set()
        added = 0
        for m in members:
            if m not in s:
                s.add(m)
                added += 1
        return added

    def _srem(key, *members):
        s = store.get(key)
        if not isinstance(s, set):
            return 0
        removed = 0
        for m in members:
            if m in s:
                s.discard(m)
                removed += 1
        return removed

    def _scard(key):
        s = store.get(key)
        return len(s) if isinstance(s, set) else 0

    def _incr(key):
        store[key] = int(store.get(key, 0) or 0) + 1
        return store[key]

    def _expire(key, ttl):
        return key in store

    def _scan_iter(match=None, count=None):
        import fnmatch
        for k in list(store.keys()):
            if match is None or fnmatch.fnmatch(k, match):
                yield k

    mock.eval = MagicMock(side_effect=_lua_handler)
    mock.get = MagicMock(side_effect=_get)
    mock.set = MagicMock(side_effect=_set)
    mock.delete = MagicMock(side_effect=_delete)
    mock.sadd = MagicMock(side_effect=_sadd)
    mock.srem = MagicMock(side_effect=_srem)
    mock.scard = MagicMock(side_effect=_scard)
    mock.incr = MagicMock(side_effect=_incr)
    mock.expire = MagicMock(side_effect=_expire)
    mock.scan_iter = MagicMock(side_effect=_scan_iter)
    mock._store = store
    return mock


# ---------------------------------------------------------------------------
# (a) explicit soft/hard limits, hard > soft
# ---------------------------------------------------------------------------

class TestTaskTimeLimits:
    def test_hard_limit_greater_than_soft_limit(self):
        from tasks.endurance_tasks import (
            ENDURANCE_HARD_TIME_LIMIT_S,
            ENDURANCE_SOFT_TIME_LIMIT_S,
        )
        assert ENDURANCE_HARD_TIME_LIMIT_S > ENDURANCE_SOFT_TIME_LIMIT_S

    def test_task_decorator_carries_explicit_soft_and_hard_limits(self):
        from tasks.endurance_tasks import (
            ENDURANCE_HARD_TIME_LIMIT_S,
            ENDURANCE_SOFT_TIME_LIMIT_S,
            process_endurance_session,
        )
        # Celery stores decorator kwargs as attributes on the Task object.
        assert process_endurance_session.soft_time_limit == ENDURANCE_SOFT_TIME_LIMIT_S
        assert process_endurance_session.time_limit == ENDURANCE_HARD_TIME_LIMIT_S


# ---------------------------------------------------------------------------
# (b) routed to its own `endurance` queue
# ---------------------------------------------------------------------------

class TestTaskRouting:
    def test_endurance_tasks_routed_to_endurance_queue(self):
        from celery_app import make_celery
        cel = make_celery()
        routes = cel.conf.task_routes
        assert "tasks.endurance_tasks.*" in routes
        assert routes["tasks.endurance_tasks.*"]["queue"] == "endurance"

    def test_pipeline_and_batch_routes_unaffected(self):
        """Regression guard: adding the endurance route must not disturb the
        existing pipeline/batch routing."""
        from celery_app import make_celery
        cel = make_celery()
        routes = cel.conf.task_routes
        assert routes["tasks.pipeline_tasks.*"]["queue"] == "pipeline"
        assert routes["tasks.batch_tasks.*"]["queue"] == "default"


# ---------------------------------------------------------------------------
# (c) broker visibility_timeout covers the endurance hard limit
# ---------------------------------------------------------------------------

class TestBrokerVisibilityTimeout:
    def test_visibility_timeout_covers_endurance_hard_limit(self):
        """Redis' own default visibility_timeout (3600s) is BELOW the
        endurance hard limit (3900s) — without an explicit override, Redis
        would redeliver a still-legitimately-running endurance task to a
        second worker before the first one finishes."""
        from celery_app import make_celery
        from tasks.endurance_tasks import ENDURANCE_HARD_TIME_LIMIT_S
        cel = make_celery()
        opts = cel.conf.broker_transport_options
        assert opts is not None
        assert opts["visibility_timeout"] >= ENDURANCE_HARD_TIME_LIMIT_S


# ---------------------------------------------------------------------------
# (d) SoftTimeLimitExceeded is not swallowed
# ---------------------------------------------------------------------------

class TestSoftTimeLimitNotSwallowed:
    def test_inner_stint_loop_reraises_instead_of_continuing(self):
        """The old per-stint `except Exception` would have caught
        SoftTimeLimitExceeded (it IS an Exception subclass), logged a
        'stint_error', and moved on to the next stint. It must now
        propagate instead."""
        from tasks.endurance_tasks import _run_endurance_session

        _r = _make_mock_redis()
        meta = {"file_path": "dummy.csv", "session_meta": {}, "workspace_id": "1"}
        stint_configs = [
            {"stint_number": 1, "start_lap": 1, "end_lap": 2, "driver_name": "Alice"},
            {"stint_number": 2, "start_lap": 3, "end_lap": 4, "driver_name": "Bob"},
        ]

        with patch(
            "tasks.endurance_tasks._process_single_stint",
            side_effect=SoftTimeLimitExceeded(),
        ) as mock_process:
            with pytest.raises(SoftTimeLimitExceeded):
                _run_endurance_session(_r, "job-timeout", meta, stint_configs)

        # Only the FIRST stint should have been attempted — the exception
        # must stop the loop, not let it continue to stint 2.
        assert mock_process.call_count == 1

    def test_task_level_marks_job_failed_without_reraising(self):
        """process_endurance_session must catch the propagated
        SoftTimeLimitExceeded, publish a 'failed' status with a
        customer-facing message, and return normally (not re-raise) so
        Celery acks the message instead of redelivering it."""
        from tasks.endurance_tasks import process_endurance_session

        _r = _make_mock_redis()
        with patch("redis.Redis.from_url", return_value=_r), \
             patch(
                 "tasks.endurance_tasks._run_endurance_session",
                 side_effect=SoftTimeLimitExceeded(),
             ):
            result = process_endurance_session("job-timeout-2", {"file_path": "x"}, [{"stint_number": 1}])

        assert result["failed"] is True
        assert result["error_class"] == "timeout"

        raw = _r._store.get("endurance:status:job-timeout-2")
        assert raw is not None
        payload = json.loads(raw)
        assert payload["status"] == "failed"
        assert payload["error_class"] == "timeout"
        assert "error" in payload and payload["error"]

    def test_lock_released_after_timeout_failure(self):
        from tasks.endurance_tasks import process_endurance_session

        _r = _make_mock_redis()
        with patch("redis.Redis.from_url", return_value=_r), \
             patch(
                 "tasks.endurance_tasks._run_endurance_session",
                 side_effect=SoftTimeLimitExceeded(),
             ):
            process_endurance_session("job-timeout-3", {"file_path": "x"}, [{"stint_number": 1}])

        assert "endurance:runlock:job-timeout-3" not in _r._store

    def test_lock_released_after_success(self):
        from tasks.endurance_tasks import process_endurance_session

        _r = _make_mock_redis()
        with patch("redis.Redis.from_url", return_value=_r), \
             patch(
                 "tasks.endurance_tasks._run_endurance_session",
                 return_value={"job_id": "job-ok", "stints_processed": 1, "session_id": None},
             ):
            process_endurance_session("job-ok", {"file_path": "x"}, [{"stint_number": 1}])

        assert "endurance:runlock:job-ok" not in _r._store

    def test_lock_released_on_unexpected_exception(self):
        """A non-timeout exception isn't part of this fix's contract (it
        propagates, matching prior behaviour for unhandled aggregation
        errors), but the lock must still be released so a legitimate retry
        isn't blocked forever."""
        from tasks.endurance_tasks import process_endurance_session

        _r = _make_mock_redis()
        with patch("redis.Redis.from_url", return_value=_r), \
             patch(
                 "tasks.endurance_tasks._run_endurance_session",
                 side_effect=RuntimeError("boom"),
             ):
            with pytest.raises(RuntimeError):
                process_endurance_session("job-boom", {"file_path": "x"}, [{"stint_number": 1}])

        assert "endurance:runlock:job-boom" not in _r._store

    def test_active_slot_cleared_on_unexpected_exception(self):
        """MEDIUM FIX (#B): a plain (non-SoftTimeLimitExceeded) exception
        propagating out of _run_endurance_session -- e.g. a bug in
        compute_driver_report/compute_team_report, or a ZeroDivisionError
        when total_stints==0 -- used to leak the endurance:active:{ws} slot
        forever (acks_late acks the message, so there's no redelivery to
        retry the clear, and the reconciler wouldn't self-heal it for
        _RECONCILE_CEILING_S). _clear_endurance_active must now run in the
        task's `finally`, alongside the lock release, on EVERY exit path."""
        from tasks.endurance_tasks import process_endurance_session

        workspace_id = "1"  # meta.get("workspace_id", "1") default
        _r = _make_mock_redis({f"endurance:active:{workspace_id}": {"job-boom-2"}})
        with patch("redis.Redis.from_url", return_value=_r), \
             patch(
                 "tasks.endurance_tasks._run_endurance_session",
                 side_effect=RuntimeError("boom"),
             ):
            with pytest.raises(RuntimeError):
                process_endurance_session("job-boom-2", {"file_path": "x"}, [{"stint_number": 1}])

        assert "job-boom-2" not in _r._store.get(f"endurance:active:{workspace_id}", set())
        assert "endurance:runlock:job-boom-2" not in _r._store


# ---------------------------------------------------------------------------
# (f) idempotency guard
# ---------------------------------------------------------------------------

class TestIdempotencyGuard:
    def test_duplicate_dispatch_skipped_while_lock_held(self):
        """A second concurrent run (double submit, or a broker redelivery
        while the first attempt is still legitimately running) must not
        re-enter processing."""
        from tasks.endurance_tasks import process_endurance_session

        _r = _make_mock_redis({"endurance:runlock:job-dup": "some-other-worker-request-id"})
        with patch("redis.Redis.from_url", return_value=_r), \
             patch("tasks.endurance_tasks._run_endurance_session") as mock_run:
            result = process_endurance_session("job-dup", {"file_path": "x"}, [{"stint_number": 1}])

        mock_run.assert_not_called()
        assert result["skipped"] is True
        assert result["reason"] == "duplicate_run"

    def test_redelivery_after_completion_is_skipped(self):
        """A redelivered message for a job that already finished (and whose
        run-lock from that attempt has since expired) must be a no-op, not a
        second full re-run from stint 1."""
        from tasks.endurance_tasks import process_endurance_session

        _r = _make_mock_redis({
            "endurance:status:job-done": json.dumps({"status": "completed", "job_id": "job-done"}),
        })
        with patch("redis.Redis.from_url", return_value=_r), \
             patch("tasks.endurance_tasks._run_endurance_session") as mock_run:
            result = process_endurance_session("job-done", {"file_path": "x"}, [{"stint_number": 1}])

        mock_run.assert_not_called()
        assert result["skipped"] is True
        assert result["reason"] == "already_completed"

    def test_redelivery_after_prior_failure_is_skipped(self):
        from tasks.endurance_tasks import process_endurance_session

        _r = _make_mock_redis({
            "endurance:status:job-failed-already": json.dumps({"status": "failed", "job_id": "job-failed-already"}),
        })
        with patch("redis.Redis.from_url", return_value=_r), \
             patch("tasks.endurance_tasks._run_endurance_session") as mock_run:
            result = process_endurance_session("job-failed-already", {"file_path": "x"}, [{"stint_number": 1}])

        mock_run.assert_not_called()
        assert result["reason"] == "already_failed"

    def test_fresh_job_is_not_blocked(self):
        """Sanity check: a job with no lock and no prior terminal status
        runs normally."""
        from tasks.endurance_tasks import process_endurance_session

        _r = _make_mock_redis()
        with patch("redis.Redis.from_url", return_value=_r), \
             patch(
                 "tasks.endurance_tasks._run_endurance_session",
                 return_value={"job_id": "job-fresh", "stints_processed": 1, "session_id": "s1"},
             ) as mock_run:
            result = process_endurance_session("job-fresh", {"file_path": "x"}, [{"stint_number": 1}])

        mock_run.assert_called_once()
        assert result["session_id"] == "s1"


# ---------------------------------------------------------------------------
# (e) /process route rejects over-cap / over-budget submissions
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    from flask import Flask

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True

    @flask_app.before_request
    def _fake_auth():
        g.current_user_id = 7
        g.workspace_id = 3
        g.plan_tier = "racer"

    from web.routes.endurance_upload import bp
    flask_app.register_blueprint(bp)
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


class TestSubmissionCaps:
    def test_rejects_over_cap_stint_count(self, client):
        from web.routes.endurance_upload import MAX_STINTS_PER_SUBMISSION

        stints = [
            {"stint_number": i, "start_lap": 1, "end_lap": 2, "driver_name": "A"}
            for i in range(MAX_STINTS_PER_SUBMISSION + 1)
        ]
        resp = client.post(
            "/api/v1/endurance/process",
            json={"job_id": "job-many-stints", "stints": stints},
        )
        assert resp.status_code == 400

    def test_rejects_over_cap_total_lap_count(self, client):
        from web.routes.endurance_upload import MAX_TOTAL_LAPS_PER_SUBMISSION

        # Two stints, but their combined lap range blows the total-laps cap.
        half = MAX_TOTAL_LAPS_PER_SUBMISSION // 2 + 10
        stints = [
            {"stint_number": 1, "start_lap": 1, "end_lap": half, "driver_name": "A"},
            {"stint_number": 2, "start_lap": 1, "end_lap": half, "driver_name": "B"},
        ]
        resp = client.post(
            "/api/v1/endurance/process",
            json={"job_id": "job-many-laps", "stints": stints},
        )
        assert resp.status_code == 400

    def test_allows_within_cap_stint_and_lap_counts(self, client):
        """Sanity check: a normal-sized request isn't rejected by the caps
        (it may still fail later for other reasons — job not found here —
        but must not be a 400 from the cap check)."""
        stints = [{"stint_number": 1, "start_lap": 1, "end_lap": 10, "driver_name": "A"}]
        _r = _make_mock_redis()  # no cached meta for this job_id
        with patch("redis.Redis.from_url", return_value=_r):
            resp = client.post(
                "/api/v1/endurance/process",
                json={"job_id": "job-normal", "stints": stints},
            )
        # No cached meta for this job_id, so it 404s past the cap checks —
        # proving the caps themselves did not reject it.
        assert resp.status_code == 404

    def test_rejects_over_shared_compute_budget(self, client):
        """A submission within the stint/lap caps must still be rejected
        when the shared per-tier compute budget is exhausted (fix item 4 —
        reusing check_shared_compute_budget, now actually reachable since
        the `web.db.get_conn` -> `get_db_connection` import bug is fixed)."""
        job_id = "job-over-budget"
        meta = {
            "file_path": "/data/uploads/endurance_x/f.csv",
            "workspace_id": "3",
            "session_meta": {},
        }
        stints = [{"stint_number": 1, "start_lap": 1, "end_lap": 5, "driver_name": "A"}]

        _r = _make_mock_redis({f"endurance:meta:{job_id}": json.dumps(meta)})

        with patch("redis.Redis.from_url", return_value=_r), \
             patch("web.db.get_db_connection", return_value=MagicMock()), \
             patch(
                 "web.compute_budget.check_shared_compute_budget",
                 return_value=(False, {"running_jobs": 2, "max_jobs": 2}),
             ), \
             patch("tasks.endurance_tasks.process_endurance_session.delay") as mock_delay:
            resp = client.post(
                "/api/v1/endurance/process",
                json={"job_id": job_id, "stints": stints},
            )

        assert resp.status_code == 429
        mock_delay.assert_not_called()

    def test_dispatches_when_budget_allows(self, client):
        """Happy path: under both the size caps and the shared budget, the
        route dispatches the (now-isolated) endurance task."""
        job_id = "job-under-budget"
        meta = {
            "file_path": "/data/uploads/endurance_y/f.csv",
            "workspace_id": "3",
            "session_meta": {},
        }
        stints = [{"stint_number": 1, "start_lap": 1, "end_lap": 5, "driver_name": "A"}]

        _r = _make_mock_redis({f"endurance:meta:{job_id}": json.dumps(meta)})

        with patch("redis.Redis.from_url", return_value=_r), \
             patch("web.db.get_db_connection", return_value=MagicMock()), \
             patch(
                 "web.compute_budget.check_shared_compute_budget",
                 return_value=(True, {"running_jobs": 0, "max_jobs": 2}),
             ), \
             patch("tasks.endurance_tasks.process_endurance_session.delay") as mock_delay:
            resp = client.post(
                "/api/v1/endurance/process",
                json={"job_id": job_id, "stints": stints},
            )

        assert resp.status_code == 200
        mock_delay.assert_called_once_with(job_id, meta, stints)
