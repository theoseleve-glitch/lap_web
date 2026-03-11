# Generic Delete System — Design Spec

**Date:** 2026-03-11
**Status:** Approved
**Scope:** Unified delete architecture for all 7 entity types (sessions, drivers, tracks, karts, weekends, race strategies, dev plans)

## Problem

The app has 7 entity types with delete functionality. Each has its own implementation with different behaviors:
- Inconsistent cascade: sessions soft-delete, everything else hard-deletes
- Race strategy delete orphans 7 child tables
- Missing delete buttons on session detail and weekend detail pages
- Kart delete blocks instead of unlinking sessions
- No impact preview before destructive cascades
- Cache invalidation gaps cause stale data across pages
- No audit logging on most deletes

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Delete semantics | Hard-delete everywhere | Daily pg_dump backups are the safety net; soft-delete adds complexity with filtered queries, purge jobs, restore UI. Data recoverable from CSV re-upload. |
| Cascade behavior | Cascade with warning | Users expect "Delete Driver" to remove everything. Confirmation panel shows exact impact. Exception: karts unlink sessions, weekends unlink junction rows. |
| Confirmation UI | Inline panel (detail pages) + compact two-click (list pages) | Inline panel is the dominant existing pattern (4/7 entities). Keeps context visible. Compact variant for space-constrained list rows. |
| Cache invalidation | Optimistic removal + broad invalidation | Instant UI feedback via optimistic cache removal. Broad invalidation of related query keys prevents stale data on navigation. |
| Delete button placement | Both detail pages and list pages | Detail pages get full inline panel with impact preview. List pages get compact two-click. |

## Architecture

### Backend: Generic Cascade Delete

#### New file: `telemetry_tool/web/repos/delete_cascade.py`

A single `delete_entity_cascade(conn, entity_type, entity_id)` function driven by a declarative config:

```python
CASCADE_CONFIG = {
    "session": {
        "parent_table": "sessions",
        "parent_pk": "session_id",
        "children": [
            # Deepest children first (no FK constraints between these, but order for clarity)
            "score_details",
            "corner_metrics",
            "condition_phases",
            "laps",
            "gps_traces",
            "theoretical_data",
            "reference_lines",
            "session_sectors",
            "session_tags",
            "session_weather",
            "session_weather_laps",
            "data_health",
            "driver_progression",
            "driving_style_features",
            "condition_markers",
            "vehicle_setups",
            "what_if_scenarios",
            "session_annotations",
            "stint_analysis",
            "user_corners",
            "plan_drill_sessions",
            "weekend_sessions",
        ],
    },
    "driver": {
        "parent_table": "drivers",
        "parent_pk": "driver_id",
        "children": [
            # Sessions and their children are handled by recursively calling
            # delete_entity_cascade("session", ...) for each session
            {"entity": "session", "fk": "driver_id"},  # recursive cascade
            "development_plans",
            "driver_badges",
            "driver_profiles",
        ],
    },
    "track": {
        "parent_table": "tracks",
        "parent_pk": "track_id",
        "pre_cascade": [
            # Null out circular FKs before session cascade (tracks.dry_ref_session_id,
            # tracks.wet_ref_session_id reference sessions — must be cleared first)
            {"sql": "UPDATE tracks SET dry_ref_session_id = NULL, wet_ref_session_id = NULL WHERE track_id = :id"},
        ],
        "children": [
            {"entity": "session", "fk": "track_id"},  # recursive cascade
            "track_sectors",
            "track_records",
            "track_key_corners",
            "corner_best_practices",
        ],
    },
    "kart": {
        "parent_table": "karts",
        "parent_pk": "kart_id",
        "children": [
            # UNLINK, not delete — set kart_id = NULL on sessions
            {"table": "sessions", "fk": "kart_id", "action": "unlink"},
        ],
    },
    "weekend": {
        "parent_table": "weekends",
        "parent_pk": "weekend_id",
        "children": [
            "weekend_sessions",  # junction table only, sessions untouched
        ],
    },
    "race_strategy": {
        "parent_table": "race_configs",
        "parent_pk": "race_id",
        "children": [
            "race_rival_events",
            "race_rivals",
            "race_stints",
            "race_pit_stops",
            "race_drivers",
            "race_windows",
            "race_sleep_windows",
            "race_messages",
            "race_neutralizations",
        ],
    },
    "dev_plan": {
        "parent_table": "development_plans",
        "parent_pk": "id",
        "children": [
            "plan_drill_sessions",
            # Unlink driver_badges that reference this plan (nullable FK)
            {"table": "driver_badges", "fk": "plan_id", "action": "unlink"},
        ],
    },
}
```

