# Coaching Phase 1 — Repair & Unify — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make LAP's existing deep coaching subsystem produce *correct* output that reaches customers — fix the 3 blocker delivery bugs, the placeholder leaks, add a fail-loud vocabulary guard, and unify the payload — so a real session yields named root causes + real drills + a filled narrative instead of "Unknown cause / 0.0% / {primary_strength}".

**Architecture:** Pure repair on the already-wired v3 coaching chain (`pipeline/stages/s13_coaching_v3.py` → `coaching/composers/*` → `analysis_json` → the 3 live endpoints). No new subsystems, no schema changes. Each task is a pinpointed fix + a regression test that reproduces the bug first.

**Tech Stack:** Python 3.14 (system, no venv), pytest 9. Backend package `telemetry_tool/`. Run pytest from `telemetry_tool/`.

## Global Constraints

- Branch-only, deploy-gated. Work on `feat/adaptive-coaching` (worktree `C:/Users/Admin/lap_web-wt-coaching`). NEVER `git add -A` (AV quarantines deletions — stage files by explicit path).
- Reuse the existing taxonomy (`coaching/taxonomy/causes.json`, 26 causes) + `DRILL_LIBRARY` (`coaching/templates/drills.py`) + `CORNER_TIPS`. Do NOT re-author the vocabulary.
- No fabrication: a customer-facing number must trace to real telemetry or be explicitly marked insufficient/low-confidence. Never emit a hardcoded `0.0` as if measured.
- Kart-first, car-safe: keep the existing vehicle-class thresholds intact.
- Tests must run BOTH under pytest AND in `main.py`'s script-mode sys.path (Task 1 exists because pytest's path masks a prod-only crash).
- Run pytest from `telemetry_tool/`: `python -m pytest tests/<file> -q -p no:randomly`.
- Spec anchor: `docs/superpowers/specs/2026-07-23-adaptive-coaching-drill-detection-design.md` §4.

---

### Task 1: Fix the import-prefix crash + a script-mode guard test

The canonical coaching stage imports `from telemetry_tool.coaching…` (10 occurrences), but `main.py`'s sys.path only supports the bare `from coaching…` prefix that every sibling stage uses. Result: `ModuleNotFoundError: No module named 'telemetry_tool'` on the real CLI entrypoint → the stage silently falls back to near-empty v2. The pytest suite's different sys.path masks it, so the guard test must reproduce `main.py`'s path.

**Files:**
- Modify: `telemetry_tool/pipeline/stages/s13_coaching_v3.py` (all `from telemetry_tool.coaching…` imports, e.g. `:32-37`, `:172-173`)
- Test: `telemetry_tool/tests/test_s13_import_scriptmode.py`

**Interfaces:**
- Produces: `s13_coaching_v3.run_analyzers(...)` and `run_enhanced_coaching(...)` importable + runnable under `main.py`'s sys.path (telemetry_tool dir on path, NOT its parent).

- [ ] **Step 1: Write the failing test** — reproduce `main.py`'s sys.path in a subprocess and import the stage the way it imports its analyzers.

```python
# telemetry_tool/tests/test_s13_import_scriptmode.py
import subprocess, sys
from pathlib import Path

TT_DIR = Path(__file__).resolve().parents[1]  # the telemetry_tool/ dir (== main.py's dir)

def test_coaching_stage_imports_under_scriptmode_syspath():
    """main.py puts telemetry_tool/ (not its parent) on sys.path. The coaching
    stage MUST import cleanly under that path — a `from telemetry_tool.coaching`
    import raises ModuleNotFoundError there and silently degrades to v2."""
    code = (
        "import importlib;"
        "m = importlib.import_module('pipeline.stages.s13_coaching_v3');"
        # force-evaluate the in-function imports the stage performs:
        "m.run_analyzers.__wrapped__ if hasattr(m.run_analyzers,'__wrapped__') else None;"
        "import coaching.analyzers.trail_brake, coaching.composers.session_composer;"
        "print('OK')"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=str(TT_DIR),
                       capture_output=True, text=True)
    assert "ModuleNotFoundError" not in r.stderr, r.stderr
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_s13_import_scriptmode.py -q -p no:randomly`
Expected: FAIL — the subprocess stderr contains `ModuleNotFoundError: No module named 'telemetry_tool'` (from the stage's `from telemetry_tool.coaching…` imports). (The import of `coaching.analyzers…` in the test body itself succeeds; the failure is the stage module's own imports when its functions run — if the module-level import already fails, the assert on returncode catches it.)

