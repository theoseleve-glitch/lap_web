# Audit Checkpoint 1 — Design

**Date**: 2026-03-01
**Scope**: Bullets 1–5 of the audit truth implementation order
**Verification**: `docs/audit-truth-dashboard.html` probes must pass after implementation

## Problem

The truth dashboard reveals six conflict points. Bullets 1–5 address the foundational API contract and session-identity issues that block all downstream work:

1. API endpoints sometimes return HTML to JSON consumers (Flask default error pages, legacy guard)
2. Missing computed data causes 500 errors instead of structured unavailability responses
3. Session title shows raw upload path instead of a display name
4. Session date shows upload timestamp instead of telemetry-derived date
5. Driver and track resolution produce stale/incorrect values

## Approach: Middleware-First (Approach A)

Single `after_request` guard catches HTML responses on `/api/*`. Extend existing `available:false` pattern to all computed-data endpoints. Schema changes via Alembic 017.

### Why not per-route decoration (Approach B)?
More boilerplate, higher risk of missing an endpoint.

### Why not blueprint-level error override (Approach C)?
Flask doesn't support blueprint-scoped error handlers for HTTP status codes reliably.

## Section 1: API JSON Contract Guard

### Changes
- **`app.py`**: `after_request` hook inspects responses on `/api/*` paths. If `Content-Type` is `text/html` or body starts with `<!DOCTYPE`/`<html`, replace with `api_error("API_HTML_RESPONSE", 500)`.
- **Exception**: Report-download endpoint returns `text/html` with `Content-Disposition: attachment` — exempt from guard.
- **`middleware/legacy_guard.py`**: Replace bare `jsonify()` with `api_error(NOT_FOUND, 404)` to include `request_id`.

### Acceptance
- Frontend never sees "Unexpected token <" or content-type mismatch from `/api/*` routes.

## Section 2: Error Hardening — Structured Unavailability

### Changes
- **`routes/data_v2.py`**: Extend `available: false + reason_code` pattern to all computed-data endpoints that currently return 404:
  - `theoretical`, `reference_line`, `fingerprint`, `delta`, `stint-analysis`, `lap-distribution`, `compare` overlay, `lap-progress`
- **Semantics**:
  - 200 + `available: false` + `reason_code` → optional data not computed
  - 404 → session entity does not exist
  - 403 → entitlement lock
- **`request_id`** already present in all `api_error()` and `api_response()` calls via `_build_meta()`.

### Pattern
```python
# Before:
if not data:
    return api_error(ErrorCode.NOT_FOUND, "No data", status=404)

# After:
if not data:
    return api_response({"available": False, "reason_code": "no_theoretical_data",
                         "message": "Theoretical lap not computed for this session"})
```

### Acceptance
- No uncaught exceptions during navigation; missing analysis explained via `reason_code`.

## Section 3: Session Identity Model

### Schema (Alembic 017 + SQLite schema.py)
```sql
ALTER TABLE sessions ADD COLUMN display_name TEXT;
ALTER TABLE sessions ADD COLUMN source_filename TEXT;
ALTER TABLE sessions ADD COLUMN source_path TEXT;
```

- `display_name`: User-editable, default = filename stem
- `source_filename`: Original upload filename (traceability)
- `source_path`: Internal server path (never exposed in API)

### Upload (`sessions_v2.py`)
- Set `source_filename` = original filename from form
- Set `source_path` = server temp path
- Set `display_name` = filename stem (without extension)

### API (`data_v2.py`)
- Session detail returns `display_name` (fallback to `csv_filename` stem), `source_filename`
- Never returns `source_path`
- PATCH allows updating `display_name`

### Acceptance
- Session header title uses `display_name`, not raw path.

## Section 4: Session Date Correctness

### Changes
- **Upload**: Extract earliest timestamp from telemetry data after pipeline runs. Store as `session_date`. `created_at` remains the upload timestamp.
- **API**: Return both `session_date` (telemetry-derived) and `created_at` (upload time).
- **Sorting**: Frontend sorts by `session_date`.

### Acceptance
- `session_date` reflects actual driving time, not upload time.

## Section 5: Driver & Track Resolution

### Driver Precedence
1. Upload form selection/input (`driver_id` parameter)
2. CSV metadata (if parser extracts driver info)
3. Create/use "Unknown" driver (workspace-scoped)

### Track Resolution
- Use pipeline's `track_detection` result to set `track_id`
- If detection fails: `track_id = NULL` (not a stale placeholder)
- API joins `tracks.name` for display; NULL → `track_name: null`
- PATCH allows manual `track_id` override

### Acceptance
- Golden fixture session matches local title/driver/track/date every time.

## Verification

After implementation, run `docs/audit-truth-dashboard.html` → "Run Probes":
- [ ] No HTML responses to `/api/*`
- [ ] No 500s for optional data endpoints
- [ ] Session header identity probes PASS (title/driver/track/date)
