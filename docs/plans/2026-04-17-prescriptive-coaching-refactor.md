# Prescriptive Coaching Refactor — Implementation Spec

**Date:** 2026-04-17
**Status:** Phases 1–4 complete (185 tests green). Producer swap in `build_ok_raw.py` applied. Nothing committed. Phase 5 (UI) gated.
**Branch:** `feat/logger-download-sync` (work-in-progress, uncommitted)

## One-line summary

Moved the 639-line monolithic `track_surface/prescriptive_coaching.py` into a `track_surface/prescriptive/` package with typed DTOs, a pattern registry, four distinct pattern-evaluation states, and an HTTP API endpoint — while preserving the exact JSON shape consumed by `lap-studio-live.html` and `ouest-karting-live.html` at byte offsets ~408,474 and ~417,662 respectively.

## Problem statement

The original single-file module had:

- Module-level `WEAKNESS_PLAYBOOK` dict — not extensible without editing the file.
- Silent drop of unregistered weaknesses (`if playbook is None: continue` at line 231).
- No separation of "pattern detected" from "data insufficient" from "no registered pattern".
- Dict-based input — a typo in an upstream key silently produces empty output.
- Research-layer concepts (median computations) pre-formatted into the public output strings.
- Not exported from the package `__init__`.
- No integration point for an API layer.

## Goals

1. Registry-driven patterns (extensible without editing the core module).
2. **Explicit four-way state separation** per the brief: `Detected`, `NotTriggered`, `Insufficient`, `Unregistered`.
3. Typed DTOs at both the input boundary (`Evidence`, `WeaknessContext`) and the output boundary (`CoachingSheet` and children).
4. **Published-schema contract preservation** — zero frontend changes required.
5. HTTP API endpoint for programmatic use (beyond the build_ok_raw.py bake-time path).

## Non-goals

- Changing the public JSON schema (HTML viewers must keep working unmodified).
- Regenerating `track-surface-ok-data.json` in this session (deferred to normal OK-build cycle).
- Building a UI (explicitly gated by the original brief).
- Deleting the legacy module (kept one cycle for rollback safety).

## Architecture

### Module layout

```
telemetry_tool/track_surface/prescriptive/
  __init__.py           Public re-exports only
  types.py              Published DTOs + Severity / PhaseTag enums
                        Severity constants: HIGH_SEVERITY_MS=400, MEDIUM_SEVERITY_MS=150
                        severity_for(cost_ms) helper
  _internal.py          Evidence, WeaknessContext, PatternResult sum type,
                        portability_for helper. Leading underscore = research layer.
  registry.py           Pattern Protocol + PatternRegistry (refuses silent overwrite,
                        refuses non-Pattern objects, insertion-ordered)
  patterns/
    __init__.py         build_default_registry() → 5 built-ins in legacy order
    _base.py            BasePattern — locked evaluate() with Option B partition policy
    low_minimum_speed.py
    early_braking.py
    late_throttle_pickup.py
    weak_exit_build.py
    line_deviation.py
  adapters.py           Upstream dict → Evidence / WeaknessContext.
                        Only place that touches leaky upstream keys.
  engine.py             run(registry, contexts, evidence, ...)
                        generate_coaching_sheet(...) — the Phase 3+ facade
                        Builders for focus, corner_coaching, next_run_plan,
                        validation_checks, storyline, limits
  serialization.py      CoachingSheet → dict (single point of JSON materialisation)
```

### Published DTOs (`types.py`)

All frozen dataclasses; collections are tuples. Any change requires a version bump of `COACHING_SHEET_VERSION` and an ADR.

| DTO | Purpose |
|---|---|
| `CoachingSheet` | Root; 9 fields (version, source, global_focus, corner_coaching, weakness_playbook_matches, next_run_plan, validation_checks, storyline, limits) |
| `FocusItem` | Top-3 ranked prescriptions → `global_focus` |
| `PlaybookMatch` | Full per-weakness prescription → `weakness_playbook_matches` |
| `CornerCoaching` | Per-corner summary → `corner_coaching` |
| `NextRunItem` | Next-run plan entry; `rank=0` + `type='anti_overload'` is the cognitive-load guard |
| `ValidationCheck` | Measurable check tied to specific corners |
| `StorylineEntry` | Narrative entry with open `type` tag |
| `Limits` | Declared bounds on what the sheet can claim |

