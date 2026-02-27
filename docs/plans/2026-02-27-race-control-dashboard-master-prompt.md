# Master Prompt — Race Control Developer/Webmaster Dashboard (Version-Clash Safe)

Use this prompt when running multiple AI agents in parallel on the Lap Coach codebase.

---

## PROMPT

You are an elite **SaaS Observability & Operations UX** squad.
Your mission is to design and implement a production-grade **Developer/Webmaster dashboard (“Race Control”)** for Lap Coach that monitors, triages, and helps fix issues across:

- Entitlements, authorization, plan enforcement, quotas/credits
- Billing and subscriptions (Stripe)
- Email deliverability and critical flows (Resend)
- Upload + background job pipeline reliability
- Retention lifecycle and deletion obligations
- Security events, auditability, and abuse detection
- Hetzner + Cloudflare infrastructure health

This is not a vanity admin page; it is an **incident-response command center** that reduces MTTR and enables audit-grade operations.

### Context

- Live product: https://www.lap-coach.racing/
- Infra: Hetzner
- DNS/CDN/WAF: Cloudflare
- Billing: Stripe Checkout + Subscriptions
- Email: Resend
- Workload: large telemetry uploads + expensive asynchronous processing

### Non-negotiables

1. No insecure “internal shortcuts.” Privileged surfaces must be hardened.
2. Every metric/state must come from authoritative sources (DB, queue, Stripe events/state, Resend events, infra telemetry).
3. Every admin action must be RBAC-protected and audit-logged.
4. Every card/widget must support drill-down with correlation IDs (`request_id`, `job_id`, `user_id`, `org_id`, `stripe_customer_id`).
5. Environment separation must be strict (dev/staging/prod).

---

## CRITICAL: Parallel-Agent Git Workflow (Prevent Version Clashes)

You are running concurrently with other agents. Follow this exact flow repeatedly to avoid divergence:

1. **Before starting any change**
   - `git fetch origin`
   - `git rebase origin/<target-branch>` (or merge if repo policy requires)
   - Resolve conflicts immediately and rerun tests.

2. **Before every commit**
   - Fetch/rebase again if more than a few minutes elapsed.
   - Verify no overlapping file ownership collisions with other in-flight work.
   - Prefer additive edits and isolated modules to reduce merge pressure.

3. **When a new commit is pushed by another agent (mandatory check)**
   - Stop current work at nearest safe point.
   - `git fetch origin`
   - Rebase onto latest target branch.
   - Run fast validation suite; if conflict impacts behavior, rerun full suite for affected areas.
   - Update implementation notes to reflect any changed assumptions.

4. **Conflict-resolution policy**
   - Preserve security and data-integrity invariants first.
   - If two implementations differ, keep the one with:
     - server-side enforcement over client-only checks,
     - idempotent/event-safe behavior,
     - stronger auditability.
   - Document conflict decisions in PR notes.

5. **Pre-PR anti-clash gate (must pass)**
   - Branch rebased on latest target branch with zero conflicts pending.
   - No duplicate migrations or divergent schema versions.
   - No duplicate route names, feature-flag keys, or metric names.
   - Changelog/plan docs updated if behavior changed.

---

## Team Roles (single squad)

- Staff Full-Stack Engineer (admin app + API integration)
- SRE/Observability Engineer (logs, metrics, alerts)
- Security Engineer (RBAC, audit, privileged actions)
- Billing Engineer (Stripe/webhook/reconciliation)
- Data Engineer (job and storage lifecycle)
- QA Automation Lead (E2E + permission tests)
- Product Designer (triage-first UX)

---

## Required Deliverables

### A) Information Architecture + Route Map

Implement secure admin area (e.g. `/admin/race-control`) with modules:

1. **System Health Overview**
2. **Users & Organizations**
3. **Entitlements / Quotas / Credits**
4. **Jobs / Processing Pipeline**
5. **Billing (Stripe)**
6. **Email (Resend)**
7. **Security & Audit**
8. **Infrastructure (Hetzner + Cloudflare)**

### B) System Health Overview (single-screen triage)

Show at-a-glance:

- Service health: web/API/worker/DB/object storage
- Job queue depth, failure rate, retries, DLQ count, p50/p95 durations
- Upload throughput + top failure causes
- Stripe webhook success %, backlog, reconciliation mismatch count
- Resend delivery/bounce/failure rates for critical templates
- Storage and retention: bytes + upcoming deletions (24h/7d)
- Security alerts: login spikes, suspicious IPs, rate-limit bursts

### C) Drill-down Modules (must be actionable)

For each module provide searchable/filterable tables, pagination, CSV export, and saved views.

- **Users/Orgs:** timeline of auth, usage, billing, email, job events
- **Entitlements:** current grants + overrides; quota/meter views; anomaly detection
- **Jobs:** inspect logs/retries/idempotency keys; retry/cancel/requeue (audited)
- **Billing:** webhook viewer with signature + idempotency status; reconciliation + heal actions
- **Email:** delivery diagnostics, per-template health, emergency template disable flag
- **Security:** immutable admin audit trail; denied-action analytics; incident records
- **Infrastructure:** Hetzner resource trends, Cloudflare WAF/rate-limit/origin error stats

### D) Security and Access Control (mandatory)

- Server-side RBAC for every read/write endpoint
- Enforce admin 2FA
- Restrict admin role assignment to allowlisted identity set
- No secrets exposed in UI; mask sensitive tokens
- Optional impersonation only if strictly necessary:
  - explicit activation,
  - time-bound,
  - clearly visible banner,
  - immutable audit record

### E) Data Contracts + Operational Semantics

Produce concrete contracts for:

- Admin API endpoints (inputs/outputs/errors)
- Event schemas (audit, usage, jobs, billing/webhook outcomes)
- Required DB indexes/materialized views for dashboard performance
- Correlation ID propagation from API → worker → logs → dashboard

### F) Alerts + Runbooks

Link alert classes to dashboard entry points:

- job failure spike
- webhook failures/backlog
- email delivery regression
- auth-deny spike
- storage nearing threshold

Runbooks must include first 5 triage steps and safe rollback controls.

### G) Tests (must ship)

- Permission matrix tests per admin role
- E2E incident flows:
  1. find failing job → inspect → retry → confirm recovery
  2. payment failure → locate user → verify Stripe state → refresh entitlements
  3. user blocked → inspect denied action + quota + override → resolve safely
- Reconciliation tests for duplicated/out-of-order Stripe events
- Audit-log assertion tests for all privileged actions

---

## Acceptance Criteria

Dashboard can answer in <60 seconds:

1. Why is this user blocked?
2. Are jobs failing now?
3. Are Stripe webhooks healthy?
4. Are emails being delivered?
5. What telemetry is scheduled for deletion next?

And:

- All admin actions are RBAC-protected + audited.
- All production-critical modules are observable and drillable.
- UI is responsive, stable, and modern-browser compatible.
- Operational burden/support escalations are measurably reduced.

---

## Execution Requirements

1. Start with architecture + schema/API deltas.
2. Build secure backend admin APIs first.
3. Implement UI modules in priority order: Health → Jobs → Billing → Users/Entitlements → Security → Infra → Email.
4. Add tests continuously; do not defer quality gates.
5. Rebase frequently per anti-clash workflow above.
6. Ship with feature flags and staged rollout plan (staging before prod).
