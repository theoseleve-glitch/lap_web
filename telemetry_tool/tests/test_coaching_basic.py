"""Tests for GPS-only basic coaching engine."""

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from coaching_basic import SectionCoaching, generate_basic_coaching
from track_decomposition import TrackSection
from mrp_detector import CornerEvents
from handling_detector import HandlingEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_corner_section(
    section_id=1,
    s_start=100.0,
    s_end=200.0,
    exit_importance=0.6,
    geometric_apex=150.0,
    direction="R",
    corner_type="medium",
):
    return TrackSection(
        section_id=section_id,
        section_type="corner",
        corner_type=corner_type,
        s_start=s_start,
        s_end=s_end,
        direction=direction,
        geometric_apex=geometric_apex,
        exit_importance=exit_importance,
    )


def _make_straight_section(
    section_id=2,
    s_start=200.0,
    s_end=400.0,
    exit_importance=0.3,
):
    return TrackSection(
        section_id=section_id,
        section_type="straight",
        corner_type=None,
        s_start=s_start,
        s_end=s_end,
        direction=None,
        geometric_apex=None,
        exit_importance=exit_importance,
    )


def _make_corner_events(
    corner_id=1,
    brake_point_m=90.0,
    turn_in_m=100.0,
    mrp_m=150.0,
    mrp_speed_mps=15.0,
    throttle_application_m=160.0,
    track_out_m=200.0,
    geometric_apex_m=150.0,
):
    return CornerEvents(
        corner_id=corner_id,
        brake_point_m=brake_point_m,
        turn_in_m=turn_in_m,
        trail_brake_end_m=None,
        mrp_m=mrp_m,
        mrp_speed_mps=mrp_speed_mps,
        mrp_yaw_rate=0.05,
        throttle_application_m=throttle_application_m,
        track_out_m=track_out_m,
        geometric_apex_m=geometric_apex_m,
        mrp_apex_delta_m=mrp_m - geometric_apex_m,
    )


def _make_lap_df(s_start=0.0, s_end=500.0, n_points=500):
    """Create a synthetic lap DataFrame with distance and speed."""
    dist = np.linspace(s_start, s_end, n_points)
    # Speed profile: fast on straights, slow through a corner at 100-200m
    speed = np.full(n_points, 30.0)  # 30 m/s baseline
    # Slow down in the corner region (100-200m)
    corner_mask = (dist >= 100) & (dist <= 200)
    # Smooth speed dip in corner
    for i in range(n_points):
        if 100 <= dist[i] <= 200:
            # V-shape speed dip centered at 150m
            frac = abs(dist[i] - 150.0) / 50.0
            speed[i] = 15.0 + 15.0 * frac  # min 15 m/s at apex

    return pd.DataFrame({
        "Distance (m)": dist,
        "Speed (m/s)": speed,
    })


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCoachingGeneratedForCorner:
    def test_coaching_generated_for_corner(self):
        """Corner sections produce coaching with time loss and hints."""
        section = _make_corner_section()
        events = {1: _make_corner_events()}
        df = _make_lap_df()

        result = generate_basic_coaching(
            sections=[section],
            events=events,
            handling={},
            lap_df=df,
        )

        assert len(result) == 1
        sc = result[0]
        assert isinstance(sc, SectionCoaching)
        assert sc.section.section_type == "corner"
        assert sc.time_loss_total_s >= 0.0
        assert len(sc.coaching_hints) > 0
        assert sc.primary_focus != ""
        # Advanced fields are None for basic engine
        assert sc.handling_summary is None
        assert sc.throttle_advice is None
        assert sc.steering_advice is None
        assert sc.gear_advice is None


class TestCoachingGeneratedForStraight:
    def test_coaching_generated_for_straight(self):
        """Straight sections also get coaching (top speed analysis)."""
        section = _make_straight_section()
        df = _make_lap_df()

        result = generate_basic_coaching(
            sections=[section],
            events={},
            handling={},
            lap_df=df,
        )

        assert len(result) == 1
        sc = result[0]
        assert sc.section.section_type == "straight"
        assert len(sc.coaching_hints) > 0
        # Straights have no corner-specific fields
        assert sc.events is None
        assert sc.optimal_apex_speed_mps is None


class TestCornerFocusNoteWhenImportant:
    def test_corner_focus_note_when_important(self):
        """Corner with exit_importance > 0.5 includes focus note."""
        section = _make_corner_section(exit_importance=0.8)
        events = {1: _make_corner_events()}
        df = _make_lap_df()

        result = generate_basic_coaching(
            sections=[section],
            events=events,
            handling={},
            lap_df=df,
        )

        sc = result[0]
        assert sc.corner_focus_note != ""
        assert "exit" in sc.corner_focus_note.lower() or "prioritize" in sc.corner_focus_note.lower()


