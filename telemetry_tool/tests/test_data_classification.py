"""Tests for data classification system (#1029)."""
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from web.data_classification import (
    DataLevel,
    classify,
    get_classification_report,
    get_restricted_fields,
    is_exportable,
)


class TestClassify:
    def test_specific_field_restricted(self):
        assert classify("users", "password_hash") == DataLevel.RESTRICTED

    def test_specific_field_confidential(self):
        assert classify("users", "email") == DataLevel.CONFIDENTIAL

    def test_wildcard_table(self):
        assert classify("sessions") == DataLevel.INTERNAL

    def test_public_table(self):
        assert classify("tracks") == DataLevel.PUBLIC

    def test_unknown_table_defaults_internal(self):
        assert classify("unknown_table") == DataLevel.INTERNAL

    def test_specific_overrides_wildcard(self):
        # users.password_hash is RESTRICTED even though users.* isn't set
        assert classify("users", "password_hash") == DataLevel.RESTRICTED

    def test_field_without_specific_falls_to_wildcard(self):
        # sessions.some_field → sessions.* → INTERNAL
        assert classify("sessions", "track_name") == DataLevel.INTERNAL


class TestGetRestrictedFields:
    def test_users_restricted_fields(self):
        restricted = get_restricted_fields("users")
        assert "password_hash" in restricted
        assert "totp_secret" in restricted
        assert "email" not in restricted  # confidential, not restricted

    def test_table_with_no_restricted(self):
        assert get_restricted_fields("tracks") == []


class TestClassificationReport:
    def test_report_has_all_levels(self):
        report = get_classification_report()
        for level in DataLevel:
            assert level.value in report

    def test_report_not_empty(self):
        report = get_classification_report()
        total = sum(len(v) for v in report.values())
        assert total > 0

    def test_restricted_has_credentials(self):
        report = get_classification_report()
        assert any("password_hash" in item for item in report["restricted"])


class TestIsExportable:
    def test_restricted_not_exportable(self):
        assert is_exportable("users", "password_hash") is False

    def test_confidential_exportable(self):
        assert is_exportable("users", "email") is True

    def test_public_exportable(self):
        assert is_exportable("tracks") is True

    def test_internal_exportable(self):
        assert is_exportable("sessions") is True
