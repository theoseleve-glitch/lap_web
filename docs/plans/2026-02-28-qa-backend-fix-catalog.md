# QA Backend Fix Catalog

**Date:** 2026-02-28
**Agent:** B (QA Strike Team)
**Scope:** Every backend fix needed for Lap Coach SaaS — exact file:line references

---

## Section 1: P0 — 500 Error Risks (Critical)

### FIX-001: Unguarded `best_lap_number` on session dict in /sessions/{id}/energy
**File:** `telemetry_tool/web/routes/api_v1_data.py:1211`
**Risk:** 500 when `session.get("best_lap_number")` returns `None` and falls back to `1`, but lap number `1` may not exist (e.g., session with only outlap removed). `get_gps_trace()` then returns `None` which is handled, but returns empty data misleadingly — the actual best lap is never queried.
**Root Cause:** `best_lap_number` is not a standard column on the `sessions` table. It defaults to `1` instead of finding the best lap from the `laps` table like other endpoints do.
**Fix:** Use the same best-lap lookup pattern as `v1_speed_trace` (lines 112-123): query `get_laps_for_session()`, find `is_best`, fallback to first valid lap.
**Priority:** P0

### FIX-002: Unguarded `best_lap_number` on session dict in /sessions/{id}/workload
**File:** `telemetry_tool/web/routes/api_v1_data.py:3251`
**Risk:** Same as FIX-001. `session.get("best_lap_number", 1)` silently uses lap 1 which may not be the best lap or may not exist.
**Root Cause:** Copy-paste of the pattern from FIX-001 without using laps-table lookup.
**Fix:** Use laps-table best-lap lookup pattern (query `get_laps_for_session()`, find `is_best`).
**Priority:** P0

### FIX-003: Division by zero in /sessions/{id}/fatigue when `mean_time` is 0
**File:** `telemetry_tool/web/routes/api_v1_data.py:417-423`
**Risk:** If all laps have `lap_time_s = 0` (corrupt data), `mean_time` is `0` and `drift = ((running_avg - mean_time) / mean_time) * 100` raises `ZeroDivisionError`.
**Root Cause:** The guard `if times else 1` on line 417 only applies when `times` is empty, not when all values are zero.
**Fix:** Change line 417 to `mean_time = sum(times) / len(times) if times and sum(times) > 0 else 1`.
**Priority:** P0

### FIX-004: `worst_speeds[-1]` IndexError in /sessions/{id}/speed-profile when worst_speeds is empty
**File:** `telemetry_tool/web/routes/api_v1_data.py:481-482`
**Risk:** If `worst_gps` is `None` or has no speeds, `worst_speeds` is `[]`. Line 482: `worst_speeds.append(worst_speeds[-1] if worst_speeds else 0)` — the first iteration checks `if worst_speeds` which is `[]` (falsy) so it appends `0`. This is actually safe. However, there is a subtler issue: `worst_gps.get("speeds", [])` on line 472 will crash if `worst_gps` is `None` because `None.get()` raises `AttributeError`.
**Root Cause:** Line 472 does `worst_gps.get("speeds", []) if worst_gps else []` — this IS guarded. Actually safe.
**Revised Risk:** No 500 risk here on closer inspection. The ternary guard is correct.
**Priority:** N/A (false positive)

### FIX-005: Unhandled exception when `corner_best_practices` table does not exist
**File:** `telemetry_tool/web/routes/api_v1_data.py:1018-1026`
**Risk:** 500 error in `/sessions/{id}/corner-coaching` when the `corner_best_practices` table is missing (table may not exist in all schema versions). The query on line 1018-1023 will raise an `OperationalError`.
**Root Cause:** No try/except around the `corner_best_practices` query. Other endpoints (e.g., `sector_times` on line 886) wrap similar queries in try/except.
**Fix:** Wrap the `bp_row` query in try/except, defaulting `bp_row = None` on failure.
**Priority:** P0

### FIX-006: Unhandled exception when `driver_badges` table does not exist
**File:** `telemetry_tool/web/routes/api_v1_data.py:1053-1059`
**Risk:** 500 error in `/sessions/{id}/badges` when the `driver_badges` table is missing. This table is not in the core schema and may not exist in all environments.
**Root Cause:** No try/except around the `driver_badges` query.
**Fix:** Wrap badge_rows query in try/except, defaulting to empty list.
**Priority:** P0

