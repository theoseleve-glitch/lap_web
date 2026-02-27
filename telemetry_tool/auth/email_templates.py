"""Centralized email template registry for all transactional emails.

All 16 template types are registered here with their subjects, HTML
builders, and required variable sets.  The ``render_email()`` function
is the single entry point used by both synchronous senders and the
async ``send_email_async`` Celery task.

Usage::

    from auth.email_templates import render_email
    subject, html = render_email("verification", {"verify_url": "..."})
"""
from __future__ import annotations

import logging
import os
from typing import Callable

logger = logging.getLogger(__name__)

FRONTEND_URL: str = os.environ.get("FRONTEND_URL", "https://www.lap-coach.racing")

# ---------------------------------------------------------------------------
# Shared HTML building blocks
# ---------------------------------------------------------------------------

_WRAPPER_OPEN = (
    '<div style="font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', '
    'Roboto, sans-serif; max-width: 600px; margin: 0 auto; '
    'background: #0B0C0F; padding: 32px 24px; color: #8A8F98;">'
    '<div style="margin-bottom: 24px;">'
    '<img src="https://www.lap-coach.racing/logo-email.png" alt="LAP" '
    'width="60" height="24" style="display: block;" />'
    '</div>'
)

_WRAPPER_CLOSE = (
    '<div style="margin-top: 32px; padding-top: 16px; border-top: 1px solid #2A2D35; '
    'font-size: 11px; color: #5A5E66;">'
    '<p>LAP — Telemetry Analysis Platform</p>'
    '<p><a href="{frontend}/app/settings/notifications" '
    'style="color: #5A5E66;">Email preferences</a> · '
    '<a href="{frontend}/privacy" style="color: #5A5E66;">Privacy</a></p>'
    '</div></div>'
).replace("{frontend}", FRONTEND_URL)


def _btn(url: str, label: str, color: str = "#B6FF2E", text_color: str = "#0B0C0F") -> str:
    return (
        f'<a href="{url}" style="display: inline-block; background: {color}; '
        f'color: {text_color}; padding: 12px 24px; border-radius: 6px; '
        f'text-decoration: none; font-weight: 600; margin: 16px 0;">{label}</a>'
    )


def _h2(text: str) -> str:
    return f'<h2 style="color: #F3F0E8; margin: 0 0 12px;">{text}</h2>'


def _p(text: str) -> str:
    return f'<p style="color: #8A8F98; line-height: 1.5;">{text}</p>'


def _small(text: str) -> str:
    return f'<p style="color: #8A8F98; font-size: 12px;">{text}</p>'


def _wrap(body: str) -> str:
    return _WRAPPER_OPEN + body + _WRAPPER_CLOSE


# ---------------------------------------------------------------------------
# Template definitions — subject + builder
# ---------------------------------------------------------------------------


def _verification(v: dict) -> tuple[str, str]:
    url = v["verify_url"]
    body = (
        _h2("Verify your email")
        + _p("Click the button below to verify your LAP account:")
        + _btn(url, "Verify Email")
        + _small(f'Or copy this link: <code style="color: #F3F0E8;">{url}</code>')
        + _small("If you didn't create an account, ignore this email.")
    )
    return "Verify your LAP account", _wrap(body)


def _welcome(v: dict) -> tuple[str, str]:
    name = v.get("display_name", "racer")
    body = (
        _h2(f"Welcome to LAP, {name}!")
        + _p("Your account is ready. Upload your first telemetry session:")
        + _btn(f"{FRONTEND_URL}/free-report/analyze", "Upload Session")
        + _small("Need help? Reply to this email or visit our docs.")
    )
    return f"Welcome to LAP, {name}!", _wrap(body)


def _password_reset(v: dict) -> tuple[str, str]:
    url = v["reset_url"]
    body = (
        _h2("Reset your password")
        + _p("We received a request to reset your LAP account password.")
        + _btn(url, "Reset Password")
        + _small(f'Or copy this link: <code style="color: #F3F0E8;">{url}</code>')
        + _small("This link expires in 1 hour. If you didn't request this, ignore it.")
    )
    return "Reset your LAP password", _wrap(body)


def _password_changed(v: dict) -> tuple[str, str]:
    body = (
        _h2("Your password was changed")
        + _p("The password for your LAP account was recently changed. "
              "If you made this change, no further action is required.")
        + _p("If you did not change your password, reset it immediately:")
        + _btn(f"{FRONTEND_URL}/forgot-password", "Reset Password")
        + _small("If you did not make this change, contact support immediately.")
    )
    return "Your LAP password was changed", _wrap(body)


