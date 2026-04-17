"""Coaching ontology migration tests (v2.0.0).

Required test coverage from the migration brief (22 items):

 1. library import-time self-validation
 2. all three consumers now depend on library-derived definitions
 3. no consumer retains authoritative inline registry ownership
 4. alias resolution works
 5. alias collisions fail loudly
 6. version helpers behave correctly
 7. backward compatibility for legacy IDs works
 8. archetype-aware thresholds change outcomes where expected
 9. unknown archetype fallback is safe
10. companion blocks are schema-valid
11. companion blocks are evidence-honest
12. trainability comes from the library
13. development intelligence output remains stable
14. prescriptive coaching output remains stable
15. coaching_intelligence output remains stable
16. deterministic behavior remains
17. sparse-data handling remains safe
18. Bronze unchanged
19. Silver unchanged
20. no Gold Lab, beta, or shadow contamination
21. additive-only contract preserved
22. malformed registry definitions fail loudly at import time
"""
from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from track_surface import coaching_library as lib
from track_surface.coaching_library import (
    ARCHETYPES,
    CONSUMERS,
    LIBRARY_VERSION,
    PHASES,
    POLARITIES,
    SENSORS,
    SIM_TRANSFER_CONFIDENCES,
    CoachingPattern,
    RealLifeCoaching,
    SetupHints,
    SimCoaching,
    StrategyFlags,
    TrainabilityGovernance,
    behavior_defs_dict,
    detect_for_archetype,
    get_pattern,
    intervention_classes_dict,
    library_manifest,
    list_pattern_ids,
    list_patterns,
    normalize_archetype,
    resolve_alias,
    threshold_for,
    weakness_playbook_dict,
)

_TRACK_SURFACE_DIR = Path(__file__).resolve().parents[1] / 'track_surface'


# ── 1. Library import-time self-validation ──────────────────────


class TestLibraryImportValidation:
    """Library refuses to import unless every pattern passes structural checks."""

    def test_imports_successfully(self):
        # If we can import the module + enumerate patterns, validation passed.
        assert len(list_patterns()) >= 12

    def test_all_patterns_have_required_schema(self):
        for p in list_patterns():
            assert p.pattern_id
            assert p.phase in PHASES
            assert p.polarity in POLARITIES
            for s in p.sensor_requirements:
                assert s in SENSORS

    def test_alias_index_consistent(self):
        # Every declared alias resolves to a real canonical ID.
        for p in list_patterns():
            for alias in p.aliases:
                assert resolve_alias(alias) == p.pattern_id


# ── 2 & 3. Consumers depend on library; no inline authoritative dicts ──


class TestConsumerMigration:
    """Each consumer module is a pure reshaper of library output."""

    def test_driver_development_uses_library(self):
        from track_surface import driver_development
        from track_surface.coaching_library import behavior_defs_dict

        lib_view = behavior_defs_dict(consumer='driver_development')
        assert driver_development.BEHAVIOR_DEFS == lib_view

    def test_coaching_intelligence_uses_library(self):
        from track_surface import coaching_intelligence
        from track_surface.coaching_library import intervention_classes_dict

        lib_view = intervention_classes_dict(consumer='coaching_intelligence')
        assert coaching_intelligence.INTERVENTION_CLASSES == lib_view

    def test_prescriptive_coaching_uses_library(self):
        from track_surface import prescriptive_coaching
        from track_surface.coaching_library import weakness_playbook_dict

        lib_view = weakness_playbook_dict(consumer='prescriptive_coaching')
        # prescriptive_coaching may wrap values into legacy list shape;
        # keys must match exactly.
        assert set(prescriptive_coaching.WEAKNESS_PLAYBOOK.keys()) == set(lib_view.keys())
        for k in lib_view:
            assert prescriptive_coaching.WEAKNESS_PLAYBOOK[k]['title'] == lib_view[k]['title']

    def test_no_consumer_defines_inline_authoritative_dict(self):
        """AST-level check: the consumer modules no longer contain a hand-
        maintained module-level dict literal for their registry."""
        for module_name, registry_name in [
            ('driver_development.py',   'BEHAVIOR_DEFS'),
            ('coaching_intelligence.py', 'INTERVENTION_CLASSES'),
            ('prescriptive_coaching.py', 'WEAKNESS_PLAYBOOK'),
        ]:
            source = (_TRACK_SURFACE_DIR / module_name).read_text(encoding='utf-8')
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if (isinstance(node, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == registry_name
                                for t in node.targets)):
                    # Must be an expression that calls the library adapter,
                    # never a literal dict.
                    assert not isinstance(node.value, ast.Dict), (
                        f'{module_name}: {registry_name} is still assigned as '
                        f'an inline dict literal — must come from the library adapter'
                    )


