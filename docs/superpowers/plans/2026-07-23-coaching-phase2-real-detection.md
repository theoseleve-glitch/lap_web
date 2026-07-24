# Coaching Phase 2 — Real Drill Detection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote the verified `coaching/corner_diagnosis.py` root-cause classifier from an orphaned, user-corner-only, dark component into the canonical driver of drill selection — so a corner's ACTUAL diagnosed mistake (entry-understeer, early-throttle, …) at a measured confidence picks the drill, instead of the shallow `symptom_detector` heuristic. Honesty-gated: yaw-based labels (under/oversteer) are low-confidence without a real curvature profile or on a corrupt-yaw kart, and are softened/withheld rather than asserted.

**Architecture:** Run `classify_all_corners` on EVERY session's auto-detected corners (not just operator-drawn), pass it the real `curvature_profile` the pipeline already computes, attach a per-label confidence, map its label vocabulary → the coaching taxonomy/drill cause ids, persist it into `analysis_json`, and route `compose_corner_coaching` through it as the highest-priority cause source (confidence-gated). Builds on Phase 1 (HEAD 4fbdec1); no new customer-facing surface — reuses the existing coaching payload + endpoints.

**Tech Stack:** Python 3.14 (system, no venv), pytest 9. Backend `telemetry_tool/`. Run pytest from `telemetry_tool/`.

## Global Constraints

- Branch-only, deploy-gated. Work on `feat/adaptive-coaching` (worktree `C:/Users/Admin/lap_web-wt-coaching`). NEVER `git add -A`.
- Reuse the existing 26-cause taxonomy + `DRILL_LIBRARY` + the Phase-1 vocabulary guard (`coaching/vocabulary_check.py`) — extend it, never weaken it. Every cause id anything can emit MUST exist in BOTH the taxonomy and a drill's `applicable_causes`.
- **No fabrication / honesty gate:** a yaw-residual (under/oversteer) label produced without a real `curvature_profile`, or on a tier/session whose yaw channel is unreliable (e.g. the SLK kart, gyro fails calibration), MUST be marked low-confidence and softened or withheld — never asserted as a confident oversteer call. Confidence is a first-class output.
- Kart-first, car-safe: keep `corner_diagnosis`'s vehicle-class thresholds intact.
- Tests run BOTH under pytest AND in `main.py`'s script-mode sys.path (Phase 1's class of bug).
- Run pytest from `telemetry_tool/`: `python -m pytest tests/<file> -q -p no:randomly`.
- Spec anchor: `docs/superpowers/specs/2026-07-23-adaptive-coaching-drill-detection-design.md` §5.

## Key interfaces (verified against current code)

- `coaching/corner_diagnosis.py::classify_all_corners(resampled_laps, theoretical_lap, user_corners, vehicle_class, valid_lap_numbers, curvature_profile=None, mrp_events=None) -> dict[lap_str, dict[corner_str, label|None]]`. `user_corners`/each corner needs keys `corner_index`, `s_entry`, `s_apex`, `s_exit`. Returns per-lap per-corner LABEL strings from its own vocabulary: `entry_understeer, entry_oversteer, insufficient_trail_brake, excessive_trail_brake, low_min_speed, early_apex, late_apex, mid_corner_understeer, mid_corner_oversteer, coast_hesitation, exit_understeer, exit_oversteer, early_throttle, late_rotation, late_throttle, throttle_lift, good, slow_exit, scrappy`. Causal roots via `_CAUSAL_PARENT` (e.g. `exit_understeer → early_throttle`). `_SAFETY_LABELS = {exit_oversteer, entry_oversteer}`. The `Candidate` dataclass is `{label, priority, phase}` — NO confidence today. Under/oversteer labels derive from `_compute_yaw_residual`, which assumes uniform curvature (low reliability) when `curvature_profile is None`.
- Orchestrator: auto-detected `corners` exist (`~:346/514-522`, from `run_corner_detection`); `curvature_profile` is computed at `~:888` and stored in `summary["curvature_profile"]`. The classifier is currently called ONLY inside `if user_corner_rows:` (`~:1264-1279`), writing the dead `summary["corner_labels"]`.
- `coaching/composers/corner_composer.py::compose_corner_coaching(corner_perf, trail_brake, traction, exit_cascade, symptoms, throttle_lifts, weight_transfer, taxonomy, vehicle_class, driver_history=None)` → `CornerCoachingDetail`; internally `_resolve_cause(corner_perf, symptoms, trail_brake, throttle_lifts, taxonomy) -> (cause_id, delta)`. The symptom→cause pattern to mirror is `_SYMPTOM_TO_CAUSE` (corner_composer.py:19).
- Persistence: `tasks/pipeline_tasks.py::_build_analysis_blob` (PG) + `web/routes/sessions_v2.py` (desktop) build `analysis_json` from `summary`.

