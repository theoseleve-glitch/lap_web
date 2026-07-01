"""Regression: classify_conditions must accept caller-supplied coords.

Real user-uploaded tracks have no gt-geojson, so gt-only centroid resolution
raised FileNotFoundError -> every real session classified safe-dry, weather
never affected the condition, and wet/damp grip never accumulated. The pipeline
now passes the session's GPS centroid via `coords=`; this test locks that the
coords are used and gt resolution is bypassed.
"""
from __future__ import annotations

import datetime as dt

from conditions import classifier
from conditions.types import SessionInputs


def test_provided_coords_bypass_gt_resolution(monkeypatch):
    captured = {}

    def fake_fetch(lat, lon, ts, cache_dir=None):
        captured["coords"] = (lat, lon)
        # Raise the classifier's own fetch error so we return cleanly after
        # proving the coords reached fetch_weather (weather parsing is not
        # under test here).
        raise classifier.OpenMeteoFetchError("stop-after-coords")

    def fake_centroid(track_id):  # must NOT be called when coords are given
        raise AssertionError("resolve_track_centroid called despite coords=")

    monkeypatch.setattr(classifier, "fetch_weather", fake_fetch)
    monkeypatch.setattr(classifier, "resolve_track_centroid", fake_centroid)

    si = SessionInputs(started_at_utc=dt.datetime(2026, 6, 15, 14, tzinfo=dt.timezone.utc))
    classifier.classify_conditions(si, "user-uuid-track", coords=(47.3881, 0.7891))

    assert captured["coords"] == (47.3881, 0.7891)


def test_no_coords_still_uses_gt_then_safe_dry(monkeypatch):
    def fake_centroid(track_id):
        raise FileNotFoundError("no gt for this track")

    monkeypatch.setattr(classifier, "resolve_track_centroid", fake_centroid)
    si = SessionInputs(started_at_utc=dt.datetime(2026, 6, 15, 14, tzinfo=dt.timezone.utc))
    res = classifier.classify_conditions(si, "curated-track")  # no coords
    assert res.dominant_factor == "safe_dry_fallback"
