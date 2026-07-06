"""Billing Celery tasks: Stripe reconciliation + grace period enforcement.

- reconcile_stripe: Hourly — compares local state with Stripe API.
- enforce_subscription_grace_periods: Daily — downgrades expired grace periods.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from billing.state_machine import map_stripe_status, transition_subscription

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Celery app import (graceful fallback for testing)
# ---------------------------------------------------------------------------

_USE_CELERY = False
try:
    from celery_app import celery as _celery_app
    _USE_CELERY = True
except Exception:
    _celery_app = None

# ---------------------------------------------------------------------------
# Stripe SDK import
# ---------------------------------------------------------------------------

try:
    import stripe
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
except ImportError:
    stripe = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# PG connection helpers
# ---------------------------------------------------------------------------


def get_pg_connection():
    """Get a PostgreSQL connection (app DSN, telemetry_app). Tests patch this."""
    from web.db_pg import get_pg_connection as _get_pg
    return _get_pg()


def get_maint_connection():
    """Get a maintenance connection (telemetry_maint, BYPASSRLS). Tests patch this."""
    from web.db_pg import get_maint_connection as _get_maint
    return _get_maint()


def return_pg_connection(conn) -> None:
    """Release a standalone connection. Tests patch this."""
    from web.db_pg import return_pg_connection as _return
    _return(conn)


# ---------------------------------------------------------------------------
# Task: reconcile_stripe
# ---------------------------------------------------------------------------


def _reconcile_stripe_impl() -> dict[str, Any]:
    """Compare local subscription state with Stripe and heal mismatches.

    Steps:
        1. Query all users with a stripe_subscription_id
        2. For each, retrieve the subscription from Stripe
        3. If local status differs from Stripe status, update local
        4. If subscription not found in Stripe, mark as canceled

    Returns:
        Dict with ``{"checked": N, "healed": N, "errors": N}``

    Error handling (B-fix4): only a definitive "subscription no longer
    exists" response from Stripe (``InvalidRequestError`` with
    ``code == 'resource_missing'`` / HTTP 404) is treated as evidence of
    cancellation. ANY other exception — timeout, 5xx, rate limit, a rotated
    ``STRIPE_SECRET_KEY``, network failure — must NOT be treated as
    "canceled": a broad ``except Exception: ... canceled`` here would mass-
    cancel (and email) the entire subscriber base on a single transient
    Stripe API hiccup. Those users are skipped for this run and counted in
    ``errors`` instead.
    """
    conn = get_pg_connection()

    rows = conn.execute(
        "SELECT id, stripe_subscription_id, subscription_status, plan_tier "
        "FROM users WHERE stripe_subscription_id IS NOT NULL",
    ).fetchall()
    users = [dict(r) if not isinstance(r, dict) else r for r in rows]

    if not users:
        logger.info("Stripe reconciliation: 0 subscribers to check")
        return {"checked": 0, "healed": 0, "errors": 0}

    healed = 0
    reconciliation_errors = 0
    for user in users:
        uid = user["id"]
        sub_id = user["stripe_subscription_id"]
        local_status = user["subscription_status"]

        try:
            stripe_sub = stripe.Subscription.retrieve(sub_id)
            stripe_status = stripe_sub.status
        except stripe.error.InvalidRequestError as exc:
            stripe_code = getattr(exc, "code", None)
            http_status = getattr(exc, "http_status", None)
            if stripe_code == "resource_missing" or http_status == 404:
                logger.warning(
                    "Subscription %s not found in Stripe for user %s — marking canceled",
                    sub_id, uid,
                )
                stripe_status = "canceled"
            else:
                reconciliation_errors += 1
                logger.error(
                    "Stripe reconciliation: non-missing InvalidRequestError for "
                    "user %s sub %s: %s — skipping this run (NOT cancelling)",
                    uid, sub_id, exc,
                )
                continue
        except Exception as exc:
            # Transient/unexpected error (timeout, 5xx, rate limit, auth
            # failure, network error, ...) — never grounds for cancellation.
            reconciliation_errors += 1
            logger.error(
                "Stripe reconciliation: error retrieving subscription %s for "
                "user %s: %s — skipping this run (NOT cancelling)",
                sub_id, uid, exc,
            )
            continue

        mapped_status = map_stripe_status(stripe_status)
        if local_status != mapped_status:
            ok = transition_subscription(
                conn, uid, mapped_status,
                metadata={"source": "reconciliation", "stripe_raw": stripe_status},
            )
            if ok:
                healed += 1
                logger.warning(
                    "Stripe reconciliation healed user %s: %s -> %s",
                    uid, local_status, mapped_status,
                )
            else:
                logger.error(
                    "Stripe reconciliation: invalid transition for user %s: %s -> %s",
                    uid, local_status, mapped_status,
                )

    logger.info(
        "Stripe reconciliation complete: checked=%d, healed=%d, errors=%d",
        len(users), healed, reconciliation_errors,
    )
    if reconciliation_errors:
        # Loud, Redis-independent alert (mirrors billing.py._unmapped_alert):
        # a run with errors means SOME subscribers were NOT checked this hour,
        # which is worth paging on if it persists (e.g. a rotated Stripe key).
        logger.error(
            "Stripe reconciliation run had %d error(s) — subscribers were "
            "skipped, not cancelled. Check Stripe API health/credentials.",
            reconciliation_errors,
        )
        try:
            import sentry_sdk
            sentry_sdk.capture_message(
                f"Stripe reconciliation: {reconciliation_errors} error(s) this run "
                f"(checked={len(users)}, healed={healed})",
                level="error",
            )
        except Exception:
            pass
    return {"checked": len(users), "healed": healed, "errors": reconciliation_errors}


# ---------------------------------------------------------------------------
# Task: reconcile_pending_entitlements
# ---------------------------------------------------------------------------


def _reconcile_pending_entitlements_impl() -> dict[str, Any]:
    """Sweep ``stripe_pending_entitlements`` for orphaned paying customers.

    ``_handle_checkout_completed`` (web/routes/billing.py) writes a row here
    whenever a Stripe ``checkout.session.completed`` webhook fires but NO
    user could be matched (case-insensitive email drift, account deleted
    between checkout and webhook, etc.). Until now nothing ever read this
    table back — those customers stayed locked forever. This task closes
    that loop.

    For each unreconciled row (``reconciled_at IS NULL``):
        1. Case-insensitively match ``customer_email`` against ``users``.
        2. On a hit: attach the Stripe customer/subscription IDs to that
           user and transition them to 'active' with the recorded
           plan_tier — the SAME state-machine path
           ``_handle_checkout_completed`` and ``_reconcile_stripe_impl``
           already use (``billing.state_machine.transition_subscription``),
           not a bespoke update.
        3. Mark the row ``reconciled_at = NOW()`` so the sweep is
           idempotent (a linked or genuinely-unmatched row is not
           reprocessed by the next run).
        4. On no match: leave the row untouched for a future sweep.

    Per-row try/except: one bad row (bad data, a DB hiccup) can never abort
    the whole sweep.

    Connection: uses the maint (BYPASSRLS) connection — this is a
    cross-tenant, no-Flask-request-context beat task touching two global
    tables with no ``workspace_id``, mirroring
    ``_enforce_grace_periods_impl``.

    Returns:
        Dict with ``{"checked": N, "linked": N, "unmatched": N, "errors": N}``
    """
    conn = get_maint_connection()
    try:
        rows = conn.execute(
            "SELECT id, stripe_customer_id, stripe_subscription_id, "
            "customer_email, plan_tier FROM stripe_pending_entitlements "
            "WHERE reconciled_at IS NULL",
        ).fetchall()
        pending = [dict(r) if not isinstance(r, dict) else r for r in rows]

        if not pending:
            logger.info("Pending entitlement sweep: 0 unreconciled rows")
            return {"checked": 0, "linked": 0, "unmatched": 0, "errors": 0}

        linked = 0
        unmatched = 0
        reconciliation_errors = 0

        for row in pending:
            row_id = row["id"]
            email = row.get("customer_email")
            try:
                if not email:
                    unmatched += 1
                    continue

                user_row = conn.execute(
                    "SELECT id FROM users WHERE LOWER(email) = LOWER(%(email)s)",
                    {"email": email},
                ).fetchone()
                if user_row is None:
                    unmatched += 1
                    continue

                uid = (dict(user_row) if not isinstance(user_row, dict) else user_row)["id"]

                conn.execute(
                    "UPDATE users SET stripe_customer_id = %(cid)s, "
                    "stripe_subscription_id = %(sid)s WHERE id = %(uid)s",
                    {
                        "cid": row.get("stripe_customer_id"),
                        "sid": row.get("stripe_subscription_id"),
                        "uid": uid,
                    },
                )
                conn.commit()

                transitioned = transition_subscription(
                    conn, uid, "active",
                    plan_tier=row.get("plan_tier"),
                    metadata={
                        "source": "pending_entitlement_reconciliation",
                        "pending_id": row_id,
                    },
                )
                if not transitioned:
                    # Stripe IDs are attached regardless (that's the part that
                    # unlocks reconciliation) even if the state transition
                    # itself was a no-op/invalid (e.g. already active).
                    logger.warning(
                        "Pending entitlement %s: linked user %s but tier "
                        "transition was a no-op/invalid — IDs attached anyway",
                        row_id, uid,
                    )

                conn.execute(
                    "UPDATE stripe_pending_entitlements SET reconciled_at = NOW() "
                    "WHERE id = %(id)s",
                    {"id": row_id},
                )
                conn.commit()
                linked += 1
                logger.info(
                    "Pending entitlement %s linked to user %s via email match",
                    row_id, uid,
                )
            except Exception:
                reconciliation_errors += 1
                logger.exception(
                    "Failed to reconcile pending entitlement %s — skipping", row_id,
                )
                try:
                    conn.rollback()
                except Exception:
                    pass

        logger.info(
            "Pending entitlement sweep complete: checked=%d linked=%d "
            "unmatched=%d errors=%d",
            len(pending), linked, unmatched, reconciliation_errors,
        )
        return {
            "checked": len(pending),
            "linked": linked,
            "unmatched": unmatched,
            "errors": reconciliation_errors,
        }
    finally:
        return_pg_connection(conn)


# ---------------------------------------------------------------------------
# Task: enforce_subscription_grace_periods
# ---------------------------------------------------------------------------


def _enforce_grace_periods_impl() -> dict[str, Any]:
    """Check for expired grace periods and lock (no active subscription).

    SAFETY: only demotes users whose grace_period_end has PASSED (or who are
    in a terminal non-paying state with no grace window).  Active, trialing,
    and still-in-grace users are NEVER touched.

    Rules (B5/B10/B11 — 7-day unified grace window):
        - canceled + grace_period_end passed → expired + plan_tier='locked'
        - past_due + grace_period_end passed → expired + plan_tier='locked'
        - unpaid (any) → expired + plan_tier='locked' immediately
          (Stripe only sets unpaid after all retry attempts have failed; the
           dunning period itself acts as the grace window.)
        - stripe_subscription_id is cleared on terminal downgrade.

    Connection: uses the MAINT (BYPASSRLS) connection so that the audit_log
    INSERT succeeds without ``app.current_workspace_id`` being set (no Flask
    request context in a Celery worker).  This mirrors the weekly_recap and
    other cross-tenant beat tasks.  The status UPDATE, plan_tier UPDATE, and
    audit INSERT all execute on the same maint connection and commit together,
    preventing the RLS-policy exception from rolling back the status write.

    Returns:
        Dict with ``{"checked": N, "downgraded": N, "warned": N}``
    """
    from datetime import datetime, timezone

    # Use the maint (BYPASSRLS) connection — this is a cross-tenant beat task
    # with NO Flask request context and NO app.current_workspace_id GUC set.
    # The app DSN (telemetry_app) is NOBYPASSRLS; migration 019's RLS policy
    # on audit_log uses current_setting('app.current_workspace_id') without
    # missing_ok, which raises "unrecognized configuration parameter" when the
    # GUC is absent, aborting the transaction and rolling back the status update.
    conn = get_maint_connection()
    now = datetime.now(timezone.utc)
    downgraded = 0
    warned = 0
    try:
        # ------------------------------------------------------------------
        # 1. Canceled users past their 7-day grace period → expired/locked
        # ------------------------------------------------------------------
        rows = conn.execute(
            "SELECT id, email, plan_tier FROM users "
            "WHERE subscription_status = 'canceled' "
            "AND grace_period_end IS NOT NULL "
            "AND grace_period_end < %(now)s",
            {"now": now},
        ).fetchall()
        canceled_users = [dict(r) if not isinstance(r, dict) else r for r in rows]

        for user in canceled_users:
            ok = transition_subscription(
                conn, user["id"], "expired",
                metadata={"source": "grace_enforcement", "previous_tier": user.get("plan_tier")},
            )
            if ok:
                # Reset tier and clear Stripe subscription (terminal downgrade)
                conn.execute(
                    "UPDATE users SET plan_tier = 'locked', "
                    "stripe_subscription_id = NULL "
                    "WHERE id = %(uid)s",
                    {"uid": user["id"]},
                )
                conn.commit()
                downgraded += 1
                logger.info(
                    "Grace period expired (canceled): user %s locked, previous tier %s",
                    user["id"], user.get("plan_tier"),
                )
            if user.get("email"):
                try:
                    from auth.email import FRONTEND_URL, _send
                    _send(
                        user["email"],
                        "Your LAP access has paused",
                        f'<div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto;">'
                        f'<h2 style="color: #F3F0E8;">Your LAP access has paused</h2>'
                        f'<p style="color: #8A8F98;">Your subscription grace period has ended, so access to LAP has paused. '
                        f'Your data is kept safe — resubscribe anytime to restore full access and pick up where you left off.</p>'
                        f'<a href="{FRONTEND_URL}/pricing" '
                        f'style="display: inline-block; background: #B6FF2E; color: #0B0C0F; '
                        f'padding: 12px 24px; border-radius: 6px; text-decoration: none; '
                        f'font-weight: 600; margin: 16px 0;">Resubscribe</a></div>',
                    )
                except Exception:
                    logger.exception("Failed to send downgrade email to %s", user["email"])

        # ------------------------------------------------------------------
        # 2. Past-due users past grace window → expired/locked (B5/B11)
        #    Warn users still within the window.
        # ------------------------------------------------------------------
        past_due_rows = conn.execute(
            "SELECT id, email, plan_tier, grace_period_end FROM users "
            "WHERE subscription_status = 'past_due' "
            "AND grace_period_end IS NOT NULL",
        ).fetchall()
        past_due_users = [dict(r) if not isinstance(r, dict) else r for r in past_due_rows]

        for user in past_due_users:
            grace_end = user["grace_period_end"]
            if hasattr(grace_end, "replace"):
                grace_end = grace_end.replace(tzinfo=timezone.utc) if grace_end.tzinfo is None else grace_end

            if now > grace_end:
                # Grace window has passed → hard downgrade via state machine
                ok = transition_subscription(
                    conn, user["id"], "expired",
                    metadata={"source": "grace_enforcement_past_due", "previous_tier": user.get("plan_tier")},
                )
                if ok:
                    conn.execute(
                        "UPDATE users SET plan_tier = 'locked', "
                        "stripe_subscription_id = NULL "
                        "WHERE id = %(uid)s",
                        {"uid": user["id"]},
                    )
                    conn.commit()
                    downgraded += 1
                    logger.info(
                        "Grace period expired (past_due): user %s locked, previous tier %s",
                        user["id"], user.get("plan_tier"),
                    )
            else:
                # Still within grace window → send/re-send payment warning
                if user.get("email"):
                    try:
                        from auth.email import FRONTEND_URL, _send
                        _send(
                            user["email"],
                            "Action required: update your payment method",
                            f'<div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto;">'
                            f'<h2 style="color: #F3F0E8;">Payment overdue — action required</h2>'
                            f'<p style="color: #8A8F98;">Your payment is overdue. Please update your payment method '
                            f'to avoid losing access to your plan features.</p>'
                            f'<a href="{FRONTEND_URL}/app/settings/billing" '
                            f'style="display: inline-block; background: #FF6A00; color: #0B0C0F; '
                            f'padding: 12px 24px; border-radius: 6px; text-decoration: none; '
                            f'font-weight: 600; margin: 16px 0;">Update Payment</a></div>',
                        )
                        warned += 1
                    except Exception:
                        logger.exception("Failed to send past-due warning to %s", user["email"])

        # ------------------------------------------------------------------
        # 3. Unpaid users → expired/locked immediately (B5)
        #    Stripe only sets 'unpaid' after all dunning retries have failed,
        #    so there is no separate grace window — demote right away.
        #    SAFETY: the WHERE clause explicitly excludes active/trialing.
        # ------------------------------------------------------------------
        unpaid_rows = conn.execute(
            "SELECT id, email, plan_tier FROM users "
            "WHERE subscription_status = 'unpaid'",
        ).fetchall()
        unpaid_users = [dict(r) if not isinstance(r, dict) else r for r in unpaid_rows]

        for user in unpaid_users:
            ok = transition_subscription(
                conn, user["id"], "expired",
                metadata={"source": "grace_enforcement_unpaid", "previous_tier": user.get("plan_tier")},
            )
            if ok:
                conn.execute(
                    "UPDATE users SET plan_tier = 'locked', "
                    "stripe_subscription_id = NULL "
                    "WHERE id = %(uid)s",
                    {"uid": user["id"]},
                )
                conn.commit()
                downgraded += 1
                logger.info(
                    "Unpaid subscription demoted: user %s locked, previous tier %s",
                    user["id"], user.get("plan_tier"),
                )
            if user.get("email"):
                try:
                    from auth.email import FRONTEND_URL, _send
                    _send(
                        user["email"],
                        "Your LAP access has paused",
                        f'<div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto;">'
                        f'<h2 style="color: #F3F0E8;">Your LAP access has paused</h2>'
                        f'<p style="color: #8A8F98;">We were unable to collect payment after multiple attempts, '
                        f'so access to LAP has paused. Your data is kept safe — resubscribe anytime to restore '
                        f'full access and pick up where you left off.</p>'
                        f'<a href="{FRONTEND_URL}/pricing" '
                        f'style="display: inline-block; background: #B6FF2E; color: #0B0C0F; '
                        f'padding: 12px 24px; border-radius: 6px; text-decoration: none; '
                        f'font-weight: 600; margin: 16px 0;">Resubscribe</a></div>',
                    )
                except Exception:
                    logger.exception("Failed to send unpaid downgrade email to %s", user["email"])

        total = len(canceled_users) + len(past_due_users) + len(unpaid_users)
        logger.info(
            "Grace period enforcement: checked=%d, downgraded=%d, warned=%d",
            total, downgraded, warned,
        )
        return {"checked": total, "downgraded": downgraded, "warned": warned}
    finally:
        return_pg_connection(conn)


# ---------------------------------------------------------------------------
# Task: retry_failed_webhooks
# ---------------------------------------------------------------------------

# Backoff schedule in seconds: 1m, 5m, 15m, 1h, 6h, 24h
_RETRY_BACKOFF = [60, 300, 900, 3600, 21600, 86400]
_MAX_ATTEMPTS = len(_RETRY_BACKOFF) + 1  # 7 total (1 initial + 6 retries)


def _retry_failed_webhooks_impl() -> dict[str, Any]:
    """Retry failed webhook events that are due for retry.

    Picks up rows where processing_status='failed' and
    next_retry_at <= now(), replays the webhook handler,
    and updates status accordingly. After max attempts,
    marks as 'deadletter'.

    Returns:
        Dict with ``{"checked": N, "retried": N, "deadlettered": N}``
    """
    import json
    from datetime import datetime, timedelta, timezone

    conn = get_pg_connection()
    now = datetime.now(timezone.utc)

    rows = conn.execute(
        "SELECT id, stripe_event_id, event_type, payload_json, attempt_count "
        "FROM stripe_webhook_log "
        "WHERE processing_status = 'failed' "
        "AND next_retry_at IS NOT NULL "
        "AND next_retry_at <= %(now)s "
        "ORDER BY next_retry_at ASC "
        "LIMIT 50",
        {"now": now},
    ).fetchall()
    events = [dict(r) if not isinstance(r, dict) else r for r in rows]

    if not events:
        return {"checked": 0, "retried": 0, "deadlettered": 0}

    retried = 0
    deadlettered = 0

    for event in events:
        eid = event["id"]
        event_type = event["event_type"]
        attempt = event["attempt_count"] + 1
        payload_json = event.get("payload_json")

        if attempt > _MAX_ATTEMPTS:
            # Dead-letter: max attempts exceeded
            conn.execute(
                "UPDATE stripe_webhook_log SET processing_status = 'deadletter', "
                "attempt_count = %(attempt)s WHERE id = %(id)s",
                {"attempt": attempt, "id": eid},
            )
            conn.commit()
            deadlettered += 1
            logger.warning(
                "Webhook dead-lettered: event=%s type=%s attempts=%d",
                event["stripe_event_id"], event_type, attempt,
            )
            continue

        # Try to replay
        success = False
        error_msg = None
        try:
            if payload_json:
                data = json.loads(payload_json)
            else:
                data = {}

            from web.routes.billing import (
                _handle_checkout_completed,
                _handle_payment_failed,
                _handle_payment_succeeded,
                _handle_subscription_created,
                _handle_subscription_deleted,
                _handle_subscription_paused,
                _handle_subscription_resumed,
                _handle_subscription_updated,
            )

            handlers = {
                "checkout.session.completed": _handle_checkout_completed,
                "customer.subscription.created": _handle_subscription_created,
                "customer.subscription.updated": _handle_subscription_updated,
                "customer.subscription.deleted": _handle_subscription_deleted,
                "customer.subscription.paused": _handle_subscription_paused,
                "customer.subscription.resumed": _handle_subscription_resumed,
                "invoice.payment_failed": _handle_payment_failed,
                "invoice.paid": _handle_payment_succeeded,
            }

            handler = handlers.get(event_type)
            if handler:
                handler(data)
                success = True
            else:
                # Unknown type, dead-letter immediately
                error_msg = f"No handler for event type: {event_type}"

        except Exception as exc:
            error_msg = str(exc)[:500]
            logger.warning(
                "Webhook retry failed: event=%s type=%s attempt=%d error=%s",
                event["stripe_event_id"], event_type, attempt, error_msg,
            )

        if success:
            conn.execute(
                "UPDATE stripe_webhook_log SET processing_status = 'processed', "
                "processed_at = %(now)s, attempt_count = %(attempt)s "
                "WHERE id = %(id)s",
                {"now": now, "attempt": attempt, "id": eid},
            )
            conn.commit()
            retried += 1
        else:
            # Schedule next retry with backoff
            backoff_idx = min(attempt - 1, len(_RETRY_BACKOFF) - 1)
            next_retry = now + timedelta(seconds=_RETRY_BACKOFF[backoff_idx])

            if attempt >= _MAX_ATTEMPTS:
                conn.execute(
                    "UPDATE stripe_webhook_log SET processing_status = 'deadletter', "
                    "attempt_count = %(attempt)s, error_message = %(error)s "
                    "WHERE id = %(id)s",
                    {"attempt": attempt, "error": error_msg, "id": eid},
                )
                deadlettered += 1
            else:
                conn.execute(
                    "UPDATE stripe_webhook_log SET attempt_count = %(attempt)s, "
                    "next_retry_at = %(next)s, error_message = %(error)s "
                    "WHERE id = %(id)s",
                    {"attempt": attempt, "next": next_retry, "error": error_msg, "id": eid},
                )
            conn.commit()

    logger.info(
        "Webhook retry sweep: checked=%d, retried=%d, deadlettered=%d",
        len(events), retried, deadlettered,
    )
    return {"checked": len(events), "retried": retried, "deadlettered": deadlettered}


# ---------------------------------------------------------------------------
# Register as Celery tasks (or plain functions when Celery unavailable)
# ---------------------------------------------------------------------------

if _USE_CELERY and _celery_app is not None:
    @_celery_app.task(name="tasks.billing_tasks.reconcile_stripe")
    def reconcile_stripe() -> dict[str, Any]:
        return _reconcile_stripe_impl()

    @_celery_app.task(name="tasks.billing_tasks.reconcile_pending_entitlements")
    def reconcile_pending_entitlements() -> dict[str, Any]:
        return _reconcile_pending_entitlements_impl()

    @_celery_app.task(name="tasks.billing_tasks.enforce_subscription_grace_periods")
    def enforce_subscription_grace_periods() -> dict[str, Any]:
        return _enforce_grace_periods_impl()

    @_celery_app.task(name="tasks.billing_tasks.retry_failed_webhooks")
    def retry_failed_webhooks() -> dict[str, Any]:
        return _retry_failed_webhooks_impl()
else:
    def reconcile_stripe() -> dict[str, Any]:  # type: ignore[misc]
        return _reconcile_stripe_impl()

    def reconcile_pending_entitlements() -> dict[str, Any]:  # type: ignore[misc]
        return _reconcile_pending_entitlements_impl()

    def enforce_subscription_grace_periods() -> dict[str, Any]:  # type: ignore[misc]
        return _enforce_grace_periods_impl()

    def retry_failed_webhooks() -> dict[str, Any]:  # type: ignore[misc]
        return _retry_failed_webhooks_impl()
