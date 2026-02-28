-- Fix migrations 017-021 that were stamped but never ran.
-- Uses IF NOT EXISTS / IF EXISTS guards so this is safe to re-run.

BEGIN;

-- ═══════════════════════════════════════════════════════════════════
-- Migration 017: session_weather_laps + session_datetime
-- ═══════════════════════════════════════════════════════════════════

-- Table already exists, just ensure RLS + session_datetime column
ALTER TABLE session_weather_laps ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'session_weather_laps'
      AND policyname = 'session_weather_laps_tenant'
  ) THEN
    EXECUTE 'CREATE POLICY session_weather_laps_tenant ON session_weather_laps
      USING (workspace_id = current_setting(''app.workspace_id'', true))';
  END IF;
END $$;

ALTER TABLE sessions ADD COLUMN IF NOT EXISTS session_datetime TEXT;

-- ═══════════════════════════════════════════════════════════════════
-- Migration 018: kart_envelope coaching columns on theoretical_data
-- ═══════════════════════════════════════════════════════════════════

ALTER TABLE theoretical_data ADD COLUMN IF NOT EXISTS corner_coaching_json TEXT;
ALTER TABLE theoretical_data ADD COLUMN IF NOT EXISTS delta_map_json TEXT;
ALTER TABLE theoretical_data ADD COLUMN IF NOT EXISTS session_scalars_json TEXT;

-- ═══════════════════════════════════════════════════════════════════
-- Migration 019: entitlements, usage, audit, stripe events
-- ═══════════════════════════════════════════════════════════════════

-- 019.1: Users columns
ALTER TABLE users ADD COLUMN IF NOT EXISTS plan_tier TEXT NOT NULL DEFAULT 'demo';
ALTER TABLE users ADD COLUMN IF NOT EXISTS suspended_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS suspension_reason TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS grace_period_end TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_platform_admin BOOLEAN NOT NULL DEFAULT false;

-- Rename billing_plan → subscription_status (only if billing_plan still exists)
DO $$ BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'users' AND column_name = 'billing_plan'
  ) THEN
    ALTER TABLE users RENAME COLUMN billing_plan TO subscription_status;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_users_stripe_customer
  ON users (stripe_customer_id) WHERE stripe_customer_id IS NOT NULL;

-- 019.2: Sessions retention columns
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS retention_expired BOOLEAN DEFAULT FALSE;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS retention_warning_sent BOOLEAN DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_sessions_retention
  ON sessions (workspace_id, created_at) WHERE retention_expired IS NOT TRUE;

-- 019.3: plan_definitions
CREATE TABLE IF NOT EXISTS plan_definitions (
  tier TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  reports_per_month INTEGER,
  max_upload_size_mb INTEGER DEFAULT 500,
  telemetry_retention_days INTEGER,
  api_access BOOLEAN DEFAULT false,
  comparison_enabled BOOLEAN DEFAULT false,
  coaching_plans_enabled BOOLEAN DEFAULT false,
  visualization_enabled BOOLEAN DEFAULT false,
  race_strategy_limit TEXT,
  live_monitoring BOOLEAN DEFAULT false,
  export_formats TEXT DEFAULT '["csv"]',
  max_concurrent_jobs INTEGER DEFAULT 1,
  rate_multiplier FLOAT DEFAULT 1.0,
  created_at TIMESTAMPTZ DEFAULT now()
);

INSERT INTO plan_definitions
  (tier, display_name, reports_per_month, max_upload_size_mb,
   telemetry_retention_days, api_access, comparison_enabled,
   coaching_plans_enabled, visualization_enabled, race_strategy_limit,
   live_monitoring, export_formats, max_concurrent_jobs, rate_multiplier)
VALUES
  ('demo', 'Demo', 1, 500, 30, false, false, false, false,
   'limited_3h', false, '["csv"]', 1, 1.0),
  ('racer', 'Racer', 10, 2000, 90, false, false, true, true,
   'full', true, '["pdf","csv"]', 2, 2.0),
  ('world-class', 'World-Class', NULL, 5000, 365, true, true, true, true,
   'full', true, '["pdf","csv","api"]', 5, 5.0),
  ('b2b', 'B2B', NULL, 10000, NULL, true, true, true, true,
   'full', true, '["pdf","csv","api","branded"]', 10, 10.0)
ON CONFLICT (tier) DO NOTHING;

