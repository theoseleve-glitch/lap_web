# Data Management Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enhance tracks, karts (new), drivers, and weekends data sections with deletion, editing, predefined reference data, bug fixes, and richer insights.

**Architecture:** Feature-by-feature delivery in dependency order (Tracks → Karts → Drivers → Weekends). Each area adds schema tables/columns via a new Phase 16 migration, then backend routes, then frontend templates/JS. All new tables use `CREATE TABLE IF NOT EXISTS` in schema.py and predefined CSV data is imported idempotently in migrate.py.

**Tech Stack:** Python 3.x, Flask, SQLite, Jinja2, vanilla JS, Leaflet (maps), Canvas 2D (charts), HTML5 Drag API.

---

## Area 1: Tracks

### Task 1: Predefined Tracks Reference Table + Migration

**Files:**
- Modify: `telemetry_tool/db/schema.py:623` (add Phase 13 tables list, update ALL_TABLES)
- Modify: `telemetry_tool/db/migrate.py:186` (add Phase 16 migration + CSV import)
- Test: `telemetry_tool/tests/test_predefined_data.py` (new)

**Step 1: Write failing test**

```python
"""Tests for predefined data import (tracks + karts)."""
import csv
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.migrate import ensure_schema


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    yield conn
    conn.close()


class TestPredefinedTracks:
    def test_table_exists(self, db):
        rows = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='predefined_tracks'"
        ).fetchall()
        assert len(rows) == 1

    def test_data_imported(self, db):
        count = db.execute("SELECT COUNT(*) FROM predefined_tracks").fetchone()[0]
        assert count > 100  # ~199 rows in CSV

    def test_columns_present(self, db):
        row = db.execute("SELECT * FROM predefined_tracks LIMIT 1").fetchone()
        keys = row.keys()
        for col in ("predefined_track_id", "country", "track_name", "layout_name", "layout_length_m"):
            assert col in keys

    def test_idempotent_import(self, db):
        """Running ensure_schema twice doesn't duplicate rows."""
        count_before = db.execute("SELECT COUNT(*) FROM predefined_tracks").fetchone()[0]
        ensure_schema(db)
        count_after = db.execute("SELECT COUNT(*) FROM predefined_tracks").fetchone()[0]
        assert count_before == count_after

    def test_tracks_has_predefined_fk_column(self, db):
        """The tracks table has a predefined_track_id column."""
        info = db.execute("PRAGMA table_info(tracks)").fetchall()
        col_names = [r["name"] for r in info]
        assert "predefined_track_id" in col_names
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_predefined_data.py -v --tb=short`
Expected: FAIL — table `predefined_tracks` does not exist.

**Step 3: Implement schema + migration**

In `schema.py`, after the Phase 12 tables block (~line 619), add:

```python
# ------------------------------------------------------------------
# Phase 13 tables — predefined reference data + karts
# ------------------------------------------------------------------

_PREDEFINED_TRACKS_TABLE = """
CREATE TABLE IF NOT EXISTS predefined_tracks (
    predefined_track_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    country              TEXT,
    track_name           TEXT,
    city                 TEXT,
    region               TEXT,
    layout_name          TEXT,
    layout_length_m      REAL,
    direction            TEXT,
    rental_available     INTEGER DEFAULT 0,
    owner_available      INTEGER DEFAULT 0,
    outdoor              INTEGER DEFAULT 1,
    data_quality         TEXT,
    source_url           TEXT
);
"""

_PREDEFINED_KARTS_TABLE = """
CREATE TABLE IF NOT EXISTS predefined_karts (
    predefined_kart_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    segment              TEXT,
    manufacturer         TEXT,
    model                TEXT,
    model_year_start     INTEGER,
    use_or_championship  TEXT,
    engine               TEXT,
    power_hp             REAL,
    engine_type          TEXT,
    kart_weight_kg       REAL,
    top_speed_kmh        REAL,
    zero_to_100_s        REAL,
    power_to_weight      REAL,
    braking_g_est        REAL,
    lateral_g_est        REAL,
    weight_source        TEXT
);
"""

_KARTS_TABLE = """
CREATE TABLE IF NOT EXISTS karts (
    kart_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    predefined_kart_id   INTEGER REFERENCES predefined_karts(predefined_kart_id),
    kart_name            TEXT NOT NULL,
    manufacturer         TEXT,
    model                TEXT,
    engine               TEXT,
    power_hp             REAL,
    kart_weight_kg       REAL,
    notes                TEXT,
    created_at           TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_TRACK_SECTORS_TABLE = """
CREATE TABLE IF NOT EXISTS track_sectors (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id      TEXT NOT NULL REFERENCES tracks(track_id),
    sector_index  INTEGER NOT NULL,
    latitude      REAL NOT NULL,
    longitude     REAL NOT NULL,
    distance_m    REAL,
    label         TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(track_id, sector_index)
);
"""

PHASE_13_TABLES: list[tuple[str, str]] = [
    ("predefined_tracks",  _PREDEFINED_TRACKS_TABLE),
    ("predefined_karts",   _PREDEFINED_KARTS_TABLE),
    ("karts",              _KARTS_TABLE),
    ("track_sectors",      _TRACK_SECTORS_TABLE),
]
```

Update `ALL_TABLES` at the bottom of schema.py:
```python
ALL_TABLES = PHASE_1_TABLES + PHASE_2_TABLES + ... + PHASE_12_TABLES + PHASE_13_TABLES
```

Update `SCHEMA_VERSION = 16`.

In `migrate.py`, after the Phase 15 block (~line 185), add:

```python
    # Phase 16 migration: predefined data + kart + track_sectors + new columns.

    # Add predefined_track_id FK column to tracks.
    try:
        cur.execute("ALTER TABLE tracks ADD COLUMN predefined_track_id INTEGER;")
        logger.debug("Added column tracks.predefined_track_id.")
    except sqlite3.OperationalError:
        pass

    # Add original start/finish columns to tracks.
    for col in ("original_start_lat REAL", "original_start_lon REAL"):
        try:
            cur.execute(f"ALTER TABLE tracks ADD COLUMN {col};")
            logger.debug("Added column tracks.%s.", col.split()[0])
        except sqlite3.OperationalError:
            pass

    # Add kart_id FK column to sessions.
    try:
        cur.execute("ALTER TABLE sessions ADD COLUMN kart_id INTEGER;")
        logger.debug("Added column sessions.kart_id.")
    except sqlite3.OperationalError:
        pass

    # Import predefined tracks from CSV (idempotent: skip if table already populated).
    _pt_count = cur.execute("SELECT COUNT(*) FROM predefined_tracks").fetchone()[0]
    if _pt_count == 0:
        _csv_path = Path(__file__).resolve().parents[2] / "predefined_track_list.csv"
        if _csv_path.exists():
            _bool_map = {"yes": 1, "no": 0}
            with open(_csv_path, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if not row.get("Track", "").strip():
                        continue
                    cur.execute(
                        "INSERT INTO predefined_tracks "
                        "(country, track_name, city, region, layout_name, layout_length_m, "
                        "direction, rental_available, owner_available, outdoor, data_quality, source_url) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            row.get("Country", "").strip(),
                            row.get("Track", "").strip(),
                            row.get("City", "").strip(),
                            row.get("Region", "").strip(),
                            row.get("LayoutName", "").strip(),
                            float(row["LayoutLength_m"]) if row.get("LayoutLength_m", "").strip() else None,
                            row.get("Direction", "").strip(),
                            _bool_map.get(row.get("RentalAvailable", "").strip().lower(), 0),
                            _bool_map.get(row.get("OwnerAvailable", "").strip().lower(), 0),
                            _bool_map.get(row.get("Outdoor", "").strip().lower(), 1),
                            row.get("DataQuality", "").strip(),
                            row.get("Source", "").strip(),
                        ),
                    )
            logger.info("Imported predefined tracks from %s.", _csv_path)

    # Import predefined karts from CSV (idempotent).
    _pk_count = cur.execute("SELECT COUNT(*) FROM predefined_karts").fetchone()[0]
    if _pk_count == 0:
        _csv_path = Path(__file__).resolve().parents[2] / "predefined_kart_list.csv"
        if _csv_path.exists():
            with open(_csv_path, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if not row.get("model", "").strip():
                        continue
                    def _flt(key):
                        v = row.get(key, "").strip()
                        if not v or v.upper() == "NA":
                            return None
                        return float(v)
                    def _int(key):
                        v = row.get(key, "").strip()
                        if not v or v.upper() == "NA":
                            return None
                        return int(v)
                    cur.execute(
                        "INSERT INTO predefined_karts "
                        "(segment, manufacturer, model, model_year_start, use_or_championship, "
                        "engine, power_hp, engine_type, kart_weight_kg, top_speed_kmh, "
                        "zero_to_100_s, power_to_weight, braking_g_est, lateral_g_est, weight_source) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            row.get("segment", "").strip(),
                            row.get("manufacturer", "").strip(),
                            row.get("model", "").strip(),
                            _int("model_year_start"),
                            row.get("use_or_championship", "").strip(),
                            row.get("engine", "").strip(),
                            _flt("power_hp"),
                            row.get("engine_type", "").strip(),
                            _flt("kart_weight_kg_no_driver"),
                            _flt("top_speed_kmh"),
                            _flt("zero_to_100_kmh_s"),
                            _flt("power_to_weight_hp_per_kg"),
                            _flt("braking_g_est"),
                            _flt("lateral_g_est"),
                            row.get("weight_source", "").strip(),
                        ),
                    )
            logger.info("Imported predefined karts from %s.", _csv_path)

    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) "
        "VALUES (?, ?);",
        (16, "Phase 16 schema — predefined tracks/karts, user karts, track sectors"),
    )
```

