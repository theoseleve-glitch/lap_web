"""Tests for wet_model.py and pre_session.py — pre-session coach."""
from __future__ import annotations

import numpy as np
import pytest

from track_surface.frenet import FrenetFrame
from track_surface.grip_2d import GripSurface
from track_surface.model import TrackSurface
from track_surface.pre_session import generate_pre_session_briefing
from track_surface.wet_model import (
    CompressionWarning,
    WetLineShift,
    compute_wet_line_shifts,
    find_compression_warnings,
    invert_grip_for_wet,
)


def _make_straight_frame(length: float = 200.0, n: int = 400) -> FrenetFrame:
    xy = np.column_stack([np.linspace(0, length, n), np.zeros(n)])
    return FrenetFrame.from_centerline(xy)


def _make_grip_with_rubber_line() -> GripSurface:
    """Create a grip surface where n=0 (center) has high mu (rubber line)
    and n=±3 has low mu (off-line)."""
    s_bins = np.arange(0, 200, 5.0)
    n_bins = np.array([-4, -3, -2, -1, 0, 1, 2, 3, 4.0])
    M, K = len(s_bins), len(n_bins)

    # Rubber line at n=0: mu=1.4, off-line: mu=0.9
    mu = np.full((M, K), 0.9)
    for i in range(M):
        mu[i, 3] = 1.2   # n=-1
        mu[i, 4] = 1.4   # n=0 (center = racing line)
        mu[i, 5] = 1.2   # n=+1

    count = np.full((M, K), 20, dtype=int)
    count[:, 4] = 100  # center heavily sampled (racing line)

    return GripSurface(
        s_bins=s_bins,
        n_bins=n_bins,
        mu_grid=mu,
        count_grid=count,
        confidence=np.clip(count / 50.0, 0, 1),
    )


def _make_surface_with_grip() -> TrackSurface:
    ff = _make_straight_frame()
    grip = _make_grip_with_rubber_line()
    n = ff.n_points
    return TrackSurface(
        track_id="test_track",
        frenet=ff,
        width_left=np.full(n, 5.0),
        width_right=np.full(n, 5.0),
        elevation_m=np.zeros(n),
        vert_curvature_1pm=np.zeros(n),
        grip_2d=grip,
        n_laps=20,
        sim_sources=["ac"],
    )


class TestGripInversion:
    def test_rubber_line_gets_lower_wet_grip(self):
        grip = _make_grip_with_rubber_line()
        wet = invert_grip_for_wet(grip)

        # Center (rubber line) should have LOWER wet grip than off-line
        center_idx = 4  # n=0
        offline_idx = 0  # n=-4
        # Average across all s-bins
        center_wet = np.mean(wet[:, center_idx])
        offline_wet = np.mean(wet[:, offline_idx])
        assert offline_wet > center_wet, "Off-line should have better wet grip"

    def test_wet_grip_stays_positive(self):
        grip = _make_grip_with_rubber_line()
        wet = invert_grip_for_wet(grip)
        assert np.all(wet >= 0.2)

    def test_uniform_grip_gives_uniform_wet(self):
        """If dry grip is uniform, wet grip should also be relatively uniform."""
        s = np.arange(0, 100, 5.0)
        n = np.array([-2, 0, 2.0])
        mu = np.ones((len(s), len(n))) * 1.0
        count = np.full((len(s), len(n)), 30, dtype=int)
        grip = GripSurface(s, n, mu, count, np.ones_like(mu))

        wet = invert_grip_for_wet(grip)
        # Should be relatively uniform
        assert np.std(wet) < 0.1


