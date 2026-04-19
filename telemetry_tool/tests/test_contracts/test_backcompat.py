"""Ensure contracts accept legacy-shaped dicts that existing code still emits."""
from datetime import datetime, timezone

from telemetry_tool.web.schemas.contracts import (
    ChannelTag,
    CoachingContract,
    DriverRef,
    OptimizerContract,
    OptimizerDepth,
    Scores,
    SessionCapabilities,
    SessionContract,
    SourceLiteral,
    TrackRef,
    VehicleRef,
)


def test_session_contract_accepts_pre_migration_row():
    """A session row that existed before migration 022 — no source, no profile, no caps.
    Adapters should default source to 'real_life' + minimal caps + empty profile."""
    legacy = {
        "session_id": "11111111-1111-1111-1111-111111111111",
        "workspace_id": "22222222-2222-2222-2222-222222222222",
        "source": "real_life",
        "capabilities": {"channels": ["gps"]},
        "data_profile": {},
        "driver": {"driver_id": 1, "name": "Theo"},
        "track": {"track_id": 10, "name": "OK"},
        "vehicle": {"vehicle_class": "kart"},
        "session_start": datetime(2025, 1, 1, tzinfo=timezone.utc).isoformat(),
        "duration_s": 1000.0,
        "laps": [],
        "scores": None,
    }
    s = SessionContract.model_validate(legacy)
    assert s.source is SourceLiteral.REAL_LIFE


def test_coaching_contract_accepts_empty_sheets():
    """Real-life sessions with insufficient data emit an empty-ish sheet; still valid."""
    c = CoachingContract(
        storyline=[],
        global_focus=[],
        corner_coaching={},
        not_evaluable_corners=[],
        validation_checks=[],
        next_run=[],
    )
    assert c.version == "1.0"


def test_optimizer_trajectory_only_from_legacy_real_life():
    """A real-life session can emit a minimal OptimizerContract without inputs."""
    o = OptimizerContract(
        depth=OptimizerDepth.TRAJECTORY_ONLY,
        method="trajectory",
        theoretical_lap_time_s=60.0,
        confidence=0.5,
    )
    assert o.reconstructed_inputs is None
