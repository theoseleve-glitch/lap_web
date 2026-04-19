"""Unified contracts for the W1 workstream.

Exported:
    ChannelTag, SessionCapabilities — capability enum + flag model
    (Additional contracts land in later tasks.)
"""
from __future__ import annotations

from telemetry_tool.web.schemas.contracts.capabilities import (
    ChannelTag,
    SessionCapabilities,
)

__all__ = ["ChannelTag", "SessionCapabilities"]