class TestWetLineShifts:
    def test_shifts_away_from_rubber(self):
        surface = _make_surface_with_grip()
        corners = [
            {"corner_id": 1, "s_start": 40, "s_end": 80, "s_apex": 60, "direction": "R"},
            {"corner_id": 2, "s_start": 120, "s_end": 160, "s_apex": 140, "direction": "L"},
        ]
        shifts = compute_wet_line_shifts(surface, corners)
        assert len(shifts) == 2
        # Wet apex should be offset from center (rubber line)
        for shift in shifts:
            assert shift.shift_m > 0 or shift.shift_direction == "none"

    def test_no_shifts_without_grip(self):
        ff = _make_straight_frame()
        surface = TrackSurface(track_id="t", frenet=ff, n_laps=1, sim_sources=["ac"])
        corners = [{"corner_id": 1, "s_start": 40, "s_end": 80, "s_apex": 60}]
        shifts = compute_wet_line_shifts(surface, corners)
        assert len(shifts) == 0

    def test_shift_to_dict(self):
        shift = WetLineShift(
            corner_id=1, s_start=40, s_end=80, s_apex=60,
            dry_apex_n=0.0, wet_apex_n=2.0, shift_m=2.0,
            shift_direction="outside", rubber_severity=0.7,
        )
        d = shift.to_dict()
        assert d["corner_id"] == 1
        assert d["shift_m"] == 2.0


class TestCompressionWarnings:
    def test_finds_compression_zones(self):
        ff = _make_straight_frame()
        n = ff.n_points
        # Create a compression at s=100
        kv = np.zeros(n)
        idx_100 = np.argmin(np.abs(ff.s_grid - 100))
        kv[idx_100] = 0.01  # strong compression

        surface = TrackSurface(
            track_id="t", frenet=ff,
            vert_curvature_1pm=kv,
            n_laps=5, sim_sources=["ac"],
        )
        warnings = find_compression_warnings(surface)
        assert len(warnings) >= 1
        assert warnings[0].vert_curvature > 0
        assert "pool" in warnings[0].wet_warning.lower() or "brake" in warnings[0].wet_warning.lower()

    def test_no_warnings_on_flat(self):
        ff = _make_straight_frame()
        surface = TrackSurface(
            track_id="t", frenet=ff,
            vert_curvature_1pm=np.zeros(ff.n_points),
            n_laps=5, sim_sources=["ac"],
        )
        warnings = find_compression_warnings(surface)
        assert len(warnings) == 0


