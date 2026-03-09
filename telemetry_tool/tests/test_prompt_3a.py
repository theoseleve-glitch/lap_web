"""Tests for PROMPT 3A — Auth Lifecycle + Organizations + Subscription States.

Validates:
- Email verification enforcement blocks writes for unverified users
- Team invite flow: create, accept, decline, expire, cancel
- Account lockout after 5 failed attempts in 15 minutes
- Subscription state machine validates allowed transitions
- Grace period enforcement correctly downgrades after timeout
- Login anomaly detection (new IP sends email)
- Suspension blocks all endpoints
"""
import hashlib
import json
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

class FakeConn:
    """Minimal fake DB connection for service-layer tests."""
    def __init__(self, rows_by_query=None):
        self._rows_by_query = rows_by_query or {}
        self._calls = []
        self._committed = False

    def execute(self, sql, params=None):
        self._calls.append((sql, params))
        cur = MagicMock()
        for key, rows in self._rows_by_query.items():
            if key in sql:
                cur.fetchone.return_value = rows[0] if rows else None
                cur.fetchall.return_value = rows
                return cur
        cur.fetchone.return_value = None
        cur.fetchall.return_value = []
        return cur

    def commit(self):
        self._committed = True

    def rollback(self):
        pass


# ===========================================================================
# A) Email verification enforcement
# ===========================================================================

class TestEmailVerificationEnforcement:
    def test_require_email_verified_blocks_unverified(self):
        """Decorator returns 403 when email_verified is False."""
        from flask import Flask

        from auth.rbac import require_email_verified

        app = Flask(__name__)

        @require_email_verified
        def protected():
            return "ok"

        with app.test_request_context():
            from flask import g
            g.email_verified = False
            resp = protected()
            # Returns tuple (response, status_code) for error
            assert resp[1] == 403
            data = resp[0].get_json()
            assert data["error"]["code"] == "EMAIL_NOT_VERIFIED"

    def test_require_email_verified_allows_verified(self):
        """Decorator allows through when email_verified is True."""
        from flask import Flask

        from auth.rbac import require_email_verified

        app = Flask(__name__)

        @require_email_verified
        def protected():
            return "ok"

        with app.test_request_context():
            from flask import g
            g.email_verified = True
            result = protected()
            assert result == "ok"

    def test_require_email_verified_allows_none(self):
        """Decorator allows through when email_verified is None (legacy)."""
        from flask import Flask

        from auth.rbac import require_email_verified

        app = Flask(__name__)

        @require_email_verified
        def protected():
            return "ok"

        with app.test_request_context():
            from flask import g
            g.email_verified = None
            result = protected()
            assert result == "ok"

    def test_email_verified_in_jwt_payload(self):
        """create_access_token includes email_verified claim."""
        from auth.service import create_access_token, decode_access_token
        secret = "test-secret-key"

        token = create_access_token(42, secret, 15, email_verified=False)
        payload = decode_access_token(token, secret)
        assert payload["email_verified"] is False

        token2 = create_access_token(42, secret, 15, email_verified=True)
        payload2 = decode_access_token(token2, secret)
        assert payload2["email_verified"] is True


# ===========================================================================
# B) Team invitation flow
# ===========================================================================

