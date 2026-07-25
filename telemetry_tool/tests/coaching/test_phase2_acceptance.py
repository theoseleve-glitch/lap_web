"""P2-Task 6 — Phase 2 end-to-end ACCEPTANCE test.

Regression guard for the whole diagnosis-driven-coaching seam: classifier
(`corner_diagnosis.classify_all_corners`) -> aggregation
(`session_composer._aggregate_corner_diagnosis`) -> cause resolution
(`corner_composer._resolve_cause` / `_diagnosis_cause_id`) -> drill selection
(`session_composer._select_drills`), all exercised through the real,
public `compose_session_coaching(corner_diagnosis=...)` entry point rather
than the individual helpers in isolation (those already have direct unit
coverage in `test_composer_diagnosis_routing.py` and
`test_corner_diagnosis.py` / `test_corner_diagnosis_confidence.py`).

This makes permanent the behavior a whole-branch review verified with a
throwaway script:
  1. A HIGH-confidence diagnosis drives drill selection end-to-end.
  2. Different diagnosed causes select different drills.
  3. The honesty gate holds: no diagnosis, and a LOW-confidence (unreliable
     yaw) diagnosis, both fall through to Phase-1 metric-based behavior —
     no diagnosis-driven drill leaks through.

Synthetic-lap builders are inlined copies of `_make_lap_df` / `_make_corner`
from `tests/test_corner_diagnosis.py`, and the corner_perf fixture is an
inlined copy of `_corner_perfs` from `tests/coaching/test_session_composer.py`.
They are copied rather than imported cross-directory: this monorepo has a
second, unrelated app at the worktree root with its OWN top-level `coaching/`
and `tests/` packages (no `__init__.py`, so it does not shadow the `coaching`
import here — regular packages win over namespace portions — but pytest's
package-rootdir walk for this file bottoms out at the worktree root, so a
bare `from tests.test_corner_diagnosis import ...` risks binding to whichever
`tests` package sys.modules already holds, which is NOT guaranteed to be
`telemetry_tool/tests` when the wider suite runs). Inlining sidesteps this
entirely.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from coaching import corner_diagnosis as cd
from coaching.corner_diagnosis import classify_all_corners
from coaching.composers.session_composer import compose_session_coaching
from coaching.diagnosis_cause_map import DIAGNOSIS_LABEL_TO_CAUSE
from coaching.taxonomy.causes import CauseTaxonomy
from coaching.templates.drills import DRILL_LIBRARY


# ---------------------------------------------------------------------------
# Inlined fixtures (see module docstring for why these aren't cross-imported)
# ---------------------------------------------------------------------------

def _corner_perfs(n: int = 5) -> list[dict]:
    """Copy of `test_session_composer._corner_perfs`."""
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


def _make_lap_df(
    n=100, s_start=50.0, s_end=150.0, v_min_at=100.0,
    v_entry_mps=30.0, v_min_mps=20.0, v_exit_mps=28.0,
    has_accel=False, has_pedals=False,
):
    """Copy of `test_corner_diagnosis._make_lap_df` (pedal support unused here,
    kept for fidelity with the original builder)."""
    dist = np.linspace(s_start, s_end, n)
    mid_idx = int(n * (v_min_at - s_start) / (s_end - s_start))
    mid_idx = max(1, min(n - 2, mid_idx))

    speed = np.concatenate([
        np.linspace(v_entry_mps, v_min_mps, mid_idx),
        np.linspace(v_min_mps, v_exit_mps, n - mid_idx),
    ])

    heading = np.linspace(0.0, np.pi / 2, n)

    data = {
        "Distance (m)": dist,
        "Speed (m/s)": speed,
        "Heading (rad)": heading,
    }

    if has_accel:
        dt = 0.1
        lon_g = np.gradient(speed, dt) / 9.81
        lat_g = np.full(n, 0.5)
        data["accel_long_mps2"] = lon_g * 9.81
        data["accel_lat_mps2"] = lat_g * 9.81

    if has_pedals:
        brake = np.zeros(n)
        brake[:mid_idx] = np.linspace(80, 0, mid_idx)
        throttle = np.zeros(n)
        throttle[mid_idx:] = np.linspace(0, 90, n - mid_idx)
        data["Brake (%)"] = brake
        data["Throttle (%)"] = throttle

    return pd.DataFrame(data)


def _make_corner(s_entry=50.0, s_apex=100.0, s_exit=150.0, corner_index=1):
    """Copy of `test_corner_diagnosis._make_corner`."""
    return {
        "corner_index": corner_index,
        "s_entry": s_entry,
        "s_apex": s_apex,
        "s_exit": s_exit,
    }


def _resolved_cause(label: str) -> str:
    """Map a raw classifier label to its taxonomy cause the same way
    `corner_composer._diagnosis_cause_id` does: one causal-parent hop, then
    `DIAGNOSIS_LABEL_TO_CAUSE`."""
    root_label = cd._CAUSAL_PARENT.get(label, label)
    return DIAGNOSIS_LABEL_TO_CAUSE[root_label]


def _drills_for_cause(cause_id: str) -> set[str]:
    """Every drill title in the library whose applicable_causes covers
    `cause_id` (the ground truth `_select_drills` draws from)."""
    return {
        drill["title"] for drill in DRILL_LIBRARY.values()
        if cause_id in drill.get("applicable_causes", [])
    }


def _compose(corner_perf: dict, corner_diagnosis: dict | None, **kwargs):
    """Thin wrapper around the real `compose_session_coaching` call, fixing
    the scaffolding args that don't vary across these acceptance cases."""
    taxonomy = kwargs.pop("taxonomy", None) or CauseTaxonomy()
    scores = kwargs.pop(
        "scores",
        {"total_score": 65, "grade": "C", "strengths": [], "weaknesses": [],
         "sub_scores": {}},
    )
    return compose_session_coaching(
        corner_perfs=[corner_perf],
        coaching_v2=None,
        scores=scores,
        lap_metrics=kwargs.pop("lap_metrics", None),
        driving_style=None,
        analyzer_results={},
        taxonomy=taxonomy,
        vehicle_class=kwargs.pop("vehicle_class", "car"),
        driver_history=None,
        previous_goals=None,
        corner_diagnosis=corner_diagnosis,
    )


