"""
track_surface — Universal track surface reconstruction from telemetry.

Provides coordinate normalization, Frenet-frame geometry, multi-lap
centerline extraction, surface property estimation (boundaries, elevation,
camber, grip), solver bridging, line delta analysis, and spatial coaching.

Also re-exports the persistence layer for backward compatibility:
    upsert_session_grip, get_track_surface, get_aggregate_grip, AggregateGrip
"""
from track_surface.persistence import (
    AggregateGrip,
    get_aggregate_grip,
    get_global_aggregate_grip,
    get_track_surface,
    upsert_global_grip,
    upsert_session_grip,
)
from track_surface.store import (
    load_track_model,
    merge_track_model,
    upsert_global_surface,
)

__all__ = [
    "AggregateGrip",
    "get_aggregate_grip",
    "get_global_aggregate_grip",
    "get_track_surface",
    "load_track_model",
    "merge_track_model",
    "upsert_global_grip",
    "upsert_global_surface",
    "upsert_session_grip",
]