class TestPreSessionBriefing:
    def test_dry_briefing_basic(self):
        surface = _make_surface_with_grip()
        briefing = generate_pre_session_briefing(surface, "dry")
        d = briefing.to_dict()
        assert d["condition"] == "dry"
        assert d["track_briefing"]["model_quality"] == "gold"
        assert len(d["condition_alerts"]) == 0  # no wet alerts in dry
        assert len(d["wet_line_shifts"]) == 0    # no wet shifts in dry

    def test_wet_briefing_has_alerts(self):
        surface = _make_surface_with_grip()
        corners = [
            {"corner_id": 1, "s_start": 40, "s_end": 80, "s_apex": 60, "direction": "R"},
        ]
        briefing = generate_pre_session_briefing(surface, "wet", corners=corners)
        d = briefing.to_dict()
        assert d["condition"] == "wet"
        # Should have rubber-line alert
        alert_types = [a["type"] for a in d["condition_alerts"]]
        assert "wet_rubber_line" in alert_types

    def test_wet_line_shifts_present(self):
        surface = _make_surface_with_grip()
        corners = [
            {"corner_id": 1, "s_start": 40, "s_end": 80, "s_apex": 60, "direction": "R"},
        ]
        briefing = generate_pre_session_briefing(surface, "wet", corners=corners)
        d = briefing.to_dict()
        assert len(d["wet_line_shifts"]) > 0

    def test_reference_pace_with_dry_time(self):
        surface = _make_surface_with_grip()
        briefing = generate_pre_session_briefing(
            surface, "wet", best_dry_lap_s=120.0,
        )
        d = briefing.to_dict()
        assert d["reference_pace"]["best_dry_lap_s"] == 120.0
        assert d["reference_pace"]["estimated_target_s"] == pytest.approx(129.6, abs=0.1)
        assert d["reference_pace"]["condition_factor"] == 1.08

    def test_driver_focus_from_history(self):
        surface = _make_surface_with_grip()
        history = [
            {"corner_id": 3, "time_loss_s": 0.8, "cause": "line", "apex_error_m": -1.5},
            {"corner_id": 7, "time_loss_s": 0.3, "cause": "speed", "apex_error_m": 0.0},
        ]
        briefing = generate_pre_session_briefing(surface, "dry", driver_history=history)
        d = briefing.to_dict()
        assert len(d["driver_focus"]) == 2
        # Sorted by loss: corner 3 first
        assert d["driver_focus"][0]["corner_id"] == 3

    def test_damp_has_mixed_conditions_alert(self):
        surface = _make_surface_with_grip()
        briefing = generate_pre_session_briefing(surface, "damp")
        d = briefing.to_dict()
        alert_types = [a["type"] for a in d["condition_alerts"]]
        assert "mixed_conditions" in alert_types

    def test_wet_briefing_with_puddle_zones(self):
        """Wet briefing should include puddle warnings when 3D elevation available."""
        from track_surface.elevation import ElevationSurface

        surface = _make_surface_with_grip()
        # Add a 3D elevation surface with a dip
        M, K = 20, 10
        s_bins = np.arange(0, 200, 10.0)[:M]
        n_bins = np.linspace(-5, 5, K)
        z_grid = np.zeros((M, K))
        z_grid[10, 5] = -0.5  # dip at center
        surface.elevation_surface = ElevationSurface(
            s_bins=s_bins, n_bins=n_bins, z_grid=z_grid,
            kv_grid=np.zeros((M, K)), count_grid=np.ones((M, K), dtype=int) * 10,
            confidence=np.ones((M, K)),
        )

        briefing = generate_pre_session_briefing(surface, "wet")
        d = briefing.to_dict()
        alert_types = [a["type"] for a in d["condition_alerts"]]
        assert "puddle_zones" in alert_types

    def test_to_dict_structure(self):
        surface = _make_surface_with_grip()
        briefing = generate_pre_session_briefing(surface, "dry", track_name="Spa GP")
        d = briefing.to_dict()
        assert "track_briefing" in d
        assert d["track_briefing"]["track_name"] == "Spa GP"
        assert "condition_alerts" in d
        assert "wet_line_shifts" in d
        assert "driver_focus" in d
        assert "reference_pace" in d


class TestEnrichCoachingWithBumps:
    def test_enrich_coaching_with_bumps(self):
        from track_surface.coaching import enrich_coaching_with_bumps
        from track_surface.bump_detection import SurfaceBump

        coaching = [{"corner_id": 1, "coaching": "Move apex 1m later."}]
        bumps = [SurfaceBump(s_position=75.0, n_estimated=0.0, severity=0.6, bump_type="bump", affected_wheels=["fl", "fr"])]
        corners = [{"corner_id": 1, "s_start": 50, "s_end": 100}]

        result = enrich_coaching_with_bumps(coaching, bumps, corners)
        assert result[0].get("has_bump_warning") is True
        assert "bump" in result[0]["coaching"].lower()

    def test_no_bumps_no_warning(self):
        from track_surface.coaching import enrich_coaching_with_bumps

        coaching = [{"corner_id": 1, "coaching": "Move apex 1m later."}]
        corners = [{"corner_id": 1, "s_start": 50, "s_end": 100}]

        result = enrich_coaching_with_bumps(coaching, [], corners)
        assert result[0].get("has_bump_warning") is None

    def test_bump_outside_corner_ignored(self):
        from track_surface.coaching import enrich_coaching_with_bumps
        from track_surface.bump_detection import SurfaceBump

        coaching = [{"corner_id": 1, "coaching": "Move apex 1m later."}]
        bumps = [SurfaceBump(s_position=200.0, n_estimated=0.0, severity=0.8, bump_type="bump", affected_wheels=["fl"])]
        corners = [{"corner_id": 1, "s_start": 50, "s_end": 100}]

        result = enrich_coaching_with_bumps(coaching, bumps, corners)
        assert result[0].get("has_bump_warning") is None