### FIX-007: `session["driver_id"]` KeyError when session has no driver
**File:** `telemetry_tool/web/routes/api_v1_data.py:819-823`
**Risk:** In `/sessions/{id}/cross-session`, line 819 accesses `session["driver_id"]` without `.get()`. If the session row doesn't have a `driver_id` column (e.g., schema mismatch), this throws `KeyError` resulting in 500.
**Root Cause:** Direct dict key access without guard.
**Fix:** Use `session.get("driver_id")` and return empty comparisons if None.
**Priority:** P0

### FIX-008: `session["driver_id"]` KeyError in /sessions/{id}/badges
**File:** `telemetry_tool/web/routes/api_v1_data.py:1058`
**Risk:** `session["driver_id"]` without `.get()` — same pattern as FIX-007.
**Root Cause:** Direct dict key access on session dict.
**Fix:** Use `session.get("driver_id")` with guard for None.
**Priority:** P0

### FIX-009: `row[0]`, `row[2]`, `row[3]` index access on weather row
**File:** `telemetry_tool/web/routes/api_v1_data.py:3231-3234`
**Risk:** In `/sessions/{id}/weather`, the row is accessed by integer index (`row[0]`, `row[2]`, `row[3]`). If the DB returns a dict-like Row object (as PG does with RealDictCursor), integer indexing will raise `KeyError` or `TypeError`.
**Root Cause:** Mixed access patterns — code uses positional indexing but PG connector returns dict rows.
**Fix:** Access by column name: `row["air_temp_c"]`, `row["humidity_pct"]`, `row["wind_speed_mps"]`. Or convert `row = dict(row)` first.
**Priority:** P0

### FIX-010: Missing try/except on `corner_metrics` queries
**File:** `telemetry_tool/web/routes/api_v1_data.py:967-973`
**Risk:** The `/sessions/{id}/corner-metrics` endpoint queries `corner_metrics` table with no try/except. If this table doesn't exist, the handler returns 500.
**Root Cause:** No graceful fallback when table is absent.
**Fix:** Wrap in try/except returning `{"session_id": session_id, "metrics": []}` on failure.
**Priority:** P0

### FIX-011: `ILIKE` used in `/sessions/browse` but ILIKE is PostgreSQL-only
**File:** `telemetry_tool/web/routes/api_v1_data.py:1516-1524`
**Risk:** When running in SQLite mode (USE_PG=0), the `ILIKE` operator on lines 1516-1524 will cause a 500 error. SQLite uses `LIKE` (case-insensitive by default for ASCII).
**Root Cause:** Hardcoded PG-specific SQL syntax without sql_compat translation.
**Fix:** Use `LIKE` instead of `ILIKE` (SQLite LIKE is case-insensitive for ASCII), or add SQLite detection and conditional operator.
**Priority:** P0 (blocks session browsing on SQLite)

### FIX-012: Unhandled exception when `data_exports` table doesn't exist
**File:** `telemetry_tool/web/routes/api_v1_data.py:2337-2348`
**Risk:** `/exports` queries `data_exports` table which may not exist in all schema versions. The try/except on line 2337 catches this, returning empty list. This is actually handled.
**Root Cause:** N/A — already guarded.
**Priority:** N/A (false positive, already handled)

### FIX-013: SQL injection via f-string in `/sessions/browse`
**File:** `telemetry_tool/web/routes/api_v1_data.py:1540-1559`
**Risk:** The `where_sql` and `order_sql` are interpolated via f-string into SQL queries. While `where_sql` uses parameterized values (`:q`, `:driver`, `:track`), the `order_sql` comes from a safe mapping on line 1531-1536 (hardcoded values). However, `{where_sql}` itself is built from safe templates. Not a direct injection risk, but the pattern is fragile.
**Root Cause:** f-string SQL construction pattern.
**Fix:** While not currently exploitable (the sort map validates input), consider using SQL builder or at minimum add a comment documenting why this is safe.
**Priority:** P1 (pattern risk, not currently exploitable)

### FIX-014: `development_plans` table may not exist for `/dev-plans`
**File:** `telemetry_tool/web/routes/api_v1_data.py:2457-2484`
**Risk:** The try/except on line 2457 catches this and returns empty plans. This is handled.
**Priority:** N/A (already handled)

