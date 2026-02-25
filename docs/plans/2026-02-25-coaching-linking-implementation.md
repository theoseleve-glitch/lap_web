# Coaching: Session-Drill Linking & Plan Completion — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let users link analyzed sessions to dev plan drills, auto-evaluate drill targets, celebrate plan completion with confetti + badge, and display earned badges on driver profiles.

**Architecture:** Two new DB tables (`plan_drill_sessions`, `driver_badges`) + `completed_at` column on `development_plans`. Three new API endpoints for linking. Completion logic triggers badge creation when plan hits 100%. Confetti animation replaces the basic overlay. Driver profile queries and displays badges.

**Tech Stack:** Python/Flask, SQLite, vanilla JS, CSS animations

---

### Task 1: G-G Diagram Bug — Add Test

The G-G API fix (m/s² to G conversion) is already applied in `api_data.py`. Add a test to lock it down.

**Files:**
- Modify: `telemetry_tool/tests/test_driver_features.py`

**Step 1: Write the test**

Add at the end of the file:

```python
class TestGGConversion:
    """G-G scatter API must return values in G, not raw m/s squared."""

    def test_gg_data_converts_to_g(self, db):
        """Raw accel stored as m/s squared should be divided by 9.80665."""
        import json
        import math

        # Insert driver, track, session.
        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'GG Tester')")
        db.execute(
            "INSERT INTO tracks (track_id, track_name, lap_length_m) VALUES ('t1', 'Oval', 500)"
        )
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, session_date) "
            "VALUES ('s1', 'f.csv', 1, 't1', '2025-01-01')"
        )
        # Store accel values in m/s squared (1 G = 9.80665 m/s squared).
        raw_lat = [9.80665, -9.80665, 0.0]
        raw_long = [4.903325, -4.903325, 0.0]
        db.execute(
            "INSERT INTO gps_traces (session_id, lap_number, latitudes_json, longitudes_json, "
            "distances_json, speeds_json, accel_lat_json, accel_long_json) "
            "VALUES ('s1', 1, '[]', '[]', '[]', '[]', :lat, :lon)",
            {"lat": json.dumps(raw_lat), "lon": json.dumps(raw_long)},
        )
        db.execute(
            "INSERT INTO laps (session_id, lap_number, lap_time_s) VALUES ('s1', 1, 30.0)"
        )
        db.commit()

        from web.app import create_app
        app = create_app(db)
        with app.test_client() as client:
            resp = client.get("/api/session/s1/gg_data")
            assert resp.status_code == 200
            data = resp.get_json()
            # 9.80665 / 9.80665 = 1.0 G
            assert math.isclose(data["accel_lat"][0], 1.0, rel_tol=0.01)
            assert math.isclose(data["accel_lat"][1], -1.0, rel_tol=0.01)
            # 4.903325 / 9.80665 = 0.5 G
            assert math.isclose(data["accel_long"][0], 0.5, rel_tol=0.01)
```

**Step 2: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_driver_features.py::TestGGConversion -v`
Expected: PASS (fix already applied)

**Step 3: Commit**

```bash
git add telemetry_tool/web/routes/api_data.py telemetry_tool/tests/test_driver_features.py
git commit -m "fix: G-G diagram converts m/s squared to G in API endpoint"
```

---

### Task 2: Schema — New Tables and Column

Add `plan_drill_sessions` table, `driver_badges` table, and `completed_at` column to `development_plans`.

**Files:**
- Modify: `telemetry_tool/db/schema.py` (lines 522-534 for dev plans table, line 708 for ALL_TABLES)
- Modify: `telemetry_tool/db/migrate.py` (lines 326-346 for Phase 17 block)

**Step 1: Update schema.py — add completed_at to development_plans**

In `schema.py`, update `_DEVELOPMENT_PLANS_TABLE` (line 522) to add `completed_at`:

```python
_DEVELOPMENT_PLANS_TABLE = """
CREATE TABLE IF NOT EXISTS development_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_id INTEGER NOT NULL REFERENCES drivers(driver_id),
    plan_name TEXT NOT NULL,
    template_id TEXT,
    level TEXT NOT NULL DEFAULT 'intermediate',
    weeks_json TEXT NOT NULL,
    progress_json TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""
```

**Step 2: Add new table constants after Phase 10 tables**

After `_DEVELOPMENT_PLANS_TABLE`, add:

```python
_PLAN_DRILL_SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS plan_drill_sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id     INTEGER NOT NULL REFERENCES development_plans(id),
    week_index  INTEGER NOT NULL,
    drill_index INTEGER NOT NULL,
    session_id  TEXT NOT NULL REFERENCES sessions(session_id),
    linked_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(plan_id, week_index, drill_index, session_id)
);
"""

