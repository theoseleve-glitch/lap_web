"""Tests for the customer-readiness follow-up fixes #2/#4/#6.

Root cause (2c5f508 follow-up): isolating endurance jobs onto their own
Celery queue moved ALL of their state into Redis-only bookkeeping, silently
defeating three separate PG-backed safety nets:

  #2 (BLOCKER) web.compute_budget only scans ingestion_jobs/exports/
     analysis_runs, so endurance jobs were invisible to the shared per-tier
     concurrency cap -- a racer-tier user could fire unlimited concurrent
     /endurance/process submissions at the single --concurrency=1 endurance
     worker.
  #4 a hard-killed endurance job (Celery's own time_limit SIGKILLs the
     worker child) never runs `finally: _release_job_lock` -- there is no
     endurance analogue of alerting_tasks._reconcile_stuck_jobs to un-stick
     it, so the job stays non-terminal and its run-lock stays held forever.
  #6 with task_reject_on_worker_lost + acks_late, that same hard-killed
     message gets requeued by the broker. `self.request.id` is unchanged
     across redeliveries of ONE message, so the re-entrant lock re-grants
     immediately and the job loops forever, pinning the sole worker.

Unlike tests/test_endurance_isolation.py::TestSubmissionCaps (which mocks
web.compute_budget.check_shared_compute_budget's RETURN VALUE and therefore
asserts nothing about the counting logic itself), the tests below exercise
the REAL counting path end-to-end.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from web.compute_budget import (  # noqa: E402
    check_shared_compute_budget,
    count_active_compute_jobs,
    count_active_endurance_jobs,
)


# ---------------------------------------------------------------------------
# Shared mock-Redis helper (same shape as tests/test_endurance_isolation.py's
# _make_mock_redis, duplicated here so this file stays self-contained) plus
# the fake PG connection convention from tests/test_shared_compute_budget.py.
# ---------------------------------------------------------------------------


def _make_mock_redis(initial: dict | None = None):
    store: dict = dict(initial or {})
    mock = MagicMock()

    def _lua_handler(script, numkeys, *args):
        key = args[0]
        value = args[1] if len(args) > 1 else None
        if "set" in script and "expire" in script:
            current = store.get(key)
            if current is None:
                store[key] = value
                return 1
            elif current == value:
                return 1
            return 0
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


class _FakeConn:
    """Minimal PG conn double -- mirrors tests/test_shared_compute_budget.py."""

    def __init__(self, counts=None, missing=()):
        self.counts = dict(counts or {})
        self.missing = set(missing)
        self._pending = {"cnt": 0}

    def execute(self, sql, params=None):
        s = str(sql).strip()
        if s.split(" ", 1)[0] in ("SAVEPOINT", "RELEASE", "ROLLBACK"):
            return self
        for table in self.missing:
            if f"FROM {table} " in s:
                raise RuntimeError(f'relation "{table}" does not exist')
        row = {"cnt": 0}
        for table, c in self.counts.items():
            if f"FROM {table} " in s:
                row = {"cnt": c}
        self._pending = row
        return self

    def fetchone(self):
        return self._pending


class _FakeRedisScard:
    """Bare-minimum redis double exposing only .scard, for unit-level tests."""

    def __init__(self, counts: dict[str, int]):
        self.counts = counts

    def scard(self, key):
        return self.counts.get(key, 0)


# ---------------------------------------------------------------------------
# Fix #2: endurance jobs must be COUNTABLE toward the shared compute budget.
# ---------------------------------------------------------------------------


class TestComputeBudgetEnduranceSignal:
    def test_count_active_endurance_jobs_reads_scard(self):
        r = _FakeRedisScard({"endurance:active:9": 3})
        assert count_active_endurance_jobs(r, workspace_id=9) == 3
        assert count_active_endurance_jobs(r, workspace_id=1) == 0

    def test_count_active_endurance_jobs_fails_open_without_client(self):
        assert count_active_endurance_jobs(None, workspace_id=9) == 0

    def test_count_active_endurance_jobs_fails_open_on_redis_error(self):
        class _Boom:
            def scard(self, key):
                raise ConnectionError("redis down")

        assert count_active_endurance_jobs(_Boom(), workspace_id=9) == 0

    def test_count_active_compute_jobs_sums_pg_and_endurance(self):
        conn = _FakeConn({"ingestion_jobs": 1, "exports": 1})
        r = _FakeRedisScard({"endurance:active:9": 2})
        total = count_active_compute_jobs(conn, workspace_id=9, redis_client=r)
        assert total == 4  # 1 + 1 + 0 (analysis_runs) + 2 (endurance)

    def test_count_active_compute_jobs_without_redis_client_is_unaffected(self):
        """Regression guard: omitting redis_client behaves exactly as before
        this fix -- no endurance contribution, no crash."""
        conn = _FakeConn({"ingestion_jobs": 2, "exports": 1, "analysis_runs": 3})
        assert count_active_compute_jobs(conn, workspace_id=1) == 6

    def test_check_shared_compute_budget_denies_when_endurance_alone_fills_pool(self):
        """Racer tier max=2; zero PG jobs but 2 endurance jobs already
        active -- must deny. This is exactly the BLOCKER scenario: a
        racer-tier user spamming /endurance/process must be capped even
        though endurance writes no ingestion_jobs/exports/analysis_runs row."""
        conn = _FakeConn({})
        r = _FakeRedisScard({"endurance:active:9": 2})
        allowed, info = check_shared_compute_budget(
            conn, user_id=1, workspace_id=9, plan_tier="racer", redis_client=r,
        )
        assert allowed is False
        assert info["running_jobs"] == 2
        assert info["max_jobs"] == 2

    def test_check_shared_compute_budget_allows_when_endurance_under_cap(self):
        conn = _FakeConn({})
        r = _FakeRedisScard({"endurance:active:9": 1})
        allowed, info = check_shared_compute_budget(
            conn, user_id=1, workspace_id=9, plan_tier="racer", redis_client=r,
        )
        assert allowed is True
        assert info["running_jobs"] == 1

    def test_check_shared_compute_budget_combines_pg_and_endurance_sources(self):
        """1 analysis_runs job AND 1 endurance job on racer tier (max=2) is
        already at the cap -- the two pools must combine, not be checked
        independently."""
        conn = _FakeConn({"analysis_runs": 1})
        r = _FakeRedisScard({"endurance:active:9": 1})
        allowed, info = check_shared_compute_budget(
            conn, user_id=1, workspace_id=9, plan_tier="racer", redis_client=r,
        )
        assert allowed is False
        assert info["running_jobs"] == 2


class TestMarkEnduranceDispatched:
    def test_sadds_active_set_and_writes_dispatch_record(self):
        from tasks.endurance_tasks import mark_endurance_dispatched

        _r = _make_mock_redis()
        mark_endurance_dispatched(_r, "job-x", "2")

        assert _r._store["endurance:active:2"] == {"job-x"}
        record = json.loads(_r._store["endurance:dispatch:job-x"])
        assert record["workspace_id"] == "2"
        assert isinstance(record["dispatched_at"], (int, float))


class TestMarkEnduranceStarted:
    """HIGH FIX: the run-start marker the reconciler now ages jobs against."""

    def test_writes_started_timestamp(self):
        from tasks.endurance_tasks import mark_endurance_started

        _r = _make_mock_redis()
        before = time.time()
        mark_endurance_started(_r, "job-y")
        after = time.time()

        raw = _r._store["endurance:started:job-y"]
        assert before <= float(raw) <= after


class TestEnduranceProcessRouteRealConcurrencyCap:
    """Fix #2's route-level enforcement, exercised through the REAL counting
    path (check_shared_compute_budget is NOT mocked here) -- this is the
    replacement for test_endurance_isolation.py::TestSubmissionCaps's
    over-budget tests, which only asserted the route's wiring against a
    hand-fed mocked return value."""

    @staticmethod
    def _make_client():
        from flask import Flask, g
        from web.routes.endurance_upload import bp

        app = Flask(__name__)
        app.config["TESTING"] = True

        @app.before_request
        def _fake_auth():
            g.current_user_id = 7
            g.workspace_id = 9
            g.plan_tier = "racer"  # max_concurrent_jobs = 2

        app.register_blueprint(bp)
        return app.test_client()

    @staticmethod
    def _submit(client, redis_mock, job_id):
        meta = {"file_path": "/x.csv", "workspace_id": "9", "session_meta": {}}
        redis_mock._store[f"endurance:meta:{job_id}"] = json.dumps(meta)
        stints = [{"stint_number": 1, "start_lap": 1, "end_lap": 5, "driver_name": "A"}]
        with patch("redis.Redis.from_url", return_value=redis_mock), \
             patch("web.db.get_db_connection", return_value=_FakeConn({})), \
             patch("tasks.endurance_tasks.process_endurance_session.delay") as mock_delay:
            resp = client.post(
                "/api/v1/endurance/process",
                json={"job_id": job_id, "stints": stints},
            )
        return resp, mock_delay

    def test_third_concurrent_submission_is_rejected_by_real_redis_count(self):
        client = self._make_client()
        _r = _make_mock_redis()

        resp1, delay1 = self._submit(client, _r, "job-a")
        assert resp1.status_code == 200
        delay1.assert_called_once()

        resp2, delay2 = self._submit(client, _r, "job-b")
        assert resp2.status_code == 200
        delay2.assert_called_once()

        # Two jobs are now active in endurance:active:9 (real SADDs from
        # mark_endurance_dispatched on the two successful dispatches above) --
        # racer tier's max_concurrent_jobs=2 pool is now full.
        assert _r._store["endurance:active:9"] == {"job-a", "job-b"}

        resp3, delay3 = self._submit(client, _r, "job-c")
        assert resp3.status_code == 429
        delay3.assert_not_called()
        assert "job-c" not in _r._store["endurance:active:9"]

    def test_completed_job_frees_a_concurrency_slot(self):
        """The signal is not monotonically increasing -- clearing an active
        job (as tasks.endurance_tasks._clear_endurance_active does on every
        terminal transition) frees the slot for a new submission."""
        client = self._make_client()
        _r = _make_mock_redis()

        assert self._submit(client, _r, "job-1")[0].status_code == 200
        assert self._submit(client, _r, "job-2")[0].status_code == 200
        assert self._submit(client, _r, "job-3")[0].status_code == 429  # pool full

        from tasks.endurance_tasks import _clear_endurance_active
        _clear_endurance_active(_r, "job-1", "9")  # e.g. job-1 completed

        resp4, delay4 = self._submit(client, _r, "job-3")
        assert resp4.status_code == 200
        delay4.assert_called_once()


# ---------------------------------------------------------------------------
# Fix #4: stuck-job reconciler for endurance (mirrors
# alerting_tasks._reconcile_stuck_jobs, but Redis-keyed).
# ---------------------------------------------------------------------------


class TestReconcileStuckEnduranceJobs:
    def test_stale_non_terminal_job_marked_failed_and_lock_released(self):
        """A job that ACTUALLY STARTED and has been running past the
        ceiling (endurance:started present and stale) is force-failed."""
        from tasks.endurance_tasks import _RECONCILE_CEILING_S, reconcile_stuck_endurance_jobs

        _r = _make_mock_redis()
        job_id = "job-stale"
        workspace_id = "4"
        stale_ts = time.time() - (_RECONCILE_CEILING_S + 60)
        _r._store[f"endurance:active:{workspace_id}"] = {job_id}
        _r._store[f"endurance:dispatch:{job_id}"] = json.dumps(
            {"workspace_id": workspace_id, "dispatched_at": stale_ts}
        )
        _r._store[f"endurance:started:{job_id}"] = stale_ts
        _r._store[f"endurance:status:{job_id}"] = json.dumps({"status": "processing_stint"})
        # Simulates the SIGKILL: `finally: _release_job_lock` never ran, so
        # the dead worker's run-lock is still held.
        _r._store[f"endurance:runlock:{job_id}"] = "dead-worker-request-id"

        reconciled = reconcile_stuck_endurance_jobs(_r)

        assert [rec["job_id"] for rec in reconciled] == [job_id]
        status = json.loads(_r._store[f"endurance:status:{job_id}"])
        assert status["status"] == "failed"
        assert status["error_class"] == "reconciled_stuck"
        assert f"endurance:runlock:{job_id}" not in _r._store
        assert job_id not in _r._store.get(f"endurance:active:{workspace_id}", set())
        assert f"endurance:dispatch:{job_id}" not in _r._store

    def test_fresh_in_flight_job_is_left_alone(self):
        """A job that started recently (started marker present, not yet past
        the ceiling) is left running."""
        from tasks.endurance_tasks import reconcile_stuck_endurance_jobs

        _r = _make_mock_redis()
        job_id = "job-fresh"
        workspace_id = "4"
        _r._store[f"endurance:active:{workspace_id}"] = {job_id}
        _r._store[f"endurance:dispatch:{job_id}"] = json.dumps(
            {"workspace_id": workspace_id, "dispatched_at": time.time()}
        )
        _r._store[f"endurance:started:{job_id}"] = time.time()
        _r._store[f"endurance:status:{job_id}"] = json.dumps({"status": "processing_stint"})
        _r._store[f"endurance:runlock:{job_id}"] = "live-worker-request-id"

        reconciled = reconcile_stuck_endurance_jobs(_r)

        assert reconciled == []
        assert json.loads(_r._store[f"endurance:status:{job_id}"])["status"] == "processing_stint"
        assert _r._store[f"endurance:runlock:{job_id}"] == "live-worker-request-id"
        assert job_id in _r._store[f"endurance:active:{workspace_id}"]

    def test_already_terminal_job_bookkeeping_cleared_without_double_publish(self):
        """A job that reached 'completed' through the normal success path,
        whose dispatch record hasn't expired yet, must NOT be re-published as
        failed -- the sweep only clears its leftover active-set/dispatch
        bookkeeping."""
        from tasks.endurance_tasks import _RECONCILE_CEILING_S, reconcile_stuck_endurance_jobs

        _r = _make_mock_redis()
        job_id = "job-done-already"
        workspace_id = "4"
        stale_ts = time.time() - (_RECONCILE_CEILING_S + 60)
        _r._store[f"endurance:active:{workspace_id}"] = {job_id}  # not yet cleared
        _r._store[f"endurance:dispatch:{job_id}"] = json.dumps(
            {"workspace_id": workspace_id, "dispatched_at": stale_ts}
        )
        _r._store[f"endurance:started:{job_id}"] = stale_ts
        _r._store[f"endurance:status:{job_id}"] = json.dumps({
            "status": "completed", "job_id": job_id, "session_id": "s1",
        })

        reconciled = reconcile_stuck_endurance_jobs(_r)

        assert reconciled == []  # not counted as a reconciled FAILURE
        status = json.loads(_r._store[f"endurance:status:{job_id}"])
        assert status["status"] == "completed"  # untouched
        assert status["session_id"] == "s1"
        assert job_id not in _r._store.get(f"endurance:active:{workspace_id}", set())

    def test_queued_not_started_past_old_ceiling_is_not_touched(self):
        """HIGH FIX (merge-blocker): a job that has been QUEUED (dispatched)
        behind another long-running job on the single-concurrency endurance
        worker for well past the OLD enqueue-based ceiling, but has NOT yet
        acquired its run-lock and started executing (no endurance:started
        marker), must NEVER be force-failed, have its run-lock released, or
        have its active-set slot cleared. Ageing off dispatched_at alone (the
        pre-fix behaviour) would have force-failed this perfectly healthy,
        still-queued job."""
        from tasks.endurance_tasks import _RECONCILE_CEILING_S, reconcile_stuck_endurance_jobs

        _r = _make_mock_redis()
        job_id = "job-queued-long"
        workspace_id = "6"
        # Dispatched WAY past the old ceiling (e.g. queued ~65min behind a
        # long job A on a single-concurrency worker) -- but never started.
        very_old_dispatch = time.time() - (_RECONCILE_CEILING_S + 3600)
        _r._store[f"endurance:active:{workspace_id}"] = {job_id}
        _r._store[f"endurance:dispatch:{job_id}"] = json.dumps(
            {"workspace_id": workspace_id, "dispatched_at": very_old_dispatch}
        )
        _r._store[f"endurance:status:{job_id}"] = json.dumps({
            "status": "queued", "total_stints": 3,
        })
        # No endurance:started:{job_id} key -- this job has not started yet.
        # No endurance:runlock:{job_id} key -- nothing has acquired it yet.

        reconciled = reconcile_stuck_endurance_jobs(_r)

        assert reconciled == []
        assert json.loads(_r._store[f"endurance:status:{job_id}"])["status"] == "queued"
        assert job_id in _r._store[f"endurance:active:{workspace_id}"]
        assert f"endurance:dispatch:{job_id}" in _r._store
        assert f"endurance:runlock:{job_id}" not in _r._store


# ---------------------------------------------------------------------------
# Fix #6: bound broker redeliveries by job_id (independent of the Celery
# message id, which is unchanged across redeliveries of one message).
# ---------------------------------------------------------------------------


class TestRedeliveryAttemptsBound:
    def test_nth_redelivery_marks_failed_and_acks_without_rerunning(self):
        from tasks.endurance_tasks import ENDURANCE_MAX_DELIVERY_ATTEMPTS, process_endurance_session

        _r = _make_mock_redis()
        job_id = "job-redelivered"
        workspace_id = "1"
        _r._store[f"endurance:active:{workspace_id}"] = {job_id}
        # Simulate ENDURANCE_MAX_DELIVERY_ATTEMPTS prior deliveries already
        # having incremented the counter -- this call is the NEXT delivery.
        _r._store[f"endurance:attempts:{job_id}"] = ENDURANCE_MAX_DELIVERY_ATTEMPTS
        meta = {"file_path": "x", "workspace_id": workspace_id}

        with patch("redis.Redis.from_url", return_value=_r), \
             patch("tasks.endurance_tasks._run_endurance_session") as mock_run:
            result = process_endurance_session(job_id, meta, [{"stint_number": 1}])

        mock_run.assert_not_called()
        assert result["failed"] is True
        assert result["error_class"] == "redelivery_exhausted"
        assert result["attempts"] == ENDURANCE_MAX_DELIVERY_ATTEMPTS + 1
        status = json.loads(_r._store[f"endurance:status:{job_id}"])
        assert status["status"] == "failed"
        assert job_id not in _r._store.get(f"endurance:active:{workspace_id}", set())
        # This delivery never actually held the run-lock -- the force-release
        # must still be a safe no-op (key simply absent).
        assert f"endurance:runlock:{job_id}" not in _r._store

    def test_nth_redelivery_does_not_relabel_an_already_reconciled_stuck_job(self):
        """LOW FIX (#G): if the job was already force-failed by the
        reconciler (status='failed', error_class='reconciled_stuck') BEFORE
        this Nth redelivery arrives, the redelivery-exhausted gate must NOT
        overwrite that more specific, already-correct terminal status with
        the less informative 'redelivery_exhausted' label."""
        from tasks.endurance_tasks import ENDURANCE_MAX_DELIVERY_ATTEMPTS, process_endurance_session

        _r = _make_mock_redis()
        job_id = "job-already-reconciled"
        workspace_id = "1"
        _r._store[f"endurance:attempts:{job_id}"] = ENDURANCE_MAX_DELIVERY_ATTEMPTS
        _r._store[f"endurance:status:{job_id}"] = json.dumps({
            "status": "failed", "job_id": job_id, "error_class": "reconciled_stuck",
        })
        meta = {"file_path": "x", "workspace_id": workspace_id}

        with patch("redis.Redis.from_url", return_value=_r), \
             patch("tasks.endurance_tasks._run_endurance_session") as mock_run:
            result = process_endurance_session(job_id, meta, [{"stint_number": 1}])

        mock_run.assert_not_called()
        assert result["skipped"] is True
        assert result["reason"] == "already_failed"
        status = json.loads(_r._store[f"endurance:status:{job_id}"])
        # Unchanged -- NOT relabeled as redelivery_exhausted.
        assert status["status"] == "failed"
        assert status["error_class"] == "reconciled_stuck"

    def test_attempts_within_bound_still_runs_normally(self):
        from tasks.endurance_tasks import process_endurance_session

        _r = _make_mock_redis()
        job_id = "job-first-attempt"
        meta = {"file_path": "x", "workspace_id": "1"}

        with patch("redis.Redis.from_url", return_value=_r), \
             patch(
                 "tasks.endurance_tasks._run_endurance_session",
                 return_value={"job_id": job_id, "stints_processed": 1, "session_id": "s9"},
             ) as mock_run:
            result = process_endurance_session(job_id, meta, [{"stint_number": 1}])

        mock_run.assert_called_once()
        assert result["session_id"] == "s9"
        assert _r._store[f"endurance:attempts:{job_id}"] == 1

    def test_attempts_counter_increments_across_simulated_redeliveries(self):
        """Two legitimate redeliveries (attempts 1 and 2, both <= the bound)
        must still be allowed to run -- only the delivery that pushes the
        counter PAST the bound is stopped (exercised separately above)."""
        from tasks.endurance_tasks import ENDURANCE_MAX_DELIVERY_ATTEMPTS, process_endurance_session

        _r = _make_mock_redis()
        job_id = "job-retried-twice"
        meta = {"file_path": "x", "workspace_id": "1"}

        with patch("redis.Redis.from_url", return_value=_r), \
             patch(
                 "tasks.endurance_tasks._run_endurance_session",
                 side_effect=[
                     {"job_id": job_id, "stints_processed": 1, "session_id": None},
                     {"job_id": job_id, "stints_processed": 1, "session_id": None},
                 ],
             ) as mock_run:
            process_endurance_session(job_id, dict(meta), [{"stint_number": 1}])
            process_endurance_session(job_id, dict(meta), [{"stint_number": 1}])

        assert mock_run.call_count == 2
        assert _r._store[f"endurance:attempts:{job_id}"] == 2
        assert 2 <= ENDURANCE_MAX_DELIVERY_ATTEMPTS


# ---------------------------------------------------------------------------
# Cross-check: the three fixes must share ONE notion of endurance job
# identity/state, not create competing stores.
# ---------------------------------------------------------------------------


class TestCrossFixComposition:
    def test_reconciled_job_late_redelivery_is_skipped_not_rerun_or_double_failed(self):
        """After the reconciler (#4) force-fails a stuck job and releases its
        lock, a LATE broker redelivery of the SAME message (fix #6's
        territory) must hit the PRE-EXISTING terminal-status skip -- not
        re-run _run_endurance_session, and not publish a second, different
        failure payload. All three fixes read/write the SAME
        endurance:status / endurance:runlock / endurance:active state
        instead of independent stores."""
        from tasks.endurance_tasks import (
            _RECONCILE_CEILING_S,
            process_endurance_session,
            reconcile_stuck_endurance_jobs,
        )

        _r = _make_mock_redis()
        job_id = "job-composed"
        workspace_id = "5"
        stale_ts = time.time() - (_RECONCILE_CEILING_S + 60)
        _r._store[f"endurance:active:{workspace_id}"] = {job_id}
        _r._store[f"endurance:dispatch:{job_id}"] = json.dumps(
            {"workspace_id": workspace_id, "dispatched_at": stale_ts}
        )
        _r._store[f"endurance:started:{job_id}"] = stale_ts
        _r._store[f"endurance:status:{job_id}"] = json.dumps({"status": "processing_stint"})
        _r._store[f"endurance:runlock:{job_id}"] = "dead-worker-request-id"

        reconciled = reconcile_stuck_endurance_jobs(_r)
        assert len(reconciled) == 1
        assert job_id not in _r._store.get(f"endurance:active:{workspace_id}", set())

        # The broker now redelivers the SAME message (task_reject_on_worker_lost).
        meta = {"file_path": "x", "workspace_id": workspace_id}
        with patch("redis.Redis.from_url", return_value=_r), \
             patch("tasks.endurance_tasks._run_endurance_session") as mock_run:
            result = process_endurance_session(job_id, meta, [{"stint_number": 1}])

        mock_run.assert_not_called()
        assert result["skipped"] is True
        assert result["reason"] == "already_failed"
        status = json.loads(_r._store[f"endurance:status:{job_id}"])
        # Unchanged -- the redelivery did not clobber it with a second,
        # different failure payload (e.g. "redelivery_exhausted").
        assert status["status"] == "failed"
        assert status["error_class"] == "reconciled_stuck"
