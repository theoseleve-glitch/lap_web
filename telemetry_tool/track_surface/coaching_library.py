"""
track_surface/coaching_library.py
---------------------------------
Formal, versioned coaching pattern library — the single source of truth
for weakness/strength pattern definitions shared across:

    • driver_development.py     (session-level behavior patterns)
    • prescriptive_coaching.py  (weakness playbooks → prescriptions)
    • coaching_intelligence.py  (lap-level intervention classes)
    • future consumers: lap optimizer, sim coaching, setup/strategy

Design invariants (guarded by tests):

1. Canonical pattern IDs. Each named driving phenomenon has ONE
   canonical_id. Consumer-specific IDs are declared as aliases so
   migration leaves external behaviour unchanged.

2. Multi-shape detection. Each pattern may declare detection for a
   CornerFeatures-shaped input (session-level, looser thresholds) and
   an evidence-dict input (lap-level, stricter thresholds). Consumers
   pick the shape that matches their data.

3. Sensor honesty. Every pattern declares the input channels it
   depends on. Patterns needing unavailable channels can be filtered
   before detection rather than silently producing garbage.

4. Evidence-backed coaching. coaching_template content is optional but
   when present declares the template parameters it expects so
   consumers can validate substitution.

5. Polarity-explicit. weakness | strength | neutral — strengths carry
   trainability = 0.0 and are never offered as training priorities.

6. Deterministic. list_patterns() iteration is stable (insertion-
   ordered); all containers are tuples; detection lambdas are pure.

7. Version-contracted. LIBRARY_VERSION bumps on any schema change.

The library validates itself at import time. A malformed entry raises
on import rather than contaminating downstream consumers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


# ─────────────────────────────────────────────────────────────────
# Version + taxonomy
# ─────────────────────────────────────────────────────────────────

# 2.0.0: schema extended with companion blocks
# (real_life_coaching, sim_coaching, setup_hints, strategy_flags),
# archetype-aware thresholds, trainability_rationale/provisional,
# consumer_keys mapping, and three new patterns
# (unstable_corner_execution, likely_understeer_proxy, likely_oversteer_proxy).
# Public API is additive — every 1.0.0 consumer still works.
LIBRARY_VERSION = '2.0.0'

PHASES = ('entry', 'brake_release', 'apex', 'exit', 'straight')

POLARITIES = ('weakness', 'strength', 'neutral')

INPUT_SHAPES = ('corner_features', 'evidence_dict')

DIRECTIONS = (
    'positive_is_bad',
    'negative_is_bad',
    'positive_is_good',
    'negative_is_good',
    'neutral_is_good',
)

# Sensor channel taxonomy — patterns declare which of these they read.
# All channels are speed-derived; no CAN/pressure sensors assumed.
SENSORS = (
    'gps_speed',
    'gps_position',
    'derived_brake_onset',      # speed-derivative brake point proxy
    'derived_throttle_onset',   # speed-derivative throttle pickup proxy
    'reference_lap_trace',      # for deltas
)

# Canonical corner-archetype taxonomy used by archetype-aware thresholds.
# 'unknown' is the explicit safe fallback when classification is not available
# or the observed archetype falls outside the whitelist. Consumers that use
# different vocabularies (driver_development currently emits
# 'slow_hairpin'/'slow_90deg'/...) can map into this via
# ``normalize_archetype()`` so the library remains authoritative about the
# threshold set.
ARCHETYPES = (
    'hairpin',
    'medium_speed_corner',
    'fast_corner',
    'chicane',
    'long_radius',
    'unknown',
)

# Consumer taxonomy — each legacy module owns a view on the library.
# Values correspond to optional per-pattern ``consumer_keys`` overrides so
# legacy dict keys (e.g. 'low_minimum_speed') are preserved for backward
# compatibility even after migration to the canonical-id registry.
CONSUMERS = (
    'driver_development',
    'coaching_intelligence',
    'prescriptive_coaching',
)

# Confidence tags allowed on SimCoaching.transfer_confidence.
SIM_TRANSFER_CONFIDENCES = ('low', 'medium', 'high')


# ─────────────────────────────────────────────────────────────────
# Dataclasses
# ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CoachingTemplate:
    """Evidence-backed coaching content. Templates may contain
    parameter placeholders like {brake_adjust_m} to be filled by the
    consumer with measured values."""
    likely_causes: tuple[str, ...]
    coaching_actions: tuple[str, ...]
    driver_cues: tuple[str, ...]
    template_params: tuple[str, ...]
    sensor_note: str


# ── Cross-platform companion blocks (v2.0.0) ────────────────────
#
# Each companion block serves a distinct downstream consumer. Blocks are
# OPTIONAL: a pattern with no actionable content in a given domain should
# leave that block as None rather than publish weak content.


@dataclass(frozen=True)
class RealLifeCoaching:
    """Instruction block for in-car / on-track coaching.

    Used by the prescriptive coaching engine and any future live-coaching
    overlay that runs while a real driver is at the wheel. Content must
    be evidence-backed and speed-derived — no CAN-signal instructions.
    """
    actions: tuple[str, ...]
    driver_cues: tuple[str, ...]
    validation_metrics: tuple[str, ...]
    sensor_honesty_note: str


@dataclass(frozen=True)
class SimCoaching:
    """Instruction block for sim-trainer coaching.

    Populated for patterns where sim practice can (or cannot) realistically
    transfer to the real car/kart. ``transfer_confidence`` gates claims:
    'low' means the sim drill is listed but transfer is speculative,
    'high' means there is a strong physical basis for transfer.
    ``non_transfer_risks`` is the honest 'what the sim will lie to you
    about' field — never leave it empty when transfer_confidence < 'high'.
    """
    trainable_in_sim: tuple[str, ...]
    transfer_to_real_life: str
    non_transfer_risks: tuple[str, ...]
    recommended_sim_exercises: tuple[str, ...]
    transfer_confidence: str   # one of SIM_TRANSFER_CONFIDENCES


@dataclass(frozen=True)
class SetupHints:
    """Setup-change hints linked to this pattern.

    A motorsport engineer's mental model is "always solve the driver first".
    ``driver_first`` lists the technique checks that should be ruled out
    before touching the kart/car; ``setup_possible`` lists the setup knobs
    that could plausibly relate, but ONLY once the driver-first items are
    excluded. ``insufficient_evidence_cases`` enumerates the specific
    scenarios where the current speed/GPS sensor suite cannot tell driver
    from setup — a direct honesty constraint on downstream UIs.
    """
    driver_first: tuple[str, ...]
    setup_possible: tuple[str, ...]
    insufficient_evidence_cases: tuple[str, ...]
    evidence_honesty_note: str


@dataclass(frozen=True)
class StrategyFlags:
    """Flags surfacing a pattern's relevance to race-strategy subsystems.

    Each field is a SHORT descriptor (or 'not_applicable') consumed by the
    race-strategy engine, tyre-management layer, stint-execution report,
    and overtake/traffic overlays. Evidence honesty note caps what can be
    claimed from a single-session/single-track dataset.
    """
    consistency_relevance: str
    tyre_management_relevance: str
    traffic_overtake_relevance: str
    stint_execution_relevance: str
    evidence_honesty_note: str


@dataclass(frozen=True)
class TrainabilityGovernance:
    """Explicit rationale for the trainability scalar.

    The ``trainability`` float is a governance value — legacy modules
    disagreed (apex_speed_deficit was 0.75 in coaching_intelligence, 0.8
    in driver_development). Consolidating required picking a single value;
    this block documents the choice and marks it ``provisional=True`` when
    the calibration was interpolated without strong empirical backing.
    """
    rationale: str
    provisional: bool = False


@dataclass
class CoachingPattern:
    """One named driving phenomenon. Canonical definition.

    v2.0.0 fields (real_life_coaching, sim_coaching, setup_hints,
    strategy_flags, archetype_thresholds, detect_features_archetype,
    detect_evidence_archetype, trainability_governance, consumer_keys)
    are all optional. Patterns authored against the v1 schema keep
    validating.
    """
    pattern_id: str
    version: str
    label: str
    title: str
    phase: str
    polarity: str
    trainability: float
    metric_key: str
    direction: str
    sensor_requirements: tuple[str, ...]
    archetype_applicability: tuple[str, ...]   # ('*',) means all archetypes
    aliases: tuple[str, ...] = ()
    related_patterns: tuple[str, ...] = ()
    coaching_template: Optional[CoachingTemplate] = None
    # Detection lambdas — may be None if this shape is not supported.
    detect_features: Optional[Callable[..., bool]] = None
    detect_evidence: Optional[Callable[[dict], bool]] = None
    confidence_fn_evidence: Optional[Callable[[dict, dict], float]] = None
    # Human-readable descriptions of the detection thresholds per shape.
    detection_descriptions: dict = field(default_factory=dict)
    # ── v2.0.0 additions ────────────────────────────────────────
    # Structured companion blocks — None when the pattern has nothing
    # evidence-honest to say in that domain (strengths often leave them
    # all None; see strong_braking / strong_exit).
    real_life_coaching: Optional[RealLifeCoaching] = None
    sim_coaching: Optional[SimCoaching] = None
    setup_hints: Optional[SetupHints] = None
    strategy_flags: Optional[StrategyFlags] = None
    # Archetype-aware detection. ``archetype_thresholds`` is the
    # inspectable threshold config (maps shape → archetype → threshold
    # name → value); it is the source the two archetype-aware lambdas
    # below read from. When both are None, archetype-aware detection
    # falls back to ``detect_features`` / ``detect_evidence``.
    archetype_thresholds: dict = field(default_factory=dict)
    detect_features_archetype: Optional[Callable[..., bool]] = None
    detect_evidence_archetype: Optional[Callable[..., bool]] = None
    # Trainability governance — rationale + provisional flag.
    trainability_governance: Optional[TrainabilityGovernance] = None
    # Consumer-specific dict keys. Legacy registries (BEHAVIOR_DEFS,
    # INTERVENTION_CLASSES, WEAKNESS_PLAYBOOK) indexed by names that are
    # aliases in the canonical library (e.g. 'low_minimum_speed' in
    # driver_development is alias of canonical 'apex_low_speed').
    # ``consumer_keys`` preserves those legacy keys when the library
    # reconstructs a consumer-facing dict.
    consumer_keys: dict = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────
# Canonical pattern registry
# ─────────────────────────────────────────────────────────────────
#
# The 9 patterns below consolidate:
#   • 7 entries from driver_development.BEHAVIOR_DEFS
#   • 5 entries from prescriptive_coaching.WEAKNESS_PLAYBOOK
#   • 6 entries from coaching_intelligence.INTERVENTION_CLASSES
#
# Naming convention: canonical IDs describe the phenomenon, not the
# intervention. 'apex_low_speed' (phenomenon) is canonical;
# 'apex_speed_deficit' (intervention label) is an alias.


_PATTERNS: dict[str, CoachingPattern] = {}


def _register(p: CoachingPattern) -> None:
    _PATTERNS[p.pattern_id] = p


# ── 1. Apex low speed ───────────────────────────────────────────
_APEX_LOW_SPEED_FEATURES_THRESHOLDS = {
    'hairpin':              {'min_speed_delta_kph': -3.0},
    'medium_speed_corner':  {'min_speed_delta_kph': -3.0},
    'fast_corner':          {'min_speed_delta_kph': -1.5},
    'chicane':              {'min_speed_delta_kph': -3.5},
    'long_radius':          {'min_speed_delta_kph': -2.5},
    'unknown':              {'min_speed_delta_kph': -3.0},
}

_APEX_LOW_SPEED_EVIDENCE_THRESHOLDS = {
    'hairpin':              {'min_speed_delta_kph': -5.0, 'timing_abs_max': 5.0},
    'medium_speed_corner':  {'min_speed_delta_kph': -5.0, 'timing_abs_max': 5.0},
    'fast_corner':          {'min_speed_delta_kph': -3.0, 'timing_abs_max': 4.0},
    'chicane':              {'min_speed_delta_kph': -6.0, 'timing_abs_max': 5.0},
    'long_radius':          {'min_speed_delta_kph': -4.0, 'timing_abs_max': 5.0},
    'unknown':              {'min_speed_delta_kph': -5.0, 'timing_abs_max': 5.0},
}


def _apex_low_speed_features_archetype(cf, archetype):
    thresh = _APEX_LOW_SPEED_FEATURES_THRESHOLDS.get(
        archetype, _APEX_LOW_SPEED_FEATURES_THRESHOLDS['unknown'])
    return cf.min_speed_delta_kph < thresh['min_speed_delta_kph']


def _apex_low_speed_evidence_archetype(ev, archetype):
    thresh = _APEX_LOW_SPEED_EVIDENCE_THRESHOLDS.get(
        archetype, _APEX_LOW_SPEED_EVIDENCE_THRESHOLDS['unknown'])
    return (
        (ev.get('min_speed_delta_kph') or 0) < thresh['min_speed_delta_kph']
        and abs(ev.get('throttle_pickup_delta_m') or 0) < thresh['timing_abs_max']
        and abs(ev.get('brake_point_delta_m') or 0) < thresh['timing_abs_max']
    )


_register(CoachingPattern(
    pattern_id='apex_low_speed',
    version='2.0.0',
    label='Low minimum speed through apex',
    title='Low minimum speed through apex',
    phase='apex',
    polarity='weakness',
    trainability=0.8,
    metric_key='min_speed_delta_kph',
    direction='negative_is_bad',
    sensor_requirements=('gps_speed', 'reference_lap_trace'),
    archetype_applicability=('*',),
    aliases=('low_minimum_speed', 'apex_speed_deficit'),
    consumer_keys={
        'driver_development':    'low_minimum_speed',
        'coaching_intelligence': 'apex_speed_deficit',
        'prescriptive_coaching': 'low_minimum_speed',
    },
    related_patterns=('entry_speed_surrender', 'weak_exit_build'),
    detect_features=lambda cf: cf.min_speed_delta_kph < -3.0,
    detect_evidence=lambda ev: (
        (ev.get('min_speed_delta_kph') or 0) < -5.0
        and abs(ev.get('throttle_pickup_delta_m') or 0) < 5.0
        and abs(ev.get('brake_point_delta_m') or 0) < 5.0
    ),
    detect_features_archetype=_apex_low_speed_features_archetype,
    detect_evidence_archetype=_apex_low_speed_evidence_archetype,
    archetype_thresholds={
        'corner_features': _APEX_LOW_SPEED_FEATURES_THRESHOLDS,
        'evidence_dict':   _APEX_LOW_SPEED_EVIDENCE_THRESHOLDS,
    },
    confidence_fn_evidence=lambda ev, pkt: min(1.0,
        0.5 * pkt.get('confidence', 0.5)
        + 0.5 * (1.0 if abs(ev.get('min_speed_delta_kph', 0)) > 8 else 0.5)
    ),
    detection_descriptions={
        'corner_features': 'min_speed_delta_kph < -3.0 (archetype-adjusted)',
        'evidence_dict': (
            'min_speed_delta_kph < -5 AND |throttle_pickup_delta_m|<5 '
            'AND |brake_point_delta_m|<5 (archetype-adjusted)'
        ),
    },
    trainability_governance=TrainabilityGovernance(
        rationale=(
            'Apex-speed commitment is a pure technique issue once brake '
            'and throttle timing are ruled out — high real-world trainability. '
            'Legacy coaching_intelligence used 0.75 (same phenomenon, stricter '
            'corner sample); driver_development used 0.8. Picked 0.8 as the '
            'session-level calibration is the more durable reference.'
        ),
        provisional=False,
    ),
    coaching_template=CoachingTemplate(
        likely_causes=(
            'Over-rotating the kart before apex (too much steering input)',
            'Releasing brake too abruptly instead of trailing',
            'Turn-in point too early, tightening the radius mid-corner',
            'Insufficient confidence in the loaded phase of the corner',
        ),
        coaching_actions=(
            'Protect minimum speed: aim to carry {target_kph} more through the middle of the corner',
            'Use a later, more patient turn-in — let the kart arc naturally rather than forcing rotation',
            'Trail the brake deeper: maintain light pressure past the initial turn-in point',
        ),
        driver_cues=(
            'Feel: the kart should feel "loaded" through mid-corner, not "falling" off speed',
            'Look: pick up the exit reference earlier to give yourself confidence to carry speed',
            'Sound: engine note should not dip as sharply between braking and acceleration',
        ),
        template_params=('target_kph',),
        sensor_note='Minimum speed measured from GPS speed trace (speed-derived, no wheel speed sensor)',
    ),
    real_life_coaching=RealLifeCoaching(
        actions=(
            'Protect minimum speed through the middle of the corner — target +2 to +4 kph',
            'Use a later, more patient turn-in to let the radius arc naturally',
            'Trail the brake deeper past turn-in so weight stays on the front and the kart rotates without steering',
        ),
        driver_cues=(
            'Feel: the kart should feel "loaded" at the apex, not "falling off speed"',
            'Look: pick up the exit reference earlier — the eyes set the commitment',
            'Sound: engine note should not dip sharply between braking and acceleration',
        ),
        validation_metrics=(
            'Apex minimum speed rises by 2+ kph vs session baseline',
            'Entry timing (brake point, throttle pickup) within 3 m of reference',
            'Line RMS stable or lower, not higher',
        ),
        sensor_honesty_note=(
            'Minimum speed derived from GPS speed trace — no wheel-speed, '
            'no accelerometer-based rotation check.'
        ),
    ),
    sim_coaching=SimCoaching(
        trainable_in_sim=(
            'Minimum-speed commitment — repeating the same corner at fixed brake point',
            'Trail-brake feel — modulating pedal pressure through turn-in',
        ),
        transfer_to_real_life=(
            'Strong transfer at slow-to-medium speed corners. Sim force-feedback '
            'understates front-end load, so absolute pedal forces will be wrong, '
            'but the VISUAL/TIMING pattern transfers directly.'
        ),
        non_transfer_risks=(
            'Sim seat-of-pants feedback is weaker than real — drivers may over-rotate in sim, under-rotate in real',
            'Tyre warmup and falloff are sim-model-dependent; real grip window is smaller',
        ),
        recommended_sim_exercises=(
            'Fixed 3-lap runs at a single medium-speed corner, varying minimum speed by ±2 kph',
            'Trail-brake modulation drills: hold the corner steady, vary brake release point only',
        ),
        transfer_confidence='high',
    ),
    setup_hints=SetupHints(
        driver_first=(
            'Confirm brake point, trail-brake depth, and turn-in timing are within 3 m of reference',
            'Confirm line RMS is within 0.5 m of reference — path is the primary driver of apex speed',
            'Confirm driver is not lifting off brake before rotation is done',
        ),
        setup_possible=(
            'Front-end grip deficit (lower front pressure, soften front bar)',
            'Too much mid-corner understeer from static alignment (toe/camber)',
            'Kart: axle stiffness too high for load transfer on this radius',
        ),
        insufficient_evidence_cases=(
            'Cannot separate technique from mechanical grip without lateral-G sensor',
            'Cannot separate tyre thermal state from setup without tyre temps',
        ),
        evidence_honesty_note=(
            'GPS-only telemetry cannot attribute apex speed loss to setup vs driver. '
            'Driver-first is mandatory; setup is a hypothesis until a track-side check supports it.'
        ),
    ),
    strategy_flags=StrategyFlags(
        consistency_relevance=(
            'High — apex-speed variance across laps is a direct consistency '
            'signal and is the single biggest lap-time variance source on '
            'medium-speed corners.'
        ),
        tyre_management_relevance=(
            'Medium — loss of apex speed late in a stint can indicate front-end '
            'grip decay; early-stint loss is almost always technique.'
        ),
        traffic_overtake_relevance=(
            'Medium — low apex speed forecasts weak exit and easy overtake '
            'on the next straight; in battle, defend the apex line explicitly.'
        ),
        stint_execution_relevance=(
            'High — protect apex commitment when managing fuel or tyres is '
            'not the active constraint; downshift the target only when explicitly pushed to.'
        ),
        evidence_honesty_note=(
            'Relevance strings are heuristic — only consistency_relevance is '
            'directly evidenced from lap-level telemetry.'
        ),
    ),
))


# ── 2. Early braking (session behavior) ──────────────────────────
_EARLY_BRAKING_FEATURES_THRESHOLDS = {
    'hairpin':              {'brake_point_delta_m': -5.0},
    'medium_speed_corner':  {'brake_point_delta_m': -5.0},
    'fast_corner':          {'brake_point_delta_m': -8.0},
    'chicane':              {'brake_point_delta_m': -4.0},
    'long_radius':          {'brake_point_delta_m': -6.0},
    'unknown':              {'brake_point_delta_m': -5.0},
}


def _early_braking_features_archetype(cf, archetype):
    thresh = _EARLY_BRAKING_FEATURES_THRESHOLDS.get(
        archetype, _EARLY_BRAKING_FEATURES_THRESHOLDS['unknown'])
    return (cf.brake_point_delta_m or 0) < thresh['brake_point_delta_m']


_register(CoachingPattern(
    pattern_id='early_braking',
    version='2.0.0',
    label='Early braking on entry',
    title='Early braking on entry',
    phase='entry',
    polarity='weakness',
    trainability=0.85,
    metric_key='brake_point_delta_m',
    direction='negative_is_bad',
    sensor_requirements=('gps_speed', 'derived_brake_onset', 'reference_lap_trace'),
    archetype_applicability=('*',),
    aliases=(),
    consumer_keys={
        'driver_development':    'early_braking',
        'prescriptive_coaching': 'early_braking',
    },
    related_patterns=('entry_speed_surrender',),
    detect_features=lambda cf: (cf.brake_point_delta_m or 0) < -5.0,
    detect_evidence=None,  # session-level only
    detect_features_archetype=_early_braking_features_archetype,
    archetype_thresholds={
        'corner_features': _EARLY_BRAKING_FEATURES_THRESHOLDS,
    },
    detection_descriptions={
        'corner_features': 'brake_point_delta_m < -5.0 (archetype-adjusted)',
    },
    trainability_governance=TrainabilityGovernance(
        rationale=(
            'Brake-point placement is among the most deliberate, coach-friendly '
            'changes a driver can make — fixed visual reference, binary outcome. '
            'High trainability is strongly supported by coaching literature.'
        ),
        provisional=False,
    ),
    coaching_template=CoachingTemplate(
        likely_causes=(
            'Braking reference point is too far from the corner',
            'Defensive habit from an earlier session or unfamiliar track',
            'Approaching the corner off-line, requiring earlier braking to make the geometry',
        ),
        coaching_actions=(
            'Move the braking reference closer by {brake_adjust_m} m (one kart-length at a time)',
            'Use a fixed visual marker for the brake point, not a feeling',
            'Keep the same peak brake force — the change is WHERE, not HOW HARD',
        ),
        driver_cues=(
            'Feel: the kart should require you to brake, not just slow down voluntarily',
            'Look: identify a crack, kerb edge, or cone that is {brake_adjust_m} m closer than your current point',
        ),
        template_params=('brake_adjust_m',),
        sensor_note='Brake point derived from speed-based deceleration onset (no brake pressure sensor)',
    ),
    real_life_coaching=RealLifeCoaching(
        actions=(
            'Move the braking reference closer by one kart-length at a time',
            'Use a fixed visual marker for the brake point — not a feeling',
            'Keep the same peak brake force — the change is WHERE, not HOW HARD',
        ),
        driver_cues=(
            'Feel: the kart should require you to brake, not slow down voluntarily',
            'Look: identify a crack, kerb edge, or cone that is one kart-length closer than your current point',
        ),
        validation_metrics=(
            'Brake point moves 2+ m later toward reference',
            'Minimum speed holds or rises — no undershoot penalty',
            'Entry line matches reference within 0.5 m',
        ),
        sensor_honesty_note=(
            'Brake point is speed-derivative onset — not actual pedal force. '
            'Cannot detect "dabbing" the brake without pressure data.'
        ),
    ),
    sim_coaching=SimCoaching(
        trainable_in_sim=(
            'Locking a visual brake marker and moving it closer incrementally',
            'Preserving peak brake force under the new brake point',
        ),
        transfer_to_real_life=(
            'Strong transfer for braking distance and reference point placement. '
            'Sim brake curves are near-linear; real pedals have more hysteresis, '
            'so drivers may stall pedal force in the real car — monitor for this.'
        ),
        non_transfer_risks=(
            'Sim pedal spring-load differs from real — absolute force cues do not transfer',
            'Tyre thermal warmup affects real-car braking; most sim models simplify this',
        ),
        recommended_sim_exercises=(
            'Single-corner loop with incremental 2-m brake-point advances',
            'Blind-distance drill: cover the HUD speed, trust the visual marker only',
        ),
        transfer_confidence='high',
    ),
    setup_hints=SetupHints(
        driver_first=(
            'Confirm the driver sees and trusts the visual brake marker',
            'Confirm entry line is not pushing the driver off-line',
            'Confirm the driver is not braking early to compensate for an unstable release',
        ),
        setup_possible=(
            'Brake bias too rearward (kart unstable on initial brake, driver backs off)',
            'Front tyre pressure too high (nervous initial bite)',
        ),
        insufficient_evidence_cases=(
            'Without brake pressure data, cannot distinguish "early brake" from "light pre-brake"',
            'Cannot tell if the driver is braking early because of mechanical unease vs habit',
        ),
        evidence_honesty_note=(
            'Setup causes here are speculative from speed-only data. '
            'Driver-first is the default path — setup changes require corroborating evidence.'
        ),
    ),
    strategy_flags=StrategyFlags(
        consistency_relevance=(
            'Medium — early braking is usually consistent (it IS the habit); '
            'inconsistent early braking points to attention drift.'
        ),
        tyre_management_relevance=(
            'Low-to-medium — slightly earlier braking reduces tyre stress at '
            'corner entry but costs lap time proportionally.'
        ),
        traffic_overtake_relevance=(
            'High — early braking is the single biggest invitation to an '
            'overtake-under-braking move; tightening the brake point is a '
            'defensive necessity in traffic.'
        ),
        stint_execution_relevance=(
            'Medium — early braking is acceptable to manage tyre life under '
            'explicit tyre-save call; otherwise should be actively narrowed.'
        ),
        evidence_honesty_note=(
            'Strategy mapping is heuristic; actual tyre impact requires '
            'tyre-temp or tyre-wear instrumentation.'
        ),
    ),
))


# ── 3. Entry speed surrender (intervention — combined) ───────────
_register(CoachingPattern(
    pattern_id='entry_speed_surrender',
    version='2.0.0',
    label='Entry speed surrendered too early',
    title='Entry speed surrendered too early',
    phase='entry',
    polarity='weakness',
    trainability=0.85,
    metric_key='brake_point_delta_m',
    direction='negative_is_bad',
    sensor_requirements=('gps_speed', 'derived_brake_onset', 'reference_lap_trace'),
    archetype_applicability=('*',),
    aliases=(),
    consumer_keys={
        'coaching_intelligence': 'entry_speed_surrender',
    },
    related_patterns=('early_braking', 'apex_low_speed'),
    detect_features=None,
    detect_evidence=lambda ev: (
        (ev.get('brake_point_delta_m') or 0) < -5.0
        and (ev.get('min_speed_delta_kph') or 0) < -3.0
    ),
    confidence_fn_evidence=lambda ev, pkt: min(1.0,
        0.5 * (1.0 if ev.get('brake_point_delta_m') is not None else 0.3)
        + 0.3 * pkt.get('confidence', 0.5)
        + 0.2 * (1.0 if abs(ev.get('min_speed_delta_kph', 0)) > 5 else 0.5)
    ),
    detection_descriptions={
        'evidence_dict': 'brake_point_delta_m < -5 AND min_speed_delta_kph < -3',
    },
    coaching_template=None,
    trainability_governance=TrainabilityGovernance(
        rationale=(
            'Compound of early_braking (trainability 0.85) and apex_low_speed '
            '(0.8). Kept at 0.85 to match the brake-point-lever weight, since '
            'fixing the brake point usually unlocks the apex-speed gain.'
        ),
        provisional=False,
    ),
    real_life_coaching=RealLifeCoaching(
        actions=(
            'Treat this as two linked problems: the brake point is early AND the apex speed is low',
            'Move brake point 2–4 m closer to the corner in kart-length increments',
            'After brake point is stabilised, push apex minimum-speed commitment up by 2–3 kph',
        ),
        driver_cues=(
            'Look: fixed brake reference first, then reach for a higher apex speed',
            'Feel: if the kart is stable on the new brake point, commit deeper to the apex',
        ),
        validation_metrics=(
            'Brake point moves 2+ m later (toward reference)',
            'Apex minimum speed rises by 1+ kph',
            'No exit speed loss — the gains must not cost the exit',
        ),
        sensor_honesty_note=(
            'Brake point is speed-derivative onset; apex speed is GPS-derived. '
            'No pedal-pressure, no steering angle.'
        ),
    ),
    sim_coaching=SimCoaching(
        trainable_in_sim=(
            'Sequenced drill: fix brake point first over 5 laps, then lift apex speed over the next 5',
        ),
        transfer_to_real_life=(
            'Sequencing is the critical sim skill here. Brake-point transfer is '
            'strong; apex-speed commitment transfer is moderate (sim feedback '
            'understates rear-end slip).'
        ),
        non_transfer_risks=(
            'Sim rarely models brake temperature — a late brake point in a long stint may fade in real car',
            'Sim may hide the consequence of missing the apex by a hand-span of track width',
        ),
        recommended_sim_exercises=(
            'Two-phase corner drills: 5 laps "brake point", 5 laps "apex speed", 5 laps "both"',
        ),
        transfer_confidence='medium',
    ),
    setup_hints=SetupHints(
        driver_first=(
            'Confirm driver sees the new brake reference clearly',
            'Confirm line into the corner is not pushing them off-optimal',
        ),
        setup_possible=(
            'Brake bias too rearward destabilising initial brake',
            'Front-end grip deficit making apex commitment unsafe',
        ),
        insufficient_evidence_cases=(
            'Cannot separate brake bias from driver hesitation without pedal data',
            'Cannot tell if low apex speed follows from the early brake or an independent cause',
        ),
        evidence_honesty_note=(
            'Compound pattern — setup attributions are the MOST speculative in '
            'this library. Driver-first is mandatory.'
        ),
    ),
    strategy_flags=StrategyFlags(
        consistency_relevance='High — compound pattern surfaces repeat lap-time variance',
        tyre_management_relevance='Low — surrender behaviour already under-stresses tyres',
        traffic_overtake_relevance='High — compound entry weakness is the biggest overtake-under-braking invitation',
        stint_execution_relevance='High — must be narrowed once tyres are up to temperature',
        evidence_honesty_note='Flag strings are heuristic — consistency is the only directly evidenced',
    ),
))


# ── 4. Conservative brake release ────────────────────────────────
_register(CoachingPattern(
    pattern_id='conservative_brake_release',
    version='2.0.0',
    label='Brake release too conservative',
    title='Brake release too conservative',
    phase='brake_release',
    polarity='weakness',
    trainability=0.9,
    metric_key='min_speed_delta_kph',
    direction='negative_is_bad',
    sensor_requirements=('gps_speed', 'derived_brake_onset', 'reference_lap_trace'),
    archetype_applicability=('*',),
    aliases=(),
    consumer_keys={
        'coaching_intelligence': 'conservative_brake_release',
    },
    related_patterns=('apex_low_speed',),
    detect_features=None,
    detect_evidence=lambda ev: (
        abs(ev.get('brake_point_delta_m') or 0) < 5.0
        and (ev.get('min_speed_delta_kph') or 0) < -5.0
    ),
    confidence_fn_evidence=lambda ev, pkt: min(1.0,
        0.4 * pkt.get('confidence', 0.5)
        + 0.3 * (1.0 if abs(ev.get('min_speed_delta_kph', 0)) > 8 else 0.5)
        + 0.3 * (1.0 if abs(ev.get('brake_point_delta_m') or 99) < 3 else 0.4)
    ),
    detection_descriptions={
        'evidence_dict': '|brake_point_delta_m|<5 AND min_speed_delta_kph < -5',
    },
    coaching_template=None,
    trainability_governance=TrainabilityGovernance(
        rationale=(
            'Brake release modulation is the most coach-trainable pedal skill — '
            'it is a direct motor-pattern drill. Highest trainability in the '
            'library (0.9) reflects strong empirical convergence across coaching literature.'
        ),
        provisional=False,
    ),
    real_life_coaching=RealLifeCoaching(
        actions=(
            'Focus on the RELEASE, not the initial application',
            'Begin trailing off brake pressure 3–5 m earlier before the apex',
            'The goal is a smoother, longer release — not less braking overall',
        ),
        driver_cues=(
            'Feel: pedal should lighten progressively as steering is added',
            'Feel: the kart should begin rotating as the brake releases — not after',
        ),
        validation_metrics=(
            'Apex minimum speed rises by 2+ kph',
            'Brake point stays within 2 m of reference',
            'No overshoot on the new release — still arrives at apex, just faster',
        ),
        sensor_honesty_note=(
            'Brake release inferred from speed-derivative deceleration shape; '
            'cannot measure actual pedal pressure decay rate.'
        ),
    ),
    sim_coaching=SimCoaching(
        trainable_in_sim=(
            'Trail-brake modulation on a fixed corner',
            'Pedal-ramp drills with visual feedback',
        ),
        transfer_to_real_life=(
            'Moderate transfer. Sim brake pedals have lower hysteresis than real '
            'hydraulic pedals, so the modulation "feel" in the sim will be lighter '
            'and smoother than in the real kart. The TIMING transfers well; the '
            'FORCE profile does not.'
        ),
        non_transfer_risks=(
            'Sim-trained release timing may cause real-car under-release due to hydraulic lag',
            'Brake temperature and pad glaze are rarely modelled; real brake feel drifts over a stint',
        ),
        recommended_sim_exercises=(
            'Slow-corner fixation: same corner 10 laps, vary ONLY brake release ramp',
            'Audio-only drill: cover the speed readout, release by engine note alone',
        ),
        transfer_confidence='medium',
    ),
    setup_hints=SetupHints(
        driver_first=(
            'Confirm driver is not flat-braking the corner — they must be trail-braking already to call this',
            'Confirm brake point is not early (that would be early_braking, not release)',
        ),
        setup_possible=(
            'Brake bias too forward (rear feels locked on release, driver is cautious)',
            'Front tyre camber too aggressive (initial release causes front nibble)',
        ),
        insufficient_evidence_cases=(
            'Without brake pressure, cannot tell "holding brake too long" from "light release too early"',
            'Cannot tell rear-lock tendency without wheel-speed data',
        ),
        evidence_honesty_note=(
            'Setup hypotheses are WEAK here — brake-release is dominantly a '
            'technique issue. Setup changes should be a last resort.'
        ),
    ),
    strategy_flags=StrategyFlags(
        consistency_relevance='High — brake release is the largest single source of apex-speed variance',
        tyre_management_relevance='Medium — aggressive release raises peak front load; manage on long stints',
        traffic_overtake_relevance='Low — rarely the deciding factor in on-track passes',
        stint_execution_relevance='High — target execution area once tyres are warm',
        evidence_honesty_note='Consistency mapping is direct; tyre/strategy claims are heuristic',
    ),
))


# ── 5. Late throttle pickup ──────────────────────────────────────
_LATE_THROTTLE_FEATURES_THRESHOLDS = {
    'hairpin':              {'throttle_pickup_delta_m': 5.0},
    'medium_speed_corner':  {'throttle_pickup_delta_m': 5.0},
    'fast_corner':          {'throttle_pickup_delta_m': 8.0},
    'chicane':              {'throttle_pickup_delta_m': 4.0},
    'long_radius':          {'throttle_pickup_delta_m': 6.0},
    'unknown':              {'throttle_pickup_delta_m': 5.0},
}
_LATE_THROTTLE_EVIDENCE_THRESHOLDS = dict(_LATE_THROTTLE_FEATURES_THRESHOLDS)


def _late_throttle_features_archetype(cf, archetype):
    thresh = _LATE_THROTTLE_FEATURES_THRESHOLDS.get(
        archetype, _LATE_THROTTLE_FEATURES_THRESHOLDS['unknown'])
    return (cf.throttle_pickup_delta_m or 0) > thresh['throttle_pickup_delta_m']


def _late_throttle_evidence_archetype(ev, archetype):
    thresh = _LATE_THROTTLE_EVIDENCE_THRESHOLDS.get(
        archetype, _LATE_THROTTLE_EVIDENCE_THRESHOLDS['unknown'])
    return (ev.get('throttle_pickup_delta_m') or 0) > thresh['throttle_pickup_delta_m']


_register(CoachingPattern(
    pattern_id='late_throttle_pickup',
    version='2.0.0',
    label='Late throttle pickup on exits',
    title='Late throttle pickup on exits',
    phase='exit',
    polarity='weakness',
    trainability=0.9,
    metric_key='throttle_pickup_delta_m',
    direction='positive_is_bad',
    sensor_requirements=('gps_speed', 'derived_throttle_onset', 'reference_lap_trace'),
    archetype_applicability=('*',),
    aliases=('late_throttle_application',),
    consumer_keys={
        'driver_development':    'late_throttle_pickup',
        'coaching_intelligence': 'late_throttle_application',
        'prescriptive_coaching': 'late_throttle_pickup',
    },
    related_patterns=('weak_exit_build',),
    detect_features=lambda cf: (cf.throttle_pickup_delta_m or 0) > 5.0,
    detect_evidence=lambda ev: (ev.get('throttle_pickup_delta_m') or 0) > 5.0,
    detect_features_archetype=_late_throttle_features_archetype,
    detect_evidence_archetype=_late_throttle_evidence_archetype,
    archetype_thresholds={
        'corner_features': _LATE_THROTTLE_FEATURES_THRESHOLDS,
        'evidence_dict':   _LATE_THROTTLE_EVIDENCE_THRESHOLDS,
    },
    confidence_fn_evidence=lambda ev, pkt: min(1.0,
        0.4 * (1.0 if ev.get('throttle_pickup_delta_m') is not None else 0.3)
        + 0.3 * pkt.get('confidence', 0.5)
        + 0.3 * (1.0 if (ev.get('throttle_pickup_delta_m') or 0) > 8 else 0.5)
    ),
    detection_descriptions={
        'corner_features': 'throttle_pickup_delta_m > 5.0 (archetype-adjusted)',
        'evidence_dict': 'throttle_pickup_delta_m > 5.0 (archetype-adjusted)',
    },
    trainability_governance=TrainabilityGovernance(
        rationale=(
            'Throttle-application timing is the second-most-trainable pedal skill '
            '(after brake release). Visual and proprioceptive cues converge; sim '
            'transfer is strong for initial application timing.'
        ),
        provisional=False,
    ),
    coaching_template=CoachingTemplate(
        likely_causes=(
            'Waiting for the kart to be fully straight before applying throttle',
            'Uncertainty about exit grip after a tight apex',
            'Habit of "completing the corner" mentally before transitioning to power',
        ),
        coaching_actions=(
            'Begin partial throttle (30-50%) as soon as you start unwinding steering',
            'Target: move throttle application {throttle_adjust_m} m earlier',
            'Do NOT go to full throttle earlier — start with initial application point only',
        ),
        driver_cues=(
            'Feel: throttle should overlap with the last bit of steering unwind',
            'Look: start thinking "power" when you see the apex, not when you see the exit',
        ),
        template_params=('throttle_adjust_m',),
        sensor_note='Throttle proxy from GPS speed derivative (no CAN throttle position sensor)',
    ),
    real_life_coaching=RealLifeCoaching(
        actions=(
            'Begin partial throttle (30–50%) as soon as steering starts unwinding',
            'Move initial throttle application 3–5 m earlier',
            'Do NOT go to full throttle earlier — start with initial application point only',
        ),
        driver_cues=(
            'Feel: throttle and steering unwind should overlap — not sequential',
            'Look: start thinking "power" when you SEE the apex, not the exit',
        ),
        validation_metrics=(
            'Throttle pickup moves 2+ m earlier toward reference',
            'Exit speed improves by 1+ kph at the exit checkpoint',
            'No line deviation growth — still on reference exit line',
        ),
        sensor_honesty_note=(
            'Throttle pickup derived from speed-trace inflection (not pedal sensor). '
            'Cannot distinguish "partial throttle ramp" from "full throttle step".'
        ),
    ),
    sim_coaching=SimCoaching(
        trainable_in_sim=(
            'Throttle-initiation timing relative to steering unwind',
            'Partial throttle application ramps',
        ),
        transfer_to_real_life=(
            'High transfer for application point. Sim tyres usually have a wider '
            'grip window than real; be cautious about sim-trained throttle '
            'aggression causing real-car rear slip.'
        ),
        non_transfer_risks=(
            'Sim tyre slip-curves differ from real — a sim-safe early throttle may cause real-car oversteer',
            'Sim engines often have flatter torque curves; real kart torque spike more pronounced',
        ),
        recommended_sim_exercises=(
            'Exit-only drills: focus on earliest possible partial-throttle point',
            'Paired-lap drills: one lap "late & clean", one lap "early & committed", compare deltas',
        ),
        transfer_confidence='high',
    ),
    setup_hints=SetupHints(
        driver_first=(
            'Confirm steering unwind is smooth — not a jerky release',
            'Confirm exit line is not pushing the driver to wait for straightening',
        ),
        setup_possible=(
            'Rear end loose on power (driver defensive)',
            'Diff/axle locking on power-up causing inside wheel spin',
        ),
        insufficient_evidence_cases=(
            'Cannot see wheel-spin without wheel-speed or ECU data',
            'Cannot tell intentional "waiting" from "kart is unstable on throttle" without steering angle',
        ),
        evidence_honesty_note=(
            'Setup changes to diff/rear stiffness are speculative from GPS data. '
            'Always rule out technique first.'
        ),
    ),
    strategy_flags=StrategyFlags(
        consistency_relevance='High — exit throttle timing is a core lap-time consistency signal',
        tyre_management_relevance='Medium — earlier throttle = more rear tyre load; manage in long stints',
        traffic_overtake_relevance='High — late throttle on exit forecasts weak straight-line speed',
        stint_execution_relevance='High — target execution area once tyres are up to temperature',
        evidence_honesty_note='Consistency evidenced directly; overtake/tyre claims are heuristic',
    ),
))


# ── 6. Weak exit build ───────────────────────────────────────────
_WEAK_EXIT_FEATURES_THRESHOLDS = {
    'hairpin':              {'exit_speed_delta_kph': -3.0},
    'medium_speed_corner':  {'exit_speed_delta_kph': -3.0},
    'fast_corner':          {'exit_speed_delta_kph': -1.5},
    'chicane':              {'exit_speed_delta_kph': -3.5},
    'long_radius':          {'exit_speed_delta_kph': -2.5},
    'unknown':              {'exit_speed_delta_kph': -3.0},
}
_WEAK_EXIT_EVIDENCE_THRESHOLDS = {
    'hairpin':              {'exit_speed_delta_kph': -5.0, 'timing_abs_max': 5.0},
    'medium_speed_corner':  {'exit_speed_delta_kph': -5.0, 'timing_abs_max': 5.0},
    'fast_corner':          {'exit_speed_delta_kph': -3.0, 'timing_abs_max': 4.0},
    'chicane':              {'exit_speed_delta_kph': -6.0, 'timing_abs_max': 5.0},
    'long_radius':          {'exit_speed_delta_kph': -4.0, 'timing_abs_max': 5.0},
    'unknown':              {'exit_speed_delta_kph': -5.0, 'timing_abs_max': 5.0},
}


def _weak_exit_features_archetype(cf, archetype):
    thresh = _WEAK_EXIT_FEATURES_THRESHOLDS.get(
        archetype, _WEAK_EXIT_FEATURES_THRESHOLDS['unknown'])
    return cf.exit_speed_delta_kph < thresh['exit_speed_delta_kph']


def _weak_exit_evidence_archetype(ev, archetype):
    thresh = _WEAK_EXIT_EVIDENCE_THRESHOLDS.get(
        archetype, _WEAK_EXIT_EVIDENCE_THRESHOLDS['unknown'])
    return (
        (ev.get('exit_speed_delta_kph') or 0) < thresh['exit_speed_delta_kph']
        and abs(ev.get('throttle_pickup_delta_m') or 0) < thresh['timing_abs_max']
    )


_register(CoachingPattern(
    pattern_id='weak_exit_build',
    version='2.0.0',
    label='Weak exit speed build',
    title='Weak exit speed build',
    phase='exit',
    polarity='weakness',
    trainability=0.85,
    metric_key='exit_speed_delta_kph',
    direction='negative_is_bad',
    sensor_requirements=('gps_speed', 'reference_lap_trace'),
    archetype_applicability=('*',),
    aliases=(),
    consumer_keys={
        'driver_development':    'weak_exit_build',
        'coaching_intelligence': 'weak_exit_build',
        'prescriptive_coaching': 'weak_exit_build',
    },
    related_patterns=('late_throttle_pickup', 'apex_low_speed'),
    detect_features=lambda cf: cf.exit_speed_delta_kph < -3.0,
    detect_evidence=lambda ev: (
        (ev.get('exit_speed_delta_kph') or 0) < -5.0
        and abs(ev.get('throttle_pickup_delta_m') or 0) < 5.0
    ),
    detect_features_archetype=_weak_exit_features_archetype,
    detect_evidence_archetype=_weak_exit_evidence_archetype,
    archetype_thresholds={
        'corner_features': _WEAK_EXIT_FEATURES_THRESHOLDS,
        'evidence_dict':   _WEAK_EXIT_EVIDENCE_THRESHOLDS,
    },
    confidence_fn_evidence=lambda ev, pkt: min(1.0,
        0.5 * pkt.get('confidence', 0.5)
        + 0.5 * (1.0 if abs(ev.get('exit_speed_delta_kph', 0)) > 8 else 0.5)
    ),
    detection_descriptions={
        'corner_features': 'exit_speed_delta_kph < -3.0 (archetype-adjusted)',
        'evidence_dict': 'exit_speed_delta_kph < -5 AND |throttle_pickup_delta_m|<5 (archetype-adjusted)',
    },
    trainability_governance=TrainabilityGovernance(
        rationale=(
            'Exit build is closely linked to exit line and throttle commitment. '
            'Trainability 0.85 reflects literature consensus — slightly below '
            'brake release since line change is slower to ingrain.'
        ),
        provisional=False,
    ),
    coaching_template=CoachingTemplate(
        likely_causes=(
            'Exit line too tight — not using full track width on exit',
            'Maintaining too much steering angle while accelerating (scrubbing speed)',
            'Insufficient throttle commitment through the exit phase',
        ),
        coaching_actions=(
            'Open the exit: begin straightening the wheel {exit_adjust_m} m earlier',
            'Use FULL track width on exit — every meter of straighter line adds exit speed',
            'If the kart pushes wide, reduce speed earlier rather than tightening exit',
        ),
        driver_cues=(
            'Look: eyes to the exit kerb/edge EARLIER than you think you should',
            'Feel: the kart should be pulling you toward the outside of the track on exit',
        ),
        template_params=('exit_adjust_m',),
        sensor_note='Exit speed from GPS speed at 30m after corner exit point',
    ),
    real_life_coaching=RealLifeCoaching(
        actions=(
            'Open the exit: begin straightening the wheel 3–5 m earlier',
            'Use FULL track width on exit — every meter of straighter line adds exit speed',
            'If the kart pushes wide, reduce speed earlier rather than tightening exit',
        ),
        driver_cues=(
            'Look: eyes to the exit kerb/edge EARLIER than feels comfortable',
            'Feel: the kart should be pulling toward the outside of the track on exit',
        ),
        validation_metrics=(
            'Exit speed improves by 1+ kph at the exit checkpoint',
            'Line uses within 0.5 m of outer track edge on exit',
            'No throttle pickup delay — commitment holds',
        ),
        sensor_honesty_note=(
            'Exit speed is GPS-speed at a fixed 30 m post-apex checkpoint. '
            'Line use is inferred from position — no steering angle measured.'
        ),
    ),
    sim_coaching=SimCoaching(
        trainable_in_sim=(
            'Line opening — widening exits to the outside of the track',
            'Throttle commitment through exit',
        ),
        transfer_to_real_life=(
            'Strong transfer for line choice. Throttle commitment transfer is '
            'moderate — sim tyre models often allow more aggressive exit throttle '
            'than real. Verify on track with a gradual progression.'
        ),
        non_transfer_risks=(
            'Sim may allow wider exit line due to lighter understeer modelling',
            'Sim kerb/rumble penalty is often softer than real — do not learn reliance on kerbs that do not exist',
        ),
        recommended_sim_exercises=(
            'Same-corner drill: widen exit by one kart-width per lap-pair',
            'Paired-exit comparison: "tight" lap, "full-width" lap, compare speed at 60 m past apex',
        ),
        transfer_confidence='medium',
    ),
    setup_hints=SetupHints(
        driver_first=(
            'Confirm throttle pickup timing is on reference',
            'Confirm apex was hit — weak exit often comes from a missed apex',
        ),
        setup_possible=(
            'Rear end loose on power (driver backs off throttle)',
            'Diff/axle behaviour limiting inside-wheel drive',
            'Excess rear camber or toe-in scrubbing exit speed',
        ),
        insufficient_evidence_cases=(
            'Cannot see wheel spin on power without wheel-speed data',
            'Cannot tell "driver lifting" from "kart not accelerating" without throttle-position data',
        ),
        evidence_honesty_note=(
            'Setup changes for exit are common and legitimate — but require '
            'tyre-temperature or wheel-speed data to validate. Driver-first still applies.'
        ),
    ),
    strategy_flags=StrategyFlags(
        consistency_relevance='High — exit speed compounds into following-straight time',
        tyre_management_relevance='Medium — more exit commitment raises rear tyre load',
        traffic_overtake_relevance='High — weak exit is the single biggest overtake invitation on the next straight',
        stint_execution_relevance='High — target execution area throughout stint',
        evidence_honesty_note='Consistency evidenced directly; straight-line gain is computed, not sensed',
    ),
))


# ── 7. Line deviation ────────────────────────────────────────────
_LINE_DEVIATION_FEATURES_THRESHOLDS = {
    'hairpin':              {'line_deviation_m': 0.8},
    'medium_speed_corner':  {'line_deviation_m': 0.8},
    'fast_corner':          {'line_deviation_m': 0.5},
    'chicane':              {'line_deviation_m': 0.9},
    'long_radius':          {'line_deviation_m': 1.0},
    'unknown':              {'line_deviation_m': 0.8},
}
_LINE_DEVIATION_EVIDENCE_THRESHOLDS = {
    'hairpin':              {'line_deviation_rms_m': 1.5},
    'medium_speed_corner':  {'line_deviation_rms_m': 1.5},
    'fast_corner':          {'line_deviation_rms_m': 1.0},
    'chicane':              {'line_deviation_rms_m': 1.7},
    'long_radius':          {'line_deviation_rms_m': 2.0},
    'unknown':              {'line_deviation_rms_m': 1.5},
}


def _line_deviation_features_archetype(cf, archetype):
    thresh = _LINE_DEVIATION_FEATURES_THRESHOLDS.get(
        archetype, _LINE_DEVIATION_FEATURES_THRESHOLDS['unknown'])
    return cf.line_deviation_m > thresh['line_deviation_m']


def _line_deviation_evidence_archetype(ev, archetype):
    thresh = _LINE_DEVIATION_EVIDENCE_THRESHOLDS.get(
        archetype, _LINE_DEVIATION_EVIDENCE_THRESHOLDS['unknown'])
    return (ev.get('line_deviation_rms_m') or 0) > thresh['line_deviation_rms_m']


_register(CoachingPattern(
    pattern_id='line_deviation',
    version='2.0.0',
    label='Inconsistent line / path deviation',
    title='Inconsistent line / path deviation',
    phase='apex',
    polarity='weakness',
    trainability=0.7,
    # CornerFeatures uses .line_deviation_m; evidence dict uses line_deviation_rms_m.
    # metric_key matches the features attribute (used by BEHAVIOR_DEFS trend code).
    metric_key='line_deviation_m',
    direction='positive_is_bad',
    sensor_requirements=('gps_position', 'reference_lap_trace'),
    archetype_applicability=('*',),
    aliases=('path_variance',),
    consumer_keys={
        'driver_development':    'line_deviation',
        'coaching_intelligence': 'path_variance',
        'prescriptive_coaching': 'line_deviation',
    },
    related_patterns=(),
    detect_features=lambda cf: cf.line_deviation_m > 0.8,
    detect_evidence=lambda ev: (ev.get('line_deviation_rms_m') or 0) > 1.5,
    detect_features_archetype=_line_deviation_features_archetype,
    detect_evidence_archetype=_line_deviation_evidence_archetype,
    archetype_thresholds={
        'corner_features': _LINE_DEVIATION_FEATURES_THRESHOLDS,
        'evidence_dict':   _LINE_DEVIATION_EVIDENCE_THRESHOLDS,
    },
    confidence_fn_evidence=lambda ev, pkt: min(1.0,
        0.5 * pkt.get('confidence', 0.5)
        + 0.5 * min(1.0, (ev.get('line_deviation_rms_m', 0)) / 3.0)
    ),
    detection_descriptions={
        'corner_features': 'line_deviation_m > 0.8 (archetype-adjusted)',
        'evidence_dict': 'line_deviation_rms_m > 1.5 (archetype-adjusted)',
    },
    trainability_governance=TrainabilityGovernance(
        rationale=(
            'Line repeatability is the slowest-to-ingrain skill in this library '
            '(0.7) because it demands fixed visual references and sustained focus, '
            'both of which fade under fatigue. Lower trainability reflects time-to-'
            'improvement, NOT low importance.'
        ),
        provisional=False,
    ),
    coaching_template=CoachingTemplate(
        likely_causes=(
            'No fixed reference points for turn-in, apex, and exit',
            'Reacting to the kart instead of placing it deliberately',
            'Different entry speed on each lap causing different geometry',
        ),
        coaching_actions=(
            'Pick ONE line and repeat it exactly for 5+ consecutive laps',
            'Use fixed visual markers: turn-in point, apex kerb contact, exit target',
            'Speed is secondary until the line is repeatable',
        ),
        driver_cues=(
            'Feel: same steering input, same load, same timing each lap',
            'Look: same visual references every lap — track features, not feelings',
        ),
        template_params=(),
        sensor_note='Line deviation = RMS of lateral offset difference from reference (GPS-derived)',
    ),
    real_life_coaching=RealLifeCoaching(
        actions=(
            'Pick ONE line and repeat it exactly for 5+ consecutive laps',
            'Use fixed visual markers: turn-in, apex kerb contact, exit target',
            'Speed is secondary until the line is repeatable',
        ),
        driver_cues=(
            'Feel: same steering input, same load, same timing each lap',
            'Look: same visual references every lap — track features, not feelings',
        ),
        validation_metrics=(
            'Line RMS drops below 0.5 m across 5 consecutive laps',
            'Turn-in point clusters within 2 m across laps',
            'Apex kerb contact consistent (same wheel over same crack)',
        ),
        sensor_honesty_note=(
            'Line deviation is RMS of lateral offset from reference line. '
            'GPS-only — cannot distinguish intentional line variation from mistakes.'
        ),
    ),
    sim_coaching=SimCoaching(
        trainable_in_sim=(
            'Line repeatability drills — same line 10 laps in a row',
            'Reference-point memorisation — pick 3 markers per corner',
        ),
        transfer_to_real_life=(
            'High transfer for geometric repeatability. Visual markers transfer '
            'directly once the sim track geometry matches the real track.'
        ),
        non_transfer_risks=(
            'Sim tracks are usually scanned — markers may exist in real that are missing in sim, and vice versa',
            'Sim visibility/lighting differs from real — references picked in sim may be unreadable in real',
        ),
        recommended_sim_exercises=(
            'Line-lock drills: 10 laps targeting same apex and exit markers',
            'Metronome corner: one corner, 20 laps, zero variation goal',
        ),
        transfer_confidence='high',
    ),
    setup_hints=SetupHints(
        driver_first=(
            'Confirm the driver has FIXED visual references — not feel-based turn-in',
            'Confirm entry speed is stable before attributing line variance to technique',
        ),
        setup_possible=(
            'Kart understeering on entry pushes the line wide — front-end grip deficit',
            'Kart oversteering on apex tightens the line — rear-end grip deficit',
        ),
        insufficient_evidence_cases=(
            'Cannot tell understeer from oversteer contribution without steering angle',
            'Cannot separate driver reaction from mechanical reaction without G-force data',
        ),
        evidence_honesty_note=(
            'Line variance is often driver-dominant. Setup changes should only be '
            'pursued after dedicated line-lock sessions show no improvement.'
        ),
    ),
    strategy_flags=StrategyFlags(
        consistency_relevance='High — line variance IS a lap-time variance signal',
        tyre_management_relevance='Low — line variance stresses tyres unpredictably',
        traffic_overtake_relevance='Medium — consistent line is a defensive prerequisite in traffic',
        stint_execution_relevance='High — line lock is the foundation of consistency',
        evidence_honesty_note='Consistency is directly evidenced; other strategy claims are heuristic',
    ),
))


# ── 8. Strong braking (strength) ─────────────────────────────────
_register(CoachingPattern(
    pattern_id='strong_braking',
    version='2.0.0',
    label='Strong braking consistency',
    title='Strong braking consistency',
    phase='entry',
    polarity='strength',
    trainability=0.0,
    metric_key='brake_point_delta_m',
    direction='neutral_is_good',
    sensor_requirements=('gps_speed', 'derived_brake_onset', 'reference_lap_trace'),
    archetype_applicability=('*',),
    aliases=(),
    consumer_keys={
        'driver_development':    'strong_braking',
    },
    related_patterns=(),
    detect_features=lambda cf: (
        cf.brake_point_delta_m is not None
        and abs(cf.brake_point_delta_m) < 3.0
        and cf.time_delta_ms < 50.0
    ),
    detect_evidence=None,
    detection_descriptions={
        'corner_features': '|brake_point_delta_m|<3 AND time_delta_ms<50',
    },
    coaching_template=None,
    trainability_governance=TrainabilityGovernance(
        rationale='Strengths are not trainability-weighted — preserve via positive reinforcement, not targeted practice.',
        provisional=False,
    ),
    # Strengths carry no action blocks. Leaving real_life_coaching,
    # sim_coaching, setup_hints as None is the evidence-honest answer —
    # there is nothing to fix.
    real_life_coaching=None,
    sim_coaching=None,
    setup_hints=None,
    strategy_flags=StrategyFlags(
        consistency_relevance='Low — strong braking already stable',
        tyre_management_relevance='not_applicable',
        traffic_overtake_relevance='High — strong braking is a defensive asset in wheel-to-wheel',
        stint_execution_relevance='not_applicable',
        evidence_honesty_note='Strengths are recognised, not coached.',
    ),
))


# ── 9. Strong exit (strength) ────────────────────────────────────
_register(CoachingPattern(
    pattern_id='strong_exit',
    version='2.0.0',
    label='Above-reference exit build',
    title='Above-reference exit build',
    phase='exit',
    polarity='strength',
    trainability=0.0,
    metric_key='exit_speed_delta_kph',
    direction='positive_is_good',
    sensor_requirements=('gps_speed', 'reference_lap_trace'),
    archetype_applicability=('*',),
    aliases=(),
    consumer_keys={
        'driver_development':    'strong_exit',
    },
    related_patterns=(),
    detect_features=lambda cf: cf.exit_speed_delta_kph > 2.0,
    detect_evidence=None,
    detection_descriptions={
        'corner_features': 'exit_speed_delta_kph > 2.0',
    },
    coaching_template=None,
    trainability_governance=TrainabilityGovernance(
        rationale='Strengths are not trainability-weighted — preserve via positive reinforcement, not targeted practice.',
        provisional=False,
    ),
    real_life_coaching=None,
    sim_coaching=None,
    setup_hints=None,
    strategy_flags=StrategyFlags(
        consistency_relevance='Low — strong exit already stable',
        tyre_management_relevance='not_applicable',
        traffic_overtake_relevance='High — strong exit is the primary overtake-on-straight enabler',
        stint_execution_relevance='not_applicable',
        evidence_honesty_note='Strengths are recognised, not coached.',
    ),
))


# ── 10. Unstable corner execution (new v2.0.0) ──────────────────
# Compound pattern — a corner where multiple signals disagree lap-to-lap.
# Speed-derived and position-derived only; no CAN/pressure sensors needed.
_UNSTABLE_FEATURES_THRESHOLDS = {
    'hairpin':              {'line_deviation_m': 0.9, 'confidence': 0.4},
    'medium_speed_corner':  {'line_deviation_m': 0.8, 'confidence': 0.4},
    'fast_corner':          {'line_deviation_m': 0.5, 'confidence': 0.5},
    'chicane':              {'line_deviation_m': 1.0, 'confidence': 0.4},
    'long_radius':          {'line_deviation_m': 1.1, 'confidence': 0.4},
    'unknown':              {'line_deviation_m': 0.8, 'confidence': 0.4},
}
_UNSTABLE_EVIDENCE_THRESHOLDS = {
    'hairpin':              {'line_deviation_rms_m': 1.5, 'brake_abs_min': 5.0, 'throttle_abs_min': 5.0},
    'medium_speed_corner':  {'line_deviation_rms_m': 1.5, 'brake_abs_min': 5.0, 'throttle_abs_min': 5.0},
    'fast_corner':          {'line_deviation_rms_m': 1.0, 'brake_abs_min': 4.0, 'throttle_abs_min': 4.0},
    'chicane':              {'line_deviation_rms_m': 1.7, 'brake_abs_min': 5.0, 'throttle_abs_min': 5.0},
    'long_radius':          {'line_deviation_rms_m': 2.0, 'brake_abs_min': 6.0, 'throttle_abs_min': 6.0},
    'unknown':              {'line_deviation_rms_m': 1.5, 'brake_abs_min': 5.0, 'throttle_abs_min': 5.0},
}


def _unstable_corner_features_archetype(cf, archetype):
    thresh = _UNSTABLE_FEATURES_THRESHOLDS.get(
        archetype, _UNSTABLE_FEATURES_THRESHOLDS['unknown'])
    return (
        cf.line_deviation_m > thresh['line_deviation_m']
        and cf.confidence < thresh['confidence']
    )


def _unstable_corner_evidence_archetype(ev, archetype):
    thresh = _UNSTABLE_EVIDENCE_THRESHOLDS.get(
        archetype, _UNSTABLE_EVIDENCE_THRESHOLDS['unknown'])
    return (
        (ev.get('line_deviation_rms_m') or 0) > thresh['line_deviation_rms_m']
        and abs(ev.get('brake_point_delta_m') or 0) > thresh['brake_abs_min']
        and abs(ev.get('throttle_pickup_delta_m') or 0) > thresh['throttle_abs_min']
    )


_register(CoachingPattern(
    pattern_id='unstable_corner_execution',
    version='2.0.0',
    label='Unstable corner execution',
    title='Unstable corner execution — line and timing both drifting',
    phase='apex',
    polarity='weakness',
    trainability=0.65,
    metric_key='line_deviation_m',
    direction='positive_is_bad',
    sensor_requirements=(
        'gps_speed', 'gps_position',
        'derived_brake_onset', 'derived_throttle_onset',
        'reference_lap_trace',
    ),
    archetype_applicability=('*',),
    aliases=(),
    consumer_keys={},  # no legacy consumer — library-canonical id only
    related_patterns=('line_deviation', 'apex_low_speed'),
    detect_features=lambda cf: cf.line_deviation_m > 0.8 and cf.confidence < 0.4,
    detect_evidence=lambda ev: (
        (ev.get('line_deviation_rms_m') or 0) > 1.5
        and abs(ev.get('brake_point_delta_m') or 0) > 5.0
        and abs(ev.get('throttle_pickup_delta_m') or 0) > 5.0
    ),
    detect_features_archetype=_unstable_corner_features_archetype,
    detect_evidence_archetype=_unstable_corner_evidence_archetype,
    archetype_thresholds={
        'corner_features': _UNSTABLE_FEATURES_THRESHOLDS,
        'evidence_dict':   _UNSTABLE_EVIDENCE_THRESHOLDS,
    },
    confidence_fn_evidence=lambda ev, pkt: min(1.0,
        0.4 * pkt.get('confidence', 0.5)
        + 0.3 * min(1.0, (ev.get('line_deviation_rms_m', 0)) / 3.0)
        + 0.3 * (1.0 if abs(ev.get('brake_point_delta_m') or 0) > 8 else 0.5)
    ),
    detection_descriptions={
        'corner_features': 'line_deviation_m > 0.8 AND confidence < 0.4 (archetype-adjusted)',
        'evidence_dict': 'line_deviation_rms_m > 1.5 AND |brake_delta|>5 AND |throttle_delta|>5 (archetype-adjusted)',
    },
    trainability_governance=TrainabilityGovernance(
        rationale=(
            'Compound pattern — slower to fix than a single-signal weakness. '
            '0.65 reflects that the driver must first stabilise ONE of the '
            'component patterns (line, brake, or throttle) before this one '
            'resolves.'
        ),
        provisional=True,
    ),
    coaching_template=None,
    real_life_coaching=RealLifeCoaching(
        actions=(
            'Fix ONE component first — pick line, brake point, or throttle initiation',
            'Lock down fixed visual references for EVERY phase of the corner',
            'Do NOT try to correct multiple signals in the same lap — serialise the drills',
        ),
        driver_cues=(
            'Feel: pick the component that feels least repeatable; start there',
            'Look: one reference at a time — apex kerb this run, brake marker next',
        ),
        validation_metrics=(
            'Targeted component variance drops first (line OR brake OR throttle)',
            'Other components follow within 5–10 laps — the corner stabilises holistically',
        ),
        sensor_honesty_note=(
            'Compound detection — requires line + brake + throttle signals. '
            'All speed / position / speed-derivative sensors only.'
        ),
    ),
    sim_coaching=SimCoaching(
        trainable_in_sim=(
            'Sequenced component-fixation drills — 10 laps per component',
            'Repetition under fatigue — drive sessions past mental tiredness to see which component breaks first',
        ),
        transfer_to_real_life=(
            'Moderate — compound-pattern practice is highly sim-friendly, but '
            'real-car fatigue and heat introduce failure modes the sim rarely models.'
        ),
        non_transfer_risks=(
            'Sim stress is psychological only — no physical heat, vibration, or g-load fatigue',
            'Sim consequences (track limits, contact) are softer — may mask bad habits',
        ),
        recommended_sim_exercises=(
            'Marathon-mode sim sessions (30+ min uninterrupted) to find the first-to-fail component',
            'Component-lock drills: pick one component per 10-lap stint',
        ),
        transfer_confidence='medium',
    ),
    setup_hints=SetupHints(
        driver_first=(
            'Always address driver-side instability first — setup will not fix an undisciplined driver',
            'Confirm whether instability is fatigue-dependent (later laps worse)',
        ),
        setup_possible=(
            'Kart nervous on corner entry — front-end grip deficit forcing compensation',
            'Kart loose on exit — rear-end grip deficit forcing variable throttle',
        ),
        insufficient_evidence_cases=(
            'Cannot attribute compound instability to any single setup item without steering/G-force data',
            'Cannot rule out fatigue without multi-session comparison',
        ),
        evidence_honesty_note=(
            'Compound instability is MOST OFTEN driver + fatigue. Setup changes '
            'should be a last resort and require corroborating evidence from '
            'tyre temps or wheel-speed data.'
        ),
    ),
    strategy_flags=StrategyFlags(
        consistency_relevance='High — unstable corners are the dominant lap-time variance source',
        tyre_management_relevance='Medium — inconsistent loading accelerates tyre wear unpredictably',
        traffic_overtake_relevance='High — unstable corner is a defensive liability and overtake target',
        stint_execution_relevance='High — target execution area; lap-time floor cannot drop below this',
        evidence_honesty_note='Consistency is directly evidenced; wear/strategy claims are heuristic',
    ),
))


# ── 11. Likely understeer proxy (new v2.0.0) ────────────────────
# Speed-derived proxy for understeer tendency. Honest in its naming
# ('likely_*_proxy') and in the provisional trainability flag because
# without lateral-G / steering-angle data the attribution is never definitive.
_UNDERSTEER_FEATURES_THRESHOLDS = {
    'hairpin':              {'min_speed_delta_kph': -3.0, 'line_deviation_m': 0.8, 'exit_speed_delta_kph': -2.0},
    'medium_speed_corner':  {'min_speed_delta_kph': -3.0, 'line_deviation_m': 0.8, 'exit_speed_delta_kph': -2.0},
    'fast_corner':          {'min_speed_delta_kph': -1.5, 'line_deviation_m': 0.5, 'exit_speed_delta_kph': -1.5},
    'chicane':              {'min_speed_delta_kph': -3.5, 'line_deviation_m': 0.9, 'exit_speed_delta_kph': -2.5},
    'long_radius':          {'min_speed_delta_kph': -2.5, 'line_deviation_m': 1.0, 'exit_speed_delta_kph': -2.0},
    'unknown':              {'min_speed_delta_kph': -3.0, 'line_deviation_m': 0.8, 'exit_speed_delta_kph': -2.0},
}
_UNDERSTEER_EVIDENCE_THRESHOLDS = {
    'hairpin':              {'min_speed_delta_kph': -5.0, 'line_deviation_rms_m': 1.5, 'exit_speed_delta_kph': -3.0},
    'medium_speed_corner':  {'min_speed_delta_kph': -5.0, 'line_deviation_rms_m': 1.5, 'exit_speed_delta_kph': -3.0},
    'fast_corner':          {'min_speed_delta_kph': -3.0, 'line_deviation_rms_m': 1.0, 'exit_speed_delta_kph': -2.0},
    'chicane':              {'min_speed_delta_kph': -6.0, 'line_deviation_rms_m': 1.7, 'exit_speed_delta_kph': -3.0},
    'long_radius':          {'min_speed_delta_kph': -4.0, 'line_deviation_rms_m': 2.0, 'exit_speed_delta_kph': -3.0},
    'unknown':              {'min_speed_delta_kph': -5.0, 'line_deviation_rms_m': 1.5, 'exit_speed_delta_kph': -3.0},
}


def _understeer_features_archetype(cf, archetype):
    t = _UNDERSTEER_FEATURES_THRESHOLDS.get(
        archetype, _UNDERSTEER_FEATURES_THRESHOLDS['unknown'])
    return (
        cf.min_speed_delta_kph < t['min_speed_delta_kph']
        and cf.line_deviation_m > t['line_deviation_m']
        and cf.exit_speed_delta_kph < t['exit_speed_delta_kph']
    )


def _understeer_evidence_archetype(ev, archetype):
    t = _UNDERSTEER_EVIDENCE_THRESHOLDS.get(
        archetype, _UNDERSTEER_EVIDENCE_THRESHOLDS['unknown'])
    return (
        (ev.get('min_speed_delta_kph') or 0) < t['min_speed_delta_kph']
        and (ev.get('line_deviation_rms_m') or 0) > t['line_deviation_rms_m']
        and (ev.get('exit_speed_delta_kph') or 0) < t['exit_speed_delta_kph']
    )


_register(CoachingPattern(
    pattern_id='likely_understeer_proxy',
    version='2.0.0',
    label='Likely understeer (proxy)',
    title='Likely understeer — speed + line + exit-speed proxy',
    phase='apex',
    polarity='weakness',
    trainability=0.5,
    metric_key='line_deviation_m',
    direction='positive_is_bad',
    sensor_requirements=('gps_speed', 'gps_position', 'reference_lap_trace'),
    archetype_applicability=('*',),
    aliases=(),
    consumer_keys={},  # library-canonical only (new pattern)
    related_patterns=('apex_low_speed', 'line_deviation', 'weak_exit_build'),
    detect_features=lambda cf: (
        cf.min_speed_delta_kph < -3.0
        and cf.line_deviation_m > 0.8
        and cf.exit_speed_delta_kph < -2.0
    ),
    detect_evidence=lambda ev: (
        (ev.get('min_speed_delta_kph') or 0) < -5.0
        and (ev.get('line_deviation_rms_m') or 0) > 1.5
        and (ev.get('exit_speed_delta_kph') or 0) < -3.0
    ),
    detect_features_archetype=_understeer_features_archetype,
    detect_evidence_archetype=_understeer_evidence_archetype,
    archetype_thresholds={
        'corner_features': _UNDERSTEER_FEATURES_THRESHOLDS,
        'evidence_dict':   _UNDERSTEER_EVIDENCE_THRESHOLDS,
    },
    confidence_fn_evidence=lambda ev, pkt: min(1.0,
        0.3 * pkt.get('confidence', 0.5)
        + 0.35 * (1.0 if abs(ev.get('min_speed_delta_kph', 0)) > 5 else 0.5)
        + 0.35 * (1.0 if abs(ev.get('exit_speed_delta_kph', 0)) > 3 else 0.5)
    ),
    detection_descriptions={
        'corner_features': 'min_speed_delta_kph<-3 AND line_deviation_m>0.8 AND exit_speed_delta_kph<-2 (archetype-adjusted)',
        'evidence_dict': 'min_speed_delta_kph<-5 AND line_deviation_rms_m>1.5 AND exit_speed_delta_kph<-3 (archetype-adjusted)',
    },
    trainability_governance=TrainabilityGovernance(
        rationale=(
            'PROVISIONAL: pattern is a proxy (no steering angle, no lateral G). '
            'Trainability 0.5 acknowledges that part of the phenomenon may be '
            'mechanical (understeer-biased setup) and not driver-trainable. '
            'Calibration is from a single-track dataset; revisit with multi-'
            'track evidence.'
        ),
        provisional=True,
    ),
    coaching_template=None,
    real_life_coaching=RealLifeCoaching(
        actions=(
            'Treat the driver side first: later turn-in, trail-braking to rotate',
            'Test a reduced entry speed for 3 laps — if understeer disappears, entry speed was the cause',
            'If reduced entry does not fix it, escalate to setup analysis',
        ),
        driver_cues=(
            'Feel: front end pushing wide through middle of corner',
            'Feel: steering angle needed exceeds what feels normal for this corner',
        ),
        validation_metrics=(
            'Apex minimum speed rises or stays within -2 kph of reference',
            'Line RMS drops below pattern threshold',
            'Exit speed improves — understeer has cleared',
        ),
        sensor_honesty_note=(
            'PROXY — no direct understeer measurement. Combination of low apex '
            'speed + wide line + weak exit is symptomatic, not diagnostic.'
        ),
    ),
    sim_coaching=SimCoaching(
        trainable_in_sim=(
            'Trail-brake depth drills to rotate the car without steering angle',
            'Reduced-entry-speed drills to test driver vs mechanical cause',
        ),
        transfer_to_real_life=(
            'Moderate — sim understeer models are often caricatured. A sim drill '
            'that "fixes" understeer may not address a real-car mechanical cause.'
        ),
        non_transfer_risks=(
            'Sim may mis-model tyre thermal grip loss, hiding stint-dependent understeer',
            'Sim setups rarely transfer 1:1 to real — setup-change recommendations from sim are speculative',
        ),
        recommended_sim_exercises=(
            'A/B drill: baseline setup vs +5% front rebound, observe whether understeer symptom persists',
            'Slow-hairpin driver-focus: trail-brake only, 10-lap block',
        ),
        transfer_confidence='low',
    ),
    setup_hints=SetupHints(
        driver_first=(
            'Verify the driver has tested a later turn-in and trail-braking first',
            'Verify the driver has tested a lower entry speed (elimination of driver cause)',
        ),
        setup_possible=(
            'Front tyre pressure too low (reduces front contact patch sharpness)',
            'Front bar too soft (insufficient weight transfer)',
            'Kart axle too stiff for corner radius',
        ),
        insufficient_evidence_cases=(
            'Cannot tell mechanical from thermal understeer without tyre temps',
            'Cannot rule out driver without steering-angle data',
        ),
        evidence_honesty_note=(
            'CRITICAL: "likely_understeer_proxy" is a hypothesis, not a diagnosis. '
            'Setup changes on this signal alone are high-risk without corroborating data.'
        ),
    ),
    strategy_flags=StrategyFlags(
        consistency_relevance='Medium — understeer is usually stable within a stint, variable across stints as tyres heat',
        tyre_management_relevance='High — chronic understeer destroys front tyres; flag for setup review',
        traffic_overtake_relevance='High — understeer in traffic is dangerous and forecast-able',
        stint_execution_relevance='Medium — must be worked around if setup cannot be changed',
        evidence_honesty_note='Wear/thermal claims are heuristic; no direct tyre-state measurement',
    ),
))


# ── 12. Likely oversteer proxy (new v2.0.0) ─────────────────────
# Oversteer proxy: early throttle initiation + tight exit line + weak
# exit-speed build (driver scrubbing speed to contain the rear slide).
_OVERSTEER_FEATURES_THRESHOLDS = {
    'hairpin':              {'throttle_pickup_delta_m': -3.0, 'line_deviation_m': 0.6, 'exit_speed_delta_kph': -2.0},
    'medium_speed_corner':  {'throttle_pickup_delta_m': -3.0, 'line_deviation_m': 0.6, 'exit_speed_delta_kph': -2.0},
    'fast_corner':          {'throttle_pickup_delta_m': -5.0, 'line_deviation_m': 0.4, 'exit_speed_delta_kph': -1.5},
    'chicane':              {'throttle_pickup_delta_m': -2.5, 'line_deviation_m': 0.7, 'exit_speed_delta_kph': -2.5},
    'long_radius':          {'throttle_pickup_delta_m': -4.0, 'line_deviation_m': 0.8, 'exit_speed_delta_kph': -2.0},
    'unknown':              {'throttle_pickup_delta_m': -3.0, 'line_deviation_m': 0.6, 'exit_speed_delta_kph': -2.0},
}
_OVERSTEER_EVIDENCE_THRESHOLDS = {
    'hairpin':              {'throttle_pickup_delta_m': -3.0, 'line_deviation_rms_m': 1.2, 'exit_speed_delta_kph': -3.0},
    'medium_speed_corner':  {'throttle_pickup_delta_m': -3.0, 'line_deviation_rms_m': 1.2, 'exit_speed_delta_kph': -3.0},
    'fast_corner':          {'throttle_pickup_delta_m': -5.0, 'line_deviation_rms_m': 0.8, 'exit_speed_delta_kph': -2.0},
    'chicane':              {'throttle_pickup_delta_m': -2.5, 'line_deviation_rms_m': 1.4, 'exit_speed_delta_kph': -3.0},
    'long_radius':          {'throttle_pickup_delta_m': -4.0, 'line_deviation_rms_m': 1.5, 'exit_speed_delta_kph': -3.0},
    'unknown':              {'throttle_pickup_delta_m': -3.0, 'line_deviation_rms_m': 1.2, 'exit_speed_delta_kph': -3.0},
}


def _oversteer_features_archetype(cf, archetype):
    t = _OVERSTEER_FEATURES_THRESHOLDS.get(
        archetype, _OVERSTEER_FEATURES_THRESHOLDS['unknown'])
    return (
        (cf.throttle_pickup_delta_m or 0) < t['throttle_pickup_delta_m']
        and cf.line_deviation_m > t['line_deviation_m']
        and cf.exit_speed_delta_kph < t['exit_speed_delta_kph']
    )


def _oversteer_evidence_archetype(ev, archetype):
    t = _OVERSTEER_EVIDENCE_THRESHOLDS.get(
        archetype, _OVERSTEER_EVIDENCE_THRESHOLDS['unknown'])
    return (
        (ev.get('throttle_pickup_delta_m') or 0) < t['throttle_pickup_delta_m']
        and (ev.get('line_deviation_rms_m') or 0) > t['line_deviation_rms_m']
        and (ev.get('exit_speed_delta_kph') or 0) < t['exit_speed_delta_kph']
    )


_register(CoachingPattern(
    pattern_id='likely_oversteer_proxy',
    version='2.0.0',
    label='Likely oversteer (proxy)',
    title='Likely oversteer — early throttle + tight line + weak exit proxy',
    phase='exit',
    polarity='weakness',
    trainability=0.5,
    metric_key='exit_speed_delta_kph',
    direction='negative_is_bad',
    sensor_requirements=(
        'gps_speed', 'gps_position',
        'derived_throttle_onset', 'reference_lap_trace',
    ),
    archetype_applicability=('*',),
    aliases=(),
    consumer_keys={},
    related_patterns=('weak_exit_build', 'line_deviation'),
    detect_features=lambda cf: (
        (cf.throttle_pickup_delta_m or 0) < -3.0
        and cf.line_deviation_m > 0.6
        and cf.exit_speed_delta_kph < -2.0
    ),
    detect_evidence=lambda ev: (
        (ev.get('throttle_pickup_delta_m') or 0) < -3.0
        and (ev.get('line_deviation_rms_m') or 0) > 1.2
        and (ev.get('exit_speed_delta_kph') or 0) < -3.0
    ),
    detect_features_archetype=_oversteer_features_archetype,
    detect_evidence_archetype=_oversteer_evidence_archetype,
    archetype_thresholds={
        'corner_features': _OVERSTEER_FEATURES_THRESHOLDS,
        'evidence_dict':   _OVERSTEER_EVIDENCE_THRESHOLDS,
    },
    confidence_fn_evidence=lambda ev, pkt: min(1.0,
        0.3 * pkt.get('confidence', 0.5)
        + 0.35 * (1.0 if abs(ev.get('throttle_pickup_delta_m') or 0) > 4 else 0.5)
        + 0.35 * (1.0 if abs(ev.get('exit_speed_delta_kph', 0)) > 3 else 0.5)
    ),
    detection_descriptions={
        'corner_features': 'throttle_pickup_delta_m<-3 AND line_deviation_m>0.6 AND exit_speed_delta_kph<-2 (archetype-adjusted)',
        'evidence_dict': 'throttle_pickup_delta_m<-3 AND line_deviation_rms_m>1.2 AND exit_speed_delta_kph<-3 (archetype-adjusted)',
    },
    trainability_governance=TrainabilityGovernance(
        rationale=(
            'PROVISIONAL: oversteer proxy is less diagnostic than understeer proxy '
            'because "early throttle" can be either driver commitment OR rear-slide '
            'compensation. Trainability 0.5 reflects the mixed attribution.'
        ),
        provisional=True,
    ),
    coaching_template=None,
    real_life_coaching=RealLifeCoaching(
        actions=(
            'Reduce throttle application aggression by 10–15% as a first test',
            'If the kart holds line and exit improves, the cause was driver-side commitment',
            'If the kart still slides, escalate to setup analysis',
        ),
        driver_cues=(
            'Feel: rear end stepping out on throttle application',
            'Feel: having to "catch" the kart with steering correction',
        ),
        validation_metrics=(
            'Exit speed improves by 1+ kph at the exit checkpoint',
            'Line RMS drops below the archetype threshold',
            'Throttle pickup timing returns within 3 m of reference',
        ),
        sensor_honesty_note=(
            'PROXY — no direct oversteer measurement (requires yaw rate + steering angle). '
            'Combination of early throttle + tight line + weak exit is symptomatic only.'
        ),
    ),
    sim_coaching=SimCoaching(
        trainable_in_sim=(
            'Throttle modulation on corner exit',
            'Counter-steer discipline — avoiding throttle when catching slides',
        ),
        transfer_to_real_life=(
            'Moderate — sim oversteer is often overstated for entertainment; '
            'real-kart oversteer window is narrower. Use sim for motor patterns, '
            'not for grip calibration.'
        ),
        non_transfer_risks=(
            'Sim counter-steer sensitivity differs from real steering ratios',
            'Sim throttle curves may mask or amplify real-kart traction windows',
        ),
        recommended_sim_exercises=(
            'Exit modulation drill: same corner, incremental throttle aggression',
            'Catch-and-hold drill: provoke slides in sim, practice calm throttle reduction',
        ),
        transfer_confidence='low',
    ),
    setup_hints=SetupHints(
        driver_first=(
            'Verify the driver has tested reduced throttle aggression',
            'Verify the driver is not lifting on the exit (that hides the rear slip)',
        ),
        setup_possible=(
            'Rear tyre pressure too high (reduced grip patch)',
            'Rear bar too stiff (load transfer not planting rear)',
            'Differential / locked axle releasing inside wheel too aggressively',
        ),
        insufficient_evidence_cases=(
            'Cannot measure rear slip without yaw rate or wheel-speed data',
            'Cannot tell driver-provoked from mechanical oversteer without steering-angle data',
        ),
        evidence_honesty_note=(
            'CRITICAL: "likely_oversteer_proxy" is a hypothesis, not a diagnosis. '
            'A setup change on this signal alone can make the kart worse. '
            'Driver-first always; corroborate with tyre temps before touching setup.'
        ),
    ),
    strategy_flags=StrategyFlags(
        consistency_relevance='Medium — oversteer often grows as rear tyres wear; flag stint-dependent patterns',
        tyre_management_relevance='High — rear tyre overwork; stint lifespan impacted',
        traffic_overtake_relevance='Medium — oversteer limits defensive line choice',
        stint_execution_relevance='Medium — can be worked around with throttle discipline',
        evidence_honesty_note='Wear/traffic claims are heuristic; no direct tyre-state measurement',
    ),
))


# ─────────────────────────────────────────────────────────────────
# Import-time validation
# ─────────────────────────────────────────────────────────────────


def _build_alias_index() -> dict[str, str]:
    """Build {alias_or_canonical_id: canonical_id} lookup.
    Raises on duplicate alias."""
    index: dict[str, str] = {}
    for pid, p in _PATTERNS.items():
        if pid in index:
            raise ValueError(f'duplicate pattern_id: {pid}')
        index[pid] = pid
        for a in p.aliases:
            if a in index:
                raise ValueError(
                    f'alias {a!r} on {pid!r} collides with existing '
                    f'id/alias pointing at {index[a]!r}'
                )
            index[a] = pid
    return index


def _validate() -> None:
    for pid, p in _PATTERNS.items():
        if p.pattern_id != pid:
            raise ValueError(f'pattern_id mismatch: {pid} vs {p.pattern_id}')
        if p.phase not in PHASES:
            raise ValueError(f'{pid}: invalid phase {p.phase!r}')
        if p.polarity not in POLARITIES:
            raise ValueError(f'{pid}: invalid polarity {p.polarity!r}')
        if not 0.0 <= p.trainability <= 1.0:
            raise ValueError(f'{pid}: trainability out of [0,1]: {p.trainability}')
        if p.direction not in DIRECTIONS:
            raise ValueError(f'{pid}: invalid direction {p.direction!r}')
        if p.polarity == 'strength' and p.trainability != 0.0:
            raise ValueError(f'{pid}: strength must have trainability=0')
        for s in p.sensor_requirements:
            if s not in SENSORS:
                raise ValueError(f'{pid}: unknown sensor {s!r}')
        if p.detect_features is None and p.detect_evidence is None:
            raise ValueError(f'{pid}: must declare at least one detection lambda')
        for shape in p.detection_descriptions:
            if shape not in INPUT_SHAPES:
                raise ValueError(f'{pid}: unknown input shape {shape!r}')
        # Template parameter consistency: every {param} placeholder in
        # coaching_actions/driver_cues must be declared in template_params.
        if p.coaching_template:
            declared = set(p.coaching_template.template_params)
            used = set()
            for s in p.coaching_template.coaching_actions + p.coaching_template.driver_cues:
                for tok in _extract_placeholders(s):
                    used.add(tok)
            missing = used - declared
            if missing:
                raise ValueError(
                    f'{pid}: coaching template uses undeclared params {sorted(missing)}'
                )
        # ── v2.0.0 companion block checks ───────────────────────
        # RealLifeCoaching: non-empty actions if declared
        if p.real_life_coaching is not None:
            if not isinstance(p.real_life_coaching, RealLifeCoaching):
                raise ValueError(f'{pid}: real_life_coaching must be RealLifeCoaching instance')
            rlc = p.real_life_coaching
            if not rlc.actions:
                raise ValueError(f'{pid}: real_life_coaching.actions must be non-empty when declared')
            if not rlc.sensor_honesty_note.strip():
                raise ValueError(f'{pid}: real_life_coaching.sensor_honesty_note must be non-empty')
        # SimCoaching: transfer_confidence must be valid; non_transfer_risks
        # must be non-empty unless transfer_confidence == 'high'
        if p.sim_coaching is not None:
            if not isinstance(p.sim_coaching, SimCoaching):
                raise ValueError(f'{pid}: sim_coaching must be SimCoaching instance')
            sc = p.sim_coaching
            if sc.transfer_confidence not in SIM_TRANSFER_CONFIDENCES:
                raise ValueError(
                    f'{pid}: sim_coaching.transfer_confidence must be one of '
                    f'{SIM_TRANSFER_CONFIDENCES!r}, got {sc.transfer_confidence!r}'
                )
            if sc.transfer_confidence != 'high' and not sc.non_transfer_risks:
                raise ValueError(
                    f'{pid}: sim_coaching.non_transfer_risks must be non-empty '
                    f'when transfer_confidence < high (evidence-honest requirement)'
                )
        # SetupHints: evidence_honesty_note mandatory
        if p.setup_hints is not None:
            if not isinstance(p.setup_hints, SetupHints):
                raise ValueError(f'{pid}: setup_hints must be SetupHints instance')
            if not p.setup_hints.evidence_honesty_note.strip():
                raise ValueError(f'{pid}: setup_hints.evidence_honesty_note must be non-empty')
        # StrategyFlags: evidence_honesty_note mandatory
        if p.strategy_flags is not None:
            if not isinstance(p.strategy_flags, StrategyFlags):
                raise ValueError(f'{pid}: strategy_flags must be StrategyFlags instance')
            if not p.strategy_flags.evidence_honesty_note.strip():
                raise ValueError(f'{pid}: strategy_flags.evidence_honesty_note must be non-empty')
        # Archetype thresholds: keys must be valid INPUT_SHAPES, inner keys
        # must be valid ARCHETYPES.
        if p.archetype_thresholds:
            if not isinstance(p.archetype_thresholds, dict):
                raise ValueError(f'{pid}: archetype_thresholds must be a dict')
            for shape, by_archetype in p.archetype_thresholds.items():
                if shape not in INPUT_SHAPES:
                    raise ValueError(
                        f'{pid}: archetype_thresholds key {shape!r} is not a valid INPUT_SHAPE'
                    )
                if not isinstance(by_archetype, dict):
                    raise ValueError(
                        f'{pid}: archetype_thresholds[{shape!r}] must be a dict'
                    )
                for archetype in by_archetype:
                    if archetype not in ARCHETYPES:
                        raise ValueError(
                            f'{pid}: archetype {archetype!r} not in ARCHETYPES {ARCHETYPES!r}'
                        )
                # 'unknown' must be present so fallback is always defined
                if 'unknown' not in by_archetype:
                    raise ValueError(
                        f'{pid}: archetype_thresholds[{shape!r}] must include '
                        f"'unknown' entry as safe fallback"
                    )
        # Consumer keys: every key must be a known consumer
        if p.consumer_keys:
            if not isinstance(p.consumer_keys, dict):
                raise ValueError(f'{pid}: consumer_keys must be a dict')
            for consumer in p.consumer_keys:
                if consumer not in CONSUMERS:
                    raise ValueError(
                        f'{pid}: consumer_keys consumer {consumer!r} not in CONSUMERS {CONSUMERS!r}'
                    )
        # Trainability governance: rationale must be non-empty if declared
        if p.trainability_governance is not None:
            if not isinstance(p.trainability_governance, TrainabilityGovernance):
                raise ValueError(
                    f'{pid}: trainability_governance must be TrainabilityGovernance instance'
                )
            if not p.trainability_governance.rationale.strip():
                raise ValueError(f'{pid}: trainability_governance.rationale must be non-empty')
    # Related patterns must exist.
    for pid, p in _PATTERNS.items():
        for rel in p.related_patterns:
            if rel not in _PATTERNS:
                raise ValueError(f'{pid}: related_pattern {rel!r} not in library')
    # Consumer-keys collision check: within a single consumer, no two
    # canonical patterns may map to the same legacy key (that would make
    # the reconstructed legacy dict ambiguous).
    for consumer in CONSUMERS:
        seen: dict[str, str] = {}
        for pid, p in _PATTERNS.items():
            key = p.consumer_keys.get(consumer)
            if key is None:
                continue
            if key in seen:
                raise ValueError(
                    f'consumer_keys collision: both {seen[key]!r} and {pid!r} '
                    f'map to {key!r} for consumer {consumer!r}'
                )
            seen[key] = pid


def _extract_placeholders(s: str) -> list[str]:
    """Extract {param} placeholders from a template string."""
    out: list[str] = []
    i = 0
    while i < len(s):
        if s[i] == '{':
            j = s.find('}', i)
            if j > i:
                out.append(s[i+1:j])
                i = j + 1
                continue
        i += 1
    return out


_ALIAS_INDEX = _build_alias_index()
_validate()


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────


def get_pattern(pattern_id_or_alias: str) -> CoachingPattern:
    """Resolve an id or alias to its canonical pattern."""
    canonical = _ALIAS_INDEX.get(pattern_id_or_alias)
    if canonical is None:
        raise KeyError(f'unknown pattern: {pattern_id_or_alias!r}')
    return _PATTERNS[canonical]


def resolve_alias(pattern_id_or_alias: str) -> str:
    """Return the canonical pattern_id for an id or alias."""
    canonical = _ALIAS_INDEX.get(pattern_id_or_alias)
    if canonical is None:
        raise KeyError(f'unknown pattern: {pattern_id_or_alias!r}')
    return canonical


def list_patterns() -> tuple[CoachingPattern, ...]:
    """All canonical patterns in registration order."""
    return tuple(_PATTERNS.values())


def list_pattern_ids() -> tuple[str, ...]:
    return tuple(_PATTERNS.keys())


def patterns_for_phase(phase: str) -> tuple[CoachingPattern, ...]:
    if phase not in PHASES:
        raise ValueError(f'invalid phase: {phase!r}')
    return tuple(p for p in _PATTERNS.values() if p.phase == phase)


def patterns_by_polarity(polarity: str) -> tuple[CoachingPattern, ...]:
    if polarity not in POLARITIES:
        raise ValueError(f'invalid polarity: {polarity!r}')
    return tuple(p for p in _PATTERNS.values() if p.polarity == polarity)


def patterns_supporting_shape(input_shape: str) -> tuple[CoachingPattern, ...]:
    if input_shape not in INPUT_SHAPES:
        raise ValueError(f'invalid input shape: {input_shape!r}')
    if input_shape == 'corner_features':
        return tuple(p for p in _PATTERNS.values() if p.detect_features is not None)
    return tuple(p for p in _PATTERNS.values() if p.detect_evidence is not None)


# ─────────────────────────────────────────────────────────────────
# Archetype-aware detection
# ─────────────────────────────────────────────────────────────────


# Legacy → canonical archetype mapping. ``driver_development.py`` currently
# emits 'slow_hairpin', 'slow_90deg', 'medium_speed', 'fast_corner',
# 'chicane', 'traction_exit'. Unrecognised names collapse to 'unknown' so
# archetype-aware detection is always safe.
_LEGACY_ARCHETYPE_MAP = {
    'slow_hairpin':     'hairpin',
    'slow_90deg':       'medium_speed_corner',
    'medium_speed':     'medium_speed_corner',
    'fast_corner':      'fast_corner',
    'chicane':          'chicane',
    'traction_exit':    'long_radius',
    # Accept canonical names passed through unchanged.
    'hairpin':              'hairpin',
    'medium_speed_corner':  'medium_speed_corner',
    'long_radius':          'long_radius',
    'unknown':              'unknown',
}


def normalize_archetype(name: Optional[str]) -> str:
    """Map a legacy or canonical archetype name to a canonical ``ARCHETYPES`` value.

    Unrecognised or missing names return ``'unknown'`` (safe fallback).
    This is the only conversion point between consumer vocabularies and
    the library's archetype taxonomy.
    """
    if name is None:
        return 'unknown'
    return _LEGACY_ARCHETYPE_MAP.get(name, 'unknown')


def detect_for_archetype(
    pattern_id_or_alias: str,
    archetype: Optional[str],
    shape: str,
    data,
) -> bool:
    """Run archetype-aware detection for a pattern.

    - ``archetype`` is passed through ``normalize_archetype()``; legacy
      archetype names are accepted.
    - If the pattern declares an archetype-aware detector for the
      requested shape, it is used.
    - Otherwise falls back to the default ``detect_features`` /
      ``detect_evidence`` lambda.
    - Returns ``False`` if the pattern has no detection for the requested
      shape at all (rather than raising) — archetype-aware detection is
      additive.

    Raises ``KeyError`` only for unknown ``pattern_id_or_alias`` and
    ``ValueError`` only for unknown ``shape``.
    """
    if shape not in INPUT_SHAPES:
        raise ValueError(f'invalid input shape: {shape!r}')
    p = get_pattern(pattern_id_or_alias)
    arch = normalize_archetype(archetype)
    if shape == 'corner_features':
        if p.detect_features_archetype is not None:
            return bool(p.detect_features_archetype(data, arch))
        if p.detect_features is not None:
            return bool(p.detect_features(data))
        return False
    # evidence_dict
    if p.detect_evidence_archetype is not None:
        return bool(p.detect_evidence_archetype(data, arch))
    if p.detect_evidence is not None:
        return bool(p.detect_evidence(data))
    return False


def threshold_for(
    pattern_id_or_alias: str,
    archetype: Optional[str],
    shape: str,
) -> Optional[dict]:
    """Return the archetype-specific threshold config for a pattern / shape,
    or ``None`` if the pattern has no archetype_thresholds for this shape.

    Intended for inspection / UI / docs — not for runtime detection
    (``detect_for_archetype`` is the runtime entry).
    """
    if shape not in INPUT_SHAPES:
        raise ValueError(f'invalid input shape: {shape!r}')
    p = get_pattern(pattern_id_or_alias)
    by_shape = p.archetype_thresholds.get(shape)
    if not by_shape:
        return None
    arch = normalize_archetype(archetype)
    return by_shape.get(arch) or by_shape.get('unknown')


def library_manifest() -> dict:
    """Inspectable summary for JSON export / debugging. Pure data."""
    return {
        'library_version': LIBRARY_VERSION,
        'phases': list(PHASES),
        'polarities': list(POLARITIES),
        'input_shapes': list(INPUT_SHAPES),
        'directions': list(DIRECTIONS),
        'sensors': list(SENSORS),
        'archetypes': list(ARCHETYPES),
        'consumers': list(CONSUMERS),
        'sim_transfer_confidences': list(SIM_TRANSFER_CONFIDENCES),
        'pattern_count': len(_PATTERNS),
        'aliases': {a: c for a, c in _ALIAS_INDEX.items() if a != c},
        'patterns': [
            {
                'pattern_id': p.pattern_id,
                'version': p.version,
                'label': p.label,
                'phase': p.phase,
                'polarity': p.polarity,
                'trainability': p.trainability,
                'trainability_rationale': (
                    p.trainability_governance.rationale
                    if p.trainability_governance else None
                ),
                'trainability_provisional': (
                    p.trainability_governance.provisional
                    if p.trainability_governance else None
                ),
                'metric_key': p.metric_key,
                'direction': p.direction,
                'aliases': list(p.aliases),
                'consumer_keys': dict(p.consumer_keys),
                'related_patterns': list(p.related_patterns),
                'sensor_requirements': list(p.sensor_requirements),
                'archetype_applicability': list(p.archetype_applicability),
                'detection_shapes': sorted(p.detection_descriptions.keys()),
                'detection_descriptions': dict(p.detection_descriptions),
                'has_archetype_thresholds': bool(p.archetype_thresholds),
                'archetype_thresholds_shapes': sorted(p.archetype_thresholds.keys()),
                'has_coaching_template': p.coaching_template is not None,
                'has_real_life_coaching': p.real_life_coaching is not None,
                'has_sim_coaching': p.sim_coaching is not None,
                'has_setup_hints': p.setup_hints is not None,
                'has_strategy_flags': p.strategy_flags is not None,
                'sim_transfer_confidence': (
                    p.sim_coaching.transfer_confidence
                    if p.sim_coaching else None
                ),
                'template_params': (
                    list(p.coaching_template.template_params)
                    if p.coaching_template else []
                ),
            }
            for p in _PATTERNS.values()
        ],
    }


# ─────────────────────────────────────────────────────────────────
# Consumer adapters — reconstruct legacy dict shapes
# ─────────────────────────────────────────────────────────────────


def as_behavior_def(pattern_id_or_alias: str) -> dict:
    """Adapter matching driver_development.BEHAVIOR_DEFS shape.
    Requires pattern to have detect_features (session-level)."""
    p = get_pattern(pattern_id_or_alias)
    if p.detect_features is None:
        raise ValueError(
            f'{p.pattern_id}: no features-level detection (lap_intervention only)'
        )
    return {
        'label': p.label,
        'test': p.detect_features,
        'metric_key': p.metric_key,
        'direction': p.direction,
        'trainable': p.trainability,
    }


def as_weakness_playbook_entry(pattern_id_or_alias: str) -> dict:
    """Adapter matching prescriptive_coaching.WEAKNESS_PLAYBOOK shape.
    Requires coaching_template."""
    p = get_pattern(pattern_id_or_alias)
    if p.coaching_template is None:
        raise ValueError(f'{p.pattern_id}: no coaching_template — cannot build playbook entry')
    t = p.coaching_template
    return {
        'title': p.title,
        'phase': p.phase,
        'likely_causes': list(t.likely_causes),
        'coaching_actions': list(t.coaching_actions),
        'driver_cues': list(t.driver_cues),
        'sensor_note': t.sensor_note,
    }


def as_intervention_class(pattern_id_or_alias: str) -> dict:
    """Adapter matching coaching_intelligence.INTERVENTION_CLASSES shape.
    Requires detect_evidence + confidence_fn_evidence (lap-level)."""
    p = get_pattern(pattern_id_or_alias)
    if p.detect_evidence is None or p.confidence_fn_evidence is None:
        raise ValueError(
            f'{p.pattern_id}: no evidence-level detection (session_behavior only)'
        )
    return {
        'label': p.label,
        'phase': p.phase,
        'trainability': p.trainability,
        'detect': p.detect_evidence,
        'confidence_fn': p.confidence_fn_evidence,
    }


def _consumer_key_for(p: CoachingPattern, consumer: Optional[str]) -> str:
    """Return the dict key to use for a pattern when reconstructing a
    consumer-owned legacy dict.

    - ``consumer=None`` (default)  → canonical ``pattern_id``.
    - ``consumer='x'`` with ``consumer_keys['x']`` present → that override.
    - ``consumer='x'`` with no override → canonical ``pattern_id``.

    Raises ``ValueError`` if ``consumer`` is non-None and not in ``CONSUMERS``.
    """
    if consumer is None:
        return p.pattern_id
    if consumer not in CONSUMERS:
        raise ValueError(f'unknown consumer: {consumer!r}. Must be one of {CONSUMERS!r}')
    return p.consumer_keys.get(consumer, p.pattern_id)


def behavior_defs_dict(consumer: Optional[str] = None) -> dict:
    """Reconstruct a BEHAVIOR_DEFS-shaped dict from the library.

    Only patterns with ``detect_features`` (session-level) are included.
    ``consumer='driver_development'`` produces the exact legacy key set
    (e.g. 'low_minimum_speed' for the canonical 'apex_low_speed').
    """
    return {
        _consumer_key_for(p, consumer): as_behavior_def(p.pattern_id)
        for p in _PATTERNS.values()
        if p.detect_features is not None
    }


def weakness_playbook_dict(consumer: Optional[str] = None) -> dict:
    """Reconstruct a WEAKNESS_PLAYBOOK-shaped dict from the library.

    Only patterns with ``coaching_template`` are included.
    ``consumer='prescriptive_coaching'`` produces the legacy key set.
    """
    return {
        _consumer_key_for(p, consumer): as_weakness_playbook_entry(p.pattern_id)
        for p in _PATTERNS.values()
        if p.coaching_template is not None
    }


def intervention_classes_dict(consumer: Optional[str] = None) -> dict:
    """Reconstruct an INTERVENTION_CLASSES-shaped dict from the library.

    Only patterns with ``detect_evidence`` (lap-level) are included.
    ``consumer='coaching_intelligence'`` produces the legacy key set
    (e.g. 'apex_speed_deficit', 'late_throttle_application', 'path_variance').
    """
    return {
        _consumer_key_for(p, consumer): as_intervention_class(p.pattern_id)
        for p in _PATTERNS.values()
        if p.detect_evidence is not None
    }


__all__ = [
    # Version + taxonomy
    'LIBRARY_VERSION',
    'PHASES',
    'POLARITIES',
    'INPUT_SHAPES',
    'DIRECTIONS',
    'SENSORS',
    'ARCHETYPES',
    'CONSUMERS',
    'SIM_TRANSFER_CONFIDENCES',
    # Dataclasses
    'CoachingPattern',
    'CoachingTemplate',
    'RealLifeCoaching',
    'SimCoaching',
    'SetupHints',
    'StrategyFlags',
    'TrainabilityGovernance',
    # Lookup
    'get_pattern',
    'resolve_alias',
    'list_patterns',
    'list_pattern_ids',
    'patterns_for_phase',
    'patterns_by_polarity',
    'patterns_supporting_shape',
    # Archetype-aware detection
    'normalize_archetype',
    'detect_for_archetype',
    'threshold_for',
    # Inspection
    'library_manifest',
    # Consumer adapters
    'as_behavior_def',
    'as_weakness_playbook_entry',
    'as_intervention_class',
    'behavior_defs_dict',
    'weakness_playbook_dict',
    'intervention_classes_dict',
]
