"""Phase 3 tests: engine + adapters + serialization.

Split into sections:
    A. Engine behaviour with explicit inputs
    B. Adapter robustness (upstream schema drift, None fields)
    C. Serialization shape lock (dict keys match published contract)
    D. Semantic parity with legacy ``generate_prescriptive_coaching``
       on the live ok-data.json inputs

Engine behaviour tests use synthetic inputs — fixture JSON parity lives
in section D.
"""
from __future__ import annotations

import json
import os

import pytest

from track_surface.prescriptive import (
    CoachingSheet,
    build_default_registry,
    generate_coaching_sheet,
    run,
    to_json_dict,
)
from track_surface.prescriptive._internal import (
    Evidence,
    Insufficient,
    Unregistered,
    WeaknessContext,
)
from track_surface.prescriptive.adapters import (
    context_list_from_weaknesses,
    evidence_from_corner_packet_dict,
    evidence_list_from_packets,
    weakness_context_from_dict,
)
from track_surface.prescriptive.registry import PatternRegistry


_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_JSON = os.path.join(_REPO, "track-surface-ok-data.json")


# ─── helpers ─────────────────────────────────────────────────────

def _ev_dict(cid: int, *, td=300.0, ms=-8.0, brake=-6.0, throttle=8.0,
             exit_spd=-6.0, line=0.5, conf=0.8) -> dict:
    return {
        "corner_id": cid,
        "time_delta_ms": td,
        "primary_cause": "test",
        "confidence": conf,
        "s_entry_m": cid * 100.0,
        "s_apex_m": cid * 100.0 + 25.0,
        "s_exit_m": cid * 100.0 + 50.0,
        "evidence": {
            "min_speed_delta_kph": ms,
            "brake_point_delta_m": brake,
            "throttle_pickup_delta_m": throttle,
            "exit_speed_delta_kph": exit_spd,
            "line_deviation_rms_m": line,
        },
    }


def _weak_dict(bid: str, *, occ=30, trend="improving", cost=300.0,
               corners=(1, 2, 3), archetypes=("slow_90deg",),
               sessions=("S1", "S2", "S3"), conf=0.8) -> dict:
    return {
        "behavior_id": bid,
        "label": bid.replace("_", " ").title(),
        "occurrence_count": occ,
        "trend": trend,
        "estimated_time_cost_ms": cost,
        "confidence": conf,
        "corners_observed": list(corners),
        "archetypes_observed": list(archetypes),
        "sessions_observed": list(sessions),
    }


# ═════════════════════════════════════════════════════════════════
# A. Engine behaviour
# ═════════════════════════════════════════════════════════════════


class TestEngineEmpty:
    def test_empty_inputs_return_empty_sheet(self):
        sheet = generate_coaching_sheet(
            corner_packets=[], weaknesses=[],
            sessions_analyzed=3, laps_analyzed=0,
        )
        assert sheet.version
        assert sheet.global_focus == ()
        assert sheet.weakness_playbook_matches == ()
        # Empty short-circuit should also emit the insufficient_data storyline.
        assert any(s.type == "insufficient_data" for s in sheet.storyline)


class TestEngineDetected:
    def _basic(self):
        pkts = [_ev_dict(i) for i in (1, 2, 3, 4)]
        weaks = [_weak_dict("low_minimum_speed", cost=500.0, corners=(1, 2, 3, 4))]
        return generate_coaching_sheet(
            corner_packets=pkts, weaknesses=weaks,
            sessions_analyzed=5, laps_analyzed=40,
        )

    def test_single_detected_produces_focus(self):
        sheet = self._basic()
        assert len(sheet.global_focus) == 1
        assert sheet.global_focus[0].weakness_key == "low_minimum_speed"
        assert sheet.global_focus[0].severity == "high"
        assert sheet.global_focus[0].rank == 1

    def test_single_detected_produces_playbook_match(self):
        sheet = self._basic()
        assert len(sheet.weakness_playbook_matches) == 1
        pm = sheet.weakness_playbook_matches[0]
        assert pm.matched_playbook is True
        assert pm.coaching_actions
        # No unresolved templates in any coaching action.
        assert all("{" not in a for a in pm.coaching_actions)

    def test_corner_coaching_emitted_for_matched_corners(self):
        sheet = self._basic()
        matched_cids = {cc.corner_id for cc in sheet.corner_coaching}
        assert {1, 2, 3, 4} <= matched_cids

    def test_storyline_has_primary_focus(self):
        sheet = self._basic()
        types_ = {s.type for s in sheet.storyline}
        assert "primary_focus" in types_


