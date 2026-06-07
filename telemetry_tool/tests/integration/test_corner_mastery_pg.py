"""corner_mastery on real PG: upsert idempotency + JSONB round-trip.

Seeding chain: users → workspaces → SET GUC → drivers → tracks → sessions
→ call update_corner_mastery twice with the same session_id → assert no new
events and no row change on the second call.

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
# Fixture: seed user / workspace / driver / track / session, yield ids,
# clean up in FK-safe order.
# ---------------------------------------------------------------------------

@pytest.fixture()
def seeded():
    """Open a superuser connection, seed rows, yield (conn, ws, drv, sid)."""
    import psycopg2
    import psycopg2.extras

    # PgConnectionWrapper.execute() calls translate_params(), which only
    # translates SQLite :name params when USE_PG=1.  Set it for the duration
    # of this fixture so mastery.py's queries are translated correctly.
    _orig_use_pg = os.environ.get("USE_PG")
    os.environ["USE_PG"] = "1"

    dsn = os.environ["TELEMETRY_PG_URL_TEST"]
    raw = psycopg2.connect(dsn)
    raw.cursor_factory = psycopg2.extras.RealDictCursor
    raw.autocommit = False

    from web.db_pg import PgConnectionWrapper
    conn = PgConnectionWrapper(raw)

    # --- unique-per-run identifiers to avoid collision across parallel runs --
    pid = os.getpid()
    uid_suffix = uuid.uuid4().hex[:8]
    email = f"cmpg{pid}_{uid_suffix}@t.local"
    driver_name = f"drv_cmpg_{pid}_{uid_suffix}"
    track_id = f"trk-cmpg-seed-{pid}-{uid_suffix}"
    session_id = f"ses-cmpg-{pid}-{uid_suffix}"

    user_id = ws_id = driver_id = None
    try:
        # 1. users
        cur = conn.execute(
            "INSERT INTO users (email, password_hash) VALUES (:email, 'x') RETURNING id",
            {"email": email},
        )
        user_id = cur.fetchone()["id"]

        # 2. workspaces
        cur = conn.execute(
            "INSERT INTO workspaces (type, owner_user_id, display_name) "
            "VALUES ('personal', :uid, 'WS') RETURNING id",
            {"uid": user_id},
        )
        ws_id = cur.fetchone()["id"]

        # 3. Set GUC so the workspace_id DEFAULT works for drivers/tracks
        conn.execute(
            "SET app.current_workspace_id = %s" % int(ws_id)
        )

        # 4. drivers (workspace_id explicit to avoid relying on DEFAULT)
        cur = conn.execute(
            "INSERT INTO drivers (driver_name, workspace_id) "
            "VALUES (:name, :ws) RETURNING driver_id",
            {"name": driver_name, "ws": ws_id},
        )
        driver_id = cur.fetchone()["driver_id"]

        # 5. tracks (workspace_id explicit; lap_length_m NOT NULL)
        conn.execute(
            "INSERT INTO tracks (track_id, track_name, lap_length_m, workspace_id) "
            "VALUES (:tid, 'T', 1.0, :ws)",
            {"tid": track_id, "ws": ws_id},
        )

        # 6. sessions (minimal required cols: session_id, csv_filename,
        #    driver_id, track_id, session_date, workspace_id)
        conn.execute(
            "INSERT INTO sessions "
            "(session_id, csv_filename, driver_id, track_id, session_date, workspace_id) "
            "VALUES (:sid, 'f.csv', :drv, :trk, '2026-06-07', :ws)",
            {"sid": session_id, "drv": driver_id, "trk": track_id, "ws": ws_id},
        )

        raw.commit()

        yield conn, ws_id, driver_id, session_id

    finally:
        # Clean up in FK-safe order (corner_mastery first, then session chain)
        try:
            conn.execute(
                "DELETE FROM corner_mastery WHERE workspace_id = :ws",
                {"ws": ws_id},
            )
            conn.execute(
                "DELETE FROM sessions WHERE session_id = :sid",
                {"sid": session_id},
            )
            conn.execute(
                "DELETE FROM tracks WHERE track_id = :tid",
                {"tid": track_id},
            )
            conn.execute(
                "DELETE FROM drivers WHERE driver_id = :drv",
                {"drv": driver_id},
            )
            conn.execute(
                "DELETE FROM workspaces WHERE id = :ws",
                {"ws": ws_id},
            )
            conn.execute(
                "DELETE FROM users WHERE id = :uid",
                {"uid": user_id},
            )
            raw.commit()
        except Exception:
            raw.rollback()
        finally:
            try:
                raw.close()
            except Exception:
                pass
            # Restore USE_PG to whatever it was before the fixture ran
            if _orig_use_pg is None:
                os.environ.pop("USE_PG", None)
            else:
                os.environ["USE_PG"] = _orig_use_pg


# ---------------------------------------------------------------------------
# THE test
# ---------------------------------------------------------------------------

def test_same_session_twice_is_idempotent(seeded):
    """Calling update_corner_mastery twice with identical args is idempotent.

    First call → inserts a row, returns bronze event (score 70 ≥ 60).
    Second call → no change, no events, row unchanged.
    sessions_at_silver stays [] because 70 < 75 (STAR_SILVER_SCORE).
    """
    from gamification.mastery import update_corner_mastery

    conn, ws, drv, sid = seeded

    # track_id in corner_mastery is plain TEXT (no FK to tracks), so we use
    # a synthetic value that doesn't need to match the seeded track row.
    mastery_track_id = "trk-cmpg"
    corner_scores = {1: 70.0}  # 70 ≥ STAR_BRONZE_SCORE(60), < STAR_SILVER_SCORE(75)

    # First call — should insert the row and return a bronze star event.
    e1 = update_corner_mastery(conn, drv, ws, mastery_track_id, "dry", corner_scores, sid)
    conn.commit()

    # Second call — identical args, should be a no-op.
    e2 = update_corner_mastery(conn, drv, ws, mastery_track_id, "dry", corner_scores, sid)
    conn.commit()

    # --- assertions on events ------------------------------------------------
    assert [x["tier"] for x in e1] == ["bronze"], (
        f"Expected ['bronze'] from first call, got {e1}"
    )
    assert e2 == [], (
        f"Expected no events from second (idempotent) call, got {e2}"
    )

    # --- assertions on persisted row -----------------------------------------
    row = conn.execute(
        "SELECT tier, sessions_at_silver FROM corner_mastery "
        "WHERE corner_id = :c AND workspace_id = :w AND driver_id = :d "
        "AND track_id = :t AND condition = :cond",
        {"c": 1, "w": ws, "d": drv, "t": mastery_track_id, "cond": "dry"},
    ).fetchone()

    assert row is not None, "corner_mastery row should exist after upsert"

    tier = row["tier"] if isinstance(row, dict) else row[0]
    raw_sas = row["sessions_at_silver"] if isinstance(row, dict) else row[1]

    # JSONB comes back as a Python list from psycopg2; string fallback for
    # hypothetical text-column environments.
    stored = json.loads(raw_sas) if isinstance(raw_sas, str) else list(raw_sas)

    assert tier == "bronze", f"Expected tier 'bronze', got {tier!r}"
    assert stored == [], (
        f"sessions_at_silver should be [] (score 70 < silver threshold), got {stored!r}"
    )
