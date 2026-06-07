"""Quest metric registry — invariants the engine relies on."""
from telemetry_tool.gamification.quest_metrics import (
    METRICS, comparator_for, render_label,
)


def test_every_metric_has_required_fields():
    for key, m in METRICS.items():
        assert m["scope"] in ("session", "corner")
        assert m["direction"] in ("higher", "lower")
        assert "{target}" in m["label"]


def test_comparator_follows_direction():
    assert comparator_for("consistency_cv_pct") == "<="   # lower is better
    assert comparator_for("best_lap_improvement_pct") == ">="


def test_render_label_session():
    assert render_label("session.score", target=80, corner_id=None) == "Post a session score of 80+"


def test_render_label_corner():
    out = render_label("corner.apex_speed_kmh", target=58, corner_id=5)
    assert out == "Carry 58 km/h minimum speed through T5"