# ── 4. Alias resolution ────────────────────────────────────────


class TestAliasResolution:
    @pytest.mark.parametrize('alias, canonical', [
        ('low_minimum_speed',      'apex_low_speed'),
        ('apex_speed_deficit',     'apex_low_speed'),
        ('late_throttle_application', 'late_throttle_pickup'),
        ('path_variance',          'line_deviation'),
    ])
    def test_known_aliases_resolve(self, alias, canonical):
        assert resolve_alias(alias) == canonical

    def test_canonical_resolves_to_itself(self):
        for pid in list_pattern_ids():
            assert resolve_alias(pid) == pid


# ── 5. Alias collisions fail loudly ────────────────────────────


class TestAliasCollisions:
    def test_alias_collision_raises(self):
        """Simulating a colliding alias must raise at build time."""
        from track_surface.coaching_library import CoachingPattern, _build_alias_index

        # We cannot mutate the real registry at test time. Instead, we exercise
        # the private helper against a hand-built dict.
        patterns = {
            'foo': CoachingPattern(
                pattern_id='foo', version='1.0.0', label='x', title='x',
                phase='entry', polarity='weakness', trainability=0.5,
                metric_key='mk', direction='positive_is_bad',
                sensor_requirements=('gps_speed',),
                archetype_applicability=('*',),
                aliases=('shared_alias',),
                detect_features=lambda cf: True,
            ),
            'bar': CoachingPattern(
                pattern_id='bar', version='1.0.0', label='x', title='x',
                phase='entry', polarity='weakness', trainability=0.5,
                metric_key='mk', direction='positive_is_bad',
                sensor_requirements=('gps_speed',),
                archetype_applicability=('*',),
                aliases=('shared_alias',),
                detect_features=lambda cf: True,
            ),
        }
        # Save / swap / restore — exercise the alias builder directly.
        original = lib._PATTERNS
        try:
            lib._PATTERNS = patterns
            with pytest.raises(ValueError, match='alias'):
                _build_alias_index()
        finally:
            lib._PATTERNS = original


# ── 6. Version helpers ─────────────────────────────────────────


class TestVersion:
    def test_library_version_semver(self):
        parts = LIBRARY_VERSION.split('.')
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_library_is_v2(self):
        # The migration is a major schema bump.
        assert LIBRARY_VERSION.startswith('2.')

    def test_every_pattern_versioned(self):
        for p in list_patterns():
            parts = p.version.split('.')
            assert len(parts) == 3
            assert all(x.isdigit() for x in parts)


# ── 7. Backward compatibility for legacy IDs ──────────────────