Add `import csv` and `from pathlib import Path` to the top of `migrate.py` if not already present.

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_predefined_data.py -v --tb=short`
Expected: All 5 tests PASS.

**Step 5: Commit**

```bash
git add telemetry_tool/db/schema.py telemetry_tool/db/migrate.py telemetry_tool/tests/test_predefined_data.py
git commit -m "feat: add Phase 16 schema — predefined tracks/karts, user karts, track sectors"
```

---

### Task 2: Track Start/Finish Editing

**Files:**
- Modify: `telemetry_tool/web/routes/tracks.py:178` (add start_finish route)
- Modify: `telemetry_tool/web/templates/track_detail.html:315-341` (draggable marker + save button)
- Modify: `telemetry_tool/web/models.py` (add `update_track_start_finish()`)
- Test: `telemetry_tool/tests/test_track_features.py` (new)

**Step 1: Write failing test**

```python
"""Tests for track management features."""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.migrate import ensure_schema
from web.models import upsert_track


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    yield conn
    conn.close()


class TestStartFinishEdit:
    def test_update_start_finish(self, db):
        """Updating start/finish stores new coords and preserves originals."""
        from web.models import update_track_start_finish

        upsert_track(db, "t1", {
            "track_name": "Test Track",
            "lap_length_m": 500,
            "start_lat": 48.0,
            "start_lon": 2.0,
        })
        db.commit()

        update_track_start_finish(db, "t1", 48.1, 2.1)
        db.commit()

        row = db.execute("SELECT * FROM tracks WHERE track_id = 't1'").fetchone()
        row = dict(row)
        assert row["start_lat"] == 48.1
        assert row["start_lon"] == 2.1
        assert row["original_start_lat"] == 48.0
        assert row["original_start_lon"] == 2.0

    def test_original_preserved_on_second_edit(self, db):
        """Second edit doesn't overwrite the original coords."""
        from web.models import update_track_start_finish

        upsert_track(db, "t1", {
            "track_name": "Test Track",
            "lap_length_m": 500,
            "start_lat": 48.0,
            "start_lon": 2.0,
        })
        db.commit()

        update_track_start_finish(db, "t1", 48.1, 2.1)
        db.commit()
        update_track_start_finish(db, "t1", 48.2, 2.2)
        db.commit()

        row = dict(db.execute("SELECT * FROM tracks WHERE track_id = 't1'").fetchone())
        assert row["start_lat"] == 48.2
        assert row["original_start_lat"] == 48.0  # Still the original

    def test_reset_to_original(self, db):
        """Reset restores original coordinates."""
        from web.models import update_track_start_finish, reset_track_start_finish

        upsert_track(db, "t1", {
            "track_name": "Test Track",
            "lap_length_m": 500,
            "start_lat": 48.0,
            "start_lon": 2.0,
        })
        db.commit()

        update_track_start_finish(db, "t1", 48.5, 2.5)
        db.commit()

        reset_track_start_finish(db, "t1")
        db.commit()

        row = dict(db.execute("SELECT * FROM tracks WHERE track_id = 't1'").fetchone())
        assert row["start_lat"] == 48.0
        assert row["start_lon"] == 2.0
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_track_features.py::TestStartFinishEdit -v --tb=short`
Expected: FAIL — `update_track_start_finish` not found.

**Step 3: Implement backend**

In `models.py`, add these functions:

```python
def update_track_start_finish(
    conn: sqlite3.Connection, track_id: str, lat: float, lon: float
) -> None:
    """Update start/finish position; preserve originals on first edit."""
    row = conn.execute(
        "SELECT start_lat, start_lon, original_start_lat FROM tracks WHERE track_id = ?",
        (track_id,),
    ).fetchone()
    if row is None:
        return
    # On first edit, save originals.
    if row["original_start_lat"] is None:
        conn.execute(
            "UPDATE tracks SET original_start_lat = start_lat, "
            "original_start_lon = start_lon WHERE track_id = ?",
            (track_id,),
        )
    conn.execute(
        "UPDATE tracks SET start_lat = ?, start_lon = ? WHERE track_id = ?",
        (lat, lon, track_id),
    )


def reset_track_start_finish(conn: sqlite3.Connection, track_id: str) -> None:
    """Reset start/finish to auto-detected originals."""
    conn.execute(
        "UPDATE tracks SET start_lat = original_start_lat, "
        "start_lon = original_start_lon WHERE track_id = ? "
        "AND original_start_lat IS NOT NULL",
        (track_id,),
    )
```

In `tracks.py`, add two new routes after `update_joker()`:

```python
@bp.route("/<track_id>/start_finish", methods=["POST"])
def update_start_finish(track_id):
    """Update or reset start/finish GPS position."""
    conn = get_db_connection()
    from web.models import update_track_start_finish, reset_track_start_finish

    action = request.form.get("action", "update")
    if action == "reset":
        reset_track_start_finish(conn, track_id)
    else:
        lat = float(request.form["lat"])
        lon = float(request.form["lon"])
        update_track_start_finish(conn, track_id, lat, lon)
    conn.commit()
    return redirect(url_for("tracks.track_detail", track_id=track_id))
```

In `track_detail.html`, replace the static circleMarker (lines 333-337) with a draggable marker + save/reset controls:

```javascript
// Replace the static marker with draggable
var startMarker = L.marker(center, {draggable: true}).addTo(map);
startMarker.bindPopup('Start / Finish (drag to move)');

var saveBar = document.getElementById('sf-save-bar');
var sfLat = document.getElementById('sf-lat');
var sfLon = document.getElementById('sf-lon');

startMarker.on('dragend', function(e) {
    var pos = e.target.getLatLng();
    sfLat.value = pos.lat.toFixed(7);
    sfLon.value = pos.lng.toFixed(7);
    saveBar.style.display = 'flex';
});
```

Add save/reset HTML bar above or below the map:

```html
<form id="sf-save-bar" method="post" action="/tracks/{{ track.track_id }}/start_finish"
      style="display:none;" class="sf-bar">
    <input type="hidden" name="action" value="update">
    <input type="hidden" name="lat" id="sf-lat">
    <input type="hidden" name="lon" id="sf-lon">
    <span class="text-muted">New position set — </span>
    <button type="submit" class="btn btn-primary btn-sm">Save Position</button>
    {% if track.original_start_lat %}
    <button type="submit" name="action" value="reset" class="btn btn-sm">Reset to Auto-Detected</button>
    {% endif %}
</form>
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_track_features.py::TestStartFinishEdit -v --tb=short`
Expected: All 3 tests PASS.

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/tracks.py telemetry_tool/web/templates/track_detail.html \
  telemetry_tool/web/models.py telemetry_tool/tests/test_track_features.py
git commit -m "feat: editable start/finish position via draggable map marker"
```

---

### Task 3: Track-Level Sectors

**Files:**
- Modify: `telemetry_tool/web/routes/tracks.py` (add sector CRUD API routes)
- Modify: `telemetry_tool/web/models.py` (add track sector functions)
- Modify: `telemetry_tool/web/templates/track_detail.html` (add sector UI on map)
- Modify: `telemetry_tool/db/queries.py` (add track sector queries)
- Test: `telemetry_tool/tests/test_track_features.py` (add sector tests)

**Step 1: Write failing test**

Add to `test_track_features.py`:

```python
class TestTrackSectors:
    def test_add_sector(self, db):
        from web.models import upsert_track_sector, get_track_sectors

        upsert_track(db, "t1", {"track_name": "T", "lap_length_m": 500})
        db.commit()
        upsert_track_sector(db, "t1", 48.1, 2.1)
        db.commit()

        sectors = get_track_sectors(db, "t1")
        assert len(sectors) == 1
        assert sectors[0]["sector_index"] == 0
        assert sectors[0]["label"] == "S1"

    def test_auto_reindex(self, db):
        from web.models import upsert_track_sector, get_track_sectors, delete_track_sector

        upsert_track(db, "t1", {"track_name": "T", "lap_length_m": 500})
        db.commit()
        upsert_track_sector(db, "t1", 48.1, 2.1)
        upsert_track_sector(db, "t1", 48.2, 2.2)
        upsert_track_sector(db, "t1", 48.3, 2.3)
        db.commit()

        sectors = get_track_sectors(db, "t1")
        assert len(sectors) == 3
        # Delete middle
        delete_track_sector(db, "t1", sectors[1]["id"])
        db.commit()

        sectors = get_track_sectors(db, "t1")
        assert len(sectors) == 2
        assert sectors[0]["sector_index"] == 0
        assert sectors[1]["sector_index"] == 1
        assert sectors[0]["label"] == "S1"
        assert sectors[1]["label"] == "S2"
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_track_features.py::TestTrackSectors -v --tb=short`
Expected: FAIL — `upsert_track_sector` not found.

