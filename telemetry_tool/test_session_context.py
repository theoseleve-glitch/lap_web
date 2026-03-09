"""
tests/test_session_context.py
-----------------------------
Pytest unit tests for session_context.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from session_context import (
    SessionContext,
    SessionType,
    TrackState,
    WeatherObs,
    collect_session_context_cli,
    load_last_session_context,
    normalize_session_type,
    normalize_track_state,
    save_session_context,
)

# ============================================================================

# normalize_session_type

# ============================================================================


class TestNormalizeSessionType:
    """Tests for the session-type normalisation function."""

    @pytest.mark.parametrize("raw,expected", [
        ("practice",      SessionType.PRACTICE),
        ("qualifying",    SessionType.QUALIFYING),
        ("race",          SessionType.SPRINT_RACE),
        ("test",          SessionType.TEST),
        ("heat",          SessionType.HEAT),
        ("final",         SessionType.FINAL),
        ("sprint_race",   SessionType.SPRINT_RACE),
        ("feature_race",  SessionType.FEATURE_RACE),
        ("endurance_stint", SessionType.ENDURANCE_STINT),
        ("endurance_race",  SessionType.ENDURANCE_RACE),
    ])
    def test_canonical_values(self, raw: str, expected: SessionType) -> None:
        assert normalize_session_type(raw) == expected

    @pytest.mark.parametrize("raw,expected", [
        ("prac",     SessionType.PRACTICE),
        ("p",        SessionType.PRACTICE),
        ("quali",    SessionType.QUALIFYING),
        ("q",        SessionType.QUALIFYING),
        ("r",        SessionType.SPRINT_RACE),
        ("sprint",   SessionType.SPRINT_RACE),
        ("feature",  SessionType.FEATURE_RACE),
        ("endurance", SessionType.ENDURANCE_RACE),
        ("stint",    SessionType.ENDURANCE_STINT),
    ])
    def test_short_forms(self, raw: str, expected: SessionType) -> None:
        assert normalize_session_type(raw) == expected

    def test_whitespace_tolerance(self) -> None:
        assert normalize_session_type("  qualifying  ") == SessionType.QUALIFYING

    def test_case_insensitive(self) -> None:
        assert normalize_session_type("PRACTICE") == SessionType.PRACTICE
        assert normalize_session_type("Qualifying") == SessionType.QUALIFYING

    def test_hyphen_underscore(self) -> None:
        assert normalize_session_type("sprint-race") == SessionType.SPRINT_RACE
        assert normalize_session_type("endurance race") == SessionType.ENDURANCE_RACE

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown session type"):
            normalize_session_type("banana")

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            normalize_session_type("")


# ============================================================================

# normalize_track_state

# ============================================================================


class TestNormalizeTrackState:
    """Tests for the track-state normalisation function."""

    @pytest.mark.parametrize("raw,expected", [
        ("dry",      TrackState.DRY),
        ("wet",      TrackState.WET),
        ("damp",     TrackState.DAMP),
        ("green",    TrackState.GREEN),
        ("rubbered", TrackState.RUBBERED),
        ("dusty",    TrackState.DUSTY),
        ("full_wet", TrackState.FULL_WET),
        ("drying",   TrackState.DRYING),
        ("greasy",   TrackState.GREASY),
        ("cold",     TrackState.COLD),
        ("unknown",  TrackState.UNKNOWN),
    ])
    def test_canonical_values(self, raw: str, expected: TrackState) -> None:
        assert normalize_track_state(raw) == expected

    @pytest.mark.parametrize("raw,expected", [
        ("sec",      TrackState.DRY),
        ("mouillé",  TrackState.WET),
        ("humide",   TrackState.DAMP),
        ("soaked",   TrackState.FULL_WET),
    ])
    def test_synonyms_and_french(self, raw: str, expected: TrackState) -> None:
        assert normalize_track_state(raw) == expected

    def test_old_pipeline_values(self) -> None:
        """The old pipeline only used dry/wet/damp — must still work."""
        assert normalize_track_state("dry") == TrackState.DRY
        assert normalize_track_state("wet") == TrackState.WET
        assert normalize_track_state("damp") == TrackState.DAMP

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown track state"):
            normalize_track_state("volcanic")


# ============================================================================

# WeatherObs

# ============================================================================


class TestWeatherObs:

    def test_valid(self) -> None:
        w = WeatherObs(air_temp_c=20.0, humidity_pct=55.0, wind_dir_deg=270.0)
        assert w.validate() == []

    def test_all_none(self) -> None:
        w = WeatherObs()
        assert w.validate() == []

    def test_humidity_out_of_range(self) -> None:
        w = WeatherObs(humidity_pct=110.0)
        errors = w.validate()
        assert len(errors) == 1
        assert "humidity_pct" in errors[0]

    def test_negative_wind(self) -> None:
        w = WeatherObs(wind_speed_mps=-5.0)
        errors = w.validate()
        assert any("wind_speed_mps" in e for e in errors)

    def test_round_trip(self) -> None:
        w = WeatherObs(air_temp_c=18.5, track_temp_c=35.0, humidity_pct=72.0)
        d = w.to_dict()
        w2 = WeatherObs.from_dict(d)
        assert w2.air_temp_c == 18.5
        assert w2.track_temp_c == 35.0
        assert w2.humidity_pct == 72.0

    def test_from_dict_partial(self) -> None:
        w = WeatherObs.from_dict({"air_temp_c": 10.0})
        assert w.air_temp_c == 10.0
        assert w.track_temp_c is None


# ============================================================================

# SessionContext

# ============================================================================


class TestSessionContext:

    def test_created_at_auto(self) -> None:
        ctx = SessionContext(
            session_id="t-001",
            track_id=None,
            session_type=SessionType.PRACTICE,
            baseline_track_state=TrackState.DRY,
        )
        assert ctx.created_at_iso != ""
        assert "T" in ctx.created_at_iso  # ISO format has T separator

    def test_round_trip(self) -> None:
        ctx = SessionContext(
            session_id="rt-001",
            track_id="monza",
            session_type=SessionType.QUALIFYING,
            baseline_track_state=TrackState.DAMP,
            weather=WeatherObs(air_temp_c=15.0, humidity_pct=80.0),
            notes="Drizzle expected",
        )
        d = ctx.to_dict()
        ctx2 = SessionContext.from_dict(d)
        assert ctx2.session_id == "rt-001"
        assert ctx2.track_id == "monza"
        assert ctx2.session_type == SessionType.QUALIFYING
        assert ctx2.baseline_track_state == TrackState.DAMP
        assert ctx2.weather is not None
        assert ctx2.weather.air_temp_c == 15.0
        assert ctx2.notes == "Drizzle expected"

    def test_backward_compat_track_state_key(self) -> None:
        """Old format used 'track_state' instead of 'baseline_track_state'."""
        ctx = SessionContext.from_dict({
            "session_type": "race",
            "track_state": "wet",
        })
        assert ctx.session_type == SessionType.SPRINT_RACE
        assert ctx.baseline_track_state == TrackState.WET

    def test_from_dict_minimal(self) -> None:
        ctx = SessionContext.from_dict({})
        assert ctx.session_type == SessionType.PRACTICE
        assert ctx.baseline_track_state == TrackState.DRY


# ============================================================================

# Persistence

# ============================================================================


class TestPersistence:

    def test_save_and_load(self, tmp_path: Path) -> None:
        ctx = SessionContext(
            session_id="persist-001",
            track_id="spa",
            session_type=SessionType.HEAT,
            baseline_track_state=TrackState.GREEN,
        )
        p = tmp_path / "results" / "spa" / "session_context.json"
        save_session_context(ctx, p)

        assert p.exists()
        raw = json.loads(p.read_text(encoding="utf-8"))
        assert raw["session_id"] == "persist-001"
        assert raw["session_type"] == "heat"

    def test_load_last_picks_newest(self, tmp_path: Path) -> None:
        base = tmp_path / "results"
        # Create two contexts

        ctx1 = SessionContext(
            session_id="old",
            track_id=None,
            session_type=SessionType.PRACTICE,
            baseline_track_state=TrackState.DRY,
        )
        ctx2 = SessionContext(
            session_id="new",
            track_id=None,
            session_type=SessionType.QUALIFYING,
            baseline_track_state=TrackState.WET,
        )
        save_session_context(ctx1, base / "run1" / "session_context.json")

        import time
        time.sleep(0.05)  # ensure different mtime
        save_session_context(ctx2, base / "run2" / "session_context.json")

        loaded = load_last_session_context(base)
        assert loaded is not None
        assert loaded.session_id == "new"

    def test_load_empty_dir(self, tmp_path: Path) -> None:
        assert load_last_session_context(tmp_path) is None

    def test_load_nonexistent_dir(self) -> None:
        assert load_last_session_context(Path("/nonexistent_xyz")) is None

    def test_atomic_write_creates_parents(self, tmp_path: Path) -> None:
        deep = tmp_path / "a" / "b" / "c" / "session_context.json"
        ctx = SessionContext(
            session_id="deep",
            track_id=None,
            session_type=SessionType.PRACTICE,
            baseline_track_state=TrackState.DRY,
        )
        save_session_context(ctx, deep)
        assert deep.exists()


# ============================================================================

# CLI collection

# ============================================================================


class TestCollectCLI:

    def test_defaults(self) -> None:
        responses = iter(["", "", "n", ""])
        ctx = collect_session_context_cli(input_func=lambda _: next(responses))
        assert ctx.session_type == SessionType.PRACTICE
        assert ctx.baseline_track_state == TrackState.DRY
        assert ctx.weather is None
        assert ctx.notes is None

    def test_custom_values(self) -> None:
        responses = iter(["quali", "drying", "n", "tyre pressure 2.1 bar"])
        ctx = collect_session_context_cli(input_func=lambda _: next(responses))
        assert ctx.session_type == SessionType.QUALIFYING
        assert ctx.baseline_track_state == TrackState.DRYING
        assert ctx.notes == "tyre pressure 2.1 bar"

    def test_with_weather(self) -> None:
        responses = iter([
            "race",       # session type
            "wet",        # track state
            "yes",        # enter weather?
            "12.5",       # air temp
            "25.0",       # track temp
            "90",         # humidity
            "",           # wind speed (skip)
            "",           # wind dir (skip)
            "",           # notes (skip)
        ])
        ctx = collect_session_context_cli(input_func=lambda _: next(responses))
        assert ctx.session_type == SessionType.SPRINT_RACE
        assert ctx.weather is not None
        assert ctx.weather.air_temp_c == 12.5
        assert ctx.weather.humidity_pct == 90.0
        assert ctx.weather.wind_speed_mps is None

    def test_defaults_from_last(self) -> None:
        last = SessionContext(
            session_id="prev",
            track_id=None,
            session_type=SessionType.QUALIFYING,
            baseline_track_state=TrackState.DAMP,
        )
        responses = iter(["", "", "n", ""])
        ctx = collect_session_context_cli(
            defaults_from_last=True,
            last=last,
            input_func=lambda _: next(responses),
        )
        assert ctx.session_type == SessionType.QUALIFYING
        assert ctx.baseline_track_state == TrackState.DAMP
