# Logger Download & Device Sync Design

**Date**: 2026-03-24
**Status**: Approved
**Branch**: feat/logger-download-sync

## Summary

Make the Lap Coach Logger desktop app (Windows, iRacing + ACC) available for download from the webapp. For World-Class users, sessions auto-upload and auto-analyze. Racer users can sync sessions but must trigger analysis manually. Demo users can use the logger locally only.

## Decisions

| Question | Decision |
|---|---|
| Installer hosting | VPS via Caddy static file server |
| Authentication | Device pairing code (6-char, entered in webapp) |
| Upload timing | Immediate after session finalize, retry queue fallback |
| Analysis trigger | Demo/Racer: manual ("Analyze" button); World-Class: auto-analyze on upload |

## 1. Download Distribution

### Installer Hosting

Caddy serves `/downloads/` from `/opt/lap-api/downloads/` on the VPS.

**Files:**
- `LapCoachLogger-Setup-{version}.exe` — Inno Setup installer (~57 MB)
- `latest.json` — version manifest for update checks

**`latest.json` schema:**
```json
{
  "version": "1.1.0",
  "filename": "LapCoachLogger-Setup-1.1.0.exe",
  "sha256": "abc123...",
  "size_bytes": 59878002,
  "released_at": "2026-03-24T00:00:00Z",
  "min_logger_version": "1.0.0",
  "changelog_url": "https://lap-coach.racing/product/logger#changelog"
}
```

**Caddy config addition:**
```
handle /downloads/* {
    root * /opt/lap-api/downloads
    file_server
}
```

### Webapp Download Page

New route: `(marketing)/product/logger/page.tsx`

Content:
- Hero: "Capture Every Lap. Automatically." with screenshot
- Feature list: iRacing + ACC support, local-first, auto-sync for paid plans
- System requirements: Windows 10/11, ~100 MB disk
- Download CTA button → `https://api.lap-coach.racing/downloads/LapCoachLogger-Setup-{version}.exe`
- For logged-in World-Class users: callout explaining auto-sync

### Update Check (Logger-Side)

On startup, logger fetches `GET {api_url}/downloads/latest.json`. If `version > current_version`, shows a non-blocking notification in the dashboard: "Lap Coach Logger {version} is available. [Download]".

No auto-update — just notification.

## 2. Device Pairing

### Flow

```
Logger                          API                         Webapp
  |                              |                            |
  |-- POST /devices/pair ------->|                            |
  |<-- { pairing_id, code } -----|                            |
  |                              |                            |
  | [shows code to driver]       |                            |
  |                              |                            |
  |-- GET /devices/pair/{id}/status (poll every 3s) --------->|
  |<-- { status: "pending" } ----|                            |
  |                              |                            |
  |                              |<-- POST /devices/confirm --|
  |                              |    { code, auth_token }    |
  |                              |-- { ok: true } ----------->|
  |                              |                            |
  |-- GET /devices/pair/{id}/status -->|                      |
  |<-- { status: "confirmed",         |                      |
  |      device_token: "..." } --------|                      |
  |                              |                            |
  | [stores token in config]     |                            |
```

### API Endpoints

**`POST /api/v1/devices/pair`** (no auth)
- Body: `{ "device_name": "DESKTOP-ABC123" }`
- Response: `{ "ok": true, "data": { "pairing_id": "uuid", "code": "K7X-9M2", "expires_at": "..." } }`
- Code format: 3 alphanumeric + dash + 3 alphanumeric (uppercase, no ambiguous chars like 0/O/I/1)
- Expires: 10 minutes

**`GET /api/v1/devices/pair/{pairing_id}/status`** (no auth)
- Response: `{ "ok": true, "data": { "status": "pending" | "confirmed" | "expired", "device_token": "..." } }`
- `device_token` only present when status is `confirmed`
- After confirmed response, pairing row is consumed (subsequent polls return 404)

**`POST /api/v1/devices/confirm`** (requires JWT auth)
- Body: `{ "code": "K7X-9M2" }`
- Validates code exists, not expired, not consumed
- Associates pairing with authenticated user + default workspace
- Generates device token (64-char hex, stored hashed)
- Checks `max_linked_devices` entitlement
- Response: `{ "ok": true, "data": { "device_id": 1, "device_name": "DESKTOP-ABC123" } }`

