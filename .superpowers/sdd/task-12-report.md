# Task 12 report — Routes + middleware allowlist + CORS

## What was built

- `telemetry_tool/web/routes/onboarding_routes.py` (new) — Flask blueprint
  `onboarding` at `url_prefix="/api/v1/onboarding"`:
  - `GET /draft?req=<request_id>` — token-authed fetch of the auto-drafted
    geojson (`onboarding.draft.load_draft`).
  - `POST /save` — token-authed submission of the corrected geojson; runs
    it through `onboarding.bless_service.bless_geometry` (force=False,
    fail-closed), revokes the token on success, best-effort kicks off
    `onboarding.reprocess.reprocess_after_bless`.
- `telemetry_tool/web/middleware/auth.py` — added exactly
  `/api/v1/onboarding/draft` and `/api/v1/onboarding/save` to
  `_AUTH_PUBLIC_PATHS`. Nothing else touched.
- `telemetry_tool/web/app.py` — registered the new blueprint inside the
  existing `if cfg.USE_PG:` try-block, right after `sync_upload_bp`,
  matching the established import/register/log pattern.
- `telemetry_tool/tests/test_onboarding/test_routes.py` (new) — 16 tests,
  Flask test client, all passing.

## Auth allowlist match style (verified, not assumed)

`web/middleware/auth.py`'s `auth_middleware()` checks
`request.path in _AUTH_PUBLIC_PATHS` — a plain Python **set membership /
exact-string match**, not a prefix or regex (prefix-style exemptions in this
file are handled separately via compiled regexes, e.g. `_OAUTH_PATH_RE`,
`_DEVICE_PAIR_STATUS_RE`, or explicit `.startswith()` calls for
`/static/` and `/api/v1/endurance/status|report/`). I added the two
onboarding paths as new exact entries in the same set, so
`/api/v1/onboarding/draft` and `/api/v1/onboarding/save` bypass JWT
verification, but a made-up neighbour like `/api/v1/onboarding/other` still
falls through to the normal `/api/v1/*` JWT-required branch and gets a 401
`"Authentication required"` (as opposed to our routes' own generic
`"Invalid or expired onboarding link"` 401) — both are asserted in
`TestAuthMiddlewareAllowlist`.

