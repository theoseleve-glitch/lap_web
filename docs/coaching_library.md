# Coaching Library

> Formal, versioned coaching pattern library. Single source of truth for weakness / strength pattern definitions shared across the coaching stack.

## What it is

`telemetry_tool/track_surface/coaching_library.py` consolidates the three previously-duplicated pattern registries into one inspectable, version-contracted ontology:

| Legacy registry | Module | Shape consumed |
|---|---|---|
| `BEHAVIOR_DEFS` | `driver_development.py` | `CornerFeatures` dataclass, session-level trends |
| `WEAKNESS_PLAYBOOK` | `prescriptive_coaching.py` | Coaching content templates |
| `INTERVENTION_CLASSES` | `coaching_intelligence.py` | Evidence-dict, lap-level interventions |

The library is the canonical definition. Consumers will migrate to importing from it; current modules still hold inline copies, which are guaranteed parity by tests.

Additional consumers the ontology is designed for:
- Future lap optimizer (mechanical targets per canonical pattern)
- Future sim coaching (same pattern → simulator-native driver prompts)
- Future setup / strategy explanation layers (pattern → setup-change hint catalogue)

## Design invariants (guarded by tests)

1. **Canonical pattern IDs.** Each named driving phenomenon has ONE `canonical_id`. Consumer-specific names are declared as aliases so migration leaves external behaviour unchanged.
2. **Multi-shape detection.** Each pattern may declare detection for a `CornerFeatures`-shaped input (session-level, looser thresholds) and an `evidence`-dict input (lap-level, stricter thresholds). Consumers pick the shape that matches their data.
3. **Sensor honesty.** Every pattern declares the input channels it depends on. All channels are speed-derived — no CAN/pressure sensors assumed.
4. **Evidence-backed coaching.** `coaching_template` content is optional; when present, it declares the template parameters it expects so consumers can validate substitution.
5. **Polarity-explicit.** `weakness | strength | neutral`. Strengths carry `trainability = 0.0` and are never offered as training priorities.
6. **Deterministic.** `list_patterns()` iteration is stable (insertion-ordered); all containers are tuples; detection lambdas are pure.
7. **Version-contracted.** `LIBRARY_VERSION` bumps on any schema change; each pattern also has its own `version`.
8. **Fail-fast validation.** Library validates itself at import time. A malformed entry raises on import rather than contaminating downstream consumers.

## Version

```
LIBRARY_VERSION = '1.0.0'
```

## Schema

### `CoachingPattern`

| Field | Type | Purpose |
|---|---|---|
| `pattern_id` | `str` | Canonical identifier. Stable across releases. |
| `version` | `str` | Per-pattern SemVer. Bumps on schema or threshold changes. |
| `label` | `str` | Short human-readable name. |
| `title` | `str` | Longer title used by playbook consumers. |
| `phase` | `str` | One of `PHASES` = `(entry, brake_release, apex, exit, straight)`. |
| `polarity` | `str` | One of `POLARITIES` = `(weakness, strength, neutral)`. |
| `trainability` | `float` | `[0.0, 1.0]`. Strengths must be `0.0`. |
| `metric_key` | `str` | Name of the primary metric on `CornerFeatures` (for features-shape consumers). |
| `direction` | `str` | One of `DIRECTIONS` = `(positive_is_bad, negative_is_bad, positive_is_good, negative_is_good, neutral_is_good)`. |
| `sensor_requirements` | `tuple[str, ...]` | Subset of `SENSORS` = `(gps_speed, gps_position, derived_brake_onset, derived_throttle_onset, reference_lap_trace)`. |
| `archetype_applicability` | `tuple[str, ...]` | Corner archetypes; `('*',)` = all. |
| `aliases` | `tuple[str, ...]` | Consumer-specific IDs that resolve to this canonical pattern. |
| `related_patterns` | `tuple[str, ...]` | Canonical IDs of causally or symptomatically linked patterns. |
| `coaching_template` | `CoachingTemplate \| None` | Coaching content (only when the pattern has actionable instruction). |
| `detect_features` | `Callable[[CornerFeatures], bool] \| None` | Session-level (loose) detection. |
| `detect_evidence` | `Callable[[dict], bool] \| None` | Lap-level (strict) detection. |
| `confidence_fn_evidence` | `Callable[[dict, dict], float] \| None` | Confidence score for evidence-level detection. |
| `detection_descriptions` | `dict[str, str]` | Human-readable threshold per input shape. |

### `CoachingTemplate`

