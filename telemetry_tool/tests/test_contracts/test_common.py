import pytest
from pydantic import ValidationError

from telemetry_tool.web.schemas.contracts.common import (
    SourceLiteral,
    TrajectorySample,
    LapSummary,
    DriverRef,
    TrackRef,
    VehicleRef,
    Scores,
)


def test_source_literal_values():
    """Source is constrained to known engine keys."""
    assert SourceLiteral.REAL_LIFE.value == "real_life"
    assert SourceLiteral.IRACING.value == "iracing"
    assert SourceLiteral.AC.value == "ac"


def test_trajectory_sample_requires_time_and_distance():
    TrajectorySample(t_s=1.23, s_m=45.0, speed_ms=30.0)
    with pytest.raises(ValidationError):
        TrajectorySample(t_s=None, s_m=45.0, speed_ms=30.0)


def test_lap_summary_basic():
    lap = LapSummary(lap_number=1, lap_time_s=95.123, is_valid=True)
    assert lap.lap_number == 1
    assert lap.is_valid


def test_scores_range_0_100():
    Scores(pace=80.0, consistency=75.0, execution=90.0, robustness=82.0, overall=82.0)
    with pytest.raises(ValidationError):
        Scores(pace=120.0, consistency=75.0, execution=90.0, robustness=82.0, overall=82.0)