### FIX-015: Raw `%s` placeholders in PG INSERT for `/weekends` POST
**File:** `telemetry_tool/web/routes/api_v1_data.py:3007-3009`
**Risk:** The PG branch uses `%s` placeholders with a tuple, but the `PgConnectionWrapper.execute()` expects `%(name)s` params (dict). Passing a tuple may cause `TypeError` or wrong parameter binding.
**Root Cause:** Inconsistent parameter style — PG branch uses positional `%s` with tuple instead of named params.
**Fix:** Use named params: `VALUES (%(name)s, %(track_id)s, ...)` with a dict.
**Priority:** P0

---

## Section 2: P0 — CORS Configuration

### CORS-001: CORS Setup Analysis

**File:** `telemetry_tool/web/app.py:150-152`

**Current configuration:**
```python
from flask_cors import CORS
origins = [o.strip() for o in cfg.CORS_ALLOWED_ORIGINS.split(",")]
CORS(app, origins=origins, supports_credentials=True)
```

**Default origin:** `http://localhost:3000` (from `telemetry_tool/web/config.py:193-195`)

**Production origin:** Set via `CORS_ALLOWED_ORIGINS` env var (e.g., `https://lap-coach.racing,https://www.lap-coach.racing`)

**Findings:**

| Check | Status | Detail |
|-------|--------|--------|
| Origins restricted | YES | Not wildcard `*` by default — restricted to `http://localhost:3000` in dev, configurable in prod |
| OPTIONS handled | YES | Flask-CORS handles preflight automatically |
| Credentials support | YES | `supports_credentials=True` is set |
| `Access-Control-Allow-Headers` | PARTIAL | Flask-CORS defaults include `Authorization`, `Content-Type`. But custom headers `X-Workspace-Id`, `Idempotency-Key`, `X-CSRF-Token` are NOT explicitly listed |
| `Access-Control-Allow-Methods` | YES | Flask-CORS defaults include GET, POST, PUT, PATCH, DELETE, OPTIONS |

### CORS-FIX-001: Missing custom headers in CORS Allow-Headers
**File:** `telemetry_tool/web/app.py:152`
**Risk:** Browser will reject requests containing `X-Workspace-Id`, `Idempotency-Key`, or `X-CSRF-Token` headers because they are not in `Access-Control-Allow-Headers`. The preflight response won't include them, so the browser blocks the actual request.
**Root Cause:** Flask-CORS is initialized without explicit `allow_headers` parameter.
**Fix:** Change CORS init to:
```python
CORS(app, origins=origins, supports_credentials=True,
     allow_headers=["Authorization", "Content-Type", "X-Workspace-Id",
                    "Idempotency-Key", "X-CSRF-Token", "X-Request-Id"])
```
**Priority:** P0

### CORS-FIX-002: Missing `Access-Control-Expose-Headers`
**File:** `telemetry_tool/web/app.py:152`
**Risk:** Response headers like `X-Request-Id` and `Retry-After` are not readable by JavaScript because they are not in `Access-Control-Expose-Headers`.
**Root Cause:** Flask-CORS is initialized without `expose_headers` parameter.
**Fix:** Add `expose_headers=["X-Request-Id", "Retry-After"]` to the CORS init.
**Priority:** P1

### CORS-FIX-003: Caddy has no CORS headers
**File:** `Caddyfile:1-20`
**Risk:** Caddy itself does not add any CORS headers (no `Access-Control-*` in the header block). This is correct because Flask-CORS handles CORS at the application layer. Caddy as a reverse proxy passes through Flask's CORS headers. No fix needed, but the CSP header on line 12 (`default-src 'none'`) could conflict with API JSON responses if the browser applies it to XHR responses (it shouldn't for API calls, but worth noting).
**Priority:** N/A (informational)

---

## Section 3: P0 — Auth/Refresh Flow

### Token Expiry Configuration

| Token | Expiry | File:Line |
|-------|--------|-----------|
| Access token (JWT) | 15 minutes | `telemetry_tool/web/config.py:83` (`JWT_ACCESS_EXPIRY_MINUTES = 15`) |
| Refresh token (DB) | 30 days | `telemetry_tool/web/config.py:84` (`JWT_REFRESH_EXPIRY_DAYS = 30`) |
| Refresh cookie (browser) | 30 days | `telemetry_tool/web/routes/auth.py:20` (`_REFRESH_COOKIE_MAX_AGE = 30 * 24 * 3600`) |
| 2FA temp token | 5 minutes | `telemetry_tool/auth/service.py:253` |
| Password reset token | 1 hour | `telemetry_tool/auth/service.py:321` |

### Silent Refresh Mechanism

