# Audit Checkpoint 1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 5 audit truth failures — API JSON contract, error hardening, session identity, date correctness, driver/track resolution.

**Architecture:** Middleware-first approach. Single `after_request` guard catches HTML on `/api/*`. Extend existing `available:false+reason_code` pattern to all computed-data endpoints. Alembic 023 adds session identity columns. Upload endpoint populates new fields.

**Tech Stack:** Python/Flask, SQLite/PostgreSQL, Alembic, pytest

---

### Task 1: API JSON Contract Guard

**Files:**
- Modify: `telemetry_tool/web/app.py:415-421` (after `set_cache_headers`)
- Modify: `telemetry_tool/web/middleware/legacy_guard.py:7,42`
- Test: `telemetry_tool/tests/test_api_json_guard.py`

**Step 1: Write the failing test**

```python
# telemetry_tool/tests/test_api_json_guard.py
"""Tests for API JSON contract enforcement."""
import json
import pytest
from web.app import create_app


@pytest.fixture
def app():
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_api_404_returns_json(client):
    """GET /api/v1/nonexistent must return JSON, not HTML."""
    resp = client.get("/api/v1/nonexistent")
    assert resp.content_type.startswith("application/json"), \
        f"Expected JSON, got {resp.content_type}"
    body = resp.get_json()
    assert body["ok"] is False
    assert "request_id" in body.get("meta", {}) or body.get("meta") is not None


def test_api_error_includes_request_id(client):
    """Every API error must include meta.request_id."""
    resp = client.get("/api/v1/nonexistent")
    body = resp.get_json()
    assert body.get("meta", {}).get("request_id") is not None


def test_html_guard_catches_html_on_api_path(app):
    """If a route accidentally returns HTML on /api/*, the guard rewrites it."""
    # Register a deliberately broken route that returns HTML
    @app.route("/api/v1/_test_html_leak")
    def _leak_html():
        return "<!DOCTYPE html><html><body>oops</body></html>", 200

    with app.test_client() as c:
        resp = c.get("/api/v1/_test_html_leak")
        assert resp.content_type.startswith("application/json"), \
            f"Guard should rewrite HTML to JSON, got {resp.content_type}"
        body = resp.get_json()
        assert body["ok"] is False
        assert body["error"]["code"] == "API_HTML_RESPONSE"


def test_html_guard_allows_attachment_downloads(app):
    """Report download (Content-Disposition: attachment) is exempt from guard."""
    from flask import send_file
    import io

    @app.route("/api/v1/_test_attachment")
    def _attachment():
        buf = io.BytesIO(b"<html>report</html>")
        return send_file(buf, mimetype="text/html", as_attachment=True,
                         download_name="report.html")

    with app.test_client() as c:
        resp = c.get("/api/v1/_test_attachment")
        assert resp.content_type.startswith("text/html"), \
            "Attachment should NOT be rewritten"
        assert "attachment" in resp.headers.get("Content-Disposition", "")
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_api_json_guard.py -v`
Expected: `test_html_guard_catches_html_on_api_path` FAIL (guard doesn't exist yet)

**Step 3: Implement the JSON guard and fix legacy_guard**

In `telemetry_tool/web/app.py`, add after the `set_cache_headers` after_request hook (around line 421):

```python
    # Guard: ensure /api/* never returns HTML to JSON consumers.
    @app.after_request
    def _guard_api_json_contract(response):
        if not request.path.startswith("/api/"):
            return response
        # Exempt file-download responses (report endpoint).
        if "attachment" in (response.headers.get("Content-Disposition") or ""):
            return response
        ct = response.content_type or ""
        if "text/html" in ct:
            # Replace with structured JSON error.
            from .api_utils import api_error as _err, ErrorCode as _ec
            err_resp = _err(
                "API_HTML_RESPONSE",
                "Endpoint returned HTML instead of JSON",
                status=500,
            )
            # _err returns (response, status) tuple
            if isinstance(err_resp, tuple):
                return err_resp[0]
            return err_resp
        # Also catch responses where body starts with HTML even if
        # content_type was not set properly.
        if response.content_length and response.content_length < 10000:
            try:
                data = response.get_data(as_text=True)[:50]
                if data.lstrip().startswith(("<!DOCTYPE", "<html", "<HTML")):
                    from .api_utils import api_error as _err
                    err_resp = _err(
                        "API_HTML_RESPONSE",
                        "Endpoint returned HTML instead of JSON",
                        status=500,
                    )
                    if isinstance(err_resp, tuple):
                        return err_resp[0]
                    return err_resp
            except Exception:
                pass
        return response
```

In `telemetry_tool/web/middleware/legacy_guard.py` line 7 and 42:

```python
# Line 7: change import
from flask import request
from web.api_utils import api_error, ErrorCode

# Line 42: change return
            return api_error(ErrorCode.NOT_FOUND, "Not found", status=404)
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_api_json_guard.py -v`
Expected: all 4 tests PASS

**Step 5: Commit**

```bash
git add telemetry_tool/tests/test_api_json_guard.py telemetry_tool/web/app.py telemetry_tool/web/middleware/legacy_guard.py
git commit -m "feat: enforce JSON contract on /api/* routes, fix legacy_guard envelope"
```

---

### Task 2: Error Hardening — Structured Unavailability

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py` (lines 697-699, 730-732, 933-935, 955-958, 967-968, 998-1000, 1059-1065, 1111-1113, 1154-1156, 1301-1314)
- Test: `telemetry_tool/tests/test_structured_unavailability.py`

**Step 1: Write the failing test**

```python
# telemetry_tool/tests/test_structured_unavailability.py
"""Tests that optional data endpoints return structured unavailability, not 404/500."""
import json
import pytest
import sqlite3
from db.schema import ensure_schema
from web.app import create_app


@pytest.fixture
def test_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    # Insert minimal driver + session (no computed data)
    conn.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')")
    conn.execute("""
        INSERT INTO sessions (session_id, csv_filename, driver_id, session_type,
                              track_state, session_date)
        VALUES ('test-sess-001', 'test.csv', 1, 'practice', 'dry', '2026-03-01')
    """)
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def client(test_db):
    import os
    os.environ["TELEMETRY_DB_PATH"] = test_db
    os.environ.pop("USE_PG", None)
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


# Endpoints that must return 200 + available:false when data is missing
_UNAVAILABLE_ENDPOINTS = [
    "/api/v1/sessions/test-sess-001/theoretical",
    "/api/v1/sessions/test-sess-001/reference_line",
    "/api/v1/sessions/test-sess-001/fingerprint",
    "/api/v1/sessions/test-sess-001/driving-style",
    "/api/v1/sessions/test-sess-001/lap-distribution",
    "/api/v1/sessions/test-sess-001/lap-progress",
    "/api/v1/sessions/test-sess-001/stint-analysis",
]


@pytest.mark.parametrize("path", _UNAVAILABLE_ENDPOINTS)
def test_missing_computed_data_returns_structured_unavailability(client, path):
    """Optional data endpoint must return 200 + available:false, not 404."""
    resp = client.get(path)
    assert resp.status_code == 200, f"{path} returned {resp.status_code}"
    body = resp.get_json()
    assert body["ok"] is True, f"{path} returned ok:false"
    assert body["data"]["available"] is False, f"{path} missing available:false"
    assert "reason_code" in body["data"], f"{path} missing reason_code"


def test_nonexistent_session_still_returns_404(client):
    """Truly missing session must still 404."""
    resp = client.get("/api/v1/sessions/does-not-exist/theoretical")
    assert resp.status_code == 404
    body = resp.get_json()
    assert body["ok"] is False
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_structured_unavailability.py -v`
Expected: parametrized tests FAIL with 404 (current behavior)

**Step 3: Convert endpoints to structured unavailability**

In `telemetry_tool/web/routes/data_v2.py`, replace each "computed data not found" 404 with the `available:false` pattern. Each change follows the same structure:

**`get_theoretical` (lines 697-699):**
```python
    if theo is None:
        return api_response({
            "available": False,
            "reason_code": "no_theoretical_data",
            "message": "Theoretical lap not computed for this session",
        })
```

**`get_reference_line` (lines 730-732):**
```python
    if ref is None:
        return api_response({
            "available": False,
            "reason_code": "no_reference_line",
            "message": "Reference line not computed for this session",
        })
```

**`get_best_lap_gps` (lines 753, 757-758):**
```python
    if lap_num is None:
        return api_response({
            "available": False,
            "reason_code": "no_laps",
            "message": "No laps available for this session",
        })
    # ...
    if trace is None:
        return api_response({
            "available": False,
            "reason_code": "no_gps_trace",
            "message": f"No GPS trace for best lap {lap_num}",
        })
```

**`get_delta` (lines 933-935, 955-958, 967-968):**
Keep validation errors (400) as-is. Change only the trace/data-not-found cases:
```python
    if trace_a is None or trace_b is None:
        return api_response({
            "available": False,
            "reason_code": "no_gps_trace",
            "message": "GPS trace not found for one or both laps",
        })
    # ...
    if not dist_a or not spd_a or not dist_b or not spd_b:
        return api_response({
            "available": False,
            "reason_code": "insufficient_trace_data",
            "message": "Insufficient trace data for delta computation",
        })
    # ...
    if max_dist <= 0:
        return api_response({
            "available": False,
            "reason_code": "no_valid_distance",
            "message": "No valid distance range for delta",
        })
```

**`get_fingerprint` (lines 998-1000):**
```python
    if scores is None:
        return api_response({
            "available": False,
            "reason_code": "no_score_data",
            "message": "No score data for fingerprint",
        })
```

**`get_driving_style` (lines 1059-1065):**
```python
    if not driver_id:
        return api_response({
            "available": False,
            "reason_code": "no_driver_linked",
            "message": "No driver linked to this session",
        })

    style = models.get_driving_style(conn, driver_id, session_id)
    if style is None:
        return api_response({
            "available": False,
            "reason_code": "no_driving_style",
            "message": "Driving style not computed for this session",
        })
```

**`get_lap_distribution` (lines 1111-1113):**
```python
    if not valid_times:
        return api_response({
            "available": False,
            "reason_code": "no_valid_lap_times",
            "message": "No valid lap times for distribution",
        })
```

**`get_lap_progress` (lines 1154-1156):**
```python
    if not valid:
        return api_response({
            "available": False,
            "reason_code": "no_valid_lap_times",
            "message": "No valid lap times for progress",
        })
```

**`get_speed_profile` (lines 1203, 1207-1208):**
```python
    if lap_num is None:
        return api_response({
            "available": False,
            "reason_code": "no_laps",
            "message": "No laps available",
        })
    # ...
    if trace is None:
        return api_response({
            "available": False,
            "reason_code": "no_gps_trace",
            "message": f"No trace for lap {lap_num}",
        })
```

**`get_stint_analysis` (lines 1313-1314):**
```python
    return api_response({
        "available": False,
        "reason_code": "no_stint_analysis",
        "message": "No stint analysis for this session",
        "stints": [],
    })
```

**`get_track_map` (line 1381):**
```python
    if best_lap is None:
        return api_response({
            "available": False,
            "reason_code": "no_laps",
            "message": "No laps available",
        })
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_structured_unavailability.py -v`
Expected: all tests PASS

**Step 5: Also run existing tests to check for regressions**

Run: `cd telemetry_tool && python -m pytest tests/test_data_api_v2.py -v`
Expected: all existing tests still PASS

**Step 6: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py telemetry_tool/tests/test_structured_unavailability.py
git commit -m "fix: return structured unavailability (200+reason_code) for optional data endpoints"
```

---

### Task 3: Session Identity Schema — Alembic 023 + SQLite

**Files:**
- Create: `telemetry_tool/alembic/versions/023_session_identity.py`
- Modify: `telemetry_tool/db/schema.py:56-76` (sessions table)
- Modify: `telemetry_tool/db/queries.py:12-26` (INSERT_SESSION)
- Test: `telemetry_tool/tests/test_session_identity.py`

**Step 1: Write the failing test**

```python
# telemetry_tool/tests/test_session_identity.py
"""Tests for session identity columns (display_name, source_filename, source_path)."""
import sqlite3
import pytest
from db.schema import ensure_schema


@pytest.fixture
def test_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    return conn


def test_session_table_has_identity_columns(test_db):
    """Schema must include display_name, source_filename, source_path."""
    cursor = test_db.execute("PRAGMA table_info(sessions)")
    cols = {row["name"] for row in cursor.fetchall()}
    assert "display_name" in cols, "Missing display_name column"
    assert "source_filename" in cols, "Missing source_filename column"
    assert "source_path" in cols, "Missing source_path column"


def test_insert_session_with_identity_fields(test_db):
    """Can insert a session with the new identity columns."""
    test_db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')")
    test_db.execute("""
        INSERT INTO sessions (session_id, csv_filename, driver_id,
                              session_type, track_state, session_date,
                              display_name, source_filename, source_path)
        VALUES ('s1', 'OK_R3.csv', 1, 'practice', 'dry', '2026-03-01',
                'OK_R3', 'OK_R3.csv', '/tmp/telemetry_upload_xyz/OK_R3.csv')
    """)
    test_db.commit()
    row = test_db.execute("SELECT * FROM sessions WHERE session_id = 's1'").fetchone()
    assert row["display_name"] == "OK_R3"
    assert row["source_filename"] == "OK_R3.csv"
    assert row["source_path"] == "/tmp/telemetry_upload_xyz/OK_R3.csv"


def test_display_name_defaults_to_null(test_db):
    """display_name should be NULL if not provided (backwards compat)."""
    test_db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')")
    test_db.execute("""
        INSERT INTO sessions (session_id, csv_filename, driver_id,
                              session_type, track_state, session_date)
        VALUES ('s2', 'test.csv', 1, 'practice', 'dry', '2026-03-01')
    """)
    row = test_db.execute("SELECT display_name FROM sessions WHERE session_id = 's2'").fetchone()
    assert row["display_name"] is None
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_session_identity.py -v`
Expected: FAIL — columns don't exist yet

**Step 3: Add columns to SQLite schema**

In `telemetry_tool/db/schema.py`, add three columns to `_SESSIONS_TABLE` before the `created_at` line:

```python
    display_name      TEXT,
    source_filename   TEXT,
    source_path       TEXT,
    created_at        TEXT    NOT NULL DEFAULT (datetime('now'))
```

**Step 4: Create Alembic migration 023**

```python
# telemetry_tool/alembic/versions/023_session_identity.py
"""Add session identity columns.

Revision ID: 023
Revises: 022
Create Date: 2026-03-01
"""
from alembic import op
import sqlalchemy as sa

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sessions", sa.Column("display_name", sa.Text(), nullable=True))
    op.add_column("sessions", sa.Column("source_filename", sa.Text(), nullable=True))
    op.add_column("sessions", sa.Column("source_path", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("sessions", "source_path")
    op.drop_column("sessions", "source_filename")
    op.drop_column("sessions", "display_name")
```

**Step 5: Update INSERT_SESSION query**

In `telemetry_tool/db/queries.py`, add the new columns to `INSERT_SESSION`:

```python
INSERT_SESSION = """
INSERT OR REPLACE INTO sessions (
    session_id, csv_filename, driver_id, track_id,
    session_type, track_state, session_date,
    n_laps, best_lap_time_s, mean_lap_time_s,
    total_score, grade, weather_json, notes,
    html_report_path, simulation_method, joker_lap_number,
    display_name, source_filename, source_path
) VALUES (
    :session_id, :csv_filename, :driver_id, :track_id,
    :session_type, :track_state, :session_date,
    :n_laps, :best_lap_time_s, :mean_lap_time_s,
    :total_score, :grade, :weather_json, :notes,
    :html_report_path, :simulation_method, :joker_lap_number,
    :display_name, :source_filename, :source_path
);
"""
```

**Step 6: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_session_identity.py -v`
Expected: all 3 tests PASS

**Step 7: Commit**

```bash
git add telemetry_tool/db/schema.py telemetry_tool/db/queries.py \
    telemetry_tool/alembic/versions/023_session_identity.py \
    telemetry_tool/tests/test_session_identity.py
git commit -m "feat: add session identity columns (display_name, source_filename, source_path)"
```

---

### Task 4: Wire Identity + Date into Upload & API

**Files:**
- Modify: `telemetry_tool/web/models.py:348-366` (upsert_session)
- Modify: `telemetry_tool/web/routes/sessions_v2.py:248-256,318` (upload_session)
- Modify: `telemetry_tool/web/routes/data_v2.py:221-227` (get_session)
- Modify: `telemetry_tool/web/routes/data_v2.py:626-628` (_UPDATABLE_FIELDS)
- Test: `telemetry_tool/tests/test_session_identity_api.py`

**Step 1: Write the failing test**

```python
# telemetry_tool/tests/test_session_identity_api.py
"""Tests that upload populates identity fields and API exposes them correctly."""
import json
import sqlite3
import pytest
from db.schema import ensure_schema
from web.app import create_app


@pytest.fixture
def test_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    conn.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')")
    conn.execute("""
        INSERT INTO sessions (session_id, csv_filename, driver_id,
                              session_type, track_state, session_date,
                              display_name, source_filename)
        VALUES ('test-001', 'OK_R3.csv', 1, 'practice', 'dry', '2026-03-01',
                'OK_R3', 'OK_R3.csv')
    """)
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def client(test_db):
    import os
    os.environ["TELEMETRY_DB_PATH"] = test_db
    os.environ.pop("USE_PG", None)
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_session_detail_returns_display_name(client):
    """GET /sessions/<id> must return display_name, not raw path."""
    resp = client.get("/api/v1/sessions/test-001")
    body = resp.get_json()
    assert body["ok"] is True
    # display_name should be present (or derived from csv_filename)
    data = body["data"]
    # csv_filename must not contain path separators
    assert "/" not in (data.get("csv_filename") or ""), \
        "csv_filename should not contain path separators"
    assert "\\" not in (data.get("csv_filename") or ""), \
        "csv_filename should not contain path separators"
    # source_path must NOT be exposed
    assert "source_path" not in data, "source_path must never be in API response"


def test_session_detail_never_exposes_source_path(client):
    """source_path is internal-only and must be stripped from API responses."""
    resp = client.get("/api/v1/sessions/test-001")
    body = resp.get_json()
    data = body["data"]
    assert "source_path" not in data


def test_patch_session_display_name(client):
    """PATCH /sessions/<id> should accept display_name update."""
    resp = client.patch(
        "/api/v1/sessions/test-001",
        data=json.dumps({"display_name": "My Best Session"}),
        content_type="application/json",
    )
    body = resp.get_json()
    assert body["ok"] is True

    # Verify it stuck
    resp2 = client.get("/api/v1/sessions/test-001")
    body2 = resp2.get_json()
    assert body2["data"].get("display_name") == "My Best Session"


def test_patch_session_track_id(client):
    """PATCH /sessions/<id> should accept track_id override."""
    resp = client.patch(
        "/api/v1/sessions/test-001",
        data=json.dumps({"track_id": "adria-karting"}),
        content_type="application/json",
    )
    body = resp.get_json()
    assert body["ok"] is True
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_session_identity_api.py -v`
Expected: FAIL

**Step 3: Update upsert_session in models.py**

In `telemetry_tool/web/models.py`, update the `upsert_session` function (around line 348-366) to populate the new fields:

```python
    conn.execute(Q.INSERT_SESSION, {
        "session_id":        session_id,
        "csv_filename":      Path(str(summary.get("csv_path", ""))).name,  # filename only!
        "driver_id":         driver_id,
        "track_id":          summary.get("track_id"),
        "session_type":      meta.get("session_type", "practice"),
        "track_state":       meta.get("track_state", "dry"),
        "session_date":      meta.get("session_date") or meta.get("date") or session_id[:10],
        "n_laps":            n_laps,
        "best_lap_time_s":   _safe_float(best_s),
        "mean_lap_time_s":   _safe_float(mean_s),
        "total_score":       _safe_float(score.get("total_score")),
        "grade":             score.get("grade"),
        "weather_json":      weather_json,
        "notes":             meta.get("notes"),
        "html_report_path":  html_path,
        "simulation_method": theo_metrics.get("simulation_method"),
        "joker_lap_number":  _joker_lap,
        "display_name":      meta.get("display_name") or Path(str(summary.get("csv_path", ""))).stem,
        "source_filename":   meta.get("source_filename") or Path(str(summary.get("csv_path", ""))).name,
        "source_path":       str(summary.get("csv_path", "")),
    })
```

Add `from pathlib import Path` to imports at top of models.py if not present.

**Step 4: Update get_session to strip source_path**

In `telemetry_tool/web/routes/data_v2.py`, update `get_session` (line 221-227):

```python
def get_session(session_id: str):
    """Return a single session by ID."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)
    # Strip internal fields — never expose server paths
    result = dict(session)
    result.pop("source_path", None)
    result.pop("html_report_path", None)
    # Ensure csv_filename is just the filename, not a path
    if result.get("csv_filename"):
        result["csv_filename"] = Path(result["csv_filename"]).name
    return api_response(result)
```

Add `from pathlib import Path` to imports at top of data_v2.py (line 31 area).

**Step 5: Update _UPDATABLE_FIELDS to include display_name and track_id**

In `telemetry_tool/web/routes/data_v2.py` line 628:

```python
_UPDATABLE_FIELDS = {"session_type", "track_state", "notes", "display_name", "track_id"}
```

**Step 6: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_session_identity_api.py -v`
Expected: all 4 tests PASS

**Step 7: Run existing tests for regression**

Run: `cd telemetry_tool && python -m pytest tests/ -v --timeout=60`
Expected: no regressions

**Step 8: Commit**

```bash
git add telemetry_tool/web/models.py telemetry_tool/web/routes/data_v2.py \
    telemetry_tool/tests/test_session_identity_api.py
git commit -m "feat: wire session identity fields into upload/API, strip source_path from responses"
```

---

### Task 5: Session Date from Telemetry + Driver/Track Resolution

**Files:**
- Modify: `telemetry_tool/web/routes/sessions_v2.py:259-263,282-285,288-316` (upload_session)
- Modify: `telemetry_tool/web/models.py:348-366` (upsert_session session_date derivation)
- Test: `telemetry_tool/tests/test_session_date_resolution.py`

**Step 1: Write the failing test**

```python
# telemetry_tool/tests/test_session_date_resolution.py
"""Tests for session_date derivation and driver/track resolution."""
import sqlite3
import pytest
from pathlib import Path
from db.schema import ensure_schema


@pytest.fixture
def test_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    return conn


def test_session_date_from_telemetry_timestamps(test_db):
    """session_date should come from telemetry start_time, not upload time."""
    from web.models import upsert_session, upsert_driver

    driver_id = upsert_driver(test_db, "Test Driver")

    summary = {
        "csv_path": "/tmp/test.csv",
        "session_meta": {
            "session_type": "practice",
            "track_state": "dry",
            "driver_name": "Test Driver",
        },
        "session_context": None,
        "score_result": {},
        "lap_times": [60.0, 61.0],
        "resampled_laps": {},
        "telemetry_start_time": "2026-02-15T14:30:00",
    }

    session_id = upsert_session(test_db, summary, driver_id)
    test_db.commit()

    row = test_db.execute(
        "SELECT session_date, created_at FROM sessions WHERE session_id = ?",
        (session_id,)
    ).fetchone()

    # session_date should be 2026-02-15 (from telemetry), not today
    assert row["session_date"].startswith("2026-02-15"), \
        f"session_date should be from telemetry, got {row['session_date']}"
    # created_at should be today (upload time)
    assert row["created_at"] is not None


def test_track_null_when_detection_fails(test_db):
    """track_id should be NULL when detection fails, not a stale placeholder."""
    from web.models import upsert_session, upsert_driver

    driver_id = upsert_driver(test_db, "Test Driver")
    summary = {
        "csv_path": "/tmp/test.csv",
        "session_meta": {"session_type": "practice", "track_state": "dry"},
        "session_context": None,
        "score_result": {},
        "lap_times": [60.0],
        "resampled_laps": {},
        "track_id": None,  # detection failed
    }

    session_id = upsert_session(test_db, summary, driver_id)
    test_db.commit()

    row = test_db.execute(
        "SELECT track_id FROM sessions WHERE session_id = ?",
        (session_id,)
    ).fetchone()
    assert row["track_id"] is None, "track_id should be NULL when detection fails"


def test_driver_from_upload_form_takes_precedence(test_db):
    """Driver from upload form should take precedence over pipeline default."""
    from web.models import upsert_session, upsert_driver

    driver_id = upsert_driver(test_db, "Form Driver")
    summary = {
        "csv_path": "/tmp/test.csv",
        "session_meta": {
            "session_type": "practice",
            "track_state": "dry",
            "driver_name": "Pipeline Default",  # would be ignored
        },
        "session_context": None,
        "score_result": {},
        "lap_times": [60.0],
        "resampled_laps": {},
    }

    session_id = upsert_session(test_db, summary, driver_id)
    test_db.commit()

    row = test_db.execute(
        "SELECT driver_id FROM sessions WHERE session_id = ?",
        (session_id,)
    ).fetchone()
    assert row["driver_id"] == driver_id
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_session_date_resolution.py -v`
Expected: `test_session_date_from_telemetry_timestamps` FAIL (currently uses session_id[:10] fallback)

**Step 3: Update upsert_session to derive session_date from telemetry**

In `telemetry_tool/web/models.py`, update the `session_date` derivation in `upsert_session` (around line 355):

```python
    # Derive session_date: prefer telemetry start time > meta date > session_id prefix
    session_date = None
    telemetry_start = summary.get("telemetry_start_time")
    if telemetry_start and isinstance(telemetry_start, str):
        session_date = telemetry_start[:10]  # "YYYY-MM-DD"
    if not session_date:
        session_date = meta.get("session_date") or meta.get("date")
    if not session_date:
        session_date = session_id[:10]
```

Then use `session_date` in the INSERT params.

**Step 4: Update upload_session to pass source metadata**

In `telemetry_tool/web/routes/sessions_v2.py`, after saving to temp (around line 250-263):

```python
        # ── 3. Build session metadata ─────────────────────────────
        session_meta: dict = {
            "session_type": request.form.get("session_type", "practice"),
            "track_state": request.form.get("track_state", "dry"),
            "driver_name": request.form.get("driver_name", "Unknown"),
            "source_filename": safe_name,
            "display_name": Path(safe_name).stem,
        }
```

**Step 5: Extract telemetry start time after pipeline runs**

In `telemetry_tool/web/routes/sessions_v2.py`, after `summary = run_full_analysis(...)` (around line 278-280):

```python
        # Extract telemetry start time for session_date derivation.
        # The pipeline puts this in session_context or resampled_laps metadata.
        _telem_start = None
        _ctx = summary.get("session_context")
        if _ctx and hasattr(_ctx, "start_time"):
            _telem_start = str(_ctx.start_time)
        elif summary.get("session_meta", {}).get("start_time"):
            _telem_start = str(summary["session_meta"]["start_time"])
        if _telem_start:
            summary["telemetry_start_time"] = _telem_start
```

**Step 6: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_session_date_resolution.py -v`
Expected: all 3 tests PASS

**Step 7: Run full test suite**

Run: `cd telemetry_tool && python -m pytest tests/ -v --timeout=60`
Expected: no regressions

**Step 8: Commit**

```bash
git add telemetry_tool/web/models.py telemetry_tool/web/routes/sessions_v2.py \
    telemetry_tool/tests/test_session_date_resolution.py
git commit -m "fix: derive session_date from telemetry timestamps, fix driver/track resolution"
```

---

### Task 6: Checkpoint Verification

**Files:** None (verification only)

**Step 1: Run full test suite**

Run: `cd telemetry_tool && python -m pytest tests/ -v --timeout=120`
Expected: all tests PASS, no regressions

**Step 2: Run truth dashboard probes (manual)**

Open `docs/audit-truth-dashboard.html` in a browser, enter:
- API URL: `http://localhost:5000` (or production URL)
- Session ID: (a known uploaded session)
- Click "Run Probes"

**Expected probe results:**
- Conflict 1 (Session Identity): **PASS** — csv_filename shows just filename, driver_name populated, track_name resolved
- Conflict 2 (Visualize): depends on data availability (not in scope for this checkpoint)
- Conflict 3-6: not in scope for this checkpoint

**Acceptance criteria (must be true before continuing):**
- [ ] No HTML responses to `/api/*`
- [ ] No 500s for optional data endpoints
- [ ] Session header identity probes PASS (title/driver/track/date)

**Step 3: Commit checkpoint marker**

```bash
git add -A
git commit -m "checkpoint: audit checkpoint 1 complete — API contract + identity + date + resolution"
```
