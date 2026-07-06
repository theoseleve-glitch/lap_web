"""Signed, expiring, scoped tokens for the track-onboarding loop.

This is the SOLE authorization on two otherwise-public HTTP endpoints (the
draw-limits link sent by email, and its save-back), so it must fail closed
on every ambiguous case:

  * ``ONBOARDING_TOKEN_SECRET`` unset/empty -> both ``mint`` and ``verify``
    raise ``TokenError`` (never fall back to a default secret).
  * Any malformed/tampered/expired/wrong-scope/wrong-request token ->
    ``TokenError`` with a generic message (never a bool, never a message
    that leaks *which* check failed).

Token shape: ``b64url(payload_json) + "." + b64url(hmac_sha256(secret, payload_json_bytes))``
where ``payload_json`` is canonical (sorted keys, no whitespace) JSON of
``{"request_id": str, "jti": str, "scope": "onboarding", "exp": int}``.
"""
from __future__ import annotations

import base64
import hmac
import json
import os
import secrets
import time
from hashlib import sha256

__all__ = ["TokenError", "mint", "verify"]

_SCOPE = "onboarding"
_DEFAULT_TTL_HOURS = 72


class TokenError(Exception):
    """Raised for any invalid, tampered, expired, or misconfigured token."""


def _get_secret() -> bytes:
    secret = os.environ.get("ONBOARDING_TOKEN_SECRET", "")
    if not secret:
        raise TokenError("onboarding token secret is not configured")
    return secret.encode("utf-8")


def _get_ttl_hours() -> float:
    raw = os.environ.get("ONBOARDING_TOKEN_TTL_HOURS")
    if raw is None or raw == "":
        return _DEFAULT_TTL_HOURS
    try:
        return float(raw)
    except ValueError:
        return _DEFAULT_TTL_HOURS


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _sign(secret: bytes, payload_bytes: bytes) -> bytes:
    return hmac.new(secret, payload_bytes, sha256).digest()


def mint(request_id: str) -> tuple[str, str]:
    """Mint a signed onboarding token for ``request_id``.

    Returns ``(raw_token, jti)``. Raises ``TokenError`` if
    ``ONBOARDING_TOKEN_SECRET`` is unset or empty.
    """
    secret = _get_secret()  # fail closed before doing any other work

    jti = secrets.token_urlsafe(16)
    ttl_hours = _get_ttl_hours()
    exp = int(time.time() + ttl_hours * 3600)
    claims = {
        "request_id": request_id,
        "jti": jti,
        "scope": _SCOPE,
        "exp": exp,
    }
    payload_bytes = json.dumps(claims, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload_b64 = _b64url_encode(payload_bytes)
    sig_b64 = _b64url_encode(_sign(secret, payload_bytes))
    return f"{payload_b64}.{sig_b64}", jti


def verify(raw_token: str, request_id: str) -> dict:
    """Verify ``raw_token`` for ``request_id`` and return its claims dict.

    Raises ``TokenError`` (generic, no detail on which check failed) for any
    of: unconfigured secret, malformed token, bad base64, bad signature,
    wrong scope, expired token, or a mismatched ``request_id``.
    """
    secret = _get_secret()  # fail closed before doing any other work

    try:
        payload_b64, sig_b64 = raw_token.split(".")
        payload_bytes = _b64url_decode(payload_b64)
        sig_bytes = _b64url_decode(sig_b64)
    except (ValueError, TypeError):
        raise TokenError("malformed onboarding token")
    except Exception:
        raise TokenError("malformed onboarding token")

    expected_sig = _sign(secret, payload_bytes)
    if not hmac.compare_digest(expected_sig, sig_bytes):
        raise TokenError("invalid onboarding token")

    try:
        claims = json.loads(payload_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise TokenError("invalid onboarding token")

    if not isinstance(claims, dict):
        raise TokenError("invalid onboarding token")

    if claims.get("scope") != _SCOPE:
        raise TokenError("invalid onboarding token")

    exp = claims.get("exp")
    if not isinstance(exp, (int, float)) or exp <= time.time():
        raise TokenError("invalid onboarding token")

    if claims.get("request_id") != request_id:
        raise TokenError("invalid onboarding token")

    return claims