### Research-layer types (`_internal.py`)

Never serialised, never re-exported from the package. Import path is explicit: `track_surface.prescriptive._internal`.

- `Evidence` — per-corner snapshot; `Optional[float]` for every sensor-derived field so absence ≠ zero.
- `WeaknessContext` — per-weakness metadata (key, occurrence_count, trend, cost, confidence, corners_observed, archetypes_observed, sessions_observed, sessions_analyzed).
- `Detected` — pattern fired; carries full prescription content (title, phase, affected_corners, not_evaluable_corners, cost_ms, severity, confidence, likely_causes, coaching_actions, driver_cues, measurable_targets, sensor_note, portability, data_support).
- `NotTriggered` — pattern registered AND evidence sufficient AND nothing fired (silent in output, observability only).
- `Insufficient` — pattern registered AND required fields absent across all corners (visible via storyline).
- `Unregistered` — upstream key not in registry (visible via storyline, new design delta).
- `PatternResult = Union[Detected, NotTriggered, Insufficient, Unregistered]`.
- `portability_for(archetypes, sessions_analyzed)` — legacy-parity heuristic.

### Four-state pattern evaluation (core design invariant)

| State | Means | Where it shows in output |
|---|---|---|
| `Detected` | Pattern registered AND evidence triggered | `global_focus`, `playbook_matches`, `corner_coaching` |
| `NotTriggered` | Pattern registered AND evidence sufficient AND nothing fired | Silent (observability only) |
| `Insufficient` | Pattern registered AND required fields absent in ALL corners | `storyline[type='insufficient_data']` |
| `Unregistered` | Upstream emitted a `weakness_key` the registry doesn't know | `storyline[type='unregistered_weakness']` |

### Partial-evidence policy (Option B, locked end of Phase 1)

When SOME corners have the required field and others don't:
- Fire on the subset where all required fields are present.
- Report incomplete corners via `Detected.not_evaluable_corners`.
- The engine surfaces those corners in `corner_coaching` with summary `"Data insufficient for: <weakness>"`.

This is finer than the per-pattern split above: it's a per-corner split WITHIN a pattern that did fire.

Options considered and rejected:
- **Option A** — always `Insufficient` if any corner missing. Too noisy for real-world partial sensor coverage.
- **Option C** — fire + scale confidence by coverage ratio. Honest but hard to explain in UI.

## Phase-by-phase record

### Phase 1 — domain + types + registry + tests

**Files:** `__init__.py`, `types.py`, `_internal.py`, `registry.py`, `tests/test_prescriptive_domain.py`.

**Exit criterion met:** types compile; registry tests green; schema-lock test confirms every key in live `track-surface-ok-data.json` is covered by a DTO field.

**Tests this phase owns:** 47 (after Phase 2 expanded the test file).

### Phase 2 — pattern porting + severity constants

**Files:** `patterns/__init__.py`, `patterns/_base.py`, five pattern files, `tests/test_prescriptive_patterns.py`.

**Key addition:** `HIGH_SEVERITY_MS=400.0` and `MEDIUM_SEVERITY_MS=150.0` pinned in `types.py` as constants; `severity_for(cost_ms)` helper.

**Design choice:** inheritance-based `BasePattern` (not decorator registry) — makes the partition/emit contract readable in one place; concrete patterns are ~40 lines each of data-driven content.

**Tests:** 73 pattern-specific tests including content parity (`title`, `phase`, `sensor_note`, `likely_causes`, `coaching_action_templates`, `driver_cues`) with the legacy `WEAKNESS_PLAYBOOK` imported from `prescriptive_coaching.py`.

### Phase 3 — adapters + engine + serializer

**Files:** `adapters.py`, `engine.py`, `serialization.py`, `tests/test_prescriptive_engine.py`.

**Engine preserves legacy parity** for well-formed input, with three design deltas:
1. `Unregistered` weaknesses → `storyline[type='unregistered_weakness']`.
2. `Insufficient` verdicts → `storyline[type='insufficient_data']` with the specific missing fields named.
3. `not_evaluable_corners` → `corner_coaching` summary `"Data insufficient for: <weakness>"`.