_DRIVER_BADGES_TABLE = """
CREATE TABLE IF NOT EXISTS driver_badges (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_id     INTEGER NOT NULL REFERENCES drivers(driver_id),
    badge_type    TEXT NOT NULL,
    badge_name    TEXT NOT NULL,
    badge_level   TEXT,
    metadata_json TEXT,
    earned_at     TEXT NOT NULL DEFAULT (datetime('now')),
    plan_id       INTEGER REFERENCES development_plans(id)
);
"""
```

**Step 3: Add them to PHASE_10_TABLES**

Update `PHASE_10_TABLES` (line 559) to include the new tables:

```python
PHASE_10_TABLES: list[tuple[str, str]] = [
    ("session_annotations",   _SESSION_ANNOTATIONS_TABLE),
    ("development_plans",     _DEVELOPMENT_PLANS_TABLE),
    ("plan_drill_sessions",   _PLAN_DRILL_SESSIONS_TABLE),
    ("driver_badges",         _DRIVER_BADGES_TABLE),
    ("custom_dashboards",     _CUSTOM_DASHBOARDS_TABLE),
    ("export_templates",      _EXPORT_TEMPLATES_TABLE),
]
```

**Step 4: Update migrate.py — add Phase 18 migration block**

After the Phase 17 block (line 346), add:

```python
    # Phase 18 migration: completed_at on development_plans, coaching linking tables.
    try:
        cur.execute("ALTER TABLE development_plans ADD COLUMN completed_at TEXT;")
        logger.debug("Added column development_plans.completed_at.")
    except sqlite3.OperationalError:
        pass  # Column already exists.

    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) "
        "VALUES (?, ?);",
        (18, "Phase 18 schema — coaching linking (plan_drill_sessions, driver_badges, completed_at)"),
    )
```

**Step 5: Bump SCHEMA_VERSION**

In `schema.py` line 9, change `SCHEMA_VERSION = 17` to `SCHEMA_VERSION = 18`.

**Step 6: Write test**

Add to `test_driver_features.py`:

```python
class TestCoachingSchema:
    """Tables for coaching linking exist after migration."""

    def test_plan_drill_sessions_table_exists(self, db):
        row = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='plan_drill_sessions'"
        ).fetchone()
        assert row is not None

    def test_driver_badges_table_exists(self, db):
        row = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='driver_badges'"
        ).fetchone()
        assert row is not None

    def test_completed_at_column_exists(self, db):
        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'D')")
        db.execute(
            "INSERT INTO development_plans (driver_id, plan_name, weeks_json) "
            "VALUES (1, 'P', '[]')"
        )
        row = db.execute("SELECT completed_at FROM development_plans WHERE id = 1").fetchone()
        assert row is not None  # column exists, value is NULL
