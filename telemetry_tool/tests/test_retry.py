"""Tests for retry with exponential backoff (#0543)."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from web.retry import retry


class TestRetryDecorator:
    def test_succeeds_first_try(self):
        """No retry needed when function succeeds."""
        fn = MagicMock(return_value="ok")
        wrapped = retry(max_attempts=3)(fn)
        assert wrapped() == "ok"
        assert fn.call_count == 1

    @patch("web.retry.time.sleep")
    def test_retries_on_connection_error(self, mock_sleep):
        """Retries on ConnectionError and eventually succeeds."""
        fn = MagicMock(side_effect=[ConnectionError("down"), "ok"])
        wrapped = retry(max_attempts=3, base_delay=0.1)(fn)
        assert wrapped() == "ok"
        assert fn.call_count == 2
        mock_sleep.assert_called_once()

    @patch("web.retry.time.sleep")
    def test_retries_on_timeout_error(self, mock_sleep):
        fn = MagicMock(side_effect=[TimeoutError(), "ok"])
        wrapped = retry(max_attempts=3, base_delay=0.1)(fn)
        assert wrapped() == "ok"
        assert fn.call_count == 2

    @patch("web.retry.time.sleep")
    def test_raises_after_max_attempts(self, mock_sleep):
        fn = MagicMock(side_effect=ConnectionError("persistent"))
        wrapped = retry(max_attempts=3, base_delay=0.01)(fn)
        with pytest.raises(ConnectionError):
            wrapped()
        assert fn.call_count == 3

    def test_non_retryable_exception_raises_immediately(self):
        """ValueError is not retryable by default."""
        fn = MagicMock(side_effect=ValueError("bad"))
        wrapped = retry(max_attempts=3)(fn)
        with pytest.raises(ValueError):
            wrapped()
        assert fn.call_count == 1

    @patch("web.retry.time.sleep")
    def test_custom_retryable_exceptions(self, mock_sleep):
        fn = MagicMock(side_effect=[ValueError("transient"), "ok"])
        wrapped = retry(max_attempts=3, retryable=[ValueError], base_delay=0.01)(fn)
        assert wrapped() == "ok"
        assert fn.call_count == 2

    @patch("web.retry.time.sleep")
    def test_on_retry_callback(self, mock_sleep):
        callback = MagicMock()
        fn = MagicMock(side_effect=[ConnectionError(), "ok"])
        wrapped = retry(max_attempts=3, base_delay=0.01, on_retry=callback)(fn)
        wrapped()
        callback.assert_called_once()
        assert callback.call_args[0][0] == 1  # attempt number

    @patch("web.retry.time.sleep")
    def test_backoff_increases_delay(self, mock_sleep):
        """Each retry should have a longer delay (before jitter)."""
        fn = MagicMock(side_effect=[ConnectionError(), ConnectionError(), "ok"])
        wrapped = retry(
            max_attempts=3, base_delay=1.0, backoff_factor=2.0, jitter=False
        )(fn)
        wrapped()
        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert len(delays) == 2
        assert delays[0] == pytest.approx(1.0)
        assert delays[1] == pytest.approx(2.0)

    @patch("web.retry.time.sleep")
    def test_max_delay_cap(self, mock_sleep):
        fn = MagicMock(side_effect=[ConnectionError(), ConnectionError(), "ok"])
        wrapped = retry(
            max_attempts=3, base_delay=100.0, max_delay=5.0, jitter=False
        )(fn)
        wrapped()
        for call in mock_sleep.call_args_list:
            assert call.args[0] <= 5.0

    @patch("web.retry.time.sleep")
    def test_jitter_adds_randomness(self, mock_sleep):
        """With jitter, delay should be >= base but not exactly base."""
        fn = MagicMock(side_effect=[ConnectionError(), "ok"])
        wrapped = retry(max_attempts=2, base_delay=1.0, jitter=True)(fn)
        wrapped()
        actual_delay = mock_sleep.call_args[0][0]
        # Jitter adds 0-50% of delay, so should be >= 1.0
        assert actual_delay >= 1.0
        assert actual_delay <= 1.5

    def test_preserves_function_name(self):
        @retry(max_attempts=2)
        def my_function():
            pass

        assert my_function.__name__ == "my_function"