**Step 3: Implement**

In `models.py`:

```python
def get_track_sectors(conn: sqlite3.Connection, track_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM track_sectors WHERE track_id = ? ORDER BY sector_index",
        (track_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_track_sector(
    conn: sqlite3.Connection, track_id: str, lat: float, lon: float,
    distance_m: float | None = None,
) -> int:
    """Add a sector and auto-reindex. Returns new sector ID."""
    next_idx = conn.execute(
        "SELECT COALESCE(MAX(sector_index), -1) + 1 FROM track_sectors WHERE track_id = ?",
        (track_id,),
    ).fetchone()[0]
    label = f"S{next_idx + 1}"
    cur = conn.execute(
        "INSERT INTO track_sectors (track_id, sector_index, latitude, longitude, distance_m, label) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (track_id, next_idx, lat, lon, distance_m, label),
    )
    return cur.lastrowid


def delete_track_sector(conn: sqlite3.Connection, track_id: str, sector_id: int) -> None:
    conn.execute("DELETE FROM track_sectors WHERE id = ? AND track_id = ?", (sector_id, track_id))
    _reindex_track_sectors(conn, track_id)


def _reindex_track_sectors(conn: sqlite3.Connection, track_id: str) -> None:
    rows = conn.execute(
        "SELECT id FROM track_sectors WHERE track_id = ? ORDER BY sector_index",
        (track_id,),
    ).fetchall()
    for idx, row in enumerate(rows):
        conn.execute(
            "UPDATE track_sectors SET sector_index = ?, label = ? WHERE id = ?",
            (idx, f"S{idx + 1}", row["id"]),
        )
```

In `tracks.py`, add API routes:

```python
@bp.route("/<track_id>/sectors", methods=["GET"])
def get_sectors(track_id):
    conn = get_db_connection()
    from web.models import get_track_sectors
    return jsonify(get_track_sectors(conn, track_id))

@bp.route("/<track_id>/sectors/add", methods=["POST"])
def add_sector(track_id):
    conn = get_db_connection()
    from web.models import upsert_track_sector
    data = request.get_json(silent=True) or {}
    sector_id = upsert_track_sector(
        conn, track_id, float(data["lat"]), float(data["lon"]),
        distance_m=data.get("distance_m"),
    )
    conn.commit()
    return jsonify({"ok": True, "id": sector_id})

@bp.route("/<track_id>/sectors/<int:sector_id>/delete", methods=["POST"])
def remove_sector(track_id, sector_id):
    conn = get_db_connection()
    from web.models import delete_track_sector
    delete_track_sector(conn, track_id, sector_id)
    conn.commit()
    return jsonify({"ok": True})
```

In `track_detail.html`, add sector management UI (after the map script):

```html
<!-- Sector Management -->
<div class="sector-controls mt-sm">
    <button id="add-sector-btn" class="btn btn-sm">+ Add Sector</button>
    <span id="sector-mode-hint" class="text-muted" style="display:none;">Click on the map to place sector marker</span>
</div>
<div id="sector-list" class="mt-sm"></div>
```

Add JS to handle sector add mode (map click → POST), render numbered markers, delete on marker click.

**Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_track_features.py -v --tb=short`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/tracks.py telemetry_tool/web/templates/track_detail.html \
  telemetry_tool/web/models.py telemetry_tool/tests/test_track_features.py
git commit -m "feat: track-level sectors with map-click placement"
```

---

### Task 4: Track Deletion (Cascade)

**Files:**
- Modify: `telemetry_tool/web/routes/tracks.py` (add delete route)
- Modify: `telemetry_tool/web/models.py` (add `delete_track()`)
- Modify: `telemetry_tool/web/templates/track_detail.html` (add delete button + confirmation modal)
- Test: `telemetry_tool/tests/test_track_features.py` (add deletion tests)

**Step 1: Write failing test**

Add to `test_track_features.py`:

```python
class TestTrackDeletion:
    def test_cascade_deletes_sessions(self, db):
        from web.models import delete_track

        upsert_track(db, "t1", {"track_name": "Doomed", "lap_length_m": 500})
        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')")
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, "
            "session_type, session_date) VALUES ('s1', 'f.csv', 1, 't1', 'practice', '2026-01-01')"
        )
        db.commit()
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1

        delete_track(db, "t1")
        db.commit()

        assert db.execute("SELECT COUNT(*) FROM tracks WHERE track_id = 't1'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM sessions WHERE track_id = 't1'").fetchone()[0] == 0

    def test_delete_nonexistent_noop(self, db):
        from web.models import delete_track
        delete_track(db, "nope")  # Should not raise
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_track_features.py::TestTrackDeletion -v --tb=short`
Expected: FAIL — `delete_track` not found.

**Step 3: Implement**

In `models.py`:

```python
def delete_track(conn: sqlite3.Connection, track_id: str) -> None:
    """Delete a track and cascade to all dependent data."""
    # Get all session IDs at this track.
    session_rows = conn.execute(
        "SELECT session_id FROM sessions WHERE track_id = ?", (track_id,)
    ).fetchall()
    session_ids = [r["session_id"] for r in session_rows]

    for sid in session_ids:
        # Delete dependent data for each session.
        for table in (
            "laps", "gps_traces", "score_details", "session_sectors",
            "session_weather", "session_tags", "corner_metrics",
            "corner_best_practices", "stint_analysis", "vehicle_setups",
            "what_if_scenarios", "annotations",
        ):
            try:
                conn.execute(f"DELETE FROM {table} WHERE session_id = ?", (sid,))
            except sqlite3.OperationalError:
                pass  # Table may not exist in test DBs
        # Delete driver progression rows for this session.
        conn.execute("DELETE FROM driver_progression WHERE session_id = ?", (sid,))
        # Delete driving style features for this session.
        conn.execute("DELETE FROM driving_style_features WHERE session_id = ?", (sid,))

    # Delete sessions.
    conn.execute("DELETE FROM sessions WHERE track_id = ?", (track_id,))
    # Delete weekend_sessions referencing these sessions.
    for sid in session_ids:
        conn.execute("DELETE FROM weekend_sessions WHERE session_id = ?", (sid,))
    # Delete track records.
    conn.execute("DELETE FROM track_records WHERE track_id = ?", (track_id,))
    # Delete track sectors.
    conn.execute("DELETE FROM track_sectors WHERE track_id = ?", (track_id,))
    # Delete the track itself.
    conn.execute("DELETE FROM tracks WHERE track_id = ?", (track_id,))
```

In `tracks.py`:

```python
@bp.route("/<track_id>/delete", methods=["POST"])
def delete_track_route(track_id):
    conn = get_db_connection()
    from web.models import delete_track, get_track_by_id

    track = get_track_by_id(conn, track_id)
    if track is None:
        abort(404)

    # Require type-to-confirm.
    confirm_name = request.form.get("confirm_name", "").strip()
    if confirm_name != track["track_name"]:
        flash("Track name does not match. Deletion cancelled.", "error")
        return redirect(url_for("tracks.track_detail", track_id=track_id))

    delete_track(conn, track_id)
    conn.commit()
    return redirect(url_for("tracks.track_list"))
```

In `track_detail.html`, add at bottom of page:

```html
<!-- Delete Track -->
<section class="section danger-zone">
    <h2>Danger Zone</h2>
    <details>
        <summary class="btn btn-sm btn-danger">Delete This Track</summary>
        <form method="post" action="/tracks/{{ track.track_id }}/delete" class="mt-sm">
            <p class="text-muted">This will permanently delete <strong>{{ track.track_name }}</strong>
               and all {{ sessions|length }} sessions associated with it.</p>
            <label>Type "<strong>{{ track.track_name }}</strong>" to confirm:</label>
            <input type="text" name="confirm_name" required autocomplete="off" class="mt-xs">
            <button type="submit" class="btn btn-danger mt-sm">Permanently Delete</button>
        </form>
    </details>
</section>
```

**Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_track_features.py -v --tb=short`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/tracks.py telemetry_tool/web/templates/track_detail.html \
  telemetry_tool/web/models.py telemetry_tool/tests/test_track_features.py
git commit -m "feat: track deletion with cascade and type-to-confirm"
```

---

## Area 2: Karts

### Task 5: Kart CRUD Backend

**Files:**
- Create: `telemetry_tool/web/routes/karts.py` (new blueprint)
- Modify: `telemetry_tool/web/models.py` (add kart functions)
- Modify: `telemetry_tool/web/app.py:95-116` (register kart blueprint)
- Test: `telemetry_tool/tests/test_karts.py` (new)

**Step 1: Write failing test**