```

**Step 7: Run tests**

Run: `pytest telemetry_tool/tests/test_driver_features.py::TestCoachingSchema -v`
Expected: PASS

**Step 8: Commit**

```bash
git add telemetry_tool/db/schema.py telemetry_tool/db/migrate.py telemetry_tool/tests/test_driver_features.py
git commit -m "feat: schema for coaching session-drill linking and driver badges"
```

---

### Task 3: Backend — Link/Unlink Session Functions

Add functions in `development_plan.py` for linking sessions to drills, unlinking, fetching linked sessions, and computing aggregate stats.

**Files:**
- Modify: `telemetry_tool/development_plan.py` (append after `get_plan_completion_pct`, around line 2446)

**Step 1: Write tests**

Add to `test_driver_features.py`:

```python
class TestDrillSessionLinking:
    """Link analyzed sessions to specific drills in a dev plan."""

    def _seed_plan(self, db):
        """Create a driver with a 1-week, 2-drill plan and 2 sessions."""
        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Linker')")
        db.execute(
            "INSERT INTO tracks (track_id, track_name, lap_length_m) VALUES ('t1', 'Oval', 500)"
        )
        import json
        weeks = [{"week": 1, "title": "Basics", "drills": [
            {"name": "Drill A", "metric": "consistency_cv_pct", "target": "< 5"},
            {"name": "Drill B"},
        ]}]
        progress = [[False, False]]
        db.execute(
            "INSERT INTO development_plans (id, driver_id, plan_name, weeks_json, progress_json) "
            "VALUES (1, 1, 'Test Plan', :weeks, :progress)",
            {"weeks": json.dumps(weeks), "progress": json.dumps(progress)},
        )
        for i, (sid, score) in enumerate([("s1", 75.0), ("s2", 82.0)]):
            db.execute(
                "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, "
                "session_date, n_laps, best_lap_time_s, total_score) "
                "VALUES (:sid, 'f.csv', 1, 't1', '2025-01-0' || :d, :laps, 30.0, :score)",
                {"sid": sid, "d": i + 1, "laps": 10 + i * 5, "score": score},
            )
        db.commit()

    def test_link_session_creates_record(self, db):
        self._seed_plan(db)
        from development_plan import link_drill_session
        result = link_drill_session(db, plan_id=1, week_index=0, drill_index=0, session_id="s1")
        assert result is not None
        assert result["session_id"] == "s1"

    def test_link_auto_completes_drill(self, db):
        self._seed_plan(db)
        from development_plan import link_drill_session, get_plan
        link_drill_session(db, plan_id=1, week_index=0, drill_index=0, session_id="s1")
        plan = get_plan(db, 1)
        assert plan["progress"][0][0] is True

    def test_unlink_session(self, db):
        self._seed_plan(db)
        from development_plan import link_drill_session, unlink_drill_session, get_drill_sessions
        link_drill_session(db, plan_id=1, week_index=0, drill_index=0, session_id="s1")
        unlink_drill_session(db, plan_id=1, week_index=0, drill_index=0, session_id="s1")
        sessions = get_drill_sessions(db, plan_id=1)
        assert len(sessions) == 0

    def test_get_drill_sessions(self, db):
        self._seed_plan(db)
        from development_plan import link_drill_session, get_drill_sessions
        link_drill_session(db, plan_id=1, week_index=0, drill_index=0, session_id="s1")
        link_drill_session(db, plan_id=1, week_index=0, drill_index=1, session_id="s2")
        sessions = get_drill_sessions(db, plan_id=1)
        assert len(sessions) == 2

    def test_duplicate_link_ignored(self, db):
        self._seed_plan(db)
        from development_plan import link_drill_session, get_drill_sessions
        link_drill_session(db, plan_id=1, week_index=0, drill_index=0, session_id="s1")
        link_drill_session(db, plan_id=1, week_index=0, drill_index=0, session_id="s1")
        sessions = get_drill_sessions(db, plan_id=1)
        assert len(sessions) == 1
```

**Step 2: Run tests — expect FAIL**

Run: `pytest telemetry_tool/tests/test_driver_features.py::TestDrillSessionLinking -v`
Expected: FAIL (ImportError: cannot import name 'link_drill_session')

**Step 3: Implement functions**

Append to `telemetry_tool/development_plan.py`:

```python
def link_drill_session(
    conn: Any,
    plan_id: int,
    week_index: int,
    drill_index: int,
    session_id: str,
) -> Optional[dict[str, Any]]:
    """Link an analyzed session to a specific drill, auto-completing it."""
    plan = get_plan(conn, plan_id)
    if not plan:
        return None

    # Bounds check.
    if week_index < 0 or week_index >= len(plan.get("weeks", [])):
        raise IndexError(f"Week index {week_index} out of range")
    if drill_index < 0 or drill_index >= len(plan["weeks"][week_index].get("drills", [])):
        raise IndexError(f"Drill index {drill_index} out of range")

    # Insert (ignore duplicate).
    conn.execute(
        "INSERT OR IGNORE INTO plan_drill_sessions "
        "(plan_id, week_index, drill_index, session_id) VALUES (?, ?, ?, ?)",
        (plan_id, week_index, drill_index, session_id),
    )

    # Auto-complete the drill.
    update_plan_progress(conn, plan_id, week_index, drill_index, completed=True)

    # Return the linked record.
    row = conn.execute(
        "SELECT pds.*, s.session_date, s.best_lap_time_s, s.total_score, s.n_laps, "
        "t.track_name FROM plan_drill_sessions pds "
        "JOIN sessions s ON pds.session_id = s.session_id "
        "LEFT JOIN tracks t ON s.track_id = t.track_id "
        "WHERE pds.plan_id = ? AND pds.week_index = ? AND pds.drill_index = ? "
        "AND pds.session_id = ?",
        (plan_id, week_index, drill_index, session_id),
    ).fetchone()
    return dict(row) if row else None


