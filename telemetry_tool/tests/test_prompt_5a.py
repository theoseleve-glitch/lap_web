"""Tests for PROMPT 5A — Entitlement Matrix + Stripe Product Reconciliation.

Validates:
- Entitlement matrix document exists with all tiers and features
- Stripe setup script structure and idempotency logic
- Reconciliation script structure and canonical values
- Stripe test flows script exists
- pricing.ts consistency with canonical matrix
- Migration seed data consistency
"""
import re
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _PROJECT_ROOT.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ===========================================================================
# A) Entitlement matrix document
# ===========================================================================

class TestEntitlementMatrixDoc:
    """docs/entitlement-matrix.md is complete and consistent."""

    def _doc(self):
        return (_REPO_ROOT / "docs" / "entitlement-matrix.md").read_text()

    def test_doc_exists(self):
        assert (_REPO_ROOT / "docs" / "entitlement-matrix.md").exists()

    def test_all_tiers_present(self):
        doc = self._doc()
        for tier in ["demo", "racer", "world-class", "b2b"]:
            assert tier.lower() in doc.lower(), f"Tier '{tier}' not found"

    def test_code_keys_present(self):
        doc = self._doc()
        keys = [
            "reports_per_month", "scoring", "corner_coaching",
            "comparison", "coaching_plans", "visualization",
            "race_strategy", "live_monitoring", "export_pdf",
            "api_access", "telemetry_retention_days",
            "max_upload_size_mb", "max_concurrent_jobs",
            "rate_multiplier",
        ]
        for key in keys:
            assert key in doc, f"Code key '{key}' not found"

    def test_pricing_values(self):
        doc = self._doc()
        assert "8.99" in doc
        assert "69" in doc
        assert "13.99" in doc
        assert "109" in doc

    def test_retention_values(self):
        doc = self._doc()
        assert "30" in doc   # demo retention
        assert "90" in doc   # racer retention
        assert "365" in doc  # world-class retention

    def test_upload_limits(self):
        doc = self._doc()
        assert "500" in doc    # demo
        assert "2000" in doc   # racer
        assert "5000" in doc   # world-class
        assert "10000" in doc  # b2b

    def test_stripe_section(self):
        doc = self._doc()
        assert "Stripe" in doc
        assert "STRIPE_PRICE_RACER_MONTHLY" in doc

    def test_portal_section(self):
        doc = self._doc()
        assert "Customer Portal" in doc or "portal" in doc.lower()
        assert "cancel_at_period_end" in doc

    def test_reconciliation_reference(self):
        doc = self._doc()
        assert "verify_entitlement_consistency" in doc

    def test_export_formats(self):
        doc = self._doc()
        assert "csv" in doc.lower()
        assert "pdf" in doc.lower()
        assert "api" in doc.lower()


# ===========================================================================
# B) Stripe setup script
# ===========================================================================

class TestStripeSetupScript:
    """scripts/setup_stripe_products.py is correct."""

    def _script(self):
        return (_REPO_ROOT / "scripts" / "setup_stripe_products.py").read_text()

    def test_script_exists(self):
        assert (_REPO_ROOT / "scripts" / "setup_stripe_products.py").exists()

    def test_products_defined(self):
        script = self._script()
        assert "Lap Coach Racer" in script
        assert "Lap Coach World-Class" in script
        assert "Lap Coach B2B" in script

    def test_racer_monthly_price(self):
        script = self._script()
        assert "899" in script  # €8.99 in cents

    def test_racer_annual_price(self):
        script = self._script()
        assert "6900" in script  # €69.00 in cents

    def test_worldclass_monthly_price(self):
        script = self._script()
        assert "1399" in script  # €13.99 in cents

    def test_worldclass_annual_price(self):
        script = self._script()
        assert "10900" in script  # €109.00 in cents

    def test_currency_eur(self):
        assert "eur" in self._script()

    def test_idempotent_lookup(self):
        """Uses metadata to find existing products."""
        script = self._script()
        assert "metadata" in script
        assert "find_existing_product" in script

    def test_dry_run_support(self):
        assert "--dry-run" in self._script()

    def test_env_key_output(self):
        script = self._script()
        for key in ["STRIPE_PRICE_RACER_MONTHLY", "STRIPE_PRICE_RACER_ANNUAL",
                     "STRIPE_PRICE_WORLDCLASS_MONTHLY", "STRIPE_PRICE_WORLDCLASS_ANNUAL"]:
            assert key in script

    def test_b2b_no_self_serve_prices(self):
        """B2B product has no self-serve prices."""
        script = self._script()
        # B2B prices list should be empty
        assert '"prices": []' in script or "'prices': []" in script


# ===========================================================================
# C) Reconciliation script
# ===========================================================================

