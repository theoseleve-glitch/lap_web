#!/usr/bin/env python3
"""One-time backfill: sync billing_state from Stripe for all users with stripe_subscription_id.

Usage:
    python scripts/backfill_billing_state.py [--dry-run]

Fetches each user's subscription from Stripe, updates subscription_status
and plan_tier to match Stripe's actual state.  Logs summary counts.

Requires:
    TELEMETRY_PG_URL env var (or defaults)
    STRIPE_SECRET_KEY env var
"""
import logging
import os
import sys
from pathlib import Path

# Add project root to path
_ROOT = Path(__file__).resolve().parent.parent / "telemetry_tool"
sys.path.insert(0, str(_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("backfill_billing")

DRY_RUN = "--dry-run" in sys.argv


def main():
    import stripe
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not stripe.api_key:
        logger.error("STRIPE_SECRET_KEY not set")
        sys.exit(1)

    from web.db_pg import get_pg_connection
    conn = get_pg_connection()

    from billing.state_machine import STRIPE_STATUS_MAP

    # Price ID → tier mapping (same as billing.py)
    price_to_tier = {}
    env_map = {
        "STRIPE_PRICE_RACER_MONTHLY": "racer",
        "STRIPE_PRICE_RACER_ANNUAL": "racer",
        "STRIPE_PRICE_WORLDCLASS_MONTHLY": "world-class",
        "STRIPE_PRICE_WORLDCLASS_ANNUAL": "world-class",
    }
    for env_key, tier in env_map.items():
        price_id = os.environ.get(env_key)
        if price_id:
            price_to_tier[price_id] = tier

    rows = conn.execute(
        "SELECT id, email, stripe_subscription_id, stripe_customer_id, "
        "subscription_status, plan_tier "
        "FROM users WHERE stripe_subscription_id IS NOT NULL"
    ).fetchall()
    users = [dict(r) if not isinstance(r, dict) else r for r in rows]

    logger.info("Found %d users with stripe_subscription_id", len(users))

    healed = 0
    errors = 0

    for user in users:
        uid = user["id"]
        sub_id = user["stripe_subscription_id"]
        local_status = user["subscription_status"] or "free"
        local_tier = user["plan_tier"] or "demo"

        try:
            sub = stripe.Subscription.retrieve(sub_id, expand=["items.data.price"])
            stripe_status = sub.status
            new_status = STRIPE_STATUS_MAP.get(stripe_status, "free")

            # Resolve tier from subscription items
            new_tier = local_tier
            for item in sub.get("items", {}).get("data", []):
                pid = item.get("price", {}).get("id")
                if pid and pid in price_to_tier:
                    new_tier = price_to_tier[pid]
                    break

            needs_update = (local_status != new_status) or (local_tier != new_tier)
            if needs_update:
                if DRY_RUN:
                    logger.info(
                        "[DRY RUN] user %d (%s): status %s→%s, tier %s→%s",
                        uid, user["email"], local_status, new_status,
                        local_tier, new_tier,
                    )
                else:
                    conn.execute(
                        "UPDATE users SET subscription_status = %(status)s, "
                        "plan_tier = %(tier)s WHERE id = %(uid)s",
                        {"status": new_status, "tier": new_tier, "uid": uid},
                    )
                    conn.commit()
                    logger.info(
                        "Healed user %d (%s): status %s→%s, tier %s→%s",
                        uid, user["email"], local_status, new_status,
                        local_tier, new_tier,
                    )
                healed += 1

        except stripe.error.InvalidRequestError:
            logger.warning(
                "Subscription %s not found in Stripe for user %d — marking canceled",
                sub_id, uid,
            )
            if not DRY_RUN:
                conn.execute(
                    "UPDATE users SET subscription_status = 'canceled', "
                    "stripe_subscription_id = NULL WHERE id = %(uid)s",
                    {"uid": uid},
                )
                conn.commit()
            healed += 1
        except Exception:
            logger.exception("Error processing user %d", uid)
            errors += 1

    mode = "[DRY RUN] " if DRY_RUN else ""
    logger.info(
        "%sSummary: checked=%d, healed=%d, errors=%d",
        mode, len(users), healed, errors,
    )


if __name__ == "__main__":
    main()