def unlink_drill_session(
    conn: Any,
    plan_id: int,
    week_index: int,
    drill_index: int,
    session_id: str,
) -> None:
    """Remove a session link from a drill."""
    conn.execute(
        "DELETE FROM plan_drill_sessions "
        "WHERE plan_id = ? AND week_index = ? AND drill_index = ? AND session_id = ?",
        (plan_id, week_index, drill_index, session_id),
    )
    conn.commit()


def get_drill_sessions(conn: Any, plan_id: int) -> list[dict[str, Any]]:
    """Get all linked sessions for a plan, with session summary data."""
    rows = conn.execute(
        "SELECT pds.*, s.session_date, s.best_lap_time_s, s.total_score, s.n_laps, "
        "t.track_name FROM plan_drill_sessions pds "
        "JOIN sessions s ON pds.session_id = s.session_id "
        "LEFT JOIN tracks t ON s.track_id = t.track_id "
        "WHERE pds.plan_id = ? ORDER BY pds.week_index, pds.drill_index, pds.linked_at",
        (plan_id,),
    ).fetchall()
    return [dict(r) for r in rows]
```

**Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_driver_features.py::TestDrillSessionLinking -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/development_plan.py telemetry_tool/tests/test_driver_features.py
git commit -m "feat: link/unlink sessions to dev plan drills"
```

---

### Task 4: Backend — Plan Completion & Badge Creation

When a plan reaches 100%, auto-set status to 'completed', store `completed_at`, and create a driver badge with aggregate stats.

**Files:**
- Modify: `telemetry_tool/development_plan.py` (update `update_plan_progress`, add `_check_plan_completion`)

**Step 1: Write tests**

Add to `test_driver_features.py`:

```python
class TestPlanCompletion:
    """Plan completion triggers badge creation and status update."""

    def _seed_single_drill_plan(self, db):
        """Create a driver with a 1-week, 1-drill plan."""
        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Finisher')")
        db.execute(
            "INSERT INTO tracks (track_id, track_name, lap_length_m) VALUES ('t1', 'Oval', 500)"
        )
        import json
        weeks = [{"week": 1, "title": "Fundamentals", "drills": [{"name": "Only Drill"}]}]
        progress = [[False]]
        db.execute(
            "INSERT INTO development_plans (id, driver_id, plan_name, level, weeks_json, progress_json) "
            "VALUES (1, 1, 'Quick Plan', 'beginner', :w, :p)",
            {"w": json.dumps(weeks), "p": json.dumps(progress)},
        )
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, "
            "session_date, n_laps, total_score) VALUES ('s1', 'f.csv', 1, 't1', '2025-01-01', 15, 80.0)"
        )
        db.commit()

    def test_completion_sets_status(self, db):
        self._seed_single_drill_plan(db)
        from development_plan import link_drill_session, get_plan
        link_drill_session(db, plan_id=1, week_index=0, drill_index=0, session_id="s1")
        plan = get_plan(db, 1)
        assert plan["status"] == "completed"
        assert plan["completed_at"] is not None

    def test_completion_creates_badge(self, db):
        self._seed_single_drill_plan(db)
        from development_plan import link_drill_session
        link_drill_session(db, plan_id=1, week_index=0, drill_index=0, session_id="s1")
        row = db.execute(
            "SELECT * FROM driver_badges WHERE driver_id = 1 AND plan_id = 1"
        ).fetchone()
        assert row is not None
        assert dict(row)["badge_type"] == "plan_completion"
        assert dict(row)["badge_name"] == "Quick Plan"

    def test_badge_metadata_has_stats(self, db):
        self._seed_single_drill_plan(db)
        import json
        from development_plan import link_drill_session
        link_drill_session(db, plan_id=1, week_index=0, drill_index=0, session_id="s1")
        row = db.execute("SELECT metadata_json FROM driver_badges WHERE plan_id = 1").fetchone()
        meta = json.loads(dict(row)["metadata_json"])
        assert meta["drills_completed"] == 1
        assert meta["sessions_linked"] >= 1

    def test_no_duplicate_badge(self, db):
        self._seed_single_drill_plan(db)
        from development_plan import link_drill_session, update_plan_progress
        link_drill_session(db, plan_id=1, week_index=0, drill_index=0, session_id="s1")
        # Uncomplete and re-complete.
        update_plan_progress(db, 1, 0, 0, completed=False)
        update_plan_progress(db, 1, 0, 0, completed=True)
        count = db.execute("SELECT COUNT(*) FROM driver_badges WHERE plan_id = 1").fetchone()[0]
        assert count == 1
```

**Step 2: Run tests — expect FAIL**

