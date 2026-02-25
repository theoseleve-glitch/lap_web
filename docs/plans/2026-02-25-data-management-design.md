# Data Management Redesign — Design Document

> **Date:** 2026-02-25
> **Status:** Approved
> **Scope:** Tracks, Karts (new), Drivers, Weekends

## Goal

Enhance the four data management sections with deletion, editing, predefined reference data, a new Kart entity, bug fixes, and richer insights.

## Architecture: Feature-by-Feature Delivery

Deliver one complete area at a time in dependency order:

1. **Tracks** — predefined reference table, S/F editing, sectors, deletion
2. **Karts** — new schema, predefined import, CRUD, session linking
3. **Drivers** — deletion, best-ever redesign, consistency fix, progression fix, profile edit
4. **Weekends** — session reorder UI, enhanced insights

---

## Section 1: Tracks

### 1A. Predefined Track Reference Table

New `predefined_tracks` table imported from `predefined_track_list.csv` (~199 rows):

| Column | Type | Notes |
|--------|------|-------|
| predefined_track_id | INTEGER PK | AUTOINCREMENT |
| country | TEXT | |
| track_name | TEXT | |
| city | TEXT | |
| region | TEXT | |
| layout_name | TEXT | |
| layout_length_m | REAL | nullable |
| direction | TEXT | |
| rental_available | INTEGER | boolean |
| owner_available | INTEGER | boolean |
| outdoor | INTEGER | boolean |
| data_quality | TEXT | |
| source_url | TEXT | |

- Imported during `ensure_schema()` migration (idempotent — skip if populated).
- Existing `tracks` table gains: `predefined_track_id INTEGER REFERENCES predefined_tracks` (nullable).
- Track detail page gets "Link to predefined track" searchable dropdown.
- Track creation from predefined list pre-fills name and length.

### 1B. Start/Finish Editing (Map-Based)

- Existing orange Leaflet marker becomes **draggable**.
- On drag end: "Save position" button with new lat/lon.
- `POST /tracks/<track_id>/start_finish` updates `start_lat`, `start_lon`.
- New columns `original_start_lat`, `original_start_lon` store auto-detected values (populated on first manual edit).
- "Reset to auto-detected" button restores originals.

### 1C. Track-Level Sectors

New `track_sectors` table:

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | AUTOINCREMENT |
| track_id | TEXT FK | → tracks |
| sector_index | INTEGER | auto-reindexed |
| latitude | REAL | from map click |
| longitude | REAL | from map click |
| distance_m | REAL | computed from GPS trace |
| label | TEXT | auto: "S1", "S2", ... |
| created_at | TEXT | DEFAULT now() |

- UNIQUE(track_id, sector_index).
- "Add Sector" mode: click map to place marker, confirm to save.
- Numbered pins (S1, S2...), click to delete with confirmation.
- Auto-reindex on add/delete.
- Used as default sector boundaries when analyzing sessions at this track.

### 1D. Track Deletion

- "Delete Track" button (red) on track detail page.
- Type-to-confirm modal: user types track name to confirm.
- CASCADE: track → sessions → laps → scores → all dependent data.
- Route: `POST /tracks/<track_id>/delete`.

---

## Section 2: Karts (New)

### 2A. Predefined Kart Reference Table

New `predefined_karts` table from `predefined_kart_list.csv` (~102 rows):

| Column | Type | Notes |
|--------|------|-------|
| predefined_kart_id | INTEGER PK | AUTOINCREMENT |
| segment | TEXT | "RENTAL" / "OWNER" |
| manufacturer | TEXT | |
| model | TEXT | |
| model_year_start | INTEGER | |
| use_or_championship | TEXT | |
| engine | TEXT | |
| power_hp | REAL | |
| engine_type | TEXT | "2T" / "4T" |
| kart_weight_kg | REAL | no driver |
| top_speed_kmh | REAL | |
| zero_to_100_s | REAL | |
| power_to_weight | REAL | |
| braking_g_est | REAL | |
| lateral_g_est | REAL | |
| weight_source | TEXT | |

Imported during `ensure_schema()` migration.

### 2B. User Karts Table

New `karts` table:

