# Audit Checkpoint 2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create JSON entity APIs for 6 entity groups, harden session PATCH, add kart_id to sessions, wire everything so frontend pages populate.

**Architecture:** Single new blueprint `api_v1_entities.py` at `/api/v1/`. Schema migration (Alembic 024 + SQLite schema.py) adds `kart_id` to sessions. Existing `models.py` functions reused where possible; new queries added to `queries.py`. All responses via `api_response()`/`api_error()` envelope.

**Tech Stack:** Python Flask, SQLite, Alembic, pytest

---

### Task 1: Schema Migration — Add kart_id to sessions

**Files:**
- Modify: `telemetry_tool/db/schema.py:56-79` (sessions table)
- Modify: `telemetry_tool/db/queries.py:12-28` (INSERT_SESSION)
- Modify: `telemetry_tool/web/models.py:402-415` (update_session_field allowed set)
- Create: `telemetry_tool/alembic/versions/024_session_kart_id.py`
- Test: `telemetry_tool/tests/test_session_kart_link.py`

**Context:** The sessions table currently has no `kart_id` column. The `karts` table exists (Phase 13). `models.py:get_all_karts()` already tries to JOIN `sessions s ON k.kart_id = s.kart_id` but the column doesn't exist in schema.py yet. `models.py:delete_kart()` also references `sessions.kart_id`. Adding the column makes these existing functions work correctly.

**Step 1: Write test**

```python
"""Tests for session-kart linking via kart_id column."""
import sqlite3
import pytest
from db.schema import ensure_schema


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    conn.execute("INSERT INTO drivers (driver_name) VALUES ('Test')")
    conn.commit()
    return conn


def test_session_kart_id_column_exists(db):
    """sessions table has kart_id column after schema creation."""
    cols = [r[1] for r in db.execute("PRAGMA table_info(sessions)").fetchall()]
    assert "kart_id" in cols


def test_session_kart_id_fk_links(db):
    """kart_id on session correctly references karts table."""
    db.execute(
        "INSERT INTO karts (kart_name) VALUES ('K1')"
    )
    kart_id = db.execute("SELECT kart_id FROM karts WHERE kart_name='K1'").fetchone()[0]
    db.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, session_date, kart_id) "
        "VALUES ('s1', 'test.csv', 1, '2026-01-01', ?)",
        (kart_id,),
    )
    db.commit()
    row = db.execute("SELECT kart_id FROM sessions WHERE session_id='s1'").fetchone()
    assert row["kart_id"] == kart_id


def test_session_kart_id_nullable(db):
    """kart_id is nullable — sessions without karts are fine."""
    db.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, session_date) "
        "VALUES ('s2', 'test.csv', 1, '2026-01-01')"
    )
    db.commit()
    row = db.execute("SELECT kart_id FROM sessions WHERE session_id='s2'").fetchone()
    assert row["kart_id"] is None
```

**Step 2: Run test — expect FAIL** (kart_id column doesn't exist yet)

Run: `pytest telemetry_tool/tests/test_session_kart_link.py -v`

**Step 3: Implement**

In `telemetry_tool/db/schema.py`, add `kart_id` to the sessions CREATE TABLE (before `created_at`):
```python
    source_path       TEXT,
    kart_id           INTEGER REFERENCES karts(kart_id),
    created_at        TEXT    NOT NULL DEFAULT (datetime('now'))
```

In `telemetry_tool/db/queries.py`, add `kart_id` to `INSERT_SESSION`:
- Column list: add `kart_id` after `source_path`
- Values list: add `:kart_id` after `:source_path`

In `telemetry_tool/web/models.py:402-415`, add `"kart_id"` to the `allowed` set in `update_session_field()`.

Create Alembic migration `telemetry_tool/alembic/versions/024_session_kart_id.py`:
```python
"""Add kart_id to sessions table.

Revision ID: 024
Revises: 023
"""
from alembic import op
import sqlalchemy as sa

revision = "024"
down_revision = "023"

def upgrade():
    op.add_column("sessions", sa.Column("kart_id", sa.Integer(), nullable=True))

def downgrade():
    op.drop_column("sessions", "kart_id")
```

**Step 4: Run test — expect PASS**

Run: `pytest telemetry_tool/tests/test_session_kart_link.py -v`

**Step 5: Commit**

```bash
git add telemetry_tool/db/schema.py telemetry_tool/db/queries.py telemetry_tool/web/models.py telemetry_tool/alembic/versions/024_session_kart_id.py telemetry_tool/tests/test_session_kart_link.py
git commit -m "feat: add kart_id column to sessions table (Alembic 024)"
```

---

### Task 2: Session PATCH Hardening — Validation + kart_id

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py:644-700` (PATCH endpoint)
- Modify: `telemetry_tool/db/queries.py:30-45` (SELECT_SESSION_BY_ID — add kart join)
- Test: `telemetry_tool/tests/test_session_patch_validation.py`

**Context:** The PATCH endpoint at `data_v2.py:648` currently has no validation — any string is accepted for `session_type`, `track_id`, etc. We need enum checks, FK existence checks, and the response must include resolved names (driver_name, track_name, kart_name).

**Step 1: Write test**

```python
"""Tests for session PATCH validation and kart_id support."""
import sqlite3
import json
import pytest
from db.schema import ensure_schema


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    conn.execute("INSERT INTO drivers (driver_name) VALUES ('TestDriver')")
    conn.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, session_date) "
        "VALUES ('s1', 'test.csv', 1, '2026-01-01')"
    )
    conn.execute("INSERT INTO karts (kart_name) VALUES ('TestKart')")
    conn.commit()
    return conn


@pytest.fixture
def client(db, tmp_path):
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    os.environ["TELEMETRY_DB_PATH"] = ":memory:"
    from web.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    # Patch get_db_connection to use our fixture db
    import web.routes.data_v2 as dv2
    dv2.get_db_connection = lambda: db
    with app.test_client() as c:
        yield c


def test_patch_rejects_invalid_session_type(client):
    resp = client.patch("/api/v1/sessions/s1",
                        json={"session_type": "banana"},
                        content_type="application/json")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"]["code"] == "VALIDATION_ERROR"


