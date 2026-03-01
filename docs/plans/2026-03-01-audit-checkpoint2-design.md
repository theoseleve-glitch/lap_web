# Audit Checkpoint 2 — Design

**Date**: 2026-03-01
**Scope**: Bullets 6–10 of the audit truth implementation order
**Verification**: `docs/audit-truth-dashboard.html` probes must pass after implementation

## Problem

The truth dashboard and Report 1/2 reveal that entity management pages (Drivers, Tracks, Karts, Weekends, Leaderboard, Dev Plans) show "0" counts, placeholder content, or errors because:

1. All 6 entity route files (`drivers.py`, `tracks.py`, `karts.py`, `weekends.py`, `leaderboard.py`, `dev_plans.py`) serve Jinja2 HTML templates at `/drivers`, `/tracks`, etc. — not JSON at `/api/v1/`.
2. The Next.js frontend calls `/api/v1/drivers`, `/api/v1/tracks`, etc. — these routes don't exist.
3. Session PATCH endpoint is missing validation and several fields (`kart_id`, `session_date`, `driver_id`).
4. Sessions table has no `kart_id` column — karts can't be linked to sessions.
5. Upload flow doesn't accept `kart_id`.

## Section 1: Entity API Blueprint

### Approach

Single new blueprint `api_v1_entities.py` registered at `/api/v1/` containing all 6 entity groups. Keeps entity CRUD separate from `data_v2.py` (session-scoped data) while avoiding 6 tiny files.

All responses use existing `api_response()`/`api_error()` envelope with `request_id`.

### Endpoints

#### Drivers
- `GET /api/v1/drivers` — List with session count, PB, mean score, `has_profile`, `total_laps`
- `GET /api/v1/drivers/:id` — Detail with profile data
- `PATCH /api/v1/drivers/:id` — Update name, notes

#### Tracks
- `GET /api/v1/tracks` — List with session count, best time, lap length
- `GET /api/v1/tracks/:id` — Detail with sessions
- `PATCH /api/v1/tracks/:id` — Update name, joker settings

#### Karts
- `GET /api/v1/karts` — List with session count, best time
- `POST /api/v1/karts` — Create (name required; optional: manufacturer, model, engine, power_hp, kart_weight_kg, notes, predefined_kart_id)
- `GET /api/v1/karts/:id` — Detail with sessions
- `PATCH /api/v1/karts/:id` — Update fields
- `DELETE /api/v1/karts/:id` — Delete (fails if sessions linked)
- `GET /api/v1/predefined-karts` — Read-only catalog

#### Weekends
- `GET /api/v1/weekends` — List with track name, session count, date range
- `POST /api/v1/weekends` — Create (name, track_id, start_date, end_date, notes)
- `GET /api/v1/weekends/:id` — Detail with session list
- `PATCH /api/v1/weekends/:id` — Update fields
- `DELETE /api/v1/weekends/:id` — Delete (cascades weekend_sessions)

#### Leaderboard
- `GET /api/v1/leaderboard?track_id=&driver_id=&limit=` — Aggregated best times, scores

#### Dev Plans
- `GET /api/v1/dev-plans` — List all plans
- `POST /api/v1/dev-plans` — Create from template
- `GET /api/v1/dev-plans/:id` — Detail with progress
- `PATCH /api/v1/dev-plans/:id` — Update progress
- `DELETE /api/v1/dev-plans/:id` — Delete
- `GET /api/v1/dev-plan-templates` — List available templates

### Field Name Mapping

Frontend expects different field names than DB columns. API layer maps:
- `kart_id` → `id`, `kart_name` → `name`, `kart_weight_kg` → `weight_kg`
- `weekend_id` → `id`
- `driver_id` → `id`, `driver_name` → `name`
- `track_id` → `id`, `track_name` → `name`

## Section 2: Session PATCH Hardening

### Expanded Fields

`_UPDATABLE_FIELDS` grows to include:
```python
_UPDATABLE_FIELDS = {
    "display_name", "session_date", "driver_id", "track_id",
    "session_type", "track_state", "kart_id", "notes"
}
```

### Validation

| Field | Rule |
|-------|------|
| `session_type` | Enum: `{practice, qualifying, race, test}` |
| `track_state` | Enum: `{dry, wet, damp, mixed}` |
| `driver_id` | Must exist in `drivers` table |
| `track_id` | Must exist in `tracks` table |
| `kart_id` | Must exist in `karts` table; `null` allowed (unlink) |
| `session_date` | ISO date format `YYYY-MM-DD` |
| `display_name` | Non-empty string, max 200 chars |
| `notes` | String, max 2000 chars |

### Response

Re-fetch with JOINs to return resolved `driver_name`, `track_name`, `kart_name` — prevents stale UI after edit.

## Section 3: Schema Migration (Alembic 024)

```sql
ALTER TABLE sessions ADD COLUMN kart_id INTEGER REFERENCES karts(kart_id);
```

- SQLite `schema.py` updated with `kart_id` column
- No backfill — existing sessions have `kart_id = NULL`
- Index on `kart_id` for efficient kart-session lookups

## Section 4: Upload Flow Kart Support

Add optional `kart_id` parameter to `POST /api/v1/sessions/upload`:
- If provided, validate FK exists in `karts` table
- Store on session record
- No default value (unlike `driver_name` which defaults to "Unknown")

## Section 5: Frontend Compatibility

The Next.js frontend pages already call the correct `/api/v1/` paths. Once the backend routes exist and return the expected field names:
- Drivers/Tracks/Karts lists populate with real counts
- Weekends shows clean empty state
- Leaderboard renders real data
- Dev Plans shows templates

No frontend code changes needed — only backend route creation and field name mapping.

## Verification

After implementation, run `docs/audit-truth-dashboard.html` → "Run Probes":
- [ ] Session metadata edits persist and reflect everywhere
- [ ] Entity list endpoints return non-empty data where expected
- [ ] No 404s for `/api/v1/drivers`, `/api/v1/tracks`, `/api/v1/karts`, `/api/v1/weekends`
- [ ] Kart field appears on session detail after PATCH
- [ ] DELETE with safety checks works (karts with sessions cannot be deleted)