```python
"""Tests for kart CRUD operations."""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.migrate import ensure_schema


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    yield conn
    conn.close()


class TestKartCRUD:
    def test_create_from_predefined(self, db):
        from web.models import create_kart, get_kart_by_id

        # Pick first predefined kart.
        pk = db.execute("SELECT * FROM predefined_karts LIMIT 1").fetchone()
        kart_id = create_kart(db, kart_name="My Sodi", predefined_kart_id=pk["predefined_kart_id"])
        db.commit()

        kart = get_kart_by_id(db, kart_id)
        assert kart["kart_name"] == "My Sodi"
        assert kart["manufacturer"] == pk["manufacturer"]
        assert kart["power_hp"] == pk["power_hp"]

    def test_create_custom(self, db):
        from web.models import create_kart, get_kart_by_id

        kart_id = create_kart(
            db, kart_name="Custom Beast",
            manufacturer="DIY", model="V1", engine="Rotax", power_hp=30,
        )
        db.commit()

        kart = get_kart_by_id(db, kart_id)
        assert kart["kart_name"] == "Custom Beast"
        assert kart["predefined_kart_id"] is None

    def test_list_karts(self, db):
        from web.models import create_kart, get_all_karts

        create_kart(db, kart_name="K1")
        create_kart(db, kart_name="K2")
        db.commit()

        karts = get_all_karts(db)
        assert len(karts) == 2

    def test_update_kart(self, db):
        from web.models import create_kart, update_kart, get_kart_by_id

        kid = create_kart(db, kart_name="Old Name")
        db.commit()

        update_kart(db, kid, {"kart_name": "New Name", "notes": "Fast"})
        db.commit()

        kart = get_kart_by_id(db, kid)
        assert kart["kart_name"] == "New Name"
        assert kart["notes"] == "Fast"

    def test_delete_kart_unlinks_sessions(self, db):
        from web.models import create_kart, delete_kart

        kid = create_kart(db, kart_name="Temp")
        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')")
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, session_type, "
            "session_date, kart_id) VALUES ('s1', 'f.csv', 1, 'practice', '2026-01-01', ?)",
            (kid,),
        )
        db.commit()

        delete_kart(db, kid)
        db.commit()

        assert db.execute("SELECT COUNT(*) FROM karts WHERE kart_id = ?", (kid,)).fetchone()[0] == 0
        # Session still exists but kart_id is NULL.
        sess = db.execute("SELECT kart_id FROM sessions WHERE session_id = 's1'").fetchone()
        assert sess["kart_id"] is None
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_karts.py -v --tb=short`
Expected: FAIL — `create_kart` not found.

**Step 3: Implement**

In `models.py`:

```python
# ── Kart CRUD ────────────────────────────────────────────────────

def create_kart(
    conn: sqlite3.Connection,
    kart_name: str,
    predefined_kart_id: int | None = None,
    manufacturer: str | None = None,
    model: str | None = None,
    engine: str | None = None,
    power_hp: float | None = None,
    kart_weight_kg: float | None = None,
    notes: str | None = None,
) -> int:
    """Create a kart. If predefined_kart_id is set, auto-fill specs from reference."""
    if predefined_kart_id is not None:
        ref = conn.execute(
            "SELECT manufacturer, model, engine, power_hp, kart_weight_kg "
            "FROM predefined_karts WHERE predefined_kart_id = ?",
            (predefined_kart_id,),
        ).fetchone()
        if ref:
            manufacturer = manufacturer or ref["manufacturer"]
            model = model or ref["model"]
            engine = engine or ref["engine"]
            power_hp = power_hp if power_hp is not None else ref["power_hp"]
            kart_weight_kg = kart_weight_kg if kart_weight_kg is not None else ref["kart_weight_kg"]

    cur = conn.execute(
        "INSERT INTO karts (kart_name, predefined_kart_id, manufacturer, model, "
        "engine, power_hp, kart_weight_kg, notes) VALUES (?,?,?,?,?,?,?,?)",
        (kart_name, predefined_kart_id, manufacturer, model, engine,
         power_hp, kart_weight_kg, notes),
    )
    return cur.lastrowid


def get_kart_by_id(conn: sqlite3.Connection, kart_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM karts WHERE kart_id = ?", (kart_id,)).fetchone()
    return dict(row) if row else None


def get_all_karts(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT k.*, COUNT(s.session_id) as session_count "
        "FROM karts k LEFT JOIN sessions s ON k.kart_id = s.kart_id "
        "GROUP BY k.kart_id ORDER BY k.kart_name",
    ).fetchall()
    return [dict(r) for r in rows]


def update_kart(conn: sqlite3.Connection, kart_id: int, data: dict) -> None:
    allowed = {"kart_name", "manufacturer", "model", "engine", "power_hp", "kart_weight_kg", "notes"}
    for field, value in data.items():
        if field in allowed:
            conn.execute(f"UPDATE karts SET {field} = ? WHERE kart_id = ?", (value, kart_id))


def delete_kart(conn: sqlite3.Connection, kart_id: int) -> None:
    conn.execute("UPDATE sessions SET kart_id = NULL WHERE kart_id = ?", (kart_id,))
    conn.execute("DELETE FROM karts WHERE kart_id = ?", (kart_id,))
```

Create `telemetry_tool/web/routes/karts.py`:

```python
"""Kart routes — list, detail, create, edit, delete."""
from __future__ import annotations

from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for

from web.db import get_db_connection
from web.models import (
    create_kart, delete_kart, get_all_karts, get_kart_by_id, update_kart,
)

bp = Blueprint("karts", __name__, url_prefix="/karts")


@bp.route("/")
def kart_list():
    conn = get_db_connection()
    karts = get_all_karts(conn)
    predefined = conn.execute(
        "SELECT * FROM predefined_karts ORDER BY segment, manufacturer, model"
    ).fetchall()
    return render_template("kart_list.html", karts=karts, predefined=[dict(r) for r in predefined])


@bp.route("/<int:kart_id>")
def kart_detail(kart_id):
    conn = get_db_connection()
    kart = get_kart_by_id(conn, kart_id)
    if kart is None:
        abort(404)
    sessions = conn.execute(
        "SELECT s.*, d.driver_name, t.track_name FROM sessions s "
        "LEFT JOIN drivers d ON s.driver_id = d.driver_id "
        "LEFT JOIN tracks t ON s.track_id = t.track_id "
        "WHERE s.kart_id = ? ORDER BY s.session_date DESC",
        (kart_id,),
    ).fetchall()
    return render_template("kart_detail.html", kart=kart, sessions=[dict(r) for r in sessions])


@bp.route("/new", methods=["GET", "POST"])
def kart_new():
    conn = get_db_connection()
    if request.method == "POST":
        pk_id = request.form.get("predefined_kart_id")
        pk_id = int(pk_id) if pk_id else None
        kart_id = create_kart(
            conn,
            kart_name=request.form["kart_name"],
            predefined_kart_id=pk_id,
            manufacturer=request.form.get("manufacturer") or None,
            model=request.form.get("model") or None,
            engine=request.form.get("engine") or None,
            power_hp=float(request.form["power_hp"]) if request.form.get("power_hp") else None,
            kart_weight_kg=float(request.form["kart_weight_kg"]) if request.form.get("kart_weight_kg") else None,
            notes=request.form.get("notes") or None,
        )
        conn.commit()
        return redirect(url_for("karts.kart_detail", kart_id=kart_id))

    predefined = conn.execute(
        "SELECT * FROM predefined_karts ORDER BY segment, manufacturer, model"
    ).fetchall()
    return render_template("kart_form.html", kart=None, predefined=[dict(r) for r in predefined])


@bp.route("/<int:kart_id>/edit", methods=["GET", "POST"])
def kart_edit(kart_id):
    conn = get_db_connection()
    kart = get_kart_by_id(conn, kart_id)
    if kart is None:
        abort(404)
    if request.method == "POST":
        update_kart(conn, kart_id, {
            "kart_name": request.form["kart_name"],
            "manufacturer": request.form.get("manufacturer") or None,
            "model": request.form.get("model") or None,
            "engine": request.form.get("engine") or None,
            "power_hp": float(request.form["power_hp"]) if request.form.get("power_hp") else None,
            "kart_weight_kg": float(request.form["kart_weight_kg"]) if request.form.get("kart_weight_kg") else None,
            "notes": request.form.get("notes") or None,
        })
        conn.commit()
        return redirect(url_for("karts.kart_detail", kart_id=kart_id))
    return render_template("kart_form.html", kart=kart, predefined=[])


@bp.route("/<int:kart_id>/delete", methods=["POST"])
def kart_delete(kart_id):
    conn = get_db_connection()
    delete_kart(conn, kart_id)
    conn.commit()
    return redirect(url_for("karts.kart_list"))
```

In `app.py`, add to `_blueprint_imports` list:
```python
('.routes.karts', 'bp', 'karts_bp'),
```

**Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_karts.py -v --tb=short`
Expected: All 5 tests PASS.

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/karts.py telemetry_tool/web/models.py \
  telemetry_tool/web/app.py telemetry_tool/tests/test_karts.py
git commit -m "feat: kart CRUD backend with predefined reference data"
```

---

### Task 6: Kart Templates + Navigation

**Files:**
- Create: `telemetry_tool/web/templates/kart_list.html`
- Create: `telemetry_tool/web/templates/kart_detail.html`
- Create: `telemetry_tool/web/templates/kart_form.html`
- Modify: `telemetry_tool/web/templates/base.html:61-71` (add Karts nav entry)

**Step 1: Create kart_list.html**

Card grid layout matching existing track_list.html style:
- Card per kart: name, manufacturer, model, engine, power, session count badge
- "New Kart" CTA button
- Empty state hero if no karts

**Step 2: Create kart_detail.html**

- Header with kart name
- Specs grid (manufacturer, model, engine, power, weight, top speed)
- If linked to predefined: show full predefined specs
- Session history table (reuse session table pattern from driver_profile.html)
- Edit / Delete buttons

**Step 3: Create kart_form.html**

- Kart name (required)
- Predefined kart search (autocomplete/select with JS filter)
- When predefined selected: auto-fill manufacturer, model, engine, power, weight fields
- Manual override fields always visible
- Submit: "Create Kart" or "Save Changes"

**Step 4: Update navigation in base.html**

At line 69-70, after the Weekends link, add:
```html
<a class="nav-dropdown-item" href="/karts/" role="menuitem">
    <span class="nav-dropdown-icon" aria-hidden="true">&#x1F3CE;</span> Karts
</a>
```

Also update the active-state condition in the dropdown trigger (line 56-58) to include `request.endpoint.startswith('karts.')`.

**Step 5: Commit**

```bash
git add telemetry_tool/web/templates/kart_list.html telemetry_tool/web/templates/kart_detail.html \
  telemetry_tool/web/templates/kart_form.html telemetry_tool/web/templates/base.html
git commit -m "feat: kart templates (list, detail, form) and navigation"
```

---

### Task 7: Session-Kart Linking

**Files:**
- Modify: `telemetry_tool/web/templates/session_detail.html` (add kart display + selector)
- Modify: `telemetry_tool/web/routes/sessions.py` (add kart assignment endpoint)
- Test: manual verification via UI

**Step 1: Add kart display to session detail**

In the session info/meta grid section of `session_detail.html`, add a kart field:
```html
<div class="meta-item">
    <span class="meta-label">Kart</span>
    <span class="meta-value">
        {% if session.kart_id %}
            <a href="/karts/{{ session.kart_id }}">{{ session.kart_name or 'Kart #' ~ session.kart_id }}</a>
        {% else %}
            <span class="text-muted">Not assigned</span>
        {% endif %}
    </span>
</div>
```

**Step 2: Add kart assignment API**

In sessions route (or api_data route):
```python
@bp.route("/<session_id>/kart", methods=["POST"])
def assign_kart(session_id):
    conn = get_db_connection()
    data = request.get_json(silent=True) or {}
    kart_id = data.get("kart_id")
    conn.execute("UPDATE sessions SET kart_id = ? WHERE session_id = ?", (kart_id, session_id))
    conn.commit()
    return jsonify({"ok": True})
```

**Step 3: Update session detail query to join kart name**

In the session detail route, modify the query to LEFT JOIN karts:
```sql
SELECT s.*, k.kart_name FROM sessions s
LEFT JOIN karts k ON s.kart_id = k.kart_id
WHERE s.session_id = ?
```

**Step 4: Commit**

```bash
git add telemetry_tool/web/templates/session_detail.html telemetry_tool/web/routes/sessions.py
git commit -m "feat: session-kart linking with detail display"
```

---

## Area 3: Drivers

### Task 8: Driver Deletion (Cascade)

**Files:**
- Modify: `telemetry_tool/web/routes/drivers.py` (add delete route)
- Modify: `telemetry_tool/web/models.py` (add `delete_driver()`)
- Modify: `telemetry_tool/web/templates/driver_profile.html` (add delete UI)
- Test: `telemetry_tool/tests/test_driver_features.py` (new)

**Step 1: Write failing test**

```python
"""Tests for driver management features."""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.migrate import ensure_schema
from web.models import upsert_driver


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    yield conn
    conn.close()


class TestDriverDeletion:
    def test_cascade_deletes_sessions_and_progression(self, db):
        from web.models import delete_driver

        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Doomed')")
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, session_type, "
            "session_date) VALUES ('s1', 'f.csv', 1, 'practice', '2026-01-01')"
        )
        db.execute(
            "INSERT INTO driver_profiles (driver_id) VALUES (1)"
        )
        db.commit()

        delete_driver(db, 1)
        db.commit()

        assert db.execute("SELECT COUNT(*) FROM drivers WHERE driver_id = 1").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM sessions WHERE driver_id = 1").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM driver_profiles WHERE driver_id = 1").fetchone()[0] == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_driver_features.py::TestDriverDeletion -v --tb=short`

**Step 3: Implement**

In `models.py`:

```python
def delete_driver(conn: sqlite3.Connection, driver_id: int) -> None:
    """Delete a driver and cascade to all dependent data."""
    # Get all session IDs for this driver.
    session_rows = conn.execute(
        "SELECT session_id FROM sessions WHERE driver_id = ?", (driver_id,)
    ).fetchall()
    session_ids = [r["session_id"] for r in session_rows]

    for sid in session_ids:
        for table in (
            "laps", "gps_traces", "score_details", "session_sectors",
            "session_weather", "session_tags", "corner_metrics",
            "corner_best_practices", "stint_analysis", "vehicle_setups",
            "what_if_scenarios", "annotations",
        ):
            try:
                conn.execute(f"DELETE FROM {table} WHERE session_id = ?", (sid,))
            except sqlite3.OperationalError:
                pass
        conn.execute("DELETE FROM weekend_sessions WHERE session_id = ?", (sid,))

    conn.execute("DELETE FROM sessions WHERE driver_id = ?", (driver_id,))
    conn.execute("DELETE FROM driver_progression WHERE driver_id = ?", (driver_id,))
    conn.execute("DELETE FROM driving_style_features WHERE driver_id = ?", (driver_id,))
    conn.execute("DELETE FROM driver_profiles WHERE driver_id = ?", (driver_id,))
    conn.execute("DELETE FROM drivers WHERE driver_id = ?", (driver_id,))
```

In `drivers.py`:

```python
@bp.route("/<int:driver_id>/delete", methods=["POST"])
def delete_driver_route(driver_id):
    conn = get_db_connection()
    from web.models import delete_driver

    driver = conn.execute(
        "SELECT * FROM drivers WHERE driver_id = ?", (driver_id,)
    ).fetchone()
    if driver is None:
        abort(404)

    confirm_name = request.form.get("confirm_name", "").strip()
    if confirm_name != driver["driver_name"]:
        return redirect(url_for("drivers.driver_detail", driver_id=driver_id))

    delete_driver(conn, driver_id)
    conn.commit()
    return redirect(url_for("drivers.driver_list"))
```

In `driver_profile.html`, add danger zone section (same pattern as track deletion).

**Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_driver_features.py -v --tb=short`

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/drivers.py telemetry_tool/web/models.py \
  telemetry_tool/web/templates/driver_profile.html telemetry_tool/tests/test_driver_features.py
git commit -m "feat: driver deletion with cascade and type-to-confirm"
```

---

### Task 9: Consistency Rating Fix (1500% Bug)

**Files:**
- Modify: `telemetry_tool/pipeline.py:2374` (fix consistency_rating computation)
- Modify: `telemetry_tool/web/templates/driver_profile.html:42` (fix display)
- Test: `telemetry_tool/tests/test_driver_features.py` (add consistency test)

**Root cause analysis:**
- `pipeline.py:2374` stores `consistency_rating = float(np.mean(_cvs))` where `_cvs` are `consistency_cv_pct` values (already percentages, e.g. 1.5 means 1.5%).
- `driver_profile.html:42` displays `profile.consistency_rating * 100` — so 1.5 → 150%, or 15.0 → 1500%.

**Fix:** The pipeline stores the mean CV% as-is (e.g., 1.5). The template should display it directly without multiplying by 100.

**Step 1: Write failing test**

Add to `test_driver_features.py`:

```python
class TestConsistencyRating:
    def test_consistency_stored_as_pct(self, db):
        """consistency_rating should be raw CV% (e.g. 2.5 meaning 2.5%)."""
        from web.models import upsert_driver_profile, get_driver_profile

        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')")
        db.commit()

        upsert_driver_profile(db, 1, {"consistency_rating": 2.5})
        db.commit()

        profile = get_driver_profile(db, 1)
        # Should be 2.5 (percent), not 0.025 (ratio).
        assert profile["consistency_rating"] == 2.5
```

**Step 2: Run test (should pass — storage is fine)**

The storage is correct. The bug is in the template display only.

**Step 3: Fix template**