**`GET /api/v1/devices`** (requires JWT auth)
- Lists user's linked devices
- Response: `{ "ok": true, "data": [{ "id": 1, "device_name": "...", "last_seen_at": "...", "status": "confirmed" }] }`

**`DELETE /api/v1/devices/{id}`** (requires JWT auth)
- Sets status to `revoked`, clears device_token
- Logger's next upload attempt gets 401, clears local token

### Security

- Pairing codes: 10-minute TTL, single-use, rate-limited (5 codes/hour per IP)
- Status polling: rate-limited (20 requests/minute per IP). `pairing_id` is a UUID (unguessable), so brute-force is not viable, but rate limiting controls log volume under automated probing
- Device tokens: scoped to upload-only (cannot read account, billing, or other sessions)
- Token validation: `device_pairings` table lookup, check `status = 'confirmed'` and `revoked_at IS NULL`
- Entitlement defense-in-depth: `sync-upload` endpoint checks `device_sync` entitlement even though pairing already gates by `max_linked_devices`
- Max devices: 0 (Demo), 2 (Racer), 3 (World-Class)

### Database

**New table: `device_pairings`**

```sql
CREATE TABLE device_pairings (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id),
    workspace_id INT REFERENCES workspaces(id),
    pairing_code VARCHAR(7) UNIQUE,
    pairing_id UUID NOT NULL DEFAULT gen_random_uuid(),
    device_token_hash VARCHAR(128),
    device_name VARCHAR(100),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmed_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_device_pairings_code ON device_pairings(pairing_code) WHERE status = 'pending';
CREATE INDEX idx_device_pairings_user ON device_pairings(user_id) WHERE status = 'confirmed';
CREATE INDEX idx_device_pairings_pairing_id ON device_pairings(pairing_id);
```

One Alembic migration (`051_device_pairings.py`). No changes to existing tables.

**Note on workspace scoping**: Device pairing is always associated with the user's default workspace at confirmation time. Multi-workspace device selection is out of scope — the logger has no workspace picker. If a user has multiple workspaces, sessions from the logger always land in the default workspace.

## 3. Sync Upload

### Endpoint

**`POST /api/v1/sessions/sync-upload`** (device token auth)

Auth header: `Authorization: DeviceToken <token>`

Request: `multipart/form-data`
- `telemetry` (file) — the CSV file from the session bundle
- `manifest` (text) — JSON string with metadata from `session.json`

Manifest fields used:
```json
{
  "session_id": "2026-03-24_14-30-00__iRacing__spa__practice",
  "bundle_hash": "sha256...",
  "sim_name": "iRacing",
  "track_name": "Spa-Francorchamps",
  "car_name": "Porsche 911 GT3 R",
  "session_type": "practice",
  "driver_name": "John",
  "started_at_utc": "2026-03-24T14:30:00Z",
  "ended_at_utc": "2026-03-24T15:15:00Z",
  "duration_s": 2700,
  "total_laps": 12,
  "valid_laps": 10,
  "best_lap_time_s": 139.42,
  "quality_score": 0.92,
  "sample_count": 27000,
  "logger_version": "1.1.0"
}
```

### Backend Logic

**Important**: The existing upload pipeline (`sessions_v2.py`) is **async via Celery** — it saves the file, seeds a `PipelineContext` in Redis, and dispatches `build_pipeline_chain()`. The sync-upload endpoint follows the same pattern.

