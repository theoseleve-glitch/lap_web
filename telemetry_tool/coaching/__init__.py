"""Coaching Engine V3 — config-driven, physics-informed coaching."""
from coaching.composers.session_composer import compose_session_coaching
from coaching.models import SessionCoaching

__all__ = ["compose_session_coaching", "SessionCoaching"]
