"""Tests for PROMPT 3C — Email System + Security + Admin + Compliance.

Validates:
- All 16 email templates render correctly with variables
- Email sends are logged in email_log table
- Signed URLs: generation, verification, expiry
- Input sanitization: filename, HTML
- Admin endpoints require is_platform_admin
- Impersonation generates valid short-lived token + audit log entry
- Compliance pages exist
- Migration 026 creates email_log + is_platform_admin
"""
import sys
import hashlib
import hmac
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ===========================================================================
# A) Email template registry
# ===========================================================================


class TestEmailTemplateRegistry:
    """All 16 templates are registered and render correctly."""

    def test_all_16_templates_registered(self):
        """Registry contains exactly 16 templates."""
        from auth.email_templates import TEMPLATES
        assert len(TEMPLATES) == 16

    def test_template_names(self):
        """All expected template names exist."""
        from auth.email_templates import TEMPLATES
        expected = {
            "verification", "welcome", "password_reset", "password_changed",
            "team_invitation", "team_joined", "report_ready",
            "retention_warning", "retention_deleted",
            "trial_ending", "payment_failed", "subscription_canceled",
            "payment_recovered", "new_login_location",
            "weekly_summary", "quota_warning",
        }
        assert set(TEMPLATES.keys()) == expected

    def test_verification_template_renders(self):
        """Verification template renders with verify_url."""
        from auth.email_templates import render_email
        subject, html = render_email("verification", {"verify_url": "https://example.com/verify"})
        assert "Verify" in subject
        assert "https://example.com/verify" in html

    def test_welcome_template_renders(self):
        """Welcome template renders with display_name."""
        from auth.email_templates import render_email
        subject, html = render_email("welcome", {"display_name": "Max"})
        assert "Max" in subject
        assert "Max" in html

    def test_password_reset_template(self):
        """Password reset includes reset URL."""
        from auth.email_templates import render_email
        subject, html = render_email("password_reset", {"reset_url": "https://example.com/reset"})
        assert "Reset" in subject
        assert "https://example.com/reset" in html

    def test_team_invitation_template(self):
        """Team invitation includes team name and inviter."""
        from auth.email_templates import render_email
        subject, html = render_email("team_invitation", {
            "accept_url": "https://example.com/accept",
            "team_name": "Team Alpha",
            "inviter_name": "Admin",
        })
        assert "Team Alpha" in subject
        assert "Admin" in html

    def test_team_joined_template(self):
        """Team joined includes member name."""
        from auth.email_templates import render_email
        subject, html = render_email("team_joined", {
            "member_name": "NewUser",
            "team_name": "Team Alpha",
        })
        assert "NewUser" in html

    def test_report_ready_template(self):
        """Report ready includes session name."""
        from auth.email_templates import render_email
        subject, html = render_email("report_ready", {
            "session_name": "Spa Test Day",
            "report_url": "https://example.com/report",
        })
        assert "Spa Test Day" in html

    def test_trial_ending_template(self):
        """Trial ending includes days remaining."""
        from auth.email_templates import render_email
        subject, html = render_email("trial_ending", {
            "plan_name": "Racer",
            "days_remaining": 3,
        })
        assert "3" in subject
        assert "View Plans" in html

    def test_payment_failed_template(self):
        """Payment failed includes amount."""
        from auth.email_templates import render_email
        subject, html = render_email("payment_failed", {
            "amount": "$19.99",
            "retry_date": "March 1",
        })
        assert "$19.99" in html
        assert "Update Payment Method" in html

    def test_subscription_canceled_template(self):
        """Cancellation includes resubscribe CTA."""
        from auth.email_templates import render_email
        subject, html = render_email("subscription_canceled", {
            "plan_name": "Pro Racer",
        })
        assert "canceled" in subject.lower()
        assert "Resubscribe" in html

    def test_payment_recovered_template(self):
        """Recovery email includes dashboard CTA."""
        from auth.email_templates import render_email
        subject, html = render_email("payment_recovered", {
            "plan_name": "Racer",
        })
        assert "active" in subject.lower() or "successful" in subject.lower()
        assert "Go to Dashboard" in html

    def test_weekly_summary_template(self):
        """Weekly summary includes stats."""
        from auth.email_templates import render_email
        subject, html = render_email("weekly_summary", {
            "sessions_count": 5,
            "best_score": "87/100",
            "improvement": "+3.2%",
        })
        assert "weekly" in subject.lower()
        assert "87/100" in html

    def test_quota_warning_template(self):
        """Quota warning includes feature and limits."""
        from auth.email_templates import render_email
        subject, html = render_email("quota_warning", {
            "feature": "reports",
            "used": 8,
            "limit": 10,
        })
        assert "reports" in subject.lower()
        assert "8" in html
        assert "10" in html

    def test_new_login_location_template(self):
        """New login includes IP and device."""
        from auth.email_templates import render_email
        subject, html = render_email("new_login_location", {
            "ip": "1.2.3.4",
            "device_info": "Chrome on Windows",
        })
        assert "1.2.3.4" in html
        assert "Chrome on Windows" in html

    def test_unknown_template_raises(self):
        """Unknown template name raises KeyError."""
        from auth.email_templates import render_email
        with pytest.raises(KeyError):
            render_email("nonexistent", {})

    def test_all_templates_have_wrapper(self):
        """All templates include the standard wrapper with logo and footer."""
        from auth.email_templates import TEMPLATES
        for name, builder in TEMPLATES.items():
            _, html = builder({
                "verify_url": "x", "reset_url": "x", "accept_url": "x",
                "team_name": "T", "inviter_name": "I", "member_name": "M",
                "session_name": "S", "report_url": "x",
                "plan_name": "P", "days_remaining": 1,
                "amount": "$1", "retry_date": "soon",
                "ip": "0.0.0.0", "device_info": "test",
                "sessions_count": 0, "best_score": 0, "improvement": "0",
                "feature": "x", "used": 0, "limit": 0,
                "sessions": [], "display_name": "X",
            })
            assert "Email preferences" in html, f"Template {name} missing footer"

    def test_list_templates(self):
        """list_templates returns sorted names."""
        from auth.email_templates import list_templates
        names = list_templates()
        assert len(names) == 16
        assert names == sorted(names)