In `driver_profile.html` line 42, change:
```html
<!-- BEFORE (buggy): -->
<span class="meta-value">{{ "%.1f"|format(profile.consistency_rating * 100) }}%</span>

<!-- AFTER (fixed): -->
<span class="meta-value">{{ "%.1f"|format(profile.consistency_rating) }}%</span>
```

**Step 4: Verify manually**

The template fix is display-only. Verify by viewing a driver profile in the app.

**Step 5: Commit**

```bash
git add telemetry_tool/web/templates/driver_profile.html telemetry_tool/tests/test_driver_features.py
git commit -m "fix: consistency rating display — remove erroneous ×100 multiplier"
```

---

### Task 10: Progression Chart Fix

**Files:**
- Modify: `telemetry_tool/web/templates/driver_profile.html:147,240-248` (fix chart rendering)
- Investigate: `telemetry_tool/web/static/js/progression.js:167-288`

**Debugging steps:**

1. Check if the section even renders — line 147: `{% if progression|length > 1 %}`. If `progression` is empty or length 1, the canvas elements won't exist in DOM. The `init()` call (line 242-248) is also gated by this check.

2. Check `progression.js:175`: `FetchHelper.fetch('/drivers/' + driverId + '/api/progression')`. Verify the endpoint returns data.

3. Check if `FetchHelper` is defined before `progression.js` — it is (base.html loads `fetch_helper.js` at line 183, and `progression.js` is loaded after in block scripts).

**Most likely cause:** The pipeline may not be inserting `driver_progression` rows, so `get_driver_progression()` returns an empty list, and the template condition `progression|length > 1` is False → section never renders.

**Fix approach:**

1. Lower the threshold — show the chart even with 1 data point (as a single dot):
```html
{% if progression %}
```

2. In `progression.js` line 187, change the minimum check:
```javascript
if (!prog || prog.length < 1) return;  // was < 2
```
For a single point, draw just the dot without a line.

3. If the issue is that `driver_progression` has no data, we need to ensure the pipeline inserts rows. Check if the Phase 3 pipeline step is completing without error. This may require investigating `pipeline.py:2320-2331`.

**Step 1: Fix template threshold**

Change line 147:
```html
{% if progression %}
```

**Step 2: Fix JS minimum**

In `progression.js:187`, change:
```javascript
if (!prog || prog.length < 1) return;
```

**Step 3: Add fallback message**

If the API returns empty data, show a message instead of blank space:
```javascript
.then(function (json) {
    data = json;
    if (!data.progression || data.progression.length === 0) {
        if (paceCanvas) {
            var ctx = paceCanvas.getContext('2d');
            ctx.fillStyle = COLORS.text;
            ctx.font = '14px system-ui, sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('No progression data yet — analyze more sessions', paceCanvas.width / 2, 60);
        }
        return;
    }
    // ... existing draw logic
```

**Step 4: Commit**

```bash
git add telemetry_tool/web/templates/driver_profile.html telemetry_tool/web/static/js/progression.js
git commit -m "fix: progression chart renders with 1+ data points and shows fallback message"
```

---

### Task 11: Best Ever Redesign

**Files:**
- Modify: `telemetry_tool/web/routes/drivers.py:58-70` (compute relative performance)
- Modify: `telemetry_tool/web/templates/driver_profile.html:27-32` (new best-ever display)
- Test: `telemetry_tool/tests/test_driver_features.py` (add best-ever tests)

**Step 1: Write failing test**

Add to `test_driver_features.py`:

```python
class TestBestEverRelative:
    def test_relative_performance(self, db):
        from web.models import compute_best_ever_relative

        # Create track with record
        db.execute(
            "INSERT INTO tracks (track_id, track_name, lap_length_m) "
            "VALUES ('t1', 'Track A', 500)"
        )
        db.execute(
            "INSERT INTO track_records (track_id, record_time_s, vehicle_class) "
            "VALUES ('t1', 60.0, 'default')"
        )
        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Racer')")
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, "
            "session_type, session_date, best_lap_time_s) "
            "VALUES ('s1', 'f.csv', 1, 't1', 'practice', '2026-01-01', 61.5)"
        )
        db.commit()

        result = compute_best_ever_relative(db, 1)
        assert result["best_pct"] is not None
        assert abs(result["best_pct"] - 102.5) < 0.1  # 61.5/60.0 * 100
        assert result["best_track_name"] == "Track A"

    def test_no_records_fallback(self, db):
        from web.models import compute_best_ever_relative

        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Racer')")
        db.execute(
            "INSERT INTO tracks (track_id, track_name, lap_length_m) VALUES ('t1', 'T', 500)"
        )
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, "
            "session_type, session_date, best_lap_time_s) "
            "VALUES ('s1', 'f.csv', 1, 't1', 'practice', '2026-01-01', 61.5)"
        )
        db.commit()

        result = compute_best_ever_relative(db, 1)
        assert result["best_pct"] is None
        assert result["best_absolute_s"] == 61.5

    def test_records_held(self, db):
        from web.models import compute_best_ever_relative

        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Champ')")
        db.execute(
            "INSERT INTO tracks (track_id, track_name, lap_length_m) VALUES ('t1', 'Track A', 500)"
        )
        db.execute(
            "INSERT INTO track_records (track_id, record_time_s, record_holder, vehicle_class) "
            "VALUES ('t1', 60.0, 'Champ', 'Senior')"
        )
        db.commit()

        result = compute_best_ever_relative(db, 1)
        assert len(result["records_held"]) == 1
        assert result["records_held"][0]["track_name"] == "Track A"
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_driver_features.py::TestBestEverRelative -v --tb=short`

**Step 3: Implement**

In `models.py`:

```python
def compute_best_ever_relative(conn: sqlite3.Connection, driver_id: int) -> dict:
    """Compute relative best-ever (% of track record) and records held."""
    driver = conn.execute(
        "SELECT driver_name FROM drivers WHERE driver_id = ?", (driver_id,)
    ).fetchone()
    driver_name = driver["driver_name"] if driver else ""

    # Per-track best times for this driver.
    track_bests = conn.execute(
        "SELECT s.track_id, t.track_name, MIN(s.best_lap_time_s) as best_time "
        "FROM sessions s JOIN tracks t ON s.track_id = t.track_id "
        "WHERE s.driver_id = ? AND s.best_lap_time_s IS NOT NULL "
        "GROUP BY s.track_id",
        (driver_id,),
    ).fetchall()

    best_pct = None
    best_track_name = None
    best_driver_time = None
    best_record_time = None
    best_absolute_s = None

    # Find absolute best.
    if track_bests:
        best_abs_row = min(track_bests, key=lambda r: r["best_time"])
        best_absolute_s = best_abs_row["best_time"]

    # Compute relative % for tracks with records.
    for tb in track_bests:
        record = conn.execute(
            "SELECT MIN(record_time_s) as record_time FROM track_records WHERE track_id = ?",
            (tb["track_id"],),
        ).fetchone()
        if record and record["record_time"] and record["record_time"] > 0:
            pct = (tb["best_time"] / record["record_time"]) * 100
            if best_pct is None or pct < best_pct:
                best_pct = round(pct, 2)
                best_track_name = tb["track_name"]
                best_driver_time = tb["best_time"]
                best_record_time = record["record_time"]

    # Records held by this driver.
    records_held = []
    held_rows = conn.execute(
        "SELECT tr.*, t.track_name FROM track_records tr "
        "JOIN tracks t ON tr.track_id = t.track_id "
        "WHERE tr.record_holder = ?",
        (driver_name,),
    ).fetchall()
    records_held = [dict(r) for r in held_rows]

    return {
        "best_pct": best_pct,
        "best_track_name": best_track_name,
        "best_driver_time": best_driver_time,
        "best_record_time": best_record_time,
        "best_absolute_s": best_absolute_s,
        "records_held": records_held,
    }
```

In `drivers.py`, update `driver_detail()` to compute and pass this data:

```python
# After existing best_ever logic (lines 58-71), add:
from web.models import compute_best_ever_relative
best_ever = compute_best_ever_relative(conn, driver_id)
```

Pass `best_ever=best_ever` to `render_template()`.

In `driver_profile.html`, replace lines 27-32 with:

```html
{% if best_ever.best_pct %}
<div class="meta-item">
    <span class="meta-label">Peak Performance</span>
    <span class="meta-value highlight">{{ "%.1f"|format(best_ever.best_pct) }}%
        <span class="text-muted text-sm">at {{ best_ever.best_track_name }}</span>
    </span>
</div>
{% elif best_ever.best_absolute_s %}
<div class="meta-item">
    <span class="meta-label">Best Ever</span>
    <span class="meta-value highlight">{{ "%.3f"|format(best_ever.best_absolute_s) }}s</span>
</div>
{% endif %}
```

Add a "Track Records Held" section after the meta grid:

