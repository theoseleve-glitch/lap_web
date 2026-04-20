"""Channel capability enum + session capability flags.

Each detector in the coaching library declares which channels it needs
(`NEEDS: set[ChannelTag]`). At runtime, the coach assembler filters
detectors by the session's capabilities — depth scales with data.
"""
from __future__ import annotations

from enum import Enum
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field


class ChannelTag(str, Enum):
    """Canonical identifier for a telemetry channel family.

    Kept deliberately small. Add entries only when a detector needs a
    distinction that cannot be inferred from an existing tag. Extending
    this set is a contract-level change — version bump required.
    """
    GPS = "gps"                  # lat/lon/speed from GPS receiver
    LAT_G = "lat_g"              # lateral acceleration (m/s^2 or G)
    LON_G = "lon_g"              # longitudinal acceleration
    YAW_RATE = "yaw_rate"        # body yaw rate (rad/s)
    THROTTLE = "throttle"        # driver throttle input [0..1]
    BRAKE = "brake"              # driver brake input [0..1]
    STEER = "steer"              # steering angle or normalized input
    WHEEL_SPD = "wheel_spd"      # per-wheel speed (sim only)
    SHOCK_DEFL = "shock_defl"    # shock deflection per corner (sim only)


class SessionCapabilities(BaseModel):
    """Flags describing which channels are present in a given session.

    The set is populated by the data-profile detector (W2) at upload time.
    Coaches and optimizers consume this to pick the right analyzer subset.
    """
    model_config = ConfigDict(frozen=True)

    channels: frozenset[ChannelTag] = Field(default_factory=frozenset)

    def has(self, tag: ChannelTag) -> bool:
        return tag in self.channels

    def has_all(self, tags: Iterable[ChannelTag]) -> bool:
        tag_set = set(tags)
        return bool(tag_set) and tag_set.issubset(self.channels)
