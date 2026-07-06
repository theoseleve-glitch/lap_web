"""Test onboarding/repo.py (Task 4): atomic-upsert dedup + conditional writes.

Two families, mirroring test_racing_line_repo.py:
  * capturing-cursor tests (RUN everywhere, no PG needed) -- assert the exact
    SQL shape + params via a fake connection that records every execute()
    call. The dedup race can't be exercised without real Postgres (it relies
    on the ON CONFLICT arbiter + the partial unique index from migration
    081), so these are the load-bearing tests in this environment.
  * real-PG tests (``@_skip_no_pg``) -- skip automatically when
    TELEMETRY_PG_URL is unset (no local PG in dev). Exercise the actual
    dedup/idempotency behaviour against a scratch table.
"""
import json
import os
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from telemetry_tool.onboarding import repo  # noqa: E402

_pg_url = os.environ.get("TELEMETRY_PG_URL", "")
_skip_no_pg = pytest.mark.skipif(
    not _pg_url,
    reason="TELEMETRY_PG_URL not set -- skipping PostgreSQL onboarding repo test",
)

_TEST_TRACK_KEY = "T1_onboarding_repo_test"


# ---------------------------------------------------------------------------
# Capturing fake connection that records the SQL + params (no PG needed).
# ---------------------------------------------------------------------------
class _CapturingCursor:
    def __init__(self, sink, fetchone_result=None, rowcount=1, fetchall_result=None):
        self._sink = sink
        self._fetchone_result = fetchone_result
        self.rowcount = rowcount
        self._fetchall_result = fetchall_result if fetchall_result is not None else []

    def execute(self, sql, params=None):
        self._sink.append((sql, params))

    def fetchone(self):
        return self._fetchone_result

    def fetchall(self):
        return self._fetchall_result

    def close(self):
        pass


class _CapturingConn:
    def __init__(self, fetchone_result=None, rowcount=1, fetchall_result=None):
        self.calls = []
        self._fetchone_result = fetchone_result
        self._rowcount = rowcount
        self._fetchall_result = fetchall_result

    def cursor(self, *a, **k):
        return _CapturingCursor(
            self.calls, self._fetchone_result, self._rowcount, self._fetchall_result
        )


def test_upsert_open_request_sql_shape_no_pg():
    conn = _CapturingConn(fetchone_result={"id": "fake-id-1", "created": True})
    request_id, created = repo.upsert_open_request(
        conn,
        track_key="T1",
        track_label="Test Track",
        fingerprint={"a": 1},
        bbox={"min_lat": 1.0},
        session_ref="sess-1",
        draft_centerline=[[5.0, 45.0], [5.001, 45.0]],
    )
    assert request_id == "fake-id-1"
    assert created is True

    sql, params = conn.calls[-1]
    # ON CONFLICT arbiter matches the partial unique index exactly --
    # Postgres requires the predicate to be restated for inference.
    assert "ON CONFLICT (track_key) WHERE status <> 'blessed'" in sql
    # draft_centerline: first-non-null-wins on conflict, never clobbered by
    # a later attaching session's (possibly absent) centerline.
    assert "draft_centerline = COALESCE(" in sql
    assert "track_onboarding_requests.draft_centerline, EXCLUDED.draft_centerline" in sql
    # jsonb dedup guard: don't duplicate a repeated session_ref.
    assert "session_refs @> to_jsonb(%(session_ref)s::text)" in sql
    assert "jsonb_array_length(track_onboarding_requests.session_refs) >= 50" in sql
    # xmax=0 distinguishes insert from update.
    assert "(xmax = 0) AS created" in sql
    assert "RETURNING id, (xmax = 0) AS created" in sql
    assert params["track_key"] == "T1"
    assert params["session_ref"] == "sess-1"
    assert json.loads(params["fingerprint"]) == {"a": 1}
    assert json.loads(params["bbox"]) == {"min_lat": 1.0}
    assert json.loads(params["draft_centerline"]) == [[5.0, 45.0], [5.001, 45.0]]


def test_upsert_open_request_created_false_on_attach_no_pg():
    conn = _CapturingConn(fetchone_result={"id": "existing-id", "created": False})
    request_id, created = repo.upsert_open_request(
        conn,
        track_key="T1",
        track_label=None,
        fingerprint=None,
        bbox=None,
        session_ref="sess-2",
    )
    assert request_id == "existing-id"
    assert created is False
    _, params = conn.calls[-1]
    assert params["fingerprint"] is None
    assert params["bbox"] is None
    assert params["draft_centerline"] is None


def test_set_status_sql_shape_no_pg():
    conn = _CapturingConn(rowcount=1)
    ok = repo.set_status(conn, "req-1", "drafted", draft_status="ok", token_jti="jti-1")
    assert ok is True
    sql, params = conn.calls[-1]
    assert "WHERE id = %(id)s AND status <> 'blessed'" in sql
    assert "status = %(status)s" in sql
    assert "draft_status = %(draft_status)s" in sql
    assert "token_jti = %(token_jti)s" in sql
    assert params["id"] == "req-1"
    assert params["status"] == "drafted"
    assert params["draft_status"] == "ok"
    assert params["token_jti"] == "jti-1"