Run: `pytest telemetry_tool/tests/test_driver_features.py::TestPlanCompletion -v`
Expected: FAIL (completion logic not yet implemented)

**Step 3: Implement completion check**

Add `_check_plan_completion()` to `development_plan.py` and call it from `update_plan_progress()`:

```python
def _check_plan_completion(conn: Any, plan_id: int) -> bool:
    """If plan is 100% complete, set status='completed', create badge. Returns True if just completed."""
    plan = get_plan(conn, plan_id)
    if not plan or plan.get("completion_pct", 0) < 100:
        return False
    if plan.get("status") == "completed":
        return False  # Already completed, no duplicate badge.

    # Mark completed.
    conn.execute(
        "UPDATE development_plans SET status = 'completed', "
        "completed_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
        (plan_id,),
    )

    # Gather aggregate stats from linked sessions.
    linked = get_drill_sessions(conn, plan_id)
    session_ids = list({r["session_id"] for r in linked})
    total_laps = sum(r.get("n_laps") or 0 for r in linked if r["session_id"] in session_ids)
    scores = [r["total_score"] for r in linked if r.get("total_score") is not None]
    improvement_pct = 0.0
    if len(scores) >= 2:
        first, last = scores[0], scores[-1]
        if first > 0:
            improvement_pct = round(100.0 * (last - first) / first, 1)

    weeks = plan.get("weeks", [])
    skills = [w.get("title", f"Week {i+1}") for i, w in enumerate(weeks)]

    total_drills = sum(len(w.get("drills", [])) for w in weeks)

    metadata = {
        "total_laps": total_laps,
        "drills_completed": total_drills,
        "sessions_linked": len(session_ids),
        "improvement_pct": improvement_pct,
        "skills_learned": skills,
    }

    # Create badge (only if none exists for this plan).
    existing = conn.execute(
        "SELECT id FROM driver_badges WHERE plan_id = ?", (plan_id,)
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO driver_badges (driver_id, badge_type, badge_name, badge_level, "
            "metadata_json, plan_id) VALUES (?, 'plan_completion', ?, ?, ?, ?)",
            (plan["driver_id"], plan["plan_name"], plan.get("level", "intermediate"),
             json.dumps(metadata), plan_id),
        )

    conn.commit()
    return True
```

Then, at the end of `update_plan_progress()` (right before the final `return`), add a call to `_check_plan_completion`:

```python
    _check_plan_completion(conn, plan_id)
    return get_plan(conn, plan_id)
```

Replace the existing `return get_plan(conn, plan_id)` with those two lines.

**Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_driver_features.py::TestPlanCompletion -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/development_plan.py telemetry_tool/tests/test_driver_features.py
git commit -m "feat: plan completion triggers badge creation with aggregate stats"
```

---

### Task 5: API Endpoints — Link/Unlink/Get Drill Sessions

Add three new API routes for session-drill linking.

**Files:**
- Modify: `telemetry_tool/web/routes/api_data.py` (add after `api_session_drill_suggestions`, around line 3250)

**Step 1: Write tests**

Add to `test_driver_features.py`:

```python
class TestDrillLinkingAPI:
    """API endpoints for linking sessions to drills."""

    def _seed(self, db):
        import json
        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'API Tester')")
        db.execute("INSERT INTO tracks (track_id, track_name, lap_length_m) VALUES ('t1', 'T', 500)")
        weeks = [{"week": 1, "title": "W1", "drills": [{"name": "D1"}, {"name": "D2"}]}]
        progress = [[False, False]]
        db.execute(
            "INSERT INTO development_plans (id, driver_id, plan_name, weeks_json, progress_json) "
            "VALUES (1, 1, 'P', :w, :p)",
            {"w": json.dumps(weeks), "p": json.dumps(progress)},
        )
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, session_date, n_laps) "
            "VALUES ('s1', 'f.csv', 1, 't1', '2025-01-01', 10)"
        )
        db.commit()

    def test_link_session_api(self, db):
        self._seed(db)
        from web.app import create_app
        app = create_app(db)
        with app.test_client() as c:
            resp = c.post("/api/dev-plans/plan/1/link-session",
                          json={"week_index": 0, "drill_index": 0, "session_id": "s1"})
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["session_id"] == "s1"

    def test_unlink_session_api(self, db):
        self._seed(db)
        from web.app import create_app
        app = create_app(db)
        with app.test_client() as c:
            c.post("/api/dev-plans/plan/1/link-session",
                   json={"week_index": 0, "drill_index": 0, "session_id": "s1"})
            resp = c.delete("/api/dev-plans/plan/1/unlink-session",
                            json={"week_index": 0, "drill_index": 0, "session_id": "s1"})
            assert resp.status_code == 200

    def test_get_drill_sessions_api(self, db):
        self._seed(db)
        from web.app import create_app
        app = create_app(db)
        with app.test_client() as c:
            c.post("/api/dev-plans/plan/1/link-session",
                   json={"week_index": 0, "drill_index": 0, "session_id": "s1"})
            resp = c.get("/api/dev-plans/plan/1/drill-sessions")
            assert resp.status_code == 200
            data = resp.get_json()
            assert len(data["sessions"]) == 1
