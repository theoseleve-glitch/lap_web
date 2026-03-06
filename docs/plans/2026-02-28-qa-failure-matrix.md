# QA Failure Matrix -- Lap Coach SaaS Platform

**Date:** 2026-02-28
**Author:** Agent A (QA Strike Team)
**Scope:** Backend routes, CSV ingestion, frontend-to-backend API map, subscription entitlements, chart component fragility

---

## Section 1: Backend Route Classification

### 1A. Session Analysis Endpoints (`api_v1_data.py`)

| # | Route | Method | Handler | Status | Issue |
|---|-------|--------|---------|--------|-------|
| 1 | `/api/v1/sessions/<id>/laps/gps` | GET | `api_v1_data.py:83` | working | Returns `{laps: [int]}`. Guarded via model function. |
| 2 | `/api/v1/sessions/<id>/speed-trace` | GET | `api_v1_data.py:100` | working | 404 on missing session/GPS. Guarded. |
| 3 | `/api/v1/sessions/<id>/lap-times` | GET | `api_v1_data.py:140` | working | Filters out null `lap_time_s`. Guarded. |
| 4 | `/api/v1/sessions/<id>/gg-data` | GET | `api_v1_data.py:182` | working | `_clean_accel` handles NaN/Inf. Returns empty arrays on no data. |
| 5 | `/api/v1/sessions/<id>/theoretical` | GET | `api_v1_data.py:221` | working | 404 on missing data. Guarded. |
| 6 | `/api/v1/sessions/<id>/fingerprint` | GET | `api_v1_data.py:257` | working | Returns empty `metrics: []` when no scores. Guarded. |
| 7 | `/api/v1/sessions/<id>/reference-line` | GET | `api_v1_data.py:306` | working | 404 on missing reference line. |
| 8 | `/api/v1/sessions/<id>/best-lap-gps` | GET | `api_v1_data.py:326` | working | 404 on missing best lap. |
| 9 | `/api/v1/sessions/<id>/gps-trace` | GET | `api_v1_data.py:358` | working | Fallback to first lap if no explicit best. |
| 10 | `/api/v1/sessions/<id>/fatigue` | GET | `api_v1_data.py:396` | 500-risk | `mean_time` defaults to 1 but `running_avg = times[0]` can be 0 if `lap_time_s` defaults to 0; `abs(brake)` where `brake` could be `None` -- guarded with `if brake else 0` so OK. Edge case: all `lap_time_s` are 0 causes division by zero in `((running_avg - mean_time) / mean_time)` when `mean_time == 0`. |
| 11 | `/api/v1/sessions/<id>/speed-profile` | GET | `api_v1_data.py:443` | 500-risk | `worst_speeds[-1]` when `worst_speeds` is empty causes `IndexError`. Protected by `if worst_speeds else 0` inline but still appends `worst_speeds[-1]` in `while` loop when `worst_speeds` is empty -- infinite loop or IndexError. |
| 12 | `/api/v1/tracks/<id>/records` | GET | `api_v1_data.py:497` | working | Simple wrapper. |
| 13 | `/api/v1/tracks/<id>/evolution` | GET | `api_v1_data.py:514` | working | Returns empty `sessions: []` on no data. |
| 14 | `/api/v1/tracks/<id>/geometry` | GET | `api_v1_data.py:554` | working | 404 on no geometry; catches JSON decode errors. |
| 15 | `/api/v1/files` | GET | `api_v1_data.py:593` | working | Lists CSV files. |
| 16 | `/api/v1/files/upload` | POST | `api_v1_data.py:624` | working | Extensive validation: extension, binary, CSV structure, double-extension block. |
| 17 | `/api/v1/sessions/<id>` | DELETE | `api_v1_data.py:744` | working | Cascades delete across 18 related tables. Catches exceptions. |
| 18 | `/api/v1/sessions/<id>/cross-session` | GET | `api_v1_data.py:802` | working | 404 on missing session. |
| 19 | `/api/v1/sessions/<id>/sectors` | GET | `api_v1_data.py:850` | working | Returns empty `sectors: []` on no data. |
| 20 | `/api/v1/sessions/<id>/sector-times` | GET | `api_v1_data.py:875` | working | Catches exception on missing table; returns empty. |
| 21 | `/api/v1/sessions/<id>/delta` | GET | `api_v1_data.py:905` | working | 404 on no laps. |
| 22 | `/api/v1/sessions/<id>/corner-metrics` | GET | `api_v1_data.py:959` | working | Returns empty `metrics: []` on no data. |
| 23 | `/api/v1/sessions/<id>/corner-coaching` | GET | `api_v1_data.py:982` | 500-risk | Queries `corner_best_practices` table which may not exist in all schemas. Uses raw `conn.execute()` with no try/except on the best-practice fetch. |
| 24 | `/api/v1/sessions/<id>/badges` | GET | `api_v1_data.py:1037` | 500-risk | Queries `driver_badges` and `session_tags` tables. If tables are missing (schema mismatch), unguarded `conn.execute()` will throw. |
| 25 | `/api/v1/sessions/<id>/style` | GET | `api_v1_data.py:1093` | working | Falls back to score_details radar if no driving style data. |
| 26 | `/api/v1/sessions/<id>/brake-points` | GET | `api_v1_data.py:1163` | working | Derives from `corner_metrics`. Returns empty arrays on no data. |
| 27 | `/api/v1/sessions/<id>/energy` | GET | `api_v1_data.py:1198` | 500-risk | `speeds` from GPS are assumed to be in km/h and divided by 3.6, but `get_gps_trace` returns speeds in m/s (RaceChrono unit). Energy calculations will be wrong by a factor of 3.6^2. Also `best_lap_number` may not exist as a field on `session` dict -- uses `.get()` defaulting to 1 which is safe but may pick wrong lap. |
| 28 | `/api/v1/sessions/<id>/consistency` | GET | `api_v1_data.py:1242` | wrong-shape | Sector deltas are **synthetically generated** from a hash formula `(0.7 + 0.6 * ((i*7 + lap*3) % 10) / 10)` rather than real sector data. Returns fake heatmap data. |
| 29 | `/api/v1/sessions/<id>/comparison-matrix` | GET | `api_v1_data.py:1285` | working | Returns raw laps data from DB. |
| 30 | `/api/v1/sessions/<id>/corner-mastery` | GET | `api_v1_data.py:1312` | working | Aggregates corner metrics with mastery score computation. |
| 31 | `/api/v1/sessions/<id>/details` | GET | `api_v1_data.py:1371` | working | Comprehensive session detail. Catches missing data gracefully. |
| 32 | `/api/v1/sessions/<id>/laps` | GET | `api_v1_data.py:1446` | working | Maps to frontend LapRow shape. |
| 33 | `/api/v1/sessions/browse` | GET | `api_v1_data.py:1485` | 500-risk | Uses `ILIKE` operator which is PostgreSQL-only; will fail on SQLite. |
| 34 | `/api/v1/sessions/recent` | GET | `api_v1_data.py:1610` | working | Simple wrapper over `get_sessions()`. |
| 35 | `/api/v1/dashboard/stats` | GET | `api_v1_data.py:1631` | working | Comprehensive stats with sparkline arrays. |
| 36 | `/api/v1/drivers` | GET | `api_v1_data.py:1698` | working | Wrapper. |
| 37 | `/api/v1/drivers/<id>` | GET | `api_v1_data.py:1715` | working | With profile and progression. 404 guarded. |
| 38 | `/api/v1/drivers/<id>/sessions` | GET | `api_v1_data.py:1755` | working | With pagination. |
| 39 | `/api/v1/tracks` | GET | `api_v1_data.py:1801` | working | Wrapper. |
| 40 | `/api/v1/tracks/<id>` | GET | `api_v1_data.py:1818` | working | With session count and best time. |
| 41 | `/api/v1/tracks/<id>/leaderboard` | GET | `api_v1_data.py:1853` | working | Ranked entries. |
| 42 | `/api/v1/karts` | GET | `api_v1_data.py:1892` | working | Exception-guarded with schema validation. |
| 43 | `/api/v1/karts` | POST | `api_v1_data.py:1936` | working | Validation on name. |
| 44 | `/api/v1/karts/<id>` | GET | `api_v1_data.py:1983` | 500-risk | `os.environ.get("USE_PG")` checked at runtime; mismatch between PG (`kart_sessions`) and SQLite (`sessions WHERE kart_id`) table structures. |
| 45 | `/api/v1/weekends` | GET | `api_v1_data.py:2018` | working | Wrapper. |
| 46 | `/api/v1/weekends/<id>` | GET | `api_v1_data.py:2035` | working | With sessions. 404 guarded. |
| 47 | `/api/v1/annotations` | GET | `api_v1_data.py:2059` | working | Paginated with search. |
| 48 | `/api/v1/data-health/stats` | GET | `api_v1_data.py:2139` | working | Exception-guarded; returns empty on error. |
| 49 | `/api/v1/data-health/jobs` | GET | `api_v1_data.py:2174` | working | Exception-guarded; strips file_path. |
| 50 | `/api/v1/predefined-karts` | GET | `api_v1_data.py:2235` | working | CSV file reader with fallback. |
| 51 | `/api/v1/predefined-tracks` | GET | `api_v1_data.py:2284` | working | CSV file reader with fallback. |
| 52 | `/api/v1/exports` | GET | `api_v1_data.py:2333` | working | Exception-guarded for missing table. |
| 53 | `/api/v1/exports/generate` | POST | `api_v1_data.py:2352` | working | Synchronous export with error handling. |
| 54 | `/api/v1/dev-plans` | GET | `api_v1_data.py:2453` | working | Exception-guarded; returns empty. |
| 55 | `/api/v1/dev-plans/<id>` | GET | `api_v1_data.py:2488` | 500-risk | Imports `development_plan.get_plan` which may not exist (ImportError caught, but other exceptions expose raw str(exc) in response). |
| 56 | `/api/v1/sessions/<id>/visualize` | GET | `api_v1_data.py:2542` | working | Full lap GPS + GG data. |
| 57 | `/api/v1/sessions` | GET | `api_v1_data.py:2603` | working | Session list for pickers. |
| 58 | `/api/v1/compare/sessions` | GET | `api_v1_data.py:2624` | working | Side-by-side comparison. 404 guarded. |
| 59 | `/api/v1/compare/drivers` | GET | `api_v1_data.py:2680` | working | Side-by-side driver comparison. 404 guarded. |
| 60 | `/api/v1/analytics/trends` | GET | `api_v1_data.py:2735` | working | Date-filtered trends. |
| 61 | `/api/v1/analytics/weather` | GET | `api_v1_data.py:2769` | working | Weather-performance correlation. |
| 62 | `/api/v1/analytics/meteo` | GET | `api_v1_data.py:2792` | working | Meteo correlation with summary. |
| 63 | `/api/v1/analytics/predict-pace` | GET | `api_v1_data.py:2834` | working | Pace prediction with confidence. |
| 64 | `/api/v1/drivers/<id>/progression` | GET | `api_v1_data.py:2882` | working | With session-based fallback. |
| 65 | `/api/v1/drivers/<id>/tracks` | GET | `api_v1_data.py:2934` | working | Track list for driver. |
| 66 | `/api/v1/karts/<id>/sessions` | GET | `api_v1_data.py:2956` | working | Via junction table. 404 guarded. |
| 67 | `/api/v1/weekends` | POST | `api_v1_data.py:2989` | 500-risk | Dual SQL syntax: PG uses `%s` positional, SQLite uses `?`. The PG branch uses raw `%s` instead of `%(name)s` which bypasses `sql_compat` translation. |
| 68 | `/api/v1/weekends/<id>/sessions` | GET | `api_v1_data.py:3027` | working | With session order. 404 guarded. |
| 69 | `/api/v1/sessions/<id>/lap-distribution` | GET | `api_v1_data.py:3061` | working | Histogram with bins/counts. Empty guard. |
| 70 | `/api/v1/sessions/<id>/lap-overlay` | GET | `api_v1_data.py:3094` | working | Top 5 laps overlay. Empty guard. |
| 71 | `/api/v1/sessions/<id>/throttle-map` | GET | `api_v1_data.py:3137` | working | Approximated from speed changes. |
| 72 | `/api/v1/sessions/<id>/tyre-data` | GET | `api_v1_data.py:3180` | 500-risk | `best = min(times)` when all `lap_time_s` are 0 causes division by zero in `((t - best) / best) * 100`. |
| 73 | `/api/v1/sessions/<id>/weather` | GET | `api_v1_data.py:3212` | working | Falls back to empty arrays. Uses `translate_params()` for compat. |
| 74 | `/api/v1/sessions/<id>/workload` | GET | `api_v1_data.py:3243` | working | Derived from speed intensity. `best_lap_number` may not exist. |
| 75 | `/api/v1/sessions/<id>/stints` | GET | `api_v1_data.py:3290` | working | Wrapper over `get_stint_analysis()`. |
| 76 | `/api/v1/sessions/<id>/trends` | GET | `api_v1_data.py:3317` | working | Pace delta and rolling consistency. |

