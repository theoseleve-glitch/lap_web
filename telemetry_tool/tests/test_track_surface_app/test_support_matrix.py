"""Tests for SupportMatrix — static (sim, vehicle, track) lookup."""
from __future__ import annotations

import json

import pytest

from track_surface_app.domain import SupportTier
from track_surface_app.support_matrix import SupportMatrix, SupportMatrixEntry


@pytest.fixture
def tmp_matrix(tmp_path):
    data = {
        "version": 1,
        "entries": [
            {
                "sim": "iracing",
                "vehicle": "mx5",
                "track": "daytona_rc",
                "max_support_tier": "A",
                "validated_vehicle_profile": "iracing_mx5_2024",
                "validated_track_profile": "daytona_rc_v5",
            },
            {
                "sim": "iracing",
                "vehicle": "mx5",
                "track": "spa",
                "max_support_tier": "B",
                "validated_vehicle_profile": "iracing_mx5_2024",
                "validated_track_profile": "spa_v3",
            },
        ],
    }
    p = tmp_path / "matrix.json"
    p.write_text(json.dumps(data))
    return p


class TestLoad:
    def test_load_valid(self, tmp_matrix):
        mx = SupportMatrix.load(tmp_matrix)
        assert len(mx.entries) == 2

    def test_missing_file_returns_empty(self, tmp_path):
        mx = SupportMatrix.load(tmp_path / "nonexistent.json")
        assert mx.entries == []


class TestResolve:
    def test_known_combo_returns_entry(self, tmp_matrix):
        mx = SupportMatrix.load(tmp_matrix)
        entry = mx.resolve(sim="iracing", vehicle="mx5", track="daytona_rc")
        assert entry is not None
        assert entry.max_support_tier is SupportTier.A
        assert entry.validated_vehicle_profile == "iracing_mx5_2024"

    def test_unknown_combo_returns_none(self, tmp_matrix):
        mx = SupportMatrix.load(tmp_matrix)
        assert mx.resolve(sim="ac", vehicle="gt3", track="nordschleife") is None

    def test_case_insensitive(self, tmp_matrix):
        mx = SupportMatrix.load(tmp_matrix)
        entry = mx.resolve(sim="IRACING", vehicle="MX5", track="daytona_rc")
        assert entry is not None
