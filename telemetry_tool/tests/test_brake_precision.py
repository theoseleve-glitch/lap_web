"""Test brake precision module."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from brake_precision import compute_brake_precision, compute_overall_brake_score


class TestBrakePrecision:
    def test_consistent_high_score(self):
        metrics = {
            1: [{"corner_id": 1, "brake_point_m": 50.0}],
            2: [{"corner_id": 1, "brake_point_m": 50.1}],
            3: [{"corner_id": 1, "brake_point_m": 49.9}],
        }
        result = compute_brake_precision(metrics)
        assert result[0]["precision_score"] > 90

    def test_variable_low_score(self):
        metrics = {
            1: [{"corner_id": 1, "brake_point_m": 50.0}],
            2: [{"corner_id": 1, "brake_point_m": 60.0}],
            3: [{"corner_id": 1, "brake_point_m": 40.0}],
        }
        result = compute_brake_precision(metrics)
        assert result[0]["precision_score"] < 50

    def test_empty(self):
        result = compute_brake_precision({})
        assert result == []

    def test_overall_score(self):
        per_corner = [
            {"corner_id": 1, "precision_score": 90, "n_samples": 5},
            {"corner_id": 2, "precision_score": 70, "n_samples": 5},
        ]
        score = compute_overall_brake_score(per_corner)
        assert 70 < score < 90