```

**Step 2: Run tests — expect FAIL**

Run: `pytest telemetry_tool/tests/test_driver_features.py::TestDrillLinkingAPI -v`
Expected: FAIL (404, routes not defined)

**Step 3: Implement API routes**

Add to `api_data.py` after the last dev-plans route:

```python
@bp.route("/dev-plans/plan/<int:plan_id>/link-session", methods=["POST"])
def link_session_api(plan_id):
    """Link an analyzed session to a specific drill."""
    conn = get_db_connection()
    data = request.get_json(force=True) or {}
    week_index = data.get("week_index")
    drill_index = data.get("drill_index")
    session_id = data.get("session_id")
    if week_index is None or drill_index is None or not session_id:
        return jsonify({"error": "week_index, drill_index, and session_id required"}), 400
    from development_plan import link_drill_session, get_plan
    try:
        result = link_drill_session(conn, plan_id, week_index, drill_index, session_id)
        if not result:
            return jsonify({"error": "Plan not found"}), 404
        plan = get_plan(conn, plan_id)
        result["completion_pct"] = plan["completion_pct"] if plan else 0
        result["just_completed"] = plan.get("status") == "completed" if plan else False
        return jsonify(result)
    except IndexError as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/dev-plans/plan/<int:plan_id>/unlink-session", methods=["DELETE"])
def unlink_session_api(plan_id):
    """Remove a session link from a drill."""
    conn = get_db_connection()
    data = request.get_json(force=True) or {}
    week_index = data.get("week_index")
    drill_index = data.get("drill_index")
    session_id = data.get("session_id")
    if week_index is None or drill_index is None or not session_id:
        return jsonify({"error": "week_index, drill_index, and session_id required"}), 400
    from development_plan import unlink_drill_session
    unlink_drill_session(conn, plan_id, week_index, drill_index, session_id)
    return jsonify({"success": True})


@bp.route("/dev-plans/plan/<int:plan_id>/drill-sessions", methods=["GET"])
def drill_sessions_api(plan_id):
    """Return all linked sessions for a plan."""
    conn = get_db_connection()
    from development_plan import get_drill_sessions
    sessions = get_drill_sessions(conn, plan_id)
    return jsonify({"sessions": sessions})
```

**Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_driver_features.py::TestDrillLinkingAPI -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/api_data.py telemetry_tool/tests/test_driver_features.py
git commit -m "feat: API endpoints for drill-session linking"
```

---

### Task 6: UI — Dev Plan Detail Session Linking

Update `dev_plan_detail.html` to show a "Link Session" button per drill and display linked sessions.

**Files:**
- Modify: `telemetry_tool/web/routes/dev_plans.py` (pass driver sessions and linked sessions to template)
- Modify: `telemetry_tool/web/templates/dev_plan_detail.html`

**Step 1: Update the route to pass sessions and drill-links**

In `dev_plans.py`, update `plan_detail()`:

```python
@bp.route("/<int:plan_id>")
def plan_detail(plan_id: int):
    conn = get_db_connection()
    from development_plan import get_plan, get_drill_sessions
    plan = get_plan(conn, plan_id)
    if not plan: abort(404)

    # Get driver's sessions for the linking dropdown.
    driver_sessions = conn.execute(
        "SELECT s.session_id, s.session_date, s.best_lap_time_s, s.total_score, "
        "s.n_laps, t.track_name FROM sessions s "
        "LEFT JOIN tracks t ON s.track_id = t.track_id "
        "WHERE s.driver_id = :did ORDER BY s.session_date DESC",
        {"did": plan["driver_id"]},
    ).fetchall()
    driver_sessions = [dict(r) for r in driver_sessions]

    # Get already-linked sessions.
    drill_links = get_drill_sessions(conn, plan_id)

    return render_template("dev_plan_detail.html",
                          plan=plan,
                          driver_sessions=driver_sessions,
                          drill_links=drill_links)
```