class TestBackwardCompat:
    """Legacy consumer keys still resolve to real library patterns, and the
    reconstructed legacy dicts expose exactly the expected keys."""

    def test_behavior_defs_has_legacy_keys(self):
        bd = behavior_defs_dict(consumer='driver_development')
        # Every legacy key that existed pre-migration must still be present.
        for legacy in (
            'late_throttle_pickup', 'early_braking', 'low_minimum_speed',
            'weak_exit_build', 'line_deviation', 'strong_braking', 'strong_exit',
        ):
            assert legacy in bd

    def test_intervention_classes_has_legacy_keys(self):
        ic = intervention_classes_dict(consumer='coaching_intelligence')
        for legacy in (
            'entry_speed_surrender', 'conservative_brake_release',
            'apex_speed_deficit', 'late_throttle_application',
            'weak_exit_build', 'path_variance',
        ):
            assert legacy in ic

    def test_weakness_playbook_has_legacy_keys(self):
        wp = weakness_playbook_dict(consumer='prescriptive_coaching')
        for legacy in (
            'low_minimum_speed', 'early_braking', 'late_throttle_pickup',
            'weak_exit_build', 'line_deviation',
        ):
            assert legacy in wp

    def test_unknown_consumer_raises(self):
        with pytest.raises(ValueError, match='unknown consumer'):
            behavior_defs_dict(consumer='not_a_consumer')


# ── 8. Archetype thresholds change outcomes ───────────────────


class TestArchetypeThresholds:
    """Archetype-aware detection must flip outcomes when the threshold is archetype-specific."""

    def test_fast_corner_tighter_than_hairpin_apex_low_speed(self):
        # fast_corner threshold is -1.5 kph; hairpin threshold is -3.0 kph.
        # A pattern of -2.0 kph triggers on fast, NOT on hairpin.
        ev_features = type('CF', (), {
            'min_speed_delta_kph': -2.0,
            'brake_point_delta_m': None,
            'throttle_pickup_delta_m': None,
            'exit_speed_delta_kph': 0.0,
            'line_deviation_m': 0.0,
            'time_delta_ms': 0.0,
            'confidence': 0.9,
        })()
        assert detect_for_archetype(
            'apex_low_speed', 'fast_corner', 'corner_features', ev_features) is True
        assert detect_for_archetype(
            'apex_low_speed', 'hairpin', 'corner_features', ev_features) is False

    def test_thresholds_accessible_via_inspection(self):
        hairpin = threshold_for('apex_low_speed', 'hairpin', 'corner_features')
        fast = threshold_for('apex_low_speed', 'fast_corner', 'corner_features')
        assert hairpin['min_speed_delta_kph'] == -3.0
        assert fast['min_speed_delta_kph'] == -1.5


# ── 9. Unknown archetype fallback ─────────────────────────────


class TestUnknownArchetypeFallback:
    def test_unknown_archetype_uses_default(self):
        ev_features = type('CF', (), {
            'min_speed_delta_kph': -3.5,
            'brake_point_delta_m': None, 'throttle_pickup_delta_m': None,
            'exit_speed_delta_kph': 0.0, 'line_deviation_m': 0.0,
            'time_delta_ms': 0.0, 'confidence': 0.9,
        })()
        # 'unknown' threshold for apex_low_speed is -3.0
        assert detect_for_archetype(
            'apex_low_speed', 'unknown', 'corner_features', ev_features) is True

    def test_unrecognised_archetype_collapses_to_unknown(self):
        """Any string not in ARCHETYPES must fall back to 'unknown' thresholds."""
        assert normalize_archetype('totally_made_up') == 'unknown'
        assert normalize_archetype(None) == 'unknown'

    def test_legacy_archetype_names_map_cleanly(self):
        """Names emitted by driver_development.classify_corner_archetype() must map."""
        assert normalize_archetype('slow_hairpin') == 'hairpin'
        assert normalize_archetype('slow_90deg') == 'medium_speed_corner'
        assert normalize_archetype('medium_speed') == 'medium_speed_corner'
        assert normalize_archetype('fast_corner') == 'fast_corner'
        assert normalize_archetype('chicane') == 'chicane'
        assert normalize_archetype('traction_exit') == 'long_radius'


# ── 10. Companion blocks schema-valid ─────────────────────────