# ===========================================================================
# B) Async email sending + logging
# ===========================================================================


class TestEmailTasks:
    """Async email sending via Celery + email_log."""

    def test_send_email_impl_success(self):
        """Successful send returns sent=True and logs to email_log."""
        from tasks.email_tasks import _send_email_impl
        with patch("tasks.email_tasks._get_pg") as mock_pg, \
             patch("auth.email._send", return_value=True):
            conn = MagicMock()
            mock_pg.return_value = conn
            result = _send_email_impl("welcome", "u@test.com", {"display_name": "X"})
        assert result["sent"] is True
        assert result["template"] == "welcome"
        # Verify email_log INSERT was called
        insert_calls = [c for c in conn.execute.call_args_list
                        if "email_log" in str(c)]
        assert len(insert_calls) > 0

    def test_send_email_impl_failure(self):
        """Failed send returns sent=False and logs error."""
        from tasks.email_tasks import _send_email_impl
        with patch("tasks.email_tasks._get_pg") as mock_pg, \
             patch("auth.email._send", return_value=False):
            conn = MagicMock()
            mock_pg.return_value = conn
            result = _send_email_impl("welcome", "u@test.com", {"display_name": "X"})
        assert result["sent"] is False
        assert result["error"] is not None

    def test_send_email_unknown_template(self):
        """Unknown template returns error without sending."""
        from tasks.email_tasks import _send_email_impl
        with patch("tasks.email_tasks._get_pg") as mock_pg:
            conn = MagicMock()
            mock_pg.return_value = conn
            result = _send_email_impl("nonexistent", "u@test.com", {})
        assert result["sent"] is False
        assert "Unknown" in result["error"]

    def test_send_email_async_callable(self):
        """send_email_async function is importable and callable."""
        from tasks.email_tasks import send_email_async
        assert callable(send_email_async)


# ===========================================================================
# C) Signed URLs
# ===========================================================================