class TestEngineRanking:
    def test_global_focus_sorted_by_cost_descending(self):
        pkts = [_ev_dict(i) for i in (1, 2, 3)]
        weaks = [
            _weak_dict("low_minimum_speed", cost=150.0, corners=(1, 2, 3)),
            _weak_dict("early_braking", cost=500.0, corners=(1, 2, 3)),
            _weak_dict("weak_exit_build", cost=300.0, corners=(1, 2, 3)),
        ]
        sheet = generate_coaching_sheet(
            corner_packets=pkts, weaknesses=weaks,
            sessions_analyzed=5, laps_analyzed=50,
        )
        costs = [f.estimated_cost_ms for f in sheet.global_focus]
        assert costs == sorted(costs, reverse=True)
        assert sheet.global_focus[0].weakness_key == "early_braking"

    def test_global_focus_capped_at_three(self):
        pkts = [_ev_dict(i) for i in (1, 2, 3)]
        weaks = [
            _weak_dict("low_minimum_speed", corners=(1, 2, 3)),
            _weak_dict("early_braking", corners=(1, 2, 3)),
            _weak_dict("late_throttle_pickup", corners=(1, 2, 3)),
            _weak_dict("weak_exit_build", corners=(1, 2, 3)),
            _weak_dict("line_deviation", corners=(1, 2, 3)),
        ]
        sheet = generate_coaching_sheet(
            corner_packets=pkts, weaknesses=weaks,
            sessions_analyzed=5, laps_analyzed=50,
        )
        assert len(sheet.global_focus) == 3


class TestNextRunPlan:
    def test_empty_when_no_detected(self):
        sheet = generate_coaching_sheet(
            corner_packets=[_ev_dict(1)], weaknesses=[],
            sessions_analyzed=5, laps_analyzed=10,
        )
        assert sheet.next_run_plan == ()

    def test_caps_at_three_plus_anti_overload(self):
        pkts = [_ev_dict(i) for i in (1, 2, 3)]
        weaks = [
            _weak_dict("low_minimum_speed", corners=(1, 2, 3)),
            _weak_dict("early_braking", corners=(1, 2, 3)),
            _weak_dict("late_throttle_pickup", corners=(1, 2, 3)),
            _weak_dict("weak_exit_build", corners=(1, 2, 3)),
        ]
        sheet = generate_coaching_sheet(
            corner_packets=pkts, weaknesses=weaks,
            sessions_analyzed=5, laps_analyzed=50,
        )
        assert len(sheet.next_run_plan) == 4  # 3 + anti-overload
        types_ = [n.type for n in sheet.next_run_plan]
        assert types_[:3] == ["technical_focus", "execution_focus", "validation_metric"]
        assert types_[-1] == "anti_overload"

    def test_anti_overload_is_rank_zero(self):
        pkts = [_ev_dict(i) for i in (1, 2)]
        weaks = [_weak_dict("low_minimum_speed", corners=(1, 2))]
        sheet = generate_coaching_sheet(
            corner_packets=pkts, weaknesses=weaks,
            sessions_analyzed=5, laps_analyzed=20,
        )
        anti = [n for n in sheet.next_run_plan if n.type == "anti_overload"]
        assert len(anti) == 1
        assert anti[0].rank == 0


class TestUnregisteredSurfaces:
    def test_unknown_weakness_key_appears_in_storyline(self):
        """This is the core design delta — legacy silently drops these.
        The engine MUST surface them."""
        pkts = [_ev_dict(i) for i in (1, 2)]
        weaks = [
            _weak_dict("low_minimum_speed", corners=(1, 2)),
            _weak_dict("some_brand_new_weakness", corners=(1, 2)),
        ]
        sheet = generate_coaching_sheet(
            corner_packets=pkts, weaknesses=weaks,
            sessions_analyzed=5, laps_analyzed=20,
        )
        unreg = [s for s in sheet.storyline if s.type == "unregistered_weakness"]
        assert len(unreg) == 1
        assert "some_brand_new_weakness" in unreg[0].text


