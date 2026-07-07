"""Test onboarding/tokens.py (Task 5): HMAC-signed, expiring, scoped token.

This token is the SOLE authorization on two otherwise-public HTTP endpoints
(draw-limits link from an email, and the save-back), so every failure mode
must collapse to a single generic ``TokenError`` -- never a bool, never a
leak of which check failed.
"""
import inspect
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from telemetry_tool.onboarding import tokens  # noqa: E402


def test_roundtrip(monkeypatch):
    monkeypatch.setenv("ONBOARDING_TOKEN_SECRET", "s3cret")
    tok, jti = tokens.mint("req1")
    claims = tokens.verify(tok, "req1")
    assert claims["jti"] == jti
    assert claims["scope"] == "onboarding"
    assert claims["request_id"] == "req1"


def test_wrong_request_id(monkeypatch):
    monkeypatch.setenv("ONBOARDING_TOKEN_SECRET", "s3cret")
    tok, _jti = tokens.mint("req1")
    with pytest.raises(tokens.TokenError):
        tokens.verify(tok, "req2")


def test_tampered_signature(monkeypatch):
    monkeypatch.setenv("ONBOARDING_TOKEN_SECRET", "s3cret")
    tok, _jti = tokens.mint("req1")
    payload_b64, sig_b64 = tok.split(".")
    flipped = _flip_char(sig_b64)
    tampered = f"{payload_b64}.{flipped}"
    with pytest.raises(tokens.TokenError):
        tokens.verify(tampered, "req1")


def test_tampered_payload(monkeypatch):
    monkeypatch.setenv("ONBOARDING_TOKEN_SECRET", "s3cret")
    tok, _jti = tokens.mint("req1")
    payload_b64, sig_b64 = tok.split(".")
    flipped = _flip_char(payload_b64)
    tampered = f"{flipped}.{sig_b64}"
    with pytest.raises(tokens.TokenError):
        tokens.verify(tampered, "req1")


def test_malformed_token(monkeypatch):
    monkeypatch.setenv("ONBOARDING_TOKEN_SECRET", "s3cret")
    with pytest.raises(tokens.TokenError):
        tokens.verify("not-a-valid-token", "req1")
    with pytest.raises(tokens.TokenError):
        tokens.verify("only-one-segment-no-dot", "req1")
    with pytest.raises(tokens.TokenError):
        tokens.verify("###not-base64###.###also-not###", "req1")


def test_expired(monkeypatch):
    monkeypatch.setenv("ONBOARDING_TOKEN_SECRET", "s3cret")
    monkeypatch.setenv("ONBOARDING_TOKEN_TTL_HOURS", "0")
    tok, _jti = tokens.mint("req1")
    with pytest.raises(tokens.TokenError):
        tokens.verify(tok, "req1")


def test_secret_unset_fails_closed(monkeypatch):
    monkeypatch.delenv("ONBOARDING_TOKEN_SECRET", raising=False)
    with pytest.raises(tokens.TokenError):
        tokens.mint("req1")
    with pytest.raises(tokens.TokenError):
        tokens.verify("whatever.whatever", "req1")


def test_secret_empty_string_fails_closed(monkeypatch):
    monkeypatch.setenv("ONBOARDING_TOKEN_SECRET", "")
    with pytest.raises(tokens.TokenError):
        tokens.mint("req1")
    with pytest.raises(tokens.TokenError):
        tokens.verify("whatever.whatever", "req1")


def test_uses_compare_digest():
    assert "compare_digest" in inspect.getsource(tokens.verify)


def _flip_char(b64_segment: str) -> str:
    """Flip one character in a urlsafe-base64 segment to a different valid char."""
    chars = list(b64_segment)
    for i, c in enumerate(chars):
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        for candidate in alphabet:
            if candidate != c:
                chars[i] = candidate
                return "".join(chars)
    raise AssertionError("segment too short to flip")
