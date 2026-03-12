"""Tests for corner diagnosis classifier and prerequisites."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


class TestCornerEventsToDict:
    """Prerequisite: CornerEvents.to_dict() must exist for MRP serialisation."""

    def test_to_dict_returns_plain_dict(self):
        from mrp_detector import CornerEvents

        ev = CornerEvents(
            corner_id=1,
            brake_point_m=100.0,
            turn_in_m=110.0,
            trail_brake_end_m=120.0,
            mrp_m=130.0,
            mrp_speed_mps=25.0,
            mrp_yaw_rate=0.05,
            throttle_application_m=135.0,
            track_out_m=160.0,
            geometric_apex_m=125.0,
            mrp_apex_delta_m=5.0,
        )
        d = ev.to_dict()
        assert isinstance(d, dict)
        assert d["mrp_m"] == 130.0
        assert d["mrp_apex_delta_m"] == 5.0
        assert d["corner_id"] == 1

    def test_to_dict_handles_none_fields(self):
        from mrp_detector import CornerEvents

        ev = CornerEvents(
            corner_id=2,
            brake_point_m=None,
            turn_in_m=50.0,
            trail_brake_end_m=None,
            mrp_m=60.0,
            mrp_speed_mps=20.0,
            mrp_yaw_rate=0.03,
            throttle_application_m=None,
            track_out_m=80.0,
            geometric_apex_m=55.0,
            mrp_apex_delta_m=5.0,
        )
        d = ev.to_dict()
        assert d["brake_point_m"] is None
        assert d["throttle_application_m"] is None
