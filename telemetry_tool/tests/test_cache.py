"""Tests for Redis cache layer (#0549)."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from web.cache import ApiCache


@pytest.fixture
def cache():
    """Cache instance with mocked Redis."""
    c = ApiCache()
    mock_redis = MagicMock()
    c._redis = mock_redis
    return c, mock_redis


class TestCacheGetSet:
    def test_get_returns_none_on_miss(self, cache):
        c, mock_redis = cache
        mock_redis.get.return_value = None
        assert c.get("missing") is None

    def test_get_returns_deserialized_value(self, cache):
        c, mock_redis = cache
        mock_redis.get.return_value = '{"key": "value"}'
        result = c.get("test")
        assert result == {"key": "value"}

    def test_set_stores_serialized_value(self, cache):
        c, mock_redis = cache
        c.set("test", {"key": "value"}, ttl=60)
        mock_redis.setex.assert_called_once()
        args = mock_redis.setex.call_args
        assert args[0][0] == "cache:test"
        assert args[0][1] == 60

    def test_set_with_tags(self, cache):
        c, mock_redis = cache
        mock_pipe = MagicMock()
        mock_redis.pipeline.return_value = mock_pipe
        c.set("test", "data", ttl=60, tags=["ws:1", "dashboard"])
        mock_pipe.sadd.assert_any_call("tag:ws:1", "cache:test")
        mock_pipe.sadd.assert_any_call("tag:dashboard", "cache:test")
        mock_pipe.execute.assert_called_once()

    def test_delete(self, cache):
        c, mock_redis = cache
        c.delete("test")
        mock_redis.delete.assert_called_once_with("cache:test")


class TestCacheInvalidation:
    def test_invalidate_tag_deletes_members(self, cache):
        c, mock_redis = cache
        mock_redis.smembers.return_value = {"cache:a", "cache:b"}
        mock_pipe = MagicMock()
        mock_redis.pipeline.return_value = mock_pipe

        count = c.invalidate_tag("ws:1")
        assert count == 2
        mock_pipe.delete.assert_any_call("cache:a")
        mock_pipe.delete.assert_any_call("cache:b")
        mock_pipe.delete.assert_any_call("tag:ws:1")

    def test_invalidate_empty_tag(self, cache):
        c, mock_redis = cache
        mock_redis.smembers.return_value = set()
        assert c.invalidate_tag("empty") == 0


class TestCacheDecorator:
    def test_cached_decorator_caches_result(self, cache):
        c, mock_redis = cache
        mock_redis.get.return_value = None  # miss first time

        call_count = 0

        @c.cached(ttl=60, key_func=lambda x: f"fn:{x}")
        def expensive_fn(x):
            nonlocal call_count
            call_count += 1
            return {"result": x}

        result = expensive_fn("a")
        assert result == {"result": "a"}
        assert call_count == 1
        mock_redis.setex.assert_called_once()

    def test_cached_decorator_returns_cached_on_hit(self, cache):
        c, mock_redis = cache
        mock_redis.get.return_value = '{"cached": true}'

        @c.cached(ttl=60, key_func=lambda x: f"fn:{x}")
        def expensive_fn(x):
            raise AssertionError("Should not be called")

        result = expensive_fn("a")
        assert result == {"cached": True}


class TestCacheFallback:
    def test_no_redis_get_returns_none(self):
        c = ApiCache()
        c._redis = None
        # Patch _get_redis to return None (no Redis)
        with patch.object(c, "_get_redis", return_value=None):
            assert c.get("key") is None

    def test_no_redis_set_is_noop(self):
        c = ApiCache()
        with patch.object(c, "_get_redis", return_value=None):
            c.set("key", "val")  # Should not raise

    def test_redis_error_returns_none(self, cache):
        c, mock_redis = cache
        mock_redis.get.side_effect = ConnectionError("down")
        assert c.get("key") is None
