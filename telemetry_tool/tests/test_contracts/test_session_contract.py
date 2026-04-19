from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from telemetry_tool.web.schemas.contracts import (
    ChannelTag,
    DriverRef,
    LapSummary,
    Scores,
    SessionCapabilities,
    SessionContract,
    SourceLiteral,
    TrackRef,
    VehicleRef,
)


def _minimal_session(**overrides) -> SessionContract:
    base = {
        "session_id": str(uuid4()),
        "workspace_id": str(uuid4()),
        "source": SourceLiteral.REAL_LIFE,
        "capabilities": SessionCapabilities(channels=frozenset({ChannelTag.GPS, ChannelTag.LAT_G, ChannelTag.LON_G})),
        "driver": DriverRef(driver_id=1, name="Theo"),
        "track": TrackRef(track_id=10, name="Ouest Karting"),
        "vehicle": VehicleRef(vehicle_class="kart"),
        "session_start": datetime.now(timezone.utc),
        "duration_s": 1234.5,
        "laps": [LapSummary(lap_number=1, lap_time_s=60.1)],
        "scores": Scores(pace=80, consistency=70, execution=75, robustness=85, overall=77),
        "data_profile": {"parser": "racechrono", "columns_detected": 14},
    }
    base.update(overrides)
    return SessionContract(**base)


def test_session_contract_constructs():
    s = _minimal_session()
    assert s.source is SourceLiteral.REAL_LIFE
    assert s.laps[0].lap_number == 1


def test_session_contract_json_roundtrip():
    s = _minimal_session()
    payload = s.model_dump_json()
    restored = SessionContract.model_validate_json(payload)
    assert restored == s


def test_session_contract_rejects_unknown_source():
    with pytest.raises(ValidationError):
        _minimal_session(source="lmu_not_yet_supported")


def test_session_contract_laps_can_be_empty():
    s = _minimal_session(laps=[])
    assert s.laps == []


def test_session_contract_capabilities_match_source_for_realife():
    """Real-life sessions MUST NOT claim THROTTLE/BRAKE/STEER — those are inferred, not measured."""
    with pytest.raises(ValidationError):
        _minimal_session(
            source=SourceLiteral.REAL_LIFE,
            capabilities=SessionCapabilities(channels=frozenset({ChannelTag.GPS, ChannelTag.THROTTLE})),
        )


def test_session_contract_accepts_sim_with_driver_input_channels():
    """Sim sources CAN claim THROTTLE/BRAKE/STEER — guard is real_life-only."""
    s = _minimal_session(
        source=SourceLiteral.IRACING,
        capabilities=SessionCapabilities(
            channels=frozenset({
                ChannelTag.GPS,
                ChannelTag.THROTTLE,
                ChannelTag.BRAKE,
                ChannelTag.STEER,
            })
        ),
    )
    assert ChannelTag.THROTTLE in s.capabilities.channels
    assert s.source is SourceLiteral.IRACING
