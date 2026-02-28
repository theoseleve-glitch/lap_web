import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import math
import json
from normalize import normalize_value, normalize_dict, normalize_summary

def test_float_rounding():
    assert normalize_value(3.14159265) == 3.1416

def test_nan_to_none():
    assert normalize_value(float("nan")) is None

def test_inf_to_none():
    assert normalize_value(float("inf")) is None

def test_negative_inf_to_none():
    assert normalize_value(float("-inf")) is None

def test_string_passthrough():
    assert normalize_value("hello") == "hello"

def test_int_passthrough():
    assert normalize_value(42) == 42

def test_none_passthrough():
    assert normalize_value(None) is None

def test_bool_passthrough():
    assert normalize_value(True) is True

def test_dict_sorted_keys():
    result = normalize_dict({"z": 1, "a": 2, "m": 3})
    keys = list(result.keys())
    assert keys == ["a", "m", "z"]

def test_dict_nested_normalization():
    result = normalize_dict({"a": {"z": 3.14159, "b": float("nan")}})
    assert result == {"a": {"b": None, "z": 3.1416}}

def test_list_preserves_order():
    result = normalize_value([3.0, 2.0, 1.0])
    assert result == [3.0, 2.0, 1.0]

def test_list_normalizes_elements():
    result = normalize_value([3.14159, float("nan"), "ok"])
    assert result == [3.1416, None, "ok"]

def test_normalize_summary_structure():
    raw = {
        "score_result": {
            "pace": 22.3456789,
            "consistency": float("nan"),
            "total_score": 81.8,
            "grade": "A",
        },
        "lap_times": [45.123456, 46.789012],
        "raw_df": "SHOULD_BE_STRIPPED",
    }
    result = normalize_summary(raw)
    assert "raw_df" not in result
    assert result["score_result"]["pace"] == 22.3457
    assert result["score_result"]["consistency"] is None
    assert result["lap_times"] == [45.1235, 46.789]
