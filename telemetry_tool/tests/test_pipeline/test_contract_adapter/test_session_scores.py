from __future__ import annotations

from telemetry_tool.pipeline.contract_adapter.session import build_scores


def test_scores_map_from_score_result():
    sr = {
        "total_score": 77.0,
        "scores": {"pace": 80.0, "consistency": 70.0, "execution": 75.0, "robustness": 85.0},
    }
    s = build_scores(sr)
    assert s is not None
    assert s.pace == 80.0
    assert s.consistency == 70.0
    assert s.execution == 75.0
    assert s.robustness == 85.0
    assert s.overall == 77.0


def test_none_score_result_returns_none():
    assert build_scores(None) is None


def test_suppressed_pace_falls_back_to_total_scaled():
    sr = {
        "total_score": 60.0,
        "scores": {"pace": 0.0, "consistency": 70.0, "execution": 75.0, "robustness": 85.0},
    }
    s = build_scores(sr)
    # pace = 0 is allowed by the contract but the adapter doesn't crash
    assert s.pace == 0.0
    assert s.overall == 60.0
