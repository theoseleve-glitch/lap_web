"""Tests for coaching / delta analysis / corner attribution."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from kart_envelope.coaching.cause_ranking import generate_coaching_text, rank_time_loss_causes
from kart_envelope.coaching.corner_coaching import (
    CornerPerformance,
    analyze_corner_performance,
    detect_corners_from_curvature,
)
from kart_envelope.coaching.delta_analysis import compute_delta_map, segment_summary
from kart_envelope.inference.session_scalars import SessionScalars
from kart_envelope.solver.min_time import TheoreticalResult


def _make_theoretical(n: int = 500) -> TheoreticalResult:
    dist = np.linspace(0, 500, n)
    speed = np.full(n, 15.0)
    return TheoreticalResult(
        speed_profile_mps=speed,
        distance_m=dist,
        accel_profile_mps2=np.zeros(n),
        lap_time_s=500.0 / 15.0,
        cornering_limited=np.zeros(n, dtype=bool),
        accel_limited=np.zeros(n, dtype=bool),
        braking_limited=np.zeros(n, dtype=bool),
    )


def _make_driver_lap(n: int = 500) -> pd.DataFrame:
    dist = np.linspace(0, 500, n)
    speed = np.full(n, 13.0)  # slower than theoretical
    return pd.DataFrame({
        "distance_m": dist,
        "speed_mps": speed,
        "time_s": np.cumsum(np.full(n, 1.0 / 13.0)),
        "accel_long_mps2": np.zeros(n),
        "accel_lat_mps2": np.zeros(n),
    })


class TestDeltaMap:
    def test_positive_delta(self):
        """Slower driver should produce positive delta."""
        th = _make_theoretical()
        dr = _make_driver_lap()
        dm = compute_delta_map(dr, th)
        assert not dm.empty
        # Total delta should be positive (driver slower)
        total = float(dm["cumulative_delta_s"].iloc[-1])
        assert total > 0

    def test_segment_summary(self):
        th = _make_theoretical()
        dr = _make_driver_lap()
        dm = compute_delta_map(dr, th, n_segments=5)
        ss = segment_summary(dm, n_segments=5)
        assert len(ss) > 0
        assert "time_loss_ms" in ss.columns


class TestCornerDetection:
    def test_detect_from_curvature(self):
        n = 500
        dist = np.linspace(0, 500, n)
        kappa = np.zeros(n)
        kappa[100:150] = 0.03
        kappa[300:350] = 0.05

        corners = detect_corners_from_curvature(kappa, dist, threshold=0.01)
        assert len(corners) == 2
        assert corners[0]["corner_id"] == 1
        assert corners[1]["corner_id"] == 2

    def test_no_corners_on_straight(self):
        n = 500
        dist = np.linspace(0, 500, n)
        kappa = np.zeros(n)
        corners = detect_corners_from_curvature(kappa, dist, threshold=0.01)
        assert len(corners) == 0


class TestCauseRanking:
    def test_ranking_order(self):
        perfs = [
            CornerPerformance(corner_id=1, s_start=0, s_end=50, s_apex=25,
                               direction="L", time_loss_total_s=0.1,
                               primary_cause="low_apex_speed",
                               coaching_hint="carry more speed"),
            CornerPerformance(corner_id=2, s_start=100, s_end=150, s_apex=125,
                               direction="R", time_loss_total_s=0.3,
                               primary_cause="early_braking",
                               coaching_hint="brake later"),
        ]
        causes = rank_time_loss_causes(perfs, top_n=5)
        assert len(causes) == 2
        assert causes[0].corner_id == 2  # biggest loss first

    def test_coaching_text(self):
        perfs = [
            CornerPerformance(corner_id=1, s_start=0, s_end=50, s_apex=25,
                               direction="L", time_loss_total_s=0.2,
                               primary_cause="slow_exit",
                               coaching_hint="throttle earlier"),
        ]
        causes = rank_time_loss_causes(perfs)
        scalars = SessionScalars(mu_session=0.9, p_session=1.0,
                                  condition_label="dry")
        text = generate_coaching_text(causes, scalars)
        assert len(text) > 0
        assert "Corner 1" in text
