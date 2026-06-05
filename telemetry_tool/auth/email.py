"""Transactional email via Resend API.

Sends verification, welcome, retention warning, password-reset, security
notification, export, and account lifecycle emails.
Fails silently (logs error) so registration is never blocked by email issues.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

RESEND_API_KEY: str = os.environ.get("RESEND_API_KEY", "")
EMAIL_FROM: str = os.environ.get("EMAIL_FROM", "LAP <team@lap-coach.racing>")
FRONTEND_URL: str = os.environ.get("FRONTEND_URL", "https://www.lap-coach.racing")
EMAIL_SUPPRESS: bool = os.environ.get("EMAIL_SUPPRESS", "0") == "1"


def _esc(s: str) -> str:
    """Escape user-controlled values for safe HTML embedding in emails."""
    import html
    return html.escape(str(s), quote=True)


def _send(to: str, subject: str, html: str) -> bool:
    """Send an email via Resend.  Returns True on success.

    Set ``EMAIL_SUPPRESS=1`` in dev/staging to log emails without sending.
    """
    if EMAIL_SUPPRESS:
        logger.info("EMAIL_SUPPRESS=1 — would send to %s: %s", to, subject)
        return True

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
  <h2 style="color: #F3F0E8;">Welcome to LAP, {_esc(display_name)}!</h2>
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
    return _send(to, f"Welcome to LAP, {_esc(display_name)}!", html)


def send_password_reset_email(to: str, token: str) -> bool:
    """Send password reset link: {FRONTEND_URL}/reset-password?token={token}."""
    reset_url = f"{FRONTEND_URL}/reset-password?token={token}"
    html = f"""\
<div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto;">
  <h2 style="color: #F3F0E8;">Reset your password</h2>
  <p style="color: #8A8F98;">
    We received a request to reset your LAP account password.
    Click the button below to set a new password:
  </p>
  <a href="{reset_url}"
     style="display: inline-block; background: #B6FF2E; color: #0B0C0F;
            padding: 12px 24px; border-radius: 6px; text-decoration: none;
            font-weight: 600; margin: 16px 0;">
    Reset Password
  </a>
  <p style="color: #8A8F98; font-size: 13px;">
    Or copy this link: <br>
    <code style="color: #F3F0E8;">{reset_url}</code>
  </p>
  <p style="color: #8A8F98; font-size: 12px;">
    This link expires in 1 hour. If you didn't request a password reset,
    you can safely ignore this email.
  </p>
</div>"""
    return _send(to, "Reset your LAP password", html)


def send_retention_warning(to: str, sessions: list[dict], days_remaining: int) -> bool:
    """Send retention warning email with list of expiring sessions.

    Sent 7 days before raw telemetry data is automatically deleted.
    """
    session_rows = ""
    for s in sessions[:10]:  # Cap at 10 to keep email readable
        name = s.get("file_name", s.get("session_id", "Unknown"))
        created = s.get("created_at", "")
        session_rows += (
            f'<tr><td style="color: #F3F0E8; padding: 4px 8px;">{_esc(name)}</td>'
            f'<td style="color: #8A8F98; padding: 4px 8px;">{_esc(created)}</td></tr>'
        )

    extra = ""
    if len(sessions) > 10:
        extra = (
            f'<p style="color: #8A8F98; font-size: 13px;">'
            f'...and {len(sessions) - 10} more sessions.</p>'
        )

    html = f"""\