- [ ] **Step 3: Fix the imports** — change every `from telemetry_tool.coaching…` to `from coaching…` in `s13_coaching_v3.py`. Concretely, replace the prefix `from telemetry_tool.coaching` → `from coaching` on all 10 occurrences (analyzer imports ~`:32-37`, composer + taxonomy imports in `run_enhanced_coaching` ~`:172-173`). Verify none remain:

```bash
grep -n "from telemetry_tool\." telemetry_tool/pipeline/stages/s13_coaching_v3.py   # expect: no output
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_s13_import_scriptmode.py -q -p no:randomly`
Expected: PASS ("OK", returncode 0, no ModuleNotFoundError). Also run the existing suite to confirm no regression: `python -m pytest tests/test_coaching_v3.py -q -p no:randomly` (expect still green).

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/pipeline/stages/s13_coaching_v3.py telemetry_tool/tests/test_s13_import_scriptmode.py
git commit -m "fix(coaching): s13 import prefix crash on CLI entrypoint + script-mode guard test"
```

---

### Task 2: Vocabulary integrity — fail loud + fix `low_apex_speed`

`_resolve_cause` emits cause id `low_apex_speed` in two places (the phase map and the final fallback), but that id exists in NEITHER the taxonomy (real id `mid_corner_speed_loss`) NOR `DRILL_LIBRARY` → every corner that hits those branches collapses to "Unknown cause" + a generic drill. Fix the id, and add a boot-time assertion so any future vocabulary drift fails loudly instead of silently degrading every corner.

**Files:**
- Modify: `telemetry_tool/coaching/composers/corner_composer.py` (`_resolve_cause`: the `phases` dict `"time_loss_apex_speed_s": "low_apex_speed"` and the final `return "low_apex_speed", …`)
- Create: `telemetry_tool/coaching/vocabulary_check.py` (a pure `assert_cause_vocabulary_integrity()` helper + the canonical set of ids `_resolve_cause` can emit)
- Test: `telemetry_tool/tests/test_cause_vocabulary.py`

**Interfaces:**
- Produces: `vocabulary_check.RESOLVABLE_CAUSE_IDS: frozenset[str]` (every cause id `_resolve_cause` can return) and `assert_cause_vocabulary_integrity() -> None` (raises `ValueError` if any resolvable id is missing from the taxonomy or from every drill's `applicable_causes`).

- [ ] **Step 1: Write the failing test**

```python
# telemetry_tool/tests/test_cause_vocabulary.py
import pytest
from coaching.vocabulary_check import RESOLVABLE_CAUSE_IDS, assert_cause_vocabulary_integrity
from coaching.taxonomy.causes import CauseTaxonomy
from coaching.templates.drills import DRILL_LIBRARY

def _drill_causes() -> set[str]:
    out: set[str] = set()
    for d in DRILL_LIBRARY.values():
        out.update(d.get("applicable_causes", []))
    return out

def test_every_resolvable_cause_is_in_taxonomy_and_drills():
    tax = CauseTaxonomy()
    drill_causes = _drill_causes()
    for cid in RESOLVABLE_CAUSE_IDS:
        assert tax.get_cause(cid) is not None, f"{cid} missing from taxonomy"
        assert cid in drill_causes, f"{cid} missing from DRILL_LIBRARY.applicable_causes"

def test_integrity_assertion_passes():
    assert_cause_vocabulary_integrity()  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cause_vocabulary.py -q -p no:randomly`
Expected: FAIL — either `coaching.vocabulary_check` doesn't exist yet (import error) or, once stubbed with the real emitted-id set, `low_apex_speed` fails the taxonomy/drill membership assert.

- [ ] **Step 3: Fix + implement.** (a) In `corner_composer.py::_resolve_cause`, change both `low_apex_speed` occurrences to `mid_corner_speed_loss`. (b) Create `vocabulary_check.py`:

```python
# telemetry_tool/coaching/vocabulary_check.py
"""Fail-loud guard: every cause id _resolve_cause can emit must exist in BOTH
the taxonomy and DRILL_LIBRARY, so vocabulary drift can never silently collapse
every corner to 'Unknown cause'."""
from __future__ import annotations

