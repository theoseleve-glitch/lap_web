# Lap Coach SaaS — Entity-Relationship Model

> Authoritative reference for all database entities. Migrations 001–021.

---

## Entity Overview

| Entity | Scope | Migration | Purpose |
|--------|-------|-----------|---------|
| users | global | 001, 002, 019, 020 | User accounts + billing + security |
| refresh_tokens | global | 002, 020 | JWT refresh token rotation |
| oauth_connections | global | 003 | Google/GitHub SSO links |
| teams | global | 004 | Team organizations |
| team_members | global | 004 | User ↔ Team M:N with roles |
| workspaces | global | 004 | Personal/team data containers |
| plan_definitions | global | 019 | Tier limits + feature flags |
| invitations | global | 021 | Team invite tokens |
| password_reset_tokens | global | 020 | Forgot-password flow |
| stripe_events | global | 019 | Webhook deduplication |
| email_log | global | 021 | Transactional email tracking |
| usage_events | workspace (RLS) | 019 | Append-only billable actions |
| usage_monthly | workspace (RLS) | 019 | Pre-aggregated monthly usage |
| usage_counters | workspace (RLS) | 021 | Real-time metric counters |
| entitlement_overrides | workspace (RLS) | 019 | Grandfathering/credits |
| audit_log | workspace (RLS) | 019 | Security + billing audit trail |
| support_tickets | workspace (RLS) | 021 | In-app support |
| sessions | workspace (RLS) | 001 | Telemetry session data |
| laps | workspace (RLS) | 001 | Lap splits per session |
| tracks | workspace (RLS) | 001 | Track definitions |
| *44 domain tables* | workspace (RLS) | 001-018 | All telemetry domain data |

---

## Entity-Relationship Diagram

```
users (001, 002, 019, 020)
├── id (PK), email (unique), password_hash
├── display_name, created_at, deleted_at
├── email_verified, default_workspace_id
├── stripe_customer_id, stripe_subscription_id
├── plan_tier → plan_definitions.tier
├── subscription_status (free/trialing/active/past_due/canceled/paused)
├── is_platform_admin
├── suspended_at, suspension_reason
├── grace_period_end
├── totp_secret, totp_enabled, totp_backup_codes, totp_verified_at
├── preferences (JSON)
├── terms_accepted_at, terms_version
│
├─── refresh_tokens (1:N, CASCADE)
│    ├── id, user_id (FK), token_hash, expires_at
│    ├── user_agent, ip_address, last_used_at
│    └── created_at
│
├─── oauth_connections (1:N)
│    ├── id, user_id (FK), provider, provider_user_id
│    └── provider_email, access_token, refresh_token
│
├─── password_reset_tokens (1:N, CASCADE)
│    ├── id, user_id (FK), token_hash
│    └── expires_at, created_at
│
├─── data_exports (1:N) [GDPR]
│    ├── id, user_id, status, format
│    └── file_path, expires_at, created_at
│
├─── entitlement_overrides (1:N, also via workspace)
│    ├── id, user_id (FK), workspace_id (FK)
│    ├── override_key, override_value (JSON)
│    ├── reason, expires_at
│    └── created_by (FK → users), created_at
│
├─── email_log (1:N)
│    ├── id, user_id, template, to_email
│    └── status, sent_at, error
│
└─── workspaces (via team_members or owner)
     ├── id, name, slug, type (personal/team)
     ├── owner_user_id (FK), owner_team_id (FK)
     ├── created_at
     │
     ├─── usage_events (1:N, RLS)
     │    ├── id (BIGSERIAL), user_id (FK), workspace_id (FK)
     │    ├── event_type, cost, metadata_json
     │    └── created_at
     │
     ├─── usage_monthly (1:N, RLS)
     │    ├── id, workspace_id (FK), period_start (DATE)
     │    ├── event_type, total
     │    └── UNIQUE(workspace_id, period_start, event_type)
     │
     ├─── usage_counters (1:N, RLS)
     │    ├── id, workspace_id (FK), metric, period
     │    ├── count, updated_at
     │    └── UNIQUE(workspace_id, metric, period)
     │
     ├─── audit_log (1:N, RLS)
     │    ├── id (BIGSERIAL), user_id (FK), workspace_id (FK)
     │    ├── action, details (JSON), ip_address, user_agent
     │    └── created_at
     │
     ├─── support_tickets (1:N, RLS)
     │    ├── id, user_id (FK), workspace_id (FK)
     │    ├── issue_type, session_id, description
     │    ├── diagnostics (JSON), status
     │    └── created_at
     │
     └─── 44 domain tables (sessions, laps, tracks, etc.) — all RLS


plan_definitions (019, global)
├── tier (PK): demo, racer, world-class, b2b
├── display_name, reports_per_month, max_upload_size_mb
├── telemetry_retention_days, api_access, comparison_enabled
├── coaching_plans_enabled, visualization_enabled, race_strategy_limit
├── live_monitoring, export_formats (JSON), max_concurrent_jobs
├── rate_multiplier, created_at
└── Referenced by: users.plan_tier

teams (004)
├── id, name, slug, created_at
├─── team_members (M:N with users)
│    ├── team_id (FK), user_id (FK), role
│    └── created_at
└─── invitations (1:N)
     ├── id, team_id (FK), email, role
     ├── token_hash, inviter_id (FK → users)
     └── expires_at, created_at

stripe_events (019, global)
├── id, stripe_event_id (unique), event_type
├── processed_at, payload_hash
└── Purpose: webhook deduplication
```

