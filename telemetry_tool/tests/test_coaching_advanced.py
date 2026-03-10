"""Tests for the advanced coaching engine (rich data channels)."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Ensure telemetry_tool is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from coaching_advanced import get_coaching_tier, generate_advanced_coaching
from coaching_basic import SectionCoaching
from track_decomposition import TrackSection
from mrp_detector import CornerEvents
from handling_detector import HandlingEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_corner_section(section_id: int = 1, s_start: float = 0.0,
                         s_end: float = 100.0) -> TrackSection:
    return TrackSection(
        section_id=section_id,
        section_type="corner",
        corner_type="medium",
        s_start=s_start,
        s_end=s_end,
        direction="R",
        geometric_apex=(s_start + s_end) / 2.0,
        exit_importance=0.3,
    )


def _make_straight_section(section_id: int = 2, s_start: float = 100.0,
                           s_end: float = 300.0) -> TrackSection:
    return TrackSection(
        section_id=section_id,
        section_type="straight",
        corner_type=None,
        s_start=s_start,
        s_end=s_end,
        direction=None,
        geometric_apex=None,
        exit_importance=0.0,
    )


def _make_events(corner_id: int = 1, mrp_m: float = 50.0) -> CornerEvents:
    return CornerEvents(
        corner_id=corner_id,
        brake_point_m=10.0,
        turn_in_m=20.0,
        trail_brake_end_m=35.0,
        mrp_m=mrp_m,
        mrp_speed_mps=15.0,
        mrp_yaw_rate=0.5,
        throttle_application_m=60.0,
        track_out_m=90.0,
        geometric_apex_m=50.0,
        mrp_apex_delta_m=0.0,
    )


def _make_handling(corner_id: int = 1) -> list[HandlingEvent]:
    return [
        HandlingEvent(
            corner_id=corner_id,
            event_type="understeer",
            severity="mild",
            s_start=55.0,
            s_end=70.0,
            duration_s=0.4,
            magnitude=0.12,
            cause="early_throttle",
            cause_detail="Understeer caused by throttle application.",
            time_cost_s=0.05,
            corner_phase="exit",
        ),
        HandlingEvent(
            corner_id=corner_id,
            event_type="oversteer",
            severity="moderate",
            s_start=20.0,
            s_end=35.0,
            duration_s=0.3,
            magnitude=0.22,
            cause="trail_brake_too_deep",
            cause_detail="Oversteer under hard trail braking.",
            time_cost_s=0.08,
            corner_phase="entry",
        ),
    ]


def _make_lap_df(s_start: float = 0.0, s_end: float = 300.0, n: int = 300,
                 include_throttle: bool = False,
                 include_steering: bool = False,
                 include_rpm_gear: bool = False,
                 include_brake: bool = False) -> pd.DataFrame:
    """Build a synthetic lap DataFrame."""
    dist = np.linspace(s_start, s_end, n)
    speed = 15.0 + 5.0 * np.sin(dist / 50.0)  # varies ~10-20 m/s
    data = {"Distance (m)": dist, "Speed (m/s)": speed}

    if include_throttle:
        # Throttle ramps up from 0 to 100 across section
        data["Throttle"] = np.linspace(0.0, 100.0, n)

    if include_steering:
        # Steering trace with some corrections
        base_steering = 20.0 * np.sin(dist / 30.0)
        noise = np.random.default_rng(42).normal(0, 2.0, n)
        data["Steering"] = base_steering + noise

    if include_rpm_gear:
        data["RPM"] = 5000.0 + 2000.0 * np.sin(dist / 50.0)
        data["Gear"] = np.where(speed > 15.0, 3.0, 2.0)

    if include_brake:
        data["Brake"] = np.where(dist < 30.0, 80.0, 0.0)

    return pd.DataFrame(data)


# ---------------------------------------------------------------------------
# Tier detection tests
# ---------------------------------------------------------------------------

class TestTierDetection:
    def test_tier_detection_advanced(self):
        """3+ advanced channels -> 'advanced' tier."""
        cols = {"Speed (m/s)", "Steering", "Brake", "Throttle"}
        assert get_coaching_tier(cols) == "advanced"

    def test_tier_detection_basic(self):
        """<3 advanced channels -> 'basic' tier."""
        cols = {"Speed (m/s)", "Latitude", "Longitude"}
        assert get_coaching_tier(cols) == "basic"

    def test_tier_detection_exactly_three(self):
        """Exactly 3 advanced channels -> 'advanced' tier."""
        cols = {"Speed (m/s)", "Steering", "Brake", "RPM"}
        assert get_coaching_tier(cols) == "advanced"

    def test_tier_detection_two_advanced(self):
        """Only 2 advanced channels -> 'basic' tier."""
        cols = {"Speed (m/s)", "Steering", "Brake"}
        assert get_coaching_tier(cols) == "basic"

    def test_tier_detection_all_advanced(self):
        """All 5 advanced channels -> 'advanced' tier."""
        cols = {"Speed (m/s)", "Steering", "Brake", "Throttle", "RPM", "Gear"}
        assert get_coaching_tier(cols) == "advanced"


# ---------------------------------------------------------------------------
# Advanced coaching tests
# ---------------------------------------------------------------------------

class TestAdvancedCoaching:
    def test_includes_basic_coaching(self):
        """Advanced coaching includes all basic coaching fields."""
        sec = _make_corner_section()
        events = {1: _make_events()}
        handling = {1: _make_handling()}
        df = _make_lap_df(include_throttle=True, include_steering=True,
                          include_rpm_gear=True)

        results = generate_advanced_coaching(
            sections=[sec], events=events, handling=handling, lap_df=df,
        )
        assert len(results) == 1
        sc = results[0]
        assert isinstance(sc, SectionCoaching)
        # Basic fields must be present
        assert sc.section is sec
        assert sc.time_loss_total_s >= 0.0
        assert isinstance(sc.coaching_hints, list)
        assert len(sc.coaching_hints) > 0
        assert sc.primary_focus != ""

    def test_handling_summary_populated(self):
        """When handling events exist, handling_summary is populated."""
        sec = _make_corner_section()
        events = {1: _make_events()}
        handling = {1: _make_handling()}
        df = _make_lap_df(include_throttle=True)

        results = generate_advanced_coaching(
            sections=[sec], events=events, handling=handling, lap_df=df,
        )
        sc = results[0]
        assert sc.handling_summary is not None
        assert "understeer" in sc.handling_summary.lower()
        assert "oversteer" in sc.handling_summary.lower()

    def test_throttle_advice_when_available(self):
        """When Throttle column exists, throttle_advice is populated."""
        sec = _make_corner_section()
        events = {1: _make_events()}
        handling = {1: []}
        df = _make_lap_df(include_throttle=True)

        results = generate_advanced_coaching(
            sections=[sec], events=events, handling=handling, lap_df=df,
        )
        sc = results[0]
        assert sc.throttle_advice is not None
        assert len(sc.throttle_advice) > 0

    def test_steering_advice_when_available(self):
        """When Steering column exists, steering_advice is populated."""
        sec = _make_corner_section()
        events = {1: _make_events()}
        handling = {1: []}
        df = _make_lap_df(include_steering=True)

        results = generate_advanced_coaching(
            sections=[sec], events=events, handling=handling, lap_df=df,
        )
        sc = results[0]
        assert sc.steering_advice is not None
        assert len(sc.steering_advice) > 0

    def test_gear_advice_when_available(self):
        """When RPM and Gear columns exist, gear_advice is populated."""
        sec = _make_corner_section()
        events = {1: _make_events()}
        handling = {1: []}
        df = _make_lap_df(include_rpm_gear=True)

        results = generate_advanced_coaching(
            sections=[sec], events=events, handling=handling, lap_df=df,
        )
        sc = results[0]
        assert sc.gear_advice is not None
        assert len(sc.gear_advice) > 0

    def test_graceful_degradation(self):
        """Only some advanced channels -> partial advice (no crash)."""
        sec = _make_corner_section()
        events = {1: _make_events()}
        handling = {1: []}
        # Only throttle, no steering/rpm/gear
        df = _make_lap_df(include_throttle=True)

        results = generate_advanced_coaching(
            sections=[sec], events=events, handling=handling, lap_df=df,
        )
        sc = results[0]
        assert sc.throttle_advice is not None
        assert sc.steering_advice is None
        assert sc.gear_advice is None

    def test_advanced_adds_hints(self):
        """Advanced engine appends extra hints beyond basic."""
        sec = _make_corner_section()
        events = {1: _make_events()}
        handling = {1: _make_handling()}
        df = _make_lap_df(include_throttle=True, include_steering=True,
                          include_rpm_gear=True)

        from coaching_basic import generate_basic_coaching
        basic_results = generate_basic_coaching(
            sections=[sec], events=events, handling=handling, lap_df=df,
        )
        advanced_results = generate_advanced_coaching(
            sections=[sec], events=events, handling=handling, lap_df=df,
        )

        basic_hints = len(basic_results[0].coaching_hints)
        advanced_hints = len(advanced_results[0].coaching_hints)
        assert advanced_hints > basic_hints

    def test_straight_section_no_advanced(self):
        """Straight sections don't get advanced corner advice."""
        sec = _make_straight_section()
        events = {}
        handling = {}
        df = _make_lap_df(include_throttle=True, include_steering=True,
                          include_rpm_gear=True)

        results = generate_advanced_coaching(
            sections=[sec], events=events, handling=handling, lap_df=df,
        )
        sc = results[0]
        # Straights should not get corner-specific advanced advice
        assert sc.throttle_advice is None
        assert sc.steering_advice is None
        assert sc.gear_advice is None

    def test_empty_sections(self):
        """Empty section list returns empty results."""
        results = generate_advanced_coaching(
            sections=[], events={}, handling={}, lap_df=pd.DataFrame(),
        )
        assert results == []
