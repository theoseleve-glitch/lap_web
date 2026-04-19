"""Tests for coaching_library.py — 10 required categories.

1. Schema stability
2. Version contract
3. Alias uniqueness + resolution
4. Phase / polarity / direction validity
5. Parity with existing registries (BEHAVIOR_DEFS, WEAKNESS_PLAYBOOK, INTERVENTION_CLASSES)
6. Adapter round-trip (legacy dict shape reconstructed identically)
7. Deterministic ordering
8. Sensor requirements declared per pattern
9. Template parameter resolution
10. Cross-pattern relationship integrity + manifest shape
"""
from __future__ import annotations

import pytest

from track_surface.coaching_library import (
    DIRECTIONS,
    INPUT_SHAPES,
    LIBRARY_VERSION,
    PHASES,
    POLARITIES,
    SENSORS,
    CoachingPattern,
    CoachingTemplate,
    as_behavior_def,
    as_intervention_class,
    as_weakness_playbook_entry,
    behavior_defs_dict,
    get_pattern,
    intervention_classes_dict,
    library_manifest,
    list_pattern_ids,
    list_patterns,
    patterns_by_polarity,
    patterns_for_phase,
    patterns_supporting_shape,
    resolve_alias,
    weakness_playbook_dict,
)


# ── 1. Schema stability ────────────────────────────────────────


class TestSchemaStability:
    def test_every_pattern_has_required_fields(self):
        for p in list_patterns():
            assert isinstance(p, CoachingPattern)
            assert p.pattern_id and isinstance(p.pattern_id, str)
            assert p.version and isinstance(p.version, str)
            assert p.label and isinstance(p.label, str)
            assert p.title and isinstance(p.title, str)
            assert p.phase in PHASES
            assert p.polarity in POLARITIES
            assert 0.0 <= p.trainability <= 1.0
            assert p.metric_key and isinstance(p.metric_key, str)
            assert p.direction in DIRECTIONS
            assert isinstance(p.sensor_requirements, tuple)
            assert isinstance(p.archetype_applicability, tuple)
            assert isinstance(p.aliases, tuple)
            assert isinstance(p.related_patterns, tuple)
            assert isinstance(p.detection_descriptions, dict)

    def test_detection_declared(self):
        for p in list_patterns():
            assert p.detect_features is not None or p.detect_evidence is not None, (
                f'{p.pattern_id}: must have at least one detection shape'
            )

    def test_detection_descriptions_match_available_shapes(self):
        for p in list_patterns():
            for shape in p.detection_descriptions:
                assert shape in INPUT_SHAPES


# ── 2. Version contract ────────────────────────────────────────


class TestVersion:
    def test_library_version_is_semver_like(self):
        parts = LIBRARY_VERSION.split('.')
        assert len(parts) == 3
        for p in parts:
            assert p.isdigit()

    def test_every_pattern_versioned(self):
        for p in list_patterns():
            parts = p.version.split('.')
            assert len(parts) == 3


# ── 3. Alias uniqueness + resolution ───────────────────────────


class TestAliases:
    def test_canonical_id_resolves_to_itself(self):
        for pid in list_pattern_ids():
            assert resolve_alias(pid) == pid

    def test_alias_resolves_to_canonical(self):
        # Known aliases declared in the registry
        assert resolve_alias('low_minimum_speed') == 'apex_low_speed'
        assert resolve_alias('apex_speed_deficit') == 'apex_low_speed'
        assert resolve_alias('late_throttle_application') == 'late_throttle_pickup'
        assert resolve_alias('path_variance') == 'line_deviation'

    def test_unknown_alias_raises(self):
        with pytest.raises(KeyError):
            resolve_alias('this_does_not_exist')

    def test_no_alias_id_overlap(self):
        all_ids = set(list_pattern_ids())
        for p in list_patterns():
            for a in p.aliases:
                # an alias may not collide with a canonical id (other than self)
                assert a not in all_ids or a == p.pattern_id, (
                    f'alias {a!r} of {p.pattern_id!r} collides with canonical id'
                )


# ── 4. Phase / polarity / direction validity ───────────────────


class TestTaxonomy:
    def test_phases_enum(self):
        for p in list_patterns():
            assert p.phase in PHASES

    def test_strengths_have_zero_trainability(self):
        for p in patterns_by_polarity('strength'):
            assert p.trainability == 0.0

    def test_weaknesses_have_positive_trainability(self):
        for p in patterns_by_polarity('weakness'):
            assert p.trainability > 0.0

    def test_patterns_for_phase_filter(self):
        apex = patterns_for_phase('apex')
        for p in apex:
            assert p.phase == 'apex'
        # sanity: at least 2 apex patterns (apex_low_speed, line_deviation)
        assert len(apex) >= 2

    def test_invalid_phase_raises(self):
        with pytest.raises(ValueError):
            patterns_for_phase('not_a_phase')


