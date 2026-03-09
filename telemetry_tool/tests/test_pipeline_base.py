"""Tests for pipeline.base — StageBase ABC and FunctionStage adapter."""
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from pipeline.base import FunctionStage, StageBase, StageResult


# ---------------------------------------------------------------------------
# StageResult
# ---------------------------------------------------------------------------

class TestStageResult:
    def test_defaults(self):
        r = StageResult()
        assert r.output is None
        assert r.artifacts == {}
        assert r.warnings == []

    def test_with_values(self):
        r = StageResult(output=42, artifacts={"k": "v"}, warnings=["w1"])
        assert r.output == 42
        assert r.artifacts == {"k": "v"}
        assert r.warnings == ["w1"]

    def test_artifacts_independent(self):
        """Each instance gets its own artifacts dict."""
        a = StageResult()
        b = StageResult()
        a.artifacts["x"] = 1
        assert "x" not in b.artifacts


# ---------------------------------------------------------------------------
# StageBase ABC
# ---------------------------------------------------------------------------

class TestStageBase:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            StageBase()  # type: ignore[abstract]

    def test_subclass_must_implement_run(self):
        class Incomplete(StageBase):
            pass

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_concrete_subclass(self):
        class MyStage(StageBase):
            name = "my_stage"

            def run(self, **ctx):
                return StageResult(output=ctx.get("x", 0) + 1)

        stage = MyStage()
        assert stage.name == "my_stage"
        result = stage.run(x=10)
        assert result.output == 11

    def test_auto_name_from_class(self):
        class FeatureExtractionStage(StageBase):
            def run(self, **ctx):
                return StageResult()

        stage = FeatureExtractionStage()
        assert stage.name == "featureextraction"

    def test_validate_default_noop(self):
        class Simple(StageBase):
            def run(self, **ctx):
                return StageResult()

        stage = Simple()
        stage.validate()  # should not raise

    def test_rollback_default_noop(self):
        class Simple(StageBase):
            def run(self, **ctx):
                return StageResult()

        stage = Simple()
        stage.rollback()  # should not raise

    def test_validate_can_raise(self):
        class Strict(StageBase):
            def run(self, **ctx):
                return StageResult()

            def validate(self, **ctx):
                if "df" not in ctx:
                    raise ValueError("df is required")

        stage = Strict()
        with pytest.raises(ValueError, match="df is required"):
            stage.validate()

    def test_repr(self):
        class IngestStage(StageBase):
            name = "ingest"

            def run(self, **ctx):
                return StageResult()

        assert "IngestStage" in repr(IngestStage())
        assert "ingest" in repr(IngestStage())


# ---------------------------------------------------------------------------
# FunctionStage adapter
# ---------------------------------------------------------------------------

class TestFunctionStage:
    def test_wraps_simple_function(self):
        def add(a, b):
            return a + b

        stage = FunctionStage("adder", add, args=["a", "b"])
        result = stage.run(a=3, b=4)
        assert result.output == 7

    def test_wraps_function_with_kwargs(self):
        def greet(name, *, greeting="hello"):
            return f"{greeting} {name}"

        stage = FunctionStage(
            "greeter",
            greet,
            args=["name"],
            kwargs={"greeting": "greeting"},
        )
        result = stage.run(name="world", greeting="hi")
        assert result.output == "hi world"

    def test_missing_optional_kwargs_skipped(self):
        def greet(name, *, greeting="hello"):
            return f"{greeting} {name}"

        stage = FunctionStage(
            "greeter",
            greet,
            args=["name"],
            kwargs={"greeting": "greeting"},
        )
        # ctx doesn't include "greeting" key → kwarg is not passed → default used
        result = stage.run(name="world")
        assert result.output == "hello world"

    def test_returns_tuple_in_output(self):
        """Functions that return tuples get wrapped in StageResult.output."""
        def detect():
            return ("track_match", "spa")

        stage = FunctionStage("detect", detect)
        result = stage.run()
        assert result.output == ("track_match", "spa")

    def test_name_and_repr(self):
        def my_func():
            return None

        stage = FunctionStage("test_stage", my_func)
        assert stage.name == "test_stage"
        assert "FunctionStage" in repr(stage)
        assert "my_func" in repr(stage)

    def test_is_subclass_of_stage_base(self):
        def noop():
            return None

        stage = FunctionStage("noop", noop)
        assert isinstance(stage, StageBase)
