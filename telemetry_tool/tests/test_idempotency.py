"""Tests for idempotency-key middleware."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from flask import Flask, g

from web.api_utils import ErrorCode, api_response, init_request_id
from web.idempotency import _LOCK_TTL, _RESPONSE_TTL, idempotent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_call_count = 0


def _make_app():
    """Build a minimal Flask app with an idempotent route."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    init_request_id(app)

    @app.before_request
    def _set_workspace():
        g.workspace_id = "ws_001"

    @app.route("/create", methods=["POST"])
    @idempotent
    def create_resource():
        global _call_count
        _call_count += 1
        return api_response({"id": 1, "call": _call_count}, status=201)

    @app.route("/fail", methods=["POST"])
    @idempotent
    def fail_resource():
        global _call_count
        _call_count += 1
        from flask import jsonify
        return jsonify({"ok": False, "error": "boom"}), 500

    return app


def _mock_redis():
    """Return a mock Redis with configurable get/set/delete."""
    r = MagicMock()
    _store = {}

    def _get(key):
        return _store.get(key)

    def _set(key, value, **kwargs):
        _store[key] = value
        return True

    def _setnx_style(key, value, nx=False, ex=None):
        if nx and key in _store:
            return False
        _store[key] = value
        return True

    def _delete(*keys):
        for k in keys:
            _store.pop(k, None)

    r.get = MagicMock(side_effect=_get)
    r.set = MagicMock(side_effect=_setnx_style)
    r.delete = MagicMock(side_effect=_delete)
    r._store = _store  # expose for assertions
    return r


@pytest.fixture(autouse=True)
def reset_call_count():
    global _call_count
    _call_count = 0


# ---------------------------------------------------------------------------
# Tests — no header
# ---------------------------------------------------------------------------

class TestNoHeader:
    def test_no_header_executes_normally(self):
        app = _make_app()
        mock_r = _mock_redis()
        with patch("web.idempotency.get_redis", return_value=mock_r):
            with app.test_client() as c:
                resp = c.post("/create")
                assert resp.status_code == 201
                data = resp.get_json()
                assert data["data"]["call"] == 1

    def test_no_header_does_not_touch_redis(self):
        app = _make_app()
        mock_r = _mock_redis()
        with patch("web.idempotency.get_redis", return_value=mock_r):
            with app.test_client() as c:
                c.post("/create")
                mock_r.get.assert_not_called()
                mock_r.set.assert_not_called()


# ---------------------------------------------------------------------------
# Tests — first request with key
# ---------------------------------------------------------------------------

class TestFirstRequest:
    def test_executes_and_caches(self):
        app = _make_app()
        mock_r = _mock_redis()
        with patch("web.idempotency.get_redis", return_value=mock_r):
            with app.test_client() as c:
                resp = c.post(
                    "/create",
                    headers={"Idempotency-Key": "key-001"},
                )
                assert resp.status_code == 201
                data = resp.get_json()
                assert data["data"]["id"] == 1
                # Response should be cached
                cache_key = "idempotency:ws_001:key-001"
                assert cache_key in mock_r._store

    def test_handler_called_once(self):
        app = _make_app()
        mock_r = _mock_redis()
        with patch("web.idempotency.get_redis", return_value=mock_r):
            with app.test_client() as c:
                c.post("/create", headers={"Idempotency-Key": "key-002"})
                assert _call_count == 1


# ---------------------------------------------------------------------------
# Tests — replay cached response
# ---------------------------------------------------------------------------

class TestReplay:
    def test_second_request_replays(self):
        app = _make_app()
        mock_r = _mock_redis()
        with patch("web.idempotency.get_redis", return_value=mock_r):
            with app.test_client() as c:
                resp1 = c.post(
                    "/create",
                    headers={"Idempotency-Key": "key-replay"},
                )
                resp2 = c.post(
                    "/create",
                    headers={"Idempotency-Key": "key-replay"},
                )
                assert resp2.status_code == resp1.status_code
                assert resp2.get_json()["data"] == resp1.get_json()["data"]

    def test_handler_not_called_on_replay(self):
        app = _make_app()
        mock_r = _mock_redis()
        with patch("web.idempotency.get_redis", return_value=mock_r):
            with app.test_client() as c:
                c.post("/create", headers={"Idempotency-Key": "key-replay2"})
                c.post("/create", headers={"Idempotency-Key": "key-replay2"})
                assert _call_count == 1

    def test_replayed_body_matches(self):
        app = _make_app()
        mock_r = _mock_redis()
        with patch("web.idempotency.get_redis", return_value=mock_r):
            with app.test_client() as c:
                resp1 = c.post(
                    "/create",
                    headers={"Idempotency-Key": "key-body"},
                )
                body1 = resp1.get_json()
                resp2 = c.post(
                    "/create",
                    headers={"Idempotency-Key": "key-body"},
                )
                body2 = resp2.get_json()
                assert body1["data"]["id"] == body2["data"]["id"]
                assert body1["data"]["call"] == body2["data"]["call"]


# ---------------------------------------------------------------------------
# Tests — concurrent lock (409)
# ---------------------------------------------------------------------------

