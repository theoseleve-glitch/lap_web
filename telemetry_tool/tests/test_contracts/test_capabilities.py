from telemetry_tool.web.schemas.contracts.capabilities import ChannelTag, SessionCapabilities


def test_channel_tag_covers_w1_acceptance_set():
    """W1 acceptance: enum covers GPS, LAT_G, LON_G, YAW_RATE, THROTTLE, BRAKE, STEER, WHEEL_SPD, SHOCK_DEFL."""
    required = {"GPS", "LAT_G", "LON_G", "YAW_RATE", "THROTTLE", "BRAKE", "STEER", "WHEEL_SPD", "SHOCK_DEFL"}
    present = {tag.name for tag in ChannelTag}
    missing = required - present
    assert not missing, f"missing channel tags: {missing}"


def test_session_capabilities_empty_default():
    """Capabilities default to empty set — unknown until set."""
    caps = SessionCapabilities()
    assert caps.channels == frozenset()
    assert caps.has(ChannelTag.GPS) is False


def test_session_capabilities_has_check():
    caps = SessionCapabilities(channels=frozenset({ChannelTag.GPS, ChannelTag.LAT_G}))
    assert caps.has(ChannelTag.GPS)
    assert caps.has(ChannelTag.LAT_G)
    assert not caps.has(ChannelTag.THROTTLE)