# The full set of cause ids corner_composer._resolve_cause can return.
# Keep in sync with _resolve_cause; the integrity test enforces membership.
RESOLVABLE_CAUSE_IDS = frozenset({
    "early_braking_confidence", "late_braking_aggressive", "no_trail_braking",
    "mid_corner_lift", "insufficient_brake_pressure", "mid_corner_speed_loss",
    "late_throttle_application",
})

def assert_cause_vocabulary_integrity() -> None:
    from coaching.taxonomy.causes import CauseTaxonomy
    from coaching.templates.drills import DRILL_LIBRARY
    tax = CauseTaxonomy()
    drill_causes: set[str] = set()
    for d in DRILL_LIBRARY.values():
        drill_causes.update(d.get("applicable_causes", []))
    missing = [
        cid for cid in RESOLVABLE_CAUSE_IDS
        if tax.get_cause(cid) is None or cid not in drill_causes
    ]
    if missing:
        raise ValueError(f"Cause vocabulary drift — ids not in taxonomy∩drills: {sorted(missing)}")
```

Then invoke it at coaching-stage import so prod fails loudly: add `from coaching.vocabulary_check import assert_cause_vocabulary_integrity; assert_cause_vocabulary_integrity()` at the bottom of `coaching/composers/corner_composer.py` module import (or call it once in `run_enhanced_coaching`). NOTE: if the symptom path (`_SYMPTOM_TO_CAUSE`) can emit ids outside `RESOLVABLE_CAUSE_IDS`, add those ids to the set — the test will tell you (extend the set until the taxonomy/drill asserts pass with the REAL ids, never by removing the check).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cause_vocabulary.py -q -p no:randomly`
Expected: PASS. Smoke: `python -m pytest tests/test_coaching_v3.py -q -p no:randomly` (still green).

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/coaching/composers/corner_composer.py telemetry_tool/coaching/vocabulary_check.py telemetry_tool/tests/test_cause_vocabulary.py
git commit -m "fix(coaching): low_apex_speed->mid_corner_speed_loss + fail-loud vocabulary integrity guard"
```

---

### Task 3: Kill placeholder leaks — real narrative + real magnitudes

Customers see literal `{primary_strength}` (the narrative is never `.format`ed) and "0.0% below optimal" (`_build_placeholders` hardcodes magnitudes to 0.0). Fill both from real values, and add a payload-level guard so no unrendered token or fake `0.0%` can ever ship again.

**Files:**
- Modify: `telemetry_tool/coaching/composers/session_composer.py` (`_pick_narrative` ~`:306` — `.format_map` the returned narrative; and its caller must pass the real substitution values)
- Modify: `telemetry_tool/coaching/composers/corner_composer.py` (`_build_placeholders` ~`:189-222` — populate from the real analyzer outputs already available, not `0.0`)
- Test: `telemetry_tool/tests/test_coaching_no_placeholders.py`

**Interfaces:**
- Consumes: `compose_session_coaching(corner_perfs, coaching_v2, scores, lap_metrics, driving_style, analyzer_results, taxonomy, vehicle_class, driver_history, previous_goals)` (from `session_composer`) — same signature the orchestrator calls.
- Produces: a coaching payload dict whose serialized form contains no `{…}` template token and no literal `"0.0%"`.

- [ ] **Step 1: Write the failing test** — build a realistic composer input (reuse an existing fixture from `tests/test_coaching_v3.py`; if none, construct minimal `corner_perfs` with non-zero `time_loss_*` + a symptom) and assert the rendered payload is clean.

```python
# telemetry_tool/tests/test_coaching_no_placeholders.py
import json, re
from coaching.composers.session_composer import compose_session_coaching
from coaching.taxonomy.causes import CauseTaxonomy
# Reuse the fixture builder from the existing v3 test if present:
from tests.test_coaching_v3 import make_corner_perfs, make_scores  # adjust to real fixture names