<div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto;">
  <h2 style="color: #F3F0E8;">Raw telemetry data expiring in {days_remaining} days</h2>
  <p style="color: #8A8F98;">
    The following sessions' raw telemetry data will be automatically deleted
    based on your plan's retention policy. Your reports, scores, and lap data
    will be preserved.
  </p>
  <table style="width: 100%; border-collapse: collapse; margin: 12px 0;">
    <tr>
      <th style="color: #8A8F98; text-align: left; padding: 4px 8px; border-bottom: 1px solid #2A2D35;">Session</th>
      <th style="color: #8A8F98; text-align: left; padding: 4px 8px; border-bottom: 1px solid #2A2D35;">Date</th>
    </tr>
    {session_rows}
  </table>
  {extra}
  <p style="color: #8A8F98; font-size: 13px;">
    To keep your raw data longer,
    <a href="{FRONTEND_URL}/pricing" style="color: #B6FF2E;">upgrade your plan</a>.
  </p>
  <a href="{FRONTEND_URL}/app/sessions"
     style="display: inline-block; background: #B6FF2E; color: #0B0C0F;
            padding: 12px 24px; border-radius: 6px; text-decoration: none;
            font-weight: 600; margin: 16px 0;">
    Export Data Now
  </a>
</div>"""
    return _send(to, f"Data expiring in {days_remaining} days — export or upgrade", html)


def send_retention_deleted(to: str, sessions: list[dict]) -> bool:
    """Send notification that sessions' raw data has been deleted."""
    session_rows = ""
    for s in sessions[:10]:
        name = s.get("file_name", s.get("session_id", "Unknown"))
        session_rows += (
            f'<li style="color: #F3F0E8; padding: 2px 0;">{_esc(name)}</li>'
        )

    extra = ""
    if len(sessions) > 10:
        extra = (
            f'<p style="color: #8A8F98; font-size: 13px;">'
            f'...and {len(sessions) - 10} more sessions.</p>'
        )

    html = f"""\
<div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto;">
  <h2 style="color: #F3F0E8;">Raw telemetry data deleted</h2>
  <p style="color: #8A8F98;">
    Raw telemetry data for the following sessions has been automatically deleted
    per your plan's retention policy. Your reports, scores, and lap data are
    still available.
  </p>
  <ul style="list-style: none; padding: 0; margin: 12px 0;">
    {session_rows}
  </ul>
  {extra}
  <p style="color: #8A8F98; font-size: 13px;">
    Want longer retention?
    <a href="{FRONTEND_URL}/pricing" style="color: #B6FF2E;">Upgrade your plan</a>
    to keep raw data for up to 12 months.
  </p>
</div>"""
    return _send(to, "Raw telemetry data deleted — reports still available", html)


def send_password_changed_email(to: str) -> bool:
    """Send notification that the account password was changed."""
    reset_url = f"{FRONTEND_URL}/forgot-password"
    html = f"""\
<div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto;">
  <h2 style="color: #F3F0E8;">Your password was changed</h2>
  <p style="color: #8A8F98;">
    The password for your LAP account was recently changed. If you made this
    change, no further action is required.
  </p>
  <p style="color: #8A8F98;">
    If you did not change your password, please reset it immediately:
  </p>
  <a href="{reset_url}"
     style="display: inline-block; background: #B6FF2E; color: #0B0C0F;
            padding: 12px 24px; border-radius: 6px; text-decoration: none;
            font-weight: 600; margin: 16px 0;">
    Reset Password
  </a>
  <p style="color: #8A8F98; font-size: 12px;">
    If you did not make this change, your account may have been compromised.
    Please contact support immediately.
  </p>
</div>"""
    return _send(to, "Your LAP password was changed", html)


def send_export_ready_email(to: str, download_url: str) -> bool:
    """Send notification that a data export is ready for download."""
    html = f"""\
<div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto;">
  <h2 style="color: #F3F0E8;">Your data export is ready</h2>
  <p style="color: #8A8F98;">
    Your LAP data export has been completed and is ready for download.
  </p>
  <a href="{download_url}"
     style="display: inline-block; background: #B6FF2E; color: #0B0C0F;
            padding: 12px 24px; border-radius: 6px; text-decoration: none;
            font-weight: 600; margin: 16px 0;">
    Download Export
  </a>
  <p style="color: #8A8F98; font-size: 12px;">
    This download link will expire in 7 days.
  </p>
</div>"""
    return _send(to, "Your LAP data export is ready", html)


