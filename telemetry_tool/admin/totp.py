"""TOTP 2FA service for admin accounts.

Handles secret generation, AES encryption for DB storage,
code verification, provisioning URIs, and recovery codes.
"""
from __future__ import annotations

import json
import secrets

import pyotp
from cryptography.fernet import Fernet

_ISSUER = "LAP Coach Racing"


def generate_totp_secret() -> str:
    """Generate a new TOTP secret (base32-encoded)."""
    return pyotp.random_base32()


def encrypt_secret(secret: str, admin_key: str) -> str:
    """AES-encrypt a TOTP secret for DB storage.

    Uses Fernet (AES-128-CBC + HMAC-SHA256). The admin_key must be
    a valid Fernet key (32 bytes, url-safe base64).
    """
    f = Fernet(admin_key.encode() if isinstance(admin_key, str) else admin_key)
    return f.encrypt(secret.encode()).decode()


def decrypt_secret(encrypted: str, admin_key: str) -> str:
    """Decrypt a stored TOTP secret."""
    f = Fernet(admin_key.encode() if isinstance(admin_key, str) else admin_key)
    return f.decrypt(encrypted.encode()).decode()


def get_provisioning_uri(secret: str, email: str) -> str:
    """Return otpauth:// URI for QR code generation."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=email, issuer_name=_ISSUER)


def verify_totp(secret: str, code: str) -> bool:
    """Verify a TOTP code with 1-step window for clock drift."""
    if not code:
        return False
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


def generate_recovery_codes(count: int = 8) -> list[str]:
    """Generate single-use recovery codes.

    Each code is a 10-character hex string (40 bits of entropy).
    """
    return [secrets.token_hex(5).upper() for _ in range(count)]


def verify_recovery_code(
    stored_codes_json: str, code: str
) -> tuple[bool, str]:
    """Check and consume a recovery code.

    Returns (valid, updated_codes_json). If valid, the code is removed
    from the list. If invalid, the list is returned unchanged.
    """
    codes = json.loads(stored_codes_json)
    normalized = code.upper().strip()

    if normalized in codes:
        codes.remove(normalized)
        return True, json.dumps(codes)

    return False, stored_codes_json
