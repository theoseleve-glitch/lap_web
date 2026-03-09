#!/usr/bin/env python3
"""Verify entitlement consistency across frontend, backend, and Stripe.

Checks that pricing.ts, plan_definitions DB, and Stripe products are in sync.
Exit code 0 = all consistent, 1 = discrepancies found.

Usage:
    python scripts/verify_entitlement_consistency.py
    python scripts/verify_entitlement_consistency.py --skip-stripe   # CI without Stripe keys
    python scripts/verify_entitlement_consistency.py --skip-db       # frontend-only check
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Canonical entitlement values (from docs/entitlement-matrix.md)
# ---------------------------------------------------------------------------

CANONICAL_TIERS = {
    "demo": {
        "display_name": "Demo",
        "reports_per_month": 1,
        "telemetry_retention_days": 30,
        "max_upload_size_mb": 500,
        "max_concurrent_jobs": 1,
        "api_access": False,
        "comparison": False,
        "coaching_plans": False,
        "visualization": False,
        "live_monitoring": False,
        "rate_multiplier": 1.0,
    },
    "racer": {
        "display_name": "Racer",
        "reports_per_month": 10,
        "telemetry_retention_days": 90,
        "max_upload_size_mb": 2000,
        "max_concurrent_jobs": 2,
        "api_access": False,
        "comparison": False,
        "coaching_plans": True,
        "visualization": True,
        "live_monitoring": True,
        "rate_multiplier": 2.0,
        "price_monthly_eur": 899,
        "price_annual_eur": 6900,
    },
    "world-class": {
        "display_name": "World-Class",
        "reports_per_month": None,  # Unlimited
        "telemetry_retention_days": 365,
        "max_upload_size_mb": 5000,
        "max_concurrent_jobs": 5,
        "api_access": True,
        "comparison": True,
        "coaching_plans": True,
        "visualization": True,
        "live_monitoring": True,
        "rate_multiplier": 5.0,
        "price_monthly_eur": 1399,
        "price_annual_eur": 10900,
    },
    "b2b": {
        "display_name": "B2B",
        "reports_per_month": None,  # Unlimited
        "telemetry_retention_days": None,  # Custom
        "max_upload_size_mb": 10000,
        "max_concurrent_jobs": 10,
        "api_access": True,
        "comparison": True,
        "coaching_plans": True,
        "visualization": True,
        "live_monitoring": True,
        "rate_multiplier": 10.0,
    },
}


def find_project_root() -> Path:
    """Walk up from this script to find the project root."""
    here = Path(__file__).resolve().parent
    # scripts/ is one level below project root
    root = here.parent
    if (root / "telemetry_tool").is_dir():
        return root
    return here


# ---------------------------------------------------------------------------
# 1. Parse pricing.ts
# ---------------------------------------------------------------------------

def check_pricing_ts(project_root: Path) -> list[str]:
    """Parse pricing.ts and check against canonical values."""
    issues: list[str] = []
    pricing_path = project_root / "lap-website" / "src" / "data" / "pricing.ts"

    if not pricing_path.exists():
        issues.append(f"MISSING: {pricing_path}")
        return issues

    content = pricing_path.read_text(encoding="utf-8")

    # Check tier slugs exist
    for tier in ["demo", "racer", "world-class"]:
        if f"slug: '{tier}'" not in content:
            issues.append(f"PRICING.TS: tier slug '{tier}' not found")

    # Check prices (use numeric part to avoid encoding issues with €)
    price_checks = {
        "9 / mo": "racer monthly",
        "72 / yr": "racer annual",
        "14 / mo": "world-class monthly",
        "108 / yr": "world-class annual",
    }
    for price_str, label in price_checks.items():
        if price_str not in content:
            issues.append(f"PRICING.TS: {label} price '{price_str}' not found")

    # Check retention values
    retention_checks = {
        "1 month": "demo retention",
        "3 months": "racer retention",
        "12 months": "world-class retention",
    }
    for value, label in retention_checks.items():
        if value not in content:
            issues.append(f"PRICING.TS: {label} '{value}' not found")

    # Check report limits
    if "1 full report" not in content and "1 report" not in content:
        issues.append("PRICING.TS: demo '1 report' limit not found")
    if "10 / month" not in content and "10/mo" not in content:
        issues.append("PRICING.TS: racer '10 reports' limit not found")
    if "Unlimited" not in content:
        issues.append("PRICING.TS: world-class 'Unlimited' reports not found")

    return issues


# ---------------------------------------------------------------------------
# 2. Query plan_definitions DB
# ---------------------------------------------------------------------------

def check_plan_definitions_db(project_root: Path) -> list[str]:
    """Check plan_definitions table against canonical values."""
    issues: list[str] = []

    # Add telemetry_tool to path
    tt_path = str(project_root / "telemetry_tool")
    if tt_path not in sys.path:
        sys.path.insert(0, tt_path)

    try:
        from web.db_pg import get_pg_connection
    except ImportError:
        issues.append("DB: cannot import web.db_pg (PG not configured)")
        return issues

    try:
        conn = get_pg_connection()
        cur = conn.execute("SELECT * FROM plan_definitions ORDER BY tier")
        rows = cur.fetchall()
    except Exception as exc:
        issues.append(f"DB: query failed: {exc}")
        return issues

    db_tiers = {}
    for row in rows:
        r = dict(row) if not isinstance(row, dict) else row
        db_tiers[r["tier"]] = r

    # Check all canonical tiers exist
    for tier in CANONICAL_TIERS:
        if tier not in db_tiers:
            issues.append(f"DB: tier '{tier}' not in plan_definitions")
            continue

        db = db_tiers[tier]
        canon = CANONICAL_TIERS[tier]

        # Check numeric values
        for key in ["reports_per_month", "telemetry_retention_days",
                     "max_upload_size_mb", "max_concurrent_jobs"]:
            if key in canon and key in db:
                if db[key] != canon[key]:
                    issues.append(
                        f"DB: {tier}.{key} = {db[key]}, expected {canon[key]}"
                    )

        # Check boolean values
        for key in ["api_access", "comparison", "coaching_plans",
                     "visualization", "live_monitoring"]:
            if key in canon and key in db:
                # DB may store as boolean column or within JSON
                db_val = db.get(key)
                if key == "comparison":
                    db_val = db.get("comparison_enabled", db_val)
                elif key == "coaching_plans":
                    db_val = db.get("coaching_plans_enabled", db_val)
                elif key == "visualization":
                    db_val = db.get("visualization_enabled", db_val)

                if db_val is not None and bool(db_val) != canon[key]:
                    issues.append(
                        f"DB: {tier}.{key} = {db_val}, expected {canon[key]}"
                    )

    # Check for extra tiers in DB not in canonical
    for tier in db_tiers:
        if tier not in CANONICAL_TIERS:
            issues.append(f"DB: unexpected tier '{tier}' in plan_definitions")

    return issues


# ---------------------------------------------------------------------------
# 3. Query Stripe API
# ---------------------------------------------------------------------------

def check_stripe_products() -> list[str]:
    """Check Stripe products/prices against canonical values."""
    issues: list[str] = []

    try:
        import stripe
    except ImportError:
        issues.append("STRIPE: stripe package not installed")
        return issues

    api_key = os.environ.get("STRIPE_SECRET_KEY")
    if not api_key:
        issues.append("STRIPE: STRIPE_SECRET_KEY not set (skipped)")
        return issues

    stripe.api_key = api_key

    # Check products exist
    products = stripe.Product.list(limit=100, active=True)
    product_names = {p.name for p in products.auto_paging_iter()}

    expected_products = ["Lap Coach Racer", "Lap Coach World-Class"]
    for name in expected_products:
        if name not in product_names:
            issues.append(f"STRIPE: product '{name}' not found")

    # Check prices
    expected_prices = {
        "racer_monthly": 899,
        "racer_annual": 6900,
        "worldclass_monthly": 1399,
        "worldclass_annual": 10900,
    }

    prices = stripe.Price.list(limit=100, active=True)
    price_map = {}
    for p in prices.auto_paging_iter():
        if p.nickname:
            price_map[p.nickname] = p.unit_amount

    for nickname, expected_amount in expected_prices.items():
        if nickname not in price_map:
            issues.append(f"STRIPE: price '{nickname}' not found")
        elif price_map[nickname] != expected_amount:
            issues.append(
                f"STRIPE: price '{nickname}' = {price_map[nickname]}, "
                f"expected {expected_amount}"
            )

    return issues


# ---------------------------------------------------------------------------
# 4. Check migration seed data
# ---------------------------------------------------------------------------

def check_migration_seed(project_root: Path) -> list[str]:
    """Check that migration 019 seeds correct plan_definitions."""
    issues: list[str] = []
    migration_path = (
        project_root / "telemetry_tool" / "alembic" / "versions"
        / "019_core_data_model.py"
    )

    if not migration_path.exists():
        issues.append(f"MIGRATION: {migration_path.name} not found")
        return issues

    content = migration_path.read_text()

    # Check seed tiers
    for tier in ["demo", "racer", "world-class", "b2b"]:
        if f"'{tier}'" not in content:
            issues.append(f"MIGRATION: tier '{tier}' not in seed data")

    # Check key values
    seed_checks = {
        "1, 500, 30": "demo (1 report, 500MB, 30 days)",
        "10, 2000, 90": "racer (10 reports, 2000MB, 90 days)",
        "NULL, 5000, 365": "world-class (unlimited, 5000MB, 365 days)",
        "NULL, 10000, NULL": "b2b (unlimited, 10000MB, custom)",
    }
    for pattern, label in seed_checks.items():
        if pattern not in content:
            issues.append(f"MIGRATION: seed data for {label} not found")

    return issues


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Verify entitlement consistency across frontend, backend, and Stripe"
    )
    parser.add_argument("--skip-stripe", action="store_true",
                        help="Skip Stripe API checks")
    parser.add_argument("--skip-db", action="store_true",
                        help="Skip database checks")
    args = parser.parse_args()

    project_root = find_project_root()
    all_issues: list[str] = []

    print("Verifying entitlement consistency...")
    print(f"Project root: {project_root}\n")

    # 1. pricing.ts
    print("[1/4] Checking pricing.ts ...")
    issues = check_pricing_ts(project_root)
    all_issues.extend(issues)
    print(f"  {'PASS' if not issues else 'FAIL'} ({len(issues)} issues)")
    for i in issues:
        print(f"    - {i}")

    # 2. Migration seed data
    print("[2/4] Checking migration seed data ...")
    issues = check_migration_seed(project_root)
    all_issues.extend(issues)
    print(f"  {'PASS' if not issues else 'FAIL'} ({len(issues)} issues)")
    for i in issues:
        print(f"    - {i}")

    # 3. plan_definitions DB
    if args.skip_db:
        print("[3/4] Skipping database checks (--skip-db)")
    else:
        print("[3/4] Checking plan_definitions DB ...")
        issues = check_plan_definitions_db(project_root)
        all_issues.extend(issues)
        print(f"  {'PASS' if not issues else 'FAIL'} ({len(issues)} issues)")
        for i in issues:
            print(f"    - {i}")

    # 4. Stripe products
    if args.skip_stripe:
        print("[4/4] Skipping Stripe checks (--skip-stripe)")
    else:
        print("[4/4] Checking Stripe products ...")
        issues = check_stripe_products()
        all_issues.extend(issues)
        print(f"  {'PASS' if not issues else 'FAIL'} ({len(issues)} issues)")
        for i in issues:
            print(f"    - {i}")

    # Summary
    print(f"\n{'='*50}")
    if all_issues:
        print(f"FAIL: {len(all_issues)} discrepancies found")
        sys.exit(1)
    else:
        print("PASS: All entitlements consistent")
        sys.exit(0)


if __name__ == "__main__":
    main()
