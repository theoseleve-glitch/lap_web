"""Tests for privacy-safe session pseudonymization.

Validates:
- PID stable for same input
- PID changes when secret changes
- PID never equals raw session_id
- PID is length/charset constrained
- Dual-secret rotation resolves both current and previous
- Export manifest pseudonymization replaces session_id with session_pid
- Missing secret raises ValueError
- Fallback to '<redacted>' when no secret configured
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from privacy.pseudonym import (
    PID_LENGTH,
    generate_session_pid,
    is_valid_pid,
    pseudonymize_export_manifest,
    pseudonymize_for_log,
    resolve_session_pid,
)

# Fixed test values
_SECRET_A = "test-secret-alpha-2026"
_SECRET_B = "test-secret-beta-2026"
_WS_ID = 42
_SESSION_ID = "sess_abc123"


class TestPseudonymGeneration:
    """Core PID generation properties."""

    def test_stable_for_same_input(self):
        """Same secret + workspace + session always produces same PID."""
        pid1 = generate_session_pid(_WS_ID, _SESSION_ID, secret=_SECRET_A)
        pid2 = generate_session_pid(_WS_ID, _SESSION_ID, secret=_SECRET_A)
        assert pid1 == pid2

    def test_changes_when_secret_changes(self):
        """Different secret produces different PID for same input."""
        pid_a = generate_session_pid(_WS_ID, _SESSION_ID, secret=_SECRET_A)
        pid_b = generate_session_pid(_WS_ID, _SESSION_ID, secret=_SECRET_B)
        assert pid_a != pid_b

    def test_changes_when_workspace_changes(self):
        """Different workspace produces different PID for same session."""
        pid1 = generate_session_pid(1, _SESSION_ID, secret=_SECRET_A)
        pid2 = generate_session_pid(2, _SESSION_ID, secret=_SECRET_A)
        assert pid1 != pid2

    def test_changes_when_session_changes(self):
        """Different session produces different PID in same workspace."""
        pid1 = generate_session_pid(_WS_ID, "sess_001", secret=_SECRET_A)
        pid2 = generate_session_pid(_WS_ID, "sess_002", secret=_SECRET_A)
        assert pid1 != pid2

    def test_never_equals_raw_session_id(self):
        """PID must never equal the raw session_id."""
        # Try many different IDs
        for i in range(100):
            sid = f"session_{i:04d}"
            pid = generate_session_pid(_WS_ID, sid, secret=_SECRET_A)
            assert pid != sid, f"PID collision with raw session_id: {sid}"

    def test_pid_length_constrained(self):
        """PID is always exactly PID_LENGTH characters."""
        pid = generate_session_pid(_WS_ID, _SESSION_ID, secret=_SECRET_A)
        assert len(pid) == PID_LENGTH

    def test_pid_charset_constrained(self):
        """PID contains only base64url-safe characters."""
        pid = generate_session_pid(_WS_ID, _SESSION_ID, secret=_SECRET_A)
        assert is_valid_pid(pid)
        # Verify no padding characters
        assert "=" not in pid

    def test_missing_secret_raises(self):
        """ValueError raised when no secret is configured."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove the env vars entirely
            os.environ.pop("LOG_PSEUDONYM_SECRET", None)
            os.environ.pop("LOG_PSEUDONYM_SECRET_PREV", None)
            with pytest.raises(ValueError, match="LOG_PSEUDONYM_SECRET"):
                generate_session_pid(_WS_ID, _SESSION_ID)


