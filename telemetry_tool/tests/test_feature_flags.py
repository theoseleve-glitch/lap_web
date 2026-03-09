"""Tests for feature flag system (#0587)."""
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from web.feature_flags import is_enabled, register_flag, get_all_flags, flags, _DEFAULTS


class TestIsEnabled:
    def test_default_flag_value(self):
        assert is_enabled("ingest_v2") is True  # default True
        assert is_enabled("experimental_charts") is False  # default False

    def test_unknown_flag_returns_false(self):
        assert is_enabled("totally_unknown_flag") is False

    def test_unknown_flag_with_default(self):
        assert is_enabled("unknown", default=True) is True

    def test_env_var_override(self):
        with patch.dict(os.environ, {"USE_PG": "1"}):
            assert is_enabled("use_pg") is True
        with patch.dict(os.environ, {"USE_PG": "0"}):
            assert is_enabled("use_pg") is False

    def test_env_var_not_set_falls_to_default(self):
        with patch.dict(os.environ, {}, clear=True):
            # use_pg defaults to False
            assert is_enabled("use_pg") is False

    @patch("web.feature_flags._redis_flag")
    def test_redis_override_takes_precedence_over_default(self, mock_redis):
        mock_redis.return_value = True
        assert is_enabled("experimental_charts") is True

    @patch("web.feature_flags._redis_flag")
    def test_redis_none_falls_through(self, mock_redis):
        mock_redis.return_value = None
        assert is_enabled("experimental_charts") is False


class TestRegisterFlag:
    def test_register_new_flag(self):
        register_flag("test_new_flag", default=True)
        assert is_enabled("test_new_flag") is True
        # Cleanup
        _DEFAULTS.pop("test_new_flag", None)


class TestGetAllFlags:
    def test_returns_all_registered(self):
        all_flags = get_all_flags()
        assert "ingest_v2" in all_flags
        assert "use_pg" in all_flags
        assert isinstance(all_flags["ingest_v2"], bool)


class TestRequireDecorator:
    def test_enabled_flag_allows_through(self):
        @flags.require("ingest_v2")  # defaults True
        def my_func():
            return "ok"

        result = my_func()
        assert result == "ok"

    def test_disabled_flag_returns_404(self):
        from flask import Flask
        app = Flask(__name__)
        app.config["TESTING"] = True

        from web.api_utils import init_request_id
        init_request_id(app)

        @app.route("/beta")
        @flags.require("experimental_charts")  # defaults False
        def beta_route():
            return "secret"

        with app.test_client() as client:
            resp = client.get("/beta")
            assert resp.status_code == 404