**Step 2: Update the template — add link UI to each drill**

In `dev_plan_detail.html`, after the drill's success criteria div and before the closing `</li>`, add the linked sessions display and link dropdown. Each drill gets:
- A list of already-linked session cards (from `drill_links` filtered by week/drill index)
- A dropdown + "Link" button to add a new session link

Use `drill_key = week_idx + '_' + drill_idx` for element IDs.

The linked session card shows: date, track name, best lap time, score, and an "unlink" X button.

**Step 3: Add linking JS functions**

Add `linkSession(planId, weekIdx, drillIdx)` and `unlinkSession(planId, weekIdx, drillIdx, sessionId)` functions. Both call the API, then `location.reload()` on success. The link function reads the selected session_id from the dropdown.

**Step 4: Add CSS for linked session cards**

Append to `telemetry_tool/web/static/css/main.css`:

```css
/* Drill session linking */
.drill-sessions { margin-top: 0.5rem; }
.linked-session-card {
    display: inline-flex; align-items: center; gap: 0.5rem;
    background: var(--card-bg, #1e1e2e); padding: 0.3rem 0.6rem;
    border-radius: 6px; font-size: 0.8rem; margin: 0.2rem 0;
}
.linked-session-date { color: var(--text-muted, #888); }
.linked-session-score { color: var(--accent, #f59e0b); font-weight: 600; }
.drill-link-action {
    display: flex; gap: 0.4rem; align-items: center; margin-top: 0.4rem;
}
.drill-session-select { max-width: 280px; font-size: 0.8rem; }
```

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/dev_plans.py telemetry_tool/web/templates/dev_plan_detail.html telemetry_tool/web/static/css/main.css
git commit -m "feat: UI for linking sessions to drills in dev plan detail"
```

---

### Task 7: UI — Confetti Celebration

Replace the basic `_showCompletionBadge()` with a confetti animation + stats modal.

**Files:**
- Modify: `telemetry_tool/web/templates/dev_plan_detail.html` (replace `_showCompletionBadge`)

**Step 1: Replace the celebration function**

Replace the `_showCompletionBadge` function (lines 236-254 approx) with `_showCompletionCelebration(data)`:

Create a canvas element for confetti particles. Generate 150 particles with random colors from `['#f59e0b','#22c55e','#3b82f6','#ef4444','#a855f7','#ec4899']`, random positions, velocities, and rotation. Animate with `requestAnimationFrame` for 180 frames, then remove canvas.

Create a modal overlay using `document.createElement` and `textContent`/`appendChild` DOM methods (not innerHTML) for safe DOM construction:
- Trophy emoji (3.5rem)
- "Plan Complete!" heading
- "You've earned a completion badge!" subtitle
- Stats from `data.badge_meta` if available (sessions linked, total laps, drills completed, improvement %)
- "View Profile" link button pointing to `/drivers/{driver_id}`

Auto-dismiss on click outside.

**Step 2: Update toggleDrill completion check**

Change the existing `if (data.completion_pct >= 100)` block to call `_showCompletionCelebration(data)` instead of `_showCompletionBadge()`.

**Step 3: Update the progress API response for completion info**

In `api_data.py`, update `update_plan_progress_api` to include badge metadata on completion. After the existing `return jsonify(updated)`, wrap it to check:

```python
        if not updated:
            return jsonify({"error": "Plan not found"}), 404
        # Check if just completed -- include badge info for celebration.
        if updated.get("status") == "completed" and updated.get("completion_pct", 0) >= 100:
            badge_row = conn.execute(
                "SELECT metadata_json FROM driver_badges WHERE plan_id = ?", (plan_id,)
            ).fetchone()
            if badge_row:
                import json as _json
                updated["just_completed"] = True
                updated["badge_meta"] = _json.loads(dict(badge_row)["metadata_json"])
                updated["driver_id"] = updated.get("driver_id")
            else:
                updated["just_completed"] = False
        else:
            updated["just_completed"] = False
        return jsonify(updated)