**Facade:** `generate_coaching_sheet(*, corner_packets, weaknesses, sessions_analyzed, laps_analyzed, registry=None)` — takes the same upstream dict shapes legacy accepted. Defaults to `build_default_registry()`.

**Tests:** 27 engine + adapter + serialization + live-parity tests (including `TestLiveParity` that reconstructs upstream inputs from the live ok-data.json and asserts the new engine detects at least the same weakness keys as the embedded legacy output).

### Phase 3 post-step — producer swap

**Edited:** `scripts/build_ok_raw.py:1744-1788` — switched from `generate_prescriptive_coaching` to `generate_coaching_sheet`. Dropped dead legacy params (`priorities`, `dev_storyline`, `track_name`). Updated debug prints from dict-subscript (`gf["rank"]`) to attribute access (`gf.rank`) since the new facade returns typed DTOs.

**Edited:** `telemetry_tool/track_surface/prescriptive_coaching.py` — added `.. deprecated:: v1.0` block in the module docstring pointing to the new package and explaining why the file is retained (one-cycle rollback + `WEAKNESS_PLAYBOOK` parity anchor).

**Not done (gated):** running `python scripts/build_ok_raw.py` to regenerate `track-surface-ok-data.json`. Deferred to normal OK-build cycle because it modifies production-adjacent data.

### Phase 4 — HTTP API

**Files:** `telemetry_tool/web/routes/coaching.py`, `tests/test_coaching_route.py`.

**Edited:** `telemetry_tool/web/app.py` — one-line addition to `_blueprint_imports` registering `coaching_bp`.

**Endpoint:** `POST /api/v1/coaching/prescriptive`. Stateless. Body `{corner_packets, weaknesses, sessions_analyzed, laps_analyzed}`. Response: standard envelope with `data` = `to_json_dict(sheet)`.

**Validation:**
- `422 VALIDATION_ERROR` on non-JSON body.
- `422` on missing required top-level fields (each missing field listed in `error.details`).
- `422` on wrong types (including explicit bool-as-int rejection).
- `422` on malformed weakness (missing `behavior_id`) or packet (missing `corner_id`) — caught at the adapter layer via `KeyError`.

**Auth:** falls behind the standard JWT middleware when `AUTH_REQUIRED=1` (no allowlist entry needed, consistent with other authenticated `/api/v1/` routes).

**Tests:** 14 route tests (happy path, design-delta surface-via-HTTP, validation, method routing).

### Phase 5 (UI) — GATED

Not started. Original brief: "do not build full UI yet".

## Key design decisions

### 1. Parallel-build with co-existence

Legacy `prescriptive_coaching.py` stays on disk. Reasons:
- `WEAKNESS_PLAYBOOK` imported by `test_prescriptive_patterns.py` as the content-parity anchor.
- One-cycle rollback safety.
- Scheduled deletion is a separate reviewable change.

### 2. Four-state `PatternResult` as a tagged union

Typed sum type (via `Union`), not `Optional[dict]` or booleans. Consumers must `isinstance()` each variant — cannot collapse silently. This is the structural enforcement of the brief's "separate pattern detected from data insufficient" rule.

### 3. `_internal.py` underscore prefix + test enforcement

`Evidence`, `WeaknessContext`, `PatternResult`, `portability_for` are reachable via `track_surface.prescriptive._internal` but MUST NOT be re-exported from `track_surface.prescriptive`. Enforced by `TestInternalPublicSeparation` in `test_prescriptive_domain.py`.

### 4. Frozen dataclasses with tuples, not lists

All collections in DTOs are tuples. Mutation is a `FrozenInstanceError` at the point of attempted mutation rather than a runtime surprise later. Serialization converts to lists for JSON.

### 5. Severity thresholds as module constants, not magic numbers

Pinned in `types.py` (`HIGH_SEVERITY_MS=400.0`, `MEDIUM_SEVERITY_MS=150.0`). Changing them shifts what appears at the top of the focus list — so they are contract, not implementation detail.

### 6. `BasePattern` inheritance (vs decorator registry)