def send_account_deletion_email(to: str, cancel_url: str, deletion_date: str) -> bool:
    """Send notification that account deletion has been scheduled."""
    html = f"""\
<div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto;">
  <h2 style="color: #F3F0E8;">Account deletion scheduled</h2>
  <p style="color: #8A8F98;">
    Your LAP account has been scheduled for deletion. All your data will be
    permanently removed on <strong style="color: #F3F0E8;">{deletion_date}</strong>.
  </p>
  <p style="color: #8A8F98;">
    If you change your mind, you can cancel the deletion before that date:
  </p>
  <a href="{cancel_url}"
     style="display: inline-block; background: #FF6A00; color: #0B0C0F;
            padding: 12px 24px; border-radius: 6px; text-decoration: none;
            font-weight: 600; margin: 16px 0;">
    Cancel Deletion
  </a>
  <p style="color: #8A8F98; font-size: 12px;">
    After {deletion_date}, this action cannot be undone.
  </p>
</div>"""
    return _send(to, "Your LAP account will be deleted", html)


def send_new_login_email(to: str, device_info: str, ip_address: str) -> bool:
    """Send notification of a new login from an unrecognised device."""
    html = f"""\
<div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto;">
  <h2 style="color: #F3F0E8;">New login detected</h2>
  <p style="color: #8A8F98;">
    A new login to your LAP account was detected:
  </p>
  <table style="margin: 12px 0; border-collapse: collapse;">
    <tr>
      <td style="color: #8A8F98; padding: 4px 12px 4px 0;">Device:</td>
      <td style="color: #F3F0E8; padding: 4px 0;">{_esc(device_info)}</td>
    </tr>
    <tr>
      <td style="color: #8A8F98; padding: 4px 12px 4px 0;">IP Address:</td>
      <td style="color: #F3F0E8; padding: 4px 0;">{_esc(ip_address)}</td>
    </tr>
  </table>
  <p style="color: #8A8F98;">
    If this was you, no further action is needed.
  </p>
  <p style="color: #8A8F98;">
    If this was not you, please change your password immediately:
  </p>
  <a href="{FRONTEND_URL}/app/settings/security"
     style="display: inline-block; background: #B6FF2E; color: #0B0C0F;
            padding: 12px 24px; border-radius: 6px; text-decoration: none;
            font-weight: 600; margin: 16px 0;">
    Review Security Settings
  </a>
</div>"""
    return _send(to, "New login to your LAP account", html)


def send_2fa_enabled_email(to: str) -> bool:
    """Send notification that 2FA has been enabled on the account."""
    html = f"""\
<div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto;">
  <h2 style="color: #F3F0E8;">Two-factor authentication enabled</h2>
  <p style="color: #8A8F98;">
    2FA has been successfully enabled on your LAP account. Your account is
    now more secure.
  </p>
  <p style="color: #8A8F98;">
    Make sure you have saved your backup codes in a safe place. You will need
    them if you lose access to your authenticator app.
  </p>
  <a href="{FRONTEND_URL}/app/settings/security"
     style="display: inline-block; background: #B6FF2E; color: #0B0C0F;
            padding: 12px 24px; border-radius: 6px; text-decoration: none;
            font-weight: 600; margin: 16px 0;">
    View Security Settings
  </a>
  <p style="color: #8A8F98; font-size: 12px;">
    If you did not enable 2FA, please contact support immediately.
  </p>
</div>"""
    return _send(to, "2FA enabled on your LAP account", html)


def send_2fa_disabled_email(to: str) -> bool:
    """Send notification that 2FA has been disabled on the account."""
    html = f"""\
<div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto;">
  <h2 style="color: #F3F0E8;">Two-factor authentication disabled</h2>
  <p style="color: #8A8F98;">
    2FA has been disabled on your LAP account. Your account is now protected
    by password only.
  </p>
  <p style="color: #8A8F98;">
    We recommend re-enabling 2FA for better security:
  </p>
  <a href="{FRONTEND_URL}/app/settings/security"
     style="display: inline-block; background: #B6FF2E; color: #0B0C0F;
            padding: 12px 24px; border-radius: 6px; text-decoration: none;
            font-weight: 600; margin: 16px 0;">
    Re-enable 2FA
  </a>
  <p style="color: #8A8F98; font-size: 12px;">
    If you did not disable 2FA, your account may be compromised.
    Please change your password immediately.
  </p>
</div>"""
    return _send(to, "2FA disabled on your LAP account", html)