def test_patch_rejects_invalid_track_state(client):
    resp = client.patch("/api/v1/sessions/s1",
                        json={"track_state": "snowy"},
                        content_type="application/json")
    assert resp.status_code == 400


def test_patch_rejects_nonexistent_driver_id(client):
    resp = client.patch("/api/v1/sessions/s1",
                        json={"driver_id": 9999},
                        content_type="application/json")
    assert resp.status_code == 400


def test_patch_rejects_nonexistent_kart_id(client):
    resp = client.patch("/api/v1/sessions/s1",
                        json={"kart_id": 9999},
                        content_type="application/json")
    assert resp.status_code == 400


def test_patch_accepts_valid_kart_id(client):
    resp = client.patch("/api/v1/sessions/s1",
                        json={"kart_id": 1},
                        content_type="application/json")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True


def test_patch_accepts_null_kart_id(client):
    """Setting kart_id to null unlinks the kart."""
    resp = client.patch("/api/v1/sessions/s1",
                        json={"kart_id": None},
                        content_type="application/json")
    assert resp.status_code == 200


def test_patch_validates_session_date_format(client):
    resp = client.patch("/api/v1/sessions/s1",
                        json={"session_date": "not-a-date"},
                        content_type="application/json")
    assert resp.status_code == 400


def test_patch_accepts_valid_session_date(client):
    resp = client.patch("/api/v1/sessions/s1",
                        json={"session_date": "2026-03-15"},
                        content_type="application/json")
    assert resp.status_code == 200
```

**Step 2: Run test — expect FAIL**

Run: `pytest telemetry_tool/tests/test_session_patch_validation.py -v`

**Step 3: Implement**

In `telemetry_tool/web/routes/data_v2.py`, replace the PATCH endpoint (lines 644-700):

```python
_UPDATABLE_FIELDS = {
    "display_name", "session_date", "driver_id", "track_id",
    "session_type", "track_state", "kart_id", "notes",
}

_VALID_SESSION_TYPES = {"practice", "qualifying", "race", "test"}
_VALID_TRACK_STATES = {"dry", "wet", "damp", "mixed"}


def _validate_patch_fields(conn, body):
    """Validate PATCH body fields. Returns (errors, cleaned_body)."""
    errors = []
    cleaned = {}

    for field in _UPDATABLE_FIELDS:
        if field not in body:
            continue
        val = body[field]

        if field == "session_type":
            if val not in _VALID_SESSION_TYPES:
                errors.append({"field": "session_type", "message": f"Must be one of: {', '.join(sorted(_VALID_SESSION_TYPES))}"})
            else:
                cleaned[field] = val

        elif field == "track_state":
            if val not in _VALID_TRACK_STATES:
                errors.append({"field": "track_state", "message": f"Must be one of: {', '.join(sorted(_VALID_TRACK_STATES))}"})
            else:
                cleaned[field] = val

        elif field == "driver_id":
            if val is not None:
                row = conn.execute("SELECT driver_id FROM drivers WHERE driver_id = ?", (val,)).fetchone()
                if not row:
                    errors.append({"field": "driver_id", "message": "Driver not found"})
                else:
                    cleaned[field] = val

        elif field == "track_id":
            if val is not None:
                row = conn.execute("SELECT track_id FROM tracks WHERE track_id = ?", (val,)).fetchone()
                if not row:
                    errors.append({"field": "track_id", "message": "Track not found"})
                else:
                    cleaned[field] = val

        elif field == "kart_id":
            if val is None:
                cleaned[field] = None  # unlink
            else:
                row = conn.execute("SELECT kart_id FROM karts WHERE kart_id = ?", (val,)).fetchone()
                if not row:
                    errors.append({"field": "kart_id", "message": "Kart not found"})
                else:
                    cleaned[field] = val

        elif field == "session_date":
            import re
            if val and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(val)):
                errors.append({"field": "session_date", "message": "Must be ISO date YYYY-MM-DD"})
            else:
                cleaned[field] = val

        elif field == "display_name":
            if val is not None and (not isinstance(val, str) or len(val) > 200):
                errors.append({"field": "display_name", "message": "Must be string, max 200 chars"})
            else:
                cleaned[field] = val

        elif field == "notes":
            if val is not None and (not isinstance(val, str) or len(val) > 2000):
                errors.append({"field": "notes", "message": "Must be string, max 2000 chars"})
            else:
                cleaned[field] = val

        else:
            cleaned[field] = val

    return errors, cleaned
```

Update the PATCH handler to call `_validate_patch_fields()` before writing:

```python
@bp.route("/sessions/<session_id>", methods=["PATCH"])
@_safe_api
def update_session(session_id: str):
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    body = request.get_json(silent=True)
    if not body or not isinstance(body, dict):
        return api_error(ErrorCode.VALIDATION_ERROR, "Request body must be a JSON object", status=400)

    updated_count = 0

    # Handle driver_name specially — upsert driver, then update driver_id.
    driver_name = body.get("driver_name")
    if driver_name and isinstance(driver_name, str):
        driver_id = models.upsert_driver(conn, driver_name)
        models.update_session_field(conn, session_id, "driver_id", driver_id)
        updated_count += 1

    # Validate structured fields
    errors, cleaned = _validate_patch_fields(conn, body)
    if errors:
        return api_error(ErrorCode.VALIDATION_ERROR, "Validation failed", details=errors, status=400)

    for field, value in cleaned.items():
        models.update_session_field(conn, session_id, field, value)
        updated_count += 1

    if updated_count == 0:
        allowed = sorted(list(_UPDATABLE_FIELDS) + ["driver_name"])
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            f"No updatable fields provided. Allowed: {', '.join(allowed)}",
            status=400,
        )

    conn.commit()

    # Re-fetch with resolved names
    updated = dict(models.get_session_by_id(conn, session_id))
    updated.pop("source_path", None)
    updated.pop("html_report_path", None)
    if updated.get("csv_filename"):
        updated["csv_filename"] = Path(updated["csv_filename"]).name
    return api_response(updated)