The partition policy (Option B) + result-type conventions live in one class. Concrete patterns override only content + two compute hooks (`_compute_parameters`, `_compute_measurable_targets`). Readable, non-magic, testable per-pattern.

### 7. Adapters isolate upstream schema drift

`evidence_from_corner_packet_dict` and `weakness_context_from_dict` are the ONLY places that touch `behavior_id`, `corners_observed`, `evidence.min_speed_delta_kph`, etc. A rename upstream fails HERE — the rest of the engine stays type-safe.

### 8. Partial-evidence = Option B

Chosen over Options A (too noisy) and C (too opaque). Matches legacy behaviour for well-formed input; adds honesty for partial input.

## Published schema contract

The `prescriptive_coaching` key in `track-surface-ok-data.json` has these top-level fields, preserved exactly:

```
version, source,
global_focus[], corner_coaching[],
weakness_playbook_matches[], next_run_plan[],
validation_checks[], storyline[], limits{}
```

**Consumers today:**
- `lap-studio-live.html` (inlines full JSON at byte ~408,474).
- `ouest-karting-live.html` (inlines full JSON at byte ~417,662).

**Schema-lock tests** (`TestSchemaLock` in `test_prescriptive_domain.py`, `TestLiveParity` in `test_prescriptive_engine.py`) verify every live-JSON key is covered by a DTO field and that the new engine covers the set of weaknesses the legacy module produced.

`COACHING_SHEET_VERSION = "1.0"` (frozen).

## Test inventory (185 total)

| File | Scope | Count |
|---|---|---|
| `test_prescriptive_coaching.py` | Legacy module (unchanged) | 24 |
| `test_prescriptive_domain.py` | Types, enums, registry, schema-lock | 47 |
| `test_prescriptive_patterns.py` | Each pattern + default registry + legacy content parity | 73 |
| `test_prescriptive_engine.py` | Engine, adapters, serialization, live parity | 27 |
| `test_coaching_route.py` | HTTP endpoint | 14 |
| **Total** | | **185** |

Runtime: ~1.7s wall-clock.

```bash
# Run the full prescriptive suite:
python -m pytest \
  telemetry_tool/tests/test_prescriptive_coaching.py \
  telemetry_tool/tests/test_prescriptive_domain.py \
  telemetry_tool/tests/test_prescriptive_patterns.py \
  telemetry_tool/tests/test_prescriptive_engine.py \
  telemetry_tool/tests/test_coaching_route.py -q
```

## What's NOT done

### Gated by original brief
- `git commit` of any of the 19 new / 3 edited files.
- React component consuming the endpoint (Phase 5).

### Gated by operational concern (requires local run)
- Regenerating `track-surface-ok-data.json` via `python scripts/build_ok_raw.py`.
- End-to-end validation that the new engine produces a delta-free JSON on the live Ouest Karting dataset.

### Scheduled follow-up (Phase 3 one-cycle policy)
- Deletion of `track_surface/prescriptive_coaching.py` after one prod cycle confirms no regression.
- Removal of the legacy parity-anchor import in `test_prescriptive_patterns.py`. Replace with a frozen content fixture, OR delete the content-parity tests once the new patterns are canonical.

## How to complete Phase 3 (when ready)

```bash
# 1. Regenerate the OK data bundle (producer now uses the new engine)
python scripts/build_ok_raw.py

# 2. Confirm the key set stayed stable
python -m pytest \
  telemetry_tool/tests/test_prescriptive_domain.py::test_live_top_level_keys_covered_by_coaching_sheet \
  -v

# 3. Regenerate the two HTML viewers (whatever the current process is — TBD)

# 4. Browser smoke-test both viewers.
```

Once the next prod cycle confirms no regression:

```bash
# 5. Delete the legacy module.
rm telemetry_tool/track_surface/prescriptive_coaching.py

# 6. Replace the legacy import in test_prescriptive_patterns.py with a
#    frozen content fixture, OR delete the content-parity tests since
#    the new patterns are now canonical.
```

## How to add a new pattern (post-Phase 2)

