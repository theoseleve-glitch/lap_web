"""Test trend analysis module."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from trend_analysis import compute_multi_session_trend, detect_plateau


class TestTrendAnalysis:
    def test_improving_trend(self):
        sessions = [
            {"session_date": f"2024-01-{i+1:02d}", "best_lap_time_s": 65 - i * 0.5}
            for i in range(10)
        ]
        result = compute_multi_session_trend(sessions, degree=1, n_bootstrap=10)
        assert result["improvement_rate"] > 0

    def test_plateau(self):
        values = [60.0, 60.1, 59.9, 60.0, 60.05, 59.95, 60.0, 60.1, 59.9, 60.0]
        result = detect_plateau(values, window=5, threshold_pct=0.5)
        assert result["is_plateau"] is True

    def test_empty(self):
        result = compute_multi_session_trend([], n_bootstrap=0)
        assert result["sessions_count"] == 0
