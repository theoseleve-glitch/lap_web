"""Shared fixtures for contract-adapter tests."""
from __future__ import annotations

import pytest

from telemetry_tool.pipeline.contract_adapter import ContextRef


@pytest.fixture
def ctx() -> ContextRef:
    return ContextRef(
        session_id="11111111-1111-1111-1111-111111111111",
        workspace_id="22222222-2222-2222-2222-222222222222",
    )


@pytest.fixture
def minimal_summary() -> dict:
    """Smallest pipeline summary the adapter must tolerate."""
    return {
        "session_meta": {
            "driver_name": "Theo",
            "session_type": "practice",
            "track_state": "dry",
            "date": "2026-04-19",
            "session_datetime": "2026-04-19T10:00:00+00:00",
            "driver_id": 1,
        },
        "track_id": "ouest_karting",
        "track_match": {"track_row_id": 10, "track_name": "Ouest Karting", "layout": "short"},
        "available_channels": ["Latitude (deg)", "Longitude (deg)", "Speed (m/s)"],
        "lap_times": [60.1, 59.8, 60.3],
        "lap_dict": {1: None, 2: None, 3: None},
        "best_lap_key": 2,
    }