#### Child entry types

Each entry in `children` can be:

1. **String** — table name. Assumes FK column = parent's `parent_pk`.
   `"laps"` → `DELETE FROM laps WHERE session_id = :id`

2. **Dict with `entity`** — recursive cascade. Finds all child entity IDs, then calls `delete_entity_cascade` for each.
   `{"entity": "session", "fk": "driver_id"}` → finds all session IDs for driver, cascades each

3. **Dict with `action: "unlink"`** — sets FK to NULL instead of deleting.
   `{"table": "sessions", "fk": "kart_id", "action": "unlink"}` → `UPDATE sessions SET kart_id = NULL WHERE kart_id = :id`

#### Pre-cascade hooks

An optional `pre_cascade` list on the config runs raw SQL statements before child deletion. Used to break circular FK references:

```python
"pre_cascade": [
    {"sql": "UPDATE tracks SET dry_ref_session_id = NULL, wet_ref_session_id = NULL WHERE track_id = :id"},
]
```

Each entry is a dict with `"sql"` — the SQL string must use `:id` as the placeholder for the parent entity ID.

#### Function signature

```python
def delete_entity_cascade(
    conn,
    entity_type: str,
    entity_id: int | str,
) -> dict:
    """Delete an entity and all its children per CASCADE_CONFIG.

    Returns:
        {"deleted": True, "impact": {"sessions": 12, "laps": 47, ...}}
    """
```

#### Impact preview function

```python
def get_delete_impact(
    conn,
    entity_type: str,
    entity_id: int | str,
) -> dict:
    """Count affected rows without deleting. Same traversal as cascade but SELECT COUNT(*) instead of DELETE.

    Returns:
        {"impact": {"sessions": 12, "laps": 47, ...}}
    """
```

#### Impact preview endpoints

Each entity gets a preview endpoint. Added to `api_v1_entities.py`:

```
GET /api/v1/drivers/<id>/delete-impact
GET /api/v1/tracks/<id>/delete-impact
GET /api/v1/karts/<id>/delete-impact
GET /api/v1/weekends/<id>/delete-impact
GET /api/v1/dev-plans/<id>/delete-impact
```

Added to `data_v2.py`:
```
GET /api/v1/sessions/<id>/delete-impact
```

Added to `race_strategy_v2.py`:
```
GET /api/v1/race-strategy/<id>/delete-impact
```

Response format: `{"ok": true, "data": {"impact": {"sessions": 12, "laps": 47}}}`

#### Route handler changes

All existing DELETE handlers are simplified to:

```python
@bp.route("/drivers/<int:driver_id>", methods=["DELETE"])
def delete_driver(driver_id):
    conn = _get_conn()
    if not _verify_driver(conn, driver_id):
        return api_error(ErrorCode.NOT_FOUND, "Driver not found", status=404)
    result = delete_entity_cascade(conn, "driver", driver_id)
    conn.commit()
    return api_response(result)
```

#### Race strategy route compatibility

The current race strategy delete is `POST /<id>/delete` (form-based, used by Jinja2 templates). The React frontend needs a REST `DELETE /api/v1/race-strategy/<id>` endpoint. Both must coexist:

- **Keep** existing `POST /<id>/delete` route for Jinja2 templates, but update its handler to call `delete_entity_cascade()`
- **Add** new `DELETE /api/v1/race-strategy/<id>` JSON endpoint for the React frontend, also calling `delete_entity_cascade()`

Both routes call the same cascade function — no duplication of delete logic.

#### Session restore endpoint removal

The current `data_v2.py` has a `POST /sessions/<id>/restore` endpoint that restores soft-deleted sessions. Since we are switching to hard-delete, this endpoint becomes non-functional. It will be **removed** along with the `restore_session` import and `soft_delete_session` function.

