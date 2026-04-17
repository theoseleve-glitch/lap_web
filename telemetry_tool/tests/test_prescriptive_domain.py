"""Phase 1+2 domain tests for ``track_surface.prescriptive``.

Scope — this file tests ONLY:
    - DTO shape + immutability
    - enum / literal bounds
    - ``severity_for`` policy (severity thresholds are part of the contract)
    - internal vs public separation at the package boundary
    - pattern registry semantics
    - schema-lock against the live ok-data.json

Pattern-specific behaviour (what each concrete pattern emits) lives in
``test_prescriptive_patterns.py``. Engine behaviour is Phase 3.
"""
from __future__ import annotations

import dataclasses
import json
import os
import typing

import pytest

from track_surface.prescriptive import (
    COACHING_SHEET_VERSION,
    HIGH_SEVERITY_MS,
    MEDIUM_SEVERITY_MS,
    CoachingSheet,
    CornerCoaching,
    FocusItem,
    Limits,
    NextRunItem,
    Pattern,
    PatternRegistry,
    PhaseTag,
    PlaybookMatch,
    Severity,
    StorylineEntry,
    ValidationCheck,
    severity_for,
)
from track_surface.prescriptive._internal import (
    Detected,
    Evidence,
    Insufficient,
    NotTriggered,
    PatternResult,
    Unregistered,
    WeaknessContext,
    portability_for,
)


_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_JSON = os.path.join(_REPO, "track-surface-ok-data.json")


# ═════════════════════════════════════════════════════════════════
# 1. Version and enum anchors
# ═════════════════════════════════════════════════════════════════


class TestVersionAndEnums:
    def test_version_is_one_zero(self):
        """Frozen at v1.0 to preserve the lap-studio / ouest-karting HTML contract."""
        assert COACHING_SHEET_VERSION == "1.0"

    def test_severity_values_match_legacy(self):
        """Viewers already see 'high' | 'medium' | 'low' — must not silently drift."""
        assert typing.get_args(Severity) == ("high", "medium", "low")

    def test_phasetag_is_superset_of_current_usage(self):
        """PhaseTag must at least cover every phase currently emitted:
        - legacy WEAKNESS_PLAYBOOK uses 'apex', 'entry', 'exit'
        - coaching_intelligence.PHASES adds 'brake_release', 'straight'
        """
        values = set(typing.get_args(PhaseTag))
        for phase in ("apex", "entry", "exit", "brake_release", "straight"):
            assert phase in values, f"PhaseTag missing {phase!r}"


# ═════════════════════════════════════════════════════════════════
# 2. Severity policy (content contract)
# ═════════════════════════════════════════════════════════════════


class TestSeverityPolicy:
    def test_thresholds_match_legacy(self):
        """Legacy hardcodes 400 / 150 ms in ``prescriptive_coaching.py:202-207``.
        Changing these shifts the focus list — version bump required."""
        assert HIGH_SEVERITY_MS == 400.0
        assert MEDIUM_SEVERITY_MS == 150.0

    def test_severity_for_high(self):
        assert severity_for(500.0) == "high"
        assert severity_for(HIGH_SEVERITY_MS + 0.01) == "high"

    def test_severity_for_medium(self):
        assert severity_for(200.0) == "medium"
        assert severity_for(MEDIUM_SEVERITY_MS + 0.01) == "medium"
        assert severity_for(HIGH_SEVERITY_MS) == "medium"  # > not >=

    def test_severity_for_low(self):
        assert severity_for(100.0) == "low"
        assert severity_for(0.0) == "low"
        assert severity_for(MEDIUM_SEVERITY_MS) == "low"  # > not >=


# ═════════════════════════════════════════════════════════════════
# 3. DTO immutability
# ═════════════════════════════════════════════════════════════════


