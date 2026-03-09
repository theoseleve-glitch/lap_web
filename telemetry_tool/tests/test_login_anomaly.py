"""Tests for login anomaly detection (#0741)."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from auth.login_anomaly import (
    check_login_anomalies,
    record_failed_login,
    VELOCITY_MAX_IPS,
    SPRAY_MAX_USERS,
)


@pytest.fixture
def mock_redis():
    r = MagicMock()
    with patch("auth.login_anomaly._get_redis", return_value=r):
        yield r


class TestCheckLoginAnomalies:
    def test_no_redis_returns_empty(self):
        with patch("auth.login_anomaly._get_redis", return_value=None):
            result = check_login_anomalies(1, "1.2.3.4")
            assert result == []

    def test_known_ip_no_anomaly(self, mock_redis):
        mock_redis.sismember.return_value = True
        mock_redis.zcard.return_value = 1
        result = check_login_anomalies(1, "1.2.3.4")
        assert not any(a["type"] == "new_ip" for a in result)

    def test_new_ip_detected(self, mock_redis):
        mock_redis.sismember.return_value = False
        mock_redis.scard.return_value = 3  # User has 3 known IPs
        mock_redis.zcard.return_value = 1
        result = check_login_anomalies(1, "9.9.9.9")
        new_ip = [a for a in result if a["type"] == "new_ip"]
        assert len(new_ip) == 1
        assert new_ip[0]["severity"] == "medium"
        # Should record the new IP
        mock_redis.sadd.assert_called()

    def test_first_ever_login_no_new_ip_alert(self, mock_redis):
        mock_redis.sismember.return_value = False
        mock_redis.scard.return_value = 0  # No known IPs yet
        mock_redis.zcard.return_value = 1
        result = check_login_anomalies(1, "1.2.3.4")
        assert not any(a["type"] == "new_ip" for a in result)

    def test_high_velocity_detected(self, mock_redis):
        mock_redis.sismember.return_value = True
        mock_redis.zcard.return_value = VELOCITY_MAX_IPS + 1
        result = check_login_anomalies(1, "1.2.3.4")
        velocity = [a for a in result if a["type"] == "high_velocity"]
        assert len(velocity) == 1
        assert velocity[0]["severity"] == "high"

    def test_normal_velocity_no_alert(self, mock_redis):
        mock_redis.sismember.return_value = True
        mock_redis.zcard.return_value = 2
        result = check_login_anomalies(1, "1.2.3.4")
        assert not any(a["type"] == "high_velocity" for a in result)

    def test_redis_error_fails_open(self, mock_redis):
        mock_redis.sismember.side_effect = ConnectionError("redis down")
        result = check_login_anomalies(1, "1.2.3.4")
        assert result == []


class TestRecordFailedLogin:
    def test_no_redis_returns_empty(self):
        with patch("auth.login_anomaly._get_redis", return_value=None):
            result = record_failed_login("1.2.3.4", "user@test.com")
            assert result == []

    def test_spray_detected(self, mock_redis):
        mock_redis.zcard.return_value = SPRAY_MAX_USERS
        result = record_failed_login("1.2.3.4", "user@test.com")
        spray = [a for a in result if a["type"] == "password_spray"]
        assert len(spray) == 1
        assert spray[0]["severity"] == "high"

    def test_no_spray_below_threshold(self, mock_redis):
        mock_redis.zcard.return_value = 2
        result = record_failed_login("1.2.3.4", "user@test.com")
        assert not any(a["type"] == "password_spray" for a in result)

    def test_email_lowercased(self, mock_redis):
        mock_redis.zcard.return_value = 0
        record_failed_login("1.2.3.4", "USER@TEST.COM")
        call_args = mock_redis.zadd.call_args
        assert "user@test.com" in call_args[0][1]

    def test_redis_error_fails_open(self, mock_redis):
        mock_redis.zadd.side_effect = ConnectionError("redis down")
        result = record_failed_login("1.2.3.4", "user@test.com")
        assert result == []
