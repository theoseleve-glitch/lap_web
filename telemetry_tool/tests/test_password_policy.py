"""Tests for NIST password policy (#0764)."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from auth.password_policy import (
    MIN_LENGTH,
    check_breached_password,
    validate_password,
)


class TestValidatePassword:
    def test_valid_password(self):
        assert validate_password("secureP@ss123!") == []

    def test_too_short(self):
        errors = validate_password("abc")
        assert any("at least" in e for e in errors)

    def test_exactly_min_length(self):
        assert validate_password("a" * MIN_LENGTH) == []

    def test_too_long(self):
        errors = validate_password("a" * 1025)
        assert any("at most" in e for e in errors)

    def test_common_password_rejected(self):
        errors = validate_password("password")
        assert any("too common" in e for e in errors)

    def test_common_password_case_insensitive(self):
        errors = validate_password("PASSWORD")
        assert any("too common" in e for e in errors)

    def test_short_and_common(self):
        errors = validate_password("pass")
        assert len(errors) >= 1  # at least length error


class TestCheckBreachedPassword:
    @patch("urllib.request.urlopen")
    def test_breached_password_detected(self, mock_urlopen):
        # SHA-1 of "password" = 5BAA61E4C9B93F3F0682250B6CF8331B7EE68FD8
        # suffix = 1E4C9B93F3F0682250B6CF8331B7EE68FD8
        resp = MagicMock()
        resp.read.return_value = b"1E4C9B93F3F0682250B6CF8331B7EE68FD8:3861493\r\nABCDEF:0\r\n"
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = resp

        assert check_breached_password("password") is True

    @patch("urllib.request.urlopen")
    def test_clean_password(self, mock_urlopen):
        resp = MagicMock()
        resp.read.return_value = b"0000000000000000000000000000000000000:0\r\n"
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = resp

        assert check_breached_password("my-super-unique-passphrase-xyz") is False

    @patch("urllib.request.urlopen", side_effect=Exception("timeout"))
    def test_fails_open_on_error(self, mock_urlopen):
        assert check_breached_password("anything") is False

    @patch("urllib.request.urlopen")
    def test_zero_count_not_breached(self, mock_urlopen):
        # SHA-1 of "test1234" = 7110EDA4D09E062AA5E4A390B0A572AC0D2C0220
        resp = MagicMock()
        resp.read.return_value = b"DA4D09E062AA5E4A390B0A572AC0D2C0220:0\r\n"
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = resp

        assert check_breached_password("test1234") is False