def test_payload_has_no_unrendered_placeholders_or_fake_zero_pct():
    result = compose_session_coaching(
        corner_perfs=make_corner_perfs(), coaching_v2={}, scores=make_scores(),
        lap_metrics=[], driving_style={}, analyzer_results={},
        taxonomy=CauseTaxonomy(), vehicle_class="kart",
        driver_history=None, previous_goals=None,
    )
    blob = json.dumps(result.to_dict())
    assert not re.search(r"\{[a-z_]+\}", blob), f"unrendered token in payload: {blob[:400]}"
    assert "0.0%" not in blob, "fabricated 0.0% magnitude leaked to payload"
    assert "Unknown cause" not in blob
```

(If `tests/test_coaching_v3.py` exposes different fixture helpers, use those; the point is a realistic `corner_perfs`/`scores` input.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_coaching_no_placeholders.py -q -p no:randomly`
Expected: FAIL — the payload contains `{primary_strength}`/`{corner_count}` and/or `0.0%`.

- [ ] **Step 3: Fix both sites.** (a) `_pick_narrative`: after selecting the narrative variant, render it — `return theme, narrative.format_map(_SafeDict(subs))` where `subs` is a dict of the real values (`primary_strength`, `primary_weakness`, `corner_count`, …) assembled from `focus_areas`/`scores`, and `_SafeDict(dict)` subclasses `dict` with `__missing__ = lambda self,k: "—"` so an unexpected token degrades to an em-dash rather than crashing or leaking. Thread the real `subs` from the caller. (b) `_build_placeholders`: replace each hardcoded `0.0` (`pct_increase`, `throttle_drop_pct`, `lift_duration_s`, `weight_shift_kg`, `yaw_spike`) with the corresponding value read from the passed analyzer outputs (`exit_cascade`, symptom evidence, etc.); when a value is genuinely unavailable, omit the token / use the insufficient-data phrasing rather than `0.0` (per the no-fabrication constraint).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_coaching_no_placeholders.py -q -p no:randomly`
Expected: PASS. Smoke: `python -m pytest tests/test_coaching_v3.py -q -p no:randomly`.

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/coaching/composers/session_composer.py telemetry_tool/coaching/composers/corner_composer.py telemetry_tool/tests/test_coaching_no_placeholders.py
git commit -m "fix(coaching): render narrative + real magnitudes; guard against placeholder/0.0% leaks"
```

---

### Task 4: Honest engine tagging + remove the no-op persist step

When the enhanced path falls back it returns the v2 payload, which the orchestrator stores under the `coaching_v3` key — consumers can't tell which engine produced the content. Tag the payload with its engine. Also remove `13g2_persist_coaching`, a no-op (called with an always-`{}` `_analysis_json_blob` and `conn=None`; real persistence already happens in `_build_analysis_blob`).

**Files:**
- Modify: `telemetry_tool/pipeline/stages/s13_coaching_v3.py` (`run_enhanced_coaching` — tag the returned dict; `persist_coaching_v3` — remove or leave unused)
- Modify: `telemetry_tool/pipeline/orchestrator.py` (`~:1526-1530` — drop the `13g2_persist_coaching` `_safe_step` call)
- Test: `telemetry_tool/tests/test_coaching_engine_tag.py`

**Interfaces:**
- Produces: `run_enhanced_coaching(...)` returns a dict carrying `"engine": "v3"` on the enhanced path and `"engine": "v2_fallback"` when it falls back (never a silently mislabeled v2).

- [ ] **Step 1: Write the failing test**

```python
# telemetry_tool/tests/test_coaching_engine_tag.py
from pipeline.stages import s13_coaching_v3 as s13

def test_success_path_tagged_v3(monkeypatch):
    # a valid-enough input yields the enhanced payload
    out = s13.run_enhanced_coaching(
        corner_perfs=[{"corner_id": 1, "time_loss_apex_speed_s": 0.3}],
        coaching_v2={"summary": "v2"}, scores={"grade": "B"}, lap_metrics=[],
        driving_style={}, analyzer_bundle={}, driver_history=None,
        vehicle_class="kart", previous_goals=None)
    assert out.get("engine") == "v3"

def test_fallback_is_tagged_not_silent(monkeypatch):
    # empty corner_perfs forces the early v2 fallback
    out = s13.run_enhanced_coaching(
        corner_perfs=[], coaching_v2={"summary": "v2"}, scores={}, lap_metrics=[],
        driving_style={}, analyzer_bundle={}, driver_history=None,
        vehicle_class="kart", previous_goals=None)
    assert out.get("engine") == "v2_fallback"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_coaching_engine_tag.py -q -p no:randomly`