```html
{% if best_ever.records_held %}
<section class="section">
    <h2>Track Records Held</h2>
    <div class="records-held-list">
        {% for rec in best_ever.records_held %}
        <div class="record-held-item">
            <a href="/tracks/{{ rec.track_id }}">{{ rec.track_name }}</a>
            — {{ "%.3f"|format(rec.record_time_s) }}s
            {% if rec.vehicle_class and rec.vehicle_class != 'default' %}({{ rec.vehicle_class }}){% endif %}
        </div>
        {% endfor %}
    </div>
</section>
{% endif %}
```

**Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_driver_features.py -v --tb=short`

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/drivers.py telemetry_tool/web/models.py \
  telemetry_tool/web/templates/driver_profile.html telemetry_tool/tests/test_driver_features.py
git commit -m "feat: best-ever shows relative % to track record + records held list"
```

---

### Task 12: Track Selection with "New Track" + Predefined List

**Files:**
- Modify: `telemetry_tool/web/templates/analyze_form.html` (add "New track" option with predefined search)
- Modify: `telemetry_tool/web/routes/tracks.py` (add API for predefined track search)
- Modify: `telemetry_tool/web/models.py` (add `create_track_from_predefined()`)

**Step 1: Add predefined tracks API**

In `tracks.py`:

```python
@bp.route("/api/predefined", methods=["GET"])
def predefined_tracks_api():
    """Search predefined tracks for autocomplete."""
    conn = get_db_connection()
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])
    rows = conn.execute(
        "SELECT * FROM predefined_tracks WHERE track_name LIKE ? OR layout_name LIKE ? "
        "ORDER BY track_name LIMIT 20",
        (f"%{q}%", f"%{q}%"),
    ).fetchall()
    return jsonify([dict(r) for r in rows])
```

**Step 2: Add track creation from predefined**

In `models.py`:

```python
def create_track_from_predefined(
    conn: sqlite3.Connection, predefined_track_id: int, custom_name: str | None = None,
) -> str:
    """Create a tracks entry linked to a predefined track. Returns track_id."""
    import uuid
    ref = conn.execute(
        "SELECT * FROM predefined_tracks WHERE predefined_track_id = ?",
        (predefined_track_id,),
    ).fetchone()
    if ref is None:
        raise ValueError("Predefined track not found")
    ref = dict(ref)

    track_id = str(uuid.uuid4())[:12]
    name = custom_name or f"{ref['track_name']} — {ref['layout_name'] or 'Default'}"
    length = ref.get("layout_length_m")

    conn.execute(
        "INSERT INTO tracks (track_id, track_name, lap_length_m, predefined_track_id) "
        "VALUES (?, ?, ?, ?)",
        (track_id, name, length or 0, predefined_track_id),
    )
    return track_id
```

**Step 3: Update analyze form template**

Add a "New track..." option to the track dropdown, which expands a searchable sub-panel with predefined tracks and a custom name input.

**Step 4: Commit**

```bash
git add telemetry_tool/web/routes/tracks.py telemetry_tool/web/models.py \
  telemetry_tool/web/templates/analyze_form.html
git commit -m "feat: track selection with predefined search and 'New track' option"
```

---

## Area 4: Weekends

### Task 13: Session Reordering (Arrows + Drag-and-Drop)

**Files:**
- Modify: `telemetry_tool/web/routes/weekends.py` (add reorder endpoints)
- Modify: `telemetry_tool/web/templates/weekend_detail.html:88-140` (add arrow buttons + drag handlers)
- Test: `telemetry_tool/tests/test_weekend_features.py` (new)

**Step 1: Write failing test**

```python
"""Tests for weekend management features."""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.migrate import ensure_schema
from web.models import create_weekend, add_session_to_weekend


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    conn.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')")
    conn.execute(
        "INSERT INTO tracks (track_id, track_name, lap_length_m) VALUES ('t1', 'T', 500)"
    )
    for i in range(1, 4):
        conn.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, "
            "session_type, session_date) VALUES (?, ?, 1, 't1', 'practice', '2026-01-0' || ?)",
            (f"s{i}", f"f{i}.csv", str(i)),
        )
    conn.commit()
    yield conn
    conn.close()


class TestSessionReorder:
    def test_swap_down(self, db):
        from web.models import swap_weekend_session_order, get_weekend_sessions

        wid = create_weekend(db, {"name": "W1"})
        add_session_to_weekend(db, wid, "s1", 0)
        add_session_to_weekend(db, wid, "s2", 1)
        add_session_to_weekend(db, wid, "s3", 2)
        db.commit()

        swap_weekend_session_order(db, wid, "s1", "down")
        db.commit()

        sessions = get_weekend_sessions(db, wid)
        assert sessions[0]["session_id"] == "s2"
        assert sessions[1]["session_id"] == "s1"
        assert sessions[2]["session_id"] == "s3"

    def test_reorder_all(self, db):
        from web.models import reorder_weekend_sessions, get_weekend_sessions

        wid = create_weekend(db, {"name": "W1"})
        add_session_to_weekend(db, wid, "s1", 0)
        add_session_to_weekend(db, wid, "s2", 1)
        add_session_to_weekend(db, wid, "s3", 2)
        db.commit()

        reorder_weekend_sessions(db, wid, ["s3", "s1", "s2"])
        db.commit()

        sessions = get_weekend_sessions(db, wid)
        assert sessions[0]["session_id"] == "s3"
        assert sessions[1]["session_id"] == "s1"
        assert sessions[2]["session_id"] == "s2"
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_weekend_features.py -v --tb=short`

**Step 3: Implement backend**

In `models.py`:

```python
def swap_weekend_session_order(
    conn: sqlite3.Connection, weekend_id: int, session_id: str, direction: str
) -> None:
    """Swap a session with its neighbor (up or down)."""
    sessions = get_weekend_sessions(conn, weekend_id)
    idx = next((i for i, s in enumerate(sessions) if s["session_id"] == session_id), None)
    if idx is None:
        return

    swap_idx = idx - 1 if direction == "up" else idx + 1
    if swap_idx < 0 or swap_idx >= len(sessions):
        return

    # Swap session_order values.
    a_order = sessions[idx]["session_order"]
    b_order = sessions[swap_idx]["session_order"]
    conn.execute(
        "UPDATE weekend_sessions SET session_order = ? WHERE weekend_id = ? AND session_id = ?",
        (b_order, weekend_id, sessions[idx]["session_id"]),
    )
    conn.execute(
        "UPDATE weekend_sessions SET session_order = ? WHERE weekend_id = ? AND session_id = ?",
        (a_order, weekend_id, sessions[swap_idx]["session_id"]),
    )


def reorder_weekend_sessions(
    conn: sqlite3.Connection, weekend_id: int, session_ids: list[str]
) -> None:
    """Set session_order based on the given list order."""
    for idx, sid in enumerate(session_ids):
        conn.execute(
            "UPDATE weekend_sessions SET session_order = ? WHERE weekend_id = ? AND session_id = ?",
            (idx, weekend_id, sid),
        )
```

In `weekends.py`, add routes:

```python
@bp.route("/<int:weekend_id>/reorder", methods=["POST"])
def weekend_reorder(weekend_id):
    from web.models import swap_weekend_session_order
    conn = get_db_connection()
    data = request.get_json(silent=True) or {}
    swap_weekend_session_order(conn, weekend_id, data["session_id"], data["direction"])
    conn.commit()
    return jsonify({"ok": True})


@bp.route("/<int:weekend_id>/reorder_all", methods=["POST"])
def weekend_reorder_all(weekend_id):
    from web.models import reorder_weekend_sessions
    conn = get_db_connection()
    data = request.get_json(silent=True) or {}
    reorder_weekend_sessions(conn, weekend_id, data["session_ids"])
    conn.commit()
    return jsonify({"ok": True})
```

In `weekend_detail.html`, add an "Order" column to the sessions table with up/down arrow buttons:

```html
<td class="col-order">
    <button class="btn-icon reorder-btn" data-sid="{{ s.session_id }}" data-dir="up"
            {% if loop.first %}disabled{% endif %}>&#x25B2;</button>
    <button class="btn-icon reorder-btn" data-sid="{{ s.session_id }}" data-dir="down"
            {% if loop.last %}disabled{% endif %}>&#x25BC;</button>
</td>
```

Add JS for arrow click (POST to reorder, reload table) and HTML5 drag-and-drop (dragstart/dragover/drop → POST reorder_all).

**Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_weekend_features.py -v --tb=short`

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/weekends.py telemetry_tool/web/models.py \
  telemetry_tool/web/templates/weekend_detail.html telemetry_tool/tests/test_weekend_features.py
git commit -m "feat: weekend session reordering with arrows and drag-and-drop"
```

---

### Task 14: Weekend Enhanced Insights

**Files:**
- Modify: `telemetry_tool/cross_session.py:253` (add `compute_weekend_insights()`)
- Modify: `telemetry_tool/web/routes/weekends.py:73-96` (compute and pass insights)
- Modify: `telemetry_tool/web/templates/weekend_detail.html` (add insight sections)
- Create: `telemetry_tool/web/static/js/weekend_insights.js` (heatmap canvas)
- Test: `telemetry_tool/tests/test_weekend_features.py` (add insights tests)

**Step 1: Write failing test**

