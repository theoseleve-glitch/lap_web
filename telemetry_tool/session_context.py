"""
session_context.py
------------------
Rich session metadata with backward-compatible enums, CLI collection,
and JSON persistence.

Public API
~~~~~~~~~~
``SessionType``         Enum with 9 session types + synonym mapping.
``TrackState``          Enum with 11 track states + synonym mapping.
``WeatherObs``          Optional weather observation dataclass.
``SessionContext``      Complete session metadata dataclass.
``normalize_session_type(user_str)``     Parse any user string â†’ SessionType.
``normalize_track_state(user_str)``      Parse any user string â†’ TrackState.
``collect_session_context_cli(...)``     Interactive CLI collection.
``save_session_context(ctx, path)``      Persist to JSON.
``load_last_session_context(base_dir)``  Load newest saved context.

Session-ID scheme
~~~~~~~~~~~~~~~~~
``YYYY-MM-DD_HHmmss`` derived from local wall-clock at creation time.
Deterministic from the clock, human-readable, sorts chronologically.

Design principles
~~~~~~~~~~~~~~~~~
- Backward compatible with old CLI values (practice/qualifying/race, dry/wet/damp).
- CLI prompts are testable via *input_func* injection.
- All I/O uses atomic write (tmp â†’ rename) and UTF-8.
- No global mutable state; constants and enums only.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Final, Optional

logger = logging.getLogger(__name__)

_CONTEXT_FILENAME: Final[str] = "session_context.json"


# ============================================================================

# Enums

# ============================================================================


class SessionType(Enum):
    """Session type with human-readable values."""
    PRACTICE      = "practice"
    TEST          = "test"
    QUALIFYING    = "qualifying"
    HEAT          = "heat"
    FINAL         = "final"
    SPRINT_RACE   = "sprint_race"
    FEATURE_RACE  = "feature_race"
    ENDURANCE_STINT = "endurance_stint"
    ENDURANCE_RACE  = "endurance_race"


class TrackState(Enum):
    """Track surface condition."""
    GREEN    = "green"
    RUBBERED = "rubbered"
    DUSTY    = "dusty"
    DAMP     = "damp"
    WET      = "wet"
    FULL_WET = "full_wet"
    DRYING   = "drying"
    GREASY   = "greasy"
    COLD     = "cold"
    DRY      = "dry"
    UNKNOWN  = "unknown"


# -- -

# Synonym mappings (lowercase â†’ enum member)

# -- -


_SESSION_TYPE_SYNONYMS: Final[dict[str, SessionType]] = {
    # Canonical

    "practice":        SessionType.PRACTICE,
    "test":            SessionType.TEST,
    "qualifying":      SessionType.QUALIFYING,
    "heat":            SessionType.HEAT,
    "final":           SessionType.FINAL,
    "sprint_race":     SessionType.SPRINT_RACE,
    "feature_race":    SessionType.FEATURE_RACE,
    "endurance_stint": SessionType.ENDURANCE_STINT,
    "endurance_race":  SessionType.ENDURANCE_RACE,
    # Short forms / aliases

    "prac":     SessionType.PRACTICE,
    "p":        SessionType.PRACTICE,
    "quali":    SessionType.QUALIFYING,
    "q":        SessionType.QUALIFYING,
    "race":     SessionType.SPRINT_RACE,
    "r":        SessionType.SPRINT_RACE,
    "sprint":   SessionType.SPRINT_RACE,
    "feature":  SessionType.FEATURE_RACE,
    "endurance": SessionType.ENDURANCE_RACE,
    "stint":    SessionType.ENDURANCE_STINT,
    "essai":    SessionType.PRACTICE,       # French
    "course":   SessionType.SPRINT_RACE,    # French
}

_TRACK_STATE_SYNONYMS: Final[dict[str, TrackState]] = {
    # Canonical

    "green":    TrackState.GREEN,
    "rubbered": TrackState.RUBBERED,
    "dusty":    TrackState.DUSTY,
    "damp":     TrackState.DAMP,
    "wet":      TrackState.WET,
    "full_wet": TrackState.FULL_WET,
    "drying":   TrackState.DRYING,
    "greasy":   TrackState.GREASY,
    "cold":     TrackState.COLD,
    "dry":      TrackState.DRY,
    "unknown":  TrackState.UNKNOWN,
    # Aliases

    "humide":   TrackState.DAMP,       # French
    "mouille":  TrackState.WET,        # French (no accent)
    "mouillé":  TrackState.WET,        # French (accent)
    "sec":      TrackState.DRY,        # French
    "séchant":  TrackState.DRYING,     # French
    "gras":     TrackState.GREASY,     # French
    "soaked":   TrackState.FULL_WET,
    "moist":    TrackState.DAMP,
}


# ============================================================================

# Normalisation helpers

# ============================================================================


def normalize_session_type(user_str: str) -> SessionType:
    """
    Parse a user-provided string into a ``SessionType``.

    Accepts canonical values, short forms (``prac``, ``q``, ``r``), and
    the old pipeline values (``practice``, ``qualifying``, ``race``).

    Raises ``ValueError`` if the string is not recognised.
    """
    key = user_str.strip().lower().replace("-", "_").replace(" ", "_")
    result = _SESSION_TYPE_SYNONYMS.get(key)
    if result is not None:
        return result
    # Try direct enum value match

    for member in SessionType:
        if member.value == key:
            return member
    raise ValueError(
        f"Unknown session type: {user_str!r}.  "
        f"Valid: {', '.join(sorted(_SESSION_TYPE_SYNONYMS.keys()))}"
    )


def normalize_track_state(user_str: str) -> TrackState:
    """
    Parse a user-provided string into a ``TrackState``.

    Accepts canonical values, French equivalents, and the old pipeline
    values (``dry``, ``wet``, ``damp``).

    Raises ``ValueError`` if the string is not recognised.
    """
    key = user_str.strip().lower().replace("-", "_").replace(" ", "_")
    result = _TRACK_STATE_SYNONYMS.get(key)
    if result is not None:
        return result
    for member in TrackState:
        if member.value == key:
            return member
    raise ValueError(
        f"Unknown track state: {user_str!r}.  "
        f"Valid: {', '.join(sorted(_TRACK_STATE_SYNONYMS.keys()))}"
    )


# ============================================================================

# Data structures

# ============================================================================


@dataclass
class WeatherObs:
    """Optional weather observation.  All fields are nullable."""
    air_temp_c:     Optional[float] = None
    track_temp_c:   Optional[float] = None
    humidity_pct:   Optional[float] = None
    wind_speed_mps: Optional[float] = None
    wind_dir_deg:   Optional[float] = None

    def validate(self) -> list[str]:
        """Return a list of validation errors (empty = valid)."""
        errors: list[str] = []
        if self.humidity_pct is not None and not (0.0 <= self.humidity_pct <= 100.0):
            errors.append(f"humidity_pct must be 0â€“100, got {self.humidity_pct}")
        if self.wind_dir_deg is not None and not (0.0 <= self.wind_dir_deg <= 360.0):
            errors.append(f"wind_dir_deg must be 0â€“360, got {self.wind_dir_deg}")
        if self.wind_speed_mps is not None and self.wind_speed_mps < 0:
            errors.append(f"wind_speed_mps must be >= 0, got {self.wind_speed_mps}")
        if self.air_temp_c is not None and not (-60.0 <= self.air_temp_c <= 65.0):
            errors.append(f"air_temp_c out of realistic range: {self.air_temp_c}")
        if self.track_temp_c is not None and not (-40.0 <= self.track_temp_c <= 90.0):
            errors.append(f"track_temp_c out of realistic range: {self.track_temp_c}")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "air_temp_c":     self.air_temp_c,
            "track_temp_c":   self.track_temp_c,
            "humidity_pct":   self.humidity_pct,
            "wind_speed_mps": self.wind_speed_mps,
            "wind_dir_deg":   self.wind_dir_deg,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WeatherObs":
        return cls(
            air_temp_c=d.get("air_temp_c"),
            track_temp_c=d.get("track_temp_c"),
            humidity_pct=d.get("humidity_pct"),
            wind_speed_mps=d.get("wind_speed_mps"),
            wind_dir_deg=d.get("wind_dir_deg"),
        )


@dataclass
class SessionContext:
    """Complete session metadata."""
    session_id:           str
    track_id:             Optional[str]
    session_type:         SessionType
    baseline_track_state: TrackState
    weather:              Optional[WeatherObs] = None
    notes:                Optional[str]        = None
    reference_lap_times:  Optional[list[float]] = None
    created_at_iso:       str                  = field(default_factory=lambda: "")

    def __post_init__(self) -> None:
        if not self.created_at_iso:
            self.created_at_iso = datetime.now().isoformat(timespec="seconds")

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id":           self.session_id,
            "track_id":             self.track_id,
            "session_type":         self.session_type.value,
            "baseline_track_state": self.baseline_track_state.value,
            "weather":              self.weather.to_dict() if self.weather else None,
            "notes":                self.notes,
            "reference_lap_times":  self.reference_lap_times,
            "created_at_iso":       self.created_at_iso,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SessionContext":
        weather_raw = d.get("weather")
        weather = WeatherObs.from_dict(weather_raw) if isinstance(weather_raw, dict) else None
        return cls(
            session_id=d.get("session_id", "unknown"),
            track_id=d.get("track_id"),
            session_type=normalize_session_type(d.get("session_type", "practice")),
            baseline_track_state=normalize_track_state(
                d.get("baseline_track_state", d.get("track_state", "dry"))
            ),
            weather=weather,
            notes=d.get("notes"),
            reference_lap_times=d.get("reference_lap_times"),
            created_at_iso=d.get("created_at_iso", ""),
        )


# ============================================================================

# CLI collection (testable via input_func injection)

# ============================================================================


def _generate_session_id() -> str:
    """Generate a human-readable session ID from wall-clock time."""
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def _prompt_optional_float(
    prompt: str,
    *,
    input_func: Callable[[str], str] = input,
) -> Optional[float]:
    """Ask for an optional float.  Enter skips (returns None)."""
    raw = input_func(f"  {prompt} [Enter to skip]: ").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def collect_session_context_cli(
    *,
    defaults_from_last: bool = False,
    last: Optional[SessionContext] = None,
    input_func: Callable[[str], str] = input,
) -> SessionContext:
    """
    Interactively collect session metadata from the console.

    Parameters
    ----------
    defaults_from_last:
        If True and *last* is provided, use its values as defaults.
    last:
        Previous session context for default population.
    input_func:
        Callable replacing ``input()`` for testability.

    Returns
    -------
    SessionContext
        Populated context.  ``track_id`` is left as None (set later
        by track detection).
    """
    # Defaults

    def_type = "practice"
    def_state = "dry"
    if defaults_from_last and last is not None:
        def_type = last.session_type.value
        def_state = last.baseline_track_state.value

    # Session type

    while True:
        raw = input_func(
            f"  Session type [{def_type}] "
            f"(practice/qualifying/race/heat/final/endurance/stint): "
        ).strip()
        if not raw:
            session_type = normalize_session_type(def_type)
            break
        try:
            session_type = normalize_session_type(raw)
            break
        except ValueError:
            print(f"    Unknown session type: {raw!r}")

    # Track state

    while True:
        raw = input_func(
            f"  Track state [{def_state}] "
            f"(dry/damp/wet/drying/green/rubbered/cold): "
        ).strip()
        if not raw:
            baseline = normalize_track_state(def_state)
            break
        try:
            baseline = normalize_track_state(raw)
            break
        except ValueError:
            print(f"    Unknown track state: {raw!r}")

    # Optional weather

    raw_weather = input_func(
        "  Enter weather data? [y/N]: "
    ).strip().lower()
    weather: Optional[WeatherObs] = None
    if raw_weather in ("y", "yes", "oui"):
        weather = WeatherObs(
            air_temp_c=_prompt_optional_float("Air temp (°C)", input_func=input_func),
            track_temp_c=_prompt_optional_float("Track temp (°C)", input_func=input_func),
            humidity_pct=_prompt_optional_float("Humidity (%)", input_func=input_func),
            wind_speed_mps=_prompt_optional_float("Wind speed (m/s)", input_func=input_func),
            wind_dir_deg=_prompt_optional_float("Wind direction (°)", input_func=input_func),
        )
        errors = weather.validate()
        if errors:
            logger.warning("Weather validation: %s", "; ".join(errors))

    # Notes

    notes_raw = input_func("  Notes [Enter to skip]: ").strip()
    notes = notes_raw if notes_raw else None

    ctx = SessionContext(
        session_id=_generate_session_id(),
        track_id=None,
        session_type=session_type,
        baseline_track_state=baseline,
        weather=weather,
        notes=notes,
    )
    logger.info(
        "Session context: type=%s state=%s id=%s",
        ctx.session_type.value,
        ctx.baseline_track_state.value,
        ctx.session_id,
    )
    return ctx


# ============================================================================

# Persistence

# ============================================================================


def save_session_context(context: SessionContext, path: Path) -> None:
    """
    Persist *context* as JSON with atomic write (tmp â†’ rename).

    Creates parent directories if needed.  File is UTF-8, sorted keys,
    2-space indent for human readability.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(context.to_dict(), indent=2, sort_keys=True, ensure_ascii=False)

    # Atomic write: write to temp file in same directory, then rename

    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), suffix=".tmp", prefix=".ctx_"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
            f.write("\n")
        # os.replace is atomic on POSIX; best-effort on Windows

        os.replace(tmp_path, str(path))
        logger.info("Saved session context to %s", path)
    except Exception:
        # Clean up temp file on failure

        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_last_session_context(base_results_dir: Path) -> Optional[SessionContext]:
    """
    Find the newest ``session_context.json`` under *base_results_dir*,
    load it with backward compatibility, and return it.

    Returns ``None`` if no context file is found or if parsing fails.
    """
    if not base_results_dir.is_dir():
        return None

    candidates: list[tuple[float, Path]] = []
    for p in base_results_dir.rglob(_CONTEXT_FILENAME):
        try:
            candidates.append((p.stat().st_mtime, p))
        except OSError:
            continue

    if not candidates:
        return None

    # Pick the most recently modified file

    candidates.sort(key=lambda x: x[0], reverse=True)
    best_path = candidates[0][1]

    try:
        with open(best_path, encoding="utf-8") as f:
            raw = json.load(f)
        ctx = SessionContext.from_dict(raw)
        logger.info("Loaded last session context from %s", best_path)
        return ctx
    except Exception as exc:
        logger.warning("Failed to load session context from %s: %s", best_path, exc)
        return None