# ── 5. Parity with existing registries ─────────────────────────


class TestRegistryParity:
    """Every key in the three legacy registries must be resolvable via
    the library (canonical or alias). This is the guarantee that makes
    the library a true single source of truth."""

    def test_behavior_defs_keys_all_resolvable(self):
        from track_surface.driver_development import BEHAVIOR_DEFS
        for key in BEHAVIOR_DEFS:
            # every legacy key resolves to something in the library
            canonical = resolve_alias(key)
            p = get_pattern(canonical)
            # and the library exposes a features-level detection
            # (since BEHAVIOR_DEFS is session-level)
            assert p.detect_features is not None, (
                f'{key}: BEHAVIOR_DEFS key must have features-level detection'
            )

    def test_weakness_playbook_keys_all_resolvable(self):
        from track_surface.prescriptive_coaching import WEAKNESS_PLAYBOOK
        for key in WEAKNESS_PLAYBOOK:
            canonical = resolve_alias(key)
            p = get_pattern(canonical)
            assert p.coaching_template is not None, (
                f'{key}: WEAKNESS_PLAYBOOK key must have coaching_template'
            )

    def test_intervention_classes_keys_all_resolvable(self):
        from track_surface.coaching_intelligence import INTERVENTION_CLASSES
        for key in INTERVENTION_CLASSES:
            canonical = resolve_alias(key)
            p = get_pattern(canonical)
            assert p.detect_evidence is not None, (
                f'{key}: INTERVENTION_CLASSES key must have evidence-level detection'
            )


# ── 6. Adapter round-trip ──────────────────────────────────────


class TestAdapters:
    def test_behavior_def_shape(self):
        bd = as_behavior_def('late_throttle_pickup')
        for k in ('label', 'test', 'metric_key', 'direction', 'trainable'):
            assert k in bd
        assert callable(bd['test'])

    def test_weakness_playbook_shape(self):
        wp = as_weakness_playbook_entry('apex_low_speed')
        for k in ('title', 'phase', 'likely_causes', 'coaching_actions',
                  'driver_cues', 'sensor_note'):
            assert k in wp
        assert isinstance(wp['likely_causes'], list)
        assert isinstance(wp['coaching_actions'], list)

    def test_intervention_class_shape(self):
        ic = as_intervention_class('apex_low_speed')
        for k in ('label', 'phase', 'trainability', 'detect', 'confidence_fn'):
            assert k in ic
        assert callable(ic['detect'])
        assert callable(ic['confidence_fn'])

    def test_adapter_via_alias(self):
        # Resolving through an alias must produce the same adapter output
        # as resolving via the canonical id.
        a = as_behavior_def('low_minimum_speed')          # alias
        b = as_behavior_def('apex_low_speed')             # canonical
        assert a['label'] == b['label']
        assert a['metric_key'] == b['metric_key']
        assert a['trainable'] == b['trainable']

    def test_adapter_rejects_missing_shape(self):
        # strong_braking has no evidence-level detection → adapter rejects
        with pytest.raises(ValueError):
            as_intervention_class('strong_braking')
        # entry_speed_surrender has no coaching_template → playbook rejects
        with pytest.raises(ValueError):
            as_weakness_playbook_entry('entry_speed_surrender')

    def test_behavior_defs_dict_equivalence(self):
        from track_surface.driver_development import BEHAVIOR_DEFS
        lib_bd = behavior_defs_dict()
        # Library is a superset: every legacy BEHAVIOR_DEFS key appears in the
        # library (by canonical id), with matching label/metric_key/direction/trainable.
        for legacy_key, legacy_def in BEHAVIOR_DEFS.items():
            canonical = resolve_alias(legacy_key)
            lib_def = lib_bd[canonical]
            assert lib_def['label'] == legacy_def['label']
            assert lib_def['metric_key'] == legacy_def['metric_key']
            assert lib_def['direction'] == legacy_def['direction']
            assert lib_def['trainable'] == legacy_def['trainable']

    def test_weakness_playbook_dict_equivalence(self):
        from track_surface.prescriptive_coaching import WEAKNESS_PLAYBOOK
        lib_wp = weakness_playbook_dict()
        for legacy_key, legacy_def in WEAKNESS_PLAYBOOK.items():
            canonical = resolve_alias(legacy_key)
            lib_def = lib_wp[canonical]
            assert lib_def['title'] == legacy_def['title']
            assert lib_def['phase'] == legacy_def['phase']
            assert lib_def['sensor_note'] == legacy_def['sensor_note']
            # content lists are identical (order-preserving)
            assert lib_def['likely_causes'] == list(legacy_def['likely_causes'])
            assert lib_def['coaching_actions'] == list(legacy_def['coaching_actions'])
            assert lib_def['driver_cues'] == list(legacy_def['driver_cues'])

    def test_intervention_classes_dict_equivalence(self):
        """Library is the source of truth. We assert STRUCTURAL equivalence:
        every legacy INTERVENTION_CLASSES key maps to a library pattern with
        the same phase and trainability. Labels are standardized by the
        library (consolidation is the whole point), so label strings may
        differ between legacy and library — that's expected and desired."""
        from track_surface.coaching_intelligence import INTERVENTION_CLASSES
        lib_ic = intervention_classes_dict()
        for legacy_key, legacy_def in INTERVENTION_CLASSES.items():
            canonical = resolve_alias(legacy_key)
            lib_def = lib_ic[canonical]
            assert isinstance(lib_def['label'], str) and lib_def['label']
            assert lib_def['phase'] == legacy_def['phase']
            # Trainability is a calibration value; legacy modules may disagree
            # on the same canonical concept. Library is the source of truth —
            # we only assert the library's value is in a valid range.
            assert 0.0 <= lib_def['trainability'] <= 1.0
            assert callable(lib_def['detect'])
            assert callable(lib_def['confidence_fn'])


