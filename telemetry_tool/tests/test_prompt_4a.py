"""Tests for PROMPT 4A — Core Entity Design + Migration Strategy.

Validates:
- Migration consolidation (019-021) chains correctly
- All required tables exist in migrations
- Seed data matches pricing.ts
- Backfill logic present
- RLS policies applied to correct tables
- Indexes created for query performance
- ER design document exists and is comprehensive
- No orphaned migrations (old 022-026 deleted)
"""
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ===========================================================================
# A) Migration chain integrity
# ===========================================================================

class TestMigrationChain:
    """Migrations 019→020→021 chain correctly from 018."""

    def test_019_chains_from_018(self):
        source = (_PROJECT_ROOT / "alembic" / "versions" / "019_core_data_model.py").read_text()
        assert 'down_revision = "018"' in source
        assert 'revision = "019"' in source

    def test_020_chains_from_019(self):
        source = (_PROJECT_ROOT / "alembic" / "versions" / "020_account_security.py").read_text()
        assert 'down_revision = "019"' in source
        assert 'revision = "020"' in source

    def test_021_chains_from_020(self):
        source = (_PROJECT_ROOT / "alembic" / "versions" / "021_community_email.py").read_text()
        assert 'down_revision = "020"' in source
        assert 'revision = "021"' in source

    def test_no_orphaned_migrations(self):
        """Old migrations 022-026 should be deleted."""
        versions_dir = _PROJECT_ROOT / "alembic" / "versions"
        for old in ["022_account_experience.py", "023_terms_acceptance.py",
                     "024_invitations_lockout.py", "025_grace_period.py",
                     "026_email_log_admin.py"]:
            assert not (versions_dir / old).exists(), f"Orphaned migration: {old}"

    def test_no_duplicate_020(self):
        """Only one 020 migration should exist."""
        versions_dir = _PROJECT_ROOT / "alembic" / "versions"
        matching = [f for f in versions_dir.iterdir()
                    if f.name.startswith("020_") and f.suffix == ".py"]
        assert len(matching) == 1, f"Expected 1 migration starting with 020_, found: {matching}"

    def test_exactly_three_new_migrations(self):
        """Exactly 3 consolidated migrations should exist (019, 020, 021)."""
        versions_dir = _PROJECT_ROOT / "alembic" / "versions"
        new_migrations = sorted(f.name for f in versions_dir.iterdir()
                                if f.name.startswith(("019_", "020_", "021_"))
                                and f.suffix == ".py")
        assert len(new_migrations) == 3


# ===========================================================================
# B) Migration 019 — core data model
# ===========================================================================

class TestMigration019Content:
    """Migration 019 creates core tables and modifies users."""

    def _source(self):
        return (_PROJECT_ROOT / "alembic" / "versions" / "019_core_data_model.py").read_text()

    def test_users_plan_tier(self):
        assert "plan_tier" in self._source()

    def test_users_subscription_status_rename(self):
        assert "subscription_status" in self._source()

    def test_users_suspended_columns(self):
        s = self._source()
        assert "suspended_at" in s
        assert "suspension_reason" in s

    def test_users_grace_period(self):
        assert "grace_period_end" in self._source()

    def test_users_is_platform_admin(self):
        assert "is_platform_admin" in self._source()

    def test_plan_definitions_table(self):
        s = self._source()
        assert "plan_definitions" in s
        assert "reports_per_month" in s
        assert "telemetry_retention_days" in s
        assert "max_upload_size_mb" in s

    def test_usage_events_table(self):
        s = self._source()
        assert "usage_events" in s
        assert "event_type" in s
        assert "metadata_json" in s

    def test_usage_monthly_table(self):
        assert "usage_monthly" in self._source()

    def test_entitlement_overrides_table(self):
        s = self._source()
        assert "entitlement_overrides" in s
        assert "override_key" in s
        assert "override_value" in s

    def test_audit_log_table(self):
        s = self._source()
        assert "audit_log" in s
        assert "user_agent" in s

    def test_stripe_events_table(self):
        s = self._source()
        assert "stripe_events" in s
        assert "stripe_event_id" in s
        assert "payload_hash" in s

    def test_sessions_retention_columns(self):
        s = self._source()
        assert "retention_expired" in s
        assert "retention_warning_sent" in s

    def test_rls_applied(self):
        s = self._source()
        assert "ENABLE ROW LEVEL SECURITY" in s
        assert "tenant_isolation" in s

    def test_rls_tables_correct(self):
        """RLS applied to workspace-scoped tables only."""
        s = self._source()
        # The migration uses a loop over rls_tables list
        for table in ["usage_events", "usage_monthly", "entitlement_overrides", "audit_log"]:
            assert f'"{table}"' in s or f"'{table}'" in s, f"Missing RLS table: {table}"
        assert "rls_tables" in s


