# Coaching Ontology Migration — v1.0.0 → v2.0.0

> How `track_surface.coaching_library` became the single runtime source of truth for the coaching stack, and what was added to make it a genuinely cross-platform ontology.

## One-line summary

The coaching library stops being a parallel ontology and becomes the **authoritative** ontology. The three legacy registries (`BEHAVIOR_DEFS` in `driver_development.py`, `INTERVENTION_CLASSES` in `coaching_intelligence.py`, `WEAKNESS_PLAYBOOK` in `prescriptive_coaching.py`) are now reconstructed from the library at import time. The schema grows with **four** structured companion blocks per pattern, **archetype-aware thresholds** on eight patterns, and **provisional trainability governance**. All changes are additive — every v1 consumer still compiles and every v1 test still passes.

## What changed structurally

| Area | v1.0.0 | v2.0.0 |
|---|---|---|
| Authoritative ontology | `coaching_library` + 3 consumer-owned inline dicts | `coaching_library` only |
| Canonical patterns | 9 | 12 (+3 new) |
| Companion blocks | `coaching_template` only | `coaching_template`, `real_life_coaching`, `sim_coaching`, `setup_hints`, `strategy_flags` |
| Archetype thresholds | `archetype_applicability=('*',)` flat | 6-value taxonomy + per-pattern per-shape override map |
| Trainability | single float | float + `TrainabilityGovernance(rationale, provisional)` |
| Consumer keys | canonical id only | `consumer_keys` override map preserves legacy names |
| Import-time validation | 8 checks | 20+ checks incl. companion-block honesty + consumer-key collisions |

## Registries that were eliminated or replaced

| Module | Legacy symbol | Before | After |
|---|---|---|---|
| `driver_development.py` | `BEHAVIOR_DEFS` | Hand-maintained 7-entry dict (lambdas + trainability + metric_key) | `behavior_defs_dict(consumer='driver_development')` from the library |
| `coaching_intelligence.py` | `INTERVENTION_CLASSES` | Hand-maintained 6-entry dict (detect + confidence_fn + trainability) | `intervention_classes_dict(consumer='coaching_intelligence')` from the library |
| `prescriptive_coaching.py` | `WEAKNESS_PLAYBOOK` | Hand-maintained 5-entry dict (title + causes + actions + cues + sensor_note) | `weakness_playbook_dict(consumer='prescriptive_coaching')` wrapped by a thin legacy-list shape helper |

All three dicts keep **the same outer keys** as before (`low_minimum_speed`, `apex_speed_deficit`, `path_variance`, …). They are preserved via a per-pattern `consumer_keys` override on the library's `CoachingPattern`. This means every existing test and every existing frontend consumer continues to see the identical dict shape it saw under v1.

## Final canonical pattern list

Insertion order (stable — consumers that iterate by order will see the v2 additions appended, never reshuffled):

| # | `pattern_id` | Phase | Polarity | Trainability | Legacy aliases |
|---|---|---|---|---|---|
| 1 | `apex_low_speed` | apex | weakness | 0.8 | `low_minimum_speed`, `apex_speed_deficit` |
| 2 | `early_braking` | entry | weakness | 0.85 | — |
| 3 | `entry_speed_surrender` | entry | weakness | 0.85 | — |
| 4 | `conservative_brake_release` | brake_release | weakness | 0.9 | — |
| 5 | `late_throttle_pickup` | exit | weakness | 0.9 | `late_throttle_application` |
| 6 | `weak_exit_build` | exit | weakness | 0.85 | — |
| 7 | `line_deviation` | apex | weakness | 0.7 | `path_variance` |
| 8 | `strong_braking` | entry | strength | 0.0 | — |
| 9 | `strong_exit` | exit | strength | 0.0 | — |
| 10 | `unstable_corner_execution` ⭐ | apex | weakness | 0.65 (provisional) | — |
| 11 | `likely_understeer_proxy` ⭐ | apex | weakness | 0.5 (provisional) | — |
| 12 | `likely_oversteer_proxy` ⭐ | exit | weakness | 0.5 (provisional) | — |

⭐ = new in v2.0.0.

## Alias policy

