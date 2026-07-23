"""Guard test: coaching payloads must never leak unrendered template tokens
or hardcoded 0.0% magnitudes masquerading as real measurements.

Regression coverage for the customer-visible bug where `_pick_narrative`
returned the raw (un-.format'ed) narrative template, and `_build_placeholders`
hardcoded several per-corner magnitudes to 0.0 regardless of real analyzer
output.
"""
import json
import re

from coaching.composers.session_composer import compose_session_coaching
from coaching.taxonomy.causes import CauseTaxonomy

# NOTE: `tests.coaching.test_session_composer._corner_perfs` cannot be imported
# by dotted path here — this worktree's pytest.ini rootdir sits one level above
# `telemetry_tool/`, and that parent also has its own top-level `tests/`
# package, so `import tests.coaching` resolves to the wrong `tests` package
# under regular (non-pytest-collection) import machinery. Per the brief's
# fallback ("construct inline the same way"), this is an exact copy of the
# real fixture body from tests/coaching/test_session_composer.py::_corner_perfs.
def _corner_perfs(n=5):
    return [
        {"corner_id": i, "s_start": i * 100, "s_end": i * 100 + 50,
         "theoretical_entry_speed_mps": 25.0, "actual_entry_speed_mps": 22.0,
         "theoretical_apex_speed_mps": 18.0, "actual_apex_speed_mps": 16.0,
         "theoretical_exit_speed_mps": 23.0, "actual_exit_speed_mps": 20.0,
         "braking_point_delta_m": 10.0,
         "time_loss_s": 0.3, "time_loss_braking_s": 0.1,
         "time_loss_apex_speed_s": 0.12, "time_loss_exit_s": 0.08,
         "grip_utilisation_pct": 65.0}
        for i in range(1, n + 1)
    ]


def test_payload_has_no_unrendered_placeholders_or_fake_zero_pct():
    result = compose_session_coaching(
        corner_perfs=_corner_perfs(), coaching_v2={}, scores={"grade": "B"},
        lap_metrics=[], driving_style={}, analyzer_results={},
        taxonomy=CauseTaxonomy(), vehicle_class="kart",
        driver_history=None, previous_goals=None,
    )
    blob = json.dumps(result.to_dict())
    # Broadened vs. the brief's literal regex to also catch format-spec tokens
    # like "{std_dev_s:.2f}" (the actual template that fires for this fixture:
    # grade "B" + an "early_braking_confidence"/"confidence" focus area picks
    # the ("B-C", "consistency") narrative variant, which only uses a
    # format-spec token — the plain r"\{[a-z_]+\}" pattern from the brief
    # would miss it and pass even with the un-rendered-narrative bug live).
    assert not re.search(r"\{[a-z_]+(?::[^}]*)?\}", blob), (
        f"unrendered token in payload: {blob[:400]}"
    )
    assert "0.0%" not in blob, "fabricated 0.0% magnitude leaked to payload"
    assert "Unknown cause" not in blob