### 1B. Billing Endpoints (`api_v1_billing.py`)

| # | Route | Method | Handler | Status | Issue |
|---|-------|--------|---------|--------|-------|
| 77 | `/api/v1/billing/subscription` | GET | `api_v1_billing.py:99` | working | Cached, with Stripe live fetch. Auth guarded. |
| 78 | `/api/v1/billing/invoices` | GET | `api_v1_billing.py:190` | working | Stripe paginated fetch. Returns empty on error. |
| 79 | `/api/v1/billing/usage` | GET | `api_v1_billing.py:253` | working | Usage from `usage_monthly` table with entitlements. |
| 80 | `/api/v1/billing/portal` | POST | `api_v1_billing.py:334` | working | Stripe portal session creation. Error guarded. |

### 1C. Race Strategy Endpoints (`api_v1_race_strategy.py`)

| # | Route | Method | Handler | Status | Issue |
|---|-------|--------|---------|--------|-------|
| 81 | `/api/v1/race-strategy/` | GET | `api_v1_race_strategy.py:70` | working | PG-only. Exception guarded. |
| 82 | `/api/v1/race-strategy/` | POST | `api_v1_race_strategy.py:91` | working | PG-only. Validation on body. |
| 83 | `/api/v1/race-strategy/<id>` | GET | `api_v1_race_strategy.py:123` | working | 404 guarded. |
| 84 | `/api/v1/race-strategy/<id>` | PUT | `api_v1_race_strategy.py:147` | working | Status-gated updates. |
| 85 | `/api/v1/race-strategy/<id>` | DELETE | `api_v1_race_strategy.py:187` | working | 404 guarded. |
| 86 | `/api/v1/race-strategy/<id>/optimize` | POST | `api_v1_race_strategy.py:211` | working | Error guarded. |
| 87 | `/api/v1/race-strategy/<id>/go-live` | POST | `api_v1_race_strategy.py:236` | working | Status validation. |
| 88 | `/api/v1/race-strategy/<id>/finish` | POST | `api_v1_race_strategy.py:264` | working | |
| 89 | `/api/v1/race-strategy/<id>/state` | GET | `api_v1_race_strategy.py:292` | working | For 2s polling. 404 guarded. |
| 90 | `/api/v1/race-strategy/<id>/end-stint` | POST | `api_v1_race_strategy.py:316` | working | Optional JSON body. |
| 91 | `/api/v1/race-strategy/<id>/toggle-fuel` | POST | `api_v1_race_strategy.py:354` | working | Validates `stint_order`. |
| 92 | `/api/v1/race-strategy/<id>/set-pit-type` | POST | `api_v1_race_strategy.py:393` | working | Validates `stint_order` + `pit_type`. |
| 93 | `/api/v1/race-strategy/<id>/reoptimize` | POST | `api_v1_race_strategy.py:440` | working | Mid-race re-optimization. |
| 94 | `/api/v1/race-strategy/<id>/export` | GET | `api_v1_race_strategy.py:467` | working | JSON export. 404 guarded. |
| 95 | `/api/v1/race-strategy/import` | POST | `api_v1_race_strategy.py:491` | working | JSON body or multipart file. ValueError caught. |
| 96 | `/api/v1/race-strategy/<id>/duplicate` | POST | `api_v1_race_strategy.py:544` | working | Clone config. 404 guarded. |
| 97 | `/api/v1/race-strategy/<id>/summary` | GET | `api_v1_race_strategy.py:568` | working | Post-race summary. 404 guarded. |