---

### Task 1: Add per-label confidence to `classify_all_corners`

Attach a confidence to every emitted label so downstream can honesty-gate yaw-based (under/oversteer) labels. Confidence is `"high" | "low"`: **low** when the label is a yaw-residual label (entry/mid/exit under/oversteer) AND (`curvature_profile is None` OR the lap's tier lacks a reliable yaw channel); **high** otherwise. This is the foundation for the whole phase — do it first so the return shape is set.

**Files:**
- Modify: `telemetry_tool/coaching/corner_diagnosis.py` (`classify_all_corners` return; `Candidate` gets a `confidence` field OR compute confidence at resolution in `_resolve_and_pick`)
- Test: `telemetry_tool/tests/coaching/test_corner_diagnosis_confidence.py`

**Interfaces:**
- Produces: `classify_all_corners(...) -> dict[lap_str, dict[corner_str, {"label": str|None, "confidence": "high"|"low"}]]`. (Return each corner's value as a small dict, not a bare string — update the docstring.) Define module-level `_YAW_RESIDUAL_LABELS = frozenset({entry_understeer, entry_oversteer, mid_corner_understeer, mid_corner_oversteer, exit_understeer, exit_oversteer})`.

- [ ] **Step 1: Write the failing test** — a yaw-based label with `curvature_profile=None` is `low`; a non-yaw label (e.g. `early_throttle`) is `high`; and with a real curvature profile a yaw label is `high`.

```python
# telemetry_tool/tests/coaching/test_corner_diagnosis_confidence.py
import pandas as pd
from coaching.corner_diagnosis import classify_all_corners, _YAW_RESIDUAL_LABELS

def _hot_entry_lap():
    # reuse the synthetic lap the existing test_corner_diagnosis.py builds for a
    # dominant entry-phase call; read that test for the real builder and mirror it.
    ...

def test_yaw_label_low_confidence_without_curvature():
    laps, corners = _hot_entry_lap()  # produces an under/oversteer-eligible corner
    out = classify_all_corners(laps, None, corners, "kart", [1], curvature_profile=None)
    cell = out["1"]["1"]
    assert isinstance(cell, dict) and "label" in cell and "confidence" in cell
    if cell["label"] in _YAW_RESIDUAL_LABELS:
        assert cell["confidence"] == "low"

def test_non_yaw_label_is_high_confidence():
    # a corner whose dominant label is a non-yaw cause (e.g. early_throttle / low_min_speed)
    ...
    assert cell["confidence"] == "high"
```
(Read the REAL `tests/coaching/test_corner_diagnosis.py` for the exact synthetic-lap builders and reuse them; the essential asserts are the confidence rule above.)

- [ ] **Step 2: Run test to verify it fails** — `python -m pytest tests/coaching/test_corner_diagnosis_confidence.py -q -p no:randomly` → FAIL (values are bare strings, no `confidence`).

- [ ] **Step 3: Implement** — add `_YAW_RESIDUAL_LABELS`; in `classify_all_corners`, replace the bare-string cell with `{"label": lbl, "confidence": conf}` where `conf = "low" if (lbl in _YAW_RESIDUAL_LABELS and (curvature_profile is None or not _tier_has_reliable_yaw(tier))) else "high"`. Add `_tier_has_reliable_yaw(tier) -> bool` (read `_detect_tier`; a tier without a usable yaw/gyro channel returns False). Update the docstring. NOTE: the orchestrator consumer (`S10h_corner_labels`) and the `corner_labels` write now receive dicts — Task 4 handles persistence; for THIS task just ensure no in-repo caller crashes on the new shape (grep `corner_labels` readers — Phase 1 confirmed none read it meaningfully; the orchestrator only stores it).

- [ ] **Step 4: Run test to verify it passes** — the confidence test + `python -m pytest tests/coaching/test_corner_diagnosis.py -q -p no:randomly` (the existing 43 must stay green; adapt ONLY assertions that read the bare-string shape, to `["label"]`).

- [ ] **Step 5: Commit** — `git add telemetry_tool/coaching/corner_diagnosis.py telemetry_tool/tests/coaching/test_corner_diagnosis_confidence.py` (+ any adapted existing test) → `git commit -m "feat(coaching): per-label confidence in classify_all_corners (yaw-residual honesty gate)"`.

---

### Task 2: Run the classifier on every session's auto-detected corners + real curvature

Decouple the classifier from operator-drawn `user_corners`: run it on the auto-detected `corners` on every session, passing the real `curvature_profile`. This is what makes diagnosis available for all customers.

**Files:**
- Modify: `telemetry_tool/pipeline/orchestrator.py` (near the existing `if user_corner_rows:` block ~`:1264-1279`)
- Test: `telemetry_tool/tests/coaching/test_diagnosis_runs_auto.py`

**Interfaces:**
- Consumes: `classify_all_corners(..., curvature_profile=...)` (Task 1's shape). Produces: `summary["corner_diagnosis"]` = the per-lap/per-corner `{label, confidence}` map, computed from the auto-detected `corners` + `summary["curvature_profile"]`, for every session (not gated on `user_corner_rows`).

- [ ] **Step 1: Write the failing test** — call the orchestrator helper (or a small extracted function `_run_corner_diagnosis(corners, resampled_laps, curvature_profile, theoretical_lap, vehicle_class, valid_laps)`) with auto-corners + a curvature profile and assert `summary["corner_diagnosis"]` is populated with `{label,confidence}` cells. If the orchestrator logic is inline+hard to unit-test, EXTRACT it into a testable pure function in a new `pipeline/stages/s10h_diagnosis.py` and test that.

```python
# telemetry_tool/tests/coaching/test_diagnosis_runs_auto.py
# Build minimal auto-corners (dicts with corner_index/s_entry/s_apex/s_exit) + a resampled lap,
# call the extracted _run_corner_diagnosis(...), assert the returned map has {label,confidence}
# for the corner and that it ran WITHOUT requiring user_corners.
```

- [ ] **Step 2: Run test to verify it fails** — the function/key doesn't exist yet.

- [ ] **Step 3: Implement** — verify the auto-detected `corners` dicts carry `corner_index/s_entry/s_apex/s_exit` (grep `run_corner_detection` output; if the key names differ, adapt a thin shim mapping auto-corner → the classifier's expected keys — do NOT change the classifier's contract). Extract `_run_corner_diagnosis(...)` (in `s10h_diagnosis.py`) that calls `classify_all_corners(resampled_laps, theoretical_lap, corners, vehicle_class, valid_lap_numbers, curvature_profile=summary["curvature_profile"])`. Wire it into the orchestrator to ALWAYS run (keep the user-corner path if it adds value, but the auto path runs unconditionally when `corners` exist), writing `summary["corner_diagnosis"]`. Pass the REAL `summary["curvature_profile"]` (the whole point of the honesty gate).

- [ ] **Step 4: Run test to verify it passes** — the new test + `python -m pytest tests/coaching/ -q -p no:randomly` (green).

- [ ] **Step 5: Commit** — `fix(coaching): run corner_diagnosis on every session's auto corners with real curvature profile`.

---

### Task 3: Map diagnosis labels → coaching cause ids (guard-enforced)

The classifier's vocabulary (`entry_understeer`, `early_throttle`, …) differs from the taxonomy/drill cause ids. Build the mapping so a diagnosis can drive drill selection, and extend the Phase-1 vocabulary guard so every mapped id is real.

**Files:**
- Create: `telemetry_tool/coaching/diagnosis_cause_map.py` (`DIAGNOSIS_LABEL_TO_CAUSE: dict[str, str]`)
- Modify: `telemetry_tool/coaching/vocabulary_check.py` (fold the mapped ids into the integrity check)
- Test: `telemetry_tool/tests/test_diagnosis_cause_map.py`

**Interfaces:**
- Produces: `DIAGNOSIS_LABEL_TO_CAUSE` mapping each RESOLVED-root diagnosis label (apply `_CAUSAL_PARENT` first) to a taxonomy cause id that exists in BOTH `causes.json` AND some drill's `applicable_causes`.

- [ ] **Step 1: Write the failing test**

```python
# telemetry_tool/tests/test_diagnosis_cause_map.py
from coaching.diagnosis_cause_map import DIAGNOSIS_LABEL_TO_CAUSE
from coaching.taxonomy.causes import CauseTaxonomy
from coaching.templates.drills import DRILL_LIBRARY

def _drill_causes():
    s=set()
    for d in DRILL_LIBRARY.values(): s.update(d.get("applicable_causes", []))
    return s

def test_every_mapped_cause_is_real():
    tax, drills = CauseTaxonomy(), _drill_causes()
    for label, cause in DIAGNOSIS_LABEL_TO_CAUSE.items():
        assert tax.get_cause(cause) is not None, f"{label}->{cause} not in taxonomy"
        assert cause in drills, f"{label}->{cause} not in DRILL_LIBRARY"

def test_all_non_good_diagnosis_labels_are_mapped():
    # every diagnosis label a customer could see (excluding good/None) must map,
    # so a real diagnosis never falls through to Unknown.
    from coaching import corner_diagnosis as cd
    emittable = {cd.EARLY_THROTTLE, cd.LATE_THROTTLE, cd.LOW_MIN_SPEED, cd.EARLY_APEX,
                 cd.LATE_APEX, cd.ENTRY_UNDERSTEER, cd.EXIT_UNDERSTEER, cd.MID_CORNER_UNDERSTEER,
                 cd.INSUFFICIENT_TRAIL_BRAKE, cd.COAST_HESITATION, cd.SLOW_EXIT, cd.LATE_ROTATION,
                 cd.ENTRY_OVERSTEER, cd.EXIT_OVERSTEER, cd.MID_CORNER_OVERSTEER, cd.EXCESSIVE_TRAIL_BRAKE}
    # (after applying _CAUSAL_PARENT the set may shrink; assert each RESOLVED label is mapped)
    for lbl in emittable:
        root = cd._CAUSAL_PARENT.get(lbl, lbl)
        assert root in DIAGNOSIS_LABEL_TO_CAUSE, f"unmapped diagnosis root {root}"
```

- [ ] **Step 2: Run test to verify it fails** — module missing.

- [ ] **Step 3: Implement** — read `coaching/taxonomy/causes.json` (the 26 ids) + `DRILL_LIBRARY.applicable_causes` + the `corner_diagnosis` label list, and author `DIAGNOSIS_LABEL_TO_CAUSE` mapping each resolved-root diagnosis label to the closest real taxonomy cause id (e.g. `early_throttle → <taxonomy exit-traction/early-throttle cause>`, `low_min_speed → mid_corner_speed_loss`, `entry_understeer → <taxonomy entry-understeer cause>`). Every value MUST pass the two asserts (real id in taxonomy ∩ drills) — pick the semantically-closest EXISTING id; do NOT invent ids and do NOT add new taxonomy/drill entries unless a genuine coverage gap exists (if one does, add the label to an existing drill's `applicable_causes`, mirroring Phase-1 Task 2, and note it). Then extend `vocabulary_check.assert_cause_vocabulary_integrity()` to also assert every value of `DIAGNOSIS_LABEL_TO_CAUSE` is in taxonomy ∩ drills.

- [ ] **Step 4: Run test to verify it passes** — the map test + `python -m pytest tests/test_cause_vocabulary.py -q -p no:randomly` (the extended guard stays green).

- [ ] **Step 5: Commit** — `feat(coaching): diagnosis-label -> taxonomy-cause map (guard-enforced)`.

---

### Task 4: Persist the per-corner diagnosis into `analysis_json`

So the composer (Task 5) and consumers can read a session's diagnosis. Replace the dead `summary["corner_labels"]` write with a persisted `corner_diagnosis`.

**Files:**
- Modify: `telemetry_tool/tasks/pipeline_tasks.py` (`_build_analysis_blob`) + `telemetry_tool/web/routes/sessions_v2.py` (desktop blob) — write `summary["corner_diagnosis"]` into `analysis_json["corner_diagnosis"]`
- Test: `telemetry_tool/tests/coaching/test_diagnosis_persisted.py`

**Interfaces:**
- Produces: `analysis_json["corner_diagnosis"]` = the `{lap:{corner:{label,confidence}}}` map (session-aggregated as the builders do for other coaching keys).

- [ ] **Step 1: Write the failing test** — feed a `summary` containing `corner_diagnosis` to `_build_analysis_blob` and assert the blob carries `corner_diagnosis`. Mirror how the existing test asserts `coaching_v3` persistence (read `tests/coaching/test_pipeline_integration.py`).
- [ ] **Step 2: FAIL** (key not written).
- [ ] **Step 3: Implement** — in both blob builders, add `cd = summary.get("corner_diagnosis"); if cd: blob["corner_diagnosis"] = cd` alongside the existing `coaching_v3` handling (grep for `coaching_v3` in each builder and add adjacent). Confirm it's the session-appropriate aggregation.
- [ ] **Step 4: PASS** + `python -m pytest tests/coaching/ -q -p no:randomly`.
- [ ] **Step 5: Commit** — `feat(coaching): persist per-corner diagnosis into analysis_json`.

---

### Task 5: Route `compose_corner_coaching` through the diagnosis (confidence-gated real detection)

The payoff: the diagnosed root cause drives drill selection, replacing `symptom_detector` as the primary. Low-confidence yaw labels do NOT drive the cause (fall through to the metric-based branches / soften), honoring the honesty gate.

**Files:**
- Modify: `telemetry_tool/coaching/composers/corner_composer.py` (`compose_corner_coaching` gains a `diagnosis` param; `_resolve_cause` gets a new highest-priority branch)
- Modify: `telemetry_tool/coaching/composers/session_composer.py` (thread the corner's diagnosis into `compose_corner_coaching`)
- Test: `telemetry_tool/tests/coaching/test_composer_diagnosis_routing.py`

**Interfaces:**
- Consumes: `DIAGNOSIS_LABEL_TO_CAUSE` (Task 3), the persisted/`summary` `corner_diagnosis` (Tasks 2/4). Produces: `compose_corner_coaching(..., diagnosis: dict | None = None)` where `diagnosis = {"label": str, "confidence": "high"|"low"}` for that corner; when `diagnosis` is present with `confidence=="high"` and its resolved label maps to a cause, THAT cause wins (highest priority in `_resolve_cause`).

- [ ] **Step 1: Write the failing test**

```python
# telemetry_tool/tests/coaching/test_composer_diagnosis_routing.py
from coaching.composers.corner_composer import _resolve_cause
from coaching.taxonomy.causes import CauseTaxonomy
from coaching.diagnosis_cause_map import DIAGNOSIS_LABEL_TO_CAUSE

def test_high_confidence_diagnosis_drives_cause():
    tax = CauseTaxonomy()
    diag = {"label": "early_throttle", "confidence": "high"}
    cause, _ = _resolve_cause({"corner_id":1}, symptoms=None, trail_brake=None,
                              throttle_lifts=[], taxonomy=tax, diagnosis=diag)
    assert cause == DIAGNOSIS_LABEL_TO_CAUSE["early_throttle"]

def test_low_confidence_diagnosis_does_not_drive_cause():
    tax = CauseTaxonomy()
    diag = {"label": "exit_oversteer", "confidence": "low"}  # yaw label, unreliable
    cause, _ = _resolve_cause({"corner_id":1, "time_loss_apex_speed_s":0.3}, symptoms=None,
                              trail_brake=None, throttle_lifts=[], taxonomy=tax, diagnosis=diag)
    assert cause != DIAGNOSIS_LABEL_TO_CAUSE.get("exit_oversteer")  # fell through to metric branch
```

- [ ] **Step 2: FAIL** (`_resolve_cause` has no `diagnosis` param).
- [ ] **Step 3: Implement** — add `diagnosis: dict | None = None` to `_resolve_cause` (and thread it from `compose_corner_coaching` ← `compose_session_coaching`, which reads the corner's cell from the `corner_diagnosis` map by corner id + best lap). New BRANCH 0 at the top of `_resolve_cause`: if `diagnosis` present, `confidence=="high"`, and `DIAGNOSIS_LABEL_TO_CAUSE.get(_CAUSAL_PARENT-resolved label)` yields a taxonomy cause → return `(that_cause, delta)` (delta from the corner_perf loss for that phase, else a moderate default). Low-confidence or unmapped → do nothing, fall through to the existing symptom/metric branches (Phase-1 behavior preserved). `symptom_detector` stays as a fallback, no longer the primary. Add any new emittable cause ids to `RESOLVABLE_CAUSE_IDS` (guard test enforces).
- [ ] **Step 4: PASS** + `python -m pytest tests/coaching/ tests/test_cause_vocabulary.py tests/test_coaching_no_placeholders.py -q -p no:randomly` (green).
- [ ] **Step 5: Commit** — `feat(coaching): route drill selection through corner_diagnosis (confidence-gated real detection)`.

---

### Task 6: End-to-end acceptance on real + synthetic data

Prove the phase goal: a real corner gets a diagnosis-driven drill, and the honesty gate holds on the corrupt-yaw kart.

**Files:**
- Test: `telemetry_tool/tests/coaching/test_phase2_acceptance.py`

- [ ] **Step 1: Write the test** — (a) SYNTHETIC good-yaw: build a lap with a clear known mistake (e.g. early-throttle exit) + a real curvature profile, run classify→map→compose, assert the corner's drill corresponds to `DIAGNOSIS_LABEL_TO_CAUSE["early_throttle"]` and confidence is `high`. (b) HONESTY: same corner but `curvature_profile=None` (or a corrupt-yaw tier) → the under/oversteer label is `low` confidence and does NOT drive an oversteer drill (falls through). Reuse the synthetic builders from `tests/coaching/test_corner_diagnosis.py`.
- [ ] **Step 2: Run** `python -m pytest tests/coaching/test_phase2_acceptance.py -q -p no:randomly` → iterate until PASS.
- [ ] **Step 3: Commit** — `test(coaching): phase-2 acceptance — diagnosis-driven drill + honesty gate`.

- [ ] **Final:** run `python -m pytest tests/coaching/ tests/test_cause_vocabulary.py tests/test_coaching_no_placeholders.py tests/test_coaching_engine_tag.py tests/test_diagnosis_cause_map.py -q -p no:randomly` (all green), then whole-branch review, then Phase 3 planning. Optionally re-run `main.py` on SLK_FP2 and confirm corners now carry diagnosis labels + drills, with oversteer withheld (corrupt yaw).
