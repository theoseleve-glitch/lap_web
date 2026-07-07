"""Regression: forecast horizon extends to 16 days (was hard-capped at 48 h).

Race Brief windows a future race date on this forecast; the old ``min(hours, 48)``
cap meant any race more than ~2 days out got a blank/48h forecast.
"""
from __future__ import annotations

import json
import urllib.request

import meteo_service


class _Resp:
    def __init__(self, body: bytes) -> None:
        self._b = body

    def read(self) -> bytes:
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen_factory(captured: dict):
    def fake_urlopen(url, timeout=None):
        captured["url"] = url
        body = json.dumps({
            "hourly": {
                "time": ["2026-07-01T19:00", "2026-07-01T20:00"],
                "temperature_2m": [20.0, 21.0],
                "relative_humidity_2m": [50, 51],
                "wind_speed_10m": [2.0, 3.0],
                "precipitation_probability": [0, 10],
                "rain": [0.0, 0.0],
                "weather_code": [0, 0],
            }
        }).encode()
        return _Resp(body)
    return fake_urlopen


def test_requests_16_day_horizon(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen_factory(captured))
    meteo_service.get_weather_forecast(47.39, 0.79, hours=384)
    assert "forecast_hours=384" in captured["url"]


def test_clamps_above_16_days(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen_factory(captured))
    meteo_service.get_weather_forecast(47.39, 0.79, hours=500)
    assert "forecast_hours=384" in captured["url"]


def test_default_short_horizon_unchanged(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen_factory(captured))
    meteo_service.get_weather_forecast(47.39, 0.79, hours=12)
    assert "forecast_hours=12" in captured["url"]