class TestInsufficientSurfaces:
    def test_missing_evidence_fields_surface_in_storyline(self):
        """When a weakness exists but required evidence is all-None,
        emit insufficient_data — do NOT silently drop."""
        # Evidence with brake_point_delta_m = None everywhere.
        pkts = [
            {
                "corner_id": i,
                "time_delta_ms": 200.0,
                "primary_cause": "t",
                "confidence": 0.5,
                "s_entry_m": i * 100.0, "s_apex_m": i * 100.0 + 25, "s_exit_m": i * 100.0 + 50,
                "evidence": {
                    "min_speed_delta_kph": -5.0,
                    "brake_point_delta_m": None,  # missing
                    "throttle_pickup_delta_m": None,
                    "exit_speed_delta_kph": -5.0,
                    "line_deviation_rms_m": 0.3,
                },
            }
            for i in (1, 2)
        ]
        weaks = [_weak_dict("early_braking", corners=(1, 2))]
        sheet = generate_coaching_sheet(
            corner_packets=pkts, weaknesses=weaks,
            sessions_analyzed=5, laps_analyzed=20,
        )
        ins = [s for s in sheet.storyline if s.type == "insufficient_data"]
        assert len(ins) == 1
        assert "brake_point_delta_m" in ins[0].text
        # No silent detection.
        assert not any(
            f.weakness_key == "early_braking" for f in sheet.global_focus
        )


class TestSparseDataWarning:
    def test_fewer_than_three_sessions_warns(self):
        sheet = generate_coaching_sheet(
            corner_packets=[_ev_dict(1)], weaknesses=[_weak_dict("low_minimum_speed", corners=(1,))],
            sessions_analyzed=1, laps_analyzed=5,
        )
        assert any(s.type == "data_warning" for s in sheet.storyline)


class TestLimits:
    def test_limits_populated_from_inputs(self):
        sheet = generate_coaching_sheet(
            corner_packets=[_ev_dict(1)], weaknesses=[],
            sessions_analyzed=7, laps_analyzed=42,
        )
        assert sheet.limits.sessions_analyzed == 7
        assert sheet.limits.laps_analyzed == 42
        assert "brake" in sheet.limits.brake_data.lower()


class TestSource:
    def test_source_is_canonical_bronze_plus_dev_intel(self):
        sheet = generate_coaching_sheet(
            corner_packets=[_ev_dict(1)], weaknesses=[_weak_dict("low_minimum_speed", corners=(1,))],
            sessions_analyzed=5, laps_analyzed=10,
        )
        assert "bronze" in sheet.source.lower()
        assert "beta" not in sheet.source.lower()


# ═════════════════════════════════════════════════════════════════
# B. Adapter robustness
# ═════════════════════════════════════════════════════════════════


class TestAdapters:
    def test_evidence_from_packet_with_no_evidence_dict(self):
        """Missing 'evidence' key → Optionals become None."""
        ev = evidence_from_corner_packet_dict({"corner_id": 5})
        assert ev.corner_id == 5
        assert ev.brake_point_delta_m is None
        assert ev.min_speed_delta_kph is None

    def test_evidence_preserves_non_zero_confidence(self):
        ev = evidence_from_corner_packet_dict({
            "corner_id": 1, "confidence": 0.75,
        })
        assert ev.confidence == 0.75

    def test_evidence_bad_float_becomes_none(self):
        ev = evidence_from_corner_packet_dict({
            "corner_id": 1,
            "evidence": {"brake_point_delta_m": "not-a-number"},
        })
        assert ev.brake_point_delta_m is None

    def test_weakness_context_requires_behavior_id(self):
        with pytest.raises(KeyError):
            weakness_context_from_dict({}, sessions_analyzed=3)

    def test_weakness_context_defaults_safe(self):
        wc = weakness_context_from_dict(
            {"behavior_id": "test"}, sessions_analyzed=3,
        )
        assert wc.key == "test"
        assert wc.occurrence_count == 0
        assert wc.corners_observed == ()
        assert wc.sessions_analyzed == 3

    def test_context_list_from_weaknesses(self):
        ctxs = context_list_from_weaknesses(
            [_weak_dict("low_minimum_speed"), _weak_dict("early_braking")],
            sessions_analyzed=5,
        )
        assert len(ctxs) == 2
        assert all(c.sessions_analyzed == 5 for c in ctxs)


# ═════════════════════════════════════════════════════════════════
# C. Serialization shape lock
# ═════════════════════════════════════════════════════════════════