| Field | Type | Purpose |
|---|---|---|
| `likely_causes` | `tuple[str, ...]` | Hypotheses explaining the weakness. |
| `coaching_actions` | `tuple[str, ...]` | Concrete instructions. May contain `{param}` placeholders. |
| `driver_cues` | `tuple[str, ...]` | Feel / look / sound cues for the driver. |
| `template_params` | `tuple[str, ...]` | Declared placeholder names (e.g. `brake_adjust_m`). |
| `sensor_note` | `str` | Sensor-honest note about how the metric was measured. |

## Canonical pattern registry (v1.0.0)

Nine canonical patterns, consolidating 18 legacy entries.

| `pattern_id` | Phase | Polarity | Trainability | Detect shapes | Aliases | Template? |
|---|---|---|---|---|---|---|
| `apex_low_speed` | apex | weakness | 0.8 | features + evidence | `low_minimum_speed`, `apex_speed_deficit` | yes |
| `early_braking` | entry | weakness | 0.85 | features | — | yes |
| `entry_speed_surrender` | entry | weakness | 0.85 | evidence | — | no |
| `conservative_brake_release` | brake_release | weakness | 0.9 | evidence | — | no |
| `late_throttle_pickup` | exit | weakness | 0.9 | features + evidence | `late_throttle_application` | yes |
| `weak_exit_build` | exit | weakness | 0.85 | features + evidence | — | yes |
| `line_deviation` | apex | weakness | 0.7 | features + evidence | `path_variance` | yes |
| `strong_braking` | entry | strength | 0.0 | features | — | no |
| `strong_exit` | exit | strength | 0.0 | features | — | no |

### Alias map

| Alias | Canonical |
|---|---|
| `low_minimum_speed` | `apex_low_speed` |
| `apex_speed_deficit` | `apex_low_speed` |
| `late_throttle_application` | `late_throttle_pickup` |
| `path_variance` | `line_deviation` |

### Relationships (declared `related_patterns`)

```
apex_low_speed ─┬─ entry_speed_surrender
                └─ weak_exit_build
early_braking ─── entry_speed_surrender
entry_speed_surrender ─┬─ early_braking
                       └─ apex_low_speed
conservative_brake_release ─ apex_low_speed
late_throttle_pickup ─── weak_exit_build
weak_exit_build ─┬─ late_throttle_pickup
                 └─ apex_low_speed
```

## Public API

```python
from track_surface.coaching_library import (
    # Taxonomy constants
    LIBRARY_VERSION, PHASES, POLARITIES, INPUT_SHAPES, DIRECTIONS, SENSORS,
    # Dataclasses
    CoachingPattern, CoachingTemplate,
    # Lookup
    get_pattern, resolve_alias,
    list_patterns, list_pattern_ids,
    patterns_for_phase, patterns_by_polarity, patterns_supporting_shape,
    # Inspection
    library_manifest,
    # Adapters to legacy dict shapes
    as_behavior_def, as_weakness_playbook_entry, as_intervention_class,
    behavior_defs_dict, weakness_playbook_dict, intervention_classes_dict,
)
```

### Lookup

- `get_pattern(id_or_alias) -> CoachingPattern` — resolves either canonical or alias; raises `KeyError` if unknown.
- `resolve_alias(id_or_alias) -> str` — returns canonical `pattern_id`.
- `list_patterns() -> tuple[CoachingPattern, ...]` — stable registration order.
- `patterns_for_phase(phase) -> tuple[CoachingPattern, ...]` — filter by phase; raises `ValueError` on invalid phase.
- `patterns_by_polarity(polarity) -> tuple[CoachingPattern, ...]`
- `patterns_supporting_shape('corner_features' | 'evidence_dict') -> tuple[CoachingPattern, ...]`

### Inspection

```python
library_manifest() -> dict
```

Pure-data JSON-serialisable manifest: version, taxonomy enums, alias map (self-refs excluded), and a compact per-pattern summary with detection-threshold descriptions. Safe to include in any `data.*` block.

### Consumer adapters

Each adapter reconstructs the exact dict shape the corresponding legacy registry exposes:

| Adapter | Legacy target | Requires |
|---|---|---|
| `as_behavior_def(id)` | `BEHAVIOR_DEFS` entry | `detect_features` is not None |
| `as_weakness_playbook_entry(id)` | `WEAKNESS_PLAYBOOK` entry | `coaching_template` is not None |
| `as_intervention_class(id)` | `INTERVENTION_CLASSES` entry | `detect_evidence` + `confidence_fn_evidence` not None |