1. **Every pattern has exactly one canonical `pattern_id`** that never changes.
2. **Legacy consumer names** (e.g. `low_minimum_speed`) are declared as `aliases` on the canonical pattern. `resolve_alias('low_minimum_speed')` returns `'apex_low_speed'`.
3. **Alias collision = import-time failure.** Two patterns cannot share an alias; an alias cannot collide with another pattern's canonical id.
4. **Consumer-key collisions are separately checked.** Within a single consumer (e.g. `driver_development`), two canonical patterns cannot map to the same legacy key in their `consumer_keys`. This prevents ambiguous reconstructed dicts.
5. **Unknown alias raises `KeyError`** from `resolve_alias()`.

## Versioning policy

| Scope | Version constant | Bump when |
|---|---|---|
| Library schema | `LIBRARY_VERSION` | Any schema change to `CoachingPattern`, its companion-block dataclasses, or the public API |
| Individual pattern | `CoachingPattern.version` | Threshold, companion-block content, or detection-semantic change |

Version strings are three-part SemVer-shaped strings (`MAJOR.MINOR.PATCH`), validated at import time.

- v2.0.0 is a **major** bump because the schema gained five required-conditional fields (the companion blocks), `archetype_thresholds`, `consumer_keys`, and `trainability_governance`. The public API is otherwise **additive** — every v1 function still exists and returns identical output for v1 inputs.
- Each v1 pattern's `version` is bumped to `2.0.0` when its companion blocks were populated. Strength patterns (`strong_braking`, `strong_exit`) carry only `strategy_flags` — the remaining companion blocks are `None` by design (see "Evidence honesty" below).

## Archetype-aware threshold design

**Taxonomy** (`ARCHETYPES`):

```
hairpin • medium_speed_corner • fast_corner • chicane • long_radius • unknown
```

`unknown` is the explicit safe fallback — every `archetype_thresholds` block must declare an `'unknown'` entry. Unrecognised archetype strings (including `None`) are normalised to `'unknown'` by `normalize_archetype()`.

**Data layout** — every archetype-aware pattern declares `archetype_thresholds` as a two-level dict keyed by input shape then by archetype:

```python
archetype_thresholds = {
    'corner_features': {
        'hairpin':              {'min_speed_delta_kph': -3.0},
        'medium_speed_corner':  {'min_speed_delta_kph': -3.0},
        'fast_corner':          {'min_speed_delta_kph': -1.5},   # tighter
        'chicane':              {'min_speed_delta_kph': -3.5},
        'long_radius':          {'min_speed_delta_kph': -2.5},
        'unknown':              {'min_speed_delta_kph': -3.0},   # same as default
    },
    'evidence_dict': {...},
}
```

**Runtime** — `detect_for_archetype(pattern_id_or_alias, archetype, shape, data)`:

1. Normalise `archetype` (legacy names → canonical names; unknown → `'unknown'`).
2. If the pattern has `detect_features_archetype` / `detect_evidence_archetype` for the requested shape, call it with `(data, archetype)`.
3. Otherwise fall back to the default `detect_features` / `detect_evidence` lambda.
4. Return `False` (rather than raise) if the pattern has no detector for the requested shape at all.

**Patterns with archetype thresholds (8):**
`apex_low_speed`, `early_braking`, `late_throttle_pickup`, `weak_exit_build`, `line_deviation`, `unstable_corner_execution`, `likely_understeer_proxy`, `likely_oversteer_proxy`.

**Patterns without** (by design — either narrow-scope interventions or strengths):
`entry_speed_surrender`, `conservative_brake_release`, `strong_braking`, `strong_exit`.

**Invariant — sparse-data safety preserved:** If `detect_for_archetype` is called with `archetype=None` or an unrecognised archetype string, detection falls back to the default lambda rather than silently defaulting or raising. Every threshold map includes an `'unknown'` entry that is equal to (or stricter than) the legacy v1 threshold — existing outputs at `archetype='unknown'` match v1 output exactly on the unit-level tests.

## Companion block schema and purpose

Every pattern may declare four optional companion blocks. Each targets a distinct downstream consumer.

### `RealLifeCoaching`

Used by the prescriptive coaching engine and any future live-coaching overlay (e.g. the Ghost Overlay spec).