**Frontend:** `lap-website/src/lib/auth.ts:108-117`
```typescript
export async function silentRefresh(): Promise<AuthUser | null> {
  try {
    const result = await authFetch<LoginResponse>('/refresh');
    setAccessToken(result.access_token);
    return result.user;
  } catch {
    setAccessToken(null);
    return null;
  }
}
```

**Backend:** `telemetry_tool/web/routes/auth.py:297-388`
- Reads refresh token from httpOnly cookie (`lap_refresh_token`)
- Validates against DB (not expired, not revoked)
- Implements single-use rotation: old token revoked, new one issued
- Returns new access + refresh tokens

**Auto-retry on 401:** `lap-website/src/lib/api-client.ts:72-96`
- On 401, calls `tryRefreshOnce()` then replays the original request
- Uses deduplication (`_refreshPromise`) so only one refresh is in-flight at a time

### AUTH-FIX-001: Multi-tab race condition on refresh token rotation
**Files:** `telemetry_tool/web/routes/auth.py:326-366`, `lap-website/src/lib/api-client.ts:29-45`
**Risk:** When multiple browser tabs are open, each tab may independently attempt a silent refresh when its access token expires. Since the backend implements single-use rotation (line 348-351: old token is revoked), the second tab's refresh attempt will find its token revoked and fail with 401, logging the user out in that tab.
**Root Cause:** Single-use refresh token rotation is a security best practice but conflicts with multi-tab scenarios. The frontend deduplicates within a single tab (`_refreshPromise` at `api-client.ts:29`) but cannot coordinate across tabs.
**Fix:** Implement a `BroadcastChannel` or `localStorage` event listener in the frontend to coordinate refresh across tabs. When one tab refreshes successfully, it broadcasts the new access token to other tabs. Alternatively, add a short grace period on the backend (e.g., allow revoked tokens for 30 seconds after revocation) to handle the race.
**Priority:** P0

### AUTH-FIX-002: Missing `X-Workspace-Id` header in frontend API client
**Files:** `lap-website/src/lib/api-client.ts:47-66`
**Risk:** The `buildHeaders()` function never sets `X-Workspace-Id`. The tenant middleware (`telemetry_tool/web/middleware/tenant.py`) expects this header to determine which workspace's data to show. Without it, the middleware falls back to the user's default workspace, which may cause unexpected behavior in team workspaces.
**Root Cause:** The workspace concept was added in Phase 2 but the frontend API client was not updated to include it.
**Fix:** Add workspace ID to `buildHeaders()`:
```typescript
// In buildHeaders():
const workspaceId = getWorkspaceId(); // from workspace store
if (workspaceId) headers['X-Workspace-Id'] = String(workspaceId);
```
**Priority:** P0

### AUTH-FIX-003: Refresh endpoint not rate-limited
**File:** `telemetry_tool/web/routes/auth.py:297`
**Risk:** The `/auth/refresh` endpoint has no `@rate_limit()` decorator. An attacker with a valid refresh token could spam this endpoint to generate millions of tokens, potentially exhausting the `refresh_tokens` table.
**Root Cause:** Rate limiting was not applied to the refresh endpoint during implementation.
**Fix:** Add `@rate_limit(tier="auth")` decorator to the `refresh()` function.
**Priority:** P1

### AUTH-FIX-004: Logout endpoint not rate-limited
**File:** `telemetry_tool/web/routes/auth.py:271`
**Risk:** The `/auth/logout` endpoint has no `@rate_limit()` decorator. Low priority since it doesn't create resources.
**Root Cause:** Omission.
**Fix:** Add `@rate_limit(tier="auth")` decorator.
**Priority:** P3

### AUTH-FIX-005: Expired refresh token returns generic "Invalid or expired" message
**File:** `telemetry_tool/web/routes/auth.py:336-339`
**Risk:** When the refresh token has expired (not revoked), the error message says "Invalid or expired refresh token" with `TOKEN_EXPIRED` code. The frontend `silentRefresh()` catches all errors and sets token to null, which is correct behavior. However, the user experience could differentiate between "expired" (re-login needed) vs "invalid" (potential security issue).
**Root Cause:** Single error code for two different conditions.
**Fix:** Low priority. Consider splitting into separate error codes, but current behavior is acceptable.
**Priority:** P3

---

## Section 4: P1 — Response Shape Mismatches

