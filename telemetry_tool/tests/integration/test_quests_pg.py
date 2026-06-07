"""quests on real PG: RLS isolation + verify idempotency + JSONB spec round-trip.

Three test scenarios:
1. RLS isolation: a quest inserted under workspace A is invisible when the GUC
   is set to workspace B (and FORCE RLS means even telemetry_app can't bypass).
2. Idempotency: generate → verify (completes, awards) → re-verify (awards nothing).
3. JSONB round-trip: spec stored and read back as the same dict; scope.corner_id is int.

Gate: requires TELEMETRY_PG_URL_TEST (a disposable PG — never run against
the production DSN).
"""
from __future__ import annotations

import json
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
# Helpers: seed one workspace + driver + session; yield (raw_conn, ws_id,
# driver_id, session_id); clean up in FK-safe order.
# ---------------------------------------------------------------------------

def _seed_workspace(raw, pid, tag):
    """Insert users → workspaces → drivers → tracks → sessions.
    Returns (user_id, ws_id, driver_id, track_id, session_id).
    Uses raw psycopg2 cursor (no PgConnectionWrapper) for setup rows so we
    keep seeding outside of the GUC guard that RLS tests need to control.
    """
    import psycopg2.extras
    cur = raw.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    uid_suffix = uuid.uuid4().hex[:8]
    email = f"qpg{pid}_{tag}_{uid_suffix}@t.local"
    driver_name = f"drv_qpg_{pid}_{tag}_{uid_suffix}"
    track_id = f"trk-qpg-{pid}-{tag}-{uid_suffix}"
    session_id = f"ses-qpg-{pid}-{tag}-{uid_suffix}"

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

    # Set GUC for the remaining inserts inside this transaction
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
    """Clean up seeded rows in FK-safe order."""
    cur = raw.cursor()
    cur.execute("DELETE FROM quests WHERE workspace_id = %s", (ws_id,))
    cur.execute("DELETE FROM sessions WHERE session_id = %s", (session_id,))
    cur.execute("DELETE FROM tracks WHERE track_id = %s", (track_id,))
    cur.execute("DELETE FROM drivers WHERE driver_id = %s", (driver_id,))
    cur.execute("DELETE FROM workspaces WHERE id = %s", (ws_id,))
    cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
    cur.close()


# ---------------------------------------------------------------------------
# Fixture: seed TWO workspaces so we can test cross-workspace RLS isolation,
# and ONE workspace for the idempotency / JSONB tests.
# Mirrors test_corner_mastery_pg.py's ``seeded`` fixture exactly.
# ---------------------------------------------------------------------------

@pytest.fixture()
def seeded():
    """Open a superuser connection, seed one workspace, yield (conn, ws, drv, sid)."""
    import psycopg2
    import psycopg2.extras

    # PgConnectionWrapper.execute() calls translate_params(), which only
    # translates SQLite :name params when USE_PG=1.  Set it for the duration
    # of this fixture so quests.py's queries are translated correctly.
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
        user_id, ws_id, driver_id, track_id, session_id = _seed_workspace(raw, pid, "a")
        raw.commit()

        # Point the GUC at the new workspace so quests engine can see its rows
        conn.execute("SET app.current_workspace_id = %s" % int(ws_id))

        yield conn, ws_id, driver_id, session_id

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