class TestInviteService:
    def test_hash_token_is_sha256(self):
        """Token hash should be SHA-256 hex."""
        from auth.invites import _hash_token
        h = _hash_token("test-token")
        assert len(h) == 64  # SHA-256 hex = 64 chars
        assert h == hashlib.sha256(b"test-token").hexdigest()

    def test_create_invite_returns_token(self):
        """create_invite returns a raw token and stores hash."""
        from auth.invites import create_invite
        conn = FakeConn({})
        token = create_invite(conn, team_id=1, inviter_id=10, email="new@example.com")
        assert len(token) > 20
        assert conn._committed
        # Should have DELETE (cleanup) and INSERT
        sql_calls = [c[0] for c in conn._calls]
        assert any("DELETE FROM invitations" in s for s in sql_calls)
        assert any("INSERT INTO invitations" in s for s in sql_calls)

    def test_accept_invite_invalid_token(self):
        """accept_invite raises ValueError for unknown token."""
        from auth.invites import accept_invite
        conn = FakeConn({})  # No matching rows
        with pytest.raises(ValueError, match="Invalid invitation token"):
            accept_invite(conn, "bad-token", user_id=5)

    def test_accept_invite_expired(self):
        """accept_invite raises ValueError for expired token."""
        from auth.invites import accept_invite
        expired = datetime.now(timezone.utc) - timedelta(days=1)
        conn = FakeConn({
            "FROM invitations WHERE token_hash": [{
                "id": 1, "team_id": 10, "email": "user@example.com",
                "role": "member", "inviter_id": 5,
                "expires_at": expired,
            }],
        })
        with pytest.raises(ValueError, match="expired"):
            accept_invite(conn, "any-token", user_id=5)

    def test_accept_invite_success(self):
        """accept_invite adds user to team and workspace."""
        from auth.invites import accept_invite
        future = datetime.now(timezone.utc) + timedelta(days=3)
        conn = FakeConn({
            "FROM invitations WHERE token_hash": [{
                "id": 1, "team_id": 10, "email": "user@example.com",
                "role": "member", "inviter_id": 5,
                "expires_at": future,
            }],
            "SELECT workspace_id FROM teams": [{"workspace_id": 100}],
        })
        result = accept_invite(conn, "valid-token", user_id=42)
        assert result["team_id"] == 10
        assert result["role"] == "member"
        assert result["workspace_id"] == 100
        assert conn._committed
        # Should have INSERT INTO team_members and workspace_members
        sql_calls = [c[0] for c in conn._calls]
        assert any("INSERT INTO team_members" in s for s in sql_calls)
        assert any("INSERT INTO workspace_members" in s for s in sql_calls)
        assert any("DELETE FROM invitations" in s for s in sql_calls)

    def test_decline_invite(self):
        """decline_invite deletes the invitation."""
        from auth.invites import decline_invite
        conn = FakeConn({
            "DELETE FROM invitations WHERE token_hash": [{"id": 1}],
        })
        assert decline_invite(conn, "some-token") is True
        assert conn._committed

    def test_decline_invite_not_found(self):
        """decline_invite returns False for unknown token."""
        from auth.invites import decline_invite
        conn = FakeConn({})
        assert decline_invite(conn, "bad-token") is False

    def test_cancel_invite(self):
        """cancel_invite deletes by ID and team_id."""
        from auth.invites import cancel_invite
        conn = FakeConn({
            "DELETE FROM invitations WHERE id": [{"id": 5}],
        })
        assert cancel_invite(conn, invite_id=5, team_id=1) is True

    def test_list_pending_invites(self):
        """list_pending_invites returns non-expired invitations."""
        from auth.invites import list_pending_invites
        now = datetime.now(timezone.utc)
        conn = FakeConn({
            "FROM invitations i": [
                {
                    "id": 1, "email": "a@example.com", "role": "member",
                    "inviter_name": "Admin", "created_at": now, "expires_at": now + timedelta(days=5),
                },
            ],
        })
        result = list_pending_invites(conn, team_id=1)
        assert len(result) == 1
        assert result[0]["email"] == "a@example.com"
        assert result[0]["role"] == "member"


class TestInvitationRoutes:
    def test_invitations_bp_registered(self):
        """invitations_bp should be registered in app.py."""
        from web.routes.teams import invitations_bp
        assert invitations_bp.name == "invitations"
        assert invitations_bp.url_prefix == "/api/v1/invitations"

    def test_teams_invitation_routes_exist(self):
        """Team invitation routes should exist on the teams blueprint."""
        from web.routes.teams import bp
        assert bp.name == "teams"
        assert bp.url_prefix == "/api/v1/teams"
        # Verify invitation endpoint functions exist
        from web.routes.teams import cancel_invitation, create_invitation, list_invitations
        assert callable(create_invitation)
        assert callable(list_invitations)
        assert callable(cancel_invitation)


class TestInviteEmail:
    def test_send_team_invite_email_exists(self):
        """send_team_invite_email function should exist in auth.email."""
        from auth.email import send_team_invite_email
        assert callable(send_team_invite_email)

    @patch("auth.email._send", return_value=True)
    def test_send_team_invite_email_content(self, mock_send):
        """Email should contain accept link with token."""
        from auth.email import send_team_invite_email
        result = send_team_invite_email(
            "user@example.com", "abc123", "Racing Team", "Admin User",
        )
        assert result is True
        call_args = mock_send.call_args
        assert "user@example.com" in call_args[0]
        html = call_args[0][2]  # third positional arg = html
        assert "abc123" in html
        assert "Racing Team" in html
        assert "Admin User" in html