```

Also update `SELECT_SESSION_BY_ID` in `queries.py` to join karts:
```sql
SELECT s.*, d.driver_name, t.track_name, k.kart_name
FROM sessions s
JOIN drivers d ON s.driver_id = d.driver_id
LEFT JOIN tracks t ON s.track_id = t.track_id
LEFT JOIN karts k ON s.kart_id = k.kart_id
WHERE s.session_id = :session_id;
```

And `SELECT_SESSIONS` similarly to include `k.kart_name`.

**Step 4: Run test — expect PASS**

Run: `pytest telemetry_tool/tests/test_session_patch_validation.py -v`

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py telemetry_tool/db/queries.py telemetry_tool/tests/test_session_patch_validation.py
git commit -m "feat: harden session PATCH with validation, kart_id support, resolved names"
```

---

### Task 3: Entity API Blueprint — Drivers + Tracks

**Files:**
- Create: `telemetry_tool/web/routes/api_v1_entities.py`
- Modify: `telemetry_tool/web/app.py:246` (register new blueprint)
- Test: `telemetry_tool/tests/test_entity_api.py`

**Context:** The existing template routes (`drivers.py`, `tracks.py`) serve HTML. We need a NEW blueprint at `/api/v1/` that returns JSON via `api_response()`. The existing `queries.py` has `SELECT_ALL_DRIVERS`, `SELECT_ALL_TRACKS`, `SELECT_DRIVER_BY_NAME`, `SELECT_TRACK_BY_ID`. The existing `models.py` has `upsert_driver()`. We reuse these.

**Step 1: Write test**

```python
"""Tests for /api/v1/ entity endpoints — drivers and tracks."""
import sqlite3
import json
import pytest
from db.schema import ensure_schema


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    # Seed data
    conn.execute("INSERT INTO drivers (driver_name) VALUES ('Alice')")
    conn.execute("INSERT INTO drivers (driver_name) VALUES ('Bob')")
    conn.execute(
        "INSERT INTO tracks (track_id, track_name, lap_length_m) "
        "VALUES ('trk1', 'Spa', 7004.0)"
    )
    conn.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, session_date) "
        "VALUES ('s1', 'test.csv', 1, 'trk1', '2026-01-01')"
    )
    conn.commit()
    return conn


@pytest.fixture
def client(db):
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    os.environ.setdefault("TELEMETRY_DB_PATH", ":memory:")
    from web.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    # Patch db connection
    import web.routes.api_v1_entities as ent
    ent._get_conn = lambda: db
    with app.test_client() as c:
        yield c


def test_list_drivers(client):
    resp = client.get("/api/v1/drivers")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    drivers = data["data"]
    assert len(drivers) >= 2
    names = [d["name"] for d in drivers]
    assert "Alice" in names
    assert "Bob" in names


def test_get_driver_detail(client):
    resp = client.get("/api/v1/drivers/1")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["data"]["name"] == "Alice"


def test_get_driver_not_found(client):
    resp = client.get("/api/v1/drivers/9999")
    assert resp.status_code == 404


def test_patch_driver(client):
    resp = client.patch("/api/v1/drivers/1", json={"notes": "Fast driver"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["data"]["notes"] == "Fast driver"


def test_list_tracks(client):
    resp = client.get("/api/v1/tracks")
    assert resp.status_code == 200
    data = resp.get_json()
    tracks = data["data"]
    assert len(tracks) >= 1
    assert tracks[0]["name"] == "Spa"


def test_get_track_detail(client):
    resp = client.get("/api/v1/tracks/trk1")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["data"]["name"] == "Spa"
    assert data["data"]["session_count"] >= 1


def test_get_track_not_found(client):
    resp = client.get("/api/v1/tracks/nonexistent")
    assert resp.status_code == 404
```