# ============================================================================

# Self-test

# ============================================================================


def _run_tests() -> None:
    import traceback as _tb
    import tempfile as _tf

    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name: str, fn: Callable[[], None]) -> None:
        try:
            fn()
            passed.append(name)
        except Exception:
            failed.append((name, _tb.format_exc()))

    # -- normalize_session_type -
    def t_normalize_session_type_canonical() -> None:
        assert normalize_session_type("practice") == SessionType.PRACTICE
        assert normalize_session_type("qualifying") == SessionType.QUALIFYING
        assert normalize_session_type("race") == SessionType.SPRINT_RACE

    _test("normalize_session_type_canonical", t_normalize_session_type_canonical)

    def t_normalize_session_type_short() -> None:
        assert normalize_session_type("prac") == SessionType.PRACTICE
        assert normalize_session_type("q") == SessionType.QUALIFYING
        assert normalize_session_type("r") == SessionType.SPRINT_RACE
        assert normalize_session_type("stint") == SessionType.ENDURANCE_STINT

    _test("normalize_session_type_short", t_normalize_session_type_short)

    def t_normalize_session_type_invalid() -> None:
        try:
            normalize_session_type("banana")
            raise AssertionError("Should have raised ValueError")
        except ValueError:
            pass

    _test("normalize_session_type_invalid", t_normalize_session_type_invalid)

    # -- normalize_track_state -
    def t_normalize_track_state_old_values() -> None:
        assert normalize_track_state("dry") == TrackState.DRY
        assert normalize_track_state("wet") == TrackState.WET
        assert normalize_track_state("damp") == TrackState.DAMP

    _test("normalize_track_state_old_values", t_normalize_track_state_old_values)

    def t_normalize_track_state_french() -> None:
        assert normalize_track_state("sec") == TrackState.DRY
        assert normalize_track_state("mouillé") == TrackState.WET

    _test("normalize_track_state_french", t_normalize_track_state_french)

    # -- WeatherObs -
    def t_weather_validate_ok() -> None:
        w = WeatherObs(air_temp_c=25.0, humidity_pct=60.0, wind_dir_deg=180.0)
        assert w.validate() == []

    _test("weather_validate_ok", t_weather_validate_ok)

    def t_weather_validate_errors() -> None:
        w = WeatherObs(humidity_pct=150.0, wind_dir_deg=-10.0)
        errs = w.validate()
        assert len(errs) == 2

    _test("weather_validate_errors", t_weather_validate_errors)

    # -- SessionContext round-trip -
    def t_context_round_trip() -> None:
        ctx = SessionContext(
            session_id="test-001",
            track_id="spa",
            session_type=SessionType.QUALIFYING,
            baseline_track_state=TrackState.DAMP,
            weather=WeatherObs(air_temp_c=18.0),
            notes="Lap 5 spin",
            reference_lap_times=[65.0, 63.5, 62.0, 61.0],
        )
        d = ctx.to_dict()
        ctx2 = SessionContext.from_dict(d)
        assert ctx2.session_id == "test-001"
        assert ctx2.session_type == SessionType.QUALIFYING
        assert ctx2.baseline_track_state == TrackState.DAMP
        assert ctx2.weather is not None
        assert ctx2.weather.air_temp_c == 18.0
        assert ctx2.notes == "Lap 5 spin"
        assert ctx2.reference_lap_times == [65.0, 63.5, 62.0, 61.0]

    _test("context_round_trip", t_context_round_trip)

    # -- Backward compatibility -
    def t_from_dict_old_format() -> None:
        """Old pipeline used 'track_state' key, not 'baseline_track_state'."""
        ctx = SessionContext.from_dict({
            "session_type": "race",
            "track_state": "wet",
        })
        assert ctx.session_type == SessionType.SPRINT_RACE
        assert ctx.baseline_track_state == TrackState.WET

    _test("from_dict_old_format", t_from_dict_old_format)

    # -- Persistence -
    def t_save_and_load() -> None:
        with _tf.TemporaryDirectory() as tmpdir:
            ctx = SessionContext(
                session_id="persist-001",
                track_id=None,
                session_type=SessionType.PRACTICE,
                baseline_track_state=TrackState.DRY,
            )
            p = Path(tmpdir) / "results" / "run1" / _CONTEXT_FILENAME
            save_session_context(ctx, p)
            assert p.exists()
            loaded = load_last_session_context(Path(tmpdir) / "results")
            assert loaded is not None
            assert loaded.session_id == "persist-001"

    _test("save_and_load", t_save_and_load)

    # -- CLI collection -
    def t_collect_cli() -> None:
        responses = iter([
            "",          # session type (default)
            "drying",    # track state
            "n",         # no weather
            "cold tyres",  # notes
        ])
        ctx = collect_session_context_cli(input_func=lambda _: next(responses))
        assert ctx.session_type == SessionType.PRACTICE
        assert ctx.baseline_track_state == TrackState.DRYING
        assert ctx.notes == "cold tyres"

    _test("collect_cli", t_collect_cli)

    # -- Summary -
    total = len(passed) + len(failed)
    print(f"\nSession Context Tests: {len(passed)}/{total} passed")
    for n in passed:
        print(f"  âœ“ {n}")
    for n, tb in failed:
        print(f"  âœ— {n}\n{tb}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()
