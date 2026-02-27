"""V1 billing API endpoints — subscription info, invoices, usage, portal.

Blueprint: ``/api/v1/billing/`` — provides endpoints for viewing subscription
details, invoice history, current usage, and generating Stripe portal URLs.

These endpoints are READ-ONLY views of billing state (Stripe is source of truth).
The webhook handler in ``billing.py`` handles state mutations from Stripe events.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone

from flask import Blueprint, g, request

from web.api_utils import ErrorCode, api_error, api_response

logger = logging.getLogger(__name__)

bp = Blueprint("api_v1_billing", __name__, url_prefix="/api/v1/billing")

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://www.lap-coach.racing")

# ---- Rate limit import (graceful fallback) ----
try:
    from web.rate_limit import rate_limit
except ImportError:
    def rate_limit(**kwargs):
        def decorator(fn):
            return fn
        return decorator


# ---- Redis cache helpers ----

def _get_redis():
    """Get Redis connection or None."""
    try:
        from web.rate_limit import get_redis
        return get_redis()
    except Exception:
        return None


def _cache_get(key: str) -> dict | None:
    """Get cached JSON value from Redis."""
    r = _get_redis()
    if r is None:
        return None
    try:
        val = r.get(key)
        if val:
            return json.loads(val)
    except Exception:
        pass
    return None


def _cache_set(key: str, value: dict, ttl: int = 300):
    """Cache JSON value in Redis with TTL (default 5 min)."""
    r = _get_redis()
    if r is None:
        return
    try:
        r.setex(key, ttl, json.dumps(value, default=str))
    except Exception:
        pass


# ---- PG connection ----

def get_pg_connection():
    """Get PostgreSQL connection."""
    from web.db_pg import get_pg_connection as _get_pg
    return _get_pg()


# ---- Stripe lazy import ----

def _get_stripe():
    """Import and configure Stripe, or return None."""
    if not STRIPE_SECRET_KEY:
        return None
    try:
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
        return stripe
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# GET /subscription — current subscription details
# ---------------------------------------------------------------------------

@bp.route("/subscription", methods=["GET"])
@rate_limit(tier="read")
def get_subscription():
    """Return current subscription details from Stripe (cached 5min)."""
    user_id = getattr(g, "user_id", None) or getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    conn = get_pg_connection()
    from sqlalchemy import text

    row = conn.execute(
        text(
            "SELECT plan_tier, subscription_status, stripe_customer_id, "
            "stripe_subscription_id FROM users WHERE id = :uid"
        ),
        {"uid": user_id},
    ).fetchone()

    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    user = dict(row) if not isinstance(row, dict) else row
    sub_id = user.get("stripe_subscription_id")

    result = {
        "plan_tier": user.get("plan_tier") or "demo",
        "subscription_status": user.get("subscription_status") or "free",
        "current_period_end": None,
        "cancel_at_period_end": False,
        "payment_method": None,
        "next_invoice_amount": None,
        "next_invoice_currency": None,
    }

    # If there's a Stripe subscription, fetch live details
    if sub_id:
        cache_key = f"billing:sub:{sub_id}"
        cached = _cache_get(cache_key)
        if cached:
            result.update(cached)
        else:
            stripe_data = _fetch_subscription_from_stripe(sub_id)
            if stripe_data:
                result.update(stripe_data)
                _cache_set(cache_key, stripe_data, ttl=300)

    return api_response(result)


def _fetch_subscription_from_stripe(sub_id: str) -> dict | None:
    """Fetch subscription details from Stripe API."""
    stripe = _get_stripe()
    if stripe is None:
        return None

    try:
        sub = stripe.Subscription.retrieve(
            sub_id,
            expand=["default_payment_method", "latest_invoice"],
        )

        result = {
            "current_period_end": (
                datetime.fromtimestamp(sub.current_period_end, tz=timezone.utc).isoformat()
                if sub.current_period_end else None
            ),
            "cancel_at_period_end": bool(sub.cancel_at_period_end),
        }

        # Payment method
        pm = sub.default_payment_method
        if pm and hasattr(pm, "card") and pm.card:
            result["payment_method"] = {
                "brand": pm.card.brand,
                "last4": pm.card.last4,
            }

        # Next invoice
        latest = sub.latest_invoice
        if latest and hasattr(latest, "amount_due"):
            result["next_invoice_amount"] = latest.amount_due
            result["next_invoice_currency"] = latest.currency

        return result
    except Exception:
        logger.warning("Failed to fetch Stripe subscription %s", sub_id, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# GET /invoices — paginated invoice history
# ---------------------------------------------------------------------------

@bp.route("/invoices", methods=["GET"])
@rate_limit(tier="read")
def get_invoices():
    """Return paginated list of past invoices from Stripe."""
    user_id = getattr(g, "user_id", None) or getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    conn = get_pg_connection()
    from sqlalchemy import text

    row = conn.execute(
        text("SELECT stripe_customer_id FROM users WHERE id = :uid"),
        {"uid": user_id},
    ).fetchone()

    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    customer_id = (dict(row) if not isinstance(row, dict) else row).get("stripe_customer_id")
    if not customer_id:
        return api_response({"invoices": []})

    limit = min(int(request.args.get("limit", 10)), 50)
    starting_after = request.args.get("starting_after")

    stripe = _get_stripe()
    if stripe is None:
        return api_response({"invoices": []})

    try:
        params = {"customer": customer_id, "limit": limit}
        if starting_after:
            params["starting_after"] = starting_after

        invoices = stripe.Invoice.list(**params)

        result = []
        for inv in invoices.data:
            result.append({
                "id": inv.id,
                "date": (
                    datetime.fromtimestamp(inv.created, tz=timezone.utc).strftime("%Y-%m-%d")
                    if inv.created else None
                ),
                "amount": inv.amount_due,
                "currency": inv.currency,
                "status": inv.status,
                "pdf_url": inv.invoice_pdf,
            })

        return api_response({
            "invoices": result,
            "has_more": invoices.has_more,
        })
    except Exception:
        logger.warning("Failed to fetch invoices for customer %s", customer_id, exc_info=True)
        return api_response({"invoices": []})


# ---------------------------------------------------------------------------
# GET /usage — current month usage summary
# ---------------------------------------------------------------------------

@bp.route("/usage", methods=["GET"])
@rate_limit(tier="read")
def get_usage():
    """Return current month usage summary from usage_monthly table."""
    user_id = getattr(g, "user_id", None) or getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    workspace_id = getattr(g, "workspace_id", None)
    if workspace_id is None:
        return api_error(ErrorCode.FORBIDDEN, "No workspace context", status=403)

    conn = get_pg_connection()

    # Get plan limits
    from auth.entitlements import get_user_entitlements
    entitlements = get_user_entitlements(conn, user_id, workspace_id)

    # Get current month usage
    from sqlalchemy import text
    first_of_month = date.today().replace(day=1).isoformat()

    rows = conn.execute(
        text(
            "SELECT event_type, total FROM usage_monthly "
            "WHERE workspace_id = :wsid AND period_start = :period"
        ),
        {"wsid": workspace_id, "period": first_of_month},
    ).fetchall()

    usage = {}
    for row in rows:
        r = dict(row) if not isinstance(row, dict) else row
        usage[r["event_type"]] = r["total"]

    reports_limit = entitlements.get("reports_per_month")
    reports_used = usage.get("report_generated", 0)

    # Calculate days until reset
    today = date.today()
    if today.month == 12:
        next_month = date(today.year + 1, 1, 1)
    else:
        next_month = date(today.year, today.month + 1, 1)
    days_until_reset = (next_month - today).days

    result = {
        "period": today.strftime("%Y-%m"),
        "days_until_reset": days_until_reset,
        "reports": {
            "used": reports_used,
            "limit": reports_limit,
            "remaining": (
                None if reports_limit is None
                else max(0, reports_limit - reports_used)
            ),
        },
        "uploads": {
            "used": usage.get("upload", 0),
            "limit": None,  # uploads are unlimited for all paid plans
            "remaining": None,
        },
        "api_calls": {
            "used": usage.get("api_call", 0),
            "limit": 0 if not entitlements.get("api_access") else None,
            "remaining": 0 if not entitlements.get("api_access") else None,
        },
        "storage_mb": {
            "used": usage.get("storage_mb", 0),
            "limit": entitlements.get("max_upload_size_mb"),
            "remaining": (
                None if entitlements.get("max_upload_size_mb") is None
                else max(0, (entitlements.get("max_upload_size_mb") or 0) - usage.get("storage_mb", 0))
            ),
        },
    }

    return api_response(result)


# ---------------------------------------------------------------------------
# POST /portal — generate Stripe Customer Portal URL
# ---------------------------------------------------------------------------

@bp.route("/portal", methods=["POST"])
@rate_limit(tier="write")
def create_portal():
    """Generate a Stripe Customer Portal URL for plan management."""
    user_id = getattr(g, "user_id", None) or getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    conn = get_pg_connection()
    from sqlalchemy import text

    row = conn.execute(
        text("SELECT stripe_customer_id FROM users WHERE id = :uid"),
        {"uid": user_id},
    ).fetchone()

    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    customer_id = (dict(row) if not isinstance(row, dict) else row).get("stripe_customer_id")
    if not customer_id:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "No Stripe customer found. Subscribe to a plan first.",
            status=400,
        )

    stripe = _get_stripe()
    if stripe is None:
        return api_error(ErrorCode.INTERNAL_ERROR, "Stripe not configured", status=503)

    body = request.get_json(silent=True) or {}
    return_url = body.get("return_url", f"{FRONTEND_URL}/app/account/billing")

    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url,
        )
        return api_response({"portal_url": session.url})
    except Exception:
        logger.exception("Failed to create Stripe portal session")
        return api_error(ErrorCode.INTERNAL_ERROR, "Could not create portal session", status=500)
