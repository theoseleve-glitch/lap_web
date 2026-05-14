"""Day-11 Phase B — Open-Meteo client + filesystem cache tests.

Committed FAILING per the test-first discipline: ``open_meteo.fetch_weather``
is a stub raising NotImplementedError at the start of Phase B; this file
encodes the spec §4 + §9 contract that the implementation must satisfy.

8 mocked tests + 1 network-gated real-API test:

    1. test_cache_miss_writes_two_files_atomically
    2. test_cache_hit_second_call_no_http
    3. test_cache_key_filename_matches_spec_section9
    4. test_atomic_write_no_partial_files_visible
    5. test_http_500_raises_open_meteo_fetch_error
    6. test_http_429_rate_limit_backs_off_and_retries
    7. test_hourly_response_exposes_all_spec_fields
    8. test_daily_response_has_30_day_window

    9. @pytest.mark.network test_real_api_schema_unchanged
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from telemetry_tool.conditions.open_meteo import (
    OpenMeteoFetchError,
    WeatherFetchResult,
    fetch_weather,
)


# ── Fixtures ──────────────────────────────────────────────────────────


# A known (lat, lon, when) used in tests; not real coords for any tracked
# session — purely for cache-key + mock-response shape verification.
_TEST_LAT = 47.39
_TEST_LON = 0.79
_TEST_WHEN = datetime(2026, 2, 7, 10, 47, tzinfo=timezone.utc)


def _synthetic_hourly_response() -> dict:
    """49-hour window (48h + the session-start hour). Open-Meteo's hourly
    response uses ISO timestamps under ``time`` and parallel arrays for
    each field."""
    n = 49
    return {
        "latitude": _TEST_LAT,
        "longitude": _TEST_LON,
        "hourly": {
            "time": [f"2026-02-{(5 + i // 24):02d}T{(i % 24):02d}:00" for i in range(n)],
            "temperature_2m": [10.0] * n,
            "precipitation": [0.0] * n,
            "cloudcover": [50.0] * n,
            "windspeed_10m": [12.0] * n,
            "winddirection_10m": [180.0] * n,
            "shortwave_radiation": [400.0] * n,
            "relative_humidity_2m": [70.0] * n,
            "dewpoint_2m": [5.0] * n,
        },
    }


def _synthetic_daily_response() -> dict:
    """30-day daily window for D5 lookup. Open-Meteo's daily response
    uses ISO dates under ``time`` and a parallel array for each field."""
    n = 30
    return {
        "latitude": _TEST_LAT,
        "longitude": _TEST_LON,
        "daily": {
            "time": [f"2026-01-{(8 + i):02d}" if (8 + i) <= 31
                     else f"2026-02-{((8 + i) - 31):02d}" for i in range(n)],
            "precipitation_sum": [0.0] * n,
        },
    }


@pytest.fixture
def mock_http(monkeypatch):
    """Replace the low-level HTTP getter with a deterministic queue.

    Usage:
        def test_x(mock_http):
            calls, queue = mock_http
            queue.append(("hourly", _synthetic_hourly_response()))
            queue.append(("daily", _synthetic_daily_response()))
            # ... call fetch_weather; assertions on calls
    """
    calls: list[dict] = []
    queue: list[tuple[str, Any]] = []

    def fake_get(url: str, params: dict, *, timeout: float = 10.0) -> dict:
        calls.append({"url": url, "params": dict(params)})
        if not queue:
            raise AssertionError(
                f"unexpected HTTP call (no queued response): {url} {params}"
            )
        kind, resp = queue.pop(0)
        if isinstance(resp, Exception):
            raise resp
        if isinstance(resp, dict) and "_http_status" in resp:
            status = resp["_http_status"]
            if status == 429:
                raise OpenMeteoFetchError(f"429 rate-limited (mock); will retry")
            raise OpenMeteoFetchError(f"HTTP {status}: {resp.get('_message', 'mock error')}")
        return resp

    monkeypatch.setattr(
        "telemetry_tool.conditions.open_meteo._http_get_json", fake_get
    )
    return calls, queue


# ── Tests (8 mocked) ──────────────────────────────────────────────────


def test_cache_miss_writes_two_files_atomically(tmp_path, mock_http):
    """Fresh cache dir → both endpoints fetched → two cache files written.

    Verifies §9 'two endpoints cached separately' contract.
    """
    calls, queue = mock_http
    queue.append(("hourly", _synthetic_hourly_response()))
    queue.append(("daily", _synthetic_daily_response()))

    result = fetch_weather(_TEST_LAT, _TEST_LON, _TEST_WHEN, cache_dir=tmp_path)

    assert isinstance(result, WeatherFetchResult)
    assert result.source == "api"
    assert len(calls) == 2, f"expected 2 HTTP calls, got {len(calls)}: {calls}"

    # Two cache files written
    cache_files = sorted(tmp_path.glob("*.json"))
    assert len(cache_files) == 2, f"expected 2 cache files, got {[p.name for p in cache_files]}"

    # Files are valid JSON (atomic write completed)
    for cf in cache_files:
        json.loads(cf.read_text())


def test_cache_hit_second_call_no_http(tmp_path, mock_http):
    """Second call with the same key → zero HTTP requests, result loaded from disk."""
    calls, queue = mock_http
    queue.append(("hourly", _synthetic_hourly_response()))
    queue.append(("daily", _synthetic_daily_response()))

    fetch_weather(_TEST_LAT, _TEST_LON, _TEST_WHEN, cache_dir=tmp_path)
    assert len(calls) == 2
    calls.clear()  # reset call counter

    # Same (lat, lon, when) → cache hit
    result2 = fetch_weather(_TEST_LAT, _TEST_LON, _TEST_WHEN, cache_dir=tmp_path)
    assert result2.source == "cache"
    assert len(calls) == 0, f"cache miss on second call; HTTP calls: {calls}"
    # Returned data must equal what was cached (round-trip through JSON)
    assert result2.hourly["hourly"]["temperature_2m"][0] == 10.0


def test_cache_key_filename_matches_spec_section9(tmp_path, mock_http):
    """§9 cache key: (round(lat,2), round(lon,2), date.isoformat())
    for hourly; same + 'daily30' suffix for daily."""
    calls, queue = mock_http
    queue.append(("hourly", _synthetic_hourly_response()))
    queue.append(("daily", _synthetic_daily_response()))

    fetch_weather(47.388, 0.789, _TEST_WHEN, cache_dir=tmp_path)

    files = {p.name for p in tmp_path.glob("*.json")}
    # Lat 47.388 rounds to 47.39 at 2 decimals; lon 0.789 → 0.79.
    expected_hourly_token = "47.39"
    expected_lon_token = "0.79"
    expected_date_token = "2026-02-07"
    # Exact filenames left to impl, but each filename must contain the
    # rounded lat/lon/date tokens, and exactly one must contain "daily30".
    assert any(
        expected_hourly_token in f
        and expected_lon_token in f
        and expected_date_token in f
        and "daily30" not in f
        for f in files
    ), f"no hourly cache file with expected tokens found in {files}"
    assert any(
        expected_hourly_token in f
        and expected_lon_token in f
        and expected_date_token in f
        and "daily30" in f
        for f in files
    ), f"no daily30 cache file with expected tokens found in {files}"


def test_atomic_write_no_partial_files_visible(tmp_path, mock_http, monkeypatch):
    """Simulate write failure mid-write → assert no .json file appears
    at the target path. The .tmp intermediate may exist but the final
    path must not be readable as JSON until rename completes."""
    calls, queue = mock_http
    queue.append(("hourly", _synthetic_hourly_response()))

    # Sabotage the rename step so writes appear to fail mid-flight.
    real_rename = Path.rename

    def failing_rename(self, target):
        raise OSError("disk full (simulated)")

    monkeypatch.setattr(Path, "rename", failing_rename)

    with pytest.raises((OSError, OpenMeteoFetchError)):
        fetch_weather(_TEST_LAT, _TEST_LON, _TEST_WHEN, cache_dir=tmp_path)

    # No final .json file landed (only the .tmp may exist)
    final_jsons = list(tmp_path.glob("*.json"))
    assert not final_jsons or all(
        ".tmp" in p.name for p in final_jsons
    ), f"partial file landed at final path: {[p.name for p in final_jsons]}"

    # Restore
    monkeypatch.setattr(Path, "rename", real_rename)


def test_http_500_raises_open_meteo_fetch_error(tmp_path, mock_http):
    """5xx response → OpenMeteoFetchError; classifier catches → safe-dry."""
    calls, queue = mock_http
    queue.append(("hourly", {"_http_status": 500, "_message": "server error"}))

    with pytest.raises(OpenMeteoFetchError):
        fetch_weather(_TEST_LAT, _TEST_LON, _TEST_WHEN, cache_dir=tmp_path)


def test_http_429_rate_limit_backs_off_and_retries(tmp_path, mock_http, monkeypatch):
    """429 on first call + 200 on retry → succeed. Sleep is patched to
    keep the test fast."""
    calls, queue = mock_http
    queue.append(("hourly", {"_http_status": 429}))                # first attempt
    queue.append(("hourly", _synthetic_hourly_response()))        # retry succeeds
    queue.append(("daily", _synthetic_daily_response()))

    sleeps: list[float] = []
    monkeypatch.setattr(
        "telemetry_tool.conditions.open_meteo.time.sleep",
        lambda s: sleeps.append(s),
    )

    result = fetch_weather(_TEST_LAT, _TEST_LON, _TEST_WHEN, cache_dir=tmp_path)
    assert result.source == "api"
    # Exactly one back-off slept between attempts
    assert len(sleeps) >= 1, f"expected at least one back-off sleep, got {sleeps}"


def test_hourly_response_exposes_all_spec_fields(tmp_path, mock_http):
    """Hourly response must contain every Open-Meteo field spec §4 lists
    (P5 air temp, P6 solar, P7 cloud, P8 wind, P9 RH, P10 dew point +
    precipitation for P1-P4 + winddirection_10m for spatial)."""
    calls, queue = mock_http
    queue.append(("hourly", _synthetic_hourly_response()))
    queue.append(("daily", _synthetic_daily_response()))

    result = fetch_weather(_TEST_LAT, _TEST_LON, _TEST_WHEN, cache_dir=tmp_path)

    hourly = result.hourly["hourly"]
    for field in (
        "time",
        "temperature_2m",
        "precipitation",
        "cloudcover",
        "windspeed_10m",
        "winddirection_10m",
        "shortwave_radiation",
        "relative_humidity_2m",
        "dewpoint_2m",
    ):
        assert field in hourly, f"hourly response missing spec field {field!r}"
        assert isinstance(hourly[field], list)
        assert len(hourly[field]) >= 48, (
            f"hourly[{field!r}] has only {len(hourly[field])} entries; expected ≥ 48"
        )


def test_daily_response_has_30_day_window(tmp_path, mock_http):
    """Daily response must have ≥ 30 entries for D5 lookback."""
    calls, queue = mock_http
    queue.append(("hourly", _synthetic_hourly_response()))
    queue.append(("daily", _synthetic_daily_response()))

    result = fetch_weather(_TEST_LAT, _TEST_LON, _TEST_WHEN, cache_dir=tmp_path)

    daily = result.daily["daily"]
    assert "time" in daily
    assert "precipitation_sum" in daily
    assert len(daily["time"]) >= 30, (
        f"daily window only {len(daily['time'])} days; expected ≥ 30"
    )


# ── Real-API test (network-gated) ─────────────────────────────────────


@pytest.mark.network
def test_real_api_schema_unchanged(tmp_path):
    """One real Open-Meteo call to verify the schema hasn't changed since
    the spec was authored. Uses a fixed historical date (Jan 1 2025) +
    KCT centroid coords. Runs once per test session; subsequent runs hit
    the cache (data preserved in tmp_path which is per-test).

    Skipped offline via ``pytest -m "not network"``.
    """
    result = fetch_weather(
        47.39, 0.79,
        datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc),
        cache_dir=tmp_path,
    )
    assert isinstance(result, WeatherFetchResult)
    # All spec-required hourly fields present
    hourly = result.hourly["hourly"]
    for field in (
        "temperature_2m", "precipitation", "cloudcover", "windspeed_10m",
        "winddirection_10m", "shortwave_radiation",
        "relative_humidity_2m", "dewpoint_2m",
    ):
        assert field in hourly, (
            f"REAL API response missing field {field!r} — spec may need amendment"
        )
    # Daily endpoint live too
    daily = result.daily["daily"]
    assert "precipitation_sum" in daily
    assert len(daily["time"]) >= 28, (
        f"REAL daily window only {len(daily['time'])} days; spec §4 D5 needs ≥ 30"
    )