def send_team_invite_email(
    to: str, token: str, team_name: str, inviter_name: str,
) -> bool:
    """Send a team invitation email with an accept link."""
    accept_url = f"{FRONTEND_URL}/invitations/accept?token={token}"
    html = f"""\
<div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto;">
  <h2 style="color: #F3F0E8;">You've been invited to join {_esc(team_name)}</h2>
  <p style="color: #8A8F98;">
    <strong style="color: #F3F0E8;">{_esc(inviter_name)}</strong> has invited you to
    join <strong style="color: #F3F0E8;">{_esc(team_name)}</strong> on LAP.
  </p>
  <a href="{accept_url}"
     style="display: inline-block; background: #B6FF2E; color: #0B0C0F;
            padding: 12px 24px; border-radius: 6px; text-decoration: none;
            font-weight: 600; margin: 16px 0;">
    Accept Invitation
  </a>
  <p style="color: #8A8F98; font-size: 13px;">
    Or copy this link: <br>
    <code style="color: #F3F0E8;">{accept_url}</code>
  </p>
  <p style="color: #8A8F98; font-size: 12px;">
    This invitation expires in 7 days. If you don't have an account,
    you'll be asked to create one first.
  </p>
</div>"""
    return _send(to, f"You're invited to join {_esc(team_name)} on LAP", html)


def send_verification_reminder_email(to: str, token: str) -> bool:
    """Send a reminder to verify email address (sent ~24h after registration)."""
    verify_url = f"{FRONTEND_URL}/verify-email?token={token}"
    html = f"""\
<div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto;">
  <h2 style="color: #F3F0E8;">Don't forget to verify your email</h2>
  <p style="color: #8A8F98;">
    You registered for LAP recently but haven't verified your email address yet.
    Verify now to unlock all features and ensure you can recover your account.
  </p>
  <a href="{verify_url}"
     style="display: inline-block; background: #B6FF2E; color: #0B0C0F;
            padding: 12px 24px; border-radius: 6px; text-decoration: none;
            font-weight: 600; margin: 16px 0;">
    Verify My Email
  </a>
  <p style="color: #8A8F98; font-size: 13px;">
    If you didn't create this account, you can safely ignore this email.
  </p>
</div>"""
    return _send(to, "Reminder: Verify your LAP email address", html)


def send_retention_warning_email(to: str, session_name: str, expiry_date: str) -> bool:
    """Send data retention notice for a specific session nearing expiry."""
    html = f"""\
<div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto;">
  <h2 style="color: #F3F0E8;">Data retention notice</h2>
  <p style="color: #8A8F98;">
    The raw telemetry data for your session
    <strong style="color: #F3F0E8;">{_esc(session_name)}</strong> will be
    automatically deleted on
    <strong style="color: #F3F0E8;">{_esc(expiry_date)}</strong> based on
    your plan's retention policy.
  </p>
  <p style="color: #8A8F98;">
    Your reports, scores, and lap data will be preserved. To keep your
    raw data longer, export it now or upgrade your plan.
  </p>
  <a href="{FRONTEND_URL}/app/sessions"
     style="display: inline-block; background: #B6FF2E; color: #0B0C0F;
            padding: 12px 24px; border-radius: 6px; text-decoration: none;
            font-weight: 600; margin: 16px 0;">
    Export Data Now
  </a>
  <p style="color: #8A8F98; font-size: 13px;">
    Want longer retention?
    <a href="{FRONTEND_URL}/pricing" style="color: #B6FF2E;">Upgrade your plan</a>.
  </p>
</div>"""
    return _send(to, f"Data retention notice: {_esc(session_name)}", html)