class TestSignedUrls:
    """HMAC-signed URL generation and verification."""

    def test_create_signed_url(self):
        """create_signed_url produces URL with expires and signature params."""
        from web.signed_urls import create_signed_url
        url = create_signed_url("/api/v1/exports/abc.zip", expires_in=3600)
        assert "expires=" in url
        assert "signature=" in url
        assert "/api/v1/exports/abc.zip" in url

    def test_verify_valid_url(self):
        """verify_signed_url returns (True, path) for valid URL."""
        from web.signed_urls import create_signed_url, verify_signed_url
        url = create_signed_url("/exports/test.zip", expires_in=3600)
        valid, path = verify_signed_url(url)
        assert valid is True
        assert path == "/exports/test.zip"

    def test_verify_expired_url(self):
        """Expired URL returns (False, path)."""
        from web.signed_urls import create_signed_url, verify_signed_url
        # Create with 0-second expiry
        url = create_signed_url("/exports/test.zip", expires_in=-1)
        valid, path = verify_signed_url(url)
        assert valid is False

    def test_verify_tampered_signature(self):
        """Tampered signature returns (False, path)."""
        from web.signed_urls import create_signed_url, verify_signed_url
        url = create_signed_url("/exports/test.zip", expires_in=3600)
        # Tamper with last character
        tampered = url[:-1] + ("a" if url[-1] != "a" else "b")
        valid, path = verify_signed_url(tampered)
        assert valid is False

    def test_verify_missing_params(self):
        """URL without expires/signature params returns False."""
        from web.signed_urls import verify_signed_url
        valid, _ = verify_signed_url("https://example.com/file.zip")
        assert valid is False


# ===========================================================================
# D) Input sanitization
# ===========================================================================


class TestInputSanitization:
    """Filename and HTML sanitization."""

    def test_sanitize_filename_basic(self):
        """Basic filename passes through."""
        from web.validation import sanitize_filename
        assert sanitize_filename("session.csv") == "session.csv"

    def test_sanitize_filename_path_traversal(self):
        """Path traversal is stripped."""
        from web.validation import sanitize_filename
        result = sanitize_filename("../../etc/passwd")
        assert ".." not in result
        assert "/" not in result
        assert "passwd" in result

    def test_sanitize_filename_unsafe_chars(self):
        """Unsafe characters are removed."""
        from web.validation import sanitize_filename
        result = sanitize_filename('my<file>:test?.csv')
        assert "<" not in result
        assert ">" not in result
        assert "?" not in result

    def test_sanitize_filename_length_limit(self):
        """Long filenames are truncated."""
        from web.validation import sanitize_filename
        long_name = "a" * 300 + ".csv"
        result = sanitize_filename(long_name, max_length=200)
        assert len(result) <= 200
        assert result.endswith(".csv")

    def test_sanitize_filename_empty(self):
        """Empty filename returns 'unnamed'."""
        from web.validation import sanitize_filename
        assert sanitize_filename("") == "unnamed"

    def test_sanitize_html_strips_tags(self):
        """HTML tags are stripped."""
        from web.validation import sanitize_html
        result = sanitize_html("<script>alert('xss')</script>Hello")
        assert "<script>" not in result
        assert "Hello" in result

    def test_sanitize_html_preserves_text(self):
        """Plain text passes through."""
        from web.validation import sanitize_html
        assert sanitize_html("Normal text") == "Normal text"

    def test_sanitize_html_length_limit(self):
        """Long text is truncated."""
        from web.validation import sanitize_html
        result = sanitize_html("a" * 20000, max_length=100)
        assert len(result) == 100


# ===========================================================================
# E) Admin API
# ===========================================================================


class TestAdminEndpoints:
    """Admin backoffice API — blueprint + access control."""

    def test_admin_blueprint_registered(self):
        """admin blueprint is registered in app.py."""
        source = Path(_PROJECT_ROOT / "web" / "app.py").read_text()
        assert "admin_bp" in source

    def test_admin_routes_exist(self):
        """Key admin endpoint functions exist."""
        from web.routes.admin import (
            list_users, get_user_detail, suspend_user, unsuspend_user,
            create_override, impersonate_user, list_workspaces,
            list_audit_log, billing_overview,
        )
        assert all(callable(f) for f in [
            list_users, get_user_detail, suspend_user, unsuspend_user,
            create_override, impersonate_user, list_workspaces,
            list_audit_log, billing_overview,
        ])

    def test_admin_guard_exists(self):
        """before_request guard checks is_platform_admin."""
        source = Path(_PROJECT_ROOT / "web" / "routes" / "admin.py").read_text()
        assert "is_platform_admin" in source
        assert "before_request" in source
        assert "Platform admin required" in source

    def test_suspend_requires_reason(self):
        """Suspend endpoint requires a reason."""
        source = Path(_PROJECT_ROOT / "web" / "routes" / "admin.py").read_text()
        assert "Reason is required" in source

    def test_impersonate_generates_token(self):
        """Impersonate generates JWT with 15-minute expiry."""
        source = Path(_PROJECT_ROOT / "web" / "routes" / "admin.py").read_text()
        assert "impersonated_by" in source
        assert "minutes=15" in source

    def test_impersonate_audits(self):
        """Impersonation is logged in audit_log."""
        source = Path(_PROJECT_ROOT / "web" / "routes" / "admin.py").read_text()
        assert "admin_impersonation" in source


