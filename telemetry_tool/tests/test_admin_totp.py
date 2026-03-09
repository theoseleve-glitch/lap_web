"""Tests for admin TOTP 2FA service.

Validates:
- Secret generation produces valid base32
- Encrypt/decrypt roundtrip
- TOTP verification with correct/incorrect codes
- Provisioning URI format
- Recovery code generation and consumption
"""
import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Generate a test encryption key (Fernet key = 32 bytes, url-safe base64)
from cryptography.fernet import Fernet

_TEST_ADMIN_KEY = Fernet.generate_key().decode()


class TestGenerateSecret:
    def test_returns_base32_string(self):
        from admin.totp import generate_totp_secret

        secret = generate_totp_secret()
        assert isinstance(secret, str)
        assert len(secret) >= 16  # pyotp default is 32 chars

    def test_generates_unique_secrets(self):
        from admin.totp import generate_totp_secret

        secrets = {generate_totp_secret() for _ in range(10)}
        assert len(secrets) == 10  # All unique


class TestEncryptDecrypt:
    def test_roundtrip(self):
        from admin.totp import decrypt_secret, encrypt_secret

        original = "JBSWY3DPEHPK3PXP"
        encrypted = encrypt_secret(original, _TEST_ADMIN_KEY)
        assert encrypted != original  # Actually encrypted
        decrypted = decrypt_secret(encrypted, _TEST_ADMIN_KEY)
        assert decrypted == original

    def test_different_keys_fail(self):
        from admin.totp import decrypt_secret, encrypt_secret

        original = "JBSWY3DPEHPK3PXP"
        encrypted = encrypt_secret(original, _TEST_ADMIN_KEY)

        other_key = Fernet.generate_key().decode()
        with pytest.raises(Exception):
            decrypt_secret(encrypted, other_key)

    def test_encrypted_value_is_different_each_time(self):
        from admin.totp import encrypt_secret

        original = "JBSWY3DPEHPK3PXP"
        enc1 = encrypt_secret(original, _TEST_ADMIN_KEY)
        enc2 = encrypt_secret(original, _TEST_ADMIN_KEY)
        # Fernet includes a timestamp, so encryptions differ
        assert enc1 != enc2


class TestVerifyTotp:
    def test_correct_code_passes(self):
        import pyotp

        from admin.totp import generate_totp_secret, verify_totp

        secret = generate_totp_secret()
        totp = pyotp.TOTP(secret)
        code = totp.now()
        assert verify_totp(secret, code) is True

    def test_wrong_code_fails(self):
        from admin.totp import generate_totp_secret, verify_totp

        secret = generate_totp_secret()
        assert verify_totp(secret, "000000") is False

    def test_empty_code_fails(self):
        from admin.totp import generate_totp_secret, verify_totp

        secret = generate_totp_secret()
        assert verify_totp(secret, "") is False


class TestProvisioningUri:
    def test_returns_otpauth_uri(self):
        from admin.totp import generate_totp_secret, get_provisioning_uri

        secret = generate_totp_secret()
        uri = get_provisioning_uri(secret, "admin@lap-coach.racing")
        assert uri.startswith("otpauth://totp/")
        assert "admin%40lap-coach.racing" in uri or "admin@lap-coach.racing" in uri
        assert "LAP" in uri or "Lap" in uri or "lap" in uri

    def test_contains_secret_param(self):
        from admin.totp import get_provisioning_uri

        secret = "JBSWY3DPEHPK3PXP"
        uri = get_provisioning_uri(secret, "test@test.com")
        assert f"secret={secret}" in uri


class TestRecoveryCodes:
    def test_generates_correct_count(self):
        from admin.totp import generate_recovery_codes

        codes = generate_recovery_codes(count=8)
        assert len(codes) == 8

    def test_codes_are_unique(self):
        from admin.totp import generate_recovery_codes

        codes = generate_recovery_codes(count=8)
        assert len(set(codes)) == 8

    def test_code_format(self):
        from admin.totp import generate_recovery_codes

        codes = generate_recovery_codes(count=4)
        for code in codes:
            assert isinstance(code, str)
            assert len(code) >= 8  # Reasonably long

    def test_default_count_is_8(self):
        from admin.totp import generate_recovery_codes

        codes = generate_recovery_codes()
        assert len(codes) == 8


class TestVerifyRecoveryCode:
    def test_valid_code_consumed(self):
        from admin.totp import generate_recovery_codes, verify_recovery_code

        codes = generate_recovery_codes(count=4)
        stored_json = json.dumps(codes)
        target = codes[0]

        valid, updated_json = verify_recovery_code(stored_json, target)
        assert valid is True
        remaining = json.loads(updated_json)
        assert target not in remaining
        assert len(remaining) == 3

    def test_second_use_fails(self):
        from admin.totp import generate_recovery_codes, verify_recovery_code

        codes = generate_recovery_codes(count=4)
        stored_json = json.dumps(codes)
        target = codes[0]

        valid, updated_json = verify_recovery_code(stored_json, target)
        assert valid is True

        # Second use with updated codes
        valid2, _ = verify_recovery_code(updated_json, target)
        assert valid2 is False

    def test_invalid_code_rejected(self):
        from admin.totp import generate_recovery_codes, verify_recovery_code

        codes = generate_recovery_codes(count=4)
        stored_json = json.dumps(codes)

        valid, updated_json = verify_recovery_code(stored_json, "INVALID-CODE")
        assert valid is False
        # Codes unchanged
        assert json.loads(updated_json) == codes

    def test_empty_codes_rejected(self):
        from admin.totp import verify_recovery_code

        valid, updated = verify_recovery_code("[]", "any-code")
        assert valid is False
