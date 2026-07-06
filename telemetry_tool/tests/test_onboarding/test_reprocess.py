"""Test onboarding/reprocess.py (Task 9): F3/F4 upgrade path after a bless.

Everything here is mocked -- the real ``build_pipeline_chain``/
``PipelineContext``/redis wiring inside ``_dispatch_build_reprocess`` needs a
live Celery broker + Postgres + Redis to exercise meaningfully, none of which
exist in this environment (see the task-09 report for what's deferred to the
deploy gate). Tests instead:

  * mock ``reprocess._dispatch_build_reprocess`` wholesale -- the "build
    entrypoint" ``reprocess_after_bless`` calls once per session_ref -- and
    assert call count/args/exception-swallowing at that boundary.
  * mock ``reprocess.compute_racing_lines`` (the real Celery task object) and
    assert dedup + delay on ``.apply_async``.
  * use a capturing fake connection (same pattern as
    ``tests/test_onboarding/test_repo.py``) to assert the exact canonical_id
    UPDATE SQL/params without a real Postgres.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from telemetry_tool.onboarding import reprocess  # noqa: E402

_TRACK_KEY = "T1_reprocess_test"
_CANONICAL_ID = "kct"


# ---------------------------------------------------------------------------
# Capturing fake connection (no PG needed) -- mirrors test_repo.py.
# ---------------------------------------------------------------------------
class _FakeCursor:
    def __init__(self, sink: list, fetchone_queue: list):
        self._sink = sink
        self._fetchone_queue = fetchone_queue

    def execute(self, sql, params=None):
        self._sink.append((sql, params))

    def fetchone(self):
        if self._fetchone_queue:
            return self._fetchone_queue.pop(0)
        return None

    def close(self):
        pass


class _FakeConn:
    """``fetchone_results`` is a shared FIFO queue: each SELECT (only SELECTs
    call ``fetchone()`` -- the UPDATE never does) pops the next entry, in the
    order the code issues them.
    """

    def __init__(self, fetchone_results: list | None = None):
        self.calls: list = []
        self.commits = 0
        self._fetchone_results = list(fetchone_results or [])

    def cursor(self, *a, **k):
        return _FakeCursor(self.calls, self._fetchone_results)

    def commit(self):
        self.commits += 1


def _updates(conn: _FakeConn) -> list[tuple[str, dict]]:
    return [(sql, params) for sql, params in conn.calls if sql.strip().startswith("UPDATE")]


def _selects(conn: _FakeConn) -> list[tuple[str, dict]]:
    return [(sql, params) for sql, params in conn.calls if sql.strip().startswith("SELECT")]


# ---------------------------------------------------------------------------
# F4 -- canonical_id mapping
# ---------------------------------------------------------------------------


def test_canonical_id_set_once_per_session(monkeypatch):
    """Two sessions, two distinct tracks -- one UPDATE per session's track,
    with the correct (canonical_id, track_id) params.
    """
    monkeypatch.setattr(reprocess, "_dispatch_build_reprocess", MagicMock())
    monkeypatch.setattr(reprocess, "compute_racing_lines", MagicMock())

    conn = _FakeConn(fetchone_results=[{"track_id": "trk-1"}, {"track_id": "trk-2"}])

    reprocess.reprocess_after_bless(
        track_key=_TRACK_KEY,
        canonical_id=_CANONICAL_ID,
        session_refs=["sess-1", "sess-2"],
        vehicle_classes=["gt3"],
        conn=conn,
    )

    updates = _updates(conn)
    assert len(updates) == 2
    params_by_track = {p["track_id"]: p for _, p in updates}
    assert params_by_track["trk-1"]["canonical_id"] == _CANONICAL_ID
    assert params_by_track["trk-2"]["canonical_id"] == _CANONICAL_ID
    # One commit per successful UPDATE.
    assert conn.commits == 2


def test_canonical_id_mapping_skips_session_with_no_track_id(monkeypatch):
    monkeypatch.setattr(reprocess, "_dispatch_build_reprocess", MagicMock())
    monkeypatch.setattr(reprocess, "compute_racing_lines", MagicMock())

    conn = _FakeConn(fetchone_results=[None])

    reprocess.reprocess_after_bless(
        track_key=_TRACK_KEY,
        canonical_id=_CANONICAL_ID,
        session_refs=["sess-unknown"],
        vehicle_classes=["gt3"],
        conn=conn,
    )

    assert _updates(conn) == []
    assert conn.commits == 0


def test_canonical_id_mapping_exception_swallowed_remaining_sessions_processed(monkeypatch):
    """A resolve/UPDATE failure for one session must not stop the others."""
    monkeypatch.setattr(reprocess, "_dispatch_build_reprocess", MagicMock())
    monkeypatch.setattr(reprocess, "compute_racing_lines", MagicMock())

    class _BoomCursor(_FakeCursor):
        def execute(self, sql, params=None):
            if sql.strip().startswith("SELECT"):
                raise RuntimeError("db exploded")
            super().execute(sql, params)

    class _BoomOnceConn(_FakeConn):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._first = True

        def cursor(self, *a, **k):
            if self._first:
                self._first = False
                return _BoomCursor(self.calls, self._fetchone_results)
            return _FakeCursor(self.calls, self._fetchone_results)

    conn = _BoomOnceConn(fetchone_results=[{"track_id": "trk-2"}])

    reprocess.reprocess_after_bless(
        track_key=_TRACK_KEY,
        canonical_id=_CANONICAL_ID,
        session_refs=["sess-boom", "sess-2"],
        vehicle_classes=["gt3"],
        conn=conn,
    )

    updates = _updates(conn)
    assert len(updates) == 1
    assert updates[0][1]["track_id"] == "trk-2"


# ---------------------------------------------------------------------------
# F3 -- build-reprocess dispatch
# ---------------------------------------------------------------------------


def test_build_reprocess_enqueued_once_per_session(monkeypatch):
    dispatch = MagicMock()
    monkeypatch.setattr(reprocess, "_dispatch_build_reprocess", dispatch)
    monkeypatch.setattr(reprocess, "compute_racing_lines", MagicMock())

    conn = _FakeConn(fetchone_results=[None, None, None])

    reprocess.reprocess_after_bless(
        track_key=_TRACK_KEY,
        canonical_id=_CANONICAL_ID,
        session_refs=["sess-1", "sess-2", "sess-3"],
        vehicle_classes=["gt3"],
        conn=conn,
    )

    assert dispatch.call_count == 3
    dispatch.assert_has_calls(
        [call(conn, "sess-1"), call(conn, "sess-2"), call(conn, "sess-3")]
    )


def test_build_reprocess_exception_swallowed_remaining_sessions_processed(monkeypatch):
    dispatch = MagicMock(side_effect=[RuntimeError("celery broker down"), None, None])
    monkeypatch.setattr(reprocess, "_dispatch_build_reprocess", dispatch)
    monkeypatch.setattr(reprocess, "compute_racing_lines", MagicMock())

    conn = _FakeConn(fetchone_results=[None, None, None])

    reprocess.reprocess_after_bless(
        track_key=_TRACK_KEY,
        canonical_id=_CANONICAL_ID,
        session_refs=["sess-1", "sess-2", "sess-3"],
        vehicle_classes=["gt3"],
        conn=conn,
    )

    # All three sessions attempted despite the first raising.
    assert dispatch.call_count == 3


# ---------------------------------------------------------------------------
# Racing lines -- dedup + delay
# ---------------------------------------------------------------------------


def test_compute_racing_lines_deduped_per_track_and_class(monkeypatch):
    monkeypatch.setattr(reprocess, "_dispatch_build_reprocess", MagicMock())
    fake_rl = MagicMock()
    monkeypatch.setattr(reprocess, "compute_racing_lines", fake_rl)

    conn = _FakeConn(fetchone_results=[None, None])

    reprocess.reprocess_after_bless(
        track_key=_TRACK_KEY,
        canonical_id=_CANONICAL_ID,
        # 3 sessions worth of vehicle classes but only 2 distinct classes.
        session_refs=["sess-1", "sess-2"],
        vehicle_classes=["gt3", "gt3", "gt4"],
        conn=conn,
    )

    assert fake_rl.apply_async.call_count == 2
    fake_rl.apply_async.assert_any_call(
        (_TRACK_KEY, "gt3"), countdown=reprocess._RACING_LINE_REPROCESS_DELAY_S
    )
    fake_rl.apply_async.assert_any_call(
        (_TRACK_KEY, "gt4"), countdown=reprocess._RACING_LINE_REPROCESS_DELAY_S
    )


def test_compute_racing_lines_exception_swallowed_remaining_classes_processed(monkeypatch):
    monkeypatch.setattr(reprocess, "_dispatch_build_reprocess", MagicMock())
    fake_rl = MagicMock()
    fake_rl.apply_async.side_effect = [RuntimeError("broker down"), None]
    monkeypatch.setattr(reprocess, "compute_racing_lines", fake_rl)

    conn = _FakeConn(fetchone_results=[None])

    reprocess.reprocess_after_bless(
        track_key=_TRACK_KEY,
        canonical_id=_CANONICAL_ID,
        session_refs=["sess-1"],
        vehicle_classes=["gt3", "gt4"],
        conn=conn,
    )

    # Both classes attempted despite the first enqueue raising.
    assert fake_rl.apply_async.call_count == 2


# ---------------------------------------------------------------------------
# conn=None default path -- opens + returns its own connection.
# ---------------------------------------------------------------------------


def test_default_conn_uses_maint_connection_helpers(monkeypatch):
    conn = _FakeConn(fetchone_results=[None])
    get_maint = MagicMock(return_value=conn)
    return_conn = MagicMock()
    monkeypatch.setattr(reprocess, "get_maint_connection", get_maint)
    monkeypatch.setattr(reprocess, "return_pg_connection", return_conn)
    monkeypatch.setattr(reprocess, "_dispatch_build_reprocess", MagicMock())
    monkeypatch.setattr(reprocess, "compute_racing_lines", MagicMock())

    reprocess.reprocess_after_bless(
        track_key=_TRACK_KEY,
        canonical_id=_CANONICAL_ID,
        session_refs=["sess-1"],
        vehicle_classes=["gt3"],
    )

    get_maint.assert_called_once()
    return_conn.assert_called_once_with(conn)


def test_caller_supplied_conn_is_never_returned(monkeypatch):
    """A caller-supplied conn is not owned by this function -- it must never
    be passed to return_pg_connection."""
    return_conn = MagicMock()
    monkeypatch.setattr(reprocess, "return_pg_connection", return_conn)
    monkeypatch.setattr(reprocess, "_dispatch_build_reprocess", MagicMock())
    monkeypatch.setattr(reprocess, "compute_racing_lines", MagicMock())

    conn = _FakeConn(fetchone_results=[None])

    reprocess.reprocess_after_bless(
        track_key=_TRACK_KEY,
        canonical_id=_CANONICAL_ID,
        session_refs=["sess-1"],
        vehicle_classes=["gt3"],
        conn=conn,
    )

    return_conn.assert_not_called()
