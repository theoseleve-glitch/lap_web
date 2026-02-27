"""Tests for PROMPT 5C — End-to-End Integration Testing + Deployment.

Validates:
- Integration test suite (4 files in tests/integration/)
- E2E frontend tests (6 spec files in lap-website/e2e/)
- Security testing checklist (docs/security-testing.md)
- Deployment script (scripts/deploy.sh)
- Rollback documentation (docs/rollback.md)
"""
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _PROJECT_ROOT.parent
_LAP_ROOT = _REPO_ROOT / "lap-website"


# ===========================================================================
# A) Integration test suite
# ===========================================================================

class TestIntegrationTestSuiteExists:
    """Integration test directory and files exist."""

    def _integ_dir(self):
        return _PROJECT_ROOT / "tests" / "integration"

    def test_integration_dir_exists(self):
        assert self._integ_dir().is_dir()

    def test_init_exists(self):
        assert (self._integ_dir() / "__init__.py").exists()

    def test_conftest_exists(self):
        assert (self._integ_dir() / "conftest.py").exists()

    def test_auth_lifecycle_exists(self):
        assert (self._integ_dir() / "test_auth_lifecycle.py").exists()

    def test_billing_entitlements_exists(self):
        assert (self._integ_dir() / "test_billing_entitlements.py").exists()

    def test_workspace_teams_exists(self):
        assert (self._integ_dir() / "test_workspace_teams.py").exists()

    def test_data_lifecycle_exists(self):
        assert (self._integ_dir() / "test_data_lifecycle.py").exists()


class TestAuthLifecycleTests:
    """Auth lifecycle tests cover required flows."""

    def _source(self):
        return (_PROJECT_ROOT / "tests" / "integration" / "test_auth_lifecycle.py").read_text()

    def test_register_test(self):
        assert "register" in self._source().lower()

    def test_login_test(self):
        assert "login" in self._source().lower()

    def test_token_test(self):
        assert "token" in self._source().lower()

    def test_2fa_test(self):
        assert "2fa" in self._source().lower() or "totp" in self._source().lower()

    def test_password_reset_test(self):
        assert "password_reset" in self._source().lower() or "reset_password" in self._source().lower()

    def test_oauth_test(self):
        assert "oauth" in self._source().lower()

    def test_lockout_test(self):
        assert "lockout" in self._source().lower()


class TestBillingEntitlementsTests:
    """Billing entitlements tests cover required flows."""

    def _source(self):
        return (_PROJECT_ROOT / "tests" / "integration" / "test_billing_entitlements.py").read_text()

    def test_feature_gating_test(self):
        assert "feature" in self._source().lower() or "gating" in self._source().lower()

    def test_subscription_test(self):
        assert "subscription" in self._source().lower() or "racer" in self._source().lower()

    def test_quota_test(self):
        assert "quota" in self._source().lower()

    def test_downgrade_test(self):
        assert "downgrade" in self._source().lower()

    def test_webhook_test(self):
        assert "webhook" in self._source().lower()

    def test_reconciliation_test(self):
        assert "reconciliation" in self._source().lower()


class TestWorkspaceTeamsTests:
    """Workspace teams tests cover required flows."""

    def _source(self):
        return (_PROJECT_ROOT / "tests" / "integration" / "test_workspace_teams.py").read_text()

    def test_isolation_test(self):
        assert "isolation" in self._source().lower()

    def test_rbac_test(self):
        assert "rbac" in self._source().lower()

    def test_team_invite_test(self):
        assert "invite" in self._source().lower() or "add_member" in self._source().lower()

    def test_idor_test(self):
        assert "idor" in self._source().lower()


class TestDataLifecycleTests:
    """Data lifecycle tests cover required flows."""

    def _source(self):
        return (_PROJECT_ROOT / "tests" / "integration" / "test_data_lifecycle.py").read_text()

    def test_retention_test(self):
        assert "retention" in self._source().lower()

    def test_gdpr_export_test(self):
        assert "export" in self._source().lower()

    def test_account_deletion_test(self):
        assert "deletion" in self._source().lower() or "delete" in self._source().lower()


# ===========================================================================
# B) E2E frontend tests
# ===========================================================================

class TestE2ETestsExist:
    """Playwright E2E spec files exist."""

    def _e2e_dir(self):
        return _LAP_ROOT / "e2e"

    def test_account_profile_spec(self):
        assert (self._e2e_dir() / "account-profile.spec.ts").exists()

    def test_account_security_spec(self):
        assert (self._e2e_dir() / "account-security.spec.ts").exists()

    def test_account_billing_spec(self):
        assert (self._e2e_dir() / "account-billing.spec.ts").exists()

    def test_account_data_spec(self):
        assert (self._e2e_dir() / "account-data.spec.ts").exists()

    def test_feature_gating_spec(self):
        assert (self._e2e_dir() / "feature-gating.spec.ts").exists()

    def test_upgrade_flow_spec(self):
        assert (self._e2e_dir() / "upgrade-flow.spec.ts").exists()


class TestE2EProfileSpec:
    """Account profile E2E covers key interactions."""

    def _source(self):
        return (_LAP_ROOT / "e2e" / "account-profile.spec.ts").read_text()

    def test_renders_profile_page(self):
        assert "Profile" in self._source()

    def test_has_display_name(self):
        assert "Display Name" in self._source()

    def test_has_email_field(self):
        assert "Email" in self._source()

    def test_has_save_button(self):
        assert "save" in self._source().lower() or "update" in self._source().lower()