### SHAPE-001: /sessions/{id}/gg-data
**Backend returns:** `{ok, data: {lat_g: [...], lon_g: [...], per_lap: {...}, n_points: N}}` (from `api_v1_data.py:208-213`)
**Frontend expects:** `{lat_g: number[], lon_g: number[]}` (from `GGDiagram.tsx:10-13`)
**Match:** YES — frontend uses `data.lat_g` and `data.lon_g` which are present. Extra fields (`per_lap`, `n_points`) are ignored gracefully.
**Fix needed:** None.

### SHAPE-002: /sessions/{id}/speed-trace
**Backend returns:** `{ok, data: {distances: [...], speeds: [...]}}` (from `api_v1_data.py:129-132`)
**Frontend expects:** `{distances: number[], speeds: number[]}` (from `SpeedTrace.tsx:10-13`)
**Match:** YES
**Fix needed:** None.

### SHAPE-003: /sessions/{id}/fingerprint
**Backend returns:** `{ok, data: {metrics: [...], strengths: [...], weaknesses: [...], adaptation_score: N}}` (from `api_v1_data.py:293-298`)
**Frontend expects:** `{metrics: {name: string, value: number, max: number}[]}` (from `Fingerprint.tsx:10-12`)
**Match:** YES — frontend only uses `metrics`, extra fields ignored.
**Fix needed:** None.

### SHAPE-004: /sessions/{id}/fatigue
**Backend returns:** `{ok, data: {laps: [...], fatigue_index: [...], reaction_time: [...]}}` (from `api_v1_data.py:431-435`)
**Frontend expects:** `{laps: number[], fatigue_index: number[], reaction_time: number[]}` (from `FatigueChart.tsx:10-14`)
**Match:** YES
**Fix needed:** None.

### SHAPE-005: /sessions/{id}/speed-profile
**Backend returns:** `{ok, data: {distances: [...], best_lap: [...], average: [...], worst_lap: [...]}}` (from `api_v1_data.py:484-489`)
**Frontend expects:** `{distances: number[], best_lap: number[], average: number[], worst_lap: number[]}` (from `SpeedProfile.tsx:10-15`)
**Match:** YES
**Fix needed:** None.

### SHAPE-006: /sessions/{id}/gps-trace
**Backend returns:** `{ok, data: {lat: [...], lon: [...], speed: [...]}}` (from `api_v1_data.py:384-388`)
**Frontend expects:** `{lat: number[], lon: number[], speed: number[]}` (from `TrackMap.tsx:10-14`)
**Match:** YES
**Fix needed:** None.

### SHAPE-007: /sessions/{id}/style
**Backend returns:** `{ok, data: {labels: [...], values: [...]}}` (from `api_v1_data.py:1124-1128` or `1155`)
**Frontend expects:** `{labels: string[], values: number[]}` (from `DrivingStyle.tsx:10-13`)
**Match:** YES
**Fix needed:** None.

### SHAPE-008: /sessions/{id}/corner-mastery
**Backend returns:** `{ok, data: {corners: [{name: str, score: float, entry_speed: float, apex_speed: float, exit_speed: float}]}}` (from `api_v1_data.py:1353-1363`)
**Frontend expects:** `{corners: {name: string, score: number, entry_speed: number, apex_speed: number, exit_speed: number}[]}` (from `CornerMastery.tsx:10-18`)
**Match:** PARTIAL — Backend `score` is 0-100 (line 1350: `mastery_score` capped at 100), but frontend treats it as 0-1 on line 63: `const score = Math.max(0, Math.min(1, c.score))`. A score of 80 would be clamped to 1.
**Fix needed:** Backend should normalize score to 0-1 by dividing by 100, OR frontend should adjust its scale. Current behavior: all corners with score > 1 show 100% bar.
**Priority:** P1

### SHAPE-009: /sessions/{id}/energy
**Backend returns:** `{ok, data: {distances: [...], kinetic_energy: [...], braking_energy: [...]}}` (from `api_v1_data.py:1230-1234`)
**Frontend expects:** `{distances: number[], kinetic_energy: number[], braking_energy: number[]}` (from `EnergyBalance.tsx:10-14`)
**Match:** YES
**Fix needed:** None.

