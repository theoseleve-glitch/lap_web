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
from web.idempotency import idempotent

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
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    conn = get_pg_connection()

    row = conn.execute(
        "SELECT plan_tier, subscription_status, stripe_customer_id, "
        "stripe_subscription_id FROM users WHERE id = %(uid)s",
        {"uid": user_id},
    ).fetchone()

    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    user = dict(row) if not isinstance(row, dict) else row
    sub_id = user.get("stripe_subscription_id")

    result = {
        "plan_tier": user.get("plan_tier") or "locked",
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
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    conn = get_pg_connection()

    row = conn.execute(
        "SELECT stripe_customer_id FROM users WHERE id = %(uid)s",
        {"uid": user_id},
    ).fetchone()

    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    customer_id = (dict(row) if not isinstance(row, dict) else row).get("stripe_customer_id")
    if not customer_id:
        return api_response({"invoices": []})

    try:
        limit = min(int(request.args.get("limit", 10)), 50)
    except (ValueError, TypeError):
        limit = 10
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
        # A Stripe API failure must NOT masquerade as "no invoices" (an empty
        # 200) — that hides the outage and the client can't retry. Return a
        # real error envelope so the UI can show "billing history temporarily
        # unavailable". (The empty-200 early-returns above are legitimate: no
        # Stripe customer / Stripe not configured.)
        logger.warning("Failed to fetch invoices for customer %s", customer_id, exc_info=True)
        return api_error(
            ErrorCode.SERVICE_UNAVAILABLE,
            "Billing history is temporarily unavailable. Please try again shortly.",
            status=503,
        )


# ---------------------------------------------------------------------------
# GET /usage — current month usage summary
# ---------------------------------------------------------------------------

@bp.route("/usage", methods=["GET"])
@rate_limit(tier="read")
def get_usage():
    """Return current month usage summary from usage_monthly table."""
    user_id = getattr(g, "current_user_id", None)
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
    first_of_month = date.today().replace(day=1).isoformat()

    rows = conn.execute(
        "SELECT event_type, total FROM usage_monthly "
        "WHERE workspace_id = %(wsid)s AND period_start = %(period)s",
        {"wsid": workspace_id, "period": first_of_month},
    ).fetchall()

    usage = {}
    for row in rows:
        r = dict(row) if not isinstance(row, dict) else row
        usage[r["event_type"]] = r["total"]

    analyses_limit = entitlements.get("analyses_per_month")
    analyses_used = usage.get("analyses", 0)

    # Calculate days until reset
    today = date.today()
    if today.month == 12:
        next_month = date(today.year + 1, 1, 1)
    else:
        next_month = date(today.year, today.month + 1, 1)
    days_until_reset = (next_month - today).days

    resets_at = next_month.isoformat()

    result = {
        "period": today.strftime("%Y-%m"),
        "days_until_reset": days_until_reset,
        "analyses": {
            "used": analyses_used,
            "limit": analyses_limit,
            "remaining": (
                None if analyses_limit is None or analyses_limit == -1
                else max(0, analyses_limit - analyses_used)
            ),
            "resets": resets_at,
        },
        "api_calls": {
            "used": usage.get("api_call", 0),
            "limit": 0 if not entitlements.get("api_access") else None,
            "remaining": 0 if not entitlements.get("api_access") else None,
        },
        "upload_volume_mb": {
            "used": usage.get("upload_volume_mb", 0),
            "limit": entitlements.get("upload_volume_mb_per_month"),
            "remaining": (
                None if entitlements.get("upload_volume_mb_per_month") in (None, -1)
                else max(0, (entitlements.get("upload_volume_mb_per_month") or 0) - usage.get("upload_volume_mb", 0))
            ),
            "resets": resets_at,
        },
    }

    return api_response(result)


# ---------------------------------------------------------------------------
# POST /portal — generate Stripe Customer Portal URL
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# POST /checkout — start a subscription Checkout Session (Founding-50 aware)
# ---------------------------------------------------------------------------

TRIAL_DAYS = 30


@bp.route("/checkout", methods=["POST"])
@rate_limit(tier="write")
@idempotent
def create_checkout():
    """Create a Stripe Checkout Session for the single membership plan.

    Founding-50: if a capacity slot is available it is reserved (race-safe, hard
    ≤50 cap) and the buyer gets the €14.90 founding price; otherwise the €19.90
    standard price. Both include a 30-day free trial.

    FAILS LOUD: a missing secret/price or a Stripe error returns a real 4xx/5xx —
    never a 200 'success' that quietly took no money (the old Worker behaviour).
    """
    standard_price = os.environ.get("STRIPE_PRICE_STANDARD_MONTHLY", "")
    founding_price = os.environ.get("STRIPE_PRICE_FOUNDING_MONTHLY", "")

    stripe = _get_stripe()
    if stripe is None:
        return api_error(ErrorCode.INTERNAL_ERROR, "Payments are not configured", status=503)
    if not standard_price:
        return api_error(ErrorCode.INTERNAL_ERROR, "Membership price not configured", status=503)

    body = request.get_json(silent=True) or {}
    email = body.get("email") or None

    from web.founding import attach_session, release_slot, reserve_slot

    conn = get_pg_connection()

    # Reserve a founding slot (race-safe). Commit the hold immediately so we don't
    # hold a row lock across the external Stripe call; the slot expires if unpaid.
    slot_no = reserve_slot(conn, email) if founding_price else None
    if slot_no is not None:
        conn.commit()
    price_id = founding_price if slot_no is not None else standard_price
    offer = "founding" if slot_no is not None else "standard"

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{FRONTEND_URL}/thank-you/book",
            cancel_url=f"{FRONTEND_URL}/pricing?checkout=cancelled",
            customer_email=email,
            allow_promotion_codes=True,
            subscription_data={"trial_period_days": TRIAL_DAYS},
            metadata={
                "plan_tier": "world-class",
                "offer": offer,
                "founding_slot_no": str(slot_no) if slot_no is not None else "",
            },
        )
    except Exception:
        logger.exception("Stripe checkout session creation failed (offer=%s)", offer)
        if slot_no is not None:
            try:
                release_slot(conn, slot_no)
                conn.commit()
            except Exception:
                logger.warning("Failed to release founding slot %s after checkout error", slot_no)
        return api_error(ErrorCode.INTERNAL_ERROR, "Could not start checkout", status=502)

    if slot_no is not None:
        attach_session(conn, slot_no, session.id)
        conn.commit()

    return api_response({"checkout_url": session.url, "offer": offer, "founding_slot_no": slot_no})