### 1D. Ingest Endpoints (`api_v1_ingest.py`)

| # | Route | Method | Handler | Status | Issue |
|---|-------|--------|---------|--------|-------|
| 98 | `/api/v1/ingest/start` | POST | `api_v1_ingest.py:10` | working | Alias to `analysis._analyze_start_impl()`. |
| 99 | `/api/v1/ingest/status/<job_id>` | GET | `api_v1_ingest.py:16` | working | Alias to `analysis._analyze_status_impl()`. |

### 1E. Support Endpoints (`api_v1_support.py`)

| # | Route | Method | Handler | Status | Issue |
|---|-------|--------|---------|--------|-------|
| 100 | `/api/v1/support/ticket` | POST | `api_v1_support.py:50` | 500-risk | Imports `from sqlalchemy import text` -- will fail if sqlalchemy not installed (not in requirements.txt). Also imports `auth.email._send` which requires resend (Docker-only). |
| 101 | `/api/v1/support/tickets` | GET | `api_v1_support.py:177` | 500-risk | Same sqlalchemy import issue. Also `created_at.isoformat()` will fail if `created_at` is a string rather than datetime. |

### 1F. Account Endpoints (`api_v1_account.py`)

| # | Route | Method | Handler | Status | Issue |
|---|-------|--------|---------|--------|-------|
| 102 | `/api/v1/account/profile` | GET/PUT | `api_v1_account.py` | working | PG-only. Auth guarded. |
| 103 | `/api/v1/account/change-password` | POST | `api_v1_account.py` | working | Argon2 verification. |
| 104 | `/api/v1/account/2fa/setup` | POST | `api_v1_account.py` | working | TOTP setup. |
| 105 | `/api/v1/account/2fa/confirm` | POST | `api_v1_account.py` | working | TOTP confirmation. |
| 106 | `/api/v1/account/2fa/disable` | POST | `api_v1_account.py` | working | TOTP disable. |
| 107 | `/api/v1/account/2fa/backup-codes` | POST | `api_v1_account.py` | working | Regenerate backup codes. |
| 108 | `/api/v1/account/sessions` | GET | `api_v1_account.py` | working | Active sessions list. |
| 109 | `/api/v1/account/sessions/<id>` | DELETE | `api_v1_account.py` | working | Revoke session. |
| 110 | `/api/v1/account/sessions/revoke-all` | POST | `api_v1_account.py` | working | Revoke all sessions. |
| 111 | `/api/v1/account/connections` | GET | `api_v1_account.py` | working | OAuth connections. |
| 112 | `/api/v1/account/connections/<provider>` | DELETE | `api_v1_account.py` | working | Unlink OAuth. |
| 113 | `/api/v1/account/data-summary` | GET | `api_v1_account.py` | working | GDPR data summary. |
| 114 | `/api/v1/account/export` | POST | `api_v1_account.py` | working | GDPR data export. |
| 115 | `/api/v1/account/` | DELETE | `api_v1_account.py` | working | Account deletion. |
| 116 | `/api/v1/account/data/retention-schedule` | GET | `api_v1_account.py` | working | Data retention schedule. |
| 117 | `/api/v1/account/data/delete-sessions` | POST | `api_v1_account.py` | working | Two-step session deletion. |
| 118 | `/api/v1/account/usage` | GET | `api_v1_account.py` | working | Usage summary. |
| 119 | `/api/v1/account/entitlements` | GET | `api_v1_account.py` | working | Entitlement snapshot. |
| 120 | `/api/v1/account/terms` | GET/POST | `api_v1_account.py` | working | Terms acceptance. |
| 121 | `/api/v1/account/activity` | GET | `api_v1_account.py` | working | Login activity. |
| 122 | `/api/v1/account/preferences` | GET/PUT | `api_v1_account.py` | working | User preferences. |

