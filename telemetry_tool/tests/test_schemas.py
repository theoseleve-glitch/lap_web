"""Tests for Pydantic v2 request validation schemas."""
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from web.schemas.auth import LoginSchema, RefreshSchema, RegisterSchema, VerifyEmailSchema
from web.schemas.teams import CreateTeamSchema, InviteMemberSchema
from web.schemas.sessions import SessionListParams
from web.schemas.jobs import JobListParams, ResumeJobSchema
from web.schemas.batch import BatchReanalyzeSchema
from web.schemas.tracks import TrackListParams
from web.schemas.account import ExportRequestSchema, ProfileUpdateSchema


# ---------------------------------------------------------------------------
# auth schemas
# ---------------------------------------------------------------------------

class TestRegisterSchema:
    def test_valid_register(self):
        """Valid registration data is accepted."""
        s = RegisterSchema(email="user@example.com", password="secure123!", display_name="Alice")
        assert s.email == "user@example.com"
        assert s.password == "secure123!"
        assert s.display_name == "Alice"

    def test_invalid_email_rejected(self):
        """Malformed email is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            RegisterSchema(email="not-an-email", password="secure123!", display_name="X")
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("email",) for e in errors)

    def test_short_password_rejected(self):
        """Password shorter than 8 characters is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            RegisterSchema(email="a@b.com", password="short", display_name="X")
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("password",) for e in errors)

    def test_long_password_rejected(self):
        """Password longer than 1024 characters is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            RegisterSchema(email="a@b.com", password="x" * 1025, display_name="X")
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("password",) for e in errors)


class TestLoginSchema:
    def test_valid_login(self):
        s = LoginSchema(email="u@e.com", password="pass1234")
        assert s.email == "u@e.com"

    def test_missing_password(self):
        with pytest.raises(ValidationError):
            LoginSchema(email="u@e.com")


class TestRefreshSchema:
    def test_valid_refresh(self):
        s = RefreshSchema(refresh_token="abc123")
        assert s.refresh_token == "abc123"

    def test_missing_token(self):
        with pytest.raises(ValidationError):
            RefreshSchema()


class TestVerifyEmailSchema:
    def test_valid_token(self):
        s = VerifyEmailSchema(token="verify-me")
        assert s.token == "verify-me"


# ---------------------------------------------------------------------------
# teams schemas
# ---------------------------------------------------------------------------

class TestCreateTeamSchema:
    def test_valid_team(self):
        s = CreateTeamSchema(name="My Team", slug="my-team")
        assert s.name == "My Team"
        assert s.slug == "my-team"

    def test_invalid_slug_uppercase(self):
        """Uppercase slugs are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            CreateTeamSchema(name="My Team", slug="My-Team")
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("slug",) for e in errors)

    def test_slug_too_short(self):
        with pytest.raises(ValidationError):
            CreateTeamSchema(name="OK", slug="a")


class TestInviteMemberSchema:
    def test_valid_invite(self):
        s = InviteMemberSchema(user_id=42, role="admin")
        assert s.user_id == 42
        assert s.role == "admin"

    def test_invalid_role(self):
        with pytest.raises(ValidationError):
            InviteMemberSchema(user_id=42, role="superuser")


# ---------------------------------------------------------------------------
# sessions / jobs / batch / tracks / account schemas
# ---------------------------------------------------------------------------

class TestSessionListParams:
    def test_defaults(self):
        s = SessionListParams()
        assert s.limit == 25
        assert s.track_id is None
        assert s.driver_id is None
        assert s.status is None


class TestJobListParams:
    def test_defaults(self):
        s = JobListParams()
        assert s.limit == 25
        assert s.status is None


class TestResumeJobSchema:
    def test_accept(self):
        s = ResumeJobSchema(joker_decision="accept")
        assert s.joker_decision == "accept"

    def test_reject(self):
        s = ResumeJobSchema(joker_decision="reject")
        assert s.joker_decision == "reject"

    def test_invalid_decision(self):
        with pytest.raises(ValidationError):
            ResumeJobSchema(joker_decision="maybe")


class TestBatchReanalyzeSchema:
    def test_empty_is_valid(self):
        s = BatchReanalyzeSchema()
        assert s.filter_criteria is None

    def test_with_filter(self):
        s = BatchReanalyzeSchema(filter_criteria={"track_id": 1})
        assert s.filter_criteria == {"track_id": 1}


class TestTrackListParams:
    def test_defaults(self):
        s = TrackListParams()
        assert s.limit == 25


class TestExportRequestSchema:
    def test_default_format(self):
        s = ExportRequestSchema()
        assert s.format == "zip"

    def test_json_format(self):
        s = ExportRequestSchema(format="json")
        assert s.format == "json"

    def test_invalid_format(self):
        with pytest.raises(ValidationError):
            ExportRequestSchema(format="csv")


class TestProfileUpdateSchema:
    def test_partial_update(self):
        s = ProfileUpdateSchema(display_name="New Name")
        assert s.display_name == "New Name"
        assert s.email is None

    def test_empty_is_valid(self):
        s = ProfileUpdateSchema()
        assert s.display_name is None
        assert s.email is None