| Column | Type | Notes |
|--------|------|-------|
| kart_id | INTEGER PK | AUTOINCREMENT |
| predefined_kart_id | INTEGER FK | nullable (NULL if custom) |
| kart_name | TEXT NOT NULL | display name |
| manufacturer | TEXT | |
| model | TEXT | |
| engine | TEXT | |
| power_hp | REAL | |
| kart_weight_kg | REAL | |
| notes | TEXT | user free text |
| created_at | TEXT | DEFAULT now() |

- Predefined selection auto-fills specs.
- Custom entry: user fills name + optional specs.

### 2C. Session-Kart Link

- `sessions` table gains: `kart_id INTEGER REFERENCES karts(kart_id)` (nullable).
- Session detail + analyze form get "Kart" dropdown.
- Dropdown: existing user karts + "Add new kart..." option (inline form/modal).

### 2D. Kart Blueprint

New `web/routes/karts.py`:

| Route | Method | Description |
|-------|--------|-------------|
| /karts/ | GET | Card grid list |
| /karts/<id> | GET | Detail: specs, sessions, performance |
| /karts/new | GET/POST | Form with predefined search + custom |
| /karts/<id>/edit | GET/POST | Edit name, notes, specs |
| /karts/<id>/delete | POST | Unlink sessions, delete kart |

### 2E. Navigation

New "Karts" sidebar entry under Data section.

---

## Section 3: Drivers

### 3A. Driver Deletion

- "Delete Driver" button on profile page (red).
- Type-to-confirm modal (driver name).
- CASCADE: driver → sessions → laps → scores → progression → style → profile.
- Route: `POST /drivers/<driver_id>/delete`.

### 3B. Profile Editing

- Existing inline AJAX fields unchanged.
- New: kart usage display (read-only, derived from sessions → karts join).
- `preferred_tracks` becomes multi-select dropdown (GPS tracks + predefined tracks).

### 3C. Best Ever Redesign

**Peak Performance (relative %):**
- Per track: `(driver_best / track_record) x 100`.
- Best = lowest %. Display: "101.5% at Track A (66.0s vs 65.0s record)".
- Tracks without records excluded.
- Fallback: absolute best time if no records exist.

**Track Records Held:**
- Query `track_records` where `record_holder` matches driver name.
- List: "Track A — 65.0s (Senior class)".
- Hidden if driver holds no records.

### 3D. Consistency Fix (1500% Bug)

- Audit `scoring.py` CV computation.
- Audit `driver_progression` insertion.
- Ensure stored value and display format are consistent.
- Sanity clamp: 0-100% display range.

### 3E. Progression Chart Fix

- Debug `GET /drivers/<id>/api/progression` response.
- Check `progression.js` loading and `window.Progression.init()` call.
- Check canvas element IDs match.
- Fix root cause.

### 3F. Track Selection with "New Track"

- Analyze form track dropdown gets "New track..." option.
- Expands sub-form: searchable predefined tracks list + custom name.
- Selecting predefined creates `tracks` entry linked to reference.

---

## Section 4: Weekends

### 4A. Session Reordering

**Arrow buttons:**
- Up/down arrows per session row (new "Order" column).
- `POST /weekends/<id>/reorder` with `{session_id, direction}`.
- Swaps `session_order` between adjacent sessions.

**Drag-and-drop:**
- HTML5 drag API (vanilla JS, no library).
- `POST /weekends/<id>/reorder_all` with ordered session_ids.
- Full re-index on drop.

### 4B. Enhanced Insights

**Session Consistency Breakdown:**
- Table: session date, driver, laps, mean time, CV%, best, worst.
- CV% color-coded (green < 3%, yellow 3-6%, red > 6%).

**Cross-Session Heatmap:**
- Canvas grid: X = lap number, Y = session.
- Color = lap time relative to session best.
- Hover tooltips, invalid laps in grey/hatched.

**Improvement Summary:**
- Average lap time per session (line chart).
- Improvement % first→last session.
- Best/worst session highlights.
- Per-sector bests if track sectors exist.

### 4C. Data Source

All computed from existing tables (`laps`, `score_details`, `track_sectors`).
New `compute_weekend_insights()` in `cross_session.py`.

---

## Non-Goals

- No multi-user / auth system.
- No automated predefined list updates (manual CSV re-import if needed).
- No kart performance normalization across different kart types (future).