# ---------------------------------------------------------------------------
# Case 1 — high-confidence diagnosis drives a diagnosis-mapped drill,
# threaded through classify_all_corners -> the grid -> compose_session_coaching.
# ---------------------------------------------------------------------------

def test_high_confidence_diagnosis_drives_drill_end_to_end():
    # A corner where the driver's min-corner speed is well below theoretical
    # but entry/exit speeds and apex position match theoretical exactly —
    # the classifier should isolate exactly one candidate: low_min_speed.
    lap_df = _make_lap_df(v_entry_mps=30.0, v_min_mps=15.0, v_exit_mps=28.0, has_accel=True)
    theo_df = _make_lap_df(v_entry_mps=30.0, v_min_mps=20.0, v_exit_mps=28.0)
    corners = [_make_corner(s_entry=50.0, s_apex=100.0, s_exit=150.0, corner_index=1)]

    # Curvature profile matched to the synthetic heading's true turn rate
    # ((pi/2 rad)/(100 m)) so the yaw-residual side channel reads clean —
    # this corner's tier ("accel", from accel_long/lat_mps2 columns) is also
    # a reliable-yaw tier, though low_min_speed is a non-yaw label so its
    # confidence isn't gated by either.
    kappa = (np.pi / 2) / 100.0
    curvature_profile = pd.DataFrame({
        "distance_m": np.linspace(0.0, 200.0, 200),
        "curvature_1pm": np.full(200, kappa),
    })

    grid = classify_all_corners(
        resampled_laps={2: lap_df},
        theoretical_lap=theo_df,
        user_corners=corners,
        vehicle_class="car",
        valid_lap_numbers=[2],
        curvature_profile=curvature_profile,
    )
    assert grid["2"]["1"] == {"label": "low_min_speed", "confidence": "high"}
    assert "low_min_speed" not in cd._YAW_RESIDUAL_LABELS  # non-yaw: reliably-high by construction

    corner_perf = _corner_perfs(1)[0]  # corner_id=1, matches the classified corner
    result = _compose(corner_perf, corner_diagnosis=grid)

    detail = result.corner_coaching[0]
    expected_cause = _resolved_cause("low_min_speed")
    assert expected_cause == "mid_corner_speed_loss"
    assert detail.primary_cause == expected_cause

    # At least one selected drill is the one the taxonomy maps this cause to
    # (the reviewer's example: low_min_speed -> mid_corner_speed_loss ->
    # "Entry Speed Ladder Drill" — asserted here via the applicable_causes
    # relationship, not a hardcoded title, per the task's own guidance).
    selected_titles = {d.title for d in result.drills}
    assert selected_titles & _drills_for_cause(expected_cause)