class TestConcurrentLock:
    def test_locked_returns_409(self):
        app = _make_app()
        mock_r = _mock_redis()
        # Pre-set the lock key to simulate concurrent request
        lock_key = "idempotency:lock:ws_001:key-locked"
        mock_r._store[lock_key] = "1"
        with patch("web.idempotency.get_redis", return_value=mock_r):
            with app.test_client() as c:
                resp = c.post(
                    "/create",
                    headers={"Idempotency-Key": "key-locked"},
                )
                assert resp.status_code == 409
                data = resp.get_json()
                assert data["error"]["code"] == "IDEMPOTENCY_CONFLICT"


# ---------------------------------------------------------------------------
# Tests — 5xx not cached
# ---------------------------------------------------------------------------

class TestServerError:
    def test_500_not_cached(self):
        app = _make_app()
        mock_r = _mock_redis()
        with patch("web.idempotency.get_redis", return_value=mock_r):
            with app.test_client() as c:
                resp = c.post(
                    "/fail",
                    headers={"Idempotency-Key": "key-500"},
                )
                assert resp.status_code == 500
                cache_key = "idempotency:ws_001:key-500"
                assert cache_key not in mock_r._store

    def test_500_retry_executes_again(self):
        app = _make_app()
        mock_r = _mock_redis()
        with patch("web.idempotency.get_redis", return_value=mock_r):
            with app.test_client() as c:
                c.post("/fail", headers={"Idempotency-Key": "key-retry"})
                c.post("/fail", headers={"Idempotency-Key": "key-retry"})
                assert _call_count == 2


# ---------------------------------------------------------------------------
# Tests — workspace scoping
# ---------------------------------------------------------------------------

class TestWorkspaceScoping:
    def test_different_workspace_separate_entries(self):
        app = _make_app()
        mock_r = _mock_redis()

        @app.before_request
        def _override_ws():
            """Overridden per-request below."""
            pass

        _ws = {"val": "ws_001"}

        @app.before_request
        def _set_ws():
            g.workspace_id = _ws["val"]

        with patch("web.idempotency.get_redis", return_value=mock_r):
            with app.test_client() as c:
                _ws["val"] = "ws_A"
                resp_a = c.post(
                    "/create",
                    headers={"Idempotency-Key": "shared-key"},
                )
                _ws["val"] = "ws_B"
                resp_b = c.post(
                    "/create",
                    headers={"Idempotency-Key": "shared-key"},
                )
                # Both should execute (different workspaces)
                assert _call_count == 2


# ---------------------------------------------------------------------------
# Tests — lock lifecycle
# ---------------------------------------------------------------------------

class TestLockLifecycle:
    def test_lock_released_after_success(self):
        app = _make_app()
        mock_r = _mock_redis()
        with patch("web.idempotency.get_redis", return_value=mock_r):
            with app.test_client() as c:
                c.post("/create", headers={"Idempotency-Key": "key-lock"})
                lock_key = "idempotency:lock:ws_001:key-lock"
                assert lock_key not in mock_r._store

    def test_lock_released_after_failure(self):
        app = _make_app()
        mock_r = _mock_redis()
        with patch("web.idempotency.get_redis", return_value=mock_r):
            with app.test_client() as c:
                c.post("/fail", headers={"Idempotency-Key": "key-lock-fail"})
                lock_key = "idempotency:lock:ws_001:key-lock-fail"
                assert lock_key not in mock_r._store


# ---------------------------------------------------------------------------
# Tests — TTL values
# ---------------------------------------------------------------------------

class TestTTL:
    def test_response_ttl_is_24h(self):
        assert _RESPONSE_TTL == 86400

    def test_lock_ttl_is_60s(self):
        assert _LOCK_TTL == 60

    def test_response_cached_with_ttl(self):
        app = _make_app()
        mock_r = _mock_redis()
        with patch("web.idempotency.get_redis", return_value=mock_r):
            with app.test_client() as c:
                c.post("/create", headers={"Idempotency-Key": "key-ttl"})
                # Find the set call that cached the response (not the lock)
                cache_calls = [
                    call for call in mock_r.set.call_args_list
                    if "idempotency:ws_001:key-ttl" in str(call)
                    and "lock" not in str(call)
                ]
                assert len(cache_calls) >= 1
                # The call should include ex=_RESPONSE_TTL
                call_kwargs = cache_calls[0]
                assert call_kwargs.kwargs.get("ex") == 86400 or \
                    (len(call_kwargs.args) >= 3 if hasattr(call_kwargs, 'args') else False)


class TestIdempotencyRedisFailopenAlert:
    def test_alerts_when_get_redis_raises(self):
        app = _make_app()
        with (
            patch("web.idempotency.get_redis", side_effect=ConnectionError("redis down")),
            patch("web.idempotency.alert_redis_failopen") as mock_alert,
        ):
            client = app.test_client()
            resp = client.post("/create", headers={"Idempotency-Key": "k1"})
        assert resp.status_code == 201  # still passes through
        mock_alert.assert_called_once_with("idempotency")
