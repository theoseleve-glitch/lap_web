import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scoring import build_tiered_scores


def _base():
    return {
        "total_score": 80.0, "grade": "A",
        "sub_scores": {
            "pace": {"score": 20.0, "max": 25.0},
            "consistency": {"score": 15.0, "max": 25.0},
            "execution": {"score": 18.0, "max": 20.0},
            "robustness": {"score": 12.0, "max": 15.0},
            "adaptation": {"score": 15.0, "max": 15.0},
        },
    }


def test_zero_feeling_is_byte_identical():
    b = _base()
    tiers = build_tiered_scores(b)
    assert tiers["absolute"]["total_score"] == 80.0
    assert tiers["absolute"]["grade"] == "A"
    assert tiers["contextualized"]["total_score"] == 80.0
    assert tiers["contextualized"]["adjustments"] == []
    assert tiers["competition"] is None
    assert tiers["reflection_present"] is False


def test_does_not_mutate_base():
    b = _base()
    build_tiered_scores(b, feeling={"result_tags": ["dnf"], "track_state": "dry"})
    assert b["sub_scores"]["robustness"]["score"] == 12.0  # unchanged
    assert b["total_score"] == 80.0


def test_contextual_and_competition_present():
    b = _base()
    tiers = build_tiered_scores(
        b,
        feeling={"result_tags": ["dnf"], "perceived_conditions": None,
                 "track_state": "dry", "felt_performance_rating": 6},
        competition={"score": 70.0, "grade": "B", "basis": "session_competitors_self_reported"},
    )
    assert tiers["contextualized"]["total_score"] == 68.0
    assert tiers["competition"]["score"] == 70.0
    assert tiers["reflection_present"] is True