### 1G. Auth Endpoints (`auth.py`)

| # | Route | Method | Handler | Status | Issue |
|---|-------|--------|---------|--------|-------|
| 123 | `/auth/register` | POST | `auth.py` | working | PG-only guard. Argon2. |
| 124 | `/auth/login` | POST | `auth.py` | working | With suspension check, anomaly detection. |
| 125 | `/auth/logout` | POST | `auth.py` | working | Clears refresh cookie. |
| 126 | `/auth/refresh` | POST | `auth.py` | working | Single-use rotation. httpOnly cookie. |
| 127 | `/auth/oauth/google` | GET | `auth.py` | working | OIDC redirect. |
| 128 | `/auth/oauth/github` | GET | `auth.py` | working | GitHub redirect. |
| 129 | `/auth/oauth/google/callback` | GET | `auth.py` | working | Callback handler. |
| 130 | `/auth/oauth/github/callback` | GET | `auth.py` | working | Callback handler. |

---

## Section 2: Telemetry File Compatibility

All 15 files are RaceChrono Pro v9.1.3 Format 2 (dynamic columns) with identical 44-column headers.

| File | Lines | Size | Columns | Parser Compatible | Risk | Notes |
|------|-------|------|---------|-------------------|------|-------|
| CKS_FP+Q.csv | 452,692 | 125 MB | 44 | Yes | Low | Standard RaceChrono Format 2. 10 metadata lines + header + data. |
| CKS_R1.csv | 333,598 | 91 MB | 44 | Yes | Low | Same format as above. |
| CKS_R2.csv | 358,876 | 98 MB | 44 | Yes | Low | Same format. |
| JV_FP+Q.csv | 499,873 | 137 MB | 44 | Yes | Low | Same format. Different track (Jovikart). |
| JV_R1.csv | 448,583 | 123 MB | 44 | Yes | Low | Same format. |
| JV_R2.csv | 330,266 | 90 MB | 44 | Yes | Low | Same format. |
| MKR_Q.csv | 263,079 | 72 MB | 44 | Yes | Low | Same format. Track: MK Racing Cholet. |
| MKR_R.csv | 2,362,230 | 659 MB | 44 | Yes | Medium | **Largest file** (659 MB, 2.3M lines). Streaming pipeline handles this, but legacy path would OOM. Memory budget: ~64 MB/chunk with INGEST_V2. Processing time: significant. |
| OK_FP+Q.csv | 218,985 | 60 MB | 44 | Yes | Low | Track: Ouest Karting. |
| OK_R1.csv | 235,639 | 65 MB | 44 | Yes | Low | Same format. |
| OK_R2.csv | 423,482 | 116 MB | 44 | Yes | Low | Same format. |
| OK_R3.csv | 201,886 | 55 MB | 44 | Yes | Low | Same format. |
| OK_R4.csv | 211,013 | 58 MB | 44 | Yes | Low | Same format. |
| SLK_FP.csv | 270,691 | 74 MB | 44 | Yes | Low | Track: Grand Circuit de Solokart. |
| TEST_TEST.csv | 25 | 5 KB | 44 | Yes | Medium | **Only 25 lines** (~15 data rows). Parser compatible but pipeline stages may fail: corner detection needs sufficient points, lap splitting needs multiple laps, resampling needs density. Many analysis features will return empty/null. Header has trailing commas on metadata lines (padded to 44 cols). |