# ===========================================================================
# C) Account lockout
# ===========================================================================

class TestLockoutModule:
    def test_lockout_constants(self):
        """Lockout configuration should match spec."""
        from auth.lockout import LOCKOUT_SECONDS, MAX_ATTEMPTS, WINDOW_SECONDS
        assert MAX_ATTEMPTS == 5
        assert WINDOW_SECONDS == 900     # 15 minutes
        assert LOCKOUT_SECONDS == 1800   # 30 minutes

    def test_check_lockout_returns_none_without_redis(self):
        """check_lockout fails open when Redis unavailable."""
        from auth.lockout import check_lockout
        with patch("auth.lockout._get_redis", return_value=None):
            result = check_lockout("test@example.com")
            assert result is None

    def test_record_failed_attempt_no_redis(self):
        """record_failed_attempt is a no-op without Redis."""
        from auth.lockout import record_failed_attempt
        with patch("auth.lockout._get_redis", return_value=None):
            # Should not raise
            record_failed_attempt("test@example.com")

    def test_clear_attempts_no_redis(self):
        """clear_attempts is a no-op without Redis."""
        from auth.lockout import clear_attempts
        with patch("auth.lockout._get_redis", return_value=None):
            clear_attempts("test@example.com")

    def test_lockout_key_format(self):
        """Key should be login_attempts:{email}."""
        from auth.lockout import _key
        assert _key("Test@Example.COM") == "login_attempts:test@example.com"

    def test_check_lockout_with_redis_not_locked(self):
        """Not locked when under threshold."""
        from auth.lockout import check_lockout
        mock_redis = MagicMock()
        mock_redis.zcard.return_value = 3  # Under MAX_ATTEMPTS (5)
        with patch("auth.lockout._get_redis", return_value=mock_redis):
            result = check_lockout("test@example.com")
            assert result is None

    def test_check_lockout_with_redis_locked(self):
        """Locked when at threshold with recent attempts."""
        import time

        from auth.lockout import LOCKOUT_SECONDS, check_lockout
        mock_redis = MagicMock()
        mock_redis.zcard.return_value = 5  # At MAX_ATTEMPTS
        # Oldest attempt was just now
        mock_redis.zrange.return_value = [(b"member", time.time())]
        with patch("auth.lockout._get_redis", return_value=mock_redis):
            result = check_lockout("test@example.com")
            assert result is not None
            assert 0 < result <= LOCKOUT_SECONDS

    def test_record_failed_attempt_adds_to_sorted_set(self):
        """record_failed_attempt should ZADD to Redis."""
        from auth.lockout import record_failed_attempt
        mock_redis = MagicMock()
        with patch("auth.lockout._get_redis", return_value=mock_redis):
            record_failed_attempt("test@example.com")
            mock_redis.zadd.assert_called_once()
            mock_redis.expire.assert_called_once()


# ===========================================================================
# C) Suspension
# ===========================================================================

class TestSuspension:
    def test_suspension_check_in_login_route(self):
        """Login route should check suspension after auth."""
        import inspect

        from web.routes.auth import login

        # The function should reference _check_suspension
        source = inspect.getsource(login)
        assert "_check_suspension" in source

    def test_check_suspension_returns_reason(self):
        """_check_suspension returns reason when suspended."""
        from web.routes.auth import _check_suspension
        conn = FakeConn({
            "SELECT suspension_reason FROM users": [
                {"suspension_reason": "Violation of terms"},
            ],
        })
        result = _check_suspension(conn, user_id=42)
        assert result == "Violation of terms"

    def test_check_suspension_returns_none_when_active(self):
        """_check_suspension returns None for active users."""
        from web.routes.auth import _check_suspension
        conn = FakeConn({})  # No matching rows
        result = _check_suspension(conn, user_id=42)
        assert result is None

    def test_migration_019_has_suspension_columns(self):
        """Migration 019 (consolidated) should add suspended_at and suspension_reason."""
        migration_path = _PROJECT_ROOT / "alembic" / "versions" / "019_core_data_model.py"
        assert migration_path.exists()
        content = migration_path.read_text()
        assert "suspended_at" in content
        assert "suspension_reason" in content
        assert 'down_revision = "018"' in content