Additionally, `device_auth.py` must check the `device_sync` entitlement after resolving the user from the device token. This prevents a Demo user (who shouldn't be able to pair at all due to `max_linked_devices: 0`, but defense in depth) from reaching the upload logic.

```
1. Validate device token → resolve user_id, workspace_id
2. Enforce entitlement: authorize_feature(conn, user_id, "device_sync")
   - If denied → 403 with upgrade CTA
3. Check bundle_hash idempotency → if exists, return existing session_id
4. Check upload volume quota:
   - check_and_record_quota(conn, user_id, workspace_id, "upload_volume_mb", cost=file_size_mb)
5. Save CSV to shared upload directory (same as sessions_v2.py)
6. Insert session row with source='logger', status='uploaded'
7. Store manifest metadata on session row
8. If auto_analyze_on_sync == True (World-Class):
   a. Also check analyses quota: check_and_record_quota(..., "analyses", cost=1)
   b. Dispatch Celery pipeline chain (same as sessions_v2.py)
   c. Return status='analyzing' + job_id (client can poll SSE like webapp)
9. Else (Racer):
   a. Set status='pending_analysis' (driver triggers analysis from webapp)
10. Update device_pairings.last_seen_at
11. Return session_id + status
```

Response (Racer — upload only):
```json
{
  "ok": true,
  "data": {
    "session_id": 42,
    "status": "pending_analysis",
    "analyze_triggered": false
  }
}
```

Response (World-Class — auto-analyze dispatched):
```json
{
  "ok": true,
  "data": {
    "session_id": 42,
    "job_id": "uuid",
    "status": "analyzing",
    "analyze_triggered": true
  }
}
```

### Error Responses

| HTTP | Meaning | Logger Behavior |
|---|---|---|
| 200 | Success | Mark synced, store remote_id |
| 401 | Token revoked/invalid | Stop retrying, clear local token, show "Device unlinked" |
| 403 | Tier doesn't allow sync | Stop retrying, show upgrade prompt |
| 409 | Bundle hash already exists | Mark synced (idempotent success) |
| 429 | Quota exceeded | Stop retrying, show "Monthly limit reached" |
| 500/503 | Server error | Retry via queue (exponential backoff) |

### Logger-Side Implementation

**New file: `src/lap_coach_logger/core/lap_coach_sync.py`**

```python
class LapCoachSyncService:
    """Implements SyncService protocol for Lap Coach API."""

    def __init__(self, api_url: str, device_token: str) -> None:
        self._api_url = api_url.rstrip("/")
        self._device_token = device_token

    @property
    def enabled(self) -> bool:
        return bool(self._device_token)

    def upload_bundle(
        self, *, bundle_dir: Path, session_id: str, bundle_hash: str
    ) -> SyncAttemptResult:
        # Read telemetry CSV and session.json from bundle_dir
        # Build multipart POST to /api/v1/sessions/sync-upload
        # Map response to SyncAttemptResult
        ...
```

**Config additions** (`config/models.py`):
```python
@dataclass
class SyncConfig:
    enabled: bool = False
    api_url: str = "https://api.lap-coach.racing"
    device_token: str = ""
    device_name: str = ""
```

Added to `AppConfig` as `sync: SyncConfig`.

**Wiring**: `bootstrap.py` reads sync config. If `device_token` is present, creates `LapCoachSyncService` and passes it to `SyncQueueManager`. The existing finalize → queue → upload flow does the rest.

## 4. Entitlements

### New Entitlement Keys

Added to `PLAN_ENTITLEMENTS` in `auth/entitlements.py`:

```python
"free": {
    ...
    "device_sync": False,
    "auto_analyze_on_sync": False,
    "max_linked_devices": 0,
},
"racer": {
    ...
    "device_sync": True,
    "auto_analyze_on_sync": False,
    "max_linked_devices": 2,
},
"world_class": {
    ...
    "device_sync": True,
    "auto_analyze_on_sync": True,
    "max_linked_devices": 3,
},
```

**Important**: These keys must be added to the `"world_class"` literal dict at definition time (not patched after). The alias at line 104 (`PLAN_ENTITLEMENTS["world-class"] = PLAN_ENTITLEMENTS["world_class"]`) is a reference — both keys point to the same dict object, so keys added at definition time are visible through both aliases. Do not create a separate dict.

Added to `_BOOLEAN_FEATURES`:
```python
"device_sync": "device_sync",
"auto_analyze_on_sync": "auto_analyze_on_sync",
```

Added to `_UPGRADE_TIERS`:
```python
"device_sync": "racer",
"auto_analyze_on_sync": "world-class",
```

### `get_user_entitlements()` Update Required

The function at lines 289-396 of `auth/entitlements.py` builds the return dict with explicit keys. The new entitlement keys (`device_sync`, `auto_analyze_on_sync`, `max_linked_devices`) must be explicitly added to this dict, sourced from `py_defaults`:

```python
entitlements["device_sync"] = py_defaults.get("device_sync", False)
entitlements["auto_analyze_on_sync"] = py_defaults.get("auto_analyze_on_sync", False)
entitlements["max_linked_devices"] = py_defaults.get("max_linked_devices", 0)
```

Without this, `ents["device_sync"]` would raise `KeyError` at runtime.

### Frontend Entitlement Store

Add `device_sync`, `auto_analyze_on_sync`, `max_linked_devices` to `entitlements-store.ts`.

## 5. Frontend

### Download Page

**Route**: `(marketing)/product/logger/page.tsx`

Sections:
- Hero with app screenshot and download CTA
- Feature grid: local capture, auto-sync, supported sims
- System requirements
- Tier comparison: what each plan gets with the logger
- FAQ (e.g. "Does it work offline?" → yes, always)

### Account Settings — Devices

**Route**: `app/account/devices/page.tsx`

- Gated behind `device_sync` entitlement (Demo sees upgrade banner)
- "Link a Device" button → opens modal with code input
- Device list: name, status, last seen, unlink button
- Shows device count vs max: "2 of 2 devices linked"

### Sessions List — Logger Badge

- Sessions with `source='logger'` show a small "Logger" badge
- Racer tier: pending-analysis sessions show "Analyze" button
- World-Class: sessions arrive analyzed, no extra UI needed

### Logger Settings Dialog — Account Section

New section in the existing PySide6 settings dialog:
- Link status: "Not linked" / "Linked to [name]"
- "Link" button → opens pairing flow (shows code + instructions)
- "Unlink" button → clears local token + calls DELETE on server
- Last sync: timestamp + queue depth

## 6. Files Changed / Created

### Data Logger (`datalogger/`)

| File | Action | Purpose |
|---|---|---|
| `src/lap_coach_logger/core/lap_coach_sync.py` | Create | `LapCoachSyncService` implementation |
| `src/lap_coach_logger/config/models.py` | Edit | Add `SyncConfig` dataclass |
| `src/lap_coach_logger/bootstrap.py` | Edit | Wire sync service based on config |
| `src/lap_coach_logger/ui/desktop/settings_dialog.py` | Edit | Add account/pairing section |
| `src/lap_coach_logger/ui/desktop/panels.py` | Edit | Sync status in dashboard |
| `config.sample.json` | Edit | Add sync section |
| `tests/test_sync_service.py` | Create | Tests for LapCoachSyncService |

### Backend (`telemetry_tool/`)

| File | Action | Purpose |
|---|---|---|
| `web/routes/devices.py` | Create | Pairing + device management endpoints |
| `web/routes/sync_upload.py` | Create | `POST /api/v1/sessions/sync-upload` |
| `web/middleware/device_auth.py` | Create | Device token validation middleware |
| `auth/entitlements.py` | Edit | Add sync entitlement keys |
| `alembic/versions/051_device_pairings.py` | Create | Migration for device_pairings table |
| `web/app.py` | Edit | Register new blueprints |
| `tests/test_device_pairing.py` | Create | Tests for pairing flow |
| `tests/test_sync_upload.py` | Create | Tests for sync upload endpoint |

### Frontend (`lap-website/`)

| File | Action | Purpose |
|---|---|---|
| `src/app/(marketing)/product/logger/page.tsx` | Create | Download page |
| `src/app/app/account/devices/page.tsx` | Create | Device management UI |
| `src/lib/entitlements-store.ts` | Edit | Add sync entitlement keys |
| `src/data/pricing.ts` | Edit | Add logger features to eligibility matrix |
| `src/data/navigation.ts` | Edit | Add logger to nav |

## Out of Scope

- Auto-update for the logger (just update notification)
- macOS / Linux logger builds
- Real-time telemetry streaming (live data during session)
- Multi-sim beyond iRacing + ACC
- Logger analytics / crash reporting