CSRF (`web/middleware/csrf.py`) needed no change: it already exempts any
request carrying an `Authorization: Bearer <token>` header outright ("Bearer
tokens are CSRF-immune"), and our POST route's sole auth mechanism is
exactly that header, so `POST /save` sails through CSRF without needing a
path exemption there.

## Rate-limit tier

Applied `web/rate_limit.py`'s `@rate_limit("analyze")` tier — `5
requests / 3600s`, which ties with `"device_pair"` as the strictest of the
9 configured tiers (by fewest requests over the longest window); `"analyze"`
was picked as the closer semantic fit for a server-gated operator action.

Keying on `request_id + client IP` (not the decorator's default
user/workspace/IP priority) was done by reusing the *existing* limiter
rather than writing a second Redis/Lua implementation: a small outer
decorator, `_scoped_rate_limit`, sets `g.workspace_id =
f"onboarding:{request_id}:{ip}"` **before** `@rate_limit` runs (it must be
the outer decorator in the stack so its assignment happens first) —
`rate_limit()`'s own scope-selection logic already prefers
`g.workspace_id` over `g.current_user_id`/IP, so this yields exactly the
required `request_id+IP` bucket with zero duplicated rate-limiting code.
The same decorator also short-circuits `OPTIONS` preflight to a bare `("",
204)` before either the auth check or the rate limiter run (no quota
consumed on preflight, no auth required — matches `auth_middleware`'s own
existing OPTIONS bypass).

Not independently asserted in tests: this environment has no live Redis, so
`get_redis()` returns `None` and `rate_limit()` fails open (calls straight
through) — same limitation already documented by other onboarding-task test
suites for their Postgres/Celery dependencies. The scoping logic itself
(`g.workspace_id` assignment) is exercised implicitly by every test that
hits the routes, since it runs unconditionally before the (no-op-here) rate
check.

## CORS mechanism

No new code needed beyond registering the blueprint: `web/middleware/cors.py`'s
`init_cors()` installs a single global `after_request` hook that stamps
`Access-Control-Allow-Origin`/`-Credentials`/`-Methods`/`-Headers` on **every**
response (success, error, or `OPTIONS`) whenever the incoming `Origin` header
is in the `CORS_ALLOWED_ORIGINS` allowlist — it never checks path, so as long
as `ANNOTATOR_HOST` is included in that env var's comma-separated list in
deployment, the two onboarding routes get CORS headers for free. The routes
themselves only need to *respond* to `OPTIONS` (methods=["GET"/"POST",
"OPTIONS"]) — handled by `_scoped_rate_limit`'s short-circuit above — since
Flask defers all OPTIONS handling to the view once "OPTIONS" is explicitly
listed in `methods`. Verified in `TestOptionsCors`: both routes return CORS
headers for `_ANNOTATOR_HOST` and correctly omit `Access-Control-Allow-Origin`
for an unrecognised origin.

## canonical_id / track_key are row-derived, not body-derived (confirmed)

Migration 081's `track_onboarding_requests` table (`onboarding/repo.py`'s
`_ALL_COLUMNS`) has **no separate `canonical_id` column** — only `track_key`.
The plan's Task 13 interfaces note calls the trigger's `track_key`
"canonical" outright, so `track_key` already **is** the canonical id at this
stage of the loop. The route does:

```python
canonical_id = row.get("track_key")
track_key = row.get("track_key")
session_refs = row.get("session_refs") or []
vehicle_classes = row.get("vehicle_classes") or []   # no such column -> always []
```

reading exclusively from the `repo.get(conn, request_id)` row fetched via
the token-verified `request_id` — the request body's `request_id` and
`geometry` are read, but any other body field (e.g. a client-supplied
`canonical_id`/`track_key`) is silently ignored; nothing in the body is ever
passed to `bless_geometry`'s `canonical_id=` or `reprocess_after_bless`'s
`track_key=`/`canonical_id=` parameters. Confirmed by
`test_canonical_id_is_row_derived_not_body`, which POSTs
`{"canonical_id": "attacker", "track_key": "attacker-track", ...}` and
asserts `bless_geometry` was called with the row's real value
(`"real_canonical"`), not the attacker's.

`reviewed_by` is likewise fully server-derived:
`f"onboarding:{os.environ['ONBOARDING_OPERATOR_EMAIL']}"` — read from env,
never from the request body, and `os.environ[...]` (not `.get`) so a
missing var raises rather than silently using an empty/absent reviewer
(fail-closed, matching the rest of this loop's env-var conventions in
`tasks/onboarding_tasks.py`).

## Auth semantics (every failure -> one generic 401)

`_authorize()` collapses every failure mode to `None` uniformly: missing
`request_id`/token, `TokenError` from `onboarding.tokens.verify` (malformed,
tampered, expired, wrong scope, wrong `request_id`), an unknown
`request_id` (`repo.get` returns `None`), or a `jti` that no longer matches
`row["token_jti"]` (already consumed by a prior save, or rotated) — the
route then returns the identical `401 {"error": {"message": "Invalid or
expired onboarding link"}}` regardless of which case fired, so a caller can
never learn which check failed. All 6 negative-path variants (missing,
expired, tampered, wrong-request_id, jti-mismatch, on both GET and one on
POST) are covered in tests.

On a successful bless, `repo.set_status(conn, request_id, "blessed",
blessed_at=..., token_jti=None)` is committed (`conn.commit()`) **before**
`reprocess_after_bless` is attempted, so the token is revoked and the bless
durable even if reprocessing throws (caught, logged, swallowed — matches
Task 9's own "best-effort" contract). On `bless_geometry` returning
`ok=False`, `repo.set_status` is never called — the token stays valid so the
operator can retry with a corrected submission — and the route returns `422`
with the gate failures.

## Deviations from the plan text

None identified — `bless_service`'s own `unreviewed_draft` gate (comparing
against `auto_draft_geojson=load_draft(request_id)`) already implements the
plan's "reject if it equals the stored auto-draft" requirement, so the route
did not need a separate pre-check; it surfaces through the same generic
`ok=False -> 422` path as any other bless-gate failure.

## Test results

```
python -m pytest tests/test_onboarding/test_routes.py -v   -> 16 passed
python -m pytest tests/test_onboarding/ -q                 -> 131 passed, 5 skipped (pre-existing)
python -m pytest tests/test_auth_middleware.py -q          -> 7 passed (no regression)
```

## Concerns / follow-ups for later tasks

- Rate limiting on these two routes is untested against a real Redis (none
  live in this environment) — same gap as every other onboarding task.
- `vehicle_classes` is always `[]` in practice (no such column on
  `track_onboarding_requests`), so `reprocess_after_bless`'s
  `compute_racing_lines` enqueue step is a guaranteed no-op from this route
  today; if a future task adds a vehicle-class column this route should be
  updated to read it.
- Task 13 (trigger hook) and Task 14 (annotator) are out of scope here and
  unstarted.
