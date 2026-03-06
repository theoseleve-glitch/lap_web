# QA Strike Team Design

**Date:** 2026-02-28
**Status:** Approved
**Approach:** Triple-Agent Parallel (Failure Matrix + Backend Fix Catalog + User Journey Map)

---

## Problem Statement

The Lap Coach SaaS platform has comprehensive backend infrastructure (387 routes, 34 blueprints, RLS multi-tenancy, Stripe billing, Celery async processing) and a Next.js frontend (95 pages, 35+ canvas charts) but suffers from:

1. **Active 500 errors** on multiple API endpoints
2. **CORS/OPTIONS preflight failures** blocking frontend-to-backend calls
3. **Chart rendering crashes** (canvas IndexSizeError, negative arc radius, blank charts)
4. **Auth/refresh instability** (token refresh loops, multi-tab issues, unexpected logouts)
5. **Feature parity regression** from old Jinja2 tool to new Next.js app:
   - Lost synchronized properties (graphs, map, speed trace linked interactions)
   - Lost edit/delete/personalize capabilities
   - UX ergonomics degraded
6. **Untested edge cases** across 15 telemetry file formats and 3 subscription tiers

## Prior Work

Extensive prior audits and fixes exist:
- `2026-02-28-verification-audit-design.md` — Traceability matrix with 89 requirements, 10 gaps (9 fixed)
- `2026-02-28-full-repair-design.md` — 17 endpoint fixes + session detail page rebuild
- `2026-02-28-e2e-certification-harness-design.md` — Playwright test framework
- ~2,800 existing tests (145 Python, 22 Playwright, 17 Vitest files)
- Critical gaps G-01 through G-09 resolved

## Design: Triple-Agent Parallel Strategy

Three agents work in parallel. Each produces a comprehensive research document (NO code changes). These documents become the implementation blueprint for subsequent execution sessions.

### Agent A: Failure Matrix Builder

**Output:** `docs/plans/2026-02-28-qa-failure-matrix.md`

**Mission:** Build the complete failure inventory.

Scope:
1. **Backend Route Audit** — Classify every route in `api_v1_data.py`, `api_v1_account.py`, etc. as: `working | 500 | wrong-shape | missing | untested`
2. **Telemetry File Audit** — Test all 15 CSV files from `data/raw/` against the ingestion pipeline. Record which succeed, which fail, and root cause.
3. **Frontend-to-Backend Mapping** — Map every page's API calls to their backend routes. Flag shape mismatches.
4. **Tier/Account Audit** — Cross-reference 3 accounts (demo/racer/world-class) against entitlement gates. Flag authorization gaps.
5. **Canvas/Chart Fragility** — Catalog all known rendering risks (arc radius, division by zero, empty data, extreme values).
6. **Full Traceability Matrix** — Route x Account x File x Expected x Actual Status.

### Agent B: Backend Fix Catalog

**Output:** `docs/plans/2026-02-28-qa-backend-fix-catalog.md`

**Mission:** Document every backend fix needed with exact file:line references.

Scope:
1. **500 Error Analysis** — Read every route handler, identify unguarded operations (empty DataFrame access, division by zero, missing columns, None dereference).
2. **Response Shape Audit** — Compare what each endpoint returns vs what the frontend chart component expects.
3. **CORS Audit** — Analyze `app.py` CORS config, middleware ordering, OPTIONS handling.
4. **Auth Flow Audit** — Trace the complete token lifecycle: login → access token → refresh → silent refresh → multi-tab behavior.
5. **Input Validation Gaps** — Missing schema validation, unvalidated query params, injection vectors.
6. **Priority Catalog** — P0 (500s, CORS, auth) → P1 (shape fixes) → P2 (missing endpoints) → P3 (edge case guards).

### Agent C: User Journey & Feature Parity Map

**Output:** `docs/plans/2026-02-28-qa-user-journey-map.md`

**Mission:** Map what users lost in the transition from old tool to new frontend.

Scope:
1. **Feature Parity Matrix** — Compare old Jinja2 templates (`web/templates/`) against new Next.js pages. Document every missing feature.
2. **6 Critical Journeys:**
   - Upload → Analyze (file selection, progress, pipeline, results)
   - View Session (all 5 tabs: Overview, Corners, Performance, Analytics, Lap Data)
   - Compare Sessions/Drivers (side-by-side, overlay, matrix)
   - Race Strategy (create, optimize, go-live, export)
   - Account/Billing (profile, security, 2FA, billing, data management)
   - Admin/Race Control (users, jobs, billing, entitlements, incidents)
3. **Synchronized Interactions** — Document which graphs/map/traces were linked in old tool.
4. **CRUD Capabilities** — Document edit/delete/personalize features that were in old tool.
5. **UX Regression Catalog** — Premium features that were degraded.

## Execution Phases (Post-Design)

Phase 1: Backend Foundation (500s, CORS, auth, schema fixes)
Phase 2: Frontend Hardening (chart guards, error boundaries, empty data, retry logic)
Phase 3: Feature Parity (synchronized graphs, edit/delete, personalization)
Phase 4: E2E Regression Suite + Production Smoke Tests
Phase 5: Monitoring, Alerting, Structured Logging

## Test Accounts

| Email | Expected Tier | Purpose |
|-------|--------------|---------|
| theos.elive@gmail.com | TBD (map in failure matrix) | Primary test account |
| theo.stipapro@gmail.com | TBD (map in failure matrix) | Secondary test account |
| fsae.ecn@gmail.com | TBD (map in failure matrix) | Tertiary test account |

Password: claudetest (all accounts)

## Telemetry Files (data/raw/)

| File | Lines | Notes |
|------|-------|-------|
| CKS_FP+Q.csv | 452,692 | City Kart Sautron, RaceChrono Pro v9.1.3 |
| CKS_R1.csv | 333,598 | Same track, race 1 |
| CKS_R2.csv | 358,876 | Same track, race 2 |
| JV_FP+Q.csv | 499,873 | Different track |
| JV_R1.csv | 448,583 | Race 1 |
| JV_R2.csv | 330,266 | Race 2 |
| MKR_Q.csv | 263,079 | MK Racing Cholet |
| MKR_R.csv | 2,362,230 | Largest file (2.3M lines) |
| OK_FP+Q.csv | 218,985 | Another track |
| OK_R1-R4.csv | 201-423K | Multiple races |
| SLK_FP.csv | 270,691 | Free practice |
| TEST_TEST.csv | 25 | Minimal test file |

## Success Criteria

- Three comprehensive documents produced covering 100% of routes, files, and features
- Every identified bug has: reproduction path, root cause hypothesis, fix location (file:line), and priority
- Feature parity gaps have: old tool reference, new tool status, and implementation estimate
- Documents are structured for direct execution in implementation sessions
