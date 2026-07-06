import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scoring.competition import compute_competition_score


def test_none_when_no_data():
    assert compute_competition_score(None, []) is None
    assert compute_competition_score({}, []) is None


def test_pole_to_last_percentile():
    win = compute_competition_score({"race_position": 1, "race_total_competitors": 10}, [])
    last = compute_competition_score({"race_position": 10, "race_total_competitors": 10}, [])
    assert win["percentile"] == 100.0
    assert last["percentile"] == 0.0
    assert win["score"] > last["score"]


def test_self_reported_provenance_always_present():
    out = compute_competition_score({"race_position": 3, "race_total_competitors": 12}, [])
    assert out["basis"] == "session_competitors_self_reported"
    assert any(p["code"] == "SELF_REPORTED" for p in out["provenance"])


def test_dnf_caps_score_and_flags():
    out = compute_competition_score(
        {"race_position": 2, "race_total_competitors": 20, "race_is_dnf": True}, [])
    assert out["is_dnf"] is True
    assert out["score"] <= 40.0
    assert any(p["code"] == "DNF" for p in out["provenance"])


def test_competitor_count_used_when_total_missing():
    comps = [
        {"competitor_name": "A", "final_position": 1, "gap_to_this_driver_s": -1.2},
        {"competitor_name": "B", "final_position": 3, "gap_to_this_driver_s": 0.8},
    ]
    out = compute_competition_score({"race_position": 2}, comps)
    assert out is not None
    assert out["total_competitors"] == 3  # self (implied) + 2 named rivals inferred from max pos
