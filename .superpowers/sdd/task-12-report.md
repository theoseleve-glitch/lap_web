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

---

# Task 12 follow-up: security review fixes (2026-07-06)

Applied targeted fixes to `telemetry_tool/web/routes/onboarding_routes.py` for
four review findings (3 IMPORTANT, 1 MINOR), plus tests. No redesign; the
auth allowlist, row-derived canonical_id/track_key/reviewed_by, generic-401
behavior, CORS allowlist, and fail-closed ordering are all unchanged.

## Finding 1 — `?token=` fallback shared by both routes (must be GET-only)

`_extract_token()` gained an `allow_query: bool = False` keyword. `GET
/draft` calls `_extract_token(allow_query=True)` (unchanged behavior); `POST
/save` calls `_extract_token(allow_query=False)` — header-only. A token
supplied ONLY via `?token=` on `/save` is now treated as "no token" and
falls into the same generic 401 as any other auth failure.

Covering test: `TestPostSave::test_query_string_only_token_401_save_is_header_only`.

## Finding 2 — missing draft file silently disabled the unreviewed-draft gate

`save_geometry()`'s `except DraftError: auto_draft = None` fallback is
removed. A `DraftError` from `load_draft(request_id)` now returns HTTP 422
immediately with `details=[{"failure": "draft_missing"}]` (same envelope
shape as every other bless-gate failure via `api_error`/`ErrorCode.
VALIDATION_ERROR`). The token is NOT revoked and `bless_geometry`/
`reprocess_after_bless` are never called, so a valid pending request can
retry once the draft is restored — this is a server fault, not an auth
bypass or a gate-skip.

Covering tests:
- `TestPostSave::test_bless_called_with_load_draft_result` — proves
  `bless_geometry` is invoked with `auto_draft_geojson` IS the exact object
  `load_draft(request_id)` returned (sentinel-object identity check).
- `TestPostSave::test_missing_draft_returns_422_draft_missing_no_bless_no_revoke`
  — `DraftError` → 422 `{"failure": "draft_missing"}`, `bless_geometry`
  not called, `repo.set_status` not called (token untouched).

## Finding 3 — rate-limit bucket keyed on attacker-controlled `request_id`

`_scoped_rate_limit` no longer takes a `get_request_id` accessor or mixes
`request_id` into the key at all. It is now a plain decorator that sets
`g.workspace_id = f"onboarding:{ip}"` (client IP only) before `@rate_limit`
runs. Both route decorator stacks changed from
`@_scoped_rate_limit(_get_req_id_from_query)` /
`@_scoped_rate_limit(_get_req_id_from_json_body)` to plain `@_scoped_rate_limit`.
The now-dead `_get_req_id_from_query`/`_get_req_id_from_json_body` helpers
were removed (no longer referenced anywhere). Final Redis key (built by
`web/rate_limit.py`) is `ratelimit:analyze:ws:onboarding:{ip}` — same strict
"analyze" tier (5 req / 3600s), same helper machinery, just without the
attacker-forgeable `request_id` component. All requests from one IP now
share one bucket regardless of how many distinct/forged `request_id`s are
tried.

Covering test:
`TestScopedRateLimitKey::test_workspace_id_key_is_ip_only_regardless_of_request_id`
— drives `_scoped_rate_limit` directly against a throwaway Flask route with
two different `request_id` values and asserts both requests land on the
identical `g.workspace_id` (`"onboarding:127.0.0.1"`), with neither
`request_id` substring present in the key.

## Minor 4 — `repo.set_status(...)` return value discarded

`updated = repo.set_status(...)` now captures the bool. If falsey (the
`WHERE status <> 'blessed'` guard matched zero rows — already blessed by a
concurrent/duplicate save, or the row is gone), the route logs a warning and
returns `200 {"status": "blessed"}` immediately, WITHOUT re-running
`reprocess_after_bless` (a prior request already ran, or is running, it) —
the response no longer implies THIS request performed the bless. Normal
(first-writer) path is unchanged: reprocess still runs best-effort exactly
as before.

Covering test:
`TestPostSave::test_set_status_noop_returns_200_idempotent_without_reprocess`
— `fake_repo.set_status.return_value = False` still yields 200
`{"status": "blessed"}` but `fake_reprocess.assert_not_called()`.

## Test results

```
python -m pytest tests/test_onboarding/test_routes.py -v
-> 21 passed (16 pre-existing + 5 new: query-only-token-401,
   bless-called-with-load-draft-result, missing-draft-422-draft_missing,
   set-status-noop-idempotent, workspace-id-key-ip-only)

python -m pytest tests/test_onboarding/ -q
-> 136 passed, 5 skipped (pre-existing, unrelated)
```

## Constraints honored

- Branch-only (`feat/track-onboarding-loop`), no deploy.
- No `git add -A` — staged `telemetry_tool/web/routes/onboarding_routes.py`
  and `telemetry_tool/tests/test_onboarding/test_routes.py` explicitly.
  `web/rate_limit.py` was NOT touched (fix was entirely on the onboarding
  side's key construction) so it was not staged.
- `onboarding_routes.py` is 305 lines (< 500-line limit).
- No secrets touched.
- Auth allowlist exact-match, row-derived canonical_id/track_key/
  reviewed_by, generic-401 wording, CORS allowlist, and fail-closed
  ordering all left unchanged (verified by the pre-existing tests in this
  same file still passing unmodified).

## Residual concerns

- Rate limiting is still untested against a real Redis (none live in this
  environment) — same pre-existing gap noted in the original Task 12
  report; the new test verifies key *derivation* (IP-only), not the
  Lua sliding-window enforcement itself.
- `set_status` returning `False` due to a genuinely-vanished row (not a
  concurrent bless) is now also reported as `200 blessed` — indistinguishable
  from the concurrent-save case from the caller's perspective. This matches
  the task's instruction ("the geometry is blessed either way") but a truly
  missing row is a different failure mode that this fix does not
  distinguish; flagging for awareness, not treating as in-scope here.