class TestCompanionBlockSchema:
    def test_real_life_coaching_has_valid_shape(self):
        for p in list_patterns():
            if p.real_life_coaching is None:
                continue
            assert isinstance(p.real_life_coaching, RealLifeCoaching)
            assert isinstance(p.real_life_coaching.actions, tuple)
            assert isinstance(p.real_life_coaching.driver_cues, tuple)
            assert isinstance(p.real_life_coaching.validation_metrics, tuple)
            assert p.real_life_coaching.sensor_honesty_note

    def test_sim_coaching_has_valid_transfer_confidence(self):
        for p in list_patterns():
            if p.sim_coaching is None:
                continue
            assert p.sim_coaching.transfer_confidence in SIM_TRANSFER_CONFIDENCES

    def test_setup_hints_has_honesty_note(self):
        for p in list_patterns():
            if p.setup_hints is None:
                continue
            assert p.setup_hints.evidence_honesty_note

    def test_strategy_flags_has_honesty_note(self):
        for p in list_patterns():
            if p.strategy_flags is None:
                continue
            assert p.strategy_flags.evidence_honesty_note


# ── 11. Companion blocks evidence-honest ───────────────────────


class TestCompanionBlockHonesty:
    def test_non_high_sim_transfer_declares_risks(self):
        """Any pattern with transfer_confidence<'high' must list non-transfer risks."""
        for p in list_patterns():
            sc = p.sim_coaching
            if sc is None or sc.transfer_confidence == 'high':
                continue
            assert sc.non_transfer_risks, (
                f'{p.pattern_id}: non-high transfer_confidence must list non_transfer_risks'
            )

    def test_proxy_patterns_are_provisional(self):
        """`likely_*_proxy` patterns must carry trainability_governance.provisional=True."""
        for pid in ('likely_understeer_proxy', 'likely_oversteer_proxy'):
            p = get_pattern(pid)
            assert p.trainability_governance is not None
            assert p.trainability_governance.provisional is True

    def test_strengths_have_no_coaching_action_blocks(self):
        """Strengths carry no real_life_coaching / sim_coaching / setup_hints —
        strengths are recognised, not trained (the spec's 'be conservative' rule)."""
        for p in list_patterns():
            if p.polarity != 'strength':
                continue
            assert p.real_life_coaching is None
            assert p.sim_coaching is None
            assert p.setup_hints is None


# ── 12. Trainability comes from the library ───────────────────


class TestTrainabilityGovernance:
    def test_all_consumers_read_same_trainability(self):
        """BEHAVIOR_DEFS, INTERVENTION_CLASSES, and WEAKNESS_PLAYBOOK all
        reflect the library's canonical trainability value — no consumer
        may override it locally."""
        from track_surface.coaching_intelligence import INTERVENTION_CLASSES
        from track_surface.driver_development import BEHAVIOR_DEFS

        # 'apex_low_speed' surfaces as 'low_minimum_speed' in BEHAVIOR_DEFS
        # and 'apex_speed_deficit' in INTERVENTION_CLASSES.
        canonical = get_pattern('apex_low_speed')
        assert BEHAVIOR_DEFS['low_minimum_speed']['trainable'] == canonical.trainability
        assert INTERVENTION_CLASSES['apex_speed_deficit']['trainability'] == canonical.trainability

    def test_trainability_has_rationale_for_every_pattern(self):
        for p in list_patterns():
            assert p.trainability_governance is not None, (
                f'{p.pattern_id}: trainability_governance is required since v2.0.0'
            )
            assert p.trainability_governance.rationale


# ── 13/14/15. Output stability (consumers still produce expected shapes) ─


