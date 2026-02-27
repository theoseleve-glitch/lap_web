"""Transactional email via Resend API.

Sends verification, welcome, and password-reset emails.
Fails silently (logs error) so registration is never blocked by email issues.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

RESEND_API_KEY: str = os.environ.get("RESEND_API_KEY", "")
EMAIL_FROM: str = os.environ.get("EMAIL_FROM", "LAP <noreply@lap-coach.racing>")
FRONTEND_URL: str = os.environ.get("FRONTEND_URL", "https://www.lap-coach.racing")


def _send(to: str, subject: str, html: str) -> bool:
    """Send an email via Resend.  Returns True on success."""
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not set — skipping email to %s", to)
        return False

    try:
        import resend
        resend.api_key = RESEND_API_KEY
        resend.Emails.send({
            "from": EMAIL_FROM,
            "to": [to],
            "subject": subject,
            "html": html,
        })
        logger.info("Email sent to %s: %s", to, subject)
        return True
    except Exception:
        logger.exception("Failed to send email to %s", to)
        return False


def send_verification_email(to: str, token: str) -> bool:
    """Send email-verification link after registration."""
    verify_url = f"{FRONTEND_URL}/verify-email?token={token}"
    html = f"""\
<div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto;">
  <h2 style="color: #F3F0E8;">Verify your email</h2>
  <p style="color: #8A8F98;">Click the button below to verify your LAP account:</p>
  <a href="{verify_url}"
     style="display: inline-block; background: #B6FF2E; color: #0B0C0F;
            padding: 12px 24px; border-radius: 6px; text-decoration: none;
            font-weight: 600; margin: 16px 0;">
    Verify Email
  </a>
  <p style="color: #8A8F98; font-size: 13px;">
    Or copy this link: <br>
    <code style="color: #F3F0E8;">{verify_url}</code>
  </p>
  <p style="color: #8A8F98; font-size: 12px;">
    If you didn't create an account, ignore this email.
  </p>
</div>"""
    return _send(to, "Verify your LAP account", html)


def send_welcome_email(to: str, display_name: str) -> bool:
    """Send a welcome email after successful verification."""
    html = f"""\
<div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto;">
  <h2 style="color: #F3F0E8;">Welcome to LAP, {display_name}!</h2>
  <p style="color: #8A8F98;">Your account is ready. Upload your first telemetry session:</p>
  <a href="{FRONTEND_URL}/free-report/analyze"
     style="display: inline-block; background: #B6FF2E; color: #0B0C0F;
            padding: 12px 24px; border-radius: 6px; text-decoration: none;
            font-weight: 600; margin: 16px 0;">
    Upload Session
  </a>
  <p style="color: #8A8F98; font-size: 13px;">
    Need help? Reply to this email or visit our docs.
  </p>
</div>"""
    return _send(to, f"Welcome to LAP, {display_name}!", html)