### SHAPE-010: /sessions/{id}/details
**Backend returns:** `{ok, data: {id, date, track_name, driver_name, laps, best_time, mean_time, score, grade, pace_score, consistency_score, execution_score, robustness_score, ..., condition_phases, data_health, weather}}` (from `api_v1_data.py:1412-1438`)
**Frontend expects:** `SessionDetail` with `session_type`, `condition` (`track_state`), `kart_name`, `condition_phases`, `data_health` (from `sessions/[id]/page.tsx:40-90`)
**Match:** PARTIAL
- Frontend expects `condition` field but backend returns `track_state` (line 1423). Need alias.
- Frontend expects `kart_name` but backend does not include it.
- Frontend expects `pace_max`, `consistency_max`, `execution_max`, `robustness_max` (from line 51-54 of page.tsx) — these are present in the backend response (lines 1426-1432).
**Fix needed:** Add `"condition": session.get("track_state")` and `"kart_name": None` to the response dict at line 1412.
**Priority:** P1

### SHAPE-011: /sessions/{id}/stints
**Backend returns:** `{ok, data: {stints: [{stint_number, start_lap, end_lap, avg_time, best_time, laps_count}]}}` (from `api_v1_data.py:3298-3309`)
**Frontend expects:** (from `StintChart.tsx:20-33`) `{stints: {stint_number: number, start_lap: number, end_lap: number, avg_time: number, best_time: number, laps_count: number}[]}`
**Match:** YES
**Fix needed:** None.

### SHAPE-012: /sessions/{id}/trends
**Backend returns:** `{ok, data: {distances: [...], pace_delta: [...], consistency_index: [...]}}` (from `api_v1_data.py:3345-3349`)
**Frontend expects:** (from `TrendChart.tsx:10-18`) `{distances: number[], pace_delta: number[], consistency_index: number[]}`
**Match:** YES
**Fix needed:** None.

### SHAPE-013: /sessions/{id}/consistency
**Backend returns:** `{ok, data: {laps: [...], sectors: [...], deltas: [[...]]}}` (from `api_v1_data.py:1273-1277`)
**Frontend expects:** (from `ConsistencyHeatmap.tsx:10-20`) `{laps: number[], sectors: number[], deltas: number[][]}`
**Match:** YES
**Fix needed:** None.

### SHAPE-014: /tracks/{id}/evolution
**Backend returns:** `{ok, data: {track_id: "...", sessions: [{session_id, date, best_time_s, score, track_state, session_type, driver}]}}` (from `api_v1_data.py:534-546`)
**Frontend expects:** (from `tracks/[id]/page.tsx:343`) `{sessions: EvolutionSession[]}`
**Match:** PARTIAL — Frontend may expect the data wrapped in `sessions` key directly. Backend wraps it as `{track_id: ..., sessions: [...]}`. The frontend query accesses it as `api.get<{ sessions: EvolutionSession[] }>` which would extract the `data` from the envelope. Since `data = {track_id, sessions}`, the frontend would need `data.sessions` to access the array.
**Fix needed:** Verify frontend destructuring. May need to adjust query to expect the full shape.
**Priority:** P2

---

## Section 5: P2 — Missing Endpoints

### MISSING-001: /api/v1/sessions/{id}/rival-gap
**Called from:** `lap-website/src/components/app/charts/RivalChart.tsx:25`
**Backend route:** DOES NOT EXIST in `api_v1_data.py`. A legacy route exists at `/session/{id}/pit-window` and `/rivals/compare` in `api_data.py` (lines 1947, 2954), but these are legacy HTML endpoints, not v1 API.
**Data source:** Would need rival registration data or simulated gap data.
**Fix:** Create `/api/v1/sessions/<session_id>/rival-gap` endpoint returning `{lap_numbers: [], gap_seconds: [], rival_name: ""}`. For now, can return empty data: `{"lap_numbers": [], "gap_seconds": []}`.
**Priority:** P2

### MISSING-002: /api/v1/sessions/{id}/pit-window
**Called from:** `lap-website/src/components/app/charts/PitWindowChart.tsx:33`
**Backend route:** DOES NOT EXIST in `api_v1_data.py`. Legacy route at `/session/{id}/pit-window` in `api_data.py:1947` but on wrong blueprint and URL pattern.
**Data source:** Computed from stint analysis and lap degradation.
**Fix:** Create `/api/v1/sessions/<session_id>/pit-window` endpoint. Can derive from stint_analysis data, returning `{current_lap, window_open, window_close, optimal_lap, time_loss_per_lap}`.
**Priority:** P2

