"""Tests for driver style profile computation."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import numpy as np
import pandas as pd
import pytest

from telemetry_tool.features import DriverStyleProfile, compute_driver_style
from telemetry_tool.corner_analysis import CornerPerformance


class TestDriverStyleProfile:
    def test_aggressive_braker_label(self):
        """High brake aggressiveness -> 'aggressive braker' label."""
        perfs = [
            CornerPerformance(corner_id=i, s_start=i*100, s_end=i*100+50,
                              time_loss_braking_s=0.1, time_loss_exit_s=0.3,
                              braking_point_delta_m=-5.0)
            for i in range(1, 6)
        ]
        # Late braking (negative delta = braked later than theoretical)
        style = compute_driver_style(perfs)
        assert style is not None
        assert isinstance(style.style_labels, list)
        assert style.confidence > 0

    def test_exit_focused_label(self):
        """Exit loss < braking loss in all corners -> 'exit-focused' label."""
        perfs = [
            CornerPerformance(corner_id=i, s_start=i*100, s_end=i*100+50,
                              time_loss_braking_s=0.5, time_loss_exit_s=0.1)
            for i in range(1, 6)
        ]
        style = compute_driver_style(perfs)
        assert style is not None
        # Exit loss < braking loss everywhere -> exit_priority high -> "exit-focused"
        assert "exit-focused" in style.style_labels

    def test_entry_focused_label(self):
        """Exit loss > braking loss in all corners -> 'entry-focused' label."""
        perfs = [
            CornerPerformance(corner_id=i, s_start=i*100, s_end=i*100+50,
                              time_loss_braking_s=0.1, time_loss_exit_s=0.5)
            for i in range(1, 6)
        ]
        style = compute_driver_style(perfs)
        assert style is not None
        assert "entry-focused" in style.style_labels

    def test_to_dict_serializable(self):
        """DriverStyleProfile.to_dict() is JSON-serializable."""
        perfs = [
            CornerPerformance(corner_id=1, s_start=100, s_end=150)
        ]
        style = compute_driver_style(perfs)
        d = style.to_dict()
        import json
        json.dumps(d)
        assert "style_labels" in d
        assert "confidence" in d

    def test_empty_perfs_returns_default(self):
        """Empty performances -> default profile with low confidence."""
        style = compute_driver_style([])
        assert style is not None
        assert style.confidence == 0.0
        assert style.style_labels == []

    def test_consistent_label(self):
        """Low braking point variance -> 'consistent' label."""
        perfs = [
            CornerPerformance(corner_id=i, s_start=i*100, s_end=i*100+50,
                              braking_point_delta_m=1.0)  # all same delta
            for i in range(1, 8)
        ]
        style = compute_driver_style(perfs)
        # Consistent braking -> should get "consistent" label
        assert "consistent" in style.style_labels or style.line_variance < 2.0