class TestLoginAnomalyDetection:
    def test_check_login_anomaly_known_ip(self):
        """Known IP should not trigger email."""
        from web.routes.auth import _check_login_anomaly
        conn = FakeConn({
            "SELECT 1 FROM audit_log": [{"1": 1}],  # Known IP
        })
        with patch("auth.email.send_new_login_email") as mock_email:
            _check_login_anomaly(conn, user_id=42, ip="1.2.3.4", user_agent="Chrome")
            mock_email.assert_not_called()

    def test_check_login_anomaly_new_ip_sends_email(self):
        """New IP should send notification email."""
        from web.routes.auth import _check_login_anomaly
        conn = FakeConn({
            "SELECT COUNT" : [{"cnt": 5}],  # Has previous logins
            "SELECT email FROM users": [{"email": "user@example.com"}],
        })
        with patch("auth.email.send_new_login_email") as mock_email:
            _check_login_anomaly(conn, user_id=42, ip="9.9.9.9", user_agent="Chrome")
            mock_email.assert_called_once_with(
                "user@example.com",
                device_info="Chrome",
                ip_address="9.9.9.9",
            )

    def test_check_login_anomaly_first_login_no_alert(self):
        """First login should not trigger anomaly alert."""
        from web.routes.auth import _check_login_anomaly
        conn = FakeConn({
            "SELECT COUNT": [{"cnt": 1}],  # Only 1 login (this one)
        })
        with patch("auth.email.send_new_login_email") as mock_email:
            _check_login_anomaly(conn, user_id=42, ip="1.2.3.4", user_agent="Chrome")
            mock_email.assert_not_called()


# ===========================================================================
# D) Subscription state machine
# ===========================================================================

class TestSubscriptionStateMachine:
    def test_states_defined(self):
        """All expected states should be defined."""
        from billing.state_machine import SUBSCRIPTION_STATES
        expected = {"free", "trialing", "active", "past_due", "canceled", "paused"}
        assert set(SUBSCRIPTION_STATES.keys()) == expected

    def test_valid_transitions(self):
        """Known valid transitions should pass validation."""
        from billing.state_machine import validate_transition
        assert validate_transition("free", "active") is True
        assert validate_transition("free", "trialing") is True
        assert validate_transition("active", "past_due") is True
        assert validate_transition("active", "canceled") is True
        assert validate_transition("active", "paused") is True
        assert validate_transition("past_due", "active") is True
        assert validate_transition("past_due", "canceled") is True
        assert validate_transition("canceled", "active") is True

    def test_invalid_transitions(self):
        """Invalid transitions should fail validation."""
        from billing.state_machine import validate_transition
        assert validate_transition("free", "past_due") is False
        assert validate_transition("free", "canceled") is False
        assert validate_transition("active", "free") is False
        assert validate_transition("canceled", "past_due") is False
        assert validate_transition("paused", "past_due") is False
        assert validate_transition("trialing", "past_due") is False

    def test_grace_days(self):
        """Grace days should match spec."""
        from billing.state_machine import get_grace_days
        assert get_grace_days("canceled") == 30
        assert get_grace_days("past_due") == 7
        assert get_grace_days("active") == 0
        assert get_grace_days("free") == 0

    def test_transition_subscription_success(self):
        """Valid transition updates DB and commits."""
        from billing.state_machine import transition_subscription
        conn = FakeConn({
            "SELECT email, subscription_status, plan_tier FROM users": [
                {"email": "user@test.com", "subscription_status": "active", "plan_tier": "racer"},
            ],
        })
        with patch("billing.state_machine._TRANSITION_EMAILS", {}):
            result = transition_subscription(conn, user_id=1, new_status="canceled")
        assert result is True
        assert conn._committed
        # Should have UPDATE and audit log INSERT
        sql_calls = [c[0] for c in conn._calls]
        assert any("UPDATE users SET" in s for s in sql_calls)
        assert any("INSERT INTO audit_log" in s for s in sql_calls)

    def test_transition_subscription_invalid(self):
        """Invalid transition returns False."""
        from billing.state_machine import transition_subscription
        conn = FakeConn({
            "SELECT email, subscription_status, plan_tier FROM users": [
                {"email": "user@test.com", "subscription_status": "free", "plan_tier": "demo"},
            ],
        })
        result = transition_subscription(conn, user_id=1, new_status="past_due")
        assert result is False
        # Should NOT have committed
        assert not conn._committed

    def test_transition_subscription_user_not_found(self):
        """Transition for non-existent user returns False."""
        from billing.state_machine import transition_subscription
        conn = FakeConn({})
        result = transition_subscription(conn, user_id=999, new_status="active")
        assert result is False

    def test_transition_sets_grace_period(self):
        """Transition to canceled should set grace_period_end."""
        from billing.state_machine import transition_subscription
        conn = FakeConn({
            "SELECT email, subscription_status, plan_tier FROM users": [
                {"email": "user@test.com", "subscription_status": "active", "plan_tier": "racer"},
            ],
        })
        with patch("billing.state_machine._TRANSITION_EMAILS", {}):
            transition_subscription(conn, user_id=1, new_status="canceled")
        # Check the UPDATE call includes grace_period_end
        update_call = next(c for c in conn._calls if "UPDATE users SET" in c[0])
        assert "grace_period_end" in update_call[0]
        assert update_call[1]["grace_end"] is not None

    def test_transition_with_plan_tier(self):
        """Transition can also update plan_tier."""
        from billing.state_machine import transition_subscription
        conn = FakeConn({
            "SELECT email, subscription_status, plan_tier FROM users": [
                {"email": "user@test.com", "subscription_status": "free", "plan_tier": "demo"},
            ],
        })
        with patch("billing.state_machine._TRANSITION_EMAILS", {}):
            result = transition_subscription(
                conn, user_id=1, new_status="active", plan_tier="world-class",
            )
        assert result is True
        update_call = next(c for c in conn._calls if "UPDATE users SET" in c[0])
        assert "plan_tier" in update_call[0]
        assert update_call[1]["tier"] == "world-class"