@bp.route("/portal", methods=["POST"])
@rate_limit(tier="write")
def create_portal():
    """Generate a Stripe Customer Portal URL for plan management."""
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    conn = get_pg_connection()

    row = conn.execute(
        "SELECT stripe_customer_id FROM users WHERE id = %(uid)s",
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

    # Open-redirect guard: return_url must start with our frontend origin.
    if not return_url.startswith(FRONTEND_URL):
        return_url = f"{FRONTEND_URL}/app/account/billing"

    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url,
        )
        try:
            from web.metrics import incr_counter
            incr_counter("portal_session_created")
        except Exception:
            pass
        return api_response({"portal_url": session.url})
    except Exception:
        logger.exception("Failed to create Stripe portal session")
        return api_error(ErrorCode.INTERNAL_ERROR, "Could not create portal session", status=500)


# ---------------------------------------------------------------------------
# POST /validate-switch — check downgrade constraints before plan change
# ---------------------------------------------------------------------------

@bp.route("/validate-switch", methods=["POST"])
@rate_limit(tier="write")
def validate_plan_switch():
    """Check whether switching to *target_plan* would violate usage constraints.

    Returns ``{ok: true, data: {allowed: true, ...}}`` or
    ``{ok: true, data: {allowed: false, violations: [...]}}``
    so the frontend can warn the user before sending them to the Stripe portal.
    """
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    workspace_id = getattr(g, "workspace_id", None)
    if workspace_id is None:
        return api_error(ErrorCode.FORBIDDEN, "No workspace context", status=403)

    body = request.get_json(silent=True) or {}
    target_plan = (body.get("target_plan") or "").lower().replace("-", "_")

    if not target_plan:
        return api_error(ErrorCode.VALIDATION_ERROR, "target_plan is required", status=400)

    from auth.entitlements import PLAN_ENTITLEMENTS, get_plan_entitlements

    if target_plan not in PLAN_ENTITLEMENTS and target_plan not in ("locked",):
        return api_error(ErrorCode.VALIDATION_ERROR, f"Unknown plan: {target_plan}", status=400)

    conn = get_pg_connection()

    # Current plan
    row = conn.execute(
        "SELECT plan_tier FROM users WHERE id = %(uid)s",
        {"uid": user_id},
    ).fetchone()
    current_plan = ((dict(row) if not isinstance(row, dict) else row).get("plan_tier") or "locked") if row else "locked"

    target_ent = get_plan_entitlements(target_plan)
    violations = []

    # 1. Workspace member count
    member_row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM workspace_members WHERE workspace_id = %(wsid)s",
        {"wsid": workspace_id},
    ).fetchone()
    member_count = int((dict(member_row) if not isinstance(member_row, dict) else member_row).get("cnt", 0)) if member_row else 0
    max_members = target_ent.get("max_workspace_members", 1)
    if max_members != -1 and member_count > max_members:
        violations.append({
            "constraint": "max_workspace_members",
            "current_value": member_count,
            "target_limit": max_members,
            "message": f"Your workspace has {member_count} members but the target plan allows {max_members}.",
        })

    # 2. Data retention — warn if retention would be shorter
    current_ent = get_plan_entitlements(current_plan)
    current_retention = current_ent.get("raw_retention_days", 30)
    target_retention = target_ent.get("raw_retention_days", 30)
    if target_retention < current_retention:
        violations.append({
            "constraint": "raw_retention_days",
            "current_value": current_retention,
            "target_limit": target_retention,
            "message": f"Data retention drops from {current_retention} to {target_retention} days. Older data may be purged.",
        })

    # 3. Feature loss warnings (non-blocking)
    feature_checks = [
        ("api_access", "API Access"),
        ("comparison_progress", "Session Comparison"),
        ("coaching_drills", "Coaching Drills"),
        ("viz_workspace", "Visualization Workspace"),
        ("pdf_reports", "PDF Reports"),
    ]
    lost_features = []
    for key, label in feature_checks:
        if current_ent.get(key) and not target_ent.get(key):
            lost_features.append(label)

    try:
        from web.metrics import incr_counter
        incr_counter("plan_switch_validated")
    except Exception:
        pass

    return api_response({
        "allowed": len(violations) == 0,
        "current_plan": current_plan,
        "target_plan": target_plan,
        "violations": violations,
        "lost_features": lost_features,
    })


