"""Scalar conditions classifier (spec §5 + §6 + §8 + §2).

Public API:
    classify_conditions(session_inputs, track_id, *, cache_dir=None)

Algorithm:
    1. If user_condition is set → source = "user". Compute mu_scale via
       the Section-6 lookup for that label using D1 from fetched weather
       (Rule 5b lookup also applies when user="greasy" + Rule 5b weather
       conditions match per brief). Return WeatherCondition with full
       raw_inputs + rationale citing user override.
    2. Else:
       a. Resolve (lat, lon) from track_id via ``track_centroid.py``.
       b. fetch_weather(lat, lon, session_start_utc).
       c. Compute P1-P10 + D1-D5.
       d. Evaluate Rules 1, 2, 3, 4, 5, 5b, 6, 7, 8, 9 in that order;
          first match wins.
       e. Look up mu_scale per Section 6 given (label, D1, dominant_factor).
       f. Return WeatherCondition with source = "weather".
    3. If fetch_weather raises OpenMeteoFetchError → safe-dry fallback
       per Day-11 brief: source = "weather" (not "ml_fallback" — that
       path is retired), confidence = 0.0, label = "dry", mu_scale = 0.9.

Implementation lands at Phase D; this module is stubs until
``test_classifier_synthetic.py`` is committed FAILING.
"""
from __future__ import annotations

from pathlib import Path

from .types import SessionInputs, WeatherCondition

# Classifier version string (spec §8). Day 11 ships the scalar layer.
CLASSIFIER_VERSION = "weather-v1.0"


def classify_conditions(
    session_inputs: SessionInputs,
    track_id: str,
    *,
    cache_dir: Path | None = None,
) -> WeatherCondition:
    """Classify the track conditions for one session.

    Args:
        session_inputs: Session start time + optional user_condition.
        track_id: Canonical track alias (e.g., ``"ok"``, ``"kct"``).
            Used to resolve (lat, lon) via gt-geojson centroid.
        cache_dir: Override Open-Meteo cache root (default
            ``data/cache/weather/``).

    Returns:
        :class:`WeatherCondition` with ``spatial_modifier=None`` for
        Day 11. Day 12 wires the spatial layer.

    Spec: §5 (rules) + §6 (mu_scale lookups) + §8 (output) + §2 (output
    hierarchy: user wins → weather → safe-dry fallback).
    """
    raise NotImplementedError(
        "Phase D — implement after test_classifier_synthetic.py FAILS"
    )
