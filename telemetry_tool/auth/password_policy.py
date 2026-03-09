"""NIST SP 800-63B password policy.

Rules:
- Minimum 8 characters (NIST minimum)
- Maximum 1024 characters (generous upper bound)
- Check against breached passwords via HIBP k-Anonymity API
  (only first 5 chars of SHA-1 sent — privacy-safe)
- No arbitrary composition rules (NIST discourages uppercase/symbol requirements)
"""
from __future__ import annotations

import hashlib
import logging

logger = logging.getLogger(__name__)

MIN_LENGTH = 8
MAX_LENGTH = 1024

# Common passwords to reject even if HIBP is unreachable
_COMMON_PASSWORDS = frozenset({
    "password", "12345678", "123456789", "1234567890", "qwerty123",
    "password1", "iloveyou", "princess", "sunshine", "football",
    "abc12345", "monkey123", "dragon12", "master12", "qwerty12",
    "letmein1", "baseball", "shadow12", "trustno1", "welcome1",
})


def validate_password(password: str) -> list[str]:
    """Validate password against NIST guidelines.

    Returns a list of error messages (empty = valid).
    """
    errors: list[str] = []

    if len(password) < MIN_LENGTH:
        errors.append(f"Password must be at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        errors.append(f"Password must be at most {MAX_LENGTH} characters")
    if password.lower() in _COMMON_PASSWORDS:
        errors.append("This password is too common and easily guessed")

    return errors


def check_breached_password(password: str) -> bool:
    """Check if password appears in known data breaches via HIBP k-Anonymity.

    Returns True if breached, False if clean or if the check fails (fail-open).
    Only the first 5 characters of the SHA-1 hash are sent to the API.
    """
    try:
        import urllib.request

        sha1 = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
        prefix, suffix = sha1[:5], sha1[5:]

        req = urllib.request.Request(
            f"https://api.pwnedpasswords.com/range/{prefix}",
            headers={"User-Agent": "LAP-Coach-Racing/1.0", "Add-Padding": "true"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            body = resp.read().decode("utf-8")

        for line in body.splitlines():
            parts = line.strip().split(":")
            if len(parts) == 2 and parts[0] == suffix:
                count = int(parts[1])
                if count > 0:
                    return True
        return False
    except Exception:
        logger.debug("HIBP check failed (fail-open)", exc_info=True)
        return False