class TestOutputStability:
    def _minimal_evidence(self, **overrides):
        ev = {
            'corner_id': 1,
            'time_delta_ms': 150.0,
            'evidence': {
                'min_speed_delta_kph': -6.0,
                'brake_point_delta_m': -1.0,
                'throttle_pickup_delta_m': 2.0,
                'exit_speed_delta_kph': -2.0,
                'line_deviation_rms_m': 0.8,
            },
            'primary_cause': 'apex_low_speed',
            'confidence': 0.7,
            's_entry_m': 0.0, 's_exit_m': 50.0,
        }
        ev.update(overrides)
        return ev

    def test_coaching_intelligence_output_shape(self):
        from track_surface.coaching_intelligence import generate_coaching, to_json_dict

        ci = generate_coaching(
            corner_packets=[self._minimal_evidence()],
            weaknesses=[],
            priorities=[],
            sessions_analyzed=3,
            track_name='test',
        )
        out = to_json_dict(ci)
        assert set(out.keys()) == {
            'version', 'actions', 'corner_families',
            'focus_summary', 'secondary_summary', 'monitor_summary',
            'confidence_note', 'sessions_context',
        }

    def test_prescriptive_coaching_output_shape(self):
        from track_surface.prescriptive_coaching import (
            generate_prescriptive_coaching, to_json_dict,
        )

        pc = generate_prescriptive_coaching(
            corner_packets=[self._minimal_evidence()],
            weaknesses=[],
            priorities=[],
            dev_storyline=[],
            sessions_analyzed=3,
            laps_analyzed=10,
            track_name='test',
        )
        out = to_json_dict(pc)
        assert set(out.keys()) == {
            'version', 'source', 'global_focus', 'corner_coaching',
            'weakness_playbook_matches', 'next_run_plan',
            'validation_checks', 'storyline', 'limits',
        }

    def test_development_intelligence_output_shape(self):
        from track_surface.driver_development import (
            CornerFeatures, analyze_development, to_json_dict,
        )

        # Build a few synthetic CornerFeatures (using the dataclass directly).
        features = [
            CornerFeatures(
                lap_id=f'L{i}', session_id='S1', corner_id=1,
                archetype='medium_speed',
                time_delta_ms=200.0,
                min_speed_delta_kph=-6.0,
                brake_point_delta_m=-2.0,
                throttle_pickup_delta_m=6.0,
                exit_speed_delta_kph=-3.0,
                line_deviation_m=1.2,
                primary_cause='apex_low_speed',
                confidence=0.7,
            )
            for i in range(5)
        ]
        lap_times = {f'L{i}': 30.0 + i * 0.05 for i in range(5)}
        di = analyze_development(features, lap_times, ['S1'], 'test')
        out = to_json_dict(di)
        assert set(out.keys()) == {
            'version', 'sessions_analyzed', 'laps_analyzed', 'track_name',
            'analysis_confidence', 'overall_direction',
            'session_summaries', 'recurring_weaknesses', 'recurring_strengths',
            'priority_focuses', 'storyline',
        }


# ── 16. Determinism ─────────────────────────────────────────────


class TestDeterminism:
    def test_list_patterns_stable(self):
        a = list_pattern_ids()
        b = list_pattern_ids()
        assert a == b

    def test_manifest_stable(self):
        m1 = library_manifest()
        m2 = library_manifest()
        assert m1 == m2

    def test_consumer_adapters_stable(self):
        a1 = behavior_defs_dict(consumer='driver_development')
        a2 = behavior_defs_dict(consumer='driver_development')
        assert a1.keys() == a2.keys()


# ── 17. Sparse-data safety ───────────────────────────────────────


class TestSparseDataSafety:
    def test_none_evidence_fields_do_not_crash_detection(self):
        cf = type('CF', (), {
            'min_speed_delta_kph': -0.1,
            'brake_point_delta_m': None, 'throttle_pickup_delta_m': None,
            'exit_speed_delta_kph': 0.0, 'line_deviation_m': 0.0,
            'time_delta_ms': 0.0, 'confidence': 0.9,
        })()
        # Must not raise, must return False (nothing meaningfully detected).
        assert detect_for_archetype(
            'apex_low_speed', 'unknown', 'corner_features', cf) is False

    def test_empty_evidence_dict_does_not_crash(self):
        ev = {}
        assert detect_for_archetype(
            'apex_low_speed', 'hairpin', 'evidence_dict', ev) is False


