from __future__ import annotations

from datetime import datetime, timezone

from telemetry_tool.pipeline.contract_adapter.session import (
    build_driver,
    build_track,
    build_vehicle,
    resolve_session_start,
    resolve_duration_s,
)


def test_driver_from_meta():
    meta = {"driver_id": 7, "driver_name": "Theo"}
    d = build_driver(meta)
    assert d.driver_id == 7
    assert d.name == "Theo"


def test_driver_default_when_id_missing():
    d = build_driver({"driver_name": "Test"})
    assert d.driver_id == 0
    assert d.name == "Test"


def test_track_ref_from_summary():
    summary = {"track_match": {"track_row_id": 10, "track_name": "Ouest Karting", "layout": "short"}}
    t = build_track(summary)
    assert t.track_id == 10
    assert t.name == "Ouest Karting"
    assert t.layout == "short"


def test_track_fallback_from_track_id_string():
    summary = {"track_id": "ouest_karting", "track_match": None}
    t = build_track(summary)
    assert t.name == "ouest_karting"
    assert t.track_id == 0


def test_kart_vehicle_ref():
    meta = {"kart_id": 42, "kart_name": "Tony Kart OTK"}
    v = build_vehicle(meta)
    assert v.vehicle_id == 42
    assert v.vehicle_class == "kart"
    assert v.model == "Tony Kart OTK"


def test_car_vehicle_ref_without_id():
    meta = {"vehicle_class": "gt3", "vehicle_model": "Porsche 992 GT3 R"}
    v = build_vehicle(meta)
    assert v.vehicle_id is None
    assert v.vehicle_class == "gt3"
    assert v.model == "Porsche 992 GT3 R"


def test_session_start_parses_iso_with_tz():
    meta = {"session_datetime": "2026-04-19T10:00:00+00:00"}
    dt = resolve_session_start(meta)
    assert dt == datetime(2026, 4, 19, 10, 0, 0, tzinfo=timezone.utc)


def test_session_start_defaults_to_utc_now_when_missing():
    dt = resolve_session_start({})
    assert dt.tzinfo is not None


def test_duration_sums_valid_laps_only():
    lap_times = [60.1, 59.8, None, 60.5, 0.0]
    assert resolve_duration_s(lap_times) == 60.1 + 59.8 + 60.5