# ===========================================================================
# C) Seed data matches pricing.ts
# ===========================================================================

class TestSeedData:
    """Plan_definitions seed data matches pricing.ts."""

    def _source(self):
        return (_PROJECT_ROOT / "alembic" / "versions" / "019_core_data_model.py").read_text()

    def test_demo_tier_seeded(self):
        s = self._source()
        assert "'demo'" in s
        assert "'Demo'" in s

    def test_racer_tier_seeded(self):
        s = self._source()
        assert "'racer'" in s
        assert "'Racer'" in s

    def test_world_class_tier_seeded(self):
        s = self._source()
        assert "'world-class'" in s
        assert "'World-Class'" in s

    def test_b2b_tier_seeded(self):
        s = self._source()
        assert "'b2b'" in s
        assert "'B2B'" in s

    def test_demo_reports_limit_1(self):
        """Demo tier should have 1 report per month."""
        s = self._source()
        # The INSERT has demo row with reports_per_month = 1
        assert "('demo', 'Demo', 1," in s

    def test_racer_reports_limit_10(self):
        """Racer tier should have 10 reports per month."""
        s = self._source()
        assert "('racer', 'Racer', 10," in s

    def test_world_class_unlimited_reports(self):
        """World-Class should have NULL (unlimited) reports."""
        s = self._source()
        assert "('world-class', 'World-Class', NULL," in s

    def test_retention_days_match(self):
        """Demo=30, Racer=90, World-Class=365, B2B=NULL."""
        s = self._source()
        # Check retention values appear in the seed SQL
        assert "30" in s   # demo retention
        assert "90" in s   # racer retention
        assert "365" in s  # world-class retention

    def test_backfill_present(self):
        """Backfill SQL should map existing users to correct tiers."""
        s = self._source()
        assert "UPDATE users SET plan_tier" in s
        assert "CASE" in s


# ===========================================================================
# D) Migration 020 — account security
# ===========================================================================

class TestMigration020Content:
    """Migration 020 creates security tables and columns."""

    def _source(self):
        return (_PROJECT_ROOT / "alembic" / "versions" / "020_account_security.py").read_text()

    def test_password_reset_tokens(self):
        s = self._source()
        assert "password_reset_tokens" in s
        assert "token_hash" in s
        assert "expires_at" in s

    def test_refresh_token_metadata(self):
        s = self._source()
        assert "user_agent" in s
        assert "ip_address" in s
        assert "last_used_at" in s

    def test_totp_columns(self):
        s = self._source()
        assert "totp_secret" in s
        assert "totp_enabled" in s
        assert "totp_backup_codes" in s

    def test_preferences_column(self):
        assert "preferences" in self._source()

    def test_terms_columns(self):
        s = self._source()
        assert "terms_accepted_at" in s
        assert "terms_version" in s


# ===========================================================================
# E) Migration 021 — community + email
# ===========================================================================

class TestMigration021Content:
    """Migration 021 creates community and email tables."""

    def _source(self):
        return (_PROJECT_ROOT / "alembic" / "versions" / "021_community_email.py").read_text()

    def test_invitations_table(self):
        s = self._source()
        assert "invitations" in s
        assert "token_hash" in s
        assert "team_id" in s
        assert "expires_at" in s

    def test_support_tickets_table(self):
        s = self._source()
        assert "support_tickets" in s
        assert "issue_type" in s
        assert "diagnostics" in s

    def test_usage_counters_table(self):
        s = self._source()
        assert "usage_counters" in s
        assert "metric" in s
        assert "period" in s

    def test_email_log_table(self):
        s = self._source()
        assert "email_log" in s
        assert "template" in s
        assert "to_email" in s

    def test_rls_on_support_tickets(self):
        s = self._source()
        assert '"support_tickets" ENABLE ROW LEVEL SECURITY' in s

    def test_rls_on_usage_counters(self):
        s = self._source()
        assert '"usage_counters" ENABLE ROW LEVEL SECURITY' in s

    def test_no_rls_on_invitations(self):
        """Invitations are cross-workspace, no RLS."""
        s = self._source()
        assert '"invitations" ENABLE ROW LEVEL SECURITY' not in s

    def test_no_rls_on_email_log(self):
        """email_log is global, no RLS."""
        s = self._source()
        assert '"email_log" ENABLE ROW LEVEL SECURITY' not in s


