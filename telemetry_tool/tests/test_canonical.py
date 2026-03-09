"""Tests for provenance canonical JSON serialisation."""
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from provenance.canonical import canonical_hash, canonicalize


class TestCanonicalize:
    def test_sorts_dict_keys(self):
        obj = {"z": 1, "a": 2, "m": 3}
        result = canonicalize(obj)
        assert result == '{"a": 2, "m": 3, "z": 1}'

    def test_rounds_floats(self):
        obj = {"val": 3.14159265358979}
        result = canonicalize(obj, float_precision=6)
        assert '"val": 3.141593' in result

    def test_normalizes_nan(self):
        obj = {"val": float("nan")}
        result = canonicalize(obj)
        assert '"val": "__NaN__"' in result

    def test_normalizes_inf(self):
        obj = {"val": float("inf"), "neg": float("-inf")}
        result = canonicalize(obj)
        assert '"val": "__Inf__"' in result
        assert '"neg": "__-Inf__"' in result

    def test_nested_dicts_sorted(self):
        obj = {"b": {"d": 1, "c": 2}, "a": 3}
        result = canonicalize(obj)
        assert result == '{"a": 3, "b": {"c": 2, "d": 1}}'

    def test_lists_preserve_order(self):
        obj = {"items": [3, 1, 2]}
        result = canonicalize(obj)
        assert '"items": [3, 1, 2]' in result

    def test_none_preserved(self):
        obj = {"val": None}
        result = canonicalize(obj)
        assert '"val": null' in result

    def test_deterministic_hash(self):
        obj = {"z": 1.0000001, "a": [1, 2, 3]}
        h1 = canonical_hash(obj)
        h2 = canonical_hash(obj)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_different_input_different_hash(self):
        h1 = canonical_hash({"a": 1})
        h2 = canonical_hash({"a": 2})
        assert h1 != h2