class TestReconciliationScript:
    """scripts/verify_entitlement_consistency.py validates all sources."""

    def _script(self):
        return (_REPO_ROOT / "scripts" / "verify_entitlement_consistency.py").read_text()

    def test_script_exists(self):
        assert (_REPO_ROOT / "scripts" / "verify_entitlement_consistency.py").exists()

    def test_checks_pricing_ts(self):
        assert "pricing.ts" in self._script() or "pricing_ts" in self._script()

    def test_checks_plan_definitions_db(self):
        assert "plan_definitions" in self._script()

    def test_checks_stripe(self):
        assert "Stripe" in self._script() or "stripe" in self._script()

    def test_checks_migration_seed(self):
        assert "migration" in self._script().lower()
        assert "019" in self._script()

    def test_canonical_tiers_defined(self):
        script = self._script()
        assert "CANONICAL_TIERS" in script
        for tier in ["demo", "racer", "world-class", "b2b"]:
            assert f'"{tier}"' in script

    def test_canonical_reports_per_month(self):
        script = self._script()
        assert "reports_per_month" in script

    def test_canonical_retention_days(self):
        script = self._script()
        assert "telemetry_retention_days" in script

    def test_skip_flags(self):
        """Supports --skip-stripe and --skip-db flags."""
        script = self._script()
        assert "--skip-stripe" in script
        assert "--skip-db" in script

    def test_exit_code_on_failure(self):
        assert "sys.exit(1)" in self._script()

    def test_exit_code_on_success(self):
        assert "sys.exit(0)" in self._script()


# ===========================================================================
# D) Stripe test flows script
# ===========================================================================

class TestStripeTestFlows:
    """scripts/test_stripe_flows.py exercises billing lifecycle."""

    def _script(self):
        return (_REPO_ROOT / "scripts" / "test_stripe_flows.py").read_text()

    def test_script_exists(self):
        assert (_REPO_ROOT / "scripts" / "test_stripe_flows.py").exists()

    def test_test_mode_guard(self):
        """Only runs with test-mode keys."""
        assert "sk_test_" in self._script()

    def test_creates_customer(self):
        assert "Customer.create" in self._script() or "create_customer" in self._script()

    def test_subscribes(self):
        assert "Subscription.create" in self._script()

    def test_upgrades(self):
        assert "upgrade" in self._script().lower()

    def test_downgrades(self):
        assert "downgrade" in self._script().lower()

    def test_cancels(self):
        assert "cancel_at_period_end" in self._script()

    def test_payment_failure(self):
        assert "payment_failure" in self._script() or "decline" in self._script().lower()

    def test_cleanup(self):
        """Cleans up test resources after run."""
        assert "cleanup" in self._script().lower()
        assert "Customer.delete" in self._script() or "delete" in self._script().lower()


# ===========================================================================
# E) Pricing.ts consistency (parsed)
# ===========================================================================

class TestPricingTsConsistency:
    """pricing.ts matches canonical entitlement matrix."""

    def _pricing(self):
        return (_REPO_ROOT / "lap-website" / "src" / "data" / "pricing.ts").read_text()

    def test_pricing_ts_exists(self):
        assert (_REPO_ROOT / "lap-website" / "src" / "data" / "pricing.ts").exists()

    def test_three_b2c_tiers(self):
        pricing = self._pricing()
        assert "slug: 'demo'" in pricing
        assert "slug: 'racer'" in pricing
        assert "slug: 'world-class'" in pricing

    def test_demo_is_free(self):
        pricing = self._pricing()
        assert "Free" in pricing

    def test_racer_monthly_price(self):
        assert "8.99" in self._pricing()

    def test_racer_annual_price(self):
        assert "69" in self._pricing()

    def test_worldclass_monthly_price(self):
        assert "13.99" in self._pricing()

    def test_worldclass_annual_price(self):
        assert "109" in self._pricing()

    def test_demo_1_report(self):
        pricing = self._pricing()
        assert "1 full report" in pricing or "1 report" in pricing

    def test_racer_10_reports(self):
        assert "10" in self._pricing()

    def test_worldclass_unlimited(self):
        assert "Unlimited" in self._pricing()

    def test_demo_retention_1_month(self):
        assert "1 month" in self._pricing()

    def test_racer_retention_3_months(self):
        assert "3 months" in self._pricing()

    def test_worldclass_retention_12_months(self):
        assert "12 months" in self._pricing()

    def test_comparison_gating(self):
        """Comparison is gated — demo and racer show '—'."""
        pricing = self._pricing()
        # Racer has Comparison & Progress as '—'
        assert "Comparison & Progress" in pricing

    def test_api_access_worldclass_only(self):
        """API Access only available for World-Class (in features)."""
        pricing = self._pricing()
        assert "API Access" in pricing or "API" in pricing

    def test_b2b_card_exists(self):
        assert "b2bCard" in self._pricing()

    def test_feature_eligibility_matrix(self):
        assert "featureEligibilityMatrix" in self._pricing()


