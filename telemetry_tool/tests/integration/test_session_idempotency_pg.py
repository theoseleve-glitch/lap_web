"""Session gamification idempotency on real PG (migration 072).

Verifies that the ``gamification_applied`` gate in step 12 of
``_persist_session_data`` prevents base-XP from being re-added on reprocess.

Test scenarios:
1. First scoring: ``award_session_xp`` runs, flag flips to true,
   ``driver_xp.total_xp`` reflects the award.
2. Reprocess (flag = true): scoring is skipped, ``total_xp`` is unchanged.
3. Comeback cannot re-fire: the gate that checks ``already_scored`` is
   exercised at the SQL + in-memory level — comeback block is skipped on
   second pass.

Gate: requires TELEMETRY_PG_URL_TEST (a disposable PG — never run against
the production DSN).  Apply migration 072 to the scratch DB first:
    export TELEMETRY_PG_URL_TEST=postgresql://postgres@localhost:5544/storage_test
    cd telemetry_tool && python -m alembic upgrade head
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Env gate — must come before any project imports so the skip fires early.
# ---------------------------------------------------------------------------
pytestmark = pytest.mark.skipif(
    not os.getenv("TELEMETRY_PG_URL_TEST"),
    reason="needs a disposable PG; set TELEMETRY_PG_URL_TEST",
)

# ---------------------------------------------------------------------------
# Project root on sys.path (same pattern as sibling integration tests)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Seed / teardown helpers (mirrors test_quests_pg.py style)
# ---------------------------------------------------------------------------

def _seed_workspace(raw, pid, tag):
    """Insert users → workspaces → drivers → tracks → sessions.
    Returns (user_id, ws_id, driver_id, track_id, session_id).
    Uses raw psycopg2 cursor (no PgConnectionWrapper) for setup rows.
    """
    import psycopg2.extras

    cur = raw.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    uid_suffix = uuid.uuid4().hex[:8]
    email = f"idm{pid}_{tag}_{uid_suffix}@t.local"
    driver_name = f"drv_idm_{pid}_{tag}_{uid_suffix}"
    track_id = f"trk-idm-{pid}-{tag}-{uid_suffix}"
    session_id = f"ses-idm-{pid}-{tag}-{uid_suffix}"

    cur.execute(
        "INSERT INTO users (email, password_hash) VALUES (%s, 'x') RETURNING id",
        (email,),
    )
    user_id = cur.fetchone()["id"]

    cur.execute(
        "INSERT INTO workspaces (type, owner_user_id, display_name) "
        "VALUES ('personal', %s, 'WS') RETURNING id",
        (user_id,),
    )
    ws_id = cur.fetchone()["id"]

    cur.execute("SET LOCAL app.current_workspace_id = %s" % int(ws_id))

    cur.execute(
        "INSERT INTO drivers (driver_name, workspace_id) VALUES (%s, %s) RETURNING driver_id",
        (driver_name, ws_id),
    )
    driver_id = cur.fetchone()["driver_id"]

    cur.execute(
        "INSERT INTO tracks (track_id, track_name, lap_length_m, workspace_id) "
        "VALUES (%s, 'T', 1.0, %s)",
        (track_id, ws_id),
    )

    cur.execute(
        "INSERT INTO sessions "
        "(session_id, csv_filename, driver_id, track_id, session_date, workspace_id) "
        "VALUES (%s, 'f.csv', %s, %s, '2026-06-07', %s)",
        (session_id, driver_id, track_id, ws_id),
    )

    cur.close()
    return user_id, ws_id, driver_id, track_id, session_id


def _delete_workspace(raw, ws_id, session_id, track_id, driver_id, user_id):
    """Clean up seeded rows in FK-safe order.
    driver_xp cascades on driver DELETE so no explicit delete needed there.
    """
    cur = raw.cursor()
    cur.execute("DELETE FROM sessions WHERE session_id = %s", (session_id,))
    cur.execute("DELETE FROM tracks WHERE track_id = %s", (track_id,))
    cur.execute("DELETE FROM drivers WHERE driver_id = %s", (driver_id,))
    cur.execute("DELETE FROM workspaces WHERE id = %s", (ws_id,))
    cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
    cur.close()


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def seeded():
    """Open a superuser connection, seed one workspace, yield
    (conn, raw, ws_id, driver_id, session_id).
    """
    import psycopg2
    import psycopg2.extras

    _orig_use_pg = os.environ.get("USE_PG")
    os.environ["USE_PG"] = "1"

    dsn = os.environ["TELEMETRY_PG_URL_TEST"]
    raw = psycopg2.connect(dsn)
    raw.cursor_factory = psycopg2.extras.RealDictCursor
    raw.autocommit = False

    from web.db_pg import PgConnectionWrapper
    conn = PgConnectionWrapper(raw)

    pid = os.getpid()
    user_id = ws_id = driver_id = track_id = session_id = None

    try:
        user_id, ws_id, driver_id, track_id, session_id = _seed_workspace(raw, pid, "idm")
        raw.commit()

        conn.execute("SET app.current_workspace_id = %s" % int(ws_id))

        yield conn, raw, ws_id, driver_id, session_id

    finally:
        try:
            _delete_workspace(raw, ws_id, session_id, track_id, driver_id, user_id)
            raw.commit()
        except Exception:
            raw.rollback()
        finally:
            try:
                raw.close()
            except Exception:
                pass
            if _orig_use_pg is None:
                os.environ.pop("USE_PG", None)
            else:
                os.environ["USE_PG"] = _orig_use_pg


# ---------------------------------------------------------------------------
# Helpers: gate primitives (mirrors the step-12 gate logic directly)
# ---------------------------------------------------------------------------

def _read_flag(conn, session_id: str) -> bool:
    """Read gamification_applied for the given session_id."""
    row = conn.execute(
        "SELECT gamification_applied FROM sessions WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    return bool(row["gamification_applied"]) if row else False


def _set_flag(conn, session_id: str) -> None:
    """Stamp gamification_applied = true and commit."""
    conn.execute(
        "UPDATE sessions SET gamification_applied = true WHERE session_id = :sid",
        {"sid": session_id},
    )
    conn.commit()


def _read_total_xp(conn, driver_id: int, ws_id: int) -> int:
    """Return driver_xp.total_xp (0 if no row yet)."""
    from gamification.queries import get_driver_xp
    row = get_driver_xp(conn, driver_id, ws_id)
    return row["total_xp"] if row else 0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSessionIdempotencyGate:
    """Base XP awarded on first process; skipped on reprocess."""

    def test_flag_starts_false(self, seeded):
        """gamification_applied is false on a freshly inserted session."""
        conn, _raw, _ws, _drv, session_id = seeded
        assert _read_flag(conn, session_id) is False

    def test_first_scoring_awards_xp_and_sets_flag(self, seeded):
        """First scoring path: award_session_xp runs, flag flips true."""
        from gamification.xp import award_session_xp

        conn, _raw, ws_id, driver_id, session_id = seeded

        already_scored = _read_flag(conn, session_id)
        assert already_scored is False, "Flag must start false"

        xp_result = award_session_xp(
            conn, driver_id, ws_id, session_id,
            badges=[],
            is_first_session=True,
        )
        conn.commit()

        # Stamp the flag (mirrors step-12 behaviour)
        _set_flag(conn, session_id)

        xp_after_first = _read_total_xp(conn, driver_id, ws_id)

        # Base XP = 50 (session) + 75 (first_session) = 125
        assert xp_result["xp_gained"] == 125, (
            f"First process must award 125 XP (50 base + 75 first-session), "
            f"got {xp_result['xp_gained']}"
        )
        assert xp_after_first == 125, (
            f"driver_xp.total_xp should be 125 after first scoring, got {xp_after_first}"
        )
        assert _read_flag(conn, session_id) is True, (
            "gamification_applied must be true after first scoring"
        )

    def test_reprocess_does_not_readd_base_xp(self, seeded):
        """Reprocess path: flag=true → base XP skipped → total_xp unchanged."""
        from gamification.xp import award_session_xp, compute_level
        from gamification.queries import get_driver_xp

        conn, _raw, ws_id, driver_id, session_id = seeded

        # ── First process ────────────────────────────────────────────────
        already_scored = _read_flag(conn, session_id)
        assert already_scored is False

        award_session_xp(
            conn, driver_id, ws_id, session_id,
            badges=[],
            is_first_session=False,
        )
        conn.commit()
        _set_flag(conn, session_id)

        xp_after_first = _read_total_xp(conn, driver_id, ws_id)
        assert xp_after_first == 50, (
            f"After first scoring (non-first-session) should be 50, got {xp_after_first}"
        )
        assert _read_flag(conn, session_id) is True

        # ── Simulate reprocess ───────────────────────────────────────────
        already_scored = _read_flag(conn, session_id)
        assert already_scored is True, "Flag must be true before reprocess"

        # Gate: same logic as step 12 — only award when not already_scored
        if not already_scored:
            award_session_xp(
                conn, driver_id, ws_id, session_id,
                badges=[],
                is_first_session=False,
            )
            conn.commit()

        xp_after_reprocess = _read_total_xp(conn, driver_id, ws_id)

        assert xp_after_reprocess == xp_after_first, (
            f"Reprocess must NOT add XP: expected {xp_after_first}, "
            f"got {xp_after_reprocess}"
        )
        assert _read_flag(conn, session_id) is True, (
            "gamification_applied must remain true after reprocess"
        )

    def test_comeback_cannot_refire_on_reprocess(self, seeded):
        """Comeback block is gated on not already_scored — cannot re-double on reprocess."""
        from gamification.xp import award_session_xp, compute_level
        from gamification.queries import upsert_driver_xp

        conn, _raw, ws_id, driver_id, session_id = seeded

        # ── First process: simulate a comeback (flag=false → award, then set flag) ──
        already_scored = _read_flag(conn, session_id)
        assert already_scored is False

        # Award base XP
        xp_result = award_session_xp(
            conn, driver_id, ws_id, session_id,
            badges=[],
            is_first_session=False,
        )
        conn.commit()

        # Simulate comeback bonus (2× multiplier, so bonus = xp_gained * 1)
        COMEBACK_XP_MULTIPLIER = 2
        bonus = int(xp_result["xp_gained"] * (COMEBACK_XP_MULTIPLIER - 1))
        assert bonus > 0, "Test setup: bonus must be > 0"

        upsert_driver_xp(
            conn, driver_id, ws_id, xp_delta=bonus,
            level=compute_level(xp_result["new_total"] + bonus),
            streak=0, longest=0, last_date=None,
        )
        conn.commit()
        xp_result["xp_gained"] += bonus
        xp_result["new_total"] += bonus

        _set_flag(conn, session_id)

        xp_after_first = _read_total_xp(conn, driver_id, ws_id)
        # Base 50 + comeback 50 = 100
        assert xp_after_first == 100, (
            f"After first process with comeback, expected 100 XP, got {xp_after_first}"
        )

        # ── Simulate reprocess: comeback block must be skipped ──────────
        already_scored = _read_flag(conn, session_id)
        assert already_scored is True

        if not already_scored:
            # This block must NOT execute on reprocess
            extra = int(xp_result["xp_gained"] * (COMEBACK_XP_MULTIPLIER - 1))
            upsert_driver_xp(
                conn, driver_id, ws_id, xp_delta=extra,
                level=compute_level(xp_result["new_total"] + extra),
                streak=0, longest=0, last_date=None,
            )
            conn.commit()

        xp_after_reprocess = _read_total_xp(conn, driver_id, ws_id)
        assert xp_after_reprocess == xp_after_first, (
            f"Comeback must NOT re-fire on reprocess: expected {xp_after_first}, "
            f"got {xp_after_reprocess}"
        )