-- 019.4: usage_events
CREATE TABLE IF NOT EXISTS usage_events (
  id BIGSERIAL PRIMARY KEY,
  user_id INTEGER REFERENCES users(id) NOT NULL,
  workspace_id INTEGER REFERENCES workspaces(id) NOT NULL,
  event_type TEXT NOT NULL,
  cost INTEGER DEFAULT 1,
  metadata_json TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_usage_events_ws_type_created ON usage_events(workspace_id, event_type, created_at);
CREATE INDEX IF NOT EXISTS idx_usage_events_user_created ON usage_events(user_id, created_at);

-- 019.5: usage_monthly
CREATE TABLE IF NOT EXISTS usage_monthly (
  id SERIAL PRIMARY KEY,
  workspace_id INTEGER REFERENCES workspaces(id) NOT NULL,
  period_start DATE NOT NULL,
  event_type TEXT NOT NULL,
  total INTEGER DEFAULT 0,
  UNIQUE (workspace_id, period_start, event_type)
);
CREATE INDEX IF NOT EXISTS idx_usage_monthly_ws_period ON usage_monthly(workspace_id, period_start);

-- 019.6: entitlement_overrides
CREATE TABLE IF NOT EXISTS entitlement_overrides (
  id SERIAL PRIMARY KEY,
  user_id INTEGER REFERENCES users(id),
  workspace_id INTEGER REFERENCES workspaces(id),
  override_key TEXT NOT NULL,
  override_value TEXT NOT NULL,
  reason TEXT,
  expires_at TIMESTAMPTZ,
  created_by INTEGER REFERENCES users(id),
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_overrides_user ON entitlement_overrides(user_id);
CREATE INDEX IF NOT EXISTS idx_overrides_workspace ON entitlement_overrides(workspace_id);

-- 019.7: audit_log (add missing 'details' column if table exists)
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS details TEXT;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS ip_address TEXT;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS user_agent TEXT;
CREATE INDEX IF NOT EXISTS idx_audit_log_user_created ON audit_log(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_log_ws_created ON audit_log(workspace_id, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);

-- 019.8: stripe_events
CREATE TABLE IF NOT EXISTS stripe_events (
  id SERIAL PRIMARY KEY,
  stripe_event_id TEXT UNIQUE NOT NULL,
  event_type TEXT NOT NULL,
  processed_at TIMESTAMPTZ DEFAULT now(),
  payload_hash TEXT
);
CREATE INDEX IF NOT EXISTS idx_stripe_events_type ON stripe_events(event_type);

-- 019.9: RLS on new workspace-scoped tables
DO $$ BEGIN
  ALTER TABLE usage_events ENABLE ROW LEVEL SECURITY;
  ALTER TABLE usage_monthly ENABLE ROW LEVEL SECURITY;
  ALTER TABLE entitlement_overrides ENABLE ROW LEVEL SECURITY;
  ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
EXCEPTION WHEN OTHERS THEN NULL;
END $$;

-- 019.10: Backfill plan_tier
UPDATE users SET plan_tier = CASE
  WHEN subscription_status = 'active' AND stripe_subscription_id IS NOT NULL THEN 'racer'
  ELSE 'demo'
END
WHERE plan_tier = 'demo';

-- ═══════════════════════════════════════════════════════════════════
-- Migration 021: invitations, support tickets, usage counters, email log
-- ═══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS invitations (
  id SERIAL PRIMARY KEY,
  team_id INTEGER REFERENCES teams(id) ON DELETE CASCADE NOT NULL,
  email TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'member',
  token_hash TEXT NOT NULL,
  inviter_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_invitations_email ON invitations(email);
CREATE INDEX IF NOT EXISTS idx_invitations_team ON invitations(team_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_invitations_token ON invitations(token_hash);

CREATE TABLE IF NOT EXISTS support_tickets (
  id SERIAL PRIMARY KEY,
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE NOT NULL,
  workspace_id INTEGER REFERENCES workspaces(id) ON DELETE CASCADE NOT NULL,
  issue_type TEXT NOT NULL,
  session_id INTEGER,
  description TEXT NOT NULL,
  diagnostics TEXT,
  status TEXT DEFAULT 'open',
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_support_tickets_user ON support_tickets(user_id);
CREATE INDEX IF NOT EXISTS idx_support_tickets_ws ON support_tickets(workspace_id);

CREATE TABLE IF NOT EXISTS usage_counters (
  id SERIAL PRIMARY KEY,
  workspace_id INTEGER REFERENCES workspaces(id) ON DELETE CASCADE NOT NULL,
  metric TEXT NOT NULL,
  period TEXT NOT NULL,
  count INTEGER NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (workspace_id, metric, period)
);
CREATE INDEX IF NOT EXISTS idx_usage_counters_lookup ON usage_counters(workspace_id, metric, period);

CREATE TABLE IF NOT EXISTS email_log (
  id SERIAL PRIMARY KEY,
  user_id INTEGER,
  template TEXT NOT NULL,
  to_email TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  sent_at TIMESTAMPTZ DEFAULT now(),
  error TEXT
);
CREATE INDEX IF NOT EXISTS idx_email_log_user ON email_log(user_id);
CREATE INDEX IF NOT EXISTS idx_email_log_template ON email_log(template);
CREATE INDEX IF NOT EXISTS idx_email_log_sent_at ON email_log(sent_at);

-- RLS on workspace-scoped tables
DO $$ BEGIN
  ALTER TABLE support_tickets ENABLE ROW LEVEL SECURITY;
  ALTER TABLE usage_counters ENABLE ROW LEVEL SECURITY;
EXCEPTION WHEN OTHERS THEN NULL;
END $$;

COMMIT;
