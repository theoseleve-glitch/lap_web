"""Shared cross-table compute budget (analysis + export + track-surface pool)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from web.compute_budget import (  # noqa: E402
    count_active_compute_jobs,
    count_active_ocp_corner_jobs,
    check_shared_compute_budget,
)


class _FakeConn:
    """Minimal conn double: returns per-table COUNT rows; can mark tables missing.

    SAVEPOINT / RELEASE / ROLLBACK statements are accepted as no-ops so the
    savepoint-guarded counter exercises its real control flow.
    """

    def __init__(self, counts, missing=()):
        self.counts = dict(counts)
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


def test_counts_sum_across_all_job_tables():
    conn = _FakeConn({"ingestion_jobs": 2, "exports": 1, "analysis_runs": 3})
    assert count_active_compute_jobs(conn, workspace_id=1) == 6


def test_missing_table_contributes_zero_and_does_not_crash():
    # analysis_runs absent (older lineage) — savepoint guard swallows the error.
    conn = _FakeConn({"ingestion_jobs": 2, "exports": 1}, missing={"analysis_runs"})
    assert count_active_compute_jobs(conn, workspace_id=1) == 3


def test_shared_budget_denies_when_pool_at_tier_limit():
    # locked tier: max_concurrent_jobs == 1. One active analysis already running.
    conn = _FakeConn({"ingestion_jobs": 1})
    allowed, info = check_shared_compute_budget(conn, user_id=1, workspace_id=1, plan_tier="locked")
    assert allowed is False
    assert info["running_jobs"] == 1
    assert info["max_jobs"] == 1


def test_shared_budget_allows_under_limit_across_types():
    # racer tier: max 2. One export + zero others = 1 < 2 → allowed.
    conn = _FakeConn({"exports": 1})
    allowed, info = check_shared_compute_budget(conn, user_id=1, workspace_id=1, plan_tier="racer")
    assert allowed is True
    assert info["running_jobs"] == 1
    assert info["max_jobs"] == 2


def test_shared_budget_denies_when_spread_across_types():
    # racer tier max 2, but 1 analysis + 1 export + 1 surface = 3 → denied.
    conn = _FakeConn({"ingestion_jobs": 1, "exports": 1, "analysis_runs": 1})
    allowed, info = check_shared_compute_budget(conn, user_id=1, workspace_id=1, plan_tier="racer")
    assert allowed is False
    assert info["running_jobs"] == 3


# ---------------------------------------------------------------------------
# Fix D: OCP-corner solves (web.routes.data_v2.solve_ocp_corner) must ALSO be
# COUNTABLE toward the shared budget -- that route only READ this pool but
# never registered itself, so concurrent same-tenant solves were invisible
# to each other's budget checks.
# ---------------------------------------------------------------------------


class _FakeRedisGet:
    """Bare-minimum redis double exposing only .get, for the INCR-counter
    read path (unlike endurance's SET-based .scard)."""

    def __init__(self, values: dict[str, int]):
        self.values = values

    def get(self, key):
        return self.values.get(key)


def test_count_active_ocp_corner_jobs_reads_incr_counter():
    r = _FakeRedisGet({"ocp_corner:active:9": 2})
    assert count_active_ocp_corner_jobs(r, workspace_id=9) == 2
    assert count_active_ocp_corner_jobs(r, workspace_id=1) == 0


def test_count_active_ocp_corner_jobs_fails_open_without_client():
    assert count_active_ocp_corner_jobs(None, workspace_id=9) == 0


def test_count_active_ocp_corner_jobs_fails_open_on_redis_error():
    class _Boom:
        def get(self, key):
            raise ConnectionError("redis down")

    assert count_active_ocp_corner_jobs(_Boom(), workspace_id=9) == 0


def test_count_active_ocp_corner_jobs_never_goes_negative():
    """A stray/duplicate DECR (e.g. a race between a TTL expiry and a slow
    solve's cleanup) must never report a negative count."""
    r = _FakeRedisGet({"ocp_corner:active:9": -1})
    assert count_active_ocp_corner_jobs(r, workspace_id=9) == 0


def test_count_active_compute_jobs_sums_pg_and_ocp_corner():
    conn = _FakeConn({"ingestion_jobs": 1, "exports": 1})
    r = _FakeRedisGet({"ocp_corner:active:9": 3})
    total = count_active_compute_jobs(conn, workspace_id=9, redis_client=r)
    assert total == 5  # 1 + 1 + 0 (analysis_runs) + 3 (ocp-corner)


def test_check_shared_compute_budget_denies_when_ocp_corner_alone_fills_pool():
    # racer tier max=2; zero PG jobs but 2 concurrent OCP-corner solves
    # already registered from the SAME workspace -- must deny.
    conn = _FakeConn({})
    r = _FakeRedisGet({"ocp_corner:active:9": 2})
    allowed, info = check_shared_compute_budget(
        conn, user_id=1, workspace_id=9, plan_tier="racer", redis_client=r,
    )
    assert allowed is False
    assert info["running_jobs"] == 2
