"""Guard test: run_enhanced_coaching must tag its output with the engine that
actually produced it — "v3" on the enhanced path, "v2_fallback" whenever it
falls back to the v2 payload. Before this fix, a fallback silently returned
the v2 payload under the same shape as v3, so consumers (and the orchestrator,
which stores it under summary["coaching_v3"]) couldn't tell v2 from v3.

NOTE: `tests.coaching.test_session_composer._corner_perfs` cannot be imported
by dotted path here — this worktree's pytest.ini rootdir sits one level above
`telemetry_tool/`, and that parent also has its own top-level `tests/`
package, so `import tests.coaching` resolves to the wrong `tests` package
under regular (non-pytest-collection) import machinery (same issue documented
in test_coaching_no_placeholders.py). Inlined here, matching that fixture.
"""
from pipeline.stages import s13_coaching_v3 as s13


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


def test_success_path_tagged_v3():
    out = s13.run_enhanced_coaching(
        corner_perfs=_corner_perfs(),
        coaching_v2={"summary": "v2"}, scores={"grade": "B"}, lap_metrics=[],
        driving_style={}, analyzer_bundle={}, driver_history=None,
        vehicle_class="kart", previous_goals=None)
    assert out.get("engine") == "v3"


def test_fallback_is_tagged_not_silent():
    out = s13.run_enhanced_coaching(
        corner_perfs=[], coaching_v2={"summary": "v2"}, scores={}, lap_metrics=[],
        driving_style={}, analyzer_bundle={}, driver_history=None,
        vehicle_class="kart", previous_goals=None)
    assert out.get("engine") == "v2_fallback"
