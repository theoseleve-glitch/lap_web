"""Derive SessionCapabilities for a real-life session.

Strict rule: never declare a capability this hardware cannot measure
directly -- the W1 contract validator rejects real-life sessions claiming
THROTTLE/BRAKE/STEER/WHEEL_SPD/SHOCK_DEFL. If a CSV happens to include
such a channel (rare: OBD adapters), we silently drop it and let the
caller emit an Event via `events.py`.
"""
from __future__ import annotations

import logging
from typing import Any

from telemetry_tool.web.schemas.contracts import ChannelTag, SessionCapabilities

logger = logging.getLogger(__name__)

# Header-name substrings that indicate a channel is present, case-insensitive.
_PATTERNS: dict[ChannelTag, tuple[str, ...]] = {
    ChannelTag.GPS: ("latitude", "longitude", "gps"),
    ChannelTag.LAT_G: ("lateral acceleration", "accel_lat", "lat_g"),
    ChannelTag.LON_G: ("longitudinal acceleration", "accel_long", "lon_g"),
    ChannelTag.YAW_RATE: ("gyroscope z", "yaw_rate", "yaw rate"),
}


def build_capabilities(summary: dict[str, Any]) -> SessionCapabilities:
    headers = summary.get("available_channels") or []
    lower = [str(h).lower() for h in headers]
    present: set[ChannelTag] = set()
    for tag, needles in _PATTERNS.items():
        if any(any(n in h for n in needles) for h in lower):
            present.add(tag)
    return SessionCapabilities(channels=frozenset(present))
