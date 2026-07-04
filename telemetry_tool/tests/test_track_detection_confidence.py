"""Tests for the low-lap-count confidence tier on TrackFingerprint.

Distinct from track_surface/track_matcher.py's same-named
compute_track_fingerprint -- this covers telemetry_tool/track_detection.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from track_detection import BoundingBox, TrackFingerprint, compute_track_fingerprint


def _make_df(n_laps: int, n_points_per_lap: int = 20) -> pd.DataFrame:
    rows = []
    for lap in range(1, n_laps + 1):
        for i in range(n_points_per_lap):
            rows.append({
                "Lap #": lap,
                "Time (s)": (lap - 1) * 30.0 + i * 1.5,
                "Distance (m)": i * 25.0,
                "Latitude (deg)": 45.0 + 0.0001 * i,
                "Longitude (deg)": 7.0 + 0.0001 * i,
            })
    return pd.DataFrame(rows)


def _bbox() -> BoundingBox:
    return BoundingBox(lat_min=45.0, lat_max=45.1, lon_min=7.0, lon_max=7.1)


class TestTrackFingerprintConfidence:
    def test_defaults_to_high_confidence(self):
        fp = TrackFingerprint(
            lap_length_m=1000.0, bbox=None, start_lat=45.0, start_lon=7.0,
            sample_count=500, lap_count=10,
        )
        assert fp.confidence == "high"

    def test_included_in_to_dict(self):
        # to_dict() serializes bbox via bbox.to_dict(), so this needs a real
        # BoundingBox (the plan's bbox=None would crash before reaching the
        # confidence assertion).
        fp = TrackFingerprint(
            lap_length_m=1000.0, bbox=_bbox(), start_lat=45.0, start_lon=7.0,
            sample_count=500, lap_count=10,
        )
        assert fp.to_dict()["confidence"] == "high"


class TestComputeTrackFingerprintConfidence:
    def test_low_lap_count_yields_low_confidence(self):
        df = _make_df(n_laps=1)
        fp = compute_track_fingerprint(df)
        assert fp.lap_count == 1
        assert fp.confidence == "low"

    def test_sufficient_lap_count_yields_high_confidence(self):
        df = _make_df(n_laps=5)
        fp = compute_track_fingerprint(df)
        assert fp.lap_count >= 3
        assert fp.confidence == "high"

    def test_confidence_present_in_serialized_output(self):
        df = _make_df(n_laps=1)
        fp = compute_track_fingerprint(df)
        assert fp.to_dict()["confidence"] == "low"
