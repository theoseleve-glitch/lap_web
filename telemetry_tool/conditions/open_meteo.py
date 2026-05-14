"""Open-Meteo Historical Weather API client + filesystem cache.

Spec §4 (raw inputs) + §9 (caching). Endpoint:

    https://archive-api.open-meteo.com/v1/archive

No API key. Free + worldwide + hourly granularity going back decades.

Two endpoints fetched per session:

    1. Hourly 48h window ending at session start — provides P1-P10 +
       ``winddirection_10m``. Cache key:
           (round(lat, 2), round(lon, 2), date.isoformat())
    2. Daily 30-day archive (precipitation_sum) — provides the daily
       precipitation array consumed by D5. Cache key:
           (round(lat, 2), round(lon, 2), date.isoformat(), "daily30")

Historical weather doesn't change, so cache never expires. Atomic write
(.tmp → os.replace) protects against partial writes.

Day-11 Phase B implementation.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests

# ── Constants (spec-locked) ────────────────────────────────────────────

_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

_DEFAULT_CACHE_DIR = Path("data") / "cache" / "weather"

_HOURLY_FIELDS: tuple[str, ...] = (
    "temperature_2m",
    "precipitation",
    "cloudcover",
    "windspeed_10m",
    "winddirection_10m",
    "shortwave_radiation",
    "relative_humidity_2m",
    "dewpoint_2m",
)

_DAILY_FIELDS: tuple[str, ...] = ("precipitation_sum",)

# Retry policy for transient failures (429 rate-limit, transient 5xx).
_MAX_RETRIES_DEFAULT: int = 3
_BACKOFF_SECONDS: tuple[float, ...] = (0.5, 1.0, 2.0)

# Hourly window length per spec §4: "48h window ending at session start".
# We fetch 3 days to cover timezone slack, then slice the 49-entry tail
# (session-start hour + 48 preceding hours).
_HOURLY_WINDOW_HOURS: int = 49
_HOURLY_FETCH_DAYS_BACK: int = 2  # → 3-day inclusive window: T-2, T-1, T

# Daily window length per spec §4 D5: "30-day daily archive".
_DAILY_WINDOW_DAYS: int = 30


# ── Public types ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class WeatherFetchResult:
    """Combined hourly + daily fetch output.

    ``hourly`` keys: ``latitude``, ``longitude``, ``hourly`` (dict of
    parallel arrays incl. ``time`` ISO timestamps and every field in
    ``_HOURLY_FIELDS``; 49 entries each).

    ``daily`` keys: ``latitude``, ``longitude``, ``daily`` (dict of
    ``time`` ISO dates + ``precipitation_sum``; 30 entries each).

    ``source`` ∈ {"api", "cache", "mixed"} for test introspection.
    """

    hourly: dict
    daily: dict
    source: str


class OpenMeteoFetchError(RuntimeError):
    """Raised when Open-Meteo fetch fails (network, rate-limit, schema)."""


# ── HTTP layer (mockable in tests) ─────────────────────────────────────


def _http_get_json(url: str, params: dict, *, timeout: float = 10.0) -> dict:
    """Plain GET → JSON dict. Mocked in tests; isolated for monkeypatch."""
    try:
        resp = requests.get(url, params=params, timeout=timeout)
    except requests.RequestException as e:
        raise OpenMeteoFetchError(f"network error: {e}") from e
    if resp.status_code == 429:
        raise OpenMeteoFetchError(
            f"429 rate-limited at {url}; will retry per backoff policy"
        )
    if resp.status_code >= 500:
        raise OpenMeteoFetchError(
            f"HTTP {resp.status_code} at {url}: {resp.text[:200]}"
        )
    if resp.status_code >= 400:
        raise OpenMeteoFetchError(
            f"HTTP {resp.status_code} at {url}: {resp.text[:200]}"
        )
    try:
        return resp.json()
    except ValueError as e:
        raise OpenMeteoFetchError(f"non-JSON response from {url}: {e}") from e


# ── Cache layer (atomic) ───────────────────────────────────────────────


def _cache_filename(lat: float, lon: float, date_iso: str, *, daily: bool) -> str:
    """Spec §9 cache key. ``round(lat,2)`` formatted with 2 decimals."""
    lat_s = f"{round(lat, 2):.2f}"
    lon_s = f"{round(lon, 2):.2f}"
    if daily:
        return f"{lat_s}_{lon_s}_{date_iso}_daily30.json"
    return f"{lat_s}_{lon_s}_{date_iso}.json"


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON to ``path`` via .tmp + os.replace.

    Failure mode contract: if any step fails (write, fsync, rename), the
    final ``path`` is either untouched (pre-existing) or absent (fresh).
    Tests sabotage ``Path.rename`` to verify this — see Phase B's
    ``test_atomic_write_no_partial_files_visible``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    # os.replace is atomic on POSIX and Win32; Path.rename uses it on
    # Python 3.10+. Tests monkeypatch Path.rename specifically, so we
    # delegate via that method (Path → rename → os.replace).
    tmp.rename(path)


def _read_cache(path: Path) -> dict | None:
    """Return cached JSON or None on miss / malformed."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ── Endpoint fetchers (cache-aware) ────────────────────────────────────