#### Removed code

- `repos/driver_repo.py` → `delete_driver_cascade()` — replaced by generic
- `repos/track_repo.py` → `delete_track_cascade()` — replaced by generic
- `data_v2.py` → `soft_delete_session()`, `restore_session()`, and `POST /sessions/<id>/restore` endpoint — replaced by hard-delete cascade
- `race_strategy_v2.py` → orphaning single-table delete — replaced by full cascade

### Frontend: `useEntityDelete` Hook

#### New file: `lap-website/src/hooks/useEntityDelete.ts`

```typescript
interface EntityDeleteConfig {
  entity: string;                    // 'driver' | 'track' | 'kart' | etc.
  id: string | number;
  endpoint: string;                  // '/drivers/42'
  invalidate: string[][];            // [['drivers'], ['sessions'], ['dashboard']]
  redirectTo?: string;               // '/app/drivers' — detail pages only
  onSuccess?: () => void;            // extra callback
}

interface EntityDeleteResult {
  // State
  showConfirm: boolean;
  isPending: boolean;
  error: string | null;
  impact: Record<string, number> | null;
  isLoadingImpact: boolean;

  // Actions
  requestDelete: () => void;
  confirmDelete: () => void;
  cancelDelete: () => void;
}

function useEntityDelete(config: EntityDeleteConfig): EntityDeleteResult;
```

#### Internal flow

1. `requestDelete()`:
   - Sets `showConfirm = true`
   - Fires `GET /{endpoint}/delete-impact` to fetch cascade counts
   - Stores impact in state

2. `confirmDelete()`:
   - Optimistically removes entity from relevant query caches
   - Fires `DELETE /{endpoint}`
   - On success: invalidates all keys in `config.invalidate`, redirects if `redirectTo` set
   - On error: rolls back optimistic removal, sets `error` state

3. `cancelDelete()`:
   - Sets `showConfirm = false`, clears impact and error

### Frontend: `<DeleteConfirmPanel>` Component

#### New file: `lap-website/src/components/app/DeleteConfirmPanel.tsx`

```typescript
interface DeleteConfirmPanelProps {
  // From useEntityDelete
  showConfirm: boolean;
  isPending: boolean;
  error: string | null;
  impact: Record<string, number> | null;
  isLoadingImpact: boolean;
  confirmDelete: () => void;
  cancelDelete: () => void;

  // Entity context
  entityName: string;          // "Spa-Francorchamps"
  entityType: string;          // "track"

  // Variant
  variant?: 'full' | 'compact';  // default: 'full'
}
```

#### Full variant (detail pages)

Red-bordered panel matching existing design system (`bg-safety-red/5 border border-safety-red/30 rounded-lg p-4`):

- Warning: `Are you sure you want to delete **{entityName}**?`
- Impact summary (non-zero counts only):
  - `This will permanently delete: 12 sessions, 47 laps, 3 scores`
  - For unlink entities: `This will unlink 5 sessions (they will not be deleted)`
  - Loading skeleton while fetching
- Error message (if delete failed)
- Buttons: `Confirm Delete` (red, "Deleting..." when pending) | `Cancel`

#### Compact variant (list pages)

Inline row: `Delete {entityName}?` + `Confirm` (red) | `Cancel` buttons. No impact preview.

#### Impact label mapping

```typescript
const IMPACT_LABELS: Record<string, string> = {
  sessions: 'sessions',
  laps: 'laps',
  score_details: 'scores',
  gps_traces: 'GPS traces',
  corner_metrics: 'corner analyses',
  development_plans: 'development plans',
  race_stints: 'stints',
  race_pit_stops: 'pit stops',
  race_drivers: 'driver assignments',
  race_windows: 'windows',
  race_sleep_windows: 'sleep windows',
  race_rivals: 'rivals',
  race_rival_events: 'rival events',
  track_sectors: 'sectors',
  track_records: 'records',
  weekend_sessions: 'weekend links',
  track_key_corners: 'key corners',
  corner_best_practices: 'corner best practices',
  driver_badges: 'badges',
  driver_profiles: 'driver profiles',
  user_corners: 'custom corners',
  plan_drill_sessions: 'drill sessions',
  session_weather_laps: 'weather lap data',
  race_messages: 'race messages',
  race_neutralizations: 'neutralizations',
  session_annotations: 'annotations',
  driving_style_features: 'driving style data',
  driver_progression: 'progression data',
  condition_phases: 'condition phases',
  condition_markers: 'condition markers',
  vehicle_setups: 'vehicle setups',
  what_if_scenarios: 'what-if scenarios',
  theoretical_data: 'theoretical data',
  reference_lines: 'reference lines',
  data_health: 'data health checks',
  stint_analysis: 'stint analyses',
};
```