```

**Step 4: Commit**

```bash
git add telemetry_tool/web/templates/dev_plan_detail.html telemetry_tool/web/routes/api_data.py
git commit -m "feat: confetti celebration and stats modal on plan completion"
```

---

### Task 8: UI — Badges on Driver Profile

Show earned badges on the driver profile page.

**Files:**
- Modify: `telemetry_tool/web/routes/drivers.py` (query badges, pass to template, around line 96)
- Modify: `telemetry_tool/web/templates/driver_profile.html` (add badges section after meta-grid, around line 70)

**Step 1: Write test**

Add to `test_driver_features.py`:

```python
class TestDriverBadgesOnProfile:
    """Driver profile page includes earned badges."""

    def test_badges_passed_to_template(self, db):
        import json
        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Badge Boy')")
        db.execute(
            "INSERT INTO driver_badges (driver_id, badge_type, badge_name, badge_level, "
            "metadata_json, plan_id) VALUES (1, 'plan_completion', 'Speed Plan', 'advanced', "
            ":meta, 99)",
            {"meta": json.dumps({"drills_completed": 6, "sessions_linked": 3})},
        )
        db.commit()
        from web.app import create_app
        app = create_app(db)
        with app.test_client() as c:
            resp = c.get("/drivers/1")
            assert resp.status_code == 200
            assert b"Speed Plan" in resp.data
```

**Step 2: Run test — expect FAIL**

Run: `pytest telemetry_tool/tests/test_driver_features.py::TestDriverBadgesOnProfile -v`
Expected: FAIL (badges not passed to template)

**Step 3: Update driver route**

In `drivers.py`, in `driver_detail()`, before `return render_template(...)`, add:

```python
    # Earned badges.
    badge_rows = conn.execute(
        "SELECT * FROM driver_badges WHERE driver_id = :did ORDER BY earned_at DESC",
        {"did": driver_id},
    ).fetchall()
    badges = [dict(r) for r in badge_rows]
```

Add `badges=badges` to the `render_template` call.

**Step 4: Update driver_profile.html — add badges section**

After the closing `</div>` of `meta-grid` (line 69), before the Track Records section (line 71), add:

```html
{% if badges %}
<section class="section">
    <h2>Earned Badges</h2>
    <div class="badges-grid">
        {% for b in badges %}
        <div class="badge-card">
            <div class="badge-icon">
                {% if b.badge_level == 'expert' or b.badge_level == 'professional' %}&#x1F947;
                {% elif b.badge_level == 'advanced' %}&#x1F948;
                {% elif b.badge_level == 'intermediate' %}&#x1F949;
                {% else %}&#x1F3C5;{% endif %}
            </div>
            <div class="badge-info">
                <span class="badge-name">{{ b.badge_name }}</span>
                <span class="badge-level">{{ b.badge_level|capitalize }} &mdash; {{ b.earned_at[:10] if b.earned_at else '' }}</span>
            </div>
        </div>
        {% endfor %}
    </div>
</section>
{% endif %}
```

**Step 5: Add CSS for badge cards**

Append to `main.css`:

```css
/* Driver badges */
.badges-grid {
    display: flex; flex-wrap: wrap; gap: 0.75rem;
}
.badge-card {
    display: flex; align-items: center; gap: 0.6rem;
    background: var(--card-bg, #1e1e2e); padding: 0.6rem 1rem;
    border-radius: 10px; border: 1px solid var(--border, #333);
}
.badge-icon { font-size: 1.8rem; }
.badge-name { font-weight: 600; font-size: 0.95rem; }
.badge-level { font-size: 0.75rem; color: var(--text-muted, #888); }
```

**Step 6: Run test**

Run: `pytest telemetry_tool/tests/test_driver_features.py::TestDriverBadgesOnProfile -v`
Expected: PASS

**Step 7: Commit**

```bash
git add telemetry_tool/web/routes/drivers.py telemetry_tool/web/templates/driver_profile.html telemetry_tool/web/static/css/main.css telemetry_tool/tests/test_driver_features.py
git commit -m "feat: display earned badges on driver profile page"
```

---

### Task 9: Final Verification

Run the full test suite and verify everything works together.

**Step 1: Run all tests**

Run: `pytest telemetry_tool/tests/ -v`
Expected: All tests PASS (242 existing + approx 20 new = approx 262 total)

**Step 2: Commit any remaining fixes**

If any tests fail, fix them and commit.

---

## Summary

| Task | What | New Tests |
|------|------|-----------|
| 1 | G-G diagram bug test | 1 |
| 2 | Schema (2 tables + 1 column) | 3 |
| 3 | Link/unlink functions | 5 |
| 4 | Plan completion + badge creation | 4 |
| 5 | API endpoints | 3 |
| 6 | Dev plan detail UI | 0 (visual) |
| 7 | Confetti celebration | 0 (visual) |
| 8 | Badges on profile | 1 |
| 9 | Final verification | 0 |
| **Total** | | **approx 17** |
