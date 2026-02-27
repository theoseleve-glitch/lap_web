# Account Experience & Billing Ops — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a complete self-serve Account section with entitlements, usage enforcement, TOTP 2FA, Stripe Customer Portal, and data privacy controls.

**Architecture:** Entitlement-first — a central `auth/entitlements.py` module maps `billing_plan` → features/limits. Usage tracked in `usage_counters` table. Stripe Customer Portal for payment management. TOTP 2FA with backup codes. All behind sidebar sub-navigation at `/app/account/*`.

**Tech Stack:** Python/Flask (backend), PostgreSQL + Alembic (DB), Celery + Redis (async), Stripe API + webhooks, pyotp + qrcode (TOTP), Resend (email), Next.js 14 + Tailwind + Zustand (frontend), Vitest + Playwright (tests)

**Design doc:** `docs/plans/2026-02-27-account-experience-design.md`

---

## Phase 1: Database Migration & Entitlements Module

### Task 1: Write Alembic migration 020

**Files:**
- Create: `telemetry_tool/alembic/versions/020_account_experience.py`

**Context:** Migration 019 is the latest. Follow the pattern in `019_entitlements_usage.py` — use `op.add_column()`, `op.create_table()`, `conn.execute(sa.text(...))` for RLS.

**Step 1: Create the migration file**

```python
"""020 — Account experience: preferences, TOTP 2FA, usage counters, support tickets.

Revision ID: 020
Revises: 019
"""
from alembic import op
import sqlalchemy as sa


revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # ── User preferences & TOTP columns ──────────────────────────
    op.add_column("users", sa.Column("preferences", sa.JSON(), server_default="{}"))
    op.add_column("users", sa.Column("totp_secret", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("totp_enabled", sa.Boolean(), server_default="false"))
    op.add_column("users", sa.Column("totp_backup_codes", sa.ARRAY(sa.Text()), nullable=True))
    op.add_column("users", sa.Column("totp_verified_at", sa.DateTime(timezone=True), nullable=True))

    # ── Usage counters ────────────────────────────────────────────
    op.create_table(
        "usage_counters",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("period", sa.Text(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "metric", "period", name="uq_usage_ws_metric_period"),
    )
    op.create_index("idx_usage_counters_lookup", "usage_counters", ["workspace_id", "metric", "period"])

    # RLS for usage_counters
    conn.execute(sa.text('ALTER TABLE "usage_counters" ENABLE ROW LEVEL SECURITY'))
    conn.execute(sa.text(
        'CREATE POLICY "usage_counters_tenant_isolation" ON "usage_counters" '
        "USING (workspace_id = current_setting('app.current_workspace_id')::integer)"
    ))

    # ── Support tickets ───────────────────────────────────────────
    op.create_table(
        "support_tickets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("issue_type", sa.Text(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("diagnostics", sa.JSON(), nullable=True),
        sa.Column("status", sa.Text(), server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_support_tickets_user", "support_tickets", ["user_id"])

    # RLS for support_tickets
    conn.execute(sa.text('ALTER TABLE "support_tickets" ENABLE ROW LEVEL SECURITY'))
    conn.execute(sa.text(
        'CREATE POLICY "support_tickets_tenant_isolation" ON "support_tickets" '
        "USING (workspace_id = current_setting('app.current_workspace_id')::integer)"
    ))

    # ── Add device_info tracking to refresh_tokens ────────────────
    # device_info column may already exist from schema.py; add if missing
    try:
        op.add_column("refresh_tokens", sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column("refresh_tokens", sa.Column("ip_address", sa.Text(), nullable=True))
        op.add_column("refresh_tokens", sa.Column("user_agent", sa.Text(), nullable=True))
    except Exception:
        pass  # Columns may already exist


def downgrade():
    conn = op.get_bind()

    # Drop RLS policies
    conn.execute(sa.text('DROP POLICY IF EXISTS "support_tickets_tenant_isolation" ON "support_tickets"'))
    conn.execute(sa.text('ALTER TABLE "support_tickets" DISABLE ROW LEVEL SECURITY'))
    conn.execute(sa.text('DROP POLICY IF EXISTS "usage_counters_tenant_isolation" ON "usage_counters"'))
    conn.execute(sa.text('ALTER TABLE "usage_counters" DISABLE ROW LEVEL SECURITY'))

    # Drop tables
    op.drop_table("support_tickets")
    op.drop_index("idx_usage_counters_lookup")
    op.drop_table("usage_counters")

    # Drop user columns
    op.drop_column("users", "totp_verified_at")
    op.drop_column("users", "totp_backup_codes")
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")
    op.drop_column("users", "preferences")

    # Drop refresh_tokens columns
    try:
        op.drop_column("refresh_tokens", "user_agent")
        op.drop_column("refresh_tokens", "ip_address")
        op.drop_column("refresh_tokens", "last_used_at")
    except Exception:
        pass
```

**Step 2: Run migration**

Run: `cd telemetry_tool && alembic upgrade head`
Expected: Migration 020 applied successfully.

**Step 3: Commit**

```bash
git add telemetry_tool/alembic/versions/020_account_experience.py
git commit -m "feat(db): add migration 020 for account experience (preferences, TOTP, usage, support)"
```

---

### Task 2: Create entitlements module with tests

**Files:**
- Create: `telemetry_tool/auth/entitlements.py`
- Create: `telemetry_tool/tests/test_entitlements.py`

**Step 1: Write the failing tests**

```python
# telemetry_tool/tests/test_entitlements.py
"""Tests for the entitlements module."""
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pytest
from auth.entitlements import (
    get_plan_entitlements,
    check_usage_limit,
    PLAN_ENTITLEMENTS,
    KNOWN_PLANS,
)


class TestPlanEntitlements:
    def test_free_plan_has_one_report(self):
        ent = get_plan_entitlements("free")
        assert ent["reports_per_month"] == 1

    def test_racer_plan_has_ten_reports(self):
        ent = get_plan_entitlements("racer")
        assert ent["reports_per_month"] == 10

    def test_world_class_has_unlimited_reports(self):
        ent = get_plan_entitlements("world_class")
        assert ent["reports_per_month"] == -1

    def test_unknown_plan_falls_back_to_free(self):
        ent = get_plan_entitlements("nonexistent")
        assert ent == get_plan_entitlements("free")

    def test_all_plans_have_required_keys(self):
        required = {"reports_per_month", "uploads_per_month", "raw_retention_days"}
        for plan in KNOWN_PLANS:
            ent = get_plan_entitlements(plan)
            assert required.issubset(ent.keys()), f"{plan} missing keys"

    def test_demo_is_alias_for_free(self):
        assert get_plan_entitlements("demo") == get_plan_entitlements("free")


class TestUsageLimitCheck:
    def test_under_limit_allowed(self):
        ok, info = check_usage_limit(plan="racer", metric="reports", current_count=5)
        assert ok is True
        assert info["limit"] == 10
        assert info["used"] == 5
        assert info["remaining"] == 5

    def test_at_limit_blocked(self):
        ok, info = check_usage_limit(plan="racer", metric="reports", current_count=10)
        assert ok is False
        assert info["remaining"] == 0

    def test_over_limit_blocked(self):
        ok, info = check_usage_limit(plan="racer", metric="reports", current_count=15)
        assert ok is False

    def test_unlimited_always_allowed(self):
        ok, info = check_usage_limit(plan="world_class", metric="reports", current_count=99999)
        assert ok is True
        assert info["remaining"] == -1  # unlimited sentinel

    def test_free_plan_single_upload(self):
        ok, _ = check_usage_limit(plan="free", metric="uploads", current_count=0)
        assert ok is True
        ok, _ = check_usage_limit(plan="free", metric="uploads", current_count=1)
        assert ok is False

    def test_unknown_metric_defaults_blocked(self):
        ok, info = check_usage_limit(plan="racer", metric="unknown_thing", current_count=0)
        assert ok is False
        assert info["limit"] == 0
```

**Step 2: Run tests to verify they fail**

Run: `cd telemetry_tool && python -m pytest tests/test_entitlements.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'auth.entitlements'`

**Step 3: Write the entitlements module**

```python
# telemetry_tool/auth/entitlements.py
"""Plan entitlements — single source of truth for what each plan can do.

Maps billing_plan strings to feature flags and numeric limits.
All API enforcement flows through this module.
"""
from __future__ import annotations

PLAN_ENTITLEMENTS: dict[str, dict] = {
    "free": {
        "reports_per_month": 1,
        "uploads_per_month": 1,
        "raw_retention_days": 30,
        "report_retention": "indefinite",
        "comparison_progress": False,
        "coaching_drills": False,
        "viz_workspace": False,
        "strategy_dashboard": "3h_limit",
        "live_pace": False,
        "pit_planning": False,
        "pdf_reports": False,
        "api_access": False,
        "track_management": "basic",
        "max_workspace_members": 1,
    },
    "racer": {
        "reports_per_month": 10,
        "uploads_per_month": 10,
        "raw_retention_days": 90,
        "report_retention": "indefinite",
        "comparison_progress": False,
        "coaching_drills": True,
        "viz_workspace": True,
        "strategy_dashboard": "full",
        "live_pace": True,
        "pit_planning": True,
        "pdf_reports": True,
        "api_access": False,
        "track_management": "full",
        "max_workspace_members": 1,
    },
    "world_class": {
        "reports_per_month": -1,
        "uploads_per_month": -1,
        "raw_retention_days": 365,
        "report_retention": "indefinite",
        "comparison_progress": True,
        "coaching_drills": True,
        "viz_workspace": True,
        "strategy_dashboard": "full",
        "live_pace": True,
        "pit_planning": True,
        "pdf_reports": True,
        "api_access": True,
        "track_management": "full",
        "max_workspace_members": 5,
    },
}

# "demo" is an alias for "free"
PLAN_ENTITLEMENTS["demo"] = PLAN_ENTITLEMENTS["free"]

KNOWN_PLANS = set(PLAN_ENTITLEMENTS.keys())

# Maps metric names to entitlement keys
_METRIC_TO_ENTITLEMENT: dict[str, str] = {
    "reports": "reports_per_month",
    "uploads": "uploads_per_month",
}


def get_plan_entitlements(plan: str) -> dict:
    """Return the entitlement dict for *plan*, falling back to free."""
    return PLAN_ENTITLEMENTS.get(plan, PLAN_ENTITLEMENTS["free"])


def check_usage_limit(
    plan: str, metric: str, current_count: int
) -> tuple[bool, dict]:
    """Check whether *current_count* of *metric* is within plan limits.

    Returns (allowed: bool, info: dict) where info contains
    limit, used, and remaining.
    """
    ent = get_plan_entitlements(plan)
    ent_key = _METRIC_TO_ENTITLEMENT.get(metric)
    if ent_key is None:
        return False, {"limit": 0, "used": current_count, "remaining": 0}

    limit = ent.get(ent_key, 0)

    if limit == -1:  # unlimited
        return True, {"limit": -1, "used": current_count, "remaining": -1}

    remaining = max(0, limit - current_count)
    allowed = current_count < limit
    return allowed, {"limit": limit, "used": current_count, "remaining": remaining}
```

