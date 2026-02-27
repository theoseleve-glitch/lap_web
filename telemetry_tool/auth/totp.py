"""TOTP two-factor authentication module.

Provides secret generation, QR URI/image creation, code verification with ±1
time step tolerance, and single-use backup code generation/consumption.

Pure-Python HOTP/TOTP (RFC 6238) -- no ``pyotp`` dependency.  QR code
generation uses the ``qrcode`` library when available and degrades gracefully
(returns ``None``) when it is not installed.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import logging
import secrets
import struct
import time

logger = logging.getLogger(__name__)

# TOTP issuer name shown in authenticator apps
_ISSUER = "LAP Coach"

# Time step in seconds (standard TOTP)
_TIME_STEP = 30

# Number of digits in TOTP code
_DIGITS = 6

# Clock skew tolerance: allow ±1 time step
_SKEW_STEPS = 1

# Number of backup codes to generate
_BACKUP_CODE_COUNT = 10


# ---------------------------------------------------------------------------
# Secret + URI
# ---------------------------------------------------------------------------

def generate_totp_secret() -> str:
    """Generate a random 20-byte TOTP secret, base32 encoded (32 chars)."""
    raw = secrets.token_bytes(20)
    return base64.b32encode(raw).decode("ascii")


def generate_totp_uri(secret: str, email: str) -> str:
    """Generate an ``otpauth://`` URI for QR code generation.

    Format::

        otpauth://totp/{issuer}:{email}?secret=...&issuer=...&digits=6&period=30
    """
    from urllib.parse import quote
    label = f"{_ISSUER}:{email}"
    return (
        f"otpauth://totp/{quote(label)}"
        f"?secret={secret}"
        f"&issuer={quote(_ISSUER)}"
        f"&digits={_DIGITS}"
        f"&period={_TIME_STEP}"
    )


# ---------------------------------------------------------------------------
# QR code generation (optional -- graceful fallback)
# ---------------------------------------------------------------------------

def generate_qr_data_uri(provisioning_uri: str) -> str | None:
    """Return a ``data:image/png;base64,...`` QR code for *provisioning_uri*.

    Returns ``None`` when the ``qrcode`` library (or its PIL backend) is not
    installed so callers can fall back to exposing the URI for manual entry.
    """
    try:
        import qrcode  # type: ignore[import-untyped]
        img = qrcode.make(provisioning_uri)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"
    except ImportError:
        logger.debug("qrcode library not available -- skipping QR generation")
        return None
    except Exception:
        logger.warning("QR code generation failed", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# HOTP / TOTP core (RFC 4226, RFC 6238)
# ---------------------------------------------------------------------------

def _hotp(secret_b32: str, counter: int) -> str:
    """Generate an HOTP code for the given counter value."""
    key = base64.b32decode(secret_b32.upper())
    msg = struct.pack(">Q", counter)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    code = struct.unpack(">I", h[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** _DIGITS)).zfill(_DIGITS)


def _current_counter() -> int:
    """Current TOTP counter based on Unix time."""
    return int(time.time()) // _TIME_STEP


def verify_totp(secret: str, code: str) -> bool:
    """Verify a TOTP code, allowing ±1 time step for clock skew.

    Returns ``True`` if the code matches any valid window.
    """
    if not code or not secret:
        return False

    code = code.strip()
    counter = _current_counter()
    for offset in range(-_SKEW_STEPS, _SKEW_STEPS + 1):
        if hmac.compare_digest(code, _hotp(secret, counter + offset)):
            return True
    return False


# ---------------------------------------------------------------------------
# Backup codes
# ---------------------------------------------------------------------------

def generate_backup_codes() -> list[str]:
    """Generate single-use backup codes in ``xxxx-xxxx`` format.

    Returns *_BACKUP_CODE_COUNT* codes (default 10), each composed of two
    4-character hex groups separated by a hyphen for readability.
    """
    codes: list[str] = []
    for _ in range(_BACKUP_CODE_COUNT):
        raw = secrets.token_hex(4)  # 8 hex chars
        codes.append(f"{raw[:4]}-{raw[4:]}")
    return codes


def hash_backup_code(code: str) -> str:
    """SHA-256 hash of a backup code for storage.

    Normalises the code (strip + lowercase) before hashing so that ``AbCd-1234``
    and ``abcd-1234`` produce the same hash.
    """
    return hashlib.sha256(code.strip().lower().encode()).hexdigest()


def verify_backup_code(code: str, hashed_codes: list[str]) -> int | None:
    """Check if a backup code matches any hashed code.

    Returns the index of the matched code (for consumption) or ``None``.
    Uses constant-time comparison via :func:`hmac.compare_digest`.
    """
    code_hash = hash_backup_code(code)
    for i, stored_hash in enumerate(hashed_codes):
        if hmac.compare_digest(code_hash, stored_hash):
            return i
    return None