class TestDTOImmutability:
    def test_focus_item_is_frozen(self):
        fi = FocusItem(
            rank=1, weakness_key="x", title="T", severity="low",
            estimated_cost_ms=10.0, corners=(1,), phase="apex", confidence=0.5,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            fi.rank = 2  # type: ignore[misc]

    def test_coaching_sheet_is_frozen(self):
        sheet = CoachingSheet.empty(_minimal_limits())
        with pytest.raises(dataclasses.FrozenInstanceError):
            sheet.version = "9.9"  # type: ignore[misc]

    def test_collection_fields_are_tuples(self):
        """Mutable list fields in a frozen dataclass defeat the invariant."""
        sheet = CoachingSheet.empty(_minimal_limits())
        assert isinstance(sheet.global_focus, tuple)
        assert isinstance(sheet.corner_coaching, tuple)
        assert isinstance(sheet.weakness_playbook_matches, tuple)
        assert isinstance(sheet.next_run_plan, tuple)
        assert isinstance(sheet.validation_checks, tuple)
        assert isinstance(sheet.storyline, tuple)


# ═════════════════════════════════════════════════════════════════
# 4. Empty sheet
# ═════════════════════════════════════════════════════════════════


class TestEmptySheet:
    def test_empty_has_insufficient_data_storyline(self):
        sheet = CoachingSheet.empty(_minimal_limits())
        types_ = {s.type for s in sheet.storyline}
        assert "insufficient_data" in types_

    def test_empty_has_no_prescriptions(self):
        sheet = CoachingSheet.empty(_minimal_limits())
        assert sheet.global_focus == ()
        assert sheet.weakness_playbook_matches == ()
        assert sheet.next_run_plan == ()
        assert sheet.validation_checks == ()
        assert sheet.corner_coaching == ()

    def test_empty_pinned_to_canonical_source(self):
        sheet = CoachingSheet.empty(_minimal_limits())
        assert "bronze" in sheet.source.lower()
        assert "beta" not in sheet.source.lower()
        assert "diagnostic" not in sheet.source.lower()
        assert "gold_lab" not in sheet.source.lower()


# ═════════════════════════════════════════════════════════════════
# 5. Internal vs public separation
# ═════════════════════════════════════════════════════════════════


class TestInternalPublicSeparation:
    def test_internal_names_not_in_public_namespace(self):
        """Research-layer concepts must not be reachable via
        ``from track_surface.prescriptive import X``."""
        import track_surface.prescriptive as pkg
        for name in (
            "Evidence",
            "WeaknessContext",
            "Detected",
            "NotTriggered",
            "Insufficient",
            "Unregistered",
            "PatternResult",
            "portability_for",
        ):
            assert not hasattr(pkg, name), (
                f"{name!r} must not be re-exported from track_surface.prescriptive — "
                f"it is a research-layer symbol."
            )
            assert name not in pkg.__all__

    def test_internal_module_importable_directly(self):
        """Pattern implementations need these types; they must still be
        reachable via the underscore-prefixed module path."""
        from track_surface.prescriptive import _internal  # noqa: F401
        assert _internal.Evidence is not None
        assert _internal.WeaknessContext is not None
        assert _internal.PatternResult is not None


# ═════════════════════════════════════════════════════════════════
# 6. PatternResult sum type — the core state-separation invariant
# ═════════════════════════════════════════════════════════════════


class TestPatternResult:
    def test_all_four_variants_are_dataclasses(self):
        for cls in (Detected, NotTriggered, Insufficient, Unregistered):
            assert dataclasses.is_dataclass(cls), f"{cls.__name__} must be a dataclass"

    def test_detected_carries_affected_and_not_evaluable_corners(self):
        d = _make_detected(
            affected_corners=(1, 2, 3), not_evaluable_corners=(7,), cost_ms=100.0,
        )
        assert d.affected_corners == (1, 2, 3)
        assert d.not_evaluable_corners == (7,)
        assert d.cost_ms == 100.0

    def test_insufficient_lists_missing_fields(self):
        ins = Insufficient(
            weakness_key="k",
            missing_fields=("brake_point_delta_m", "throttle_pickup_delta_m"),
            reason="required evidence absent",
        )
        assert "brake_point_delta_m" in ins.missing_fields
        assert ins.reason

    def test_unregistered_carries_key(self):
        u = Unregistered(weakness_key="some_unknown_weakness")
        assert u.weakness_key == "some_unknown_weakness"

    def test_four_variants_are_distinct_types(self):
        """The whole design rule 'separate pattern detected from data
        insufficient' depends on the variants being type-distinguishable."""
        nt = NotTriggered(weakness_key="k", reason="r")
        ins = Insufficient(weakness_key="k", missing_fields=(), reason="r")
        unreg = Unregistered(weakness_key="k")
        det = _make_detected()
        assert len({type(nt), type(ins), type(unreg), type(det)}) == 4

    def test_pattern_result_union_covers_all_four(self):
        variants = set(typing.get_args(PatternResult))
        assert variants == {Detected, NotTriggered, Insufficient, Unregistered}


# ═════════════════════════════════════════════════════════════════
# 7. Evidence + WeaknessContext
# ═════════════════════════════════════════════════════════════════


class TestEvidence:
    def test_optional_fields_allow_none(self):
        """Absent sensors must be representable as None — never silently 0."""
        ev = _minimal_evidence()
        assert ev.brake_point_delta_m is None
        assert ev.min_speed_delta_kph is None
        assert ev.throttle_pickup_delta_m is None

    def test_evidence_is_frozen(self):
        ev = _minimal_evidence()
        with pytest.raises(dataclasses.FrozenInstanceError):
            ev.corner_id = 9  # type: ignore[misc]


class TestWeaknessContext:
    def test_all_fields_required(self):
        wc = _minimal_context()
        assert wc.key == "test"
        assert wc.sessions_analyzed == 3

    def test_context_is_frozen(self):
        wc = _minimal_context()
        with pytest.raises(dataclasses.FrozenInstanceError):
            wc.key = "other"  # type: ignore[misc]


# ═════════════════════════════════════════════════════════════════
# 8. portability_for heuristic
# ═════════════════════════════════════════════════════════════════


class TestPortability:
    def test_too_few_sessions_returns_unknown(self):
        assert portability_for(("a", "b", "c"), sessions_analyzed=2) == (
            "unknown (too few sessions)"
        )

    def test_three_archetypes_returns_likely_portable(self):
        result = portability_for(("a", "b", "c"), sessions_analyzed=5)
        assert "likely portable" in result

    def test_two_archetypes_returns_possibly_portable(self):
        result = portability_for(("a", "b"), sessions_analyzed=5)
        assert "possibly portable" in result

    def test_single_archetype_returns_track_specific(self):
        result = portability_for(("a",), sessions_analyzed=5)
        assert "track-specific" in result


# ═════════════════════════════════════════════════════════════════
# 9. Pattern registry
# ═════════════════════════════════════════════════════════════════


class _StubPattern:
    key = "stub_weakness"
    title = "Stub"
    phase: PhaseTag = "apex"
    required_fields = ("min_speed_delta_kph",)

    def evaluate(self, context, evidence):
        return NotTriggered(weakness_key=self.key, reason="stub")


class _NotAPattern:
    """Missing key/title/phase/required_fields/evaluate — should be rejected."""


class _Pattern2:
    key = "weak2"
    title = "W2"
    phase: PhaseTag = "entry"
    required_fields: tuple[str, ...] = ()

    def evaluate(self, context, evidence):
        return NotTriggered(weakness_key=self.key, reason="p2")


class _Pattern3:
    key = "weak3"
    title = "W3"
    phase: PhaseTag = "exit"
    required_fields: tuple[str, ...] = ()

    def evaluate(self, context, evidence):
        return NotTriggered(weakness_key=self.key, reason="p3")


class TestPatternRegistry:
    def test_register_then_get_round_trip(self):
        reg = PatternRegistry()
        p = _StubPattern()
        reg.register(p)
        assert reg.get("stub_weakness") is p

    def test_get_unknown_returns_none(self):
        reg = PatternRegistry()
        assert reg.get("nope") is None

    def test_duplicate_register_raises_valueerror(self):
        reg = PatternRegistry()
        reg.register(_StubPattern())
        with pytest.raises(ValueError, match="already registered"):
            reg.register(_StubPattern())

    def test_non_pattern_object_raises_typeerror(self):
        reg = PatternRegistry()
        with pytest.raises(TypeError):
            reg.register(_NotAPattern())  # type: ignore[arg-type]

    def test_insertion_order_preserved(self):
        reg = PatternRegistry()
        reg.register(_StubPattern())
        reg.register(_Pattern2())
        reg.register(_Pattern3())
        assert reg.keys() == ("stub_weakness", "weak2", "weak3")

    def test_contains_operator(self):
        reg = PatternRegistry()
        reg.register(_StubPattern())
        assert "stub_weakness" in reg
        assert "other" not in reg

    def test_len(self):
        reg = PatternRegistry()
        assert len(reg) == 0
        reg.register(_StubPattern())
        assert len(reg) == 1
        reg.register(_Pattern2())
        assert len(reg) == 2

    def test_iter_yields_patterns_in_order(self):
        reg = PatternRegistry()
        reg.register(_StubPattern())
        reg.register(_Pattern2())
        seen = [p.key for p in reg]
        assert seen == ["stub_weakness", "weak2"]

    def test_remove_then_re_register_is_allowed(self):
        reg = PatternRegistry()
        reg.register(_StubPattern())
        reg.remove("stub_weakness")
        reg.register(_StubPattern())  # must not raise

    def test_remove_unknown_raises_keyerror(self):
        reg = PatternRegistry()
        with pytest.raises(KeyError):
            reg.remove("nope")

    def test_stub_satisfies_pattern_protocol(self):
        """Sanity check: the test stub conforms to the Pattern protocol."""
        assert isinstance(_StubPattern(), Pattern)


# ═════════════════════════════════════════════════════════════════
# 10. Schema lock against the live ok-data.json
# ═════════════════════════════════════════════════════════════════


def _load_live_sheet() -> dict | None:
    if not os.path.isfile(_JSON):
        return None
    with open(_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("prescriptive_coaching")


_LIST_DTO_MAP = {
    "global_focus": FocusItem,
    "corner_coaching": CornerCoaching,
    "weakness_playbook_matches": PlaybookMatch,
    "next_run_plan": NextRunItem,
    "validation_checks": ValidationCheck,
    "storyline": StorylineEntry,
}


def test_live_top_level_keys_covered_by_coaching_sheet():
    live = _load_live_sheet()
    if live is None:
        pytest.skip("track-surface-ok-data.json missing or lacks prescriptive_coaching")
    sheet_fields = {f.name for f in dataclasses.fields(CoachingSheet)}
    missing = [k for k in live.keys() if k not in sheet_fields]
    assert not missing, (
        f"CoachingSheet does not cover live JSON keys: {missing}. "
        f"Add them to types.py BEFORE Phase 3 swaps the producer."
    )


def test_live_limits_keys_covered():
    live = _load_live_sheet()
    if live is None or "limits" not in live:
        pytest.skip("limits block not present in live JSON")
    limit_fields = {f.name for f in dataclasses.fields(Limits)}
    missing = [k for k in live["limits"].keys() if k not in limit_fields]
    assert not missing, f"Limits DTO does not cover live limits keys: {missing}"


@pytest.mark.parametrize("list_key,dto_cls", list(_LIST_DTO_MAP.items()))
def test_live_list_element_keys_covered(list_key, dto_cls):
    live = _load_live_sheet()
    if live is None:
        pytest.skip("track-surface-ok-data.json missing")
    items = live.get(list_key) or []
    if not items:
        pytest.skip(f"no {list_key} items in live JSON")
    fields_ = {f.name for f in dataclasses.fields(dto_cls)}
    missing = [k for k in items[0].keys() if k not in fields_]
    assert not missing, (
        f"{dto_cls.__name__} does not cover live {list_key}[0] keys: {missing}"
    )


# ═════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════


def _minimal_limits() -> Limits:
    return Limits(
        sessions_analyzed=0, laps_analyzed=0,
        brake_data="n/a", throttle_data="n/a", steering_data="n/a",
        cross_track_portability="n/a", weather_conditions="n/a",
        reference_basis="n/a", confidence_floor="n/a",
    )


def _minimal_evidence() -> Evidence:
    return Evidence(
        corner_id=1, time_delta_ms=100.0, primary_cause="t", confidence=0.5,
        s_entry_m=None, s_apex_m=None, s_exit_m=None,
        min_speed_delta_kph=None, brake_point_delta_m=None,
        throttle_pickup_delta_m=None, exit_speed_delta_kph=None,
        line_deviation_rms_m=None,
    )


def _minimal_context() -> WeaknessContext:
    return WeaknessContext(
        key="test", label="Test", occurrence_count=10, trend="flat",
        estimated_time_cost_ms=100.0, confidence=0.5,
        corners_observed=(1, 2, 3), archetypes_observed=("slow_90deg",),
        sessions_observed=("S1", "S2", "S3"), sessions_analyzed=3,
    )


def _make_detected(
    *,
    weakness_key: str = "k",
    title: str = "T",
    phase: PhaseTag = "apex",
    affected_corners: tuple[int, ...] = (),
    not_evaluable_corners: tuple[int, ...] = (),
    cost_ms: float = 0.0,
    severity: Severity = "low",
    confidence: float = 0.5,
) -> Detected:
    return Detected(
        weakness_key=weakness_key, title=title, phase=phase,
        affected_corners=affected_corners,
        not_evaluable_corners=not_evaluable_corners,
        cost_ms=cost_ms, severity=severity, confidence=confidence,
        likely_causes=(), coaching_actions=(), driver_cues=(),
        measurable_targets=(), sensor_note="", portability="", data_support="",
    )