**Step 4: Run tests to verify they pass**

Run: `cd telemetry_tool && python -m pytest tests/test_entitlements.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add telemetry_tool/auth/entitlements.py telemetry_tool/tests/test_entitlements.py
git commit -m "feat(auth): add entitlements module with plan-to-feature mapping"
```

---

### Task 3: Create usage tracking service with tests

**Files:**
- Create: `telemetry_tool/auth/usage.py`
- Create: `telemetry_tool/tests/test_usage_service.py`

**Step 1: Write the failing tests**

```python
# telemetry_tool/tests/test_usage_service.py
"""Tests for the usage tracking service."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pytest
from auth.usage import (
    get_current_period,
    get_usage_count,
    increment_usage,
    get_usage_snapshot,
)


class TestCurrentPeriod:
    def test_returns_yyyy_mm_format(self):
        period = get_current_period()
        assert len(period) == 7
        assert period[4] == "-"

    def test_returns_current_month(self):
        now = datetime.now(timezone.utc)
        expected = f"{now.year}-{now.month:02d}"
        assert get_current_period() == expected


class TestGetUsageCount:
    def test_returns_zero_when_no_row(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = None
        count = get_usage_count(conn, workspace_id=1, metric="reports")
        assert count == 0

    def test_returns_count_from_row(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {"count": 7}
        count = get_usage_count(conn, workspace_id=1, metric="reports")
        assert count == 7


class TestIncrementUsage:
    def test_calls_upsert(self):
        conn = MagicMock()
        increment_usage(conn, workspace_id=1, metric="reports")
        conn.execute.assert_called_once()
        sql_arg = str(conn.execute.call_args[0][0])
        assert "INSERT INTO" in sql_arg or "usage_counters" in sql_arg

    def test_increments_by_one_default(self):
        conn = MagicMock()
        increment_usage(conn, workspace_id=1, metric="uploads")
        conn.commit.assert_called_once()


class TestUsageSnapshot:
    def test_returns_all_tracked_metrics(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = None
        snapshot = get_usage_snapshot(conn, workspace_id=1, plan="racer")
        assert "reports" in snapshot
        assert "uploads" in snapshot
        assert snapshot["reports"]["limit"] == 10
        assert snapshot["reports"]["used"] == 0
```

**Step 2: Run tests to verify they fail**

Run: `cd telemetry_tool && python -m pytest tests/test_usage_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'auth.usage'`

**Step 3: Write the usage service**

```python
# telemetry_tool/auth/usage.py
"""Usage tracking — increment counters, read snapshots, check limits."""
from __future__ import annotations

from datetime import datetime, timezone

from auth.entitlements import get_plan_entitlements, _METRIC_TO_ENTITLEMENT


def get_current_period() -> str:
    """Return current billing period as 'YYYY-MM'."""
    now = datetime.now(timezone.utc)
    return f"{now.year}-{now.month:02d}"


def get_usage_count(conn, workspace_id: int, metric: str, period: str | None = None) -> int:
    """Return the current count for *metric* in *period* (defaults to current month)."""
    if period is None:
        period = get_current_period()
    cur = conn.execute(
        "SELECT count FROM usage_counters "
        "WHERE workspace_id = %(ws)s AND metric = %(m)s AND period = %(p)s",
        {"ws": workspace_id, "m": metric, "p": period},
    )
    row = cur.fetchone()
    return row["count"] if row else 0


def increment_usage(conn, workspace_id: int, metric: str, amount: int = 1) -> int:
    """Atomically increment *metric* counter. Returns new count."""
    period = get_current_period()
    conn.execute(
        "INSERT INTO usage_counters (workspace_id, metric, period, count, updated_at) "
        "VALUES (%(ws)s, %(m)s, %(p)s, %(amt)s, NOW()) "
        "ON CONFLICT (workspace_id, metric, period) "
        "DO UPDATE SET count = usage_counters.count + %(amt)s, updated_at = NOW()",
        {"ws": workspace_id, "m": metric, "p": period, "amt": amount},
    )
    conn.commit()
    return get_usage_count(conn, workspace_id, metric, period)


def get_usage_snapshot(conn, workspace_id: int, plan: str) -> dict:
    """Return usage snapshot for all tracked metrics.

    Returns dict like:
    {
        "reports": {"used": 7, "limit": 10, "remaining": 3, "resets": "2026-03-01"},
        "uploads": {"used": 2, "limit": 10, "remaining": 8, "resets": "2026-03-01"},
    }
    """
    ent = get_plan_entitlements(plan)
    period = get_current_period()

    # Calculate reset date (first of next month)
    now = datetime.now(timezone.utc)
    if now.month == 12:
        reset_date = f"{now.year + 1}-01-01"
    else:
        reset_date = f"{now.year}-{now.month + 1:02d}-01"

    snapshot = {}
    for metric, ent_key in _METRIC_TO_ENTITLEMENT.items():
        used = get_usage_count(conn, workspace_id, metric, period)
        limit = ent.get(ent_key, 0)
        if limit == -1:
            remaining = -1
        else:
            remaining = max(0, limit - used)
        snapshot[metric] = {
            "used": used,
            "limit": limit,
            "remaining": remaining,
            "resets": reset_date,
        }
    return snapshot
```

**Step 4: Run tests to verify they pass**

Run: `cd telemetry_tool && python -m pytest tests/test_usage_service.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add telemetry_tool/auth/usage.py telemetry_tool/tests/test_usage_service.py
git commit -m "feat(auth): add usage tracking service with atomic counters"
```

---

## Phase 2: Password Management & Session Endpoints

### Task 4: Add password change and reset endpoints with tests

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_account.py` (add password change)
- Modify: `telemetry_tool/web/routes/auth.py` (add forgot-password, reset-password)
- Modify: `telemetry_tool/auth/email.py` (add password email templates)
- Create: `telemetry_tool/web/schemas/security.py`
- Create: `telemetry_tool/tests/test_password_management.py`

**Step 1: Write the Pydantic schemas**

```python
# telemetry_tool/web/schemas/security.py
"""Schemas for security endpoints: password, 2FA, sessions."""
from pydantic import BaseModel, Field


class PasswordChangeSchema(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=1024)


class ForgotPasswordSchema(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class ResetPasswordSchema(BaseModel):
    token: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=1024)


