"""Coaching Engine V3 — config-driven, physics-informed coaching."""
from telemetry_tool.coaching.composers.session_composer import compose_session_coaching
from telemetry_tool.coaching.models import SessionCoaching

__all__ = ["compose_session_coaching", "SessionCoaching"]
