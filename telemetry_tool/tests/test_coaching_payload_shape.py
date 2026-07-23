"""Payload-shape parity test: coaching_engine's fallback must emit the same
contract as the canonical coaching/models.py types (v3 engine path), since
GET /sessions/<id>/coaching (web/routes/data_v2.py) returns result.to_dict()
regardless of which engine produced the result.
"""
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from coaching_engine import generate_session_coaching, FocusArea, Drill, SessionCoaching
import coaching.models as canon


def test_coaching_engine_types_are_canonical():
    # After unification these ARE the coaching/models.py classes (same object identity) —
    # no more name-collision between two distinct dataclass definitions.
    assert Drill is canon.Drill
    assert FocusArea is canon.FocusArea
    assert SessionCoaching is canon.SessionCoaching


def test_fallback_payload_shape_matches_v3_contract():
    # _aggregate_focus_areas (coaching_engine.py) reads corner_id / primary_cause /
    # time_loss_total_s (or time_loss_s) — not corner_index/avg_time_loss_s/category.
    # "traction_limited" maps to category "exit_traction" via _CAUSE_CATEGORIES.
    result = generate_session_coaching(
        corners=[{"corner_id": 3, "primary_cause": "traction_limited", "time_loss_total_s": 0.4}],
        coaching_v2={}, scores={}, lap_metrics=[], driving_style=None,
    )
    d = result.to_dict()

    # Top-level keys per the canonical SessionCoaching.to_dict
    for k in ("session_theme", "narrative", "strengths", "weaknesses",
              "focus_areas", "drills", "progression", "next_session_goals", "confidence"):
        assert k in d, f"missing {k}"

    # V3-only keys must also be present (always emitted, None when unset) —
    # this is what proves the fallback shape now MATCHES the v3 contract.
    for k in ("corner_coaching", "trail_brake_assessment", "traction_budgets",
              "exit_speed_cascades", "warm_up_protocol", "vehicle_class"):
        assert k in d, f"missing v3 key {k}"

    assert d["focus_areas"], "expected at least one focus area from the 0.4s loss"
    for k in ("rank", "category", "time_loss_s", "corner_ids", "summary", "advice"):
        assert k in d["focus_areas"][0], f"focus area missing {k}"

    assert d["drills"], "expected at least one generated drill"
    for k in ("rank", "title", "description", "focus_corners",
              "target_metric", "target_improvement", "lap_count"):
        assert k in d["drills"][0], f"drill missing {k}"