# ===========================================================================
# E) Grace period enforcement task
# ===========================================================================

class TestGracePeriodEnforcement:
    def test_enforce_impl_exists(self):
        """The enforcement function should be importable."""
        from tasks.billing_tasks import _enforce_grace_periods_impl
        assert callable(_enforce_grace_periods_impl)

    @patch("tasks.billing_tasks.get_pg_connection")
    def test_enforce_downgrades_expired_canceled(self, mock_get_conn):
        """Canceled users past grace should be downgraded to demo."""
        from tasks.billing_tasks import _enforce_grace_periods_impl

        past = datetime.now(timezone.utc) - timedelta(days=1)
        conn = FakeConn({
            "WHERE subscription_status = 'canceled'": [
                {"id": 1, "email": "user@test.com", "plan_tier": "racer"},
            ],
            "WHERE subscription_status = 'past_due'": [],
        })
        mock_get_conn.return_value = conn

        with patch("auth.email._send", return_value=True):
            result = _enforce_grace_periods_impl()

        assert result["downgraded"] == 1
        # Check that UPDATE set plan_tier to demo
        update_calls = [c for c in conn._calls if "UPDATE users SET plan_tier = 'demo'" in c[0]]
        assert len(update_calls) >= 1

    @patch("tasks.billing_tasks.get_pg_connection")
    def test_enforce_no_expired(self, mock_get_conn):
        """No downgrade when no expired grace periods."""
        from tasks.billing_tasks import _enforce_grace_periods_impl

        conn = FakeConn({
            "WHERE subscription_status = 'canceled'": [],
            "WHERE subscription_status = 'past_due'": [],
        })
        mock_get_conn.return_value = conn

        result = _enforce_grace_periods_impl()
        assert result["downgraded"] == 0
        assert result["warned"] == 0

    def test_celery_task_registered(self):
        """enforce_subscription_grace_periods should be callable."""
        from tasks.billing_tasks import enforce_subscription_grace_periods
        assert callable(enforce_subscription_grace_periods)


# ===========================================================================
# Migration chain
# ===========================================================================

class TestMigrations:
    def test_migration_019_chains_from_018(self):
        """Migration 019 (consolidated) should chain from 018."""
        path = _PROJECT_ROOT / "alembic" / "versions" / "019_core_data_model.py"
        assert path.exists()
        content = path.read_text()
        assert 'down_revision = "018"' in content

    def test_migration_019_has_grace_period(self):
        """Migration 019 (consolidated) should have grace_period_end."""
        path = _PROJECT_ROOT / "alembic" / "versions" / "019_core_data_model.py"
        content = path.read_text()
        assert "grace_period_end" in content

    def test_migration_021_creates_invitations(self):
        """Migration 021 (consolidated) should create the invitations table."""
        path = _PROJECT_ROOT / "alembic" / "versions" / "021_community_email.py"
        content = path.read_text()
        assert '"invitations"' in content
        assert "token_hash" in content
        assert "team_id" in content
        assert "expires_at" in content