## Entity Wiring

### Cache Invalidation Map

| Entity | DELETE Endpoint | Invalidate Keys | Redirect |
|--------|----------------|-----------------|----------|
| Session | `DELETE /sessions/:id` | `sessions`, `dashboard`, `drivers`, `tracks` | → `/app/sessions` or stay on list |
| Driver | `DELETE /drivers/:id` | `drivers`, `sessions`, `dashboard` | → `/app/drivers` |
| Track | `DELETE /tracks/:id` | `tracks`, `sessions`, `dashboard` | → `/app/tracks` |
| Kart | `DELETE /karts/:id` | `karts`, `sessions` | → `/app/karts` |
| Weekend | `DELETE /weekends/:id` | `weekends` | → `/app/weekends` |
| Race Strategy | `DELETE /race-strategy/:id` | `race-strategy` | → `/app/race-strategy` |
| Dev Plan | `DELETE /dev-plans/:id` | `dev-plans` | → `/app/development` |

### Pages Modified

| Page | Change |
|------|--------|
| `sessions/[id]/page.tsx` | **Add** delete button + `DeleteConfirmPanel` (currently missing) |
| `sessions/page.tsx` | Refactor bulk delete to use `useEntityDelete` |
| `drivers/[id]/page.tsx` | Replace custom 2-step with generic hook + panel |
| `drivers/page.tsx` | Replace custom inline with compact variant |
| `tracks/[id]/page.tsx` | Replace custom panel with generic hook + panel |
| `karts/[id]/page.tsx` | Replace custom modal-style with generic hook + panel |
| `weekends/[id]/page.tsx` | **Add** delete button + `DeleteConfirmPanel` (currently missing) |
| `race-strategy/[id]/page.tsx` | Replace `window.confirm` with generic hook + panel |
| `development/[id]/page.tsx` | Replace custom danger zone with generic hook + panel |

### Backend Files Modified

| File | Change |
|------|--------|
| New: `repos/delete_cascade.py` | Generic cascade function + config + impact preview |
| `api_v1_entities.py` | All DELETE handlers → `delete_entity_cascade()`. Add 5 impact preview endpoints. |
| `data_v2.py` | Session DELETE → remove soft-delete, use cascade. Add impact preview endpoint. |
| `race_strategy_v2.py` | DELETE → `delete_entity_cascade()` (fixes orphan bug). Add impact preview endpoint. |
| `repos/driver_repo.py` | Remove `delete_driver_cascade()` |
| `repos/track_repo.py` | Remove `delete_track_cascade()` |

## Testing

### Backend tests (`telemetry_tool/tests/test_delete_cascade.py`)

- Each entity type: verify all child tables are cleaned up after cascade
- Recursive cascade: driver delete → sessions → session children all gone
- Unlink behavior: kart delete → sessions still exist with `kart_id = NULL`
- Weekend: junction rows deleted, sessions untouched
- Race strategy: all 9 child tables cleaned up (regression test for orphan bug)
- Impact preview: counts match actual deletions
- 404 on non-existent entity

### Frontend tests

- `useEntityDelete` hook: state transitions (idle → confirming → pending → success/error)
- `DeleteConfirmPanel`: renders impact summary, handles loading/error states
- Integration: verify cache invalidation fires correct query keys

## Out of Scope

- RBAC on delete endpoints (separate concern, tracked elsewhere)
- Audit logging (separate concern)
- Batch delete redesign (session list bulk delete works, keep as-is but wire through same cascade)
- Undo/restore functionality (decided against soft-delete)