Bulk variants (`behavior_defs_dict()`, `weakness_playbook_dict()`, `intervention_classes_dict()`) reconstruct the entire legacy dict.

## Import-time validation

On import the library:

- Builds `_ALIAS_INDEX` and rejects alias/id collisions.
- Rejects invalid `phase`, `polarity`, `direction`, `trainability` out of range.
- Rejects strengths with non-zero trainability.
- Rejects unknown sensors in `sensor_requirements`.
- Rejects patterns with no detection shape declared.
- Rejects unknown input shapes in `detection_descriptions`.
- Rejects `{placeholder}` tokens in coaching content that are not declared in `template_params`.
- Rejects `related_patterns` pointing at nonexistent canonical IDs.

Any violation raises `ValueError` on module import — consumers cannot silently read corrupt data.

## Test contract

`telemetry_tool/tests/test_coaching_library.py` — 36 tests across 10 categories:

1. **Schema stability** — required fields, correct types, detection declared, detection descriptions match available shapes.
2. **Version contract** — `LIBRARY_VERSION` is SemVer-shaped; every pattern is versioned.
3. **Alias uniqueness + resolution** — canonical IDs resolve to self; declared aliases resolve correctly; unknown aliases raise.
4. **Taxonomy validity** — valid phases/polarities/directions; strengths trainability=0; weaknesses trainability>0.
5. **Registry parity** — every legacy `BEHAVIOR_DEFS`, `WEAKNESS_PLAYBOOK`, `INTERVENTION_CLASSES` key is resolvable through the library and the library exposes a matching detection shape.
6. **Adapter round-trip** — adapters produce correct legacy dict shapes; alias-resolved adapter output matches canonical-resolved output; bulk dicts match legacy labels/metric keys/content where semantically possible.
7. **Determinism** — `list_pattern_ids()` stable across calls; manifest stable.
8. **Sensor honesty** — every pattern declares ≥1 sensor; all sensors are in `SENSORS` taxonomy.
9. **Template parameter resolution** — every `{placeholder}` is declared; template substitution succeeds with declared params.
10. **Relationships + manifest** — all `related_patterns` resolve; manifest contains required keys and correct counts; alias map excludes self-refs; shape filters cover all patterns.

Regression guard: 71 tests across `test_driver_development.py`, `test_prescriptive_coaching.py`, `test_coaching_intelligence.py` continue to pass — the library is purely additive.

## Explicit non-goals (v1.0.0)

- **No coaching content authored in multiple languages.** Single-language (English) content only; i18n layer not in scope.
- **No archetype-specific thresholds.** Every pattern applies to `('*',)`; archetype-aware detection is deferred.
- **No skill-level or vehicle-class modulation of coaching templates.**
- **No setup-change or sim-coaching content blocks.** Schema has room for `setup_hints` / `sim_hints` but none are populated.
- **No feedback-loop calibration.** `trainability` and `confidence_fn` values are fixed at v1.0.0 and are not updated from observed driver improvement.
- **No pattern migration helper.** Future version bumps will need a versioned resolver for consumers; not yet implemented.

## What remains missing for a true cross-platform coaching ontology

1. **Consumer migration.** The three legacy modules (`driver_development`, `prescriptive_coaching`, `coaching_intelligence`) still hold inline dicts. They should be refactored to import from `coaching_library` so the library is the only mutation point. Current parity is test-enforced, not structurally enforced.
2. **Companion content blocks.** Add optional `setup_hints`, `sim_coaching_hints`, `strategy_flags` fields on `CoachingPattern` to serve future lap optimizer / sim / setup layers from the same ontology.
3. **Archetype-specific thresholds.** Today detection thresholds are flat. Hairpin vs fast corner should have different tolerances for `apex_low_speed`.
4. **Skill-level and vehicle-class modulation.** Same pattern, different coaching depth and language for beginner/expert, kart/car.
5. **Multi-lingual coaching content.** Project already ships 7 locales; the library currently carries only English content.
6. **Feedback loop.** Observed improvement should update `trainability` and `confidence_fn` values over time.
7. **Versioned migration helper.** When a pattern version bumps, consumers need a resolver for breaking changes.
8. **Trainability calibration governance.** Legacy modules disagreed on the same concept (e.g. `apex_speed_deficit` trainability was 0.75 in `coaching_intelligence`, 0.8 in `driver_development`). The library picked one per canonical pattern; a review process should confirm these values.

Items 1–3 are the highest-leverage next moves for turning this consolidated registry into a true cross-platform ontology.