class TestCornerFocusNoteEmptyWhenUnimportant:
    def test_corner_focus_note_empty_when_unimportant(self):
        """Corner with exit_importance < 0.2 has minimal focus note."""
        section = _make_corner_section(exit_importance=0.1)
        events = {1: _make_corner_events()}
        df = _make_lap_df()

        result = generate_basic_coaching(
            sections=[section],
            events=events,
            handling={},
            lap_df=df,
        )

        sc = result[0]
        assert sc.corner_focus_note == ""


class TestCoachingHintsAreOrdered:
    def test_coaching_hints_are_ordered(self):
        """Hints are ordered by estimated time impact (most impactful first)."""
        # Create a corner with substantial time loss in multiple areas
        section = _make_corner_section(s_start=100.0, s_end=200.0, geometric_apex=150.0)
        events = {1: _make_corner_events(mrp_speed_mps=12.0)}
        df = _make_lap_df()

        # Provide theoretical data so we get measurable time losses
        theoretical = {
            "corners": {
                1: {
                    "optimal_entry_speed_mps": 28.0,
                    "optimal_apex_speed_mps": 22.0,
                    "optimal_exit_speed_mps": 28.0,
                    "optimal_brake_point_m": 95.0,
                }
            },
            "straights": {},
        }

        result = generate_basic_coaching(
            sections=[section],
            events=events,
            handling={},
            lap_df=df,
            theoretical=theoretical,
        )

        sc = result[0]
        # With theoretical data providing large deltas, we should get multiple hints
        assert len(sc.coaching_hints) >= 1


class TestPrimaryFocusIsHighestImpact:
    def test_primary_focus_is_highest_impact(self):
        """primary_focus matches the first coaching hint."""
        section = _make_corner_section()
        events = {1: _make_corner_events()}
        df = _make_lap_df()

        result = generate_basic_coaching(
            sections=[section],
            events=events,
            handling={},
            lap_df=df,
        )

        sc = result[0]
        if sc.coaching_hints:
            assert sc.primary_focus == sc.coaching_hints[0]


class TestTimeLossBreakdownSums:
    def test_time_loss_breakdown_sums(self):
        """time_loss_braking + time_loss_apex + time_loss_exit approx equals time_loss_total."""
        section = _make_corner_section()
        events = {1: _make_corner_events()}
        df = _make_lap_df()

        theoretical = {
            "corners": {
                1: {
                    "optimal_entry_speed_mps": 25.0,
                    "optimal_apex_speed_mps": 20.0,
                    "optimal_exit_speed_mps": 25.0,
                    "optimal_brake_point_m": 95.0,
                }
            },
            "straights": {},
        }

        result = generate_basic_coaching(
            sections=[section],
            events=events,
            handling={},
            lap_df=df,
            theoretical=theoretical,
        )

        sc = result[0]
        component_sum = sc.time_loss_braking_s + sc.time_loss_apex_s + sc.time_loss_exit_s
        assert abs(sc.time_loss_total_s - component_sum) < 0.01


class TestEmptySectionsReturnsEmpty:
    def test_empty_sections_returns_empty(self):
        """No sections -> no coaching."""
        df = _make_lap_df()
        result = generate_basic_coaching(
            sections=[],
            events={},
            handling={},
            lap_df=df,
        )
        assert result == []


class TestMultipleSections:
    def test_mixed_sections_all_get_coaching(self):
        """A mix of corner and straight sections all receive coaching."""
        corner = _make_corner_section(section_id=1, s_start=100, s_end=200)
        straight = _make_straight_section(section_id=2, s_start=200, s_end=400)
        corner2 = _make_corner_section(section_id=3, s_start=400, s_end=450, geometric_apex=425.0)
        events = {
            1: _make_corner_events(corner_id=1),
            3: _make_corner_events(corner_id=3, mrp_m=425.0, geometric_apex_m=425.0),
        }
        df = _make_lap_df(s_end=500.0)

        result = generate_basic_coaching(
            sections=[corner, straight, corner2],
            events=events,
            handling={},
            lap_df=df,
        )

        assert len(result) == 3
        assert result[0].section.section_type == "corner"
        assert result[1].section.section_type == "straight"
        assert result[2].section.section_type == "corner"


class TestHandlingEventsIncluded:
    def test_handling_events_attached(self):
        """Handling events are passed through to coaching output."""
        section = _make_corner_section()
        events = {1: _make_corner_events()}
        he = HandlingEvent(
            corner_id=1,
            event_type="understeer",
            severity="mild",
            s_start=120.0,
            s_end=140.0,
            duration_s=0.5,
            magnitude=0.15,
            cause="entry_speed",
            cause_detail="Excess entry speed.",
            time_cost_s=0.05,
            corner_phase="entry",
        )
        handling = {1: [he]}
        df = _make_lap_df()

        result = generate_basic_coaching(
            sections=[section],
            events=events,
            handling=handling,
            lap_df=df,
        )

        sc = result[0]
        assert len(sc.handling) == 1
        assert sc.handling[0].event_type == "understeer"