# ── 18/19. Bronze and Silver unchanged ─────────────────────────


class TestBronzeSilverUnchanged:
    """The library does not introduce any Bronze or Silver signal. All new
    fields are companion blocks — additive to the Gold (coaching) layer."""

    def test_no_new_sensor_types_introduced(self):
        """Sensor taxonomy stayed speed+position-derivative only (no Gold Lab,
        IMU, or CAN signals leaked in)."""
        for s in SENSORS:
            assert s in (
                'gps_speed', 'gps_position',
                'derived_brake_onset', 'derived_throttle_onset',
                'reference_lap_trace',
            ), f'Unexpected sensor {s!r} — Bronze vocabulary must not grow silently'

    def test_no_pattern_requires_non_bronze_sensor(self):
        """Every pattern's sensor_requirements is a subset of the Bronze-safe taxonomy."""
        for p in list_patterns():
            for s in p.sensor_requirements:
                assert s in SENSORS


# ── 20. No Gold Lab / beta / shadow contamination ──────────────


class TestNoExperimentalContamination:
    def test_prescriptive_source_tag_is_canonical_only(self):
        from track_surface.prescriptive_coaching import generate_prescriptive_coaching

        pc = generate_prescriptive_coaching(
            corner_packets=[], weaknesses=[], priorities=[],
            dev_storyline=[], sessions_analyzed=3,
        )
        assert pc.source == 'bronze_compare_plus_development_intelligence_only'

    def test_no_pattern_references_gold_lab_in_content(self):
        """Content strings must not contain forbidden source tags."""
        forbidden = ('gold_lab', 'shadow', 'beta_candidate', 'experimental')
        for p in list_patterns():
            blob_parts: list[str] = []
            if p.coaching_template:
                blob_parts.extend(p.coaching_template.coaching_actions)
                blob_parts.extend(p.coaching_template.driver_cues)
                blob_parts.extend(p.coaching_template.likely_causes)
            if p.real_life_coaching:
                blob_parts.extend(p.real_life_coaching.actions)
                blob_parts.extend(p.real_life_coaching.driver_cues)
            if p.sim_coaching:
                blob_parts.extend(p.sim_coaching.trainable_in_sim)
                blob_parts.extend(p.sim_coaching.non_transfer_risks)
            blob = ' '.join(blob_parts).lower()
            for token in forbidden:
                assert token not in blob, (
                    f'{p.pattern_id}: content mentions forbidden source {token!r}'
                )


# ── 21. Additive-only contract ────────────────────────────────


class TestAdditiveContract:
    """Every 1.0.0 consumer field and API method still exists and behaves
    as before — the migration is purely additive."""

    def test_v1_api_still_exported(self):
        for name in (
            'get_pattern', 'resolve_alias', 'list_patterns', 'list_pattern_ids',
            'patterns_for_phase', 'patterns_by_polarity', 'patterns_supporting_shape',
            'library_manifest',
            'as_behavior_def', 'as_weakness_playbook_entry', 'as_intervention_class',
            'behavior_defs_dict', 'weakness_playbook_dict', 'intervention_classes_dict',
        ):
            assert name in lib.__all__, f'{name!r} disappeared from v1 API'

    def test_v1_consumer_adapter_default_is_canonical(self):
        """behavior_defs_dict() (no consumer) keeps the canonical keys —
        same as 1.0.0 behaviour."""
        bd_none = behavior_defs_dict()
        # Canonical IDs — e.g. 'apex_low_speed' (not 'low_minimum_speed').
        assert 'apex_low_speed' in bd_none

    def test_existing_companion_blocks_are_optional(self):
        """v1 pattern definitions (no companion blocks) would still validate."""
        # Simulate: strengths were introduced pre-v2 without blocks.
        # They must still be loaded with real_life_coaching=None etc.
        strong = get_pattern('strong_braking')
        assert strong.real_life_coaching is None
        assert strong.sim_coaching is None