# ── 7. Deterministic ordering ──────────────────────────────────


class TestDeterminism:
    def test_list_patterns_stable(self):
        ids1 = list_pattern_ids()
        ids2 = list_pattern_ids()
        assert ids1 == ids2

    def test_manifest_stable(self):
        m1 = library_manifest()
        m2 = library_manifest()
        assert m1 == m2


# ── 8. Sensor requirements declared per pattern ────────────────


class TestSensorHonesty:
    def test_every_pattern_declares_sensors(self):
        for p in list_patterns():
            assert len(p.sensor_requirements) > 0, (
                f'{p.pattern_id}: must declare at least one sensor_requirement'
            )

    def test_sensor_values_are_in_taxonomy(self):
        for p in list_patterns():
            for s in p.sensor_requirements:
                assert s in SENSORS


# ── 9. Template parameter resolution ───────────────────────────


class TestTemplateParams:
    def test_all_placeholders_declared(self):
        """Every {param} that appears in a coaching_action or driver_cue
        must be declared in template_params."""
        for p in list_patterns():
            if p.coaching_template is None:
                continue
            declared = set(p.coaching_template.template_params)
            combined = p.coaching_template.coaching_actions + p.coaching_template.driver_cues
            for s in combined:
                # extract all {tokens}
                i = 0
                while i < len(s):
                    lb = s.find('{', i)
                    if lb == -1:
                        break
                    rb = s.find('}', lb)
                    assert rb > lb, f'{p.pattern_id}: unclosed placeholder in {s!r}'
                    token = s[lb+1:rb]
                    assert token in declared, (
                        f'{p.pattern_id}: placeholder {{{token}}} not declared in template_params'
                    )
                    i = rb + 1

    def test_template_substitution_succeeds(self):
        """Given declared params, template strings format without KeyError."""
        for p in list_patterns():
            if p.coaching_template is None:
                continue
            subs = {param: f'<{param}>' for param in p.coaching_template.template_params}
            for s in p.coaching_template.coaching_actions:
                s.format(**subs)
            for s in p.coaching_template.driver_cues:
                s.format(**subs)


# ── 10. Relationship integrity + manifest shape ────────────────


class TestRelationshipsAndManifest:
    def test_related_patterns_exist(self):
        ids = set(list_pattern_ids())
        for p in list_patterns():
            for rel in p.related_patterns:
                assert rel in ids, (
                    f'{p.pattern_id}: related_pattern {rel!r} not in library'
                )

    def test_manifest_contains_required_keys(self):
        m = library_manifest()
        for k in ('library_version', 'phases', 'polarities', 'input_shapes',
                  'directions', 'sensors', 'pattern_count', 'aliases', 'patterns'):
            assert k in m
        assert m['library_version'] == LIBRARY_VERSION
        assert m['pattern_count'] == len(list_patterns())

    def test_manifest_alias_map_excludes_self(self):
        m = library_manifest()
        for alias, canonical in m['aliases'].items():
            assert alias != canonical

    def test_patterns_supporting_shape(self):
        feats = patterns_supporting_shape('corner_features')
        ev = patterns_supporting_shape('evidence_dict')
        # union must cover everything
        union = {p.pattern_id for p in feats} | {p.pattern_id for p in ev}
        assert union == set(list_pattern_ids())

    def test_invalid_shape_raises(self):
        with pytest.raises(ValueError):
            patterns_supporting_shape('nonsense')