# ---------------------------------------------------------------------------
# Case 2 — the selected drill changes when the diagnosed cause changes,
# corner_perf held fixed.
# ---------------------------------------------------------------------------

def test_drill_changes_with_diagnosed_cause():
    corner_perf = _corner_perfs(1)[0]

    grid_low_min_speed = {"1": {"1": {"label": "low_min_speed", "confidence": "high"}}}
    grid_coast_hesitation = {"1": {"1": {"label": "coast_hesitation", "confidence": "high"}}}

    result_a = _compose(corner_perf, corner_diagnosis=grid_low_min_speed)
    result_b = _compose(corner_perf, corner_diagnosis=grid_coast_hesitation)

    cause_a = _resolved_cause("low_min_speed")
    cause_b = _resolved_cause("coast_hesitation")
    assert cause_a != cause_b  # sanity: the two labels really do route differently

    assert result_a.corner_coaching[0].primary_cause == cause_a
    assert result_b.corner_coaching[0].primary_cause == cause_b

    titles_a = {d.title for d in result_a.drills}
    titles_b = {d.title for d in result_b.drills}
    assert titles_a.isdisjoint(titles_b)
    assert titles_a & _drills_for_cause(cause_a)
    assert titles_b & _drills_for_cause(cause_b)


# ---------------------------------------------------------------------------
# Case 3 — honesty gate + backward compatibility.
# ---------------------------------------------------------------------------

def test_no_diagnosis_matches_omitted_kwarg_phase1_behavior():
    """corner_diagnosis=None must be indistinguishable from never passing the
    kwarg at all — adding the Phase-2 parameter must not perturb Phase-1
    callers."""
    corner_perf = _corner_perfs(1)[0]

    result_explicit_none = _compose(corner_perf, corner_diagnosis=None)
    result_omitted = compose_session_coaching(
        corner_perfs=[corner_perf],
        coaching_v2=None,
        scores={"total_score": 65, "grade": "C", "strengths": [], "weaknesses": [],
                "sub_scores": {}},
        lap_metrics=None,
        driving_style=None,
        analyzer_results={},
        taxonomy=CauseTaxonomy(),
        vehicle_class="car",
        driver_history=None,
        previous_goals=None,
        # corner_diagnosis kwarg intentionally omitted
    )

    assert (result_explicit_none.corner_coaching[0].primary_cause
            == result_omitted.corner_coaching[0].primary_cause)
    assert ([d.title for d in result_explicit_none.drills]
            == [d.title for d in result_omitted.drills])


def test_low_confidence_yaw_diagnosis_falls_through_no_diagnosis_drill():
    """A LOW-confidence yaw diagnosis (the honesty gate: unreliable without a
    corroborating curvature/tier/channel read) must NOT drive cause or drill
    selection — result must match the no-diagnosis Phase-1 path exactly, and
    must NOT surface the diagnosis's own (oversteer) cause."""
    corner_perf = _corner_perfs(1)[0]  # braking_point_delta_m=10.0 -> metric branch fires
    assert "exit_oversteer" in cd._YAW_RESIDUAL_LABELS  # sanity: this IS a gated label

    grid_low_confidence = {"1": {"1": {"label": "exit_oversteer", "confidence": "low"}}}
    result_low = _compose(corner_perf, corner_diagnosis=grid_low_confidence)
    result_none = _compose(corner_perf, corner_diagnosis=None)

    oversteer_cause = DIAGNOSIS_LABEL_TO_CAUSE["exit_oversteer"]
    assert result_low.corner_coaching[0].primary_cause != oversteer_cause
    assert (result_low.corner_coaching[0].primary_cause
            == result_none.corner_coaching[0].primary_cause
            == "early_braking_confidence")  # metric branch: braking_point_delta_m=10.0 > 5.0

    # No diagnosis-driven oversteer drill leaked through: drill selection is
    # byte-for-byte identical to the honest no-diagnosis result.
    assert ([d.title for d in result_low.drills]
            == [d.title for d in result_none.drills])