# ---------------------------------------------------------------------------
# GET/PUT /profile — billing profile (EU/FR VAT, company info)
# ---------------------------------------------------------------------------

_VALID_BILLING_TYPES = {"b2c", "b2b"}
_PROFILE_FIELDS = [
    "billing_type", "company_name", "vat_id",
    "address_line1", "address_line2", "city",
    "postal_code", "state_region", "country_code",
]


@bp.route("/profile", methods=["GET"])
@rate_limit(tier="read")
def get_billing_profile():
    """Return the workspace's billing profile (company, VAT, address)."""
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    workspace_id = getattr(g, "workspace_id", None)
    if workspace_id is None:
        return api_error(ErrorCode.FORBIDDEN, "No workspace context", status=403)

    conn = get_pg_connection()
    row = conn.execute(
        "SELECT billing_type, company_name, vat_id, "
        "address_line1, address_line2, city, postal_code, state_region, country_code "
        "FROM billing_profiles WHERE workspace_id = %(wsid)s",
        {"wsid": workspace_id},
    ).fetchone()

    if row is None:
        return api_response({
            "billing_type": "b2c",
            "company_name": None,
            "vat_id": None,
            "address_line1": None,
            "address_line2": None,
            "city": None,
            "postal_code": None,
            "state_region": None,
            "country_code": None,
        })

    profile = dict(row) if not isinstance(row, dict) else row
    return api_response(profile)