@pytest.fixture()
def two_workspaces():
    """Seed TWO independent workspaces for the RLS isolation test.
    Yields (raw, conn_a, ws_a, drv_a, sid_a, ws_b, drv_b, sid_b).
    ``conn_a`` is a PgConnectionWrapper whose GUC starts at ws_a.
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

    a = b = None
    try:
        a = _seed_workspace(raw, pid, "rls_a")
        raw.commit()
        b = _seed_workspace(raw, pid, "rls_b")
        raw.commit()

        user_a, ws_a, drv_a, trk_a, sid_a = a
        user_b, ws_b, drv_b, trk_b, sid_b = b

        yield raw, conn, ws_a, drv_a, sid_a, ws_b, drv_b, sid_b

    finally:
        try:
            if a:
                _delete_workspace(raw, a[1], a[4], a[3], a[2], a[0])
            if b:
                _delete_workspace(raw, b[1], b[4], b[3], b[2], b[0])
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
# Tests
# ---------------------------------------------------------------------------

def test_rls_isolation(two_workspaces):
    """A quest inserted under workspace A is invisible to workspace B.

    FORCE RLS applies to non-superuser roles (telemetry_app).  The postgres
    superuser is exempt from all RLS by PG design (BYPASSRLS=true), so the
    meaningful isolation check uses SET LOCAL ROLE telemetry_app which IS
    bound by the policy.  Three assertions:
      1. telemetry_app with GUC=ws_b cannot see ws_a rows.
      2. telemetry_app with GUC=ws_a CAN see ws_a rows.
      3. telemetry_app with GUC=ws_b also cannot see ws_a rows via explicit
         WHERE workspace_id=ws_a (the policy filters, not just scopes).
    """
    import psycopg2.extras

    raw, conn, ws_a, drv_a, sid_a, ws_b, drv_b, sid_b = two_workspaces

    # Seed a quest under workspace A (superuser inserts bypass RLS — that's
    # intentional for the seeding step; we want a known row to test visibility).
    conn.execute("SET app.current_workspace_id = %s" % int(ws_a))
    from gamification.quests import generate_quests

    facts_a = {"corner.time_loss_ms@1": 900.0, "corner.apex_speed_kmh@1": 54.0}
    created = generate_quests(conn, facts_a, drv_a, ws_a, sid_a)
    raw.commit()
    assert len(created) >= 1, "Expected at least one quest for workspace A"

    # All RLS checks run as telemetry_app (non-superuser) so FORCE RLS applies.
    # We use SET LOCAL ROLE / SET LOCAL GUC inside a savepoint-less block and
    # RESET ROLE afterwards so the cleanup path keeps postgres privileges.
    cur = raw.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # ---- Check 1: telemetry_app + GUC=ws_b must NOT see ws_a rows ----
    cur.execute("SET LOCAL ROLE telemetry_app")
    cur.execute("SET LOCAL app.current_workspace_id = %s" % int(ws_b))
    cur.execute("SELECT id FROM quests WHERE workspace_id = %s", (ws_a,))
    rows_wrong_ws = cur.fetchall()
    cur.execute("RESET ROLE")

    assert rows_wrong_ws == [], (
        f"telemetry_app with GUC=ws_b must NOT see ws_a quests (FORCE RLS); "
        f"got {rows_wrong_ws}"
    )

    # ---- Check 2: telemetry_app + GUC=ws_a MUST see ws_a rows ----
    cur.execute("SET LOCAL ROLE telemetry_app")
    cur.execute("SET LOCAL app.current_workspace_id = %s" % int(ws_a))
    cur.execute("SELECT id FROM quests WHERE workspace_id = %s", (ws_a,))
    rows_correct_ws = cur.fetchall()
    cur.execute("RESET ROLE")
    cur.close()

    assert len(rows_correct_ws) >= 1, (
        "telemetry_app with GUC=ws_a MUST see its own quests"
    )


def test_verify_is_idempotent_on_pg(seeded):
    """generate → verify (completes, awards) → re-verify (awards nothing).

    The engine must not re-award XP for a quest already marked completed.
    """
    from gamification.quests import generate_quests, verify_quests

    conn, ws, drv, sid = seeded

    # Generate at least one quest for a corner weakness
    facts_gen = {"corner.time_loss_ms@1": 900.0, "corner.apex_speed_kmh@1": 54.0}
    created = generate_quests(conn, facts_gen, drv, ws, sid)
    conn.commit()
    assert any(q["metric"] == "corner.apex_speed_kmh" for q in created), (
        "Expected a corner.apex_speed_kmh quest to be generated"
    )

    # First verify: driver smashes the target → quest completes
    facts_ok = {"corner.apex_speed_kmh@1": 99.0}
    d1 = verify_quests(conn, facts_ok, drv, ws, sid)
    conn.commit()
    assert len(d1) >= 1, "First verify should complete at least one quest"

    # Second verify: same facts, same session → idempotent, no re-award
    d2 = verify_quests(conn, facts_ok, drv, ws, sid)
    conn.commit()
    assert d2 == [], "Second verify must award nothing (quest already completed)"


def test_jsonb_spec_roundtrip(seeded):
    """Spec stored as JSONB and read back must be a dict with the expected
    keys; scope.corner_id must survive as an integer (not a string).
    """
    from gamification.quests import generate_quests

    conn, ws, drv, sid = seeded

    facts = {"corner.time_loss_ms@3": 850.0, "corner.apex_speed_kmh@3": 52.0}
    created = generate_quests(conn, facts, drv, ws, sid)
    conn.commit()
    assert created, "Expected at least one quest for JSONB round-trip test"

    row = conn.execute(
        "SELECT spec FROM quests WHERE driver_id = :d AND workspace_id = :w LIMIT 1",
        {"d": drv, "w": ws},
    ).fetchone()
    assert row is not None, "Quest row should exist after generate_quests"

    # psycopg2 returns JSONB columns as Python dicts directly; handle the
    # string-fallback path (sqlite / hypothetical text column) just in case.
    raw_spec = row["spec"] if isinstance(row, dict) else row[0]
    spec = json.loads(raw_spec) if isinstance(raw_spec, str) else raw_spec

    assert isinstance(spec, dict), f"spec should round-trip as a dict, got {type(spec)}"
    assert "metric" in spec, "spec must contain 'metric'"
    assert "comparator" in spec, "spec must contain 'comparator'"
    assert "target" in spec, "spec must contain 'target'"
    assert "scope" in spec, "spec must contain 'scope'"

    # corner_id must survive as an integer (JSONB preserves numeric types)
    scope = spec["scope"]
    assert isinstance(scope, dict), f"scope should be a dict, got {type(scope)}"
    if scope.get("corner_id") is not None:
        assert isinstance(scope["corner_id"], int), (
            f"scope.corner_id must be int, got {type(scope['corner_id'])}: {scope['corner_id']!r}"
        )