def test_set_status_zero_rowcount_returns_false_no_pg():
    conn = _CapturingConn(rowcount=0)
    ok = repo.set_status(conn, "req-1", "drafted")
    assert ok is False


def test_set_status_jsonb_field_is_cast_and_dumped_no_pg():
    conn = _CapturingConn(rowcount=1)
    repo.set_status(conn, "req-1", "requested", bbox={"min_lat": 2.0})
    sql, params = conn.calls[-1]
    assert "bbox = %(bbox)s::jsonb" in sql
    assert json.loads(params["bbox"]) == {"min_lat": 2.0}


def test_set_status_rejects_unwhitelisted_field_no_pg():
    conn = _CapturingConn()
    with pytest.raises(ValueError):
        repo.set_status(conn, "req-1", "drafted", track_key="not-allowed")


def test_claim_for_drafting_sql_shape_true_no_pg():
    conn = _CapturingConn(fetchone_result={"id": "req-1"})
    claimed = repo.claim_for_drafting(conn, "req-1")
    assert claimed is True
    sql, params = conn.calls[-1]
    assert "status = 'drafting'" in sql
    assert "status IN ('requested', 'draft_failed')" in sql
    assert "RETURNING id" in sql
    assert params["id"] == "req-1"


def test_claim_for_drafting_false_when_no_row_no_pg():
    conn = _CapturingConn(fetchone_result=None)
    assert repo.claim_for_drafting(conn, "req-1") is False


def test_get_returns_none_when_missing_no_pg():
    conn = _CapturingConn(fetchone_result=None)
    assert repo.get(conn, "missing") is None


def test_get_decodes_jsonb_columns_no_pg():
    row = {
        "id": "req-1", "track_key": "T1", "track_label": "Test",
        "fingerprint": json.dumps({"a": 1}), "status": "requested",
        "bbox": json.dumps({"min_lat": 1.0}),
        "draft_centerline": json.dumps([[5.0, 45.0], [5.001, 45.0]]),
        "first_session_ref": "sess-1",
        "session_refs": json.dumps(["sess-1"]), "session_count": 1,
        "draft_status": None, "draft_path": None, "token_jti": None,
        "error": None, "created_at": None, "updated_at": None,
        "emailed_at": None, "blessed_at": None,
    }
    conn = _CapturingConn(fetchone_result=row)
    result = repo.get(conn, "req-1")
    assert result["fingerprint"] == {"a": 1}
    assert result["bbox"] == {"min_lat": 1.0}
    assert result["draft_centerline"] == [[5.0, 45.0], [5.001, 45.0]]
    assert result["session_refs"] == ["sess-1"]


def test_find_stale_unemailed_sql_shape_no_pg():
    conn = _CapturingConn(fetchall_result=[{"id": "req-1"}, {"id": "req-2"}])
    ids = repo.find_stale_unemailed(conn, older_than_minutes=60)
    assert ids == ["req-1", "req-2"]
    sql, params = conn.calls[-1]
    assert "status <> 'blessed'" in sql
    assert "emailed_at IS NULL" in sql
    assert "updated_at < now() - (%(mins)s || ' minutes')::interval" in sql
    assert params["mins"] == 60


def test_find_stale_unemailed_default_older_than_60_no_pg():
    conn = _CapturingConn(fetchall_result=[])
    repo.find_stale_unemailed(conn)
    _, params = conn.calls[-1]
    assert params["mins"] == 60


def test_find_stale_unemailed_tuple_rows_no_pg():
    """Also handle plain tuple rows (PgConnectionWrapper.cursor() shape)."""
    conn = _CapturingConn(fetchall_result=[("req-1",), ("req-2",)])
    ids = repo.find_stale_unemailed(conn)
    assert ids == ["req-1", "req-2"]


def test_find_stale_unemailed_empty_no_pg():
    conn = _CapturingConn(fetchall_result=[])
    assert repo.find_stale_unemailed(conn) == []


def test_reset_for_retry_sql_shape_true_no_pg():
    conn = _CapturingConn(rowcount=1)
    ok = repo.reset_for_retry(conn, "req-1")
    assert ok is True
    sql, params = conn.calls[-1]
    assert "SET status = 'requested'" in sql
    assert "draft_status = NULL" in sql
    assert "draft_path = NULL" in sql
    assert "token_jti = NULL" in sql
    assert "WHERE id = %(id)s AND status <> 'blessed' AND emailed_at IS NULL" in sql
    assert params["id"] == "req-1"


def test_reset_for_retry_zero_rowcount_returns_false_no_pg():
    """Never touches a blessed or already-emailed row -- the guard predicate
    means Postgres itself matches zero rows, surfaced here as rowcount=0."""
    conn = _CapturingConn(rowcount=0)
    assert repo.reset_for_retry(conn, "req-1") is False