Expected: FAIL — `engine` key absent (fallback returns bare `coaching_v2`; success returns `result.to_dict()` without the tag).

- [ ] **Step 3: Implement.** In `run_enhanced_coaching`: the two fallback returns become `return {**coaching_v2, "engine": "v2_fallback"}`; the success return becomes `d = result.to_dict(); d["engine"] = "v3"; return d`. In `orchestrator.py`, delete the `_safe_step("13g2_persist_coaching", …)` block (the no-op) and, if `persist_coaching_v3` now has no callers, remove it from `s13_coaching_v3.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_coaching_engine_tag.py -q -p no:randomly`
Expected: PASS. Smoke: `python -m pytest tests/test_coaching_v3.py -q -p no:randomly`.

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/pipeline/stages/s13_coaching_v3.py telemetry_tool/pipeline/orchestrator.py telemetry_tool/tests/test_coaching_engine_tag.py
git commit -m "fix(coaching): tag coaching payload engine (v3 vs v2_fallback); drop no-op persist step"
```

---

### Task 5: Unify the coaching type systems on `coaching/models.py`

`coaching_engine.py` defines its OWN `FocusArea/Drill/SessionCoaching` dataclasses that collide by name with `coaching/models.py` but have incompatible shapes — two payload contracts under one name. `coaching_engine` is the fallback behind `GET /sessions/<id>/coaching` (`data_v2.py:7050`). Converge on ONE contract so downstream consumers see a single shape.

**Files:**
- Modify: `telemetry_tool/coaching_engine.py` (its `FocusArea/Drill/SessionCoaching` definitions + `to_dict`)
- Read (do not break): `telemetry_tool/web/routes/data_v2.py:7050` (the fallback caller), `telemetry_tool/coaching/models.py` (canonical), `telemetry_tool/tests/test_coaching_engine.py`
- Test: `telemetry_tool/tests/test_coaching_payload_shape.py`

**Interfaces:**
- Produces: `coaching_engine.generate_session_coaching(...).to_dict()` emits a payload whose top-level keys match the v3 payload's shape (same drill/focus-area field names), so a consumer reading `/sessions/<id>/coaching` gets one contract regardless of which engine ran.

- [ ] **Step 1: Write the failing test** — assert the fallback payload and the v3 payload agree on the customer-facing keys.

```python
# telemetry_tool/tests/test_coaching_payload_shape.py
from coaching_engine import generate_session_coaching

DRILL_KEYS = {"rank", "title", "description", "focus_corners", "target_metric",
              "target_improvement", "lap_count"}

def test_fallback_drill_shape_matches_contract():
    # minimal real-ish corner input with a measurable loss
    result = generate_session_coaching(corners=[{
        "corner_index": 3, "avg_time_loss_s": 0.4, "category": "technique",
    }], lap_metrics=[])
    d = result.to_dict()
    assert "drills" in d and "focus_areas" in d
    if d["drills"]:
        assert DRILL_KEYS.issubset(set(d["drills"][0].keys()))
```

(Confirm the exact expected key set against `coaching/models.py`'s `Drill`/`to_dict`; align `coaching_engine`'s `Drill.to_dict` to it. If `coaching/models.py`'s `Drill` shape differs, THAT is the canonical target — adapt `coaching_engine` to it, not the reverse.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_coaching_payload_shape.py -q -p no:randomly`
Expected: FAIL — key mismatch between `coaching_engine`'s `Drill.to_dict` and the canonical `coaching/models.py` shape.