---

## Seed Data — plan_definitions

| tier | display_name | reports/mo | upload MB | retention days | API | comparison | coaching | viz | strategy | live | exports | jobs | rate |
|------|-------------|-----------|----------|---------------|-----|-----------|---------|-----|----------|------|---------|------|------|
| demo | Demo | 1 | 500 | 30 | no | no | no | no | limited_3h | no | csv | 1 | 1.0 |
| racer | Racer | 10 | 2000 | 90 | no | no | yes | yes | full | yes | pdf,csv | 2 | 2.0 |
| world-class | World-Class | NULL | 5000 | 365 | yes | yes | yes | yes | full | yes | pdf,csv,api | 5 | 5.0 |
| b2b | B2B | NULL | 10000 | NULL | yes | yes | yes | yes | full | yes | pdf,csv,api,branded | 10 | 10.0 |

---

## RLS Policy Summary

| Table | RLS | Policy | Reason |
|-------|-----|--------|--------|
| usage_events | YES | workspace_id = app.current_workspace_id | Per-workspace billing |
| usage_monthly | YES | workspace_id = app.current_workspace_id | Per-workspace aggregates |
| usage_counters | YES | workspace_id = app.current_workspace_id | Per-workspace metrics |
| entitlement_overrides | YES | workspace_id = app.current_workspace_id | Per-workspace overrides |
| audit_log | YES | workspace_id = app.current_workspace_id | Per-workspace audit |
| support_tickets | YES | workspace_id = app.current_workspace_id | Per-workspace support |
| plan_definitions | NO | — | Global reference table |
| invitations | NO | — | Cross-workspace (team invite) |
| password_reset_tokens | NO | — | User-level, not workspace |
| stripe_events | NO | — | Global dedup table |
| email_log | NO | — | Global email tracking |

---

## Index Strategy

| Index | Table | Columns | Purpose |
|-------|-------|---------|---------|
| idx_users_stripe_customer | users | stripe_customer_id (partial) | Stripe webhook lookup |
| idx_sessions_retention | sessions | workspace_id, created_at (partial) | Retention task query |
| idx_usage_events_ws_type_created | usage_events | workspace_id, event_type, created_at | Monthly usage aggregation |
| idx_usage_events_user_created | usage_events | user_id, created_at | User activity queries |
| idx_usage_monthly_ws_period | usage_monthly | workspace_id, period_start | Monthly report queries |
| idx_overrides_user | entitlement_overrides | user_id | User entitlement lookup |
| idx_overrides_workspace | entitlement_overrides | workspace_id | Workspace entitlement lookup |
| idx_audit_log_user_created | audit_log | user_id, created_at | User audit history |
| idx_audit_log_ws_created | audit_log | workspace_id, created_at | Workspace audit history |
| idx_audit_log_action | audit_log | action | Action filtering |
| idx_stripe_events_event_id | stripe_events | stripe_event_id (unique) | Dedup lookup |
| idx_stripe_events_type | stripe_events | event_type | Event type filtering |
| idx_password_reset_token_hash | password_reset_tokens | token_hash | Token verification |
| idx_password_reset_user | password_reset_tokens | user_id | User token cleanup |
| idx_invitations_email | invitations | email | Invite-by-email lookup |
| idx_invitations_team | invitations | team_id | Team invite listing |
| idx_invitations_token | invitations | token_hash (unique) | Token verification |
| idx_usage_counters_lookup | usage_counters | workspace_id, metric, period | Counter lookup |
| idx_support_tickets_user | support_tickets | user_id | User ticket listing |
| idx_support_tickets_ws | support_tickets | workspace_id | Workspace ticket listing |
| idx_email_log_user | email_log | user_id | User email history |
| idx_email_log_template | email_log | template | Template analytics |
| idx_email_log_sent_at | email_log | sent_at | Deliverability monitoring |

---

## Migration Chain

```
001 → 002 → 003 → 004 → 005 → 006 → 007 → 008 → 009 → 010
 → 011 → 012 → 013 → 014 → 015 → 016 → 017 → 018
 → 019 (core data model) → 020 (account security) → 021 (community + email)
```

---

## Data Deletion Cascades

### User Account Deletion (GDPR Erasure)

```
users →
  refresh_tokens (CASCADE)
  oauth_connections (CASCADE)
  password_reset_tokens (CASCADE)
  data_exports (CASCADE)
  entitlement_overrides (CASCADE where user_id)
  team_members (CASCADE) → if last member, orphan team + workspace
  email_log (SET NULL user_id, keep record)
  usage_events (anonymize user_id, keep for aggregate accuracy)
  audit_log (SET NULL user_id, keep action/details for compliance)
  workspaces (owned personal) → all 44 domain tables CASCADE
```

### Workspace Deletion

```
workspaces →
  all 44 domain tables (CASCADE via RLS policies)
  usage_events (CASCADE)
  usage_monthly (CASCADE)
  usage_counters (CASCADE)
  support_tickets (CASCADE)
  audit_log (archive, don't delete)
  entitlement_overrides (CASCADE where workspace_id)
```
