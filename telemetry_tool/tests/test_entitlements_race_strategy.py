"""Tests for the 'race_strategy' feature key in authorize_feature().

The middleware passes "race_strategy" (not "race_strategy_full") for
POST/PUT/DELETE on race strategy routes. This file verifies that
authorize_feature handles the "race_strategy" key correctly by checking
the race_strategy_limit entitlement field.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask, g

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _make_entitlements(tier="demo", race_strategy_limit=None):
    """Build a minimal entitlements dict for authorize_feature tests."""
    return {
        "plan_tier": tier,
        "subscription_status": "active",
        "race_strategy_limit": race_strategy_limit,
    }


class TestRaceStrategyFeatureGate:
    """authorize_feature(conn, user_id, "race_strategy") must check
    race_strategy_limit and deny when it is None."""

    def test_race_strategy_allowed_for_racer(self):
        """Racer with race_strategy_limit='full' should be allowed."""
        from auth.entitlements import authorize_feature

        ents = _make_entitlements(tier="racer", race_strategy_limit="full")
        app = Flask(__name__)
        with app.test_request_context():
            g.workspace_id = 1
            conn = MagicMock()
            with patch("auth.entitlements.get_user_entitlements", return_value=ents):
                allowed, ctx = authorize_feature(conn, 1, "race_strategy")
                assert allowed is True
                assert ctx["current_tier"] == "racer"

    def test_race_strategy_allowed_for_demo_limited(self):
        """Demo user with race_strategy_limit='limited_3h' should be allowed.

        The 3-hour limit is enforced at strategy-create time, not at the
        feature gate level.
        """
        from auth.entitlements import authorize_feature

        ents = _make_entitlements(tier="demo", race_strategy_limit="limited_3h")
        app = Flask(__name__)
        with app.test_request_context():
            g.workspace_id = 1
            conn = MagicMock()
            with patch("auth.entitlements.get_user_entitlements", return_value=ents):
                allowed, ctx = authorize_feature(conn, 1, "race_strategy")
                assert allowed is True
                assert ctx["current_tier"] == "demo"

    def test_race_strategy_denied_when_no_limit(self):
        """Demo user with race_strategy_limit=None should be denied
        and directed to upgrade to racer.
        """
        from auth.entitlements import authorize_feature

        ents = _make_entitlements(tier="demo", race_strategy_limit=None)
        app = Flask(__name__)
        with app.test_request_context():
            g.workspace_id = 1
            conn = MagicMock()
            with patch("auth.entitlements.get_user_entitlements", return_value=ents):
                allowed, ctx = authorize_feature(conn, 1, "race_strategy")
                assert allowed is False
                assert ctx["upgrade_tier"] == "racer"
                assert ctx["upgrade_url"] == "/billing?plan=RACER"
                assert ctx["current_tier"] == "demo"


class TestDurationLimit:
    """Test 3-hour duration enforcement in create/update."""

    def test_create_race_rejects_over_limit(self):
        """create_race should raise ValueError when duration exceeds max."""
        from unittest.mock import MagicMock

        from services.race_strategy import create_race

        conn = MagicMock()
        data = {
            "race": {"race_name": "Test", "race_duration_s": 14400},  # 4h
            "drivers": [],
        }
        with pytest.raises(ValueError, match="3-hour"):
            create_race(conn, data, max_duration_s=10800)

    def test_create_race_allows_within_limit(self):
        """create_race should succeed when duration is within max."""
        from unittest.mock import MagicMock

        from services.race_strategy import create_race

        conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.lastrowid = 42
        conn.execute.return_value = mock_cursor

        data = {
            "race": {"race_name": "Test", "race_duration_s": 7200},  # 2h
            "drivers": [],
        }
        result = create_race(conn, data, max_duration_s=10800)
        assert result == 42

    def test_create_race_no_limit(self):
        """create_race without max_duration_s should not check duration."""
        from unittest.mock import MagicMock

        from services.race_strategy import create_race

        conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.lastrowid = 99
        conn.execute.return_value = mock_cursor

        data = {
            "race": {"race_name": "Test", "race_duration_s": 86400},  # 24h
            "drivers": [],
        }
        result = create_race(conn, data)  # no max — should succeed
        assert result == 99