Add to `test_weekend_features.py`:

```python
class TestWeekendInsights:
    def _seed_weekend_with_laps(self, db):
        from web.models import create_weekend, add_session_to_weekend, insert_laps

        wid = create_weekend(db, {"name": "W1", "track_id": "t1"})

        for sess_idx in range(1, 4):
            sid = f"s{sess_idx}"
            add_session_to_weekend(db, wid, sid, sess_idx - 1)

            # Create 5 laps per session.
            summary = {
                "lap_metrics": [
                    {"lap_number": i, "lap_time_s": 60.0 + i * 0.1 - sess_idx * 0.5,
                     "speed_mean_mps": 20, "speed_max_mps": 30,
                     "braking_max_mps2": 10, "accel_max_mps2": 5, "line_length_m": 500}
                    for i in range(1, 6)
                ],
                "best_lap_key": 1,
                "lap_to_phase": {},
                "trim_report": {"outlap_analysis": {"outlap_numbers": [], "inlap_numbers": [], "flagged_only": []}},
                "incomplete_lap_analysis": {"incomplete_laps": []},
                "anomalous_lap_analysis": {"flagged_laps": [], "dist_flagged": [], "time_flagged": []},
                "line_deviation_analysis": {"deviated_laps": []},
                "joker_lap_number": None,
                "session_meta": {"session_type": "practice", "drivers": []},
            }
            insert_laps(db, sid, summary)

        db.commit()
        return wid

    def test_insights_has_consistency_breakdown(self, db):
        from cross_session import compute_weekend_insights

        wid = self._seed_weekend_with_laps(db)
        insights = compute_weekend_insights(db, wid)
        assert "consistency_breakdown" in insights
        assert len(insights["consistency_breakdown"]) == 3

    def test_insights_has_improvement_summary(self, db):
        from cross_session import compute_weekend_insights

        wid = self._seed_weekend_with_laps(db)
        insights = compute_weekend_insights(db, wid)
        assert "improvement_pct" in insights
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_weekend_features.py::TestWeekendInsights -v --tb=short`

**Step 3: Implement**

In `cross_session.py`, add after `compute_weekend_summary()`:

```python
def compute_weekend_insights(
    conn: sqlite3.Connection, weekend_id: int
) -> dict[str, Any]:
    """Compute enhanced insights for a weekend: consistency, heatmap, improvement."""
    import numpy as np

    # Get ordered session IDs.
    ws_rows = conn.execute(
        "SELECT ws.session_id, s.session_date, s.best_lap_time_s, d.driver_name "
        "FROM weekend_sessions ws "
        "JOIN sessions s ON ws.session_id = s.session_id "
        "LEFT JOIN drivers d ON s.driver_id = d.driver_id "
        "ORDER BY ws.session_order, s.session_date",
        (weekend_id,),
    ).fetchall()

    consistency_breakdown = []
    heatmap_data = []  # [[lap_time_delta, ...], ...]
    avg_times = []

    for ws in ws_rows:
        sid = ws["session_id"]
        laps = conn.execute(
            "SELECT lap_number, lap_time_s FROM laps "
            "WHERE session_id = ? AND is_valid = 1 ORDER BY lap_number",
            (sid,),
        ).fetchall()

        times = [l["lap_time_s"] for l in laps if l["lap_time_s"]]
        if not times:
            consistency_breakdown.append({
                "session_id": sid, "session_date": ws["session_date"],
                "driver_name": ws["driver_name"], "n_laps": 0,
                "mean_time": None, "cv_pct": None, "best": None, "worst": None,
            })
            continue

        mean_t = float(np.mean(times))
        std_t = float(np.std(times))
        cv_pct = (std_t / mean_t * 100) if mean_t > 0 else 0
        best_t = min(times)

        consistency_breakdown.append({
            "session_id": sid, "session_date": ws["session_date"],
            "driver_name": ws["driver_name"], "n_laps": len(times),
            "mean_time": round(mean_t, 3), "cv_pct": round(cv_pct, 2),
            "best": round(best_t, 3), "worst": round(max(times), 3),
        })

        # Heatmap row: delta from session best.
        row = []
        for l in laps:
            if l["lap_time_s"]:
                row.append(round(l["lap_time_s"] - best_t, 3))
            else:
                row.append(None)
        heatmap_data.append({"session_id": sid, "deltas": row})

        avg_times.append(mean_t)

    # Improvement summary.
    improvement_pct = None
    if len(avg_times) >= 2:
        first_avg = avg_times[0]
        last_avg = avg_times[-1]
        if first_avg > 0:
            improvement_pct = round(((first_avg - last_avg) / first_avg) * 100, 2)

    # Best / worst session by average time.
    best_session_idx = None
    worst_session_idx = None
    if avg_times:
        best_session_idx = int(np.argmin(avg_times))
        worst_session_idx = int(np.argmax(avg_times))

    return {
        "consistency_breakdown": consistency_breakdown,
        "heatmap_data": heatmap_data,
        "improvement_pct": improvement_pct,
        "avg_times": [round(t, 3) for t in avg_times],
        "best_session_idx": best_session_idx,
        "worst_session_idx": worst_session_idx,
    }
```

In `weekends.py`, update `weekend_detail()` to call and pass insights:

```python
from cross_session import compute_weekend_insights
insights = compute_weekend_insights(conn, weekend_id)
# Pass to template
```

In `weekend_detail.html`, add three new sections after the sessions table:

1. **Consistency Breakdown table** — iterate `insights.consistency_breakdown`
2. **Heatmap canvas** — load `weekend_insights.js` which draws the heatmap from `insights.heatmap_data`
3. **Improvement Summary** — display `insights.improvement_pct` with green/red indicator + avg time chart

Create `weekend_insights.js` with canvas rendering for the heatmap grid.

**Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_weekend_features.py -v --tb=short`

**Step 5: Commit**

```bash
git add telemetry_tool/cross_session.py telemetry_tool/web/routes/weekends.py \
  telemetry_tool/web/templates/weekend_detail.html \
  telemetry_tool/web/static/js/weekend_insights.js \
  telemetry_tool/tests/test_weekend_features.py
git commit -m "feat: enhanced weekend insights — consistency breakdown, heatmap, improvement summary"
```

---

## Final Task

### Task 15: Integration Test + CSS Polish

**Files:**
- Run all tests: `pytest telemetry_tool/tests/ -v --tb=short`
- Modify: `telemetry_tool/web/static/css/main.css` (add styles for new components)

**Step 1: Run full test suite**

```bash
pytest telemetry_tool/tests/ -v --tb=short
```

Expected: All tests PASS (existing + new).

**Step 2: Add CSS for new components**

Add to `main.css`:

```css
/* Danger zone for delete actions */
.danger-zone { border-top: 2px solid var(--red, #f85149); margin-top: 2rem; padding-top: 1rem; }
.danger-zone h2 { color: var(--red, #f85149); }
.btn-danger { background: var(--red, #f85149); color: #fff; border: none; }
.btn-danger:hover { background: #da3633; }

/* Start/finish save bar */
.sf-bar { display: flex; align-items: center; gap: 0.5rem; padding: 0.5rem; background: var(--bg-card); border-radius: var(--radius-md); }

/* Sector markers */
.sector-controls { display: flex; align-items: center; gap: 0.5rem; }

/* Reorder buttons */
.col-order { width: 60px; text-align: center; }
.btn-icon { background: none; border: 1px solid var(--border); padding: 0.15rem 0.3rem; border-radius: var(--radius-sm); cursor: pointer; color: var(--text-secondary); }
.btn-icon:hover { color: var(--accent); border-color: var(--accent); }
.btn-icon[disabled] { opacity: 0.3; cursor: not-allowed; }

/* Heatmap */
.heatmap-wrap { overflow-x: auto; }

/* Records held */
.records-held-list { display: flex; flex-direction: column; gap: 0.3rem; }
.record-held-item { padding: 0.4rem 0; border-bottom: 1px solid var(--border); }
```

**Step 3: Commit**

```bash
git add telemetry_tool/web/static/css/main.css
git commit -m "style: CSS for delete zones, reorder buttons, heatmap, record list"
```

---

## Task Dependency Summary

```
Task 1: Schema + Migration (predefined tables, karts, track_sectors)
  └─ Task 2: Track S/F editing
  └─ Task 3: Track sectors
  └─ Task 4: Track deletion
  └─ Task 5: Kart CRUD backend
      └─ Task 6: Kart templates + nav
      └─ Task 7: Session-kart linking
  └─ Task 8: Driver deletion
  └─ Task 9: Consistency fix
  └─ Task 10: Progression chart fix
  └─ Task 11: Best-ever redesign
  └─ Task 12: Track selection + predefined
  └─ Task 13: Weekend reordering
  └─ Task 14: Weekend insights
Task 15: Integration test + CSS (depends on all above)
```

Tasks 2-14 all depend on Task 1 (schema). Within each area, tasks are sequential. Across areas, tasks are independent (Tracks, Karts, Drivers, Weekends can be done in any order after Task 1).