class TestE2ESecuritySpec:
    """Account security E2E covers key sections."""

    def _source(self):
        return (_LAP_ROOT / "e2e" / "account-security.spec.ts").read_text()

    def test_has_password_section(self):
        assert "password" in self._source().lower()

    def test_has_2fa_section(self):
        assert "2fa" in self._source().lower() or "two" in self._source().lower()


class TestE2EBillingSpec:
    """Account billing E2E covers plan and status."""

    def _source(self):
        return (_LAP_ROOT / "e2e" / "account-billing.spec.ts").read_text()

    def test_shows_plan(self):
        assert "plan" in self._source().lower() or "racer" in self._source().lower()

    def test_shows_status(self):
        assert "active" in self._source().lower()


class TestE2EFeatureGatingSpec:
    """Feature gating E2E covers demo vs paid."""

    def _source(self):
        return (_LAP_ROOT / "e2e" / "feature-gating.spec.ts").read_text()

    def test_demo_user_gated(self):
        assert "demo" in self._source().lower()

    def test_upgrade_prompt(self):
        assert "upgrade" in self._source().lower()

    def test_racer_user_access(self):
        assert "racer" in self._source().lower()


class TestE2EUpgradeFlowSpec:
    """Upgrade flow E2E covers checkout interaction."""

    def _source(self):
        return (_LAP_ROOT / "e2e" / "upgrade-flow.spec.ts").read_text()

    def test_billing_upgrade_page(self):
        assert "upgrade" in self._source().lower()

    def test_checkout_api_call(self):
        assert "checkout" in self._source().lower()

    def test_stripe_redirect(self):
        assert "stripe" in self._source().lower()


# ===========================================================================
# C) Security testing checklist
# ===========================================================================

class TestSecurityChecklistExists:
    """Security testing documentation exists."""

    def _source(self):
        return (_PROJECT_ROOT / "docs" / "security-testing.md").read_text()

    def test_doc_exists(self):
        assert (_PROJECT_ROOT / "docs" / "security-testing.md").exists()

    def test_authentication_section(self):
        assert "Authentication" in self._source()

    def test_authorization_section(self):
        assert "Authorization" in self._source()

    def test_input_validation_section(self):
        assert "Input Validation" in self._source()

    def test_rate_limiting_section(self):
        assert "Rate Limiting" in self._source()

    def test_billing_section(self):
        assert "Billing" in self._source()

    def test_jwt_check(self):
        assert "JWT" in self._source()

    def test_idor_check(self):
        assert "IDOR" in self._source()

    def test_sql_injection_check(self):
        assert "SQL injection" in self._source()

    def test_xss_check(self):
        assert "XSS" in self._source()

    def test_csrf_check(self):
        assert "CSRF" in self._source()

    def test_webhook_signature_check(self):
        assert "Webhook" in self._source() or "webhook" in self._source()


# ===========================================================================
# D) Deployment script
# ===========================================================================

class TestDeployScriptExists:
    """Deployment script exists with required stages."""

    def _source(self):
        return (_REPO_ROOT / "scripts" / "deploy.sh").read_text()

    def test_script_exists(self):
        assert (_REPO_ROOT / "scripts" / "deploy.sh").exists()

    def test_has_preflight_stage(self):
        assert "Pre-flight" in self._source() or "preflight" in self._source().lower()

    def test_has_backend_deploy_stage(self):
        assert "backend" in self._source().lower() or "Backend" in self._source()

    def test_has_migration_stage(self):
        assert "migration" in self._source().lower() or "alembic" in self._source().lower()

    def test_has_health_check(self):
        assert "healthz" in self._source()

    def test_has_frontend_deploy_stage(self):
        assert "Frontend" in self._source() or "cf:deploy" in self._source()

    def test_has_smoke_tests(self):
        assert "Smoke" in self._source() or "smoke" in self._source()

    def test_has_dry_run_flag(self):
        assert "--dry-run" in self._source()

    def test_uses_strict_mode(self):
        assert "set -euo pipefail" in self._source()

    def test_runs_pytest(self):
        assert "pytest" in self._source()

    def test_runs_consistency_check(self):
        assert "verify_entitlement_consistency" in self._source()

    def test_has_retry_loop(self):
        """Health check retries on failure."""
        source = self._source()
        assert "sleep" in source and ("seq" in source or "for" in source)


# ===========================================================================
# E) Rollback documentation
# ===========================================================================

class TestRollbackDocExists:
    """Rollback documentation covers all scenarios."""

    def _source(self):
        return (_PROJECT_ROOT / "docs" / "rollback.md").read_text()

    def test_doc_exists(self):
        assert (_PROJECT_ROOT / "docs" / "rollback.md").exists()

    def test_backend_rollback(self):
        assert "Backend" in self._source()

    def test_frontend_rollback(self):
        assert "Frontend" in self._source()

    def test_database_rollback(self):
        assert "Database" in self._source()

    def test_feature_flag_rollback(self):
        assert "Feature" in self._source() or "flag" in self._source().lower()

    def test_alembic_downgrade(self):
        assert "alembic downgrade" in self._source()

    def test_wrangler_rollback(self):
        assert "wrangler" in self._source().lower() or "cf:deploy" in self._source()

    def test_pg_restore(self):
        assert "pg_restore" in self._source()

    def test_health_check_verification(self):
        assert "healthz" in self._source()