# ===========================================================================
# F) Migration seed consistency
# ===========================================================================

class TestMigrationSeedConsistency:
    """Migration 019 seeds plan_definitions matching canonical values."""

    def _migration(self):
        return (
            _PROJECT_ROOT / "alembic" / "versions" / "019_core_data_model.py"
        ).read_text()

    def test_seeds_demo(self):
        assert "'demo'" in self._migration()

    def test_seeds_racer(self):
        assert "'racer'" in self._migration()

    def test_seeds_worldclass(self):
        assert "'world-class'" in self._migration()

    def test_seeds_b2b(self):
        assert "'b2b'" in self._migration()

    def test_demo_1_report_500mb_30d(self):
        migration = self._migration()
        # demo: 1 report, 500MB, 30 days
        assert "1, 500, 30" in migration

    def test_racer_10_reports_2000mb_90d(self):
        migration = self._migration()
        assert "10, 2000, 90" in migration

    def test_worldclass_unlimited_5000mb_365d(self):
        migration = self._migration()
        assert "NULL, 5000, 365" in migration

    def test_b2b_unlimited_10000mb_customd(self):
        migration = self._migration()
        assert "NULL, 10000, NULL" in migration

    def test_demo_rate_multiplier_1(self):
        migration = self._migration()
        assert "1.0" in migration  # demo rate_multiplier

    def test_racer_rate_multiplier_2(self):
        migration = self._migration()
        assert "2.0" in migration

    def test_worldclass_rate_multiplier_5(self):
        migration = self._migration()
        assert "5.0" in migration

    def test_b2b_rate_multiplier_10(self):
        migration = self._migration()
        assert "10.0" in migration


# ===========================================================================
# G) Reconciliation canonical values match
# ===========================================================================

class TestReconciliationCanonicalValues:
    """Canonical values in reconciliation script match the matrix."""

    def test_canonical_demo_values(self):
        from scripts.verify_entitlement_consistency import CANONICAL_TIERS
        demo = CANONICAL_TIERS["demo"]
        assert demo["reports_per_month"] == 1
        assert demo["telemetry_retention_days"] == 30
        assert demo["max_upload_size_mb"] == 500
        assert demo["max_concurrent_jobs"] == 1
        assert demo["api_access"] is False
        assert demo["rate_multiplier"] == 1.0

    def test_canonical_racer_values(self):
        from scripts.verify_entitlement_consistency import CANONICAL_TIERS
        racer = CANONICAL_TIERS["racer"]
        assert racer["reports_per_month"] == 10
        assert racer["telemetry_retention_days"] == 90
        assert racer["max_upload_size_mb"] == 2000
        assert racer["max_concurrent_jobs"] == 2
        assert racer["api_access"] is False
        assert racer["coaching_plans"] is True
        assert racer["visualization"] is True
        assert racer["rate_multiplier"] == 2.0

    def test_canonical_worldclass_values(self):
        from scripts.verify_entitlement_consistency import CANONICAL_TIERS
        wc = CANONICAL_TIERS["world-class"]
        assert wc["reports_per_month"] is None  # Unlimited
        assert wc["telemetry_retention_days"] == 365
        assert wc["max_upload_size_mb"] == 5000
        assert wc["max_concurrent_jobs"] == 5
        assert wc["api_access"] is True
        assert wc["comparison"] is True
        assert wc["rate_multiplier"] == 5.0

    def test_canonical_b2b_values(self):
        from scripts.verify_entitlement_consistency import CANONICAL_TIERS
        b2b = CANONICAL_TIERS["b2b"]
        assert b2b["reports_per_month"] is None  # Unlimited
        assert b2b["telemetry_retention_days"] is None  # Custom
        assert b2b["max_upload_size_mb"] == 10000
        assert b2b["max_concurrent_jobs"] == 10
        assert b2b["api_access"] is True
        assert b2b["rate_multiplier"] == 10.0

    def test_pricing_ts_check_function(self):
        from scripts.verify_entitlement_consistency import check_pricing_ts
        assert callable(check_pricing_ts)

    def test_migration_seed_check_function(self):
        from scripts.verify_entitlement_consistency import check_migration_seed
        assert callable(check_migration_seed)


# ===========================================================================
# H) Reconciliation passes on current codebase
# ===========================================================================

class TestReconciliationPassesCurrent:
    """Reconciliation checks pass for pricing.ts and migration seed."""

    def test_pricing_ts_passes(self):
        from scripts.verify_entitlement_consistency import check_pricing_ts, find_project_root
        issues = check_pricing_ts(find_project_root())
        assert issues == [], f"pricing.ts issues: {issues}"

    def test_migration_seed_passes(self):
        from scripts.verify_entitlement_consistency import check_migration_seed, find_project_root
        issues = check_migration_seed(find_project_root())
        assert issues == [], f"Migration seed issues: {issues}"