```python
@dataclass(frozen=True)
class RealLifeCoaching:
    actions:              tuple[str, ...]
    driver_cues:          tuple[str, ...]
    validation_metrics:   tuple[str, ...]
    sensor_honesty_note:  str
```

**Honesty rule:** `actions` and `sensor_honesty_note` MUST be non-empty when declared. `sensor_honesty_note` must call out the proxy nature of speed-derived fields (no brake pressure, no throttle position, no steering angle).

### `SimCoaching`

Used by sim-trainer overlays and the (future) Lap Oracle AC driver feedback layer.

```python
@dataclass(frozen=True)
class SimCoaching:
    trainable_in_sim:          tuple[str, ...]
    transfer_to_real_life:     str
    non_transfer_risks:        tuple[str, ...]
    recommended_sim_exercises: tuple[str, ...]
    transfer_confidence:       str   # 'low' | 'medium' | 'high'
```

**Honesty rule:** `non_transfer_risks` MUST be non-empty when `transfer_confidence != 'high'`. The two proxy patterns (`likely_understeer_proxy`, `likely_oversteer_proxy`) carry `transfer_confidence='low'` because GPS-only sim-to-real transfer for vehicle-dynamic concepts is weakly evidenced.

### `SetupHints`

Used by the future setup / handling explanation layer.

```python
@dataclass(frozen=True)
class SetupHints:
    driver_first:                tuple[str, ...]
    setup_possible:              tuple[str, ...]
    insufficient_evidence_cases: tuple[str, ...]
    evidence_honesty_note:       str
```

**Honesty rule:** every block explicitly lists driver-first checks before setup hypotheses. Every block declares the sensors required to rule mechanical vs driver cause — a critical guard since GPS-only telemetry cannot definitively attribute apex speed loss to setup.

### `StrategyFlags`

Used by the race-strategy engine, stint-execution report, and tyre-management overlays.

```python
@dataclass(frozen=True)
class StrategyFlags:
    consistency_relevance:       str
    tyre_management_relevance:   str
    traffic_overtake_relevance:  str
    stint_execution_relevance:   str
    evidence_honesty_note:       str
```

**Honesty rule:** `evidence_honesty_note` must call out which flag(s) are directly evidenced (usually only `consistency_relevance`) and which are heuristic.

## Trainability governance

Every pattern now carries a `TrainabilityGovernance` block:

```python
@dataclass(frozen=True)
class TrainabilityGovernance:
    rationale:    str
    provisional:  bool = False
```

- `rationale` is a short explanation of why the scalar has the value it has — anchored in coaching-literature expectations, historical disagreement between consumers, or calibration source.
- `provisional=True` marks patterns whose trainability value was interpolated from a single-track dataset or where the underlying phenomenon cannot be cleanly attributed to the driver (e.g. the understeer/oversteer proxies).

**Invariant:** `trainability_governance.rationale` is required (non-empty) for every pattern. Downstream consumers all read trainability from the library; no consumer is allowed a local override. This is enforced structurally by the import-time validator and behaviourally by the `TestTrainabilityGovernance.test_all_consumers_read_same_trainability` test.

## Output contract preservation

Bronze, Silver, Gold Lab, and shadow signals are unchanged.

- **Bronze** (session_compare.corner_packets, development_intelligence outputs) has zero schema changes. Validated by `TestBronzeSilverUnchanged` and `TestOutputStability`.
- **Silver** (intermediate computed outputs) is unchanged — the library adds no new sensor type and no pattern requires a non-Bronze-safe sensor.
- **Gold Lab / beta / shadow:** a new test (`TestNoExperimentalContamination`) scans every pattern's content strings (`coaching_actions`, `driver_cues`, `likely_causes`, companion-block actions + cues + risks) for forbidden source tags (`gold_lab`, `shadow`, `beta_candidate`, `experimental`) and fails if any leak in.
- **Consumer outputs** (`DevelopmentIntelligence.to_json_dict()`, `CoachingIntelligence.to_json_dict()`, `PrescriptiveCoaching.to_json_dict()`) keep identical outer-key sets — validated by `TestOutputStability`.
- **Frontend contracts** (`lap-studio-live.html`, `ouest-karting-live.html` at byte offsets ~408,474 and ~417,662) are untouched — none of the companion blocks surface to those viewers yet; they remain available for future consumers to opt into.