### MISSING-003: /api/v1/sessions/{id}/corners/{cornerId}/replay
**Called from:** `lap-website/src/components/app/corner-replay/CornerReplay.tsx:67`
**Backend route:** DOES NOT EXIST in `api_v1_data.py`. A legacy route exists at `/session/{id}/corner-replay-data` in `api_data.py:1240`, but it doesn't match the expected URL pattern and doesn't return per-corner data.
**Data source:** GPS traces filtered by corner boundaries, augmented with speed/throttle/brake approximations.
**Fix:** Create `/api/v1/sessions/<session_id>/corners/<corner_id>/replay` endpoint. Return `{corner_id, corner_name, frames: [{time, speed, throttle, brake, steeringAngle, gLat, gLon, lat, lon}], gps_path: [{lat, lon}], total_time}`.
**Priority:** P2

### MISSING-004: /api/v1/setup/status
**Called from:** `lap-website/src/app/app/setup-tracker/page.tsx:149`
**Backend route:** DOES NOT EXIST. The legacy `/setup-tracker` route in `predictions.py:21` is an HTML page, not an API endpoint.
**Data source:** User activity data (has sessions? has tracks? has drivers?).
**Fix:** Create `/api/v1/setup/status` endpoint. Query sessions, tracks, drivers counts and return `{steps: [{id: "create_account", status: "complete"}, {id: "upload_session", status: "pending"}, ...]}`.
**Priority:** P2

### MISSING-005: /api/v1/data-health/jobs/{id}
**Called from:** `lap-website/src/app/app/data-health/[id]/page.tsx:49`
**Backend route:** DOES NOT EXIST. The `/data-health/jobs` (list) endpoint exists at `api_v1_data.py:2173` but there's no detail endpoint for a single job by ID.
**Data source:** `ingestion_jobs` table, filtered by `job_id`.
**Fix:** Create `/api/v1/data-health/jobs/<job_id>` endpoint. Query `SELECT * FROM ingestion_jobs WHERE job_id = :jid` and return the job detail.
**Priority:** P2

### MISSING-006: /api/v1/tracks/{id}/evolution (different shape expected)
**Called from:** `lap-website/src/app/app/tracks/[id]/evolution/page.tsx:265`
**Backend route:** EXISTS at `api_v1_data.py:513` but the evolution page fetches with a query path that may include `?driver_id=X` filtering which the backend doesn't support.
**Fix:** Add optional `driver_id` query parameter support to `v1_track_evolution`.
**Priority:** P2

---

## Section 6: P3 — Edge Case Guards

### EDGE-001: Session ID not validated as safe string
**File:** `telemetry_tool/web/routes/api_v1_data.py` (all session endpoints)
**Risk:** Session IDs are strings (not integers) and are used directly in SQL queries via parameterized queries (safe from injection). However, extremely long session IDs (e.g., 10MB string) could cause memory issues.
**Fix:** Add max-length validation: `if len(session_id) > 500: return api_error(...)`.
**Priority:** P3

### EDGE-002: `page` and `per_page` query params accept negative values
**File:** `telemetry_tool/web/routes/api_v1_data.py:1501-1502`
**Risk:** `page = max(1, request.args.get("page", 1, type=int))` — this is actually guarded by `max(1, ...)`. The `type=int` in `request.args.get()` returns the default value if the param is not a valid int. This is safe.
**Fix needed:** None — already guarded.
**Priority:** N/A

### EDGE-003: `limit` query params with large values
**File:** Multiple endpoints (e.g., `api_v1_data.py:1621`, `1775`, `1864`, `2097`, `2186`)
**Risk:** All limit params are capped: `min(50, max(1, ...))`, `min(200, ...)`, `min(100, ...)`. These are properly guarded.
**Fix needed:** None — already guarded.
**Priority:** N/A

### EDGE-004: No workspace isolation check on legacy endpoints
**File:** `telemetry_tool/web/routes/api_v1_data.py` (all endpoints)
**Risk:** When `USE_PG=1`, RLS policies auto-filter workspace-scoped tables. But the `api_v1_data.py` endpoints use `get_db_connection()` which, in PG mode, returns a connection with RLS context set by `tenant_middleware`. In SQLite mode, there's no workspace isolation at all.
**Root Cause:** SQLite mode has no RLS. This is by design for single-user desktop mode.
**Fix:** Acceptable for desktop mode. For SaaS mode (USE_PG=1), RLS provides isolation. No additional code changes needed.
**Priority:** N/A (by design)

### EDGE-005: Rate limit tier not assigned for some endpoints
**File:** `telemetry_tool/web/routes/api_v1_data.py`
**Risk:** All endpoints in `api_v1_data.py` have `@rate_limit(tier="read")` or `@rate_limit(tier="write")`. This is consistently applied.
**Fix needed:** None.
**Priority:** N/A