**Step 2: Run test — expect FAIL** (module doesn't exist)

Run: `pytest telemetry_tool/tests/test_entity_api.py -v`

**Step 3: Implement**

Create `telemetry_tool/web/routes/api_v1_entities.py`:

```python
"""JSON API endpoints for entity management (drivers, tracks, karts, weekends, etc.).

All endpoints use the standard api_response()/api_error() envelope.
Field names are mapped to match frontend expectations.
"""
from __future__ import annotations

import logging
from flask import Blueprint, request
from web.api_utils import api_response, api_error, ErrorCode
from db import queries as Q

logger = logging.getLogger(__name__)

bp = Blueprint("api_v1_entities", __name__, url_prefix="/api/v1")


def _get_conn():
    """Get DB connection — overridden in tests."""
    from web.routes.data_v2 import get_db_connection
    return get_db_connection()


# ══════════════════════════════════════════════════════════════════
# Drivers
# ══════════════════════════════════════════════════════════════════

def _map_driver(row):
    """Map DB driver row to frontend-expected field names."""
    d = dict(row)
    return {
        "id": d["driver_id"],
        "name": d["driver_name"],
        "notes": d.get("notes"),
        "created_at": d.get("created_at"),
        "session_count": d.get("session_count", 0),
        "personal_best_s": d.get("personal_best_s"),
        "mean_score": d.get("mean_score"),
    }


@bp.route("/drivers", methods=["GET"])
def list_drivers():
    conn = _get_conn()
    rows = conn.execute(Q.SELECT_ALL_DRIVERS).fetchall()
    return api_response([_map_driver(r) for r in rows])


@bp.route("/drivers/<int:driver_id>", methods=["GET"])
def get_driver(driver_id):
    conn = _get_conn()
    row = conn.execute(
        "SELECT d.*, COUNT(s.session_id) AS session_count, "
        "MIN(s.best_lap_time_s) AS personal_best_s, AVG(s.total_score) AS mean_score "
        "FROM drivers d LEFT JOIN sessions s ON d.driver_id = s.driver_id "
        "WHERE d.driver_id = ?", (driver_id,)
    ).fetchone()
    if not row or row["driver_id"] is None:
        return api_error(ErrorCode.NOT_FOUND, "Driver not found", status=404)
    return api_response(_map_driver(row))


@bp.route("/drivers/<int:driver_id>", methods=["PATCH"])
def patch_driver(driver_id):
    conn = _get_conn()
    row = conn.execute("SELECT * FROM drivers WHERE driver_id = ?", (driver_id,)).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Driver not found", status=404)
    body = request.get_json(silent=True) or {}
    allowed = {"driver_name", "notes"}
    sets, vals = [], []
    for f in allowed:
        if f in body:
            sets.append(f"{f} = ?")
            vals.append(body[f])
    if not sets:
        return api_error(ErrorCode.VALIDATION_ERROR, "No updatable fields", status=400)
    vals.append(driver_id)
    conn.execute(f"UPDATE drivers SET {', '.join(sets)} WHERE driver_id = ?", vals)
    conn.commit()
    updated = conn.execute(
        "SELECT d.*, COUNT(s.session_id) AS session_count, "
        "MIN(s.best_lap_time_s) AS personal_best_s, AVG(s.total_score) AS mean_score "
        "FROM drivers d LEFT JOIN sessions s ON d.driver_id = s.driver_id "
        "WHERE d.driver_id = ?", (driver_id,)
    ).fetchone()
    return api_response(_map_driver(updated))


# ══════════════════════════════════════════════════════════════════
# Tracks
# ══════════════════════════════════════════════════════════════════

def _map_track(row):
    d = dict(row)
    return {
        "id": d["track_id"],
        "name": d["track_name"],
        "lap_length_m": d.get("lap_length_m"),
        "has_joker": bool(d.get("has_joker")),
        "session_count": d.get("session_count", 0),
        "best_time_s": d.get("best_time_s"),
        "created_at": d.get("created_at"),
        "updated_at": d.get("updated_at"),
    }


@bp.route("/tracks", methods=["GET"])
def list_tracks():
    conn = _get_conn()
    rows = conn.execute(Q.SELECT_ALL_TRACKS).fetchall()
    return api_response([_map_track(r) for r in rows])


@bp.route("/tracks/<track_id>", methods=["GET"])
def get_track(track_id):
    conn = _get_conn()
    row = conn.execute(
        "SELECT t.*, COUNT(s.session_id) AS session_count, "
        "MIN(s.best_lap_time_s) AS best_time_s "
        "FROM tracks t LEFT JOIN sessions s ON t.track_id = s.track_id "
        "WHERE t.track_id = ?", (track_id,)
    ).fetchone()
    if not row or row["track_id"] is None:
        return api_error(ErrorCode.NOT_FOUND, "Track not found", status=404)
    return api_response(_map_track(row))


@bp.route("/tracks/<track_id>", methods=["PATCH"])
def patch_track(track_id):
    conn = _get_conn()
    row = conn.execute(Q.SELECT_TRACK_BY_ID, {"track_id": track_id}).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Track not found", status=404)
    body = request.get_json(silent=True) or {}
    allowed = {"track_name", "has_joker", "joker_distance_delta_m", "joker_time_delta_s"}
    sets, vals = [], []
    for f in allowed:
        if f in body:
            sets.append(f"{f} = ?")
            vals.append(body[f])
    if not sets:
        return api_error(ErrorCode.VALIDATION_ERROR, "No updatable fields", status=400)
    sets.append("updated_at = datetime('now')")
    vals.append(track_id)
    conn.execute(f"UPDATE tracks SET {', '.join(sets)} WHERE track_id = ?", vals)
    conn.commit()
    updated = conn.execute(
        "SELECT t.*, COUNT(s.session_id) AS session_count, "
        "MIN(s.best_lap_time_s) AS best_time_s "
        "FROM tracks t LEFT JOIN sessions s ON t.track_id = s.track_id "
        "WHERE t.track_id = ?", (track_id,)
    ).fetchone()
    return api_response(_map_track(updated))
```

Register in `telemetry_tool/web/app.py` — add to `_blueprint_imports` list after data_v2:
```python
('.routes.api_v1_entities',  'bp', 'api_v1_entities_bp'),
```

**Step 4: Run test — expect PASS**

Run: `pytest telemetry_tool/tests/test_entity_api.py -v`

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/api_v1_entities.py telemetry_tool/web/app.py telemetry_tool/tests/test_entity_api.py
git commit -m "feat: add /api/v1/drivers and /api/v1/tracks JSON entity endpoints"
```

---

### Task 4: Entity API — Karts (CRUD + predefined catalog)

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_entities.py`
- Test: `telemetry_tool/tests/test_entity_api_karts.py`

**Context:** `models.py` already has `create_kart()`, `get_kart_by_id()`, `get_all_karts()`, `update_kart()`, `delete_kart()`, `get_predefined_karts_grouped()`. We wrap these in API routes with field name mapping. DELETE must check session count before deleting (safety).

**Step 1: Write test**

```python
"""Tests for /api/v1/karts entity endpoints."""
import sqlite3
import pytest
from db.schema import ensure_schema


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    conn.execute("INSERT INTO drivers (driver_name) VALUES ('Test')")
    conn.execute("INSERT INTO karts (kart_name, manufacturer) VALUES ('K1', 'Tony Kart')")
    conn.commit()
    return conn


@pytest.fixture
def client(db):
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    os.environ.setdefault("TELEMETRY_DB_PATH", ":memory:")
    from web.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    import web.routes.api_v1_entities as ent
    ent._get_conn = lambda: db
    with app.test_client() as c:
        yield c


def test_list_karts(client):
    resp = client.get("/api/v1/karts")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert len(data) >= 1
    assert data[0]["name"] == "K1"


def test_create_kart(client):
    resp = client.post("/api/v1/karts", json={"name": "K2", "manufacturer": "CRG"})
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["name"] == "K2"
    assert data["id"] > 0


def test_create_kart_missing_name(client):
    resp = client.post("/api/v1/karts", json={"manufacturer": "CRG"})
    assert resp.status_code == 400


def test_get_kart_detail(client):
    resp = client.get("/api/v1/karts/1")
    assert resp.status_code == 200
    assert resp.get_json()["data"]["name"] == "K1"


def test_patch_kart(client):
    resp = client.patch("/api/v1/karts/1", json={"notes": "Primary kart"})
    assert resp.status_code == 200
    assert resp.get_json()["data"]["notes"] == "Primary kart"


def test_delete_kart_no_sessions(client):
    resp = client.delete("/api/v1/karts/1")
    assert resp.status_code == 200


def test_delete_kart_with_sessions_blocked(client, db):
    """Karts linked to sessions cannot be deleted."""
    db.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, session_date, kart_id) "
        "VALUES ('s1', 'test.csv', 1, '2026-01-01', 1)"
    )
    db.commit()
    resp = client.delete("/api/v1/karts/1")
    assert resp.status_code == 409  # Conflict


def test_delete_kart_not_found(client):
    resp = client.delete("/api/v1/karts/9999")
    assert resp.status_code == 404
```

**Step 2: Run test — expect FAIL**

Run: `pytest telemetry_tool/tests/test_entity_api_karts.py -v`

**Step 3: Implement**

Add to `api_v1_entities.py`:

```python
import web.models as models

# ══════════════════════════════════════════════════════════════════
# Karts
# ══════════════════════════════════════════════════════════════════

def _map_kart(row):
    d = dict(row) if not isinstance(row, dict) else row
    return {
        "id": d["kart_id"],
        "name": d["kart_name"],
        "manufacturer": d.get("manufacturer"),
        "model": d.get("model"),
        "engine": d.get("engine"),
        "power_hp": d.get("power_hp"),
        "weight_kg": d.get("kart_weight_kg"),
        "notes": d.get("notes"),
        "created_at": d.get("created_at"),
        "session_count": d.get("session_count", 0),
    }


@bp.route("/karts", methods=["GET"])
def list_karts():
    conn = _get_conn()
    rows = models.get_all_karts(conn)
    return api_response([_map_kart(r) for r in rows])


@bp.route("/karts", methods=["POST"])
def create_kart():
    conn = _get_conn()
    body = request.get_json(silent=True) or {}
    name = body.get("name") or body.get("kart_name")
    if not name:
        return api_error(ErrorCode.VALIDATION_ERROR, "name is required", status=400)
    kart_id = models.create_kart(
        conn, kart_name=name,
        predefined_kart_id=body.get("predefined_kart_id"),
        manufacturer=body.get("manufacturer"),
        model=body.get("model"),
        engine=body.get("engine"),
        power_hp=body.get("power_hp"),
        kart_weight_kg=body.get("weight_kg") or body.get("kart_weight_kg"),
        notes=body.get("notes"),
    )
    conn.commit()
    kart = models.get_kart_by_id(conn, kart_id)
    return api_response(_map_kart(kart), status=201)


@bp.route("/karts/<int:kart_id>", methods=["GET"])
def get_kart(kart_id):
    conn = _get_conn()
    kart = models.get_kart_by_id(conn, kart_id)
    if not kart:
        return api_error(ErrorCode.NOT_FOUND, "Kart not found", status=404)
    # Add session count
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM sessions WHERE kart_id = ?", (kart_id,)
    ).fetchone()
    kart["session_count"] = count["c"] if count else 0
    return api_response(_map_kart(kart))


@bp.route("/karts/<int:kart_id>", methods=["PATCH"])
def patch_kart(kart_id):
    conn = _get_conn()
    kart = models.get_kart_by_id(conn, kart_id)
    if not kart:
        return api_error(ErrorCode.NOT_FOUND, "Kart not found", status=404)
    body = request.get_json(silent=True) or {}
    update_data = {}
    if "name" in body: update_data["kart_name"] = body["name"]
    if "kart_name" in body: update_data["kart_name"] = body["kart_name"]
    for f in ("manufacturer", "model", "engine", "power_hp", "notes"):
        if f in body: update_data[f] = body[f]
    if "weight_kg" in body: update_data["kart_weight_kg"] = body["weight_kg"]
    if "kart_weight_kg" in body: update_data["kart_weight_kg"] = body["kart_weight_kg"]
    if not update_data:
        return api_error(ErrorCode.VALIDATION_ERROR, "No updatable fields", status=400)
    models.update_kart(conn, kart_id, update_data)
    conn.commit()
    updated = models.get_kart_by_id(conn, kart_id)
    return api_response(_map_kart(updated))


@bp.route("/karts/<int:kart_id>", methods=["DELETE"])
def delete_kart(kart_id):
    conn = _get_conn()
    kart = models.get_kart_by_id(conn, kart_id)
    if not kart:
        return api_error(ErrorCode.NOT_FOUND, "Kart not found", status=404)
    # Safety: check if any sessions link to this kart
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM sessions WHERE kart_id = ?", (kart_id,)
    ).fetchone()
    if count and count["c"] > 0:
        return api_error(
            ErrorCode.CONFLICT,
            f"Cannot delete kart with {count['c']} linked session(s). Unlink sessions first.",
            status=409,
        )
    conn.execute("DELETE FROM karts WHERE kart_id = ?", (kart_id,))
    conn.commit()
    return api_response({"deleted": True})


@bp.route("/predefined-karts", methods=["GET"])
def list_predefined_karts():
    conn = _get_conn()
    grouped = models.get_predefined_karts_grouped(conn)
    return api_response(grouped)
```

**Step 4: Run test — expect PASS**

Run: `pytest telemetry_tool/tests/test_entity_api_karts.py -v`

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/api_v1_entities.py telemetry_tool/tests/test_entity_api_karts.py
git commit -m "feat: add /api/v1/karts CRUD + predefined-karts catalog endpoint"
```

---

### Task 5: Entity API — Weekends + Leaderboard + Dev Plans

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_entities.py`
- Test: `telemetry_tool/tests/test_entity_api_weekends.py`

**Context:** `queries.py` has `INSERT_WEEKEND`, `UPDATE_WEEKEND`, `DELETE_WEEKEND`, `SELECT_ALL_WEEKENDS`, `SELECT_WEEKEND_BY_ID`, `SELECT_WEEKEND_SESSIONS`, `DELETE_ALL_WEEKEND_SESSIONS`. Dev plans queries: `INSERT_DEVELOPMENT_PLAN`, `SELECT_PLANS_FOR_DRIVER`, `SELECT_PLAN_BY_ID`, `UPDATE_PLAN_PROGRESS`, `DELETE_DEVELOPMENT_PLAN`. Leaderboard is built from session aggregates.

**Step 1: Write test**

```python
"""Tests for weekends, leaderboard, and dev-plans entity APIs."""
import sqlite3
import pytest
from db.schema import ensure_schema


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    conn.execute("INSERT INTO drivers (driver_name) VALUES ('Alice')")
    conn.execute("INSERT INTO tracks (track_id, track_name, lap_length_m) VALUES ('t1', 'Spa', 7004)")
    conn.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, session_date, best_lap_time_s, total_score) "
        "VALUES ('s1', 'test.csv', 1, 't1', '2026-01-01', 88.5, 75.0)"
    )
    conn.commit()
    return conn


@pytest.fixture
def client(db):
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    os.environ.setdefault("TELEMETRY_DB_PATH", ":memory:")
    from web.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    import web.routes.api_v1_entities as ent
    ent._get_conn = lambda: db
    with app.test_client() as c:
        yield c


# ── Weekends ──────────────────────────────────────────────────

def test_list_weekends_empty(client):
    resp = client.get("/api/v1/weekends")
    assert resp.status_code == 200
    assert resp.get_json()["data"] == []


def test_create_weekend(client):
    resp = client.post("/api/v1/weekends", json={
        "name": "Spa Weekend", "track_id": "t1",
        "start_date": "2026-03-01", "end_date": "2026-03-02"
    })
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["name"] == "Spa Weekend"
    assert data["id"] > 0


def test_create_weekend_missing_name(client):
    resp = client.post("/api/v1/weekends", json={"track_id": "t1"})
    assert resp.status_code == 400


def test_get_weekend_detail(client, db):
    db.execute(Q_INSERT_WEEKEND, {"name": "W1", "track_id": "t1",
               "start_date": "2026-03-01", "end_date": "2026-03-02", "notes": None})
    db.commit()
    wid = db.execute("SELECT weekend_id FROM weekends").fetchone()["weekend_id"]
    resp = client.get(f"/api/v1/weekends/{wid}")
    assert resp.status_code == 200


def test_delete_weekend(client, db):
    db.execute(
        "INSERT INTO weekends (name, track_id, start_date, end_date) "
        "VALUES ('W2', 't1', '2026-04-01', '2026-04-02')"
    )
    db.commit()
    wid = db.execute("SELECT weekend_id FROM weekends WHERE name='W2'").fetchone()["weekend_id"]
    resp = client.delete(f"/api/v1/weekends/{wid}")
    assert resp.status_code == 200


# ── Leaderboard ──────────────────────────────────────────────

def test_leaderboard(client):
    resp = client.get("/api/v1/leaderboard")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert len(data) >= 1
    assert data[0]["driver_name"] == "Alice"


def test_leaderboard_with_track_filter(client):
    resp = client.get("/api/v1/leaderboard?track_id=t1")
    assert resp.status_code == 200


# ── Dev Plans ────────────────────────────────────────────────

def test_list_dev_plans_empty(client):
    resp = client.get("/api/v1/dev-plans")
    assert resp.status_code == 200
    assert resp.get_json()["data"] == []


Q_INSERT_WEEKEND = (
    "INSERT INTO weekends (name, track_id, start_date, end_date, notes) "
    "VALUES (:name, :track_id, :start_date, :end_date, :notes)"
)
```

**Step 2: Run test — expect FAIL**

Run: `pytest telemetry_tool/tests/test_entity_api_weekends.py -v`

**Step 3: Implement**

Add weekends, leaderboard, and dev-plans sections to `api_v1_entities.py`:

```python
# ══════════════════════════════════════════════════════════════════
# Weekends
# ══════════════════════════════════════════════════════════════════

def _map_weekend(row):
    d = dict(row) if not isinstance(row, dict) else row
    return {
        "id": d["weekend_id"],
        "name": d["name"],
        "track_id": d.get("track_id"),
        "track_name": d.get("track_name"),
        "start_date": d.get("start_date"),
        "end_date": d.get("end_date"),
        "notes": d.get("notes"),
        "session_count": d.get("session_count", 0),
        "created_at": d.get("created_at"),
    }


@bp.route("/weekends", methods=["GET"])
def list_weekends():
    conn = _get_conn()
    rows = conn.execute(Q.SELECT_ALL_WEEKENDS).fetchall()
    return api_response([_map_weekend(r) for r in rows])


@bp.route("/weekends", methods=["POST"])
def create_weekend():
    conn = _get_conn()
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    if not name:
        return api_error(ErrorCode.VALIDATION_ERROR, "name is required", status=400)
    conn.execute(Q.INSERT_WEEKEND, {
        "name": name,
        "track_id": body.get("track_id"),
        "start_date": body.get("start_date"),
        "end_date": body.get("end_date"),
        "notes": body.get("notes"),
    })
    conn.commit()
    wid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    row = conn.execute(Q.SELECT_WEEKEND_BY_ID, {"weekend_id": wid}).fetchone()
    result = _map_weekend(row)
    result["session_count"] = 0
    return api_response(result, status=201)


@bp.route("/weekends/<int:weekend_id>", methods=["GET"])
def get_weekend(weekend_id):
    conn = _get_conn()
    row = conn.execute(Q.SELECT_WEEKEND_BY_ID, {"weekend_id": weekend_id}).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Weekend not found", status=404)
    result = _map_weekend(row)
    sessions = conn.execute(Q.SELECT_WEEKEND_SESSIONS, {"weekend_id": weekend_id}).fetchall()
    result["sessions"] = [dict(s) for s in sessions]
    result["session_count"] = len(sessions)
    return api_response(result)


@bp.route("/weekends/<int:weekend_id>", methods=["PATCH"])
def patch_weekend(weekend_id):
    conn = _get_conn()
    row = conn.execute(Q.SELECT_WEEKEND_BY_ID, {"weekend_id": weekend_id}).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Weekend not found", status=404)
    body = request.get_json(silent=True) or {}
    current = dict(row)
    conn.execute(Q.UPDATE_WEEKEND, {
        "weekend_id": weekend_id,
        "name": body.get("name", current["name"]),
        "track_id": body.get("track_id", current.get("track_id")),
        "start_date": body.get("start_date", current.get("start_date")),
        "end_date": body.get("end_date", current.get("end_date")),
        "notes": body.get("notes", current.get("notes")),
    })
    conn.commit()
    updated = conn.execute(Q.SELECT_WEEKEND_BY_ID, {"weekend_id": weekend_id}).fetchone()
    return api_response(_map_weekend(updated))


@bp.route("/weekends/<int:weekend_id>", methods=["DELETE"])
def delete_weekend(weekend_id):
    conn = _get_conn()
    row = conn.execute(Q.SELECT_WEEKEND_BY_ID, {"weekend_id": weekend_id}).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Weekend not found", status=404)
    conn.execute(Q.DELETE_ALL_WEEKEND_SESSIONS, {"weekend_id": weekend_id})
    conn.execute(Q.DELETE_WEEKEND, {"weekend_id": weekend_id})
    conn.commit()
    return api_response({"deleted": True})


# ══════════════════════════════════════════════════════════════════
# Leaderboard
# ══════════════════════════════════════════════════════════════════

@bp.route("/leaderboard", methods=["GET"])
def get_leaderboard():
    conn = _get_conn()
    track_id = request.args.get("track_id")
    driver_id = request.args.get("driver_id")
    limit = min(int(request.args.get("limit", 50)), 200)

    where_clauses = ["s.best_lap_time_s IS NOT NULL"]
    params = []
    if track_id:
        where_clauses.append("s.track_id = ?")
        params.append(track_id)
    if driver_id:
        where_clauses.append("s.driver_id = ?")
        params.append(int(driver_id))

    where_sql = " AND ".join(where_clauses)
    params.append(limit)

    rows = conn.execute(f"""
        SELECT s.session_id, s.session_date, s.best_lap_time_s, s.total_score,
               s.track_state, s.n_laps, d.driver_name, t.track_name, t.track_id
        FROM sessions s
        JOIN drivers d ON s.driver_id = d.driver_id
        LEFT JOIN tracks t ON s.track_id = t.track_id
        WHERE {where_sql}
        ORDER BY s.best_lap_time_s ASC
        LIMIT ?
    """, params).fetchall()

    return api_response([dict(r) for r in rows])


# ══════════════════════════════════════════════════════════════════
# Dev Plans
# ══════════════════════════════════════════════════════════════════

@bp.route("/dev-plans", methods=["GET"])
def list_dev_plans():
    conn = _get_conn()
    driver_id = request.args.get("driver_id")
    if driver_id:
        rows = conn.execute(Q.SELECT_PLANS_FOR_DRIVER, {"driver_id": int(driver_id)}).fetchall()
    else:
        rows = conn.execute("SELECT * FROM development_plans ORDER BY created_at DESC").fetchall()
    return api_response([dict(r) for r in rows])


@bp.route("/dev-plans", methods=["POST"])
def create_dev_plan():
    conn = _get_conn()
    body = request.get_json(silent=True) or {}
    driver_id = body.get("driver_id")
    plan_name = body.get("plan_name")
    if not driver_id or not plan_name:
        return api_error(ErrorCode.VALIDATION_ERROR, "driver_id and plan_name required", status=400)
    conn.execute(Q.INSERT_DEVELOPMENT_PLAN, {
        "driver_id": driver_id,
        "plan_name": plan_name,
        "template_id": body.get("template_id"),
        "level": body.get("level", "beginner"),
        "weeks_json": body.get("weeks_json", "[]"),
        "progress_json": body.get("progress_json", "{}"),
    })
    conn.commit()
    plan_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    row = conn.execute(Q.SELECT_PLAN_BY_ID, {"id": plan_id}).fetchone()
    return api_response(dict(row), status=201)


@bp.route("/dev-plans/<int:plan_id>", methods=["GET"])
def get_dev_plan(plan_id):
    conn = _get_conn()
    row = conn.execute(Q.SELECT_PLAN_BY_ID, {"id": plan_id}).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Plan not found", status=404)
    return api_response(dict(row))


@bp.route("/dev-plans/<int:plan_id>", methods=["PATCH"])
def patch_dev_plan(plan_id):
    conn = _get_conn()
    row = conn.execute(Q.SELECT_PLAN_BY_ID, {"id": plan_id}).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Plan not found", status=404)
    body = request.get_json(silent=True) or {}
    if "progress_json" in body:
        conn.execute(Q.UPDATE_PLAN_PROGRESS, {"id": plan_id, "progress_json": body["progress_json"]})
    conn.commit()
    updated = conn.execute(Q.SELECT_PLAN_BY_ID, {"id": plan_id}).fetchone()
    return api_response(dict(updated))


@bp.route("/dev-plans/<int:plan_id>", methods=["DELETE"])
def delete_dev_plan(plan_id):
    conn = _get_conn()
    row = conn.execute(Q.SELECT_PLAN_BY_ID, {"id": plan_id}).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Plan not found", status=404)
    conn.execute(Q.DELETE_DEVELOPMENT_PLAN, {"id": plan_id})
    conn.commit()
    return api_response({"deleted": True})
```

**Step 4: Run test — expect PASS**

Run: `pytest telemetry_tool/tests/test_entity_api_weekends.py -v`

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/api_v1_entities.py telemetry_tool/tests/test_entity_api_weekends.py
git commit -m "feat: add weekends, leaderboard, dev-plans entity API endpoints"
```

---

### Task 6: Upload Flow — kart_id Support

**Files:**
- Modify: `telemetry_tool/web/routes/sessions_v2.py` (upload endpoint)
- Modify: `telemetry_tool/web/models.py` (upsert_session kart_id param)
- Test: `telemetry_tool/tests/test_upload_kart_id.py`

**Context:** The upload endpoint at `sessions_v2.py` accepts multipart form data. Currently accepts `driver_name`, `session_type`, `track_state`, `lap_range`, `exclude_laps`. We add optional `kart_id`. The `upsert_session()` function in `models.py` builds the INSERT params dict — it needs to include `kart_id` from `session_meta`.

**Step 1: Write test**

```python
"""Test upload flow with optional kart_id."""
import sqlite3
import pytest
from db.schema import ensure_schema


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    conn.execute("INSERT INTO drivers (driver_name) VALUES ('Unknown')")
    conn.execute("INSERT INTO karts (kart_name) VALUES ('TestKart')")
    conn.commit()
    return conn


def test_upload_meta_includes_kart_id(db):
    """When kart_id is in session_meta, upsert_session stores it."""
    from web.models import upsert_session
    summary = {
        "csv_path": "test.csv",
        "session_id": "test-upload-kart",
        "n_laps": 5,
        "best_lap_time_s": 88.0,
        "mean_lap_time_s": 89.0,
        "total_score": 75.0,
        "grade": "B",
    }
    meta = {
        "session_type": "practice",
        "track_state": "dry",
        "driver_name": "Unknown",
        "kart_id": 1,
    }
    upsert_session(db, summary, meta)
    db.commit()
    row = db.execute("SELECT kart_id FROM sessions WHERE session_id='test-upload-kart'").fetchone()
    assert row["kart_id"] == 1


def test_upload_meta_without_kart_id(db):
    """When kart_id is not in session_meta, kart_id is NULL."""
    from web.models import upsert_session
    summary = {
        "csv_path": "test2.csv",
        "session_id": "test-upload-no-kart",
        "n_laps": 3,
    }
    meta = {"session_type": "practice", "track_state": "dry", "driver_name": "Unknown"}
    upsert_session(db, summary, meta)
    db.commit()
    row = db.execute("SELECT kart_id FROM sessions WHERE session_id='test-upload-no-kart'").fetchone()
    assert row["kart_id"] is None
```

**Step 2: Run test — expect FAIL**

Run: `pytest telemetry_tool/tests/test_upload_kart_id.py -v`

**Step 3: Implement**

In `sessions_v2.py`, read `kart_id` from form data and add to `session_meta`:
```python
# After the existing form field parsing:
kart_id_str = request.form.get("kart_id")
if kart_id_str:
    session_meta["kart_id"] = int(kart_id_str)
```

In `models.py:upsert_session()`, add `kart_id` to the params dict:
```python
"kart_id": meta.get("kart_id"),
```

**Step 4: Run test — expect PASS**

Run: `pytest telemetry_tool/tests/test_upload_kart_id.py -v`

**Step 5: Run all tests**

Run: `pytest telemetry_tool/tests/ -v`

**Step 6: Commit**

```bash
git add telemetry_tool/web/routes/sessions_v2.py telemetry_tool/web/models.py telemetry_tool/tests/test_upload_kart_id.py
git commit -m "feat: accept optional kart_id in session upload flow"
```

---

### Task 7: Update Truth Dashboard Probes

**Files:**
- Modify: `docs/audit-truth-dashboard.html`

**Context:** Add probes for checkpoint 2 verification: entity list endpoints return data, session PATCH persists, kart field works.

**Step 1: Add new probes to CONFLICTS array**

Add probes 7-9:
- Probe 7: Entity Lists — GET /api/v1/drivers, /api/v1/tracks, /api/v1/karts return non-empty arrays
- Probe 8: Session Edit — PATCH /api/v1/sessions/:id with valid data persists and returns resolved names
- Probe 9: Kart Safety — DELETE /api/v1/karts/:id blocked when sessions linked

**Step 2: Test locally**

Open dashboard, set API to `http://127.0.0.1:5000`, provide session ID, run probes.

**Step 3: Commit**

```bash
git add docs/audit-truth-dashboard.html
git commit -m "feat: add checkpoint 2 probes to truth dashboard (entity lists, PATCH, kart safety)"
```

---

### Task 8: Integration Test — Full Checkpoint 2 Verification

**Files:**
- Test: `telemetry_tool/tests/test_checkpoint2_integration.py`

**Step 1: Write integration test**

```python
"""Checkpoint 2 integration: entity APIs work end-to-end after upload."""
import sqlite3
import pytest
from db.schema import ensure_schema


@pytest.fixture
def seeded_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    conn.execute("INSERT INTO drivers (driver_name) VALUES ('Alice')")
    conn.execute("INSERT INTO tracks (track_id, track_name, lap_length_m) VALUES ('t1', 'Spa', 7004)")
    conn.execute("INSERT INTO karts (kart_name, manufacturer) VALUES ('K1', 'Tony Kart')")
    conn.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, session_date, "
        "best_lap_time_s, total_score, kart_id) "
        "VALUES ('s1', 'test.csv', 1, 't1', '2026-01-01', 88.5, 75.0, 1)"
    )
    conn.commit()
    return conn


@pytest.fixture
def client(seeded_db):
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    os.environ.setdefault("TELEMETRY_DB_PATH", ":memory:")
    from web.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    import web.routes.api_v1_entities as ent
    import web.routes.data_v2 as dv2
    ent._get_conn = lambda: seeded_db
    dv2.get_db_connection = lambda: seeded_db
    with app.test_client() as c:
        yield c


def test_drivers_list_populated(client):
    resp = client.get("/api/v1/drivers")
    data = resp.get_json()["data"]
    assert len(data) >= 1
    assert data[0]["session_count"] >= 1


def test_tracks_list_populated(client):
    resp = client.get("/api/v1/tracks")
    data = resp.get_json()["data"]
    assert len(data) >= 1
    assert data[0]["session_count"] >= 1


def test_karts_list_populated(client):
    resp = client.get("/api/v1/karts")
    data = resp.get_json()["data"]
    assert len(data) >= 1
    assert data[0]["session_count"] >= 1


def test_session_patch_persists(client):
    resp = client.patch("/api/v1/sessions/s1", json={"display_name": "My Race"})
    assert resp.status_code == 200
    assert resp.get_json()["data"]["display_name"] == "My Race"


def test_session_patch_returns_resolved_names(client):
    resp = client.patch("/api/v1/sessions/s1", json={"notes": "test"})
    data = resp.get_json()["data"]
    assert "driver_name" in data
    assert "track_name" in data


def test_leaderboard_returns_data(client):
    resp = client.get("/api/v1/leaderboard")
    data = resp.get_json()["data"]
    assert len(data) >= 1


def test_weekends_empty_state(client):
    resp = client.get("/api/v1/weekends")
    assert resp.status_code == 200
    assert resp.get_json()["data"] == []


def test_no_404s_for_entity_endpoints(client):
    """All entity list endpoints return 200, not 404."""
    for path in ["/api/v1/drivers", "/api/v1/tracks", "/api/v1/karts",
                 "/api/v1/weekends", "/api/v1/leaderboard", "/api/v1/dev-plans"]:
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} returned {resp.status_code}"
```

**Step 2: Run test — expect PASS** (all prior tasks implemented)

Run: `pytest telemetry_tool/tests/test_checkpoint2_integration.py -v`

**Step 3: Commit**

```bash
git add telemetry_tool/tests/test_checkpoint2_integration.py
git commit -m "test: checkpoint 2 integration — entity APIs, PATCH, leaderboard, no 404s"
```
