# Tracks Section Fix — Design Spec

**Date:** 2026-03-10
**Scope:** Fix track detection, replace legacy routes with REST API v2, add RLS, rebuild frontend + evolution page

## Problem Statement

1. **Track detection misassignment** — All sessions assigned to "Ouest Karting" regardless of actual location due to relaxed geometric matching thresholds
2. **API mismatch** — Frontend calls PATCH/DELETE but backend only has POST-based HTML-form routes → 405 errors
3. **No multi-tenant isolation** — tracks/records/sectors tables lack workspace_id and RLS policies
4. **Delete logic mismatch** — Frontend blocks delete when sessions exist, but backend allows cascade
5. **Track evolution page** — Stub, not implemented

## Design

### Section 1: Track Detection Fix

**File:** `telemetry_tool/track_detection.py`

Threshold changes:

| Parameter | Current | New | Reason |
|-----------|---------|-----|--------|
| `min_bbox_iou` | 0.50 | 0.75 | Kart tracks are small — 50% overlap catches unrelated circuits |
| `sf_saturation` | 500m | 200m | Kart start/finish lines are close but not 500m close |
| `composite threshold` | 0.60 | 0.70 | Raise minimum confidence for a "match" |

**Metadata-first matching:** Before geometric matching, check if session metadata (filename, user-provided track name) matches an existing track name. If exact or fuzzy match (>85% similarity), prefer that over geometric scoring.

**Re-detection migration** (`scripts/redetect_tracks.py`):
- Load all sessions with GPS data from DB
- Re-run `register_or_match_track()` with new thresholds
- Update `sessions.track_id` where it changed
- Log summary: "X sessions reassigned, Y new tracks created"
- Idempotent — safe to run multiple times

### Section 2: REST API v2 for Tracks

**New file:** `telemetry_tool/web/routes/tracks_v2.py`
**Blueprint prefix:** `/api/v1/tracks`
**Replaces:** `tracks.py` (deleted entirely)

| Method | Path | Purpose | RBAC |
|--------|------|---------|------|
| GET | `/api/v1/tracks` | List tracks (session count, best time, lap count) | Required |
| GET | `/api/v1/tracks/:id` | Track detail (metadata + records + sectors) | Required |
| POST | `/api/v1/tracks` | Create track manually | admin+ |
| PATCH | `/api/v1/tracks/:id` | Update name, joker, start/finish | member+ |
| DELETE | `/api/v1/tracks/:id` | Cascade delete (track + sessions + records + sectors) | admin+ |
| GET | `/api/v1/tracks/:id/sessions` | List sessions at this track | Required |
| GET | `/api/v1/tracks/:id/evolution` | Evolution data (trends, sectors, conditions, corners) | Required |
| POST | `/api/v1/tracks/:id/sectors` | Add sector split | member+ |
| DELETE | `/api/v1/tracks/:id/sectors/:sid` | Remove sector | member+ |
| POST | `/api/v1/tracks/:id/records` | Add/update track record | member+ |
| DELETE | `/api/v1/tracks/:id/records/:rid` | Remove track record | member+ |

Response format: Standard envelope `{ok, data, error, meta}`.
Reuses existing `track_repo.py` functions.

### Section 3: Workspace/RLS for Tracks

**New Alembic migration (017).**

Schema changes:

| Table | Change |
|-------|--------|
| `tracks` | Add `workspace_id UUID NOT NULL` + FK, RLS policy |
| `track_records` | Add `workspace_id UUID NOT NULL` + FK, RLS policy |
| `track_sectors` | Add `workspace_id UUID NOT NULL` + FK, RLS policy |

Migration steps:
1. Add `workspace_id` column as nullable
2. Backfill from `sessions.workspace_id` (join on `track_id`); orphan tracks get default workspace
3. Set NOT NULL constraint
4. Create RLS policies: `WHERE workspace_id = current_setting('app.workspace_id')::uuid`
5. Add workspace-scoped unique constraint on `(workspace_id, track_name)`

`track_repo.py`: All queries auto-filtered by RLS. Write operations must include `workspace_id` from `g.workspace_id`.

### Section 4: Frontend Fixes

**Tracks list page** (`app/tracks/page.tsx`):
- Align API calls to new v2 endpoints
- Delete button calls DELETE directly — cascade is the behavior
- Remove "unlink sessions first" warning

**Track detail page** (`app/tracks/[id]/page.tsx`):
- PATCH for rename/joker update
- Delete with confirmation: "This will permanently delete the track and all X sessions"
- Link to evolution page

**Track evolution page** (`app/tracks/[id]/evolution/page.tsx`) — new build:

| Panel | Data | Visualization |
|-------|------|---------------|
| Lap Time Trend | Best lap per session over time | Line chart with rolling average |
| Sector Breakdown | Sector times per session | Stacked bar, color-coded |
| Conditions | Wet/dry flag from session metadata | Badge/tag on trend data points |
| Best/Worst Corners | Corner metrics aggregated across sessions | Horizontal bar, sorted worst→best |

Component reuse: `TrackMap`, vanilla JS chart modules + `useVanillaChart` hook, Zustand hover sync store.

## Delete Behavior

Cascade: deleting a track deletes all associated sessions, records, and sectors. Confirmation dialog warns the user with session count.

## Out of Scope

- Track merge/split UI
- Manual track assignment per session
- Geographic disambiguation via external geocoding API