**Common header columns (all 15 files):**
`Time (s), Session fragment #, Lap #, Trap name, X-position (m), Y-position (m), Distance (m), Speed (m/s), Altitude (m), Bearing (deg), Device update rate (Hz), Elapsed time (s), Latitude (deg), Longitude (deg), Device battery level (%), Satellites (sats), Fix type, Accuracy (m), Speed (m/s) *calc, Lateral acceleration (G) *calc, Longitudinal acceleration (G) *calc, Device update rate (Hz) *calc, Lean angle (deg) *calc` + 21 additional OBD/sensor channels.

**Parser notes:**
- All files use RaceChrono Format 2 with 10 metadata lines before the header.
- `io_racechrono.py` header detection (`_read_header_columns()`) handles skipping metadata lines.
- Streaming pipeline (`INGEST_V2`) handles all sizes. Feature flag defaults ON.
- No RaceBox or non-RaceChrono files present; no CSV dialect variation across the corpus.
- No files with semicolon delimiters, UTF-16 encoding, or non-standard line endings.

---

## Section 3: Frontend-to-Backend API Dependency Map

| Frontend Page | API Endpoints Called | Backend Status | Gap |
|---------------|---------------------|----------------|-----|
| `/app/dashboard` | `GET /dashboard/stats` | working | None |
| `/app/sessions` | `GET /sessions/browse?...` | 500-risk (ILIKE) | SQLite mode breaks on ILIKE |
| `/app/sessions/[id]` | `GET /sessions/{id}/details`, `GET /sessions/{id}/laps`, `GET /sessions/{id}/fingerprint`, `GET /sessions/{id}/badges`, `GET /sessions/{id}/corner-coaching`, `GET /sessions/{id}/theoretical`, `GET /sessions/{id}/stints` | working / 500-risk (badges) | `badges` endpoint may fail if `driver_badges` table missing |
| `/app/sessions/[id]` (charts) | `GET /sessions/{id}/corner-mastery`, `GET /sessions/{id}/brake-points`, `GET /sessions/{id}/consistency`, `GET /sessions/{id}/comparison-matrix`, `GET /sessions/{id}/lap-distribution`, `GET /sessions/{id}/gg-data`, `GET /sessions/{id}/speed-trace`, `GET /sessions/{id}/speed-profile`, `GET /sessions/{id}/lap-overlay`, `GET /sessions/{id}/throttle-map`, `GET /sessions/{id}/tyre-data`, `GET /sessions/{id}/weather`, `GET /sessions/{id}/workload`, `GET /sessions/{id}/fatigue`, `GET /sessions/{id}/energy`, `GET /sessions/{id}/trends`, `GET /sessions/{id}/style`, `GET /sessions/{id}/gps-trace` | mixed | `consistency` returns synthetic data; `energy` has unit mismatch; `tyre-data` has div-by-zero risk |
| `/app/sessions/[id]` (charts) | `GET /sessions/{id}/pit-window` | **missing** | **No v1 endpoint exists.** Legacy `api_data.py` has `/session/{id}/pit-window` (no `/api/v1/` prefix). Frontend fetches from `/api/v1/sessions/{id}/pit-window` -- 404. |
| `/app/sessions/[id]` (charts) | `GET /sessions/{id}/rival-gap` | **missing** | **No v1 endpoint exists.** Frontend `RivalChart.tsx` calls `/api/v1/sessions/{id}/rival-gap` -- 404. |
| `/app/drivers` | `GET /drivers` | working | None |
| `/app/drivers/[id]` | `GET /drivers/{id}`, `GET /drivers/{id}/sessions`, `GET /drivers/{id}/tracks` | working | None |
| `/app/drivers/[id]/progression` | `GET /drivers/{id}/progression?track_id=...`, `GET /drivers/{id}/tracks` | working | None |
| `/app/tracks` | `GET /tracks` | working | None |
| `/app/tracks/[id]` | `GET /tracks/{id}`, `GET /tracks/{id}/leaderboard`, `GET /tracks/{id}/evolution`, `GET /tracks/{id}/geometry`, `GET /tracks/{id}/records` | working | None |
| `/app/tracks/[id]/evolution` | `GET /tracks/{id}/evolution` | working | None |
| `/app/karts` | `GET /karts` | working | None |
| `/app/karts/[id]` | `GET /karts/{id}`, `GET /karts/{id}/sessions` | working | None |
| `/app/karts/new` | `GET /predefined-karts`, `POST /karts` | working | None |
| `/app/weekends` | `GET /weekends` | working | None |
| `/app/weekends/[id]` | `GET /weekends/{id}`, `GET /weekends/{id}/sessions` | working | None |
| `/app/weekends/new` | `GET /tracks`, `POST /weekends` | 500-risk | POST uses raw `%s` SQL on PG path |
| `/app/compare/sessions` | `GET /sessions`, `GET /compare/sessions?a=...&b=...` | working | None |
| `/app/compare/drivers` | `GET /drivers`, `GET /compare/drivers?a=...&b=...` | working | None |
| `/app/visualize/[id]` | `GET /sessions/{id}/visualize` | working | None |
| `/app/visualize` | `GET /sessions/recent?limit=50` | working | None |
| `/app/analyze` | `GET /files`, `GET /drivers`, `GET /tracks`, `GET /karts` | working | None |
| `/app/exports` | `GET /exports`, `POST /exports/generate` | working | None |
| `/app/leaderboard` | `GET /tracks`, `GET /tracks/{id}/leaderboard` | working | None |
| `/app/jobs` | `GET /jobs?limit=50`, `POST /jobs/{id}/cancel`, `POST /jobs/{id}/retry` | untested | Jobs routes exist in `jobs.py` but no v1 prefix wrappers verified |
| `/app/annotations` | `GET /annotations` | working | None |
| `/app/data-health` | `GET /data-health/stats`, `GET /data-health/jobs` | working | None |
| `/app/data-health/[id]` | `GET /data-health/jobs/{id}` | **missing** | **No endpoint for individual job detail.** Frontend `data-health/[id]/page.tsx` calls `GET /data-health/jobs/{id}` -- 404. |
| `/app/dev-plans` | `GET /dev-plans` | working | None |
| `/app/dev-plans/[id]` | `GET /dev-plans/{id}` | 500-risk | `development_plan` module may not exist |
| `/app/analytics/trends` | `GET /analytics/trends?from=...&to=...` | working | None |
| `/app/analytics/weather` | `GET /analytics/weather` | working | None |
| `/app/analytics/meteo` | `GET /analytics/meteo` | working | None |
| `/app/analytics/pace-predictor` | `GET /tracks`, `GET /analytics/predict-pace?track_id=...` | working | None |
| `/app/race-strategy` | `GET /race-strategy/` | working | PG-only |
| `/app/race-strategy/new` | `POST /race-strategy/` | working | PG-only |
| `/app/race-strategy/[id]` | `GET /race-strategy/{id}`, `POST .../optimize`, `POST .../go-live`, `POST .../duplicate`, `DELETE /race-strategy/{id}` | working | PG-only |
| `/app/race-strategy/[id]/edit` | `GET /race-strategy/{id}`, `PUT /race-strategy/{id}` | working | PG-only |
| `/app/race-strategy/[id]/live` | `GET /race-strategy/{id}/state`, `POST .../end-stint`, `POST .../reoptimize`, `POST .../finish` | working | PG-only |
| `/app/race-strategy/[id]/summary` | `GET /race-strategy/{id}/summary`, `POST .../duplicate` | working | PG-only |
| `/app/account/profile` | `GET /me`, `PUT /account/profile` | working | PG-only |
| `/app/account/security` | `GET /me`, `GET /account/sessions`, `GET /account/connections`, `POST /account/change-password`, `POST /account/2fa/*`, `DELETE /account/sessions/*`, `DELETE /account/connections/*` | working | PG-only |
| `/app/account/billing` | `GET /billing/subscription`, `GET /billing/invoices`, `POST /billing/portal` | working | PG-only |
| `/app/account/usage` | `GET /account/usage`, `GET /account/entitlements` | working | PG-only |
| `/app/account/data` | `GET /account/data-summary`, `GET /account/data/retention-schedule`, `POST /account/export`, `POST /account/data/delete-sessions`, `DELETE /account/` | working | PG-only |
| `/app/account/support` | `GET /support/tickets`, `POST /support/ticket` | 500-risk | sqlalchemy + resend imports |
| `/app/setup-tracker` | `GET /setup/status` | **missing** | **No `/api/v1/setup/status` endpoint exists.** Frontend `setup-tracker/page.tsx` calls it -- 404. |
| `/app/admin/*` | `GET /admin/metrics`, `GET /admin/billing/overview`, `GET /admin/users`, etc. | working | Admin routes exist in `routes/admin/`. |
| `(free-report)/free-report/report/[id]` | `GET /sessions/{id}/details`, `GET /sessions/{id}/laps`, `GET /sessions/{id}/corners` | **missing** | **No `/api/v1/sessions/{id}/corners` endpoint exists.** Frontend expects `{corners: CornerSummary[]}` -- 404. |
| Corner Replay component | `GET /sessions/{id}/corner-replay?corner={n}&lap={n}` | **missing** | **No v1 endpoint.** Legacy `api_data.py` has `/session/{id}/corner-replay-data` (different path + prefix). Frontend `CornerReplay.tsx` calls `/api/v1/sessions/{id}/corner-replay` -- 404. |