# ---------------------------------------------------------------------------
# Real-PG tests (skip when TELEMETRY_PG_URL unset).
# ---------------------------------------------------------------------------
def _make_pg_conn():
    import psycopg2  # noqa: PLC0415
    import psycopg2.extras  # noqa: PLC0415

    conn = psycopg2.connect(_pg_url)
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn


def _cleanup(conn):
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM track_onboarding_requests WHERE track_key = %s",
            (_TEST_TRACK_KEY,),
        )
    conn.commit()


@_skip_no_pg
def test_pg_first_upsert_creates_one_row():
    conn = _make_pg_conn()
    try:
        _cleanup(conn)
        request_id, created = repo.upsert_open_request(
            conn, track_key=_TEST_TRACK_KEY, track_label="Test",
            fingerprint={"a": 1}, bbox={"min_lat": 1.0}, session_ref="sess-1",
        )
        conn.commit()
        assert created is True

        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS n FROM track_onboarding_requests WHERE track_key = %s",
                (_TEST_TRACK_KEY,),
            )
            assert cur.fetchone()["n"] == 1
    finally:
        _cleanup(conn)
        conn.close()


@_skip_no_pg
def test_pg_second_upsert_same_open_track_attaches_no_dup_refs():
    conn = _make_pg_conn()
    try:
        _cleanup(conn)
        _, created1 = repo.upsert_open_request(
            conn, track_key=_TEST_TRACK_KEY, track_label="Test",
            fingerprint=None, bbox=None, session_ref="sess-1",
        )
        conn.commit()
        req_id2, created2 = repo.upsert_open_request(
            conn, track_key=_TEST_TRACK_KEY, track_label="Test",
            fingerprint=None, bbox=None, session_ref="sess-2",
        )
        conn.commit()
        # repeat the same session_ref -- must not duplicate in session_refs
        req_id3, created3 = repo.upsert_open_request(
            conn, track_key=_TEST_TRACK_KEY, track_label="Test",
            fingerprint=None, bbox=None, session_ref="sess-2",
        )
        conn.commit()

        assert created1 is True
        assert created2 is False
        assert created3 is False
        assert req_id2 == req_id3

        row = repo.get(conn, req_id2)
        assert sorted(row["session_refs"]) == ["sess-1", "sess-2"]
        assert row["session_count"] == 3
    finally:
        _cleanup(conn)
        conn.close()


@_skip_no_pg
def test_pg_claim_for_drafting_true_once_then_false():
    conn = _make_pg_conn()
    try:
        _cleanup(conn)
        req_id, _ = repo.upsert_open_request(
            conn, track_key=_TEST_TRACK_KEY, track_label="Test",
            fingerprint=None, bbox=None, session_ref="sess-1",
        )
        conn.commit()

        assert repo.claim_for_drafting(conn, req_id) is True
        conn.commit()
        assert repo.claim_for_drafting(conn, req_id) is False
        conn.commit()
    finally:
        _cleanup(conn)
        conn.close()


@_skip_no_pg
def test_pg_find_stale_unemailed_and_reset_for_retry():
    conn = _make_pg_conn()
    try:
        _cleanup(conn)
        req_id, _ = repo.upsert_open_request(
            conn, track_key=_TEST_TRACK_KEY, track_label="Test",
            fingerprint=None, bbox=None, session_ref="sess-1",
        )
        conn.commit()
        repo.set_status(conn, req_id, "drafted", draft_status="sam2", token_jti="jti-1")
        conn.commit()

        # Fresh row: not yet stale at 60 minutes.
        assert req_id not in repo.find_stale_unemailed(conn, older_than_minutes=60)

        # Backdate updated_at to simulate a request stuck mid-flight.
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE track_onboarding_requests "
                "SET updated_at = now() - interval '2 hours' WHERE id = %s",
                (req_id,),
            )
        conn.commit()

        stale = repo.find_stale_unemailed(conn, older_than_minutes=60)
        assert req_id in stale

        assert repo.reset_for_retry(conn, req_id) is True
        conn.commit()
        row = repo.get(conn, req_id)
        assert row["status"] == "requested"
        assert row["draft_status"] is None
        assert row["token_jti"] is None

        # Bless it, then confirm reset_for_retry refuses to touch it.
        repo.set_status(conn, req_id, "blessed")
        conn.commit()
        assert repo.reset_for_retry(conn, req_id) is False
    finally:
        _cleanup(conn)
        conn.close()


@_skip_no_pg
def test_pg_set_status_blessed_then_further_writes_refused():
    conn = _make_pg_conn()
    try:
        _cleanup(conn)
        req_id, _ = repo.upsert_open_request(
            conn, track_key=_TEST_TRACK_KEY, track_label="Test",
            fingerprint=None, bbox=None, session_ref="sess-1",
        )
        conn.commit()

        assert repo.set_status(conn, req_id, "blessed") is True
        conn.commit()
        assert repo.set_status(conn, req_id, "drafted") is False
        conn.commit()

        row = repo.get(conn, req_id)
        assert row["status"] == "blessed"
    finally:
        _cleanup(conn)
        conn.close()
