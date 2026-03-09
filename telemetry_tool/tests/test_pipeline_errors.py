"""Tests for pipeline_errors module — error hierarchy and classify_error()."""

import pytest

from pipeline_errors import (
    FatalError,
    InteractionRequired,
    PipelineError,
    TransientError,
    classify_error,
)

# ── Hierarchy tests ──────────────────────────────────────────────────


class TestPipelineError:
    def test_is_exception(self):
        assert issubclass(PipelineError, Exception)

    def test_default_retry_eligible(self):
        assert PipelineError.retry_eligible is False

    def test_default_error_class(self):
        assert PipelineError.error_class == "unknown"

    def test_instance_attributes(self):
        err = PipelineError("boom")
        assert str(err) == "boom"
        assert err.retry_eligible is False
        assert err.error_class == "unknown"


class TestTransientError:
    def test_is_pipeline_error(self):
        assert issubclass(TransientError, PipelineError)

    def test_is_exception(self):
        assert issubclass(TransientError, Exception)

    def test_retry_eligible(self):
        assert TransientError.retry_eligible is True

    def test_error_class(self):
        assert TransientError.error_class == "transient"

    def test_instance(self):
        err = TransientError("network down")
        assert err.retry_eligible is True
        assert err.error_class == "transient"
        assert str(err) == "network down"

    def test_catchable_as_pipeline_error(self):
        with pytest.raises(PipelineError):
            raise TransientError("timeout")


class TestFatalError:
    def test_is_pipeline_error(self):
        assert issubclass(FatalError, PipelineError)

    def test_is_exception(self):
        assert issubclass(FatalError, Exception)

    def test_retry_eligible(self):
        assert FatalError.retry_eligible is False

    def test_error_class(self):
        assert FatalError.error_class == "fatal"

    def test_instance(self):
        err = FatalError("corrupt CSV")
        assert err.retry_eligible is False
        assert err.error_class == "fatal"
        assert str(err) == "corrupt CSV"


class TestInteractionRequired:
    def test_is_pipeline_error(self):
        assert issubclass(InteractionRequired, PipelineError)

    def test_retry_eligible(self):
        assert InteractionRequired.retry_eligible is False

    def test_error_class(self):
        assert InteractionRequired.error_class == "interaction"

    def test_stores_reason_and_payload(self):
        payload = {"session_id": "s1", "choices": ["A", "B"]}
        err = InteractionRequired("joker confirmation", payload)
        assert err.reason == "joker confirmation"
        assert err.payload == payload
        assert err.payload["session_id"] == "s1"

    def test_message_includes_reason(self):
        err = InteractionRequired("pick a track", {})
        assert "pick a track" in str(err)
        assert "Interaction required" in str(err)

    def test_empty_payload(self):
        err = InteractionRequired("choose", {})
        assert err.payload == {}


# ── classify_error tests ─────────────────────────────────────────────


class TestClassifyError:
    def test_pipeline_error_base(self):
        assert classify_error(PipelineError("x")) == "unknown"

    def test_transient_error(self):
        assert classify_error(TransientError("x")) == "transient"

    def test_fatal_error(self):
        assert classify_error(FatalError("x")) == "fatal"

    def test_interaction_required(self):
        err = InteractionRequired("reason", {"k": "v"})
        assert classify_error(err) == "interaction"

    def test_connection_error(self):
        assert classify_error(ConnectionError("refused")) == "transient"

    def test_timeout_error(self):
        assert classify_error(TimeoutError("timed out")) == "transient"

    def test_connection_error_subclass(self):
        """Subclasses of ConnectionError should also be transient."""

        class CustomConnectionError(ConnectionError):
            pass

        assert classify_error(CustomConnectionError("redis down")) == "transient"

    def test_timeout_error_subclass(self):
        """Subclasses of TimeoutError should also be transient."""

        class CustomTimeoutError(TimeoutError):
            pass

        assert classify_error(CustomTimeoutError("slow")) == "transient"

    def test_redis_connection_error_if_available(self):
        """redis.ConnectionError inherits from ConnectionError, so it maps to transient."""
        try:
            import redis

            err = redis.ConnectionError("connection refused")
            assert classify_error(err) == "transient"
        except ImportError:
            # redis not installed — verify with a plain ConnectionError subclass instead
            class FakeRedisConnectionError(ConnectionError):
                pass

            assert classify_error(FakeRedisConnectionError("refused")) == "transient"

    def test_value_error_is_fatal(self):
        assert classify_error(ValueError("bad")) == "fatal"

    def test_runtime_error_is_fatal(self):
        assert classify_error(RuntimeError("oops")) == "fatal"

    def test_type_error_is_fatal(self):
        assert classify_error(TypeError("wrong type")) == "fatal"

    def test_os_error_is_fatal(self):
        assert classify_error(OSError("disk full")) == "fatal"

    def test_generic_exception_is_fatal(self):
        assert classify_error(Exception("generic")) == "fatal"