---

## Section 4: Subscription Tier / Entitlement Matrix

### Pure-Python Entitlements (`PLAN_ENTITLEMENTS` in `auth/entitlements.py`)

| Feature | demo/free | racer | world_class | Gate Type |
|---------|-----------|-------|-------------|-----------|
| `reports_per_month` | 1 | 10 | -1 (unlimited) | Quota |
| `uploads_per_month` | 1 | 10 | -1 (unlimited) | Quota |
| `raw_retention_days` | 30 | 90 | 365 | Limit |
| `comparison_progress` | No | No | Yes | Feature |
| `coaching_drills` | No | Yes | Yes | Feature |
| `viz_workspace` | No | Yes | Yes | Feature |
| `strategy_dashboard` | 3h limit | Full | Full | Feature |
| `live_pace` | No | Yes | Yes | Feature |
| `pit_planning` | No | Yes | Yes | Feature |
| `pdf_reports` | No | Yes | Yes | Feature |
| `api_access` | No | No | Yes | Feature |
| `track_management` | Basic | Full | Full | Feature |
| `max_workspace_members` | 1 | 1 | 5 | Limit |

### Middleware Feature Gates (`_FEATURE_GATES` in `web/middleware/entitlements.py`)

| HTTP Method | Path Prefix | Feature Key | Enforced For |
|-------------|-------------|-------------|--------------|
| GET | `/compare/` | `comparison` | World-Class only |
| GET | `/api/v1/comparisons/` | `comparison` | World-Class only |
| GET | `/visualize/` | `visualization` | Racer+ |
| POST | `/race-strategy/` | `race_strategy` | Racer+ (mutations) |
| POST | `/api/v1/race-strategy/` | `race_strategy` | Racer+ (mutations) |
| PUT | `/api/v1/race-strategy/` | `race_strategy` | Racer+ (mutations) |
| DELETE | `/api/v1/race-strategy/` | `race_strategy` | Racer+ (mutations) |
| GET | `/api/v1/data/` | `api_access` | World-Class only |
| POST | `/api/data/export/` | `exports` | Racer+ |
| POST | `/api/v1/exports/` | `exports` | Racer+ |
| POST | `/api/data/simulate-race` | `race_strategy` | Racer+ |
| POST | `/api/data/what-if` | `race_strategy` | Racer+ |
| POST | `/api/data/weight-simulation` | `race_strategy` | Racer+ |
| POST | `/api/data/weight-scenarios` | `race_strategy` | Racer+ |