def _team_invitation(v: dict) -> tuple[str, str]:
    url = v["accept_url"]
    team = v["team_name"]
    inviter = v["inviter_name"]
    body = (
        _h2(f"You've been invited to join {team}")
        + _p(f'<strong style="color: #F3F0E8;">{inviter}</strong> has invited you '
              f'to join <strong style="color: #F3F0E8;">{team}</strong> on LAP.')
        + _btn(url, "Accept Invitation")
        + _small(f'Or copy this link: <code style="color: #F3F0E8;">{url}</code>')
        + _small("This invitation expires in 7 days.")
    )
    return f"You're invited to join {team} on LAP", _wrap(body)


def _team_joined(v: dict) -> tuple[str, str]:
    member = v.get("member_name", "A new member")
    team = v["team_name"]
    body = (
        _h2(f"{member} joined {team}")
        + _p(f'{member} has accepted the invitation and joined your team.')
        + _btn(f"{FRONTEND_URL}/app/settings/team", "Manage Team")
    )
    return f"{member} joined {team} on LAP", _wrap(body)


def _report_ready(v: dict) -> tuple[str, str]:
    session = v.get("session_name", "your session")
    url = v.get("report_url", f"{FRONTEND_URL}/app/sessions")
    body = (
        _h2("Your analysis is ready")
        + _p(f'Analysis for <strong style="color: #F3F0E8;">{session}</strong> '
              f'has been completed.')
        + _btn(url, "View Report")
    )
    return f"Analysis ready: {session}", _wrap(body)


def _retention_warning(v: dict) -> tuple[str, str]:
    days = v.get("days_remaining", 7)
    sessions = v.get("sessions", [])
    rows = ""
    for s in sessions[:10]:
        name = s.get("file_name", s.get("session_id", "Unknown"))
        rows += f'<li style="color: #F3F0E8; padding: 2px 0;">{name}</li>'
    extra = f"<p>...and {len(sessions) - 10} more.</p>" if len(sessions) > 10 else ""
    body = (
        _h2(f"Data expiring in {days} days")
        + _p("The following sessions' raw telemetry data will be automatically deleted:")
        + f'<ul style="list-style: disc; padding-left: 20px; margin: 12px 0;">{rows}</ul>'
        + extra
        + _btn(f"{FRONTEND_URL}/app/sessions", "Export Data Now")
        + _small(f'Want longer retention? <a href="{FRONTEND_URL}/pricing" '
                 f'style="color: #B6FF2E;">Upgrade your plan</a>.')
    )
    return f"Data expiring in {days} days — export or upgrade", _wrap(body)


def _retention_deleted(v: dict) -> tuple[str, str]:
    sessions = v.get("sessions", [])
    rows = ""
    for s in sessions[:10]:
        name = s.get("file_name", s.get("session_id", "Unknown"))
        rows += f'<li style="color: #F3F0E8; padding: 2px 0;">{name}</li>'
    body = (
        _h2("Raw telemetry data deleted")
        + _p("Raw data for the following sessions has been deleted per your retention policy. "
              "Reports, scores, and lap data are still available.")
        + f'<ul style="list-style: disc; padding-left: 20px; margin: 12px 0;">{rows}</ul>'
        + _small(f'Want longer retention? <a href="{FRONTEND_URL}/pricing" '
                 f'style="color: #B6FF2E;">Upgrade your plan</a>.')
    )
    return "Raw telemetry data deleted — reports still available", _wrap(body)


def _trial_ending(v: dict) -> tuple[str, str]:
    plan = v.get("plan_name", "your plan")
    days = v.get("days_remaining", 3)
    body = (
        _h2(f"Your trial ends in {days} days")
        + _p(f"Your trial of {plan} is ending soon. To keep access to all features, "
              f"subscribe before your trial expires.")
        + _btn(f"{FRONTEND_URL}/pricing", "View Plans")
        + _small("After your trial ends, your account will move to the free tier. "
                 "Your data will be preserved.")
    )
    return f"Your LAP trial ends in {days} days", _wrap(body)


def _payment_failed(v: dict) -> tuple[str, str]:
    amount = v.get("amount", "your subscription")
    retry_date = v.get("retry_date", "soon")
    body = (
        _h2("Payment failed")
        + _p(f"We were unable to process your payment of {amount}. "
              f"We'll retry on {retry_date}.")
        + _p("Please update your payment method to avoid service interruption:")
        + _btn(f"{FRONTEND_URL}/app/settings/billing", "Update Payment Method",
               color="#FF6A00")
    )
    return "Payment failed — update your payment method", _wrap(body)


