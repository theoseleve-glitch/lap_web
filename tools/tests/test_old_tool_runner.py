"""Tests for old_tool_runner — metric extraction and config loading."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from old_tool_runner import extract_comparable_metrics, load_batch_config


def test_extract_comparable_metrics_minimal():
    raw = {
        "score_result": {"pace": 22.5, "consistency": 18.0, "execution": 19.0,
                         "robustness": 21.0, "total_score": 80.5, "grade": "A"},
        "lap_times": [45.1, 46.2, 47.3],
        "corners": [{"id": 1}, {"id": 2}],
        "consistency_metrics": {"cv": 0.02},
        "robustness_metrics": {"std": 0.5},
        "theoretical_metrics": {"lap_time_s": 44.0},
        "lap_metrics": [{}],
        "delta_segments": [{}],
        "segment_losses": [{}],
        "track_id": "CKS",
        "track_match": {"name": "CKS", "length_m": 1200},
        "steps_ok": ["01_ingest", "02_gps"],
        "steps_failed": [],
    }
    result = extract_comparable_metrics(raw)
    assert result["scores"]["total_score"] == 80.5
    assert result["scores"]["grade"] == "A"
    assert len(result["lap_times"]) == 3
    assert result["corner_count"] == 2
    assert result["track_id"] == "CKS"


def test_extract_comparable_metrics_missing_fields():
    raw = {"steps_ok": [], "steps_failed": ["01_ingest"]}
    result = extract_comparable_metrics(raw)
    assert result["scores"]["total_score"] is None
    assert result["lap_times"] == []
    assert result["corner_count"] == 0


def test_load_batch_config(tmp_path):
    config = {"session_type": "race", "track_state": "dry",
              "drivers": [{"name": "Test", "lap_range": None}]}
    path = tmp_path / "test.json"
    import json
    path.write_text(json.dumps(config))
    loaded = load_batch_config(str(path))
    assert loaded["session_type"] == "race"
    assert loaded["drivers"][0]["name"] == "Test"