### EDGE-006: `track_id` not validated as safe string
**File:** `telemetry_tool/web/routes/api_v1_data.py:498-506, 515-546, 553-577`
**Risk:** `track_id` is used in parameterized queries (safe). No length validation.
**Fix:** Add length guard similar to EDGE-001.
**Priority:** P3

### EDGE-007: DELETE session cascade may miss tables
**File:** `telemetry_tool/web/routes/api_v1_data.py:761-778`
**Risk:** The `related_tables` list on lines 761-778 is hardcoded. If new tables are added that reference `session_id`, they won't be cleaned up, potentially leaving orphaned rows (not a 500 risk, but data hygiene issue).
**Root Cause:** Manual table list instead of schema introspection or CASCADE foreign keys.
**Fix:** Use `ON DELETE CASCADE` foreign keys in the schema, or maintain the list as a constant that's updated when new tables are added.
**Priority:** P3

### EDGE-008: `float()` conversion without validation in file upload
**File:** `telemetry_tool/web/routes/api_v1_data.py:2268-2276`
**Risk:** In `v1_predefined_karts()`, `float(row.get("power_hp", "0") or "0")` could throw `ValueError` if the CSV contains non-numeric values like "N/A" that weren't caught by the "NA" filter.
**Root Cause:** The CSV filter on line 2257 checks for `"NA"` but not variations like "N/A", "n/a", "None", etc.
**Fix:** Wrap each `float()` call in try/except with default `0.0`.
**Priority:** P3

### EDGE-009: Missing `Content-Disposition` header on export responses
**File:** `telemetry_tool/web/routes/api_v1_data.py:2431-2442`
**Risk:** Export data is returned as JSON with the content embedded as a string. The frontend would need to create a blob download from this. No 500 risk, but the UX could be improved by returning a file download response directly.
**Root Cause:** Intentional design — content is returned inline for the frontend to handle.
**Fix:** Optional improvement: add a `/exports/{id}/download` endpoint that returns the file with proper Content-Disposition headers.
**Priority:** P3

---

## Section 7: Priority Summary

| Priority | Count | Description |
|----------|-------|-------------|
| P0 | 13 | 500 risks (FIX-001 through FIX-015, excluding false positives) + CORS headers (CORS-FIX-001) + Auth race condition (AUTH-FIX-001) + Missing workspace header (AUTH-FIX-002) |
| P1 | 4 | Response shape mismatches (SHAPE-008, SHAPE-010) + Refresh rate limit (AUTH-FIX-003) + CORS expose headers (CORS-FIX-002) |
| P2 | 7 | Missing endpoints (MISSING-001 through MISSING-006) + Evolution shape (SHAPE-014) |
| P3 | 6 | Edge case guards (EDGE-001, EDGE-006, EDGE-007, EDGE-008, EDGE-009) + Logout rate limit (AUTH-FIX-004) |

### P0 Breakdown (Fix Immediately)

| ID | Summary | File |
|----|---------|------|
| FIX-001 | `best_lap_number` not on session table — energy endpoint | `api_v1_data.py:1211` |
| FIX-002 | `best_lap_number` not on session table — workload endpoint | `api_v1_data.py:3251` |
| FIX-003 | Division by zero in fatigue calculation | `api_v1_data.py:417` |
| FIX-005 | Unhandled missing `corner_best_practices` table | `api_v1_data.py:1018` |
| FIX-006 | Unhandled missing `driver_badges` table | `api_v1_data.py:1053` |
| FIX-007 | `session["driver_id"]` KeyError in cross-session | `api_v1_data.py:819` |
| FIX-008 | `session["driver_id"]` KeyError in badges | `api_v1_data.py:1058` |
| FIX-009 | Integer-indexed row access fails on PG dict rows (weather) | `api_v1_data.py:3231` |
| FIX-010 | Missing try/except on `corner_metrics` table query | `api_v1_data.py:967` |
| FIX-011 | `ILIKE` is PG-only, breaks SQLite mode (sessions/browse) | `api_v1_data.py:1516` |
| FIX-015 | Raw `%s` params in PG INSERT for weekends | `api_v1_data.py:3007` |
| CORS-FIX-001 | Custom headers not in CORS Allow-Headers | `app.py:152` |
| AUTH-FIX-001 | Multi-tab refresh token race condition | `auth.py:326` / `api-client.ts:29` |
| AUTH-FIX-002 | Missing `X-Workspace-Id` header in frontend API client | `api-client.ts:47` |