@bp.route("/profile", methods=["PUT"])
@rate_limit(tier="write")
def update_billing_profile():
    """Create or update the workspace's billing profile.

    Syncs company/VAT info to the Stripe customer if configured.
    """
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    workspace_id = getattr(g, "workspace_id", None)
    if workspace_id is None:
        return api_error(ErrorCode.FORBIDDEN, "No workspace context", status=403)

    body = request.get_json(silent=True) or {}

    billing_type = body.get("billing_type", "b2c")
    if billing_type not in _VALID_BILLING_TYPES:
        return api_error(ErrorCode.VALIDATION_ERROR, "billing_type must be 'b2c' or 'b2b'", status=400)

    # Validate country_code (ISO 3166-1 alpha-2)
    country_code = body.get("country_code")
    if country_code and (len(country_code) != 2 or not country_code.isalpha()):
        return api_error(ErrorCode.VALIDATION_ERROR, "country_code must be a 2-letter ISO code", status=400)

    # Validate VAT ID format (basic check: 2-letter country prefix + 2-15 chars)
    vat_id = body.get("vat_id")
    if vat_id:
        vat_id = vat_id.strip().upper().replace(" ", "")
        if len(vat_id) < 4 or len(vat_id) > 17:
            return api_error(ErrorCode.VALIDATION_ERROR, "VAT ID format invalid", status=400)

    conn = get_pg_connection()

    # Upsert billing profile
    conn.execute(
        "INSERT INTO billing_profiles (workspace_id, billing_type, company_name, vat_id, "
        "address_line1, address_line2, city, postal_code, state_region, country_code, updated_at) "
        "VALUES (%(wsid)s, %(btype)s, %(company)s, %(vat)s, "
        "%(a1)s, %(a2)s, %(city)s, %(postal)s, %(state)s, %(cc)s, NOW()) "
        "ON CONFLICT (workspace_id) "
        "DO UPDATE SET billing_type = %(btype)s, company_name = %(company)s, vat_id = %(vat)s, "
        "address_line1 = %(a1)s, address_line2 = %(a2)s, city = %(city)s, "
        "postal_code = %(postal)s, state_region = %(state)s, country_code = %(cc)s, "
        "updated_at = NOW()",
        {
            "wsid": workspace_id,
            "btype": billing_type,
            "company": body.get("company_name"),
            "vat": vat_id,
            "a1": body.get("address_line1"),
            "a2": body.get("address_line2"),
            "city": body.get("city"),
            "postal": body.get("postal_code"),
            "state": body.get("state_region"),
            "cc": country_code.upper() if country_code else None,
        },
    )
    conn.commit()

    # Sync to Stripe customer if available
    _sync_billing_profile_to_stripe(conn, user_id, body, vat_id)

    try:
        from web.metrics import incr_counter
        incr_counter("billing_profile_updated")
    except Exception:
        pass

    return api_response({"updated": True})


def _sync_billing_profile_to_stripe(conn, user_id: int, body: dict, vat_id: str | None):
    """Best-effort sync of billing info to Stripe customer."""
    stripe = _get_stripe()
    if stripe is None:
        return

    row = conn.execute(
        "SELECT stripe_customer_id FROM users WHERE id = %(uid)s",
        {"uid": user_id},
    ).fetchone()
    if row is None:
        return

    customer_id = (dict(row) if not isinstance(row, dict) else row).get("stripe_customer_id")
    if not customer_id:
        return

    try:
        update_params = {}
        if body.get("company_name"):
            update_params["name"] = body["company_name"]
        if body.get("address_line1"):
            update_params["address"] = {
                "line1": body.get("address_line1", ""),
                "line2": body.get("address_line2", ""),
                "city": body.get("city", ""),
                "postal_code": body.get("postal_code", ""),
                "state": body.get("state_region", ""),
                "country": body.get("country_code", ""),
            }

        if update_params:
            stripe.Customer.modify(customer_id, **update_params)

        # Set VAT ID (tax_ids) if provided
        if vat_id:
            # Determine tax ID type from prefix
            prefix = vat_id[:2].upper()
            tax_type_map = {
                "FR": "eu_vat", "DE": "eu_vat", "IT": "eu_vat",
                "ES": "eu_vat", "NL": "eu_vat", "BE": "eu_vat",
                "AT": "eu_vat", "PT": "eu_vat", "IE": "eu_vat",
                "LU": "eu_vat", "FI": "eu_vat", "EL": "eu_vat",
                "GB": "gb_vat", "CH": "ch_vat",
            }
            tax_type = tax_type_map.get(prefix, "eu_vat")
            try:
                stripe.Customer.create_tax_id(customer_id, type=tax_type, value=vat_id)
            except Exception:
                logger.warning("Failed to set VAT ID on Stripe customer %s", customer_id)
    except Exception:
        logger.warning("Failed to sync billing profile to Stripe", exc_info=True)