1. Add `prescriptive/patterns/<new_weakness>.py`:

   ```python
   from track_surface.prescriptive.patterns._base import BasePattern

   class NewWeakness(BasePattern):
       key = "new_weakness"
       title = "..."
       phase = "apex"  # or entry / exit / brake_release / straight
       required_fields = ("relevant_evidence_field",)
       likely_causes = (...,)
       coaching_action_templates = (...,)  # with {placeholders}
       driver_cues = (...,)
       sensor_note = "..."

       def _compute_parameters(self, context, evaluable):
           return {"placeholder": "..."}

       def _compute_measurable_targets(self, context, evaluable):
           return (...,)
   ```

2. Register in `patterns/__init__.py::build_default_registry()` (order matters for tie-breaking).

3. Add a row to `_PATTERN_MATRIX` in `tests/test_prescriptive_patterns.py`. The existing parametrised tests (protocol conformance, Insufficient branch, Detected branch, parameterisation, measurable targets) will apply automatically.

4. If upstream (`driver_development.py`) will emit a matching `behavior_id`, coordinate the rename — otherwise the engine will emit `Unregistered` storyline entries for the new behaviour id instead of silently dropping it.

## How to change the published schema (version bump)

1. Update the DTO in `types.py`.
2. Bump `COACHING_SHEET_VERSION` (e.g., `"1.0"` → `"1.1"`).
3. Write an ADR under `docs/adr/` (or the project's current ADR location) explaining what changed and why.
4. Update the schema-lock tests in `test_prescriptive_domain.py`.
5. Update the HTML viewers if the change is not strictly additive.

Additive changes (new optional fields with safe defaults) do NOT require a version bump — but do require updating the schema-lock tests so future drift is caught.

## File inventory

### New (19)

**Package (14):**
- `telemetry_tool/track_surface/prescriptive/__init__.py`
- `telemetry_tool/track_surface/prescriptive/types.py`
- `telemetry_tool/track_surface/prescriptive/_internal.py`
- `telemetry_tool/track_surface/prescriptive/registry.py`
- `telemetry_tool/track_surface/prescriptive/adapters.py`
- `telemetry_tool/track_surface/prescriptive/engine.py`
- `telemetry_tool/track_surface/prescriptive/serialization.py`
- `telemetry_tool/track_surface/prescriptive/patterns/__init__.py`
- `telemetry_tool/track_surface/prescriptive/patterns/_base.py`
- `telemetry_tool/track_surface/prescriptive/patterns/low_minimum_speed.py`
- `telemetry_tool/track_surface/prescriptive/patterns/early_braking.py`
- `telemetry_tool/track_surface/prescriptive/patterns/late_throttle_pickup.py`
- `telemetry_tool/track_surface/prescriptive/patterns/weak_exit_build.py`
- `telemetry_tool/track_surface/prescriptive/patterns/line_deviation.py`

**Route (1):**
- `telemetry_tool/web/routes/coaching.py`

**Tests (4):**
- `telemetry_tool/tests/test_prescriptive_domain.py`
- `telemetry_tool/tests/test_prescriptive_patterns.py`
- `telemetry_tool/tests/test_prescriptive_engine.py`
- `telemetry_tool/tests/test_coaching_route.py`

### Edited (3)

- `telemetry_tool/web/app.py` — one line in `_blueprint_imports`.
- `scripts/build_ok_raw.py` — lines 1744–1788 swapped to the new engine.
- `telemetry_tool/track_surface/prescriptive_coaching.py` — module docstring adds `.. deprecated:: v1.0` block.

## Appendix A — minimal glossary

- **Bronze / canonical**: upstream evidence derived only from speed traces + GPS + the session-compare engine. No Gold Lab / beta / bank-corrected / diagnostic signals.
- **Weakness**: a recurring behavioural pattern with a stable `behavior_id` emitted by `driver_development.DevelopmentIntelligence.recurring_weaknesses`. Current set: `low_minimum_speed`, `early_braking`, `late_throttle_pickup`, `weak_exit_build`, `line_deviation`.
- **Corner packet**: a `session_compare.CornerPacket` dataclass serialised to dict by `build_ok_raw.py` before reaching the engine.
- **Pattern**: a small class that evaluates one weakness against the evidence for the corners it cares about. Must satisfy the `Pattern` protocol (`key`, `title`, `phase`, `required_fields`, `evaluate`).
- **Sheet**: a `CoachingSheet` — the published, versioned root DTO.
