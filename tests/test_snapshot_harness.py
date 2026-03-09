"""Self-tests for the snapshot harness module."""
import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tests.snapshot_harness import _deep_compare, assert_snapshot_match


class TestDeepCompare:
    def test_identical_dicts(self):
        a = {"x": 1.0, "y": [2.0, 3.0]}
        diffs = _deep_compare(a, a)
        assert diffs == []

    def test_float_within_tolerance(self):
        a = {"x": 1.0000001}
        b = {"x": 1.0000002}
        diffs = _deep_compare(a, b, rtol=1e-6)
        assert diffs == []

    def test_float_outside_tolerance(self):
        a = {"x": 1.0}
        b = {"x": 2.0}
        diffs = _deep_compare(a, b, rtol=1e-6)
        assert len(diffs) > 0

    def test_missing_key(self):
        a = {"x": 1}
        b = {"x": 1, "y": 2}
        diffs = _deep_compare(a, b)
        assert len(diffs) > 0

    def test_nested_diff(self):
        a = {"outer": {"inner": 1.0}}
        b = {"outer": {"inner": 2.0}}
        diffs = _deep_compare(a, b)
        assert any("outer.inner" in d for d in diffs)

    def test_list_length_mismatch(self):
        a = {"items": [1, 2, 3]}
        b = {"items": [1, 2]}
        diffs = _deep_compare(a, b)
        assert any("length" in d for d in diffs)

    def test_nan_equality(self):
        a = {"x": float("nan")}
        b = {"x": float("nan")}
        diffs = _deep_compare(a, b)
        assert diffs == []

    def test_inf_equality(self):
        a = {"x": float("inf")}
        b = {"x": float("inf")}
        diffs = _deep_compare(a, b)
        assert diffs == []

    def test_positive_negative_inf_differ(self):
        a = {"x": float("inf")}
        b = {"x": float("-inf")}
        diffs = _deep_compare(a, b)
        assert len(diffs) > 0

    def test_int_float_cross_compare(self):
        a = {"x": 1}
        b = {"x": 1.0}
        diffs = _deep_compare(a, b, rtol=1e-6)
        assert diffs == []

    def test_type_mismatch(self):
        a = {"x": "hello"}
        b = {"x": 42}
        diffs = _deep_compare(a, b)
        assert any("type mismatch" in d for d in diffs)

    def test_string_diff(self):
        a = {"x": "hello"}
        b = {"x": "world"}
        diffs = _deep_compare(a, b)
        assert len(diffs) == 1


class TestSnapshotMatch:
    def test_creates_snapshot_on_first_run(self, tmp_path):
        result = {"score": 85.5, "grade": "A"}
        assert_snapshot_match(
            result, "test_first_run", snapshot_dir=tmp_path, rtol=1e-6
        )
        assert (tmp_path / "test_first_run.json").exists()
        assert (tmp_path / "test_first_run.hash").exists()

    def test_matches_on_second_run(self, tmp_path):
        result = {"score": 85.5, "grade": "A"}
        assert_snapshot_match(result, "test_match", snapshot_dir=tmp_path)
        assert_snapshot_match(result, "test_match", snapshot_dir=tmp_path)

    def test_fails_on_different_result(self, tmp_path):
        r1 = {"score": 85.5}
        r2 = {"score": 99.0}
        assert_snapshot_match(r1, "test_diff", snapshot_dir=tmp_path)
        with pytest.raises(AssertionError, match="mismatch"):
            assert_snapshot_match(r2, "test_diff", snapshot_dir=tmp_path)

    def test_update_mode_overwrites(self, tmp_path):
        r1 = {"score": 85.5}
        r2 = {"score": 99.0}
        assert_snapshot_match(r1, "test_update", snapshot_dir=tmp_path)
        # Update mode should accept the new result
        assert_snapshot_match(r2, "test_update", snapshot_dir=tmp_path, update=True)
        # Now r2 is the baseline
        assert_snapshot_match(r2, "test_update", snapshot_dir=tmp_path)

    def test_tolerance_pass_updates_hash(self, tmp_path):
        """When values are within tolerance but hash differs, hash file is updated."""
        r1 = {"score": 1.0}
        assert_snapshot_match(r1, "test_tol", snapshot_dir=tmp_path)
        # Manually write a slightly different value into the json but keep old hash
        stored = json.loads((tmp_path / "test_tol.json").read_text())
        stored["score"] = 1.0 + 1e-8  # within default rtol
        (tmp_path / "test_tol.json").write_text(
            json.dumps(stored, sort_keys=True), encoding="utf-8"
        )
        # This should pass (within tolerance) and silently update the hash
        assert_snapshot_match(r1, "test_tol", snapshot_dir=tmp_path)

    def test_nested_snapshot(self, tmp_path):
        result = {
            "metrics": {"pace": 22.5, "consistency": 18.0},
            "laps": [60.1, 60.3, 60.2],
        }
        assert_snapshot_match(result, "test_nested", snapshot_dir=tmp_path)
        assert_snapshot_match(result, "test_nested", snapshot_dir=tmp_path)

    def test_error_message_contains_diffs(self, tmp_path):
        r1 = {"a": 1.0, "b": 2.0}
        r2 = {"a": 1.0, "b": 99.0}
        assert_snapshot_match(r1, "test_msg", snapshot_dir=tmp_path)
        with pytest.raises(AssertionError, match=r"\.b:"):
            assert_snapshot_match(r2, "test_msg", snapshot_dir=tmp_path)