### Middleware Quota Gates (`_QUOTA_GATES`)

| HTTP Method | Path Prefix | Meter Key | Cost |
|-------------|-------------|-----------|------|
| POST | `/analyze/api/start` | reports | 1 |
| POST | `/analyze/sync` | reports | 1 |
| POST | `/api/v1/batch-reanalyze` | reports | 1 |
| POST | `/api/data/files/upload` | uploads | 1 |
| POST | `/api/v1/ingest/start` | uploads | 1 |

### Entitlement Gaps

1. **Race strategy READ not gated:** `GET /api/v1/race-strategy/` and `GET /api/v1/race-strategy/<id>` are not in `_FEATURE_GATES` -- demo users can **read** race strategy data but not mutate it. May be intentional but inconsistent with visualization gate which blocks all GETs.
2. **Comparison gate path mismatch:** Frontend calls `GET /api/v1/compare/sessions?a=...&b=...` but the feature gate checks `/compare/` (no `api/v1` prefix) and `/api/v1/comparisons/` (different path). The actual v1 route at `/api/v1/compare/sessions` is **NOT gated** -- all tiers can compare.
3. **Visualization gate only checks `/visualize/`:** Frontend calls `GET /api/v1/sessions/{id}/visualize` which does **not** match the gate prefix `/visualize/`. This endpoint is **NOT gated** by tier.
4. **Export quota mismatch:** `POST /api/v1/exports/generate` is the frontend path but the quota gate checks `/api/v1/exports/` which is a prefix match -- this works. However the feature gate also checks `/api/v1/exports/` for POST which blocks demo users from generating any export. This is correct.
5. **`api_access` gate overly broad:** Gate checks `GET /api/v1/data/` but all session endpoints are at `GET /api/v1/sessions/` which does **not** match. The `api_access` gate is effectively never triggered for session data endpoints. Only `GET /api/v1/data/*` paths (which don't exist in `api_v1_data.py` as it uses `/api/v1/sessions/`) are gated.
6. **No upload quota on v1 file upload:** `POST /api/v1/files/upload` is the actual file upload route but the quota gate checks `/api/data/files/upload` (legacy path). The v1 upload path is **NOT quota-gated**.

---

## Section 5: Canvas/Chart Fragility Catalog

All chart components use `useInteractiveCanvas` hook from `src/hooks/useInteractiveCanvas.ts`. The hook itself is safe -- it handles missing canvas/ctx gracefully and uses ResizeObserver for responsive sizing.

| Chart Component | Empty Guard | Div/Zero Guard | Radius Guard | Extreme Guard | Null Guard | Risk Level |
|-----------------|-------------|----------------|--------------|---------------|------------|------------|
| `SpeedTrace.tsx` | Yes (`distances.length === 0`) | Yes (range derived from data) | N/A | Yes (clamped by plot area) | No explicit null filtering | Low |
| `SpeedProfile.tsx` | Yes (`distances.length === 0`) | Yes | N/A | Yes | No null filtering on speed arrays | Low |
| `LapProgress.tsx` | Yes (`laps.length === 0`) | Yes (max guarded) | N/A | Yes | Yes (filters `lap_time_s != null`) | Low |
| `GGDiagram.tsx` | Yes (`lat_g.length === 0`) | Yes (`maxG` floored at 0.5) | Yes (circle radius from `Math.min`) | Yes (clamped) | Yes (NaN/Inf cleaned by backend `_clean_accel`) | Low |
| `Fingerprint.tsx` | Yes (`metrics.length === 0`) | Yes (`max` guarded) | Yes (radius from `Math.min(cx,cy) - 20`) | Yes (`Math.max(0, Math.min(1, val))` clamp) | No | Low |
| `DrivingStyle.tsx` | Yes (`labels.length === 0`) | No explicit | Yes (`Math.min(cx,cy) - 30`, but negative possible if container < 60px) | Yes (`Math.max(0, Math.min(1, val))`) | No | Medium |
| `SectorChart.tsx` | Yes (`sectors.length === 0`) | Yes (maxVal guarded) | N/A | Yes | No | Low |
| `BrakeScatter.tsx` | Yes (`distances.length === 0`) | Yes (stats computed safely) | N/A | Yes (plot area clamped) | No null filtering on pressures array | Low |
| `ConsistencyHeatmap.tsx` | Yes (`laps.length === 0`) | Yes | N/A | Yes (color clamped) | Yes (`??` operator on cell values) | Low |
| `EnergyBalance.tsx` | Yes (`distances.length === 0`) | No explicit | N/A | No (KE can be very large) | No null filtering | Medium |
| `FatigueChart.tsx` | Yes (`laps.length === 0`) | No explicit | N/A | No (fatigue index unbounded) | No | Medium |
| `WorkloadChart.tsx` | Yes (`timestamps.length === 0`) | No explicit | N/A | No | No | Medium |
| `WeatherChart.tsx` | Yes (`timestamps.length === 0`) | No explicit | N/A | No | No | Medium |
| `LapDistribution.tsx` | Yes (`bins.length === 0`) | Yes (barWidth from range) | N/A | Yes | No | Low |
| `LapOverlay.tsx` | Yes (`distances.length === 0 \|\| laps.length === 0`) | Yes | N/A | Yes | No | Low |
| `ThrottleHeatmap.tsx` | Yes (`distances.length === 0 \|\| laps.length === 0`) | No explicit | N/A | Yes (color clamped 0-1) | Yes (`??` on cells) | Low |
| `TyreChart.tsx` | Yes (`laps.length === 0`) | No explicit | N/A | No (deg can be very large) | No | Medium |
| `CornerMastery.tsx` | Yes (`corners.length === 0`) | No explicit | N/A | Yes (bar heights from max) | No | Low |
| `ComparisonMatrix.tsx` | Yes (`metrics.length === 0 \|\| laps.length === 0`) | No explicit | N/A | No (cell values unbounded) | Yes (`??` on row values) | Medium |
| `StintChart.tsx` | Yes (`stints.length === 0`) | Yes (maxTime guarded) | N/A | Yes | No | Low |
| `TrendChart.tsx` | Yes (`distances.length === 0`) | No explicit | N/A | No (pace_delta unbounded) | No | Medium |
| `TrackMap.tsx` | Yes (`lat.length < 2`) | Yes (bounds computed safely) | N/A | Yes (coordinate clamped to plot area) | No | Low |
| `PitWindowChart.tsx` | Yes (`laps.length === 0`) | No explicit | N/A | No | No | Medium |
| `RivalChart.tsx` | Yes (`laps.length === 0`) | No explicit | N/A | No | No | Medium |
| `Sparkline.tsx` | Yes (`data.length === 0`) | Yes (range guarded) | N/A | Yes | No | Low |

### Risk explanation

- **Low:** Has empty data guard + no known path to crash (div-by-zero, negative radius, etc.)
- **Medium:** Has empty data guard but **no div-by-zero or extreme value guard** -- large or NaN values from the backend could cause visual artifacts, enormous canvas draws, or NaN propagation into coordinates resulting in invisible/misplaced elements. Backend is the primary defense line.
- **High:** Would be assigned if a component lacked an empty guard. **No chart component currently has High risk** -- all guard against empty data arrays.

### `useInteractiveCanvas.ts` Hook Assessment

The hook itself is **safe and well-structured:**
- Handles missing `canvas`/`ctx` (early return)
- Uses `ResizeObserver` for responsive sizing
- Normalizes hover coordinates to 0-1 range
- Crosshair rendering is guarded by padding bounds
- No division by zero possible (uses subtraction for plotW/plotH)
- **One concern:** `plotW` or `plotH` could be 0 if container has 0 size, making `nx`/`ny` calculations produce `NaN` via `(x - pad.left) / 0`. This propagates to tooltip positioning but does not crash.

---

## Section 6: Summary Statistics

### Backend Routes

| Status | Count | Details |
|--------|-------|---------|
| **working** | 104 | Routes that return correct data in expected shape with proper error handling |
| **500-risk** | 14 | Routes with unguarded operations: div-by-zero (`fatigue`, `tyre-data`), empty array access (`speed-profile`), SQLite/PG incompatibility (`sessions/browse`, `weekends POST`, `karts/{id}`), missing tables (`badges`, `corner-coaching`), missing imports (`support`, `dev-plans`) |
| **wrong-shape** | 1 | `consistency` returns synthetic heatmap data (hash-based, not real sector times) |
| **missing** | 5 | `pit-window`, `rival-gap`, `corners`, `corner-replay`, `setup/status` -- frontend pages exist but no v1 API endpoint |
| **untested** | 6 | `jobs`, `weekends POST`, several admin endpoints (test files exist but no route-level integration tests for these specific flows) |
| **TOTAL** | 130 | |

### Telemetry Files

| Status | Count | Details |
|--------|-------|---------|
| **Compatible** | 15 | All files are RaceChrono Pro v9.1.3 Format 2, 44 columns |
| **At-risk** | 2 | `MKR_R.csv` (659 MB, streaming-only safe), `TEST_TEST.csv` (25 lines, pipeline stages may return empty/null) |
| **Incompatible** | 0 | None in current corpus |

### Charts

| Risk Level | Count | Details |
|------------|-------|---------|
| **Low (fully guarded)** | 16 | `SpeedTrace`, `SpeedProfile`, `LapProgress`, `GGDiagram`, `Fingerprint`, `SectorChart`, `BrakeScatter`, `ConsistencyHeatmap`, `LapDistribution`, `LapOverlay`, `ThrottleHeatmap`, `CornerMastery`, `StintChart`, `TrackMap`, `Sparkline`, `LapOverlay` |
| **Medium (partially guarded)** | 10 | `DrivingStyle`, `EnergyBalance`, `FatigueChart`, `WorkloadChart`, `WeatherChart`, `TyreChart`, `ComparisonMatrix`, `TrendChart`, `PitWindowChart`, `RivalChart` -- all have empty guards but no div-by-zero or extreme-value guards |
| **High (unguarded)** | 0 | None |

### Entitlement Gaps

| Gap | Severity | Description |
|-----|----------|-------------|
| Comparison gate path mismatch | P1 | `/api/v1/compare/sessions` not gated -- all tiers can compare |
| Visualization gate path mismatch | P1 | `/api/v1/sessions/{id}/visualize` not gated -- all tiers can visualize |
| Upload quota not enforced on v1 path | P1 | `POST /api/v1/files/upload` bypasses quota gate (wrong path prefix) |
| `api_access` gate never triggers | P2 | Gate checks `/api/v1/data/` but routes use `/api/v1/sessions/` |
| Race strategy reads ungated | P3 | Demo users can read (but not mutate) race strategy data |
| **Total entitlement gaps** | **5** | 3 at P1, 1 at P2, 1 at P3 |

### Missing Endpoint Summary

| Frontend Path | Expected v1 Endpoint | Status |
|---------------|---------------------|--------|
| Session detail charts | `GET /api/v1/sessions/{id}/pit-window` | NOT IMPLEMENTED |
| Session detail charts | `GET /api/v1/sessions/{id}/rival-gap` | NOT IMPLEMENTED |
| Free report page | `GET /api/v1/sessions/{id}/corners` | NOT IMPLEMENTED |
| Corner replay component | `GET /api/v1/sessions/{id}/corner-replay?corner=N&lap=N` | NOT IMPLEMENTED |
| Setup tracker page | `GET /api/v1/setup/status` | NOT IMPLEMENTED |
| Data health detail | `GET /api/v1/data-health/jobs/{id}` | NOT IMPLEMENTED |