class TotpSetupVerifySchema(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class TotpDisableSchema(BaseModel):
    password: str = Field(min_length=1)
    code: str = Field(min_length=6, max_length=8)  # 6 for TOTP, 8 for backup


class TotpLoginSchema(BaseModel):
    temp_token: str = Field(min_length=1)
    code: str = Field(min_length=6, max_length=8)
```

**Step 2: Write failing tests**

```python
# telemetry_tool/tests/test_password_management.py
"""Tests for password change and reset flows."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, ANY
from datetime import datetime, timezone, timedelta

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pytest
from flask import Flask, g
from web.routes.api_v1_account import bp as account_bp
from web.api_utils import init_request_id


def _make_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["JWT_SECRET"] = "test-secret-key-for-jwt-signing"
    init_request_id(app)
    app.register_blueprint(account_bp)

    @app.before_request
    def _inject_user():
        g.user_id = 1
        g.workspace_id = 1
        g.workspace_role = "owner"

    return app


@pytest.fixture
def client():
    app = _make_app()
    return app.test_client()


class TestPasswordChange:
    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_rejects_wrong_current_password(self, mock_db, client):
        conn = MagicMock()
        mock_db.return_value = conn
        # Return a user with a known hash
        from auth.service import hash_password
        conn.execute.return_value.fetchone.return_value = {
            "password_hash": hash_password("correct-password")
        }
        resp = client.post("/api/v1/account/password", json={
            "current_password": "wrong-password",
            "new_password": "new-secure-password-123"
        })
        assert resp.status_code == 403

    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_accepts_correct_password(self, mock_db, client):
        conn = MagicMock()
        mock_db.return_value = conn
        from auth.service import hash_password
        conn.execute.return_value.fetchone.return_value = {
            "password_hash": hash_password("correct-password")
        }
        resp = client.post("/api/v1/account/password", json={
            "current_password": "correct-password",
            "new_password": "new-secure-password-123"
        })
        assert resp.status_code == 200

    def test_rejects_short_new_password(self, client):
        resp = client.post("/api/v1/account/password", json={
            "current_password": "anything",
            "new_password": "short"
        })
        assert resp.status_code == 422
```

**Step 3: Run tests to verify they fail**

Run: `cd telemetry_tool && python -m pytest tests/test_password_management.py -v`
Expected: FAIL — endpoint doesn't exist yet.

**Step 4: Implement password change endpoint**

Add to `telemetry_tool/web/routes/api_v1_account.py` after the existing profile endpoint:

```python
@bp.route("/password", methods=["POST"])
@rate_limit(tier="auth")
@validate_body(PasswordChangeSchema)
def change_password():
    """Change the current user's password."""
    from auth.service import verify_password, hash_password

    body = g.body
    conn = get_pg_connection()

    # Fetch current password hash
    cur = conn.execute(
        "SELECT password_hash FROM users WHERE id = %(uid)s",
        {"uid": g.user_id},
    )
    row = cur.fetchone()
    if not row or not row["password_hash"]:
        return api_error("NO_PASSWORD", "Account uses OAuth — set a password first", status=400)

    if not verify_password(body.current_password, row["password_hash"]):
        return api_error("INVALID_CREDENTIALS", "Current password is incorrect", status=403)

    new_hash = hash_password(body.new_password)
    conn.execute(
        "UPDATE users SET password_hash = %(hash)s WHERE id = %(uid)s",
        {"hash": new_hash, "uid": g.user_id},
    )

    # Revoke all refresh tokens except the current one
    conn.execute(
        "UPDATE refresh_tokens SET revoked_at = NOW() "
        "WHERE user_id = %(uid)s AND revoked_at IS NULL",
        {"uid": g.user_id},
    )
    conn.commit()

    # Send notification email (non-blocking)
    try:
        cur = conn.execute("SELECT email FROM users WHERE id = %(uid)s", {"uid": g.user_id})
        email_row = cur.fetchone()
        if email_row:
            from auth.email import send_password_changed_email
            send_password_changed_email(email_row["email"])
    except Exception:
        logger.warning("Password change email failed", exc_info=True)

    return api_response({"message": "Password changed successfully"})
```

Add the import for `PasswordChangeSchema` at the top of the file:
```python
from web.schemas.security import PasswordChangeSchema
```

**Step 5: Add email templates to `auth/email.py`**

Append to `telemetry_tool/auth/email.py`:

```python
def send_password_changed_email(to: str) -> bool:
    """Notify user their password was changed."""
    html = f"""
    <div style="background:#0B0C0F;color:#F3F0E8;padding:32px;font-family:Inter,sans-serif;">
      <h2 style="color:#B6FF2E;font-family:Teko,sans-serif;">Password Changed</h2>
      <p>Your LAP password was just changed. If this wasn't you, reset your password immediately.</p>
      <a href="{FRONTEND_URL}/forgot-password"
         style="display:inline-block;background:#FF6A00;color:#0B0C0F;padding:12px 24px;
                border-radius:4px;text-decoration:none;font-weight:600;">
        Reset Password
      </a>
    </div>
    """
    return _send(to, "Your password was changed — LAP", html)


def send_password_reset_email(to: str, token: str) -> bool:
    """Send password reset link."""
    reset_url = f"{FRONTEND_URL}/reset-password?token={token}"
    html = f"""
    <div style="background:#0B0C0F;color:#F3F0E8;padding:32px;font-family:Inter,sans-serif;">
      <h2 style="color:#B6FF2E;font-family:Teko,sans-serif;">Reset Your Password</h2>
      <p>Click below to reset your password. This link expires in 1 hour.</p>
      <a href="{reset_url}"
         style="display:inline-block;background:#FF6A00;color:#0B0C0F;padding:12px 24px;
                border-radius:4px;text-decoration:none;font-weight:600;">
        Reset Password
      </a>
      <p style="color:#8A8F98;font-size:12px;margin-top:24px;">
        If you didn't request this, ignore this email.
      </p>
    </div>
    """
    return _send(to, "Reset your password — LAP", html)


def send_export_ready_email(to: str, download_url: str) -> bool:
    """Notify user their data export is ready."""
    html = f"""
    <div style="background:#0B0C0F;color:#F3F0E8;padding:32px;font-family:Inter,sans-serif;">
      <h2 style="color:#B6FF2E;font-family:Teko,sans-serif;">Your Data Export is Ready</h2>
      <p>Your data export has been prepared. Download it within 7 days.</p>
      <a href="{download_url}"
         style="display:inline-block;background:#FF6A00;color:#0B0C0F;padding:12px 24px;
                border-radius:4px;text-decoration:none;font-weight:600;">
        Download Export
      </a>
    </div>
    """
    return _send(to, "Your data export is ready — LAP", html)


def send_account_deletion_email(to: str, cancel_url: str, deletion_date: str) -> bool:
    """Notify user their account deletion is scheduled."""
    html = f"""
    <div style="background:#0B0C0F;color:#F3F0E8;padding:32px;font-family:Inter,sans-serif;">
      <h2 style="color:#FF2A2A;font-family:Teko,sans-serif;">Account Deletion Scheduled</h2>
      <p>Your account is scheduled for permanent deletion on <strong>{deletion_date}</strong>.</p>
      <p>If you change your mind, you can cancel the deletion within 30 days.</p>
      <a href="{cancel_url}"
         style="display:inline-block;background:#FF6A00;color:#0B0C0F;padding:12px 24px;
                border-radius:4px;text-decoration:none;font-weight:600;">
        Cancel Deletion
      </a>
    </div>
    """
    return _send(to, "Account deletion scheduled — LAP", html)


def send_new_login_email(to: str, device_info: str, ip_address: str) -> bool:
    """Notify user of a new login."""
    html = f"""
    <div style="background:#0B0C0F;color:#F3F0E8;padding:32px;font-family:Inter,sans-serif;">
      <h2 style="color:#B6FF2E;font-family:Teko,sans-serif;">New Login Detected</h2>
      <p>A new login to your LAP account was detected:</p>
      <p style="color:#8A8F98;">Device: {device_info}<br>IP: {ip_address}</p>
      <p>If this wasn't you, change your password immediately.</p>
      <a href="{FRONTEND_URL}/app/account/security"
         style="display:inline-block;background:#FF6A00;color:#0B0C0F;padding:12px 24px;
                border-radius:4px;text-decoration:none;font-weight:600;">
        Secure My Account
      </a>
    </div>
    """
    return _send(to, "New login to your account — LAP", html)


def send_2fa_enabled_email(to: str) -> bool:
    """Notify user that 2FA has been enabled."""
    html = f"""
    <div style="background:#0B0C0F;color:#F3F0E8;padding:32px;font-family:Inter,sans-serif;">
      <h2 style="color:#B6FF2E;font-family:Teko,sans-serif;">Two-Factor Authentication Enabled</h2>
      <p>2FA has been enabled on your LAP account. Make sure to store your backup codes safely.</p>
    </div>
    """
    return _send(to, "2FA enabled on your account — LAP", html)


def send_2fa_disabled_email(to: str) -> bool:
    """Notify user that 2FA has been disabled."""
    html = f"""
    <div style="background:#0B0C0F;color:#F3F0E8;padding:32px;font-family:Inter,sans-serif;">
      <h2 style="color:#FF2A2A;font-family:Teko,sans-serif;">Two-Factor Authentication Disabled</h2>
      <p>2FA has been disabled on your LAP account. We recommend re-enabling it for security.</p>
      <a href="{FRONTEND_URL}/app/account/security"
         style="display:inline-block;background:#FF6A00;color:#0B0C0F;padding:12px 24px;
                border-radius:4px;text-decoration:none;font-weight:600;">
        Re-enable 2FA
      </a>
    </div>
    """
    return _send(to, "2FA disabled on your account — LAP", html)


def send_retention_warning_email(to: str, session_name: str, expiry_date: str) -> bool:
    """Warn user that raw data will be deleted soon."""
    html = f"""
    <div style="background:#0B0C0F;color:#F3F0E8;padding:32px;font-family:Inter,sans-serif;">
      <h2 style="color:#FFD400;font-family:Teko,sans-serif;">Data Retention Notice</h2>
      <p>Raw telemetry data for <strong>{session_name}</strong> will be deleted on
         <strong>{expiry_date}</strong> per your plan's retention policy.</p>
      <p>Processed reports are kept indefinitely. To keep raw data longer, upgrade your plan.</p>
      <a href="{FRONTEND_URL}/app/account/data"
         style="display:inline-block;background:#FF6A00;color:#0B0C0F;padding:12px 24px;
                border-radius:4px;text-decoration:none;font-weight:600;">
        Export My Data
      </a>
    </div>
    """
    return _send(to, f"Data retention notice: {session_name} — LAP", html)
```

**Step 6: Implement forgot-password and reset-password in `auth.py`**

Add to `telemetry_tool/web/routes/auth.py` (append before the `api_v1_bp` section):

```python
@bp.route("/forgot-password", methods=["POST"])
@rate_limit(tier="auth")
@validate_body(ForgotPasswordSchema)
def forgot_password():
    """Send a password reset email."""
    import secrets as _secrets
    body = g.body
    conn = _get_conn()

    cur = conn.execute(
        "SELECT id, email FROM users WHERE email = %(email)s AND deleted_at IS NULL",
        {"email": body.email.strip().lower()},
    )
    user = cur.fetchone()

    # Always return 200 to prevent email enumeration
    if user:
        token = _secrets.token_urlsafe(32)
        expires = datetime.now(timezone.utc) + timedelta(hours=1)
        conn.execute(
            "UPDATE users SET email_verify_token = %(token)s, "
            "email_verify_expires = %(expires)s WHERE id = %(uid)s",
            {"token": token, "expires": expires, "uid": user["id"]},
        )
        conn.commit()
        try:
            from auth.email import send_password_reset_email
            send_password_reset_email(user["email"], token)
        except Exception:
            logger.warning("Password reset email failed", exc_info=True)

    return api_response({"message": "If an account exists with that email, a reset link has been sent."})


@bp.route("/reset-password", methods=["POST"])
@rate_limit(tier="auth")
@validate_body(ResetPasswordSchema)
def reset_password():
    """Complete password reset with token."""
    from auth.service import hash_password
    body = g.body
    conn = _get_conn()

    cur = conn.execute(
        "SELECT id FROM users WHERE email_verify_token = %(token)s "
        "AND email_verify_expires > NOW() AND deleted_at IS NULL",
        {"token": body.token},
    )
    user = cur.fetchone()
    if not user:
        return api_error("INVALID_TOKEN", "Invalid or expired reset token", status=400)

    new_hash = hash_password(body.new_password)
    conn.execute(
        "UPDATE users SET password_hash = %(hash)s, "
        "email_verify_token = NULL, email_verify_expires = NULL "
        "WHERE id = %(uid)s",
        {"hash": new_hash, "uid": user["id"]},
    )
    # Revoke all sessions
    conn.execute(
        "UPDATE refresh_tokens SET revoked_at = NOW() "
        "WHERE user_id = %(uid)s AND revoked_at IS NULL",
        {"uid": user["id"]},
    )
    conn.commit()

    return api_response({"message": "Password reset successfully. Please log in."})
```

Add imports at the top of auth.py:
```python
from web.schemas.security import ForgotPasswordSchema, ResetPasswordSchema
```

**Step 7: Run tests to verify they pass**

Run: `cd telemetry_tool && python -m pytest tests/test_password_management.py -v`
Expected: All tests PASS.

**Step 8: Commit**

```bash
git add telemetry_tool/web/routes/api_v1_account.py telemetry_tool/web/routes/auth.py \
  telemetry_tool/auth/email.py telemetry_tool/web/schemas/security.py \
  telemetry_tool/tests/test_password_management.py
git commit -m "feat(auth): add password change, forgot/reset password, and email templates"
```

---

### Task 5: Add session management endpoints with tests

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_account.py`
- Create: `telemetry_tool/tests/test_session_management.py`

**Step 1: Write failing tests**

```python
# telemetry_tool/tests/test_session_management.py
"""Tests for session (device) management endpoints."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pytest
from flask import Flask, g
from web.routes.api_v1_account import bp as account_bp
from web.api_utils import init_request_id


def _make_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    init_request_id(app)
    app.register_blueprint(account_bp)

    @app.before_request
    def _inject_user():
        g.user_id = 1
        g.workspace_id = 1

    return app


@pytest.fixture
def client():
    return _make_app().test_client()


class TestListSessions:
    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_returns_active_sessions(self, mock_db, client):
        conn = MagicMock()
        mock_db.return_value = conn
        conn.execute.return_value.fetchall.return_value = [
            {"id": 1, "user_agent": "Chrome/120", "ip_address": "1.2.3.4",
             "created_at": "2026-02-20T10:00:00Z", "last_used_at": None},
            {"id": 2, "user_agent": "Firefox/115", "ip_address": "5.6.7.8",
             "created_at": "2026-02-21T10:00:00Z", "last_used_at": None},
        ]
        resp = client.get("/api/v1/account/sessions")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert len(body["data"]) == 2


class TestRevokeSession:
    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_revokes_session_by_id(self, mock_db, client):
        conn = MagicMock()
        mock_db.return_value = conn
        conn.execute.return_value.rowcount = 1
        resp = client.delete("/api/v1/account/sessions/42")
        assert resp.status_code == 200

    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_returns_404_for_unknown_session(self, mock_db, client):
        conn = MagicMock()
        mock_db.return_value = conn
        conn.execute.return_value.rowcount = 0
        resp = client.delete("/api/v1/account/sessions/999")
        assert resp.status_code == 404


class TestRevokeOtherSessions:
    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_revokes_all_except_current(self, mock_db, client):
        conn = MagicMock()
        mock_db.return_value = conn
        conn.execute.return_value.rowcount = 3
        resp = client.post("/api/v1/account/sessions/revoke-others",
                           headers={"Cookie": "lap_refresh_token=test-token"})
        assert resp.status_code == 200
```

**Step 2: Implement session management endpoints**

Add to `telemetry_tool/web/routes/api_v1_account.py`:

```python
@bp.route("/sessions", methods=["GET"])
@rate_limit(tier="read")
def list_sessions():
    """List all active sessions (refresh tokens) for the current user."""
    conn = get_pg_connection()
    cur = conn.execute(
        "SELECT id, user_agent, ip_address, created_at, last_used_at "
        "FROM refresh_tokens "
        "WHERE user_id = %(uid)s AND revoked_at IS NULL AND expires_at > NOW() "
        "ORDER BY created_at DESC",
        {"uid": g.user_id},
    )
    sessions = [dict(row) for row in cur.fetchall()]
    return api_response(sessions)


@bp.route("/sessions/<int:session_id>", methods=["DELETE"])
@rate_limit(tier="write")
def revoke_session(session_id):
    """Revoke a specific session (refresh token)."""
    conn = get_pg_connection()
    cur = conn.execute(
        "UPDATE refresh_tokens SET revoked_at = NOW() "
        "WHERE id = %(sid)s AND user_id = %(uid)s AND revoked_at IS NULL",
        {"sid": session_id, "uid": g.user_id},
    )
    conn.commit()
    if cur.rowcount == 0:
        return api_error("NOT_FOUND", "Session not found", status=404)
    return api_response({"message": "Session revoked"})


@bp.route("/sessions/revoke-others", methods=["POST"])
@rate_limit(tier="write")
def revoke_other_sessions():
    """Revoke all sessions except the current one."""
    from auth.service import hash_refresh_token
    conn = get_pg_connection()

    # Get current refresh token from cookie to exclude it
    current_token = request.cookies.get("lap_refresh_token")
    if current_token:
        current_hash = hash_refresh_token(current_token)
        conn.execute(
            "UPDATE refresh_tokens SET revoked_at = NOW() "
            "WHERE user_id = %(uid)s AND revoked_at IS NULL "
            "AND token_hash != %(hash)s",
            {"uid": g.user_id, "hash": current_hash},
        )
    else:
        conn.execute(
            "UPDATE refresh_tokens SET revoked_at = NOW() "
            "WHERE user_id = %(uid)s AND revoked_at IS NULL",
            {"uid": g.user_id},
        )
    conn.commit()
    return api_response({"message": "All other sessions revoked"})
```

**Step 3: Run tests**

Run: `cd telemetry_tool && python -m pytest tests/test_session_management.py -v`
Expected: All PASS.

**Step 4: Commit**

```bash
git add telemetry_tool/web/routes/api_v1_account.py telemetry_tool/tests/test_session_management.py
git commit -m "feat(auth): add session management endpoints (list, revoke, revoke-others)"
```

---

## Phase 3: TOTP Two-Factor Authentication

### Task 6: Implement TOTP 2FA backend with tests

**Files:**
- Create: `telemetry_tool/auth/totp.py`
- Modify: `telemetry_tool/web/routes/api_v1_account.py` (add 2FA endpoints)
- Modify: `telemetry_tool/web/routes/auth.py` (add 2FA login step)
- Create: `telemetry_tool/tests/test_totp.py`

**Dependencies:** Install `pyotp` and `qrcode` packages.

Run: `pip install pyotp qrcode[pil]`

**Step 1: Write the TOTP service**

```python
# telemetry_tool/auth/totp.py
"""TOTP two-factor authentication service."""
from __future__ import annotations

import base64
import io
import secrets

import pyotp
from auth.service import hash_password, verify_password, PasswordHasher


_ISSUER = "LAP Coach"
_BACKUP_CODE_COUNT = 10


def generate_totp_secret() -> str:
    """Generate a new TOTP secret."""
    return pyotp.random_base32(length=32)


def get_provisioning_uri(secret: str, email: str) -> str:
    """Return the otpauth:// URI for QR code generation."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=email, issuer_name=_ISSUER)


def generate_qr_data_uri(provisioning_uri: str) -> str:
    """Generate a QR code as a base64 data URI."""
    import qrcode
    img = qrcode.make(provisioning_uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}"


def verify_totp_code(secret: str, code: str) -> bool:
    """Verify a 6-digit TOTP code (allows 1 window of drift)."""
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


def generate_backup_codes() -> list[str]:
    """Generate human-readable backup codes."""
    codes = []
    for _ in range(_BACKUP_CODE_COUNT):
        raw = secrets.token_hex(4)  # 8 hex chars
        code = f"{raw[:4]}-{raw[4:]}"
        codes.append(code)
    return codes


def hash_backup_codes(codes: list[str]) -> list[str]:
    """Hash backup codes for storage. Uses SHA-256 (fast but sufficient for 8-char codes)."""
    import hashlib
    return [hashlib.sha256(c.encode()).hexdigest() for c in codes]


def verify_backup_code(code: str, hashed_codes: list[str]) -> int | None:
    """Check if code matches any hashed backup code. Returns index or None."""
    import hashlib
    code_hash = hashlib.sha256(code.encode()).hexdigest()
    for i, h in enumerate(hashed_codes):
        if h == code_hash:
            return i
    return None
```

**Step 2: Write failing tests**

```python
# telemetry_tool/tests/test_totp.py
"""Tests for TOTP two-factor authentication."""
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pytest
from auth.totp import (
    generate_totp_secret,
    get_provisioning_uri,
    verify_totp_code,
    generate_backup_codes,
    hash_backup_codes,
    verify_backup_code,
)


class TestTotpSecret:
    def test_generates_base32_string(self):
        secret = generate_totp_secret()
        assert len(secret) == 32
        assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567=" for c in secret)

    def test_generates_unique_secrets(self):
        s1 = generate_totp_secret()
        s2 = generate_totp_secret()
        assert s1 != s2


class TestProvisioningUri:
    def test_contains_issuer(self):
        uri = get_provisioning_uri("JBSWY3DPEHPK3PXP", "user@example.com")
        assert "LAP" in uri
        assert "otpauth://totp/" in uri

    def test_contains_email(self):
        uri = get_provisioning_uri("JBSWY3DPEHPK3PXP", "user@example.com")
        assert "user%40example.com" in uri or "user@example.com" in uri


class TestTotpVerification:
    def test_valid_code_accepted(self):
        import pyotp
        secret = generate_totp_secret()
        totp = pyotp.TOTP(secret)
        code = totp.now()
        assert verify_totp_code(secret, code) is True

    def test_invalid_code_rejected(self):
        secret = generate_totp_secret()
        assert verify_totp_code(secret, "000000") is False


class TestBackupCodes:
    def test_generates_ten_codes(self):
        codes = generate_backup_codes()
        assert len(codes) == 10

    def test_codes_are_formatted(self):
        codes = generate_backup_codes()
        for code in codes:
            assert "-" in code
            assert len(code) == 9  # xxxx-xxxx

    def test_hash_and_verify_roundtrip(self):
        codes = generate_backup_codes()
        hashed = hash_backup_codes(codes)
        assert len(hashed) == 10
        idx = verify_backup_code(codes[3], hashed)
        assert idx == 3

    def test_invalid_code_returns_none(self):
        codes = generate_backup_codes()
        hashed = hash_backup_codes(codes)
        assert verify_backup_code("xxxx-yyyy", hashed) is None
```

**Step 3: Run tests**

Run: `cd telemetry_tool && python -m pytest tests/test_totp.py -v`
Expected: All PASS (since we wrote the module first this time — the service is pure logic).

**Step 4: Add 2FA endpoints to api_v1_account.py**

```python
# Add to telemetry_tool/web/routes/api_v1_account.py

@bp.route("/2fa/setup", methods=["POST"])
@rate_limit(tier="write")
def setup_2fa():
    """Generate TOTP secret and QR code for 2FA setup."""
    from auth.totp import generate_totp_secret, get_provisioning_uri, generate_qr_data_uri, generate_backup_codes, hash_backup_codes

    conn = get_pg_connection()

    # Check if already enabled
    cur = conn.execute("SELECT totp_enabled, email FROM users WHERE id = %(uid)s", {"uid": g.user_id})
    user = cur.fetchone()
    if user and user["totp_enabled"]:
        return api_error("ALREADY_ENABLED", "2FA is already enabled", status=409)

    secret = generate_totp_secret()
    uri = get_provisioning_uri(secret, user["email"])
    qr = generate_qr_data_uri(uri)
    backup_codes = generate_backup_codes()
    hashed_codes = hash_backup_codes(backup_codes)

    # Store secret and hashed backup codes (not yet verified)
    conn.execute(
        "UPDATE users SET totp_secret = %(secret)s, totp_backup_codes = %(codes)s "
        "WHERE id = %(uid)s",
        {"secret": secret, "codes": hashed_codes, "uid": g.user_id},
    )
    conn.commit()

    return api_response({
        "secret": secret,
        "provisioning_uri": uri,
        "qr_code": qr,
        "backup_codes": backup_codes,  # Show only once
    })


@bp.route("/2fa/verify", methods=["POST"])
@rate_limit(tier="auth")
@validate_body(TotpSetupVerifySchema)
def verify_2fa_setup():
    """Verify a TOTP code to complete 2FA setup."""
    from auth.totp import verify_totp_code

    body = g.body
    conn = get_pg_connection()

    cur = conn.execute(
        "SELECT totp_secret, totp_enabled FROM users WHERE id = %(uid)s",
        {"uid": g.user_id},
    )
    user = cur.fetchone()
    if not user or not user["totp_secret"]:
        return api_error("NOT_SETUP", "Call /2fa/setup first", status=400)
    if user["totp_enabled"]:
        return api_error("ALREADY_ENABLED", "2FA is already enabled", status=409)

    if not verify_totp_code(user["totp_secret"], body.code):
        return api_error("INVALID_CODE", "Invalid verification code", status=400)

    conn.execute(
        "UPDATE users SET totp_enabled = true, totp_verified_at = NOW() WHERE id = %(uid)s",
        {"uid": g.user_id},
    )
    conn.commit()

    try:
        cur = conn.execute("SELECT email FROM users WHERE id = %(uid)s", {"uid": g.user_id})
        row = cur.fetchone()
        if row:
            from auth.email import send_2fa_enabled_email
            send_2fa_enabled_email(row["email"])
    except Exception:
        logger.warning("2FA enabled email failed", exc_info=True)

    return api_response({"message": "2FA enabled successfully"})


@bp.route("/2fa", methods=["DELETE"])
@rate_limit(tier="auth")
@validate_body(TotpDisableSchema)
def disable_2fa():
    """Disable 2FA. Requires password + valid TOTP code."""
    from auth.service import verify_password
    from auth.totp import verify_totp_code

    body = g.body
    conn = get_pg_connection()

    cur = conn.execute(
        "SELECT password_hash, totp_secret, totp_enabled FROM users WHERE id = %(uid)s",
        {"uid": g.user_id},
    )
    user = cur.fetchone()
    if not user or not user["totp_enabled"]:
        return api_error("NOT_ENABLED", "2FA is not enabled", status=400)

    if not verify_password(body.password, user["password_hash"]):
        return api_error("INVALID_CREDENTIALS", "Incorrect password", status=403)

    if not verify_totp_code(user["totp_secret"], body.code):
        return api_error("INVALID_CODE", "Invalid TOTP code", status=400)

    conn.execute(
        "UPDATE users SET totp_secret = NULL, totp_enabled = false, "
        "totp_backup_codes = NULL, totp_verified_at = NULL WHERE id = %(uid)s",
        {"uid": g.user_id},
    )
    conn.commit()

    try:
        cur = conn.execute("SELECT email FROM users WHERE id = %(uid)s", {"uid": g.user_id})
        row = cur.fetchone()
        if row:
            from auth.email import send_2fa_disabled_email
            send_2fa_disabled_email(row["email"])
    except Exception:
        logger.warning("2FA disabled email failed", exc_info=True)

    return api_response({"message": "2FA disabled"})


@bp.route("/2fa/backup-codes/regenerate", methods=["POST"])
@rate_limit(tier="auth")
@validate_body(TotpDisableSchema)  # reuse: requires password + code
def regenerate_backup_codes():
    """Generate new backup codes. Requires password + TOTP code."""
    from auth.service import verify_password
    from auth.totp import verify_totp_code, generate_backup_codes, hash_backup_codes

    body = g.body
    conn = get_pg_connection()

    cur = conn.execute(
        "SELECT password_hash, totp_secret, totp_enabled FROM users WHERE id = %(uid)s",
        {"uid": g.user_id},
    )
    user = cur.fetchone()
    if not user or not user["totp_enabled"]:
        return api_error("NOT_ENABLED", "2FA is not enabled", status=400)

    if not verify_password(body.password, user["password_hash"]):
        return api_error("INVALID_CREDENTIALS", "Incorrect password", status=403)

    if not verify_totp_code(user["totp_secret"], body.code):
        return api_error("INVALID_CODE", "Invalid TOTP code", status=400)

    new_codes = generate_backup_codes()
    hashed = hash_backup_codes(new_codes)
    conn.execute(
        "UPDATE users SET totp_backup_codes = %(codes)s WHERE id = %(uid)s",
        {"codes": hashed, "uid": g.user_id},
    )
    conn.commit()

    return api_response({"backup_codes": new_codes})
```

Add schema imports at the top of `api_v1_account.py`:
```python
from web.schemas.security import TotpSetupVerifySchema, TotpDisableSchema
```

**Step 5: Add 2FA login step to auth.py**

Add to `telemetry_tool/web/routes/auth.py` before the `api_v1_bp` section:

```python
@bp.route("/login/2fa", methods=["POST"])
@rate_limit(tier="auth")
@validate_body(TotpLoginSchema)
def login_2fa():
    """Complete login for accounts with 2FA enabled."""
    from auth.totp import verify_totp_code, verify_backup_code
    from auth.service import create_access_token, create_refresh_token, hash_refresh_token

    body = g.body
    conn = _get_conn()
    secret = current_app.config["JWT_SECRET"]

    # Decode temp token (short-lived JWT with type="2fa_pending")
    try:
        payload = jwt.decode(body.temp_token, secret, algorithms=["HS256"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return api_error("INVALID_TOKEN", "Invalid or expired temporary token", status=401)

    if payload.get("type") != "2fa_pending":
        return api_error("INVALID_TOKEN", "Not a 2FA pending token", status=401)

    user_id = payload["user_id"]
    cur = conn.execute(
        "SELECT totp_secret, totp_backup_codes FROM users WHERE id = %(uid)s",
        {"uid": user_id},
    )
    user = cur.fetchone()
    if not user or not user["totp_secret"]:
        return api_error("NOT_ENABLED", "2FA is not enabled for this account", status=400)

    # Try TOTP code first, then backup code
    code = body.code
    if len(code) == 6 and code.isdigit():
        if not verify_totp_code(user["totp_secret"], code):
            return api_error("INVALID_CODE", "Invalid authentication code", status=401)
    else:
        # Try as backup code
        idx = verify_backup_code(code, user["totp_backup_codes"] or [])
        if idx is None:
            return api_error("INVALID_CODE", "Invalid authentication code", status=401)
        # Consume the backup code
        remaining = list(user["totp_backup_codes"])
        remaining[idx] = "USED"
        conn.execute(
            "UPDATE users SET totp_backup_codes = %(codes)s WHERE id = %(uid)s",
            {"codes": remaining, "uid": user_id},
        )

    # Issue real tokens
    access_token = create_access_token(user_id, secret)
    refresh_token = create_refresh_token()
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=current_app.config.get("JWT_REFRESH_EXPIRY_DAYS", 30)
    )
    conn.execute(
        "INSERT INTO refresh_tokens (user_id, token_hash, expires_at, user_agent, ip_address) "
        "VALUES (%(uid)s, %(hash)s, %(exp)s, %(ua)s, %(ip)s)",
        {
            "uid": user_id,
            "hash": hash_refresh_token(refresh_token),
            "exp": expires_at,
            "ua": request.headers.get("User-Agent", "")[:500],
            "ip": request.remote_addr,
        },
    )
    conn.commit()

    # Get user info
    cur = conn.execute(
        "SELECT id, email, display_name FROM users WHERE id = %(uid)s",
        {"uid": user_id},
    )
    user_info = dict(cur.fetchone())

    result = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": user_info,
    }
    resp = make_response(api_response(result))
    _set_refresh_cookie(resp, refresh_token)
    return resp
```

Also modify the existing `login()` endpoint to check for 2FA. In the login function, after password verification succeeds, add this check before issuing tokens:

```python
# After successful password verification, check if 2FA is enabled
cur = conn.execute(
    "SELECT totp_enabled FROM users WHERE id = %(uid)s",
    {"uid": user["id"]},
)
totp_row = cur.fetchone()
if totp_row and totp_row["totp_enabled"]:
    # Issue a short-lived temp token instead of full access
    temp_payload = {
        "user_id": user["id"],
        "type": "2fa_pending",
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    temp_token = jwt.encode(temp_payload, secret, algorithm="HS256")
    return api_response({
        "requires_2fa": True,
        "temp_token": temp_token,
    })
```

Add import at top of auth.py:
```python
from web.schemas.security import TotpLoginSchema
```

**Step 6: Run all tests**

Run: `cd telemetry_tool && python -m pytest tests/test_totp.py tests/test_password_management.py tests/test_session_management.py -v`
Expected: All PASS.

**Step 7: Commit**

```bash
git add telemetry_tool/auth/totp.py telemetry_tool/web/routes/api_v1_account.py \
  telemetry_tool/web/routes/auth.py telemetry_tool/tests/test_totp.py
git commit -m "feat(auth): add full TOTP 2FA with backup codes and 2FA login flow"
```

---

## Phase 4: Billing, Stripe Portal & OAuth Management

### Task 7: Add billing status and Stripe Portal endpoints with tests

**Files:**
- Modify: `telemetry_tool/web/routes/billing.py`
- Create: `telemetry_tool/tests/test_billing_portal.py`

**Step 1: Write failing tests**

```python
# telemetry_tool/tests/test_billing_portal.py
"""Tests for billing status and Stripe Portal endpoints."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pytest
from flask import Flask, g
from web.routes.billing import bp as billing_bp
from web.api_utils import init_request_id


def _make_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["STRIPE_SECRET_KEY"] = "sk_test_fake"
    init_request_id(app)
    app.register_blueprint(billing_bp)

    @app.before_request
    def _inject_user():
        g.user_id = 1
        g.workspace_id = 1

    return app


@pytest.fixture
def client():
    return _make_app().test_client()


class TestBillingStatus:
    @patch("web.routes.billing._get_conn")
    def test_returns_free_plan_for_no_subscription(self, mock_db, client):
        conn = MagicMock()
        mock_db.return_value = conn
        conn.execute.return_value.fetchone.return_value = {
            "plan_tier": "free",
            "subscription_status": None,
            "stripe_customer_id": None,
            "stripe_subscription_id": None,
        }
        resp = client.get("/api/v1/billing/status")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["plan"] == "free"


class TestCreatePortalSession:
    @patch("web.routes.billing._get_conn")
    def test_returns_400_without_stripe_customer(self, mock_db, client):
        conn = MagicMock()
        mock_db.return_value = conn
        conn.execute.return_value.fetchone.return_value = {
            "stripe_customer_id": None,
        }
        resp = client.post("/api/v1/billing/portal", json={
            "return_url": "https://lap-coach.racing/app/account/billing"
        })
        assert resp.status_code == 400
```

**Step 2: Implement billing status and portal endpoints**

Add to `telemetry_tool/web/routes/billing.py` (after the webhook handler):

```python
@bp.route("/status", methods=["GET"])
@rate_limit(tier="read")
def billing_status():
    """Return the current user's billing status."""
    conn = _get_conn()
    cur = conn.execute(
        "SELECT plan_tier, subscription_status, stripe_customer_id, stripe_subscription_id "
        "FROM users WHERE id = %(uid)s",
        {"uid": g.user_id},
    )
    user = cur.fetchone()
    if not user:
        return api_error("NOT_FOUND", "User not found", status=404)

    data = {
        "plan": user["plan_tier"] or "free",
        "status": user["subscription_status"] or "none",
        "has_payment_method": user["stripe_customer_id"] is not None,
    }

    # If there's a Stripe subscription, fetch live details
    if user["stripe_subscription_id"] and STRIPE_SECRET_KEY:
        try:
            import stripe
            stripe.api_key = STRIPE_SECRET_KEY
            sub = stripe.Subscription.retrieve(user["stripe_subscription_id"])
            data.update({
                "billing_cycle": sub.get("items", {}).get("data", [{}])[0].get("price", {}).get("recurring", {}).get("interval", "month"),
                "current_period_end": sub.get("current_period_end"),
                "cancel_at_period_end": sub.get("cancel_at_period_end", False),
            })
            # Payment method info
            if sub.get("default_payment_method"):
                pm = stripe.PaymentMethod.retrieve(sub["default_payment_method"])
                if pm.get("card"):
                    data["payment_method_last4"] = pm["card"]["last4"]
                    data["payment_method_brand"] = pm["card"]["brand"]
        except Exception:
            logger.warning("Failed to fetch Stripe subscription details", exc_info=True)

    return api_response(data)


@bp.route("/portal", methods=["POST"])
@rate_limit(tier="write")
def create_portal_session():
    """Create a Stripe Customer Portal session."""
    if not STRIPE_SECRET_KEY:
        return api_error("NOT_CONFIGURED", "Billing not configured", status=503)

    body = request.get_json(silent=True) or {}
    return_url = body.get("return_url", "https://www.lap-coach.racing/app/account/billing")

    conn = _get_conn()
    cur = conn.execute(
        "SELECT stripe_customer_id FROM users WHERE id = %(uid)s",
        {"uid": g.user_id},
    )
    user = cur.fetchone()
    if not user or not user["stripe_customer_id"]:
        return api_error("NO_CUSTOMER", "No billing account found. Subscribe to a plan first.", status=400)

    try:
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
        session = stripe.billing_portal.Session.create(
            customer=user["stripe_customer_id"],
            return_url=return_url,
        )
        return api_response({"url": session.url})
    except Exception as e:
        logger.error("Stripe portal session failed: %s", e, exc_info=True)
        return api_error("STRIPE_ERROR", "Failed to create billing portal session", status=502)


@bp.route("/email", methods=["PATCH"])
@rate_limit(tier="write")
def update_billing_email():
    """Update the billing email on Stripe."""
    if not STRIPE_SECRET_KEY:
        return api_error("NOT_CONFIGURED", "Billing not configured", status=503)

    body = request.get_json(silent=True) or {}
    email = body.get("email")
    if not email:
        return api_error("VALIDATION_ERROR", "email is required", status=422)

    conn = _get_conn()
    cur = conn.execute(
        "SELECT stripe_customer_id FROM users WHERE id = %(uid)s",
        {"uid": g.user_id},
    )
    user = cur.fetchone()
    if not user or not user["stripe_customer_id"]:
        return api_error("NO_CUSTOMER", "No billing account found", status=400)

    try:
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
        stripe.Customer.modify(user["stripe_customer_id"], email=email)
        return api_response({"message": "Billing email updated"})
    except Exception as e:
        logger.error("Stripe email update failed: %s", e, exc_info=True)
        return api_error("STRIPE_ERROR", "Failed to update billing email", status=502)
```

**Step 3: Run tests**

Run: `cd telemetry_tool && python -m pytest tests/test_billing_portal.py -v`
Expected: All PASS.

**Step 4: Commit**

```bash
git add telemetry_tool/web/routes/billing.py telemetry_tool/tests/test_billing_portal.py
git commit -m "feat(billing): add billing status, Stripe Portal session, and billing email endpoints"
```

---

### Task 8: Add entitlements, usage, retention, OAuth, and support endpoints

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_account.py`
- Create: `telemetry_tool/tests/test_account_endpoints.py`

**Step 1: Add remaining endpoints to api_v1_account.py**

```python
# Add to api_v1_account.py

@bp.route("/entitlements", methods=["GET"])
@rate_limit(tier="read")
def get_entitlements():
    """Return the current plan's entitlements."""
    from auth.entitlements import get_plan_entitlements
    conn = get_pg_connection()
    cur = conn.execute(
        "SELECT plan_tier FROM users WHERE id = %(uid)s",
        {"uid": g.user_id},
    )
    user = cur.fetchone()
    plan = user["plan_tier"] if user else "free"
    ent = get_plan_entitlements(plan)
    return api_response({"plan": plan, "entitlements": ent})


@bp.route("/usage", methods=["GET"])
@rate_limit(tier="read")
def get_usage():
    """Return monthly usage snapshot."""
    from auth.usage import get_usage_snapshot
    conn = get_pg_connection()
    cur = conn.execute(
        "SELECT plan_tier FROM users WHERE id = %(uid)s",
        {"uid": g.user_id},
    )
    user = cur.fetchone()
    plan = user["plan_tier"] if user else "free"
    snapshot = get_usage_snapshot(conn, g.workspace_id, plan)
    return api_response(snapshot)


@bp.route("/retention", methods=["GET"])
@rate_limit(tier="read")
def get_retention():
    """Return data retention info per session."""
    from auth.entitlements import get_plan_entitlements
    from datetime import timedelta
    conn = get_pg_connection()

    cur = conn.execute(
        "SELECT plan_tier FROM users WHERE id = %(uid)s",
        {"uid": g.user_id},
    )
    user = cur.fetchone()
    plan = user["plan_tier"] if user else "free"
    ent = get_plan_entitlements(plan)
    retention_days = ent["raw_retention_days"]

    cur = conn.execute(
        "SELECT id, name, created_at FROM sessions "
        "WHERE workspace_id = %(ws)s ORDER BY created_at DESC LIMIT 100",
        {"ws": g.workspace_id},
    )
    sessions = []
    for row in cur.fetchall():
        row_dict = dict(row)
        created = row_dict["created_at"]
        if hasattr(created, "isoformat"):
            expires = created + timedelta(days=retention_days)
            row_dict["expires_at"] = expires.isoformat()
        sessions.append(row_dict)

    return api_response({
        "plan": plan,
        "raw_retention_days": retention_days,
        "report_retention": "indefinite",
        "sessions": sessions,
    })


@bp.route("/oauth-connections", methods=["GET"])
@rate_limit(tier="read")
def list_oauth_connections():
    """List linked OAuth providers."""
    conn = get_pg_connection()
    cur = conn.execute(
        "SELECT provider, provider_user_id, created_at "
        "FROM oauth_connections WHERE user_id = %(uid)s",
        {"uid": g.user_id},
    )
    connections = [dict(row) for row in cur.fetchall()]
    return api_response(connections)


@bp.route("/oauth-connections/<provider>", methods=["DELETE"])
@rate_limit(tier="write")
def unlink_oauth(provider):
    """Unlink an OAuth provider. Blocked if it's the last auth method."""
    conn = get_pg_connection()

    # Check if user has a password (another auth method)
    cur = conn.execute(
        "SELECT password_hash FROM users WHERE id = %(uid)s",
        {"uid": g.user_id},
    )
    user = cur.fetchone()

    # Count remaining OAuth connections
    cur = conn.execute(
        "SELECT COUNT(*) as cnt FROM oauth_connections WHERE user_id = %(uid)s",
        {"uid": g.user_id},
    )
    oauth_count = cur.fetchone()["cnt"]

    has_password = user and user["password_hash"] is not None
    if not has_password and oauth_count <= 1:
        return api_error(
            "LAST_AUTH_METHOD",
            "Cannot unlink the last authentication method. Set a password first.",
            status=400,
        )

    cur = conn.execute(
        "DELETE FROM oauth_connections WHERE user_id = %(uid)s AND provider = %(p)s",
        {"uid": g.user_id, "p": provider},
    )
    conn.commit()
    if cur.rowcount == 0:
        return api_error("NOT_FOUND", f"No {provider} connection found", status=404)

    return api_response({"message": f"{provider} unlinked"})
```

**Step 2: Add support ticket endpoint**

Create a new blueprint file for support or add to api_v1_account.py:

```python
# Add to api_v1_account.py

@bp.route("/support/ticket", methods=["POST"])
@rate_limit(tier="write")
def create_support_ticket():
    """Submit a support ticket via email."""
    body = request.get_json(silent=True)
    if not body:
        return api_error("VALIDATION_ERROR", "Request body required", status=422)

    issue_type = body.get("issue_type", "other")
    description = body.get("description", "")
    session_id = body.get("session_id")

    if not description or len(description) < 10:
        return api_error("VALIDATION_ERROR", "Description must be at least 10 characters", status=422)

    conn = get_pg_connection()
    cur = conn.execute(
        "SELECT email, plan_tier FROM users WHERE id = %(uid)s",
        {"uid": g.user_id},
    )
    user = cur.fetchone()

    # Store ticket in DB
    conn.execute(
        "INSERT INTO support_tickets (user_id, workspace_id, issue_type, session_id, description, diagnostics) "
        "VALUES (%(uid)s, %(ws)s, %(type)s, %(sid)s, %(desc)s, %(diag)s)",
        {
            "uid": g.user_id,
            "ws": g.workspace_id,
            "type": issue_type,
            "sid": session_id,
            "desc": description,
            "diag": json.dumps({
                "user_agent": request.headers.get("User-Agent", ""),
                "plan": user["plan_tier"] if user else "free",
            }),
        },
    )
    conn.commit()

    # Send email to support
    try:
        from auth.email import _send
        html = f"""
        <div style="font-family:Inter,sans-serif;padding:16px;">
          <h3>Support Ticket — {issue_type}</h3>
          <p><strong>User:</strong> {user['email'] if user else 'unknown'} (ID: {g.user_id})</p>
          <p><strong>Plan:</strong> {user['plan_tier'] if user else 'free'}</p>
          <p><strong>Session ID:</strong> {session_id or 'N/A'}</p>
          <hr>
          <p>{description}</p>
        </div>
        """
        _send("support@lap-coach.racing", f"[Support] {issue_type} — User {g.user_id}", html)
    except Exception:
        logger.warning("Support email failed", exc_info=True)

    return api_response({"message": "Support ticket submitted"}, status=201)
```

**Step 3: Write tests and run**

Write corresponding tests following the same mock pattern from Task 5. Test all new endpoints.

Run: `cd telemetry_tool && python -m pytest tests/test_account_endpoints.py -v`

**Step 4: Commit**

```bash
git add telemetry_tool/web/routes/api_v1_account.py telemetry_tool/tests/test_account_endpoints.py
git commit -m "feat(account): add entitlements, usage, retention, OAuth, and support endpoints"
```

---

### Task 9: Add profile preferences update (JSONB)

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_account.py` (enhance profile PATCH)
- Modify: `telemetry_tool/web/schemas/account.py` (add preferences schema)

**Step 1: Update ProfileUpdateSchema**

In `telemetry_tool/web/schemas/account.py`:

```python
from pydantic import BaseModel, Field
from typing import Literal


class NotificationPreferences(BaseModel):
    report_ready: bool = True
    billing_alerts: bool = True
    product_updates: bool = False
    weekly_digest: bool = True


class UserPreferences(BaseModel):
    language: str | None = Field(default=None, max_length=5)
    timezone: str | None = Field(default=None, max_length=50)
    units: Literal["metric", "imperial"] | None = None
    notifications: NotificationPreferences | None = None


class ProfileUpdateSchema(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    avatar_url: str | None = Field(default=None, max_length=2048)
    preferences: UserPreferences | None = None


class ExportRequestSchema(BaseModel):
    format: Literal["zip", "json"] = "zip"
```

**Step 2: Update the existing profile PATCH endpoint**

In the existing `update_profile()` function in `api_v1_account.py`, add handling for `avatar_url` and `preferences`:

```python
# Inside the existing update_profile() function, after display_name and email handling:

if body.avatar_url is not None:
    conn.execute(
        "UPDATE users SET avatar_url = %(url)s WHERE id = %(uid)s",
        {"url": body.avatar_url, "uid": g.user_id},
    )

if body.preferences is not None:
    prefs_json = body.preferences.model_dump(exclude_none=True)
    # Merge with existing preferences
    cur = conn.execute(
        "SELECT preferences FROM users WHERE id = %(uid)s",
        {"uid": g.user_id},
    )
    row = cur.fetchone()
    existing = row["preferences"] if row and row["preferences"] else {}
    if isinstance(existing, str):
        import json as _json
        existing = _json.loads(existing)
    existing.update(prefs_json)
    conn.execute(
        "UPDATE users SET preferences = %(prefs)s WHERE id = %(uid)s",
        {"prefs": json.dumps(existing), "uid": g.user_id},
    )
```

**Step 3: Commit**

```bash
git add telemetry_tool/web/routes/api_v1_account.py telemetry_tool/web/schemas/account.py
git commit -m "feat(account): add preferences (language, timezone, units, notifications) to profile update"
```

---

### Task 10: Add data retention enforcement Celery task

**Files:**
- Create: `telemetry_tool/tasks/retention_tasks.py`
- Create: `telemetry_tool/tests/test_retention_tasks.py`

**Step 1: Write the retention enforcement task**

```python
# telemetry_tool/tasks/retention_tasks.py
"""Data retention enforcement — daily Celery task."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger(__name__)

_USE_CELERY = os.environ.get("USE_CELERY", "0") == "1"
_celery_app = None

try:
    from celery_app import celery as _celery_app
except ImportError:
    pass


def _enforce_retention_impl() -> dict[str, Any]:
    """Delete raw telemetry data past retention window per plan."""
    from web.db_pg import get_pg_connection
    from auth.entitlements import get_plan_entitlements

    conn = get_pg_connection()
    now = datetime.now(timezone.utc)
    stats = {"checked": 0, "deleted": 0, "warned": 0}

    # Get all workspaces with their plan
    cur = conn.execute(
        "SELECT w.id as workspace_id, u.plan_tier, u.email "
        "FROM workspaces w "
        "JOIN users u ON w.owner_user_id = u.id "
        "WHERE w.type = 'personal' AND u.deleted_at IS NULL"
    )
    workspaces = [dict(row) for row in cur.fetchall()]

    for ws in workspaces:
        ent = get_plan_entitlements(ws["plan_tier"] or "free")
        retention_days = ent["raw_retention_days"]
        cutoff = now - timedelta(days=retention_days)
        warn_cutoff = now - timedelta(days=retention_days - 7)

        # Find sessions to delete
        cur = conn.execute(
            "SELECT id, name FROM sessions "
            "WHERE workspace_id = %(ws)s AND created_at < %(cutoff)s",
            {"ws": ws["workspace_id"], "cutoff": cutoff},
        )
        expired = [dict(row) for row in cur.fetchall()]
        stats["checked"] += 1

        for session in expired:
            # Delete raw telemetry (keep session metadata and reports)
            conn.execute(
                "DELETE FROM gps_traces WHERE session_id = %(sid)s",
                {"sid": session["id"]},
            )
            stats["deleted"] += 1

        # Find sessions to warn about
        cur = conn.execute(
            "SELECT id, name, created_at FROM sessions "
            "WHERE workspace_id = %(ws)s "
            "AND created_at >= %(cutoff)s AND created_at < %(warn)s",
            {"ws": ws["workspace_id"], "cutoff": cutoff, "warn": warn_cutoff},
        )
        expiring_soon = [dict(row) for row in cur.fetchall()]

        for session in expiring_soon:
            try:
                from auth.email import send_retention_warning_email
                expiry = session["created_at"] + timedelta(days=retention_days)
                send_retention_warning_email(
                    ws["email"],
                    session["name"] or f"Session #{session['id']}",
                    expiry.strftime("%Y-%m-%d"),
                )
                stats["warned"] += 1
            except Exception:
                logger.warning("Retention warning email failed", exc_info=True)

    conn.commit()
    logger.info("Retention enforcement: %s", stats)
    return stats


# Register as Celery task if available
if _USE_CELERY and _celery_app is not None:
    @_celery_app.task(name="tasks.retention_tasks.enforce_data_retention")
    def enforce_data_retention() -> dict[str, Any]:
        return _enforce_retention_impl()
else:
    def enforce_data_retention() -> dict[str, Any]:
        return _enforce_retention_impl()
```

**Step 2: Write tests**

Follow the pattern from `test_gdpr_tasks.py` — mock connections, verify cascade logic.

**Step 3: Commit**

```bash
git add telemetry_tool/tasks/retention_tasks.py telemetry_tool/tests/test_retention_tasks.py
git commit -m "feat(tasks): add data retention enforcement Celery task"
```

---

### Task 11: Register new blueprints and update auth middleware allowlist

**Files:**
- Modify: `telemetry_tool/web/app.py` (ensure new routes are registered)
- Modify: `telemetry_tool/web/middleware/auth.py` (add forgot-password and reset-password to allowlist)

**Step 1: Update auth middleware allowlist**

In `telemetry_tool/web/middleware/auth.py`, add to `_AUTH_PUBLIC_PATHS`:

```python
_AUTH_PUBLIC_PATHS = {
    "/auth/register", "/auth/login", "/auth/logout",
    "/auth/refresh", "/auth/verify-email",
    "/auth/forgot-password", "/auth/reset-password",  # NEW
    "/auth/login/2fa",  # NEW — 2FA step (uses temp_token, not JWT)
    "/api/v1/billing/webhook",
}
```

**Step 2: Verify app.py already registers api_v1_account blueprint**

The `api_v1_account_bp` is already registered in `app.py` (line ~284). No changes needed unless new blueprints were created.

**Step 3: Commit**

```bash
git add telemetry_tool/web/middleware/auth.py
git commit -m "fix(auth): add password reset and 2FA login to public path allowlist"
```

---

## Phase 5: Frontend — Account Layout & Navigation

### Task 12: Create account layout with sidebar sub-navigation

**Files:**
- Create: `lap-website/src/app/app/account/layout.tsx`
- Create: `lap-website/src/app/app/account/page.tsx` (redirect to profile)

**Step 1: Create the account layout**

```tsx
// lap-website/src/app/app/account/layout.tsx
'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect } from 'react';

const accountNav = [
  { href: '/app/account/profile', label: 'Profile', icon: '◉' },
  { href: '/app/account/security', label: 'Security', icon: '◈' },
  { href: '/app/account/billing', label: 'Plan & Billing', icon: '◆' },
  { href: '/app/account/usage', label: 'Usage & Limits', icon: '◇' },
  { href: '/app/account/data', label: 'Data & Privacy', icon: '◎' },
  { href: '/app/account/support', label: 'Support', icon: '◌' },
];

export default function AccountLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex min-h-screen">
      {/* Account Sidebar */}
      <aside className="w-56 shrink-0 border-r border-steel/10 bg-concrete p-4">
        <Link
          href="/app/dashboard"
          className="mb-6 flex items-center gap-2 text-xs font-telemetry uppercase text-steel hover:text-chalk transition-colors"
        >
          ← Back to Dashboard
        </Link>

        <h2 className="mb-4 font-monument text-lg text-chalk">Account</h2>

        <nav className="flex flex-col gap-1">
          {accountNav.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`
                  flex items-center gap-2 rounded px-3 py-2 text-sm transition-colors
                  ${active
                    ? 'bg-acid-green/10 text-acid-green'
                    : 'text-steel hover:bg-chalk/5 hover:text-chalk'
                  }
                `.trim()}
              >
                <span className="text-xs">{item.icon}</span>
                {item.label}
              </Link>
            );
          })}
        </nav>
      </aside>

      {/* Content */}
      <main className="flex-1 p-6 lg:p-8">
        <div className="mx-auto max-w-3xl">{children}</div>
      </main>
    </div>
  );
}
```

**Step 2: Create the redirect page**

```tsx
// lap-website/src/app/app/account/page.tsx
import { redirect } from 'next/navigation';

export default function AccountPage() {
  redirect('/app/account/profile');
}
```

**Step 3: Commit**

```bash
cd lap-website
git add src/app/app/account/layout.tsx src/app/app/account/page.tsx
git commit -m "feat(frontend): add account layout with sidebar sub-navigation"
```

---

### Task 13: Add user avatar menu to app sidebar

**Files:**
- Modify: `lap-website/src/app/app/layout.tsx`

**Step 1: Add user menu at the bottom of the app sidebar**

In the sidebar section of `layout.tsx`, after the navigation groups, add:

```tsx
{/* User menu at bottom of sidebar */}
<div className="mt-auto border-t border-steel/10 pt-4">
  <Link
    href="/app/account"
    className={`
      flex items-center gap-3 rounded px-3 py-2 text-sm transition-colors
      ${pathname.startsWith('/app/account')
        ? 'bg-acid-green/10 text-acid-green'
        : 'text-steel hover:bg-chalk/5 hover:text-chalk'
      }
    `.trim()}
  >
    <span className="flex h-8 w-8 items-center justify-center rounded-full bg-pit-orange/20 text-xs font-bold text-pit-orange">
      {/* First letter of user name or generic icon */}
      ◉
    </span>
    <span className="font-telemetry text-xs uppercase">Account</span>
  </Link>
</div>
```

**Step 2: Commit**

```bash
git add src/app/app/layout.tsx
git commit -m "feat(frontend): add account link to app sidebar"
```

---

### Task 14: Create API hooks for account data

**Files:**
- Create: `lap-website/src/hooks/useAccount.ts`
- Create: `lap-website/src/hooks/useEntitlements.ts`
- Create: `lap-website/src/hooks/useBilling.ts`
- Create: `lap-website/src/hooks/useUsage.ts`

**Step 1: Create the hooks**

```typescript
// lap-website/src/hooks/useAccount.ts
'use client';

import { useState, useEffect } from 'react';
import { api } from '@/lib/api-client';

export interface AccountProfile {
  id: number;
  email: string;
  display_name: string;
  avatar_url: string | null;
  email_verified: boolean;
  plan_tier: string;
  subscription_status: string | null;
  preferences: {
    language?: string;
    timezone?: string;
    units?: 'metric' | 'imperial';
    notifications?: {
      report_ready?: boolean;
      billing_alerts?: boolean;
      product_updates?: boolean;
      weekly_digest?: boolean;
    };
  };
}

export function useAccount() {
  const [profile, setProfile] = useState<AccountProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchProfile = async () => {
    try {
      setLoading(true);
      const data = await api.get<AccountProfile>('/me');
      setProfile(data);
      setError(null);
    } catch (err: any) {
      setError(err.message || 'Failed to load profile');
    } finally {
      setLoading(false);
    }
  };

  const updateProfile = async (updates: Partial<AccountProfile>) => {
    try {
      const data = await api.put<AccountProfile>('/account/profile', updates);
      setProfile(data);
      return data;
    } catch (err: any) {
      throw err;
    }
  };

  useEffect(() => {
    fetchProfile();
  }, []);

  return { profile, loading, error, updateProfile, refetch: fetchProfile };
}
```

```typescript
// lap-website/src/hooks/useEntitlements.ts
'use client';

import { useState, useEffect } from 'react';
import { api } from '@/lib/api-client';

export interface Entitlements {
  plan: string;
  entitlements: {
    reports_per_month: number;
    uploads_per_month: number;
    raw_retention_days: number;
    report_retention: string;
    comparison_progress: boolean;
    coaching_drills: boolean;
    viz_workspace: boolean;
    strategy_dashboard: string;
    live_pace: boolean;
    pit_planning: boolean;
    pdf_reports: boolean;
    api_access: boolean;
    track_management: string;
    max_workspace_members: number;
  };
}

export function useEntitlements() {
  const [data, setData] = useState<Entitlements | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get<Entitlements>('/account/entitlements')
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return { entitlements: data, loading };
}
```

```typescript
// lap-website/src/hooks/useBilling.ts
'use client';

import { useState, useEffect } from 'react';
import { api } from '@/lib/api-client';

export interface BillingStatus {
  plan: string;
  status: string;
  has_payment_method: boolean;
  billing_cycle?: string;
  current_period_end?: number;
  cancel_at_period_end?: boolean;
  payment_method_last4?: string;
  payment_method_brand?: string;
}

export function useBilling() {
  const [billing, setBilling] = useState<BillingStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchBilling = async () => {
    try {
      setLoading(true);
      const data = await api.get<BillingStatus>('/billing/status');
      setBilling(data);
    } catch {
    } finally {
      setLoading(false);
    }
  };

  const openPortal = async () => {
    const { url } = await api.post<{ url: string }>('/billing/portal', {
      return_url: `${window.location.origin}/app/account/billing`,
    });
    window.location.href = url;
  };

  useEffect(() => {
    fetchBilling();
  }, []);

  return { billing, loading, openPortal, refetch: fetchBilling };
}
```

```typescript
// lap-website/src/hooks/useUsage.ts
'use client';

import { useState, useEffect } from 'react';
import { api } from '@/lib/api-client';

export interface UsageMetric {
  used: number;
  limit: number;
  remaining: number;
  resets: string;
}

export type UsageSnapshot = Record<string, UsageMetric>;

export function useUsage() {
  const [usage, setUsage] = useState<UsageSnapshot | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get<UsageSnapshot>('/account/usage')
      .then(setUsage)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return { usage, loading };
}
```

**Step 2: Commit**

```bash
git add src/hooks/useAccount.ts src/hooks/useEntitlements.ts src/hooks/useBilling.ts src/hooks/useUsage.ts
git commit -m "feat(frontend): add account, entitlements, billing, and usage hooks"
```

---

## Phase 6: Frontend — Account Pages

### Task 15: Create Profile page

**Files:**
- Create: `lap-website/src/app/app/account/profile/page.tsx`

Build a form with: display name input, email (with verification badge), avatar URL input, language/timezone/units selectors, notification preference toggles. Use the existing `FormField` component pattern. Call `useAccount()` hook for data, `updateProfile()` for saves.

**Step 1: Create the page**

The page should follow the patterns from the login form (FormField component, loading states, error display). Use Tailwind classes matching the existing theme (asphalt, chalk, steel, acid-green, pit-orange).

**Step 2: Commit**

```bash
git add src/app/app/account/profile/page.tsx
git commit -m "feat(frontend): add account profile page with preferences"
```

---

### Task 16: Create Security page

**Files:**
- Create: `lap-website/src/app/app/account/security/page.tsx`

Build sections for: password change form, 2FA setup wizard (3 states: disabled → setup → enabled), active sessions table with revoke buttons, OAuth connections with unlink buttons.

**2FA Setup Flow:**
1. "Enable 2FA" button → calls POST /2fa/setup → shows QR code + backup codes
2. User enters verification code → calls POST /2fa/verify → shows "2FA enabled"
3. When enabled: shows "Disable" option, "Regenerate backup codes" option

**Sessions Table:**
- Columns: Device, IP, Last Active, Actions
- "Revoke" button per session
- "Log out all other devices" button

**Step 1: Create the page**

**Step 2: Commit**

```bash
git add src/app/app/account/security/page.tsx
git commit -m "feat(frontend): add security page with password, 2FA, sessions, OAuth"
```

---

### Task 17: Create Billing page

**Files:**
- Create: `lap-website/src/app/app/account/billing/page.tsx`

Build: plan status card (plan name, status badge, renewal date, payment method), quick action cards that open Stripe Portal (invoices, payment method, cancel), billing email field.

Use subscription state badges from design:
- `free` → steel badge
- `active` → acid-green badge
- `past_due` → safety-red badge
- `canceled` → steel badge

**Step 1: Create the page**

**Step 2: Commit**

```bash
git add src/app/app/account/billing/page.tsx
git commit -m "feat(frontend): add billing page with Stripe Portal integration"
```

---

### Task 18: Create Usage & Limits page

**Files:**
- Create: `lap-website/src/app/app/account/usage/page.tsx`

Build: progress bars for each metric (reports, uploads), showing used/limit with color coding (green < 80%, yellow 80-99%, red at limit), reset date display, upgrade CTA when at limit.

**Step 1: Create the page**

**Step 2: Commit**

```bash
git add src/app/app/account/usage/page.tsx
git commit -m "feat(frontend): add usage and limits dashboard page"
```

---

### Task 19: Create Data & Privacy page

**Files:**
- Create: `lap-website/src/app/app/account/data/page.tsx`

Build: export section (request button, status indicator, download button), retention table (session name, uploaded date, expiry date), delete account section with confirmation modal (two-step: type email to confirm).

**Step 1: Create the page**

**Step 2: Commit**

```bash
git add src/app/app/account/data/page.tsx
git commit -m "feat(frontend): add data and privacy page with export, retention, delete"
```

---

### Task 20: Create Support page

**Files:**
- Create: `lap-website/src/app/app/account/support/page.tsx`

Build: structured contact form (issue type dropdown, optional session ID, description textarea), status page link, changelog link.

**Step 1: Create the page**

**Step 2: Commit**

```bash
git add src/app/app/account/support/page.tsx
git commit -m "feat(frontend): add support page with contact form"
```

---

## Phase 7: Frontend Auth Updates (2FA Login Flow)

### Task 21: Update login page for 2FA flow

**Files:**
- Modify: `lap-website/src/app/(auth)/login/page.tsx`
- Modify: `lap-website/src/lib/auth.ts`
- Modify: `lap-website/src/hooks/useAuth.ts`

**Step 1: Update auth.ts to handle 2FA response**

In `auth.ts`, modify `login()` to detect the `requires_2fa` response and return it. Add a new `verify2FA(tempToken, code)` function.

**Step 2: Update login page**

Add a second form state: when login returns `requires_2fa: true`, show a TOTP code input instead of the email/password form. On submit, call `verify2FA()`.

**Step 3: Commit**

```bash
git add src/app/\(auth\)/login/page.tsx src/lib/auth.ts src/hooks/useAuth.ts
git commit -m "feat(frontend): add 2FA login flow with TOTP code input"
```

---

## Phase 8: Auth Route for Forgot/Reset Password Frontend

### Task 22: Create forgot-password and reset-password pages

**Files:**
- Create: `lap-website/src/app/(auth)/forgot-password/page.tsx`
- Create: `lap-website/src/app/(auth)/reset-password/page.tsx`

**Step 1: Create forgot-password page**

Simple form: email input, submit button. Calls POST /auth/forgot-password. Shows success message regardless (no email enumeration).

**Step 2: Create reset-password page**

Reads `?token=` from URL. Shows new password + confirm password inputs. Calls POST /auth/reset-password. Redirects to login on success.

**Step 3: Commit**

```bash
git add src/app/\(auth\)/forgot-password/page.tsx src/app/\(auth\)/reset-password/page.tsx
git commit -m "feat(frontend): add forgot-password and reset-password pages"
```

---

## Phase 9: Integration Tests & Verification

### Task 23: Add backend integration tests for the full account flow

**Files:**
- Create: `telemetry_tool/tests/test_account_integration.py`

Write integration tests that cover:
1. Register → verify email → login → get profile
2. Change password → old password rejected → new password works
3. Enable 2FA → login requires 2FA step → backup code works
4. Get entitlements → matches plan
5. Get usage → starts at 0
6. Request export → status → download
7. Delete account → login fails

Use the Flask test client with mocked DB connections.

**Step 1: Write the tests**

**Step 2: Run**

Run: `cd telemetry_tool && python -m pytest tests/test_account_integration.py -v`

**Step 3: Commit**

```bash
git add telemetry_tool/tests/test_account_integration.py
git commit -m "test(account): add integration tests for full account lifecycle"
```

---

### Task 24: Add frontend E2E tests

**Files:**
- Create: `lap-website/e2e/account.spec.ts`

Write Playwright E2E tests covering:
1. Navigate to /app/account → redirects to /app/account/profile
2. Profile page renders with user data
3. Security page renders 2FA toggle
4. Billing page shows plan status
5. Usage page shows progress bars
6. Data page shows export button
7. Support page has contact form

Mock API responses using `page.route()` (follow pattern from `e2e/auth.spec.ts`).

**Step 1: Write the tests**

**Step 2: Run**

Run: `cd lap-website && npx playwright test e2e/account.spec.ts`

**Step 3: Commit**

```bash
git add e2e/account.spec.ts
git commit -m "test(e2e): add Playwright tests for account section"
```

---

### Task 25: Run full test suites and fix any issues

**Step 1: Run backend tests**

Run: `cd telemetry_tool && python -m pytest tests/ -v --tb=short`
Expected: All pass (check for no regressions).

**Step 2: Run frontend tests**

Run: `cd lap-website && npm run lint && npm run test && npm run build`
Expected: All pass, build succeeds.

**Step 3: Final commit with any fixes**

```bash
git add -A
git commit -m "fix: resolve test issues from account experience implementation"
```

---

## Summary

| Phase | Tasks | Key Deliverables |
|-------|-------|-----------------|
| 1. Foundation | 1-3 | Migration 020, entitlements module, usage service |
| 2. Password | 4-5 | Password change/reset, session management |
| 3. 2FA | 6 | Full TOTP with backup codes, 2FA login |
| 4. Billing | 7-10 | Stripe Portal, billing status, OAuth, retention, support |
| 5. Frontend Layout | 11-14 | Account layout, sidebar, hooks |
| 6. Frontend Pages | 15-20 | Profile, Security, Billing, Usage, Data, Support pages |
| 7. Auth Updates | 21-22 | 2FA login flow, forgot/reset password |
| 8. Testing | 23-25 | Integration tests, E2E tests, full verification |

**Total: 25 tasks across 8 phases. Each task is 1 commit.**

**Dependencies**: Phases 1-4 (backend) can run independently. Phase 5-7 (frontend) depends on Phase 1-4 APIs existing. Phase 8 runs last.

**Python packages needed**: `pyotp`, `qrcode[pil]` (for TOTP)
**No new frontend packages needed** — uses existing Next.js + Tailwind + existing components.
