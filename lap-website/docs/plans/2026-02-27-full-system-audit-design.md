# Full-System Audit & Remediation Design

**Date:** 2026-02-27
**Status:** Approved
**Approach:** Security-Out (Approach A)

## System Overview

| Component | Technology | Location |
|-----------|-----------|----------|
| Frontend | Next.js 14, React 18, Tailwind, Three.js/R3F, GSAP | Cloudflare Workers |
| Backend | Flask, Python 3.11, Gunicorn (4 sync workers) | Hetzner VPS (46.225.227.24) |
| Database | PostgreSQL 16 (Docker) | Same VPS |
| Cache/Queue | Redis 7, Celery | Same VPS |
| Payments | Stripe (test mode) | SaaS |
| Auth | JWT HS256, Argon2id, Google/GitHub OAuth | Backend |
| Analytics | Plausible | SaaS |
| DNS | api.lap-coach.racing → Hetzner; www.lap-coach.racing → Cloudflare | |

**Scale:** ~60 frontend pages, ~150 backend routes, 44+ DB tables, 572+ tests, 90+ React components.

**Environment:** Production only (no staging). Fresh database, no real users.

## Severity Rubric

| Level | Criteria | SLA |
|-------|----------|-----|
| P0 | Security breach, data loss/corruption, auth bypass, payment failure, app unusable | Fix immediately, block deployment |
| P1 | Major workflow broken, severe UI breakage, significant performance regression | Fix before any user-facing launch |
| P2 | Functional bug with workaround, notable UX confusion, minor security misconfig | Fix within audit scope |
| P3 | Polish, cosmetic, minor copy, low-risk refactors | Document, schedule for later |

## Acceptance Gates

- Zero P0 issues open
- All P1 issues fixed or explicitly accepted with mitigation
- Web vitals: LCP <= 2.5s, INP <= 200ms, CLS <= 0.1
- OWASP Top 10 critical items mitigated
- All critical user journeys pass e2e tests
- Auth flow works end-to-end (register → verify → login → JWT refresh → logout → OAuth)
- Stripe checkout works in live mode
- Every link/CTA verified functional

## Phase Sequence

### Phase 1: Security Audit & Hardening

**Scope:**
- Threat model: actors, assets, entry points, trust boundaries
- OWASP Top 10: XSS, CSRF, SSRF, SQLi, auth/session, IDOR, misconfig, file upload
- Headers: CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy
- Secrets: JWT secret strength, env var handling, no secrets in repo/logs
- Token storage: localStorage risks, migration plan to httpOnly cookies
- CORS: verify allowed origins
- Rate limiting: connect Redis, verify functional
- Dependencies: pip audit + npm audit
- File upload: size limits, type validation, path traversal
- OAuth: state/nonce, redirect URI, email_verified enforcement

**Deliverables:** Threat model doc, security headers config, dependency report, remediation PRs.

### Phase 2: Database Correctness & Migration Safety

**Scope:**
- Deploy Alembic migrations 001-008
- Add alembic.ini to Docker image
- Verify FK constraints, unique constraints, check constraints
- Add indexes for top query patterns
- Transaction isolation: verify SET LOCAL workspace context
- Backup strategy: pg_dump cron + retention policy
- Query performance: EXPLAIN ANALYZE for hot endpoints
- Migration rollback plan

**Deliverables:** Migration deployment scripts, index additions, backup cron, rollback procedures.

### Phase 3: Backend API Integrity

**Scope:**
- Input validation on all write endpoints
- Error handling: consistent envelope, no stack traces in prod
- Authorization boundary audit: every endpoint
- Idempotency for state-changing operations
- Upload → ingest → analysis pipeline: e2e verification
- Celery task reliability
- API contract verification (frontend ↔ backend)
- Connection management under load

**Deliverables:** Validation schema coverage, permission test suite, API contract tests.

### Phase 4: Reliability & Observability

**Scope:**
- Health check improvements (Redis, Celery status)
- Structured JSON logging with correlation IDs
- Docker Compose production hardening
- Gunicorn config optimization
- Deploy pipeline documentation
- Rollback procedure documentation

**Deliverables:** Health check improvements, logging config, ops runbook.

### Phase 5: Frontend Bug Bash

**Scope:**
- Test every route across Chrome, Firefox, Safari, mobile
- Auth flow: register → verify → login → dashboard → logout
- Free report flow: upload → configure → analyze → view
- App workflows: sessions, tracks, drivers, karts, compare, analytics
- Billing: checkout → subscription → portal → cancel
- Error/empty/loading states
- Link/CTA verification

**Deliverables:** Issue tracker with all findings, golden path journey tests.

### Phase 6: Frontend Quality & Design System

**Scope:**
- Design token audit
- Component consistency
- Responsive testing: 320px → 1440px
- Accessibility: keyboard nav, focus states, contrast, screen reader
- Cross-browser compatibility
- Loading/error/empty state consistency

**Deliverables:** Design system spec, component inventory, refactor PRs.

### Phase 7: Performance

**Scope:**
- Web vitals baseline (Lighthouse)
- Bundle analysis
- Three.js/R3F mobile performance
- Font loading optimization
- Image optimization
- API latency profiling
- Memory leak detection

**Deliverables:** Performance baseline report, optimization PRs, target benchmarks.

### Phase 8: Marketing & Conversion

**Scope:**
- Content pruning table (keep/rewrite/remove per section)
- Page-by-page copy rewrite
- B2C pricing simplification (1-3 plans max)
- B2B restructure: "Book a Call" with simple lead form
- Visual coherence: marketing ↔ app consistency
- Analytics tracking plan
- Conversion funnel metrics

**Deliverables:** Content pruning table, copy deck, pricing spec, B2B page spec, tracking plan.

## Constraints

- Production-only environment (no staging)
- Fresh database: safe for destructive schema changes
- B2B: simple lead form (no calendar integration)
- Sequential phases, each verified before next
- Rollback: git revert + container restart (backend); Cloudflare rollback (frontend)

## Deliverable Summary

| Deliverable | Phase |
|-------------|-------|
| Master audit report | Final |
| Security pack (threat model, headers, deps) | 1 |
| Migration deployment + backup plan | 2 |
| API contract + permission tests | 3 |
| Ops runbook (deploy, rollback, backup) | 4 |
| Issue tracker (all bugs found) | 5 |
| Design system spec | 6 |
| Performance baseline + optimizations | 7 |
| Marketing copy deck + tracking plan | 8 |
| E2e test suite (critical journeys) | 3, 5 |
