"""Tests for email retry config and dev/staging suppression."""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestEmailSuppression(unittest.TestCase):
    """EMAIL_SUPPRESS=1 prevents actual email sends."""

    @patch.dict(os.environ, {"EMAIL_SUPPRESS": "1", "RESEND_API_KEY": "re_test"})
    def test_suppress_skips_send(self):
        """When EMAIL_SUPPRESS=1, _send returns True without calling Resend."""
        # Reimport to pick up env var
        import importlib
        import auth.email as email_mod
        importlib.reload(email_mod)

        with patch.object(email_mod, "resend", create=True) as mock_resend:
            result = email_mod._send("test@example.com", "Test Subject", "<p>Hi</p>")

        self.assertTrue(result)
        # resend should NOT have been called
        if hasattr(mock_resend, "Emails"):
            mock_resend.Emails.send.assert_not_called()

        # Restore default
        email_mod.EMAIL_SUPPRESS = False

    @patch.dict(os.environ, {"EMAIL_SUPPRESS": "0"})
    def test_no_suppress_sends_normally(self):
        """When EMAIL_SUPPRESS=0, _send attempts to use Resend."""
        import importlib
        import auth.email as email_mod
        importlib.reload(email_mod)

        # Without API key, should return False
        email_mod.RESEND_API_KEY = ""
        result = email_mod._send("test@example.com", "Test", "<p>Hi</p>")
        self.assertFalse(result)

        # Restore
        email_mod.EMAIL_SUPPRESS = False


class TestEmailRetryConfig(unittest.TestCase):
    """Celery email task has retry configuration."""

    def test_impl_function_exists(self):
        """_send_email_impl is importable and callable."""
        from tasks.email_tasks import _send_email_impl
        self.assertTrue(callable(_send_email_impl))

    def test_retry_config_in_source(self):
        """email_tasks.py source contains retry configuration."""
        import tasks.email_tasks as mod
        source_path = mod.__file__
        with open(source_path) as f:
            source = f.read()

        self.assertIn("autoretry_for", source)
        self.assertIn("retry_backoff", source)
        self.assertIn("max_retries", source)
        self.assertIn("ConnectionError", source)
        self.assertIn("TimeoutError", source)
