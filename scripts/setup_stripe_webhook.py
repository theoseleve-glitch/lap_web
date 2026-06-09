#!/usr/bin/env python3
"""Create (idempotently) the LAP production Stripe webhook endpoint.

Run with STRIPE_SECRET_KEY set (live key on prod). Prints ONLY the signing
secret (whsec_...) to stdout so the caller can capture it into the env without
echoing it; diagnostics go to stderr. Exit codes:
  0 = created, secret on stdout
  2 = an endpoint with this URL already exists (secret is only shown at
      creation time; roll it in the dashboard or delete+recreate if you need it)
  1 = error

Usage:
    STRIPE_SECRET_KEY=sk_live_xxx python scripts/setup_stripe_webhook.py
"""
from __future__ import annotations

import os
import sys

URL = "https://api.lap-coach.racing/api/v1/billing/webhook"
EVENTS = [
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "customer.subscription.paused",
    "customer.subscription.resumed",
    "customer.subscription.trial_will_end",
    "invoice.paid",
    "invoice.payment_failed",
    "charge.refunded",
]


def main() -> int:
    try:
        import stripe
    except ImportError:
        sys.stderr.write("stripe package not installed\n")
        return 1

    key = os.environ.get("STRIPE_SECRET_KEY")
    if not key:
        sys.stderr.write("STRIPE_SECRET_KEY not set\n")
        return 1
    stripe.api_key = key

    for e in stripe.WebhookEndpoint.list(limit=100).auto_paging_iter():
        if getattr(e, "url", None) == URL:
            sys.stderr.write(f"EXISTS:{e.id} status={e.status}\n")
            return 2

    ep = stripe.WebhookEndpoint.create(
        url=URL, enabled_events=EVENTS, description="LAP prod billing webhook"
    )
    sys.stderr.write(f"CREATED:{ep.id} events={len(EVENTS)}\n")
    sys.stdout.write(ep.secret)  # secret ONLY on stdout
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