class TestSerialization:
    def test_to_json_dict_top_keys(self):
        sheet = generate_coaching_sheet(
            corner_packets=[_ev_dict(1)], weaknesses=[_weak_dict("low_minimum_speed", corners=(1,))],
            sessions_analyzed=5, laps_analyzed=10,
        )
        out = to_json_dict(sheet)
        expected = {
            "version", "source", "global_focus", "corner_coaching",
            "weakness_playbook_matches", "next_run_plan",
            "validation_checks", "storyline", "limits",
        }
        assert set(out.keys()) == expected

    def test_tuples_become_lists(self):
        sheet = generate_coaching_sheet(
            corner_packets=[_ev_dict(i) for i in (1, 2, 3)],
            weaknesses=[_weak_dict("low_minimum_speed", corners=(1, 2, 3))],
            sessions_analyzed=5, laps_analyzed=10,
        )
        out = to_json_dict(sheet)
        assert isinstance(out["global_focus"], list)
        if out["global_focus"]:
            assert isinstance(out["global_focus"][0]["corners"], list)

    def test_is_json_serialisable(self):
        sheet = generate_coaching_sheet(
            corner_packets=[_ev_dict(i) for i in (1, 2, 3)],
            weaknesses=[_weak_dict("low_minimum_speed", corners=(1, 2, 3))],
            sessions_analyzed=5, laps_analyzed=10,
        )
        out = to_json_dict(sheet)
        # Round-trip through JSON to prove no non-serialisable objects leak.
        reloaded = json.loads(json.dumps(out))
        assert reloaded["version"] == sheet.version


# ═════════════════════════════════════════════════════════════════
# D. Semantic parity against the live ok-data.json
# ═════════════════════════════════════════════════════════════════


def _load_live() -> dict | None:
    if not os.path.isfile(_JSON):
        return None
    with open(_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


class TestLiveParity:
    @pytest.fixture
    def live(self):
        data = _load_live()
        if data is None:
            pytest.skip("track-surface-ok-data.json missing")
        return data

    def test_shape_lock_top_keys(self, live):
        """New engine's JSON output must have exactly the same top-level keys
        as the live JSON's prescriptive_coaching node."""
        live_pc = live.get("prescriptive_coaching")
        if live_pc is None:
            pytest.skip("prescriptive_coaching absent from JSON")
        # Reconstruct inputs the legacy module consumed.
        compare = live.get("session_compare", {})
        dev = live.get("development_intelligence", {})
        pkts = compare.get("corner_packets", [])
        weaks = dev.get("recurring_weaknesses", [])
        sessions = dev.get("sessions_analyzed", 1)
        laps = dev.get("laps_analyzed", 0)
        sheet = generate_coaching_sheet(
            corner_packets=pkts, weaknesses=weaks,
            sessions_analyzed=sessions, laps_analyzed=laps,
        )
        new_json = to_json_dict(sheet)
        assert set(new_json.keys()) == set(live_pc.keys())

    def test_same_detected_weakness_keys(self, live):
        """Given the same upstream, the new engine fires on the same
        weaknesses as legacy (subset of both since Insufficient/Unregistered
        may split some)."""
        live_pc = live.get("prescriptive_coaching")
        if live_pc is None:
            pytest.skip("prescriptive_coaching absent")
        compare = live.get("session_compare", {})
        dev = live.get("development_intelligence", {})
        pkts = compare.get("corner_packets", [])
        weaks = dev.get("recurring_weaknesses", [])
        sessions = dev.get("sessions_analyzed", 1)
        laps = dev.get("laps_analyzed", 0)
        sheet = generate_coaching_sheet(
            corner_packets=pkts, weaknesses=weaks,
            sessions_analyzed=sessions, laps_analyzed=laps,
        )
        new_keys = {pm.weakness_key for pm in sheet.weakness_playbook_matches}
        live_keys = {pm["weakness_key"] for pm in live_pc["weakness_playbook_matches"]}
        # New engine must detect AT LEAST what legacy detected (since the
        # only gain-only deltas are surfacing previously-hidden states).
        assert live_keys <= new_keys


# ═════════════════════════════════════════════════════════════════
# E. Custom registry (facade accepts an override)
# ═════════════════════════════════════════════════════════════════


class TestCustomRegistry:
    def test_custom_registry_restricts_patterns(self):
        """Passing a custom registry with fewer patterns should yield fewer
        (or zero) prescriptions."""
        reg = PatternRegistry()  # empty
        sheet = generate_coaching_sheet(
            corner_packets=[_ev_dict(1), _ev_dict(2)],
            weaknesses=[_weak_dict("low_minimum_speed", corners=(1, 2))],
            sessions_analyzed=5, laps_analyzed=10,
            registry=reg,
        )
        # Every weakness is Unregistered → storyline surfaces it, no focus.
        assert sheet.global_focus == ()
        assert any(s.type == "unregistered_weakness" for s in sheet.storyline)
