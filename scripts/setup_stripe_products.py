#!/usr/bin/env python3
"""Create/update Stripe products and prices for Lap Coach.

June-8 model: ONE self-serve product (the membership). Idempotent — uses
metadata tags to find existing products/prices. Run with STRIPE_SECRET_KEY set.

Usage:
    STRIPE_SECRET_KEY=sk_test_xxx python scripts/setup_stripe_products.py
    STRIPE_SECRET_KEY=sk_test_xxx python scripts/setup_stripe_products.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys

# ---------------------------------------------------------------------------
# Product / Price definitions (canonical source: docs/entitlement-matrix.md)
# ---------------------------------------------------------------------------

PRODUCTS = [
    {
        # Founding-50 launch offer: ONE full-access membership.
        # Standard €19.90/mo; the first 50 founders pay €14.90/mo (same product,
        # same entitlement, discounted price). The server-side cap picks which
        # price at checkout. Canonical env names below are read IDENTICALLY by
        # frontend (stripe-billing.ts), backend (billing.py), and the Worker —
        # this is the converged naming that kills the PERFORMANCE/PRO_RACER vs
        # RACER/WORLDCLASS split-brain. Every paying member receives the
        # internal `world-class` entitlement (see docs/entitlement-matrix.md).
        "name": "Lap Coach Membership",
        "metadata_key": "lap_coach_membership",
        "description": "Full access — €19.90/mo (€14.90/mo for the first 50 founding members)",
        "prices": [
            {
                "nickname": "standard_monthly",
                "unit_amount": 1990,     # €19.90 in cents
                "currency": "eur",
                "interval": "month",
                "env_key": "STRIPE_PRICE_STANDARD_MONTHLY",
            },
            {
                "nickname": "founding_monthly",
                "unit_amount": 1490,     # €14.90 in cents
                "currency": "eur",
                "interval": "month",
                "env_key": "STRIPE_PRICE_FOUNDING_MONTHLY",
            },
        ],
    },
]


def get_stripe():
    """Import and configure stripe module."""
    try:
        import stripe
    except ImportError:
        print("ERROR: stripe package not installed. Run: pip install stripe")
        sys.exit(1)

    api_key = os.environ.get("STRIPE_SECRET_KEY")
    if not api_key:
        print("ERROR: STRIPE_SECRET_KEY environment variable not set")
        sys.exit(1)

    stripe.api_key = api_key
    return stripe


def _metadata_value(obj, key):
    """Read a metadata key from a Stripe object, version-robustly.

    StripeObject does NOT support .get() (intercepted by __getattr__) and is
    not dict()-able, but it supports `in` (__contains__) and [] (__getitem__).
    """
    md = getattr(obj, "metadata", None)
    if md is None:
        return None
    try:
        return md[key] if key in md else None
    except Exception:
        return None


def find_existing_product(stripe, metadata_key: str):
    """Find product by metadata tag (idempotent lookup)."""
    products = stripe.Product.list(limit=100, active=True)
    for p in products.auto_paging_iter():
        if _metadata_value(p, "lap_coach_product") == metadata_key:
            return p
    return None


def find_existing_price(stripe, product_id: str, nickname: str):
    """Find price by nickname on a product (idempotent lookup)."""
    prices = stripe.Price.list(product=product_id, limit=100, active=True)
    for p in prices.auto_paging_iter():
        if getattr(p, "nickname", None) == nickname:
            return p
    return None


def setup_products(dry_run: bool = False):
    """Create or update all Stripe products and prices."""
    stripe = get_stripe()

    env_output: dict[str, str] = {}

    for product_def in PRODUCTS:
        print(f"\n{'='*60}")
        print(f"Product: {product_def['name']}")
        print(f"{'='*60}")

        # Find or create product
        existing = find_existing_product(stripe, product_def["metadata_key"])

        if existing:
            print(f"  Found existing product: {existing.id}")
            product = existing

            if not dry_run:
                # Update description if changed
                stripe.Product.modify(
                    existing.id,
                    description=product_def["description"],
                )
        else:
            print(f"  Creating new product...")
            if dry_run:
                print(f"  [DRY RUN] Would create product: {product_def['name']}")
                product = None
            else:
                product = stripe.Product.create(
                    name=product_def["name"],
                    description=product_def["description"],
                    metadata={"lap_coach_product": product_def["metadata_key"]},
                )
                print(f"  Created product: {product.id}")

        # Create prices
        for price_def in product_def["prices"]:
            print(f"\n  Price: {price_def['nickname']}")
            print(f"    Amount: {price_def['unit_amount']} {price_def['currency']}")
            print(f"    Interval: {price_def['interval']}")

            if product:
                existing_price = find_existing_price(
                    stripe, product.id, price_def["nickname"]
                )
            else:
                existing_price = None

            if existing_price:
                print(f"    Found existing price: {existing_price.id}")
                env_output[price_def["env_key"]] = existing_price.id
            else:
                if dry_run:
                    print(f"    [DRY RUN] Would create price: {price_def['nickname']}")
                    env_output[price_def["env_key"]] = "price_DRY_RUN"
                elif product:
                    price = stripe.Price.create(
                        product=product.id,
                        nickname=price_def["nickname"],
                        unit_amount=price_def["unit_amount"],
                        currency=price_def["currency"],
                        recurring={"interval": price_def["interval"]},
                    )
                    print(f"    Created price: {price.id}")
                    env_output[price_def["env_key"]] = price.id

    # Output environment variables
    if env_output:
        print(f"\n{'='*60}")
        print("Environment variables for .env.production:")
        print(f"{'='*60}")
        for key, value in sorted(env_output.items()):
            print(f"{key}={value}")

    return env_output


def main():
    parser = argparse.ArgumentParser(
        description="Set up Stripe products and prices for Lap Coach"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be created without making API calls",
    )
    args = parser.parse_args()

    setup_products(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
