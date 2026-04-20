from __future__ import annotations

from telemetry_tool.pipeline.contract_adapter.capabilities import build_capabilities
from telemetry_tool.web.schemas.contracts import ChannelTag, SessionCapabilities


def test_gps_only_kart_csv():
    summary = {
        "available_channels": ["Latitude (deg)", "Longitude (deg)", "Speed (m/s)"],
    }
    caps = build_capabilities(summary)
    assert caps.channels == frozenset({ChannelTag.GPS})


def test_racechrono_full_imu():
    summary = {
        "available_channels": [
            "Latitude (deg)", "Longitude (deg)", "Speed (m/s)",
            "Lateral acceleration (G)",
            "Longitudinal acceleration (G)",
            "Gyroscope z (rad/s)",
        ],
    }
    caps = build_capabilities(summary)
    assert ChannelTag.GPS in caps.channels
    assert ChannelTag.LAT_G in caps.channels
    assert ChannelTag.LON_G in caps.channels
    assert ChannelTag.YAW_RATE in caps.channels


def test_obd_throttle_channel_is_dropped_not_declared():
    """Per F-check: real-life MUST NOT declare THROTTLE even if a column exists."""
    summary = {
        "available_channels": [
            "Latitude (deg)", "Longitude (deg)", "Speed (m/s)",
            "Throttle (%)",
        ],
    }
    caps = build_capabilities(summary)
    # GPS declared; THROTTLE silently dropped (contract validator would reject it anyway)
    assert ChannelTag.THROTTLE not in caps.channels
    assert ChannelTag.GPS in caps.channels


def test_empty_summary_returns_empty_capabilities():
    caps = build_capabilities({})
    assert caps.channels == frozenset()
    assert isinstance(caps, SessionCapabilities)
