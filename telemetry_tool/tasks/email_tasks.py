"""Async email sending via Celery.

Renders templates from :mod:`auth.email_templates`, sends via Resend,
and logs results to the ``email_log`` table for deliverability tracking.

Usage::

    from tasks.email_tasks import send_email_async
    send_email_async.delay("verification", "user@example.com", {"verify_url": "..."})
"""
from __future__ import annotations

import logging
from typing import Any

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
# PG connection helper
# ---------------------------------------------------------------------------


def _get_pg():
    """Get a PostgreSQL connection. Tests patch this."""
    from web.db_pg import get_pg_connection as _get_pg_conn
    return _get_pg_conn()


# ---------------------------------------------------------------------------
# Core implementation
# ---------------------------------------------------------------------------


def _send_email_impl(
    template: str,
    to: str,
    variables: dict,
    language: str = "en",
    user_id: int | None = None,
) -> dict[str, Any]:
    """Render template, send via Resend, log to email_log.

    Args:
        template: Template name from the registry.
        to: Recipient email address.
        variables: Template variables.
        language: User's language preference (reserved for future i18n).
        user_id: Optional user ID for logging.

    Returns:
        Dict with ``{"sent": bool, "template": str, "error": str|None}``
    """
    from auth.email import _send
    from auth.email_templates import render_email

    error_msg = None
    sent = False

    try:
        subject, html = render_email(template, variables)
    except KeyError:
        logger.error("Unknown email template: %s", template)
        error_msg = f"Unknown template: {template}"
        _log_email(user_id, template, to, "failed", error_msg)
        return {"sent": False, "template": template, "error": error_msg}

    try:
        sent = _send(to, subject, html)
        if not sent:
            error_msg = "Resend API returned failure or not configured"
    except Exception as exc:
        logger.exception("Failed to send %s email to %s", template, to)
        error_msg = str(exc)[:500]

    status = "sent" if sent else "failed"
    _log_email(user_id, template, to, status, error_msg)

    return {"sent": sent, "template": template, "error": error_msg}


def _log_email(
    user_id: int | None,
    template: str,
    to_email: str,
    status: str,
    error: str | None,
) -> None:
    """Log email send attempt to the email_log table."""
    try:
        conn = _get_pg()
        conn.execute(
            "INSERT INTO email_log (user_id, template, to_email, status, error) "
            "VALUES (%(uid)s, %(tpl)s, %(to)s, %(status)s, %(error)s)",
            {
                "uid": user_id,
                "tpl": template,
                "to": to_email,
                "status": status,
                "error": error,
            },
        )
        conn.commit()
    except Exception:
        # Email logging failure should never break sending
        logger.warning("Failed to log email send to email_log", exc_info=True)


# ---------------------------------------------------------------------------
# Register as Celery task
# ---------------------------------------------------------------------------

def _send_verification_reminders_impl() -> dict[str, Any]:
    """Find users unverified for 24h+ and send one reminder.

    Only sends one reminder per user (checks email_log for prior reminder).
    """
    sent_count = 0
    try:
        conn = _get_pg()
        # Users registered >24h ago, not verified, no reminder sent yet
        rows = conn.execute(
            "SELECT u.id, u.email, u.email_verify_token "
            "FROM users u "
            "WHERE u.email_verified_at IS NULL "
            "  AND u.created_at < NOW() - INTERVAL '24 hours' "
            "  AND u.email_verify_token IS NOT NULL "
            "  AND NOT EXISTS ("
            "    SELECT 1 FROM email_log el "
            "    WHERE el.user_id = u.id AND el.template = 'verification_reminder'"
            "  ) "
            "LIMIT 50",
            {},
        ).fetchall()

        for row in rows:
            user_id, email, token = row[0], row[1], row[2]
            result = _send_email_impl(
                "verification_reminder",
                email,
                {"verify_url": f"https://www.lap-coach.racing/verify-email?token={token}"},
                user_id=user_id,
            )
            if result.get("sent"):
                sent_count += 1
    except Exception:
        logger.exception("Failed to send verification reminders")

    return {"sent_count": sent_count}


if _USE_CELERY and _celery_app is not None:
    @_celery_app.task(
        name="tasks.email_tasks.send_email_async",
        queue="default",
        autoretry_for=(ConnectionError, TimeoutError, OSError),
        retry_backoff=True,       # exponential: 1s, 2s, 4s, 8s ...
        retry_backoff_max=300,    # cap at 5 minutes
        max_retries=3,
        retry_jitter=True,        # ±random to avoid thundering herd
    )
    def send_email_async(
        template: str,
        to: str,
        variables: dict,
        language: str = "en",
        user_id: int | None = None,
    ) -> dict[str, Any]:
        return _send_email_impl(template, to, variables, language, user_id)

    @_celery_app.task(
        name="tasks.email_tasks.send_verification_reminders",
        queue="default",
    )
    def send_verification_reminders() -> dict[str, Any]:
        return _send_verification_reminders_impl()
else:
    def send_email_async(  # type: ignore[misc]
        template: str,
        to: str,
        variables: dict,
        language: str = "en",
        user_id: int | None = None,
    ) -> dict[str, Any]:
        return _send_email_impl(template, to, variables, language, user_id)