def _fetch_with_retry(
    url: str,
    params: dict,
    *,
    max_retries: int = _MAX_RETRIES_DEFAULT,
) -> dict:
    """GET with exponential backoff on 429 / transient errors.

    Sleeps ``_BACKOFF_SECONDS[i]`` between attempts (0.5, 1, 2). Test
    suite monkeypatches ``time.sleep`` to keep fast.
    """
    last_err: OpenMeteoFetchError | None = None
    for attempt in range(max_retries):
        try:
            return _http_get_json(url, params)
        except OpenMeteoFetchError as e:
            last_err = e
            transient = "429" in str(e) or "network" in str(e)
            if not transient or attempt == max_retries - 1:
                raise
            backoff = _BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)]
            time.sleep(backoff)
    # unreachable; the loop either returns or raises
    assert last_err is not None
    raise last_err


def _fetch_hourly_48h(lat: float, lon: float, when: datetime) -> dict:
    """Fetch 3 days of hourly data covering the 48h window ending at ``when``."""
    end_date = when.date()
    start_date = end_date - timedelta(days=_HOURLY_FETCH_DAYS_BACK)
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "hourly": ",".join(_HOURLY_FIELDS),
        "timezone": "UTC",
    }
    raw = _fetch_with_retry(_ARCHIVE_URL, params)
    # Trim hourly arrays to the 49-entry window ending at session-start.
    hourly = raw.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return raw  # caller will error-out on missing fields
    # Find the last hourly index ≤ ``when``. Open-Meteo timestamps are
    # ISO strings; the last entry is end_date 23:00 UTC by default.
    when_iso = when.replace(minute=0, second=0, microsecond=0).isoformat(
        timespec="minutes"
    )[:16]  # "YYYY-MM-DDTHH:MM"
    cut_idx = None
    for i, t in enumerate(times):
        if t[:16] <= when_iso:
            cut_idx = i
    if cut_idx is None:
        cut_idx = len(times) - 1
    start_idx = max(0, cut_idx + 1 - _HOURLY_WINDOW_HOURS)
    end_idx = cut_idx + 1
    raw["hourly"] = {
        k: (v[start_idx:end_idx] if isinstance(v, list) else v)
        for k, v in hourly.items()
    }
    return raw


def _fetch_daily_30(lat: float, lon: float, when: datetime) -> dict:
    """Fetch 30-day daily precipitation_sum ending at ``when.date()``."""
    end_date = when.date()
    start_date = end_date - timedelta(days=_DAILY_WINDOW_DAYS - 1)
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "daily": ",".join(_DAILY_FIELDS),
        "timezone": "UTC",
    }
    return _fetch_with_retry(_ARCHIVE_URL, params)


# ── Public entry point ─────────────────────────────────────────────────


def fetch_weather(
    lat: float,
    lon: float,
    when: datetime,
    *,
    cache_dir: Path | None = None,
) -> WeatherFetchResult:
    """Fetch hourly 48h + daily 30-day Open-Meteo data for the session.

    Spec §4 + §9. Two endpoints cached separately under their own keys;
    historical weather → infinite TTL → second call is zero-API.
    """
    if cache_dir is None:
        cache_dir = _DEFAULT_CACHE_DIR
    cache_dir = Path(cache_dir)

    date_iso = when.date().isoformat()
    hourly_path = cache_dir / _cache_filename(lat, lon, date_iso, daily=False)
    daily_path = cache_dir / _cache_filename(lat, lon, date_iso, daily=True)

    hourly_cached = _read_cache(hourly_path)
    daily_cached = _read_cache(daily_path)

    # Both cache hits → zero HTTP.
    if hourly_cached is not None and daily_cached is not None:
        return WeatherFetchResult(
            hourly=hourly_cached, daily=daily_cached, source="cache"
        )

    # One or both miss → fetch what's missing, write atomically.
    if hourly_cached is None:
        hourly_cached = _fetch_hourly_48h(lat, lon, when)
        _atomic_write_json(hourly_path, hourly_cached)
    if daily_cached is None:
        daily_cached = _fetch_daily_30(lat, lon, when)
        _atomic_write_json(daily_path, daily_cached)

    return WeatherFetchResult(
        hourly=hourly_cached, daily=daily_cached, source="api"
    )