# ── 22. Malformed registry definitions fail loudly ────────────


class TestMalformedFailsLoudly:
    """The validation layer must reject structurally-invalid pattern
    additions at build time — a silent accept is forbidden."""

    def _minimal_valid_pattern(self, **overrides) -> CoachingPattern:
        kwargs = dict(
            pattern_id='temp', version='1.0.0', label='x', title='x',
            phase='entry', polarity='weakness', trainability=0.5,
            metric_key='mk', direction='positive_is_bad',
            sensor_requirements=('gps_speed',),
            archetype_applicability=('*',),
            detect_features=lambda cf: True,
        )
        kwargs.update(overrides)
        return CoachingPattern(**kwargs)

    def _run_validation(self, patterns: dict) -> None:
        original = lib._PATTERNS
        try:
            lib._PATTERNS = patterns
            lib._validate()
        finally:
            lib._PATTERNS = original

    def test_unknown_sensor_rejected(self):
        p = self._minimal_valid_pattern(sensor_requirements=('fictional_sensor',))
        with pytest.raises(ValueError, match='unknown sensor'):
            self._run_validation({'temp': p})

    def test_unknown_archetype_threshold_rejected(self):
        p = self._minimal_valid_pattern(archetype_thresholds={
            'corner_features': {'hairpin': {}, 'unknown': {}, 'not_a_real_archetype': {}},
        })
        with pytest.raises(ValueError, match='ARCHETYPES'):
            self._run_validation({'temp': p})

    def test_archetype_thresholds_missing_unknown_fallback(self):
        p = self._minimal_valid_pattern(archetype_thresholds={
            'corner_features': {'hairpin': {}},  # no 'unknown' fallback
        })
        with pytest.raises(ValueError, match='unknown'):
            self._run_validation({'temp': p})

    def test_sim_coaching_invalid_transfer_confidence_rejected(self):
        p = self._minimal_valid_pattern(sim_coaching=SimCoaching(
            trainable_in_sim=('x',),
            transfer_to_real_life='...',
            non_transfer_risks=('y',),
            recommended_sim_exercises=('z',),
            transfer_confidence='super-high',
        ))
        with pytest.raises(ValueError, match='transfer_confidence'):
            self._run_validation({'temp': p})

    def test_non_high_transfer_without_risks_rejected(self):
        p = self._minimal_valid_pattern(sim_coaching=SimCoaching(
            trainable_in_sim=('x',),
            transfer_to_real_life='...',
            non_transfer_risks=(),     # empty while transfer_confidence < high
            recommended_sim_exercises=('z',),
            transfer_confidence='medium',
        ))
        with pytest.raises(ValueError, match='non_transfer_risks'):
            self._run_validation({'temp': p})

    def test_unknown_consumer_key_rejected(self):
        p = self._minimal_valid_pattern(consumer_keys={'made_up_consumer': 'x'})
        with pytest.raises(ValueError, match='CONSUMERS'):
            self._run_validation({'temp': p})

    def test_consumer_key_collision_rejected(self):
        a = self._minimal_valid_pattern(
            pattern_id='pa',
            consumer_keys={'driver_development': 'same_key'},
        )
        b = self._minimal_valid_pattern(
            pattern_id='pb',
            consumer_keys={'driver_development': 'same_key'},
        )
        with pytest.raises(ValueError, match='collision'):
            self._run_validation({'pa': a, 'pb': b})

    def test_empty_trainability_rationale_rejected(self):
        p = self._minimal_valid_pattern(
            trainability_governance=TrainabilityGovernance(rationale='   ', provisional=False),
        )
        with pytest.raises(ValueError, match='rationale'):
            self._run_validation({'temp': p})