## Deterministic + sparse-data behaviour preserved

- `list_patterns()`, `list_pattern_ids()`, and `library_manifest()` are deterministic across calls (validated).
- `detect_for_archetype(…, None, …, …)` returns the same result as `detect_for_archetype(…, 'unknown', …, …)`.
- Missing evidence fields (None values, empty dicts, missing attributes) produce `False` — not exceptions. The Insufficient/Detected/NotTriggered distinction continues to live in the `prescriptive/` package's `PatternResult` sum type; the library's detectors are a thin substrate.

## Import-time validation — new checks introduced in v2.0.0

1. `real_life_coaching.actions` non-empty (when declared)
2. `real_life_coaching.sensor_honesty_note` non-empty (when declared)
3. `sim_coaching.transfer_confidence ∈ SIM_TRANSFER_CONFIDENCES`
4. `sim_coaching.non_transfer_risks` non-empty when `transfer_confidence < 'high'`
5. `setup_hints.evidence_honesty_note` non-empty
6. `strategy_flags.evidence_honesty_note` non-empty
7. `archetype_thresholds` keys ⊆ INPUT_SHAPES
8. `archetype_thresholds[*]` inner keys ⊆ ARCHETYPES
9. `archetype_thresholds[*]` must include `'unknown'` fallback
10. `consumer_keys` keys ⊆ CONSUMERS
11. `consumer_keys` per-consumer collision check (two patterns cannot map to the same legacy key for the same consumer)
12. `trainability_governance.rationale` non-empty when declared

Any violation raises `ValueError` at **library import time** — consumers cannot silently read corrupt data.

## Remaining gaps before this is a truly market-ready cross-platform coaching ontology

1. **Consumer-key coverage is pragmatic, not exhaustive.** Three legacy consumers mapped; future consumers (Lap Oracle sim coaching, ghost-overlay live-coach, setup hint surface) will need their own entries in `CONSUMERS` and their own per-pattern `consumer_keys` overrides.
2. **Archetype vocabulary collides with `driver_development.CORNER_ARCHETYPES`.** The library uses `hairpin/medium_speed_corner/fast_corner/chicane/long_radius/unknown`; `driver_development` emits `slow_hairpin/slow_90deg/medium_speed/fast_corner/chicane/traction_exit`. `normalize_archetype()` bridges them, but the long-term answer is to make the library's taxonomy authoritative downstream (or teach `driver_development` to emit canonical names).
3. **Thresholds are single-track-calibrated.** The archetype-specific values (especially for `likely_*_proxy` patterns) were set from a single dataset. Multi-track validation is a hard prerequisite before presenting these thresholds as product-grade.
4. **Trainability is coarsely governed.** Rationale strings are present but there is no audit trail for threshold changes (no version-bump enforcement beyond tests). A per-pattern changelog with ADR links would close this.
5. **Localization / i18n.** Companion-block content is English-only. The product already ships 7 locales via `telemetry_tool/web/i18n/`; the library content is not yet wired to translation keys.
6. **Sim coaching transfer-confidence is editorial, not empirical.** No A/B data backs the `low/medium/high` assignments. Publishing these to users requires either measured evidence or explicit disclaimers.
7. **Setup hints are intentionally speculative.** The `SetupHints.insufficient_evidence_cases` block is the honest guard; but a product surface would need a "show only when corroborated by tyre-temp / wheel-speed data" gate that does not exist yet.
8. **Strategy flags are heuristic.** Only `consistency_relevance` is directly evidenced; the other three fields are expert-labelled defaults. A real cross-platform ontology would either measure them or downgrade them to `'heuristic'`.
9. **Archetype thresholds have no online calibration.** They are baked in at version bump time. A future iteration could accept per-workspace overrides (e.g. kart-class-specific hairpin thresholds) without branching the canonical registry.
10. **Pattern migration helper.** When a pattern `version` bumps with a breaking threshold change, consumers will need a resolver to compare a cached v1 prescription to a v2 library state. Not yet implemented.

The short list: **items 2, 3, and 10 are the highest-leverage next moves** — they are the remaining structural gaps; items 1 and 4–9 are expansion / content work that becomes incremental once the structural pieces are in place.
