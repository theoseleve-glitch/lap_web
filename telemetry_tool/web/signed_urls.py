"""HMAC-signed URL generation and verification for secure file downloads.

Generates time-limited, tamper-proof URLs for file downloads (GDPR exports,
report PDFs, etc.) so that file serve endpoints don't need separate auth.

The signature covers: path + expiry timestamp, signed with the app's
JWT secret. URLs expire after a configurable duration (default 1 hour).

Usage::

    from web.signed_urls import create_signed_url, verify_signed_url

    url = create_signed_url("/exports/abc123.zip", expires_in=3600)
    valid, path = verify_signed_url(url)
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

_SECRET = os.environ.get("TELEMETRY_JWT_SECRET", os.environ.get("TELEMETRY_SECRET_KEY", ""))
_BASE_URL = os.environ.get("FRONTEND_URL", "https://api.lap-coach.racing")


def _get_secret() -> str:
    """Get the signing secret, falling back to app secret."""
    return _SECRET or "telemetry-local-dev-key"


def create_signed_url(path: str, expires_in: int = 3600) -> str:
    """Generate an HMAC-signed URL for a file download.

    Args:
        path: The URL path to sign (e.g., ``/api/v1/exports/abc123.zip``).
        expires_in: Seconds until the URL expires (default: 3600 = 1 hour).

    Returns:
        Full URL with ``expires`` and ``signature`` query parameters.
    """
    expires = int(time.time()) + expires_in
    payload = f"{path}:{expires}"
    sig = hmac.new(
        _get_secret().encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()

    # Build the signed URL
    params = urlencode({"expires": expires, "signature": sig})
    return f"{_BASE_URL}{path}?{params}"


def verify_signed_url(url: str) -> tuple[bool, str]:
    """Verify the HMAC signature and expiry of a signed URL.

    Args:
        url: The full URL to verify (or just path + query string).

    Returns:
        ``(valid, path)`` — ``valid`` is True if signature matches and
        URL hasn't expired, ``path`` is the original path.
    """
    parsed = urlparse(url)
    path = parsed.path
    params = parse_qs(parsed.query)

    expires_str = params.get("expires", [None])[0]
    signature = params.get("signature", [None])[0]

    if not expires_str or not signature:
        return False, path

    try:
        expires = int(expires_str)
    except (ValueError, TypeError):
        return False, path

    # Check expiry
    if time.time() > expires:
        return False, path

    # Verify signature
    payload = f"{path}:{expires}"
    expected_sig = hmac.new(
        _get_secret().encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature, expected_sig):
        return False, path

    return True, path