# ===========================================================================
# F) Migration 026
# ===========================================================================


class TestMigrationConsolidated:
    """Consolidated migrations contain email_log and is_platform_admin."""

    def test_migration_021_chains_from_020(self):
        """021 revision chains from 020."""
        source = Path(_PROJECT_ROOT / "alembic" / "versions" / "021_community_email.py").read_text()
        assert 'down_revision = "020"' in source

    def test_migration_021_creates_email_log(self):
        """021 creates the email_log table."""
        source = Path(_PROJECT_ROOT / "alembic" / "versions" / "021_community_email.py").read_text()
        assert "email_log" in source
        assert "template" in source
        assert "to_email" in source
        assert "status" in source

    def test_migration_019_adds_platform_admin(self):
        """019 adds is_platform_admin to users."""
        source = Path(_PROJECT_ROOT / "alembic" / "versions" / "019_core_data_model.py").read_text()
        assert "is_platform_admin" in source


# ===========================================================================
# G) Admin frontend
# ===========================================================================


class TestAdminFrontend:
    """Admin frontend pages exist."""

    def test_admin_layout_exists(self):
        """Admin layout component exists."""
        path = _PROJECT_ROOT.parent / "lap-website" / "src" / "app" / "admin" / "layout.tsx"
        assert path.exists()

    def test_admin_dashboard_exists(self):
        """Admin dashboard page exists."""
        path = _PROJECT_ROOT.parent / "lap-website" / "src" / "app" / "admin" / "page.tsx"
        assert path.exists()
        source = path.read_text()
        assert "AdminDashboard" in source or "admin" in source.lower()

    def test_admin_users_page_exists(self):
        """Admin users page exists with suspend/unsuspend."""
        path = _PROJECT_ROOT.parent / "lap-website" / "src" / "app" / "admin" / "users" / "page.tsx"
        assert path.exists()
        source = path.read_text()
        assert "Suspend" in source
        assert "Unsuspend" in source

    def test_admin_audit_page_exists(self):
        """Admin audit log page exists with filters."""
        path = _PROJECT_ROOT.parent / "lap-website" / "src" / "app" / "admin" / "audit" / "page.tsx"
        assert path.exists()
        source = path.read_text()
        assert "audit" in source.lower()


# ===========================================================================
# H) Compliance pages
# ===========================================================================


class TestCompliancePages:
    """Compliance pages exist and are linked from footer."""

    def test_privacy_page_exists(self):
        path = _PROJECT_ROOT.parent / "lap-website" / "src" / "app" / "(marketing)" / "privacy" / "page.tsx"
        assert path.exists()

    def test_terms_page_exists(self):
        path = _PROJECT_ROOT.parent / "lap-website" / "src" / "app" / "(marketing)" / "terms" / "page.tsx"
        assert path.exists()

    def test_dpa_page_exists(self):
        path = _PROJECT_ROOT.parent / "lap-website" / "src" / "app" / "(marketing)" / "dpa" / "page.tsx"
        assert path.exists()

    def test_subprocessors_page_exists(self):
        path = _PROJECT_ROOT.parent / "lap-website" / "src" / "app" / "(marketing)" / "subprocessors" / "page.tsx"
        assert path.exists()
        source = path.read_text()
        assert "Stripe" in source
        assert "Resend" in source
        assert "Cloudflare" in source
        assert "Hetzner" in source

    def test_footer_links_include_compliance(self):
        """Footer navigation includes all compliance pages."""
        nav_path = _PROJECT_ROOT.parent / "lap-website" / "src" / "data" / "navigation.ts"
        source = nav_path.read_text()
        assert "/privacy" in source
        assert "/terms" in source
        assert "/dpa" in source
        assert "/subprocessors" in source

    def test_email_deliverability_docs_exist(self):
        """SPF/DKIM/DMARC documentation exists."""
        doc_path = _PROJECT_ROOT.parent / "docs" / "email-deliverability.md"
        assert doc_path.exists()
        source = doc_path.read_text()
        assert "SPF" in source
        assert "DKIM" in source
        assert "DMARC" in source
