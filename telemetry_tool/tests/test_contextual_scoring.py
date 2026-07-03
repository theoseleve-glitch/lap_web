import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scoring.contextual import apply_feeling_adjustments, RESULT_TAGS


def _base():
    # Mirrors score_session output shape (pre-confidence/DR sub scores sum -> total).
    return {
        "total_score": 80.0,
        "grade": "A",
        "sub_scores": {
            "pace":        {"score": 20.0, "max": 25.0},
            "consistency": {"score": 15.0, "max": 25.0},
            "execution":   {"score": 18.0, "max": 20.0},
            "robustness":  {"score": 12.0, "max": 15.0},
            "adaptation":  {"score": 15.0, "max": 15.0},
        },
    }


def test_no_tags_no_mismatch_is_exact_base():
    b = _base()
    out = apply_feeling_adjustments(b, result_tags=[], perceived_conditions=None,
                                    track_state="dry", felt_rating=None)
    assert out["total_score"] == b["total_score"]
    assert out["grade"] == b["grade"]
    assert out["adjustments"] == []
    assert out["provenance"] == []


def test_dnf_zeroes_robustness_with_label():
    b = _base()  # base_pre = 80, robustness=12 -> contextual pre = 68, scale=80/80=1
    out = apply_feeling_adjustments(b, result_tags=["dnf"], perceived_conditions=None,
                                    track_state="dry", felt_rating=None)
    assert out["total_score"] == 68.0
    codes = [a["code"] for a in out["adjustments"]]
    assert "DNF_ROBUSTNESS_ZERO" in codes
    assert any(a["dimension"] == "robustness" and a["delta"] == -12.0 for a in out["adjustments"])


def test_traffic_relief_is_bounded_and_labeled():
    b = _base()  # consistency deficit = 25-15=10; 25% = 2.5 < cap 3.0 -> +2.5
    out = apply_feeling_adjustments(b, result_tags=["traffic"], perceived_conditions=None,
                                    track_state="dry", felt_rating=None)
    assert out["total_score"] == 82.5
    assert any(a["code"] == "TRAFFIC_CONSISTENCY_RELIEF" and a["delta"] == 2.5
               for a in out["adjustments"])


def test_tyre_age_relief_capped_at_3_points():
    b = _base()
    b["sub_scores"]["pace"]["score"] = 5.0   # deficit = 20; 25% = 5 -> capped to 3.0
    out = apply_feeling_adjustments(b, result_tags=["tyre_age_high"], perceived_conditions=None,
                                    track_state="dry", felt_rating=None)
    assert any(a["code"] == "TYRE_AGE_PACE_NORMALIZE" and a["delta"] == 3.0
               for a in out["adjustments"])


def test_perceived_mismatch_applies_confidence_penalty():
    b = _base()
    out = apply_feeling_adjustments(b, result_tags=[], perceived_conditions="wet",
                                    track_state="dry", felt_rating=None)
    assert out["total_score"] == 72.0  # 80 * 0.90
    assert any(p["code"] == "PERCEIVED_CONDITION_MISMATCH" for p in out["provenance"])


def test_result_tags_set_is_the_contract():
    assert {"dnf", "crashed", "traffic", "tyre_age_high", "completed"} <= RESULT_TAGS