class TestDualSecretRotation:
    """Dual-secret rotation support."""

    def test_resolve_with_current_secret(self):
        """Resolve matches PID generated with current secret."""
        pid = generate_session_pid(_WS_ID, _SESSION_ID, secret=_SECRET_A)
        with patch.dict(os.environ, {
            "LOG_PSEUDONYM_SECRET": _SECRET_A,
        }):
            resolved = resolve_session_pid(
                _WS_ID, _SESSION_ID, pid_to_match=pid,
            )
            assert resolved == pid

    def test_resolve_with_previous_secret(self):
        """Resolve matches PID generated with previous secret (rotation grace)."""
        pid_old = generate_session_pid(_WS_ID, _SESSION_ID, secret=_SECRET_A)
        # Now secret has rotated: B is current, A is previous
        with patch.dict(os.environ, {
            "LOG_PSEUDONYM_SECRET": _SECRET_B,
            "LOG_PSEUDONYM_SECRET_PREV": _SECRET_A,
        }):
            resolved = resolve_session_pid(
                _WS_ID, _SESSION_ID, pid_to_match=pid_old,
            )
            assert resolved == pid_old

    def test_resolve_no_match_returns_none(self):
        """Resolve returns None when PID matches neither secret."""
        with patch.dict(os.environ, {
            "LOG_PSEUDONYM_SECRET": _SECRET_A,
        }):
            resolved = resolve_session_pid(
                _WS_ID, _SESSION_ID, pid_to_match="bogus_pid_value_here",
            )
            assert resolved is None

    def test_resolve_without_pid_returns_current(self):
        """Without pid_to_match, resolve returns PID from current secret."""
        with patch.dict(os.environ, {
            "LOG_PSEUDONYM_SECRET": _SECRET_A,
        }):
            resolved = resolve_session_pid(_WS_ID, _SESSION_ID)
            expected = generate_session_pid(_WS_ID, _SESSION_ID, secret=_SECRET_A)
            assert resolved == expected


class TestPseudonymizeForLog:
    """Log-safe pseudonymization with fallback."""

    def test_returns_pid_when_secret_set(self):
        with patch.dict(os.environ, {"LOG_PSEUDONYM_SECRET": _SECRET_A}):
            result = pseudonymize_for_log(_WS_ID, _SESSION_ID)
            expected = generate_session_pid(_WS_ID, _SESSION_ID, secret=_SECRET_A)
            assert result == expected

    def test_returns_redacted_when_no_secret(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("LOG_PSEUDONYM_SECRET", None)
            result = pseudonymize_for_log(_WS_ID, _SESSION_ID)
            assert result == "<redacted>"


class TestExportManifest:
    """Export manifest pseudonymization."""

    def test_replaces_session_id_with_pid(self):
        manifest = [
            {"session_id": "sess_001", "track": "Monza"},
            {"session_id": "sess_002", "track": "Spa"},
        ]
        result = pseudonymize_export_manifest(manifest, _WS_ID, secret=_SECRET_A)

        assert len(result) == 2
        for entry in result:
            assert "session_id" not in entry
            assert "session_pid" in entry
            assert is_valid_pid(entry["session_pid"])

    def test_preserves_other_fields(self):
        manifest = [{"session_id": "sess_001", "track": "Monza", "laps": 10}]
        result = pseudonymize_export_manifest(manifest, _WS_ID, secret=_SECRET_A)

        assert result[0]["track"] == "Monza"
        assert result[0]["laps"] == 10

    def test_does_not_mutate_input(self):
        manifest = [{"session_id": "sess_001"}]
        original_id = manifest[0]["session_id"]
        pseudonymize_export_manifest(manifest, _WS_ID, secret=_SECRET_A)
        assert manifest[0]["session_id"] == original_id


class TestIsValidPid:
    """PID format validation."""

    def test_valid_pid(self):
        pid = generate_session_pid(_WS_ID, _SESSION_ID, secret=_SECRET_A)
        assert is_valid_pid(pid)

    def test_wrong_length(self):
        assert not is_valid_pid("too_short")
        assert not is_valid_pid("a" * (PID_LENGTH + 1))

    def test_invalid_chars(self):
        assert not is_valid_pid("!" * PID_LENGTH)

    def test_not_a_string(self):
        assert not is_valid_pid(12345)  # type: ignore[arg-type]
