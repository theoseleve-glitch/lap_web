# Browser Console Error Triage (lap-coach.racing)

This guide explains the exact classes of browser-console messages seen on production and how to debug them quickly.

## 1) CORS preflight failures (`blocked by CORS policy` + `preflight ... does not have HTTP ok status`)

Example:

- `Access to fetch at 'https://api.lap-coach.racing/api/v1/leaderboard' from origin 'https://www.lap-coach.racing' has been blocked by CORS policy`
- `Failed to load resource: net::ERR_FAILED`

### What this actually means

The browser sent an **OPTIONS preflight** request before the real request. The preflight response was not a 2xx with valid CORS headers, so the browser blocked the real call.

In practice this is usually one of:

1. Endpoint path is wrong (404 on preflight).
2. Auth/proxy rejects `OPTIONS` (401/403/5xx).
3. CORS allowlist does not include the frontend origin.
4. Reverse proxy is routing GET/POST but not OPTIONS.

### Repo context

- Backend app enables CORS from `CORS_ALLOWED_ORIGINS` and supports credentials. Ensure it includes `https://www.lap-coach.racing` exactly. (`telemetry_tool/web/app.py`)
- Auth middleware explicitly bypasses `OPTIONS`, which is required for preflight to succeed on protected APIs. (`telemetry_tool/web/middleware/auth.py`)

### Fast checks

```bash
# Preflight check from prod origin
curl -i -X OPTIONS 'https://api.lap-coach.racing/api/v1/leaderboard' \
  -H 'Origin: https://www.lap-coach.racing' \
  -H 'Access-Control-Request-Method: GET'

# Verify env on backend
echo "$CORS_ALLOWED_ORIGINS"
```

Expected: `HTTP 200/204` and `Access-Control-Allow-Origin: https://www.lap-coach.racing`.

---

## 2) `401` on `/auth/login`

This is not a CORS error by itself.

- If credentials are wrong or payload missing, `401` is expected.
- If this appears immediately on page load (without login action), check frontend boot flow for accidental login call.

---

## 3) `500` on `/api/v1/karts`

Server-side failure in the karts endpoint.

- This is backend logic/data and **not** a CORS failure.
- Inspect backend logs using request IDs if present.
- Verify DB migrations/tables for karts exist and are healthy.

Fast check:

```bash
curl -i 'https://api.lap-coach.racing/api/v1/karts' \
  -H 'Origin: https://www.lap-coach.racing' \
  -H 'Authorization: Bearer <token>'
```

If this returns 500 with CORS headers present, the issue is endpoint internals.

---

## 4) `404` on `/analyze/api/start`

Likely wrong URL shape from frontend/runtime config.

- API client uses `${NEXT_PUBLIC_API_URL}/api/v1` base path. (`lap-website/src/lib/api-client.ts`)
- A call to `/analyze/api/start` suggests an extra `/analyze` prefix was introduced outside the typed API client.

Action:

1. Find where `/analyze/api/start` is built in frontend code/config.
2. Normalize to v1 path (for example `/api/v1/...`) through the central API client.

---

## 5) `Element not found: #s5-personas`

Non-fatal DOM warning from code trying to initialize a node that is absent on the current route/build variant.

Fix options:

- Guard selector lookup before usage.
- Scope script execution to pages that contain the element.

---

## 6) THREE / WebGL warnings

Examples:

- `THREE.Clock: ... deprecated. Please use THREE.Timer instead.`
- `WebGL: INVALID_OPERATION: readPixels ... HALF_FLOAT ... not Uint16Array`
- `THREE.WebGLRenderer: Context Lost.`

Interpretation:

- Deprecation: library upgrade follow-up item.
- `readPixels` mismatch: shader/readback type mismatch in render pipeline.
- Context lost: GPU resource pressure or error cascade.

Prioritize API/CORS/404/500 blockers first; WebGL warnings may be noisy but unrelated to data-load failures.

---

## Recommended triage order for the exact error set above

1. Fix/verify CORS preflight on `/api/v1/leaderboard` and `/api/v1/files/list`.
2. Fix wrong route construction causing `/analyze/api/start` 404.
3. Investigate backend 500 on `/api/v1/karts` in server logs.
4. Then clean DOM init and WebGL warnings.

This ordering resolves user-visible functional failures before visual/engine warnings.