- [ ] **Step 3: Implement.** Make `coaching_engine.py` import the canonical dataclasses from `coaching/models.py` where the shapes are compatible, or align its `Drill.to_dict()`/`FocusArea.to_dict()`/`SessionCoaching.to_dict()` field names to the canonical contract. Do NOT change `data_v2.py:7050`'s call unless a field it reads moved — if so, update that read. Keep the existing `test_coaching_engine.py` green (adjust its assertions only if they encode the OLD divergent shape).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_coaching_payload_shape.py tests/test_coaching_engine.py -q -p no:randomly`
Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/coaching_engine.py telemetry_tool/tests/test_coaching_payload_shape.py
git commit -m "refactor(coaching): unify fallback payload contract on coaching/models.py shape"
```

---

### Task 6: Remove the phantom `debrief_engine` stage + decide the dead practice-plan endpoint

`debrief_engine` (pipeline step `13b_coaching_guide`) references a module that never existed — every run logs `WARNING Module debrief_engine unavailable` and `summary['coaching_guide']` is always `None`. And `GET /sessions/<id>/practice-plan` can never return data (`practice_plan` is never persisted). Both are dead. Remove the phantom stage; remove the permanently-404ing endpoint (YAGNI — nothing fetches it; if practice-plan is wanted it becomes a real Phase-2+ feature).

**Files:**
- Modify: `telemetry_tool/pipeline/stages/s13_scoring.py:144` (the `debrief_engine` import/reference) + the orchestrator step registration for `13b_coaching_guide`
- Modify: `telemetry_tool/web/routes/data_v2.py:6918-6937` (remove the `practice-plan` route)
- Test: `telemetry_tool/tests/test_no_phantom_coaching_stages.py`

**Interfaces:**
- Produces: no pipeline step attempts to import `debrief_engine`; no `practice-plan` route registered.

- [ ] **Step 1: Write the failing test**

```python
# telemetry_tool/tests/test_no_phantom_coaching_stages.py
import pathlib
TT = pathlib.Path(__file__).resolve().parents[1]

def test_no_debrief_engine_reference():
    src = (TT / "pipeline" / "stages" / "s13_scoring.py").read_text()
    assert "debrief_engine" not in src, "phantom debrief_engine reference still present"

def test_practice_plan_route_removed():
    src = (TT / "web" / "routes" / "data_v2.py").read_text()
    assert "/practice-plan" not in src, "dead practice-plan route still registered"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_no_phantom_coaching_stages.py -q -p no:randomly`
Expected: FAIL — both references still present.

- [ ] **Step 3: Implement.** Remove the `debrief_engine` import + the `13b_coaching_guide` step wiring from `s13_scoring.py`/orchestrator (leave `summary['coaching_guide']` unset or drop it). Remove the `@bp.route(".../practice-plan"…)` handler from `data_v2.py`. Verify nothing else reads `coaching_guide`/`practice_plan`: `grep -rnE "coaching_guide|practice_plan|practice-plan" telemetry_tool/ lap-website/src/` (expect only the removals).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_no_phantom_coaching_stages.py -q -p no:randomly`
Expected: PASS. Smoke the pipeline import: `python -m pytest tests/test_coaching_v3.py -q -p no:randomly`.

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/pipeline/stages/s13_scoring.py telemetry_tool/pipeline/orchestrator.py telemetry_tool/web/routes/data_v2.py telemetry_tool/tests/test_no_phantom_coaching_stages.py
git commit -m "chore(coaching): remove phantom debrief_engine stage + dead practice-plan endpoint"
```

---

## Final Phase-1 acceptance (run after all tasks)

- [ ] Run the full coaching test set: `python -m pytest tests/test_s13_import_scriptmode.py tests/test_cause_vocabulary.py tests/test_coaching_no_placeholders.py tests/test_coaching_engine_tag.py tests/test_coaching_payload_shape.py tests/test_no_phantom_coaching_stages.py tests/test_coaching_v3.py -q -p no:randomly` — all green.
- [ ] **Real-data proof:** run `python telemetry_tool/main.py <SLK_FP2 abs path> --batch <slk config>` from the worktree root and confirm the coaching output has named root causes (no "Unknown cause"), real drills, a rendered narrative (no `{tokens}`, no `0.0%`), and `engine == "v3"`. (Borrow the SLK batch config the audit used, in `C:/Users/Admin/lap_web-wt-theo-hardening`, or construct a kart RaceChrono config.)
- [ ] Whole-branch review, then hand off to Phase 2 (real drill detection) planning.