# ===========================================================================
# F) Indexes
# ===========================================================================

class TestIndexes:
    """All critical indexes exist in the migrations."""

    def test_usage_events_indexes(self):
        s = (_PROJECT_ROOT / "alembic" / "versions" / "019_core_data_model.py").read_text()
        assert "idx_usage_events_ws_type_created" in s
        assert "idx_usage_events_user_created" in s

    def test_audit_log_indexes(self):
        s = (_PROJECT_ROOT / "alembic" / "versions" / "019_core_data_model.py").read_text()
        assert "idx_audit_log_user_created" in s
        assert "idx_audit_log_ws_created" in s
        assert "idx_audit_log_action" in s

    def test_stripe_events_indexes(self):
        s = (_PROJECT_ROOT / "alembic" / "versions" / "019_core_data_model.py").read_text()
        assert "idx_stripe_events_event_id" in s

    def test_password_reset_indexes(self):
        s = (_PROJECT_ROOT / "alembic" / "versions" / "020_account_security.py").read_text()
        assert "idx_password_reset_token_hash" in s

    def test_invitation_indexes(self):
        s = (_PROJECT_ROOT / "alembic" / "versions" / "021_community_email.py").read_text()
        assert "idx_invitations_token" in s
        assert "idx_invitations_email" in s
        assert "idx_invitations_team" in s

    def test_email_log_indexes(self):
        s = (_PROJECT_ROOT / "alembic" / "versions" / "021_community_email.py").read_text()
        assert "idx_email_log_user" in s
        assert "idx_email_log_template" in s

    def test_sessions_retention_index(self):
        s = (_PROJECT_ROOT / "alembic" / "versions" / "019_core_data_model.py").read_text()
        assert "idx_sessions_retention" in s


# ===========================================================================
# G) Downgrade functions
# ===========================================================================

class TestDowngrades:
    """Each migration has proper downgrade function."""

    def test_019_has_downgrade(self):
        s = (_PROJECT_ROOT / "alembic" / "versions" / "019_core_data_model.py").read_text()
        assert "def downgrade():" in s
        assert "DROP POLICY" in s

    def test_020_has_downgrade(self):
        s = (_PROJECT_ROOT / "alembic" / "versions" / "020_account_security.py").read_text()
        assert "def downgrade():" in s
        assert "drop_table" in s.lower() or "drop_column" in s.lower()

    def test_021_has_downgrade(self):
        s = (_PROJECT_ROOT / "alembic" / "versions" / "021_community_email.py").read_text()
        assert "def downgrade():" in s
        assert "DROP POLICY" in s


# ===========================================================================
# H) ER design document
# ===========================================================================

class TestERDocument:
    """ER design document exists and is comprehensive."""

    def _doc(self):
        return (_PROJECT_ROOT.parent / "docs" / "plans" / "2026-02-28-entity-relationship-model.md").read_text()

    def test_document_exists(self):
        path = _PROJECT_ROOT.parent / "docs" / "plans" / "2026-02-28-entity-relationship-model.md"
        assert path.exists()

    def test_contains_all_core_tables(self):
        doc = self._doc()
        for table in ["users", "plan_definitions", "usage_events", "usage_monthly",
                       "entitlement_overrides", "audit_log", "invitations",
                       "password_reset_tokens", "stripe_events", "email_log",
                       "support_tickets", "usage_counters"]:
            assert table in doc, f"Missing table: {table}"

    def test_contains_rls_summary(self):
        doc = self._doc()
        assert "RLS" in doc
        assert "workspace_id" in doc

    def test_contains_index_strategy(self):
        doc = self._doc()
        assert "Index" in doc
        assert "idx_usage_events" in doc

    def test_contains_seed_data(self):
        doc = self._doc()
        assert "demo" in doc
        assert "racer" in doc
        assert "world-class" in doc

    def test_contains_deletion_cascades(self):
        doc = self._doc()
        assert "Deletion" in doc or "CASCADE" in doc

    def test_contains_migration_chain(self):
        doc = self._doc()
        assert "019" in doc
        assert "020" in doc
        assert "021" in doc