def _subscription_canceled(v: dict) -> tuple[str, str]:
    plan = v.get("plan_name", "your plan")
    body = (
        _h2("Your subscription has been canceled")
        + _p(f"Your {plan} subscription has been canceled. You'll continue to have "
              f"access until your current billing period ends.")
        + _p("After that, your account will move to the free tier. Your data will be preserved.")
        + _btn(f"{FRONTEND_URL}/pricing", "Resubscribe")
    )
    return "Your LAP subscription has been canceled", _wrap(body)


def _payment_recovered(v: dict) -> tuple[str, str]:
    plan = v.get("plan_name", "your plan")
    body = (
        _h2("Payment successful — you're back on track")
        + _p(f"Your payment for {plan} has been successfully processed. "
              f"Your subscription is now active.")
        + _btn(f"{FRONTEND_URL}/app", "Go to Dashboard")
    )
    return "Payment successful — your LAP subscription is active", _wrap(body)


def _new_login_location(v: dict) -> tuple[str, str]:
    ip = v.get("ip", "unknown")
    device = v.get("device_info", v.get("country", "unknown device"))
    body = (
        _h2("New login detected")
        + _p("A new login to your LAP account was detected:")
        + f'<table style="margin: 12px 0; border-collapse: collapse;">'
        + f'<tr><td style="color: #8A8F98; padding: 4px 12px 4px 0;">Device:</td>'
        + f'<td style="color: #F3F0E8;">{device}</td></tr>'
        + f'<tr><td style="color: #8A8F98; padding: 4px 12px 4px 0;">IP:</td>'
        + f'<td style="color: #F3F0E8;">{ip}</td></tr></table>'
        + _p("If this was you, no action needed. If not, secure your account:")
        + _btn(f"{FRONTEND_URL}/app/settings/security", "Review Security Settings")
    )
    return "New login to your LAP account", _wrap(body)


def _weekly_summary(v: dict) -> tuple[str, str]:
    count = v.get("sessions_count", 0)
    best = v.get("best_score", "—")
    improvement = v.get("improvement", "—")
    body = (
        _h2("Your weekly summary")
        + f'<table style="margin: 12px 0; border-collapse: collapse; width: 100%;">'
        + f'<tr><td style="color: #8A8F98; padding: 8px 12px;">Sessions this week</td>'
        + f'<td style="color: #F3F0E8; font-weight: 600; text-align: right; padding: 8px 12px;">{count}</td></tr>'
        + f'<tr><td style="color: #8A8F98; padding: 8px 12px;">Best score</td>'
        + f'<td style="color: #B6FF2E; font-weight: 600; text-align: right; padding: 8px 12px;">{best}</td></tr>'
        + f'<tr><td style="color: #8A8F98; padding: 8px 12px;">Improvement</td>'
        + f'<td style="color: #F3F0E8; font-weight: 600; text-align: right; padding: 8px 12px;">{improvement}</td></tr>'
        + f'</table>'
        + _btn(f"{FRONTEND_URL}/app", "View Dashboard")
    )
    return "Your LAP weekly summary", _wrap(body)


def _quota_warning(v: dict) -> tuple[str, str]:
    feature = v.get("feature", "reports")
    used = v.get("used", 0)
    limit = v.get("limit", 0)
    body = (
        _h2(f"You're approaching your {feature} limit")
        + _p(f"You've used {used} of {limit} {feature} this month. "
              f"Upgrade your plan for higher limits:")
        + _btn(f"{FRONTEND_URL}/pricing", "Upgrade Plan")
    )
    return f"Approaching your {feature} limit on LAP", _wrap(body)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

TEMPLATES: dict[str, Callable[[dict], tuple[str, str]]] = {
    "verification": _verification,
    "welcome": _welcome,
    "password_reset": _password_reset,
    "password_changed": _password_changed,
    "team_invitation": _team_invitation,
    "team_joined": _team_joined,
    "report_ready": _report_ready,
    "retention_warning": _retention_warning,
    "retention_deleted": _retention_deleted,
    "trial_ending": _trial_ending,
    "payment_failed": _payment_failed,
    "subscription_canceled": _subscription_canceled,
    "payment_recovered": _payment_recovered,
    "new_login_location": _new_login_location,
    "weekly_summary": _weekly_summary,
    "quota_warning": _quota_warning,
}


def render_email(template: str, variables: dict) -> tuple[str, str]:
    """Render an email template by name.

    Args:
        template: Template name (must be in TEMPLATES registry).
        variables: Template-specific variables.

    Returns:
        (subject, html) tuple.

    Raises:
        KeyError: If template name is not registered.
    """
    if template not in TEMPLATES:
        raise KeyError(f"Unknown email template: {template}")
    return TEMPLATES[template](variables)


def list_templates() -> list[str]:
    """Return all registered template names."""
    return sorted(TEMPLATES.keys())
