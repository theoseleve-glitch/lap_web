# Meteo Deep Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Integrate per-lap weather data into the analysis pipeline so every session is scored against condition-adjusted theoreticals, a new Adaptation grade (/15) is added, the race strategy dashboard gets rain alerts, and reports show condition timelines.

**Architecture:** New `weather_timeline.py` module interpolates hourly Open-Meteo data to per-lap resolution. Pipeline step 8e produces a `weather_timeline` DataFrame that flows into scoring (new `_score_adaptation`), theoretical engine (grip-scaled + blended envelope), race strategy (alerts via forecast polling), and report generation (5 new optional sections). All new features degrade gracefully when weather data is unavailable.

**Tech Stack:** Python 3.x, pandas, numpy, Open-Meteo free API (urllib), Flask, Jinja2 templates, matplotlib (reports), Next.js/TypeScript (frontend), SQLite + PostgreSQL (Alembic migration 017).

**Design doc:** `docs/plans/2026-02-27-meteo-deep-integration-design.md`

---

## Task 1: Weather Timeline Module — Core Interpolation

**Files:**
- Create: `telemetry_tool/weather_timeline.py`
- Test: `telemetry_tool/tests/test_weather_timeline.py`

**Step 1: Write the failing tests**

```python
# telemetry_tool/tests/test_weather_timeline.py
"""Tests for weather_timeline module."""
import sys
from pathlib import Path
from datetime import datetime

import pandas as pd
import pytest

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from telemetry_tool.weather_timeline import build_weather_timeline


@pytest.fixture
def two_hour_weather():
    """Hourly weather with 2 data points: 14:00 and 15:00."""
    return {
        "date": "2026-02-15",
        "hours": [
            {
                "time": "2026-02-15T14:00",
                "air_temp_c": 20.0,
                "humidity_pct": 60.0,
                "wind_speed_mps": 3.0,
                "wind_dir_deg": 180.0,
                "rain_mm": 0.0,
                "cloud_cover_pct": 20.0,
                "weather_code": 1,
            },
            {
                "time": "2026-02-15T15:00",
                "air_temp_c": 18.0,
                "humidity_pct": 70.0,
                "wind_speed_mps": 5.0,
                "wind_dir_deg": 200.0,
                "rain_mm": 2.0,
                "cloud_cover_pct": 80.0,
                "weather_code": 61,
            },
        ],
        "source": "open-meteo-archive",
    }


class TestBuildWeatherTimeline:
    def test_interpolation_between_hours(self, two_hour_weather):
        """Lap at 14:30 should get midpoint values."""
        # 3 laps: at 0s (14:00), 1800s (14:30), 3600s (15:00)
        lap_timestamps = [0.0, 1800.0, 3600.0]
        session_start = datetime(2026, 2, 15, 14, 0, 0)

        result = build_weather_timeline(two_hour_weather, lap_timestamps, session_start)

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 3
        # Lap 2 (14:30) should be midpoint: (20+18)/2 = 19.0
        assert abs(result.iloc[1]["air_temp_c"] - 19.0) < 0.1
        # Humidity midpoint: (60+70)/2 = 65
        assert abs(result.iloc[1]["humidity_pct"] - 65.0) < 0.1

    def test_nearest_weather_code(self, two_hour_weather):
        """WMO codes use nearest-hour, not interpolation."""
        lap_timestamps = [0.0, 1500.0, 2100.0, 3600.0]
        session_start = datetime(2026, 2, 15, 14, 0, 0)

        result = build_weather_timeline(two_hour_weather, lap_timestamps, session_start)

        # Lap at 1500s (14:25) -> nearest to 14:00, code=1
        assert result.iloc[1]["weather_code"] == 1
        # Lap at 2100s (14:35) -> nearest to 15:00, code=61
        assert result.iloc[2]["weather_code"] == 61

    def test_grip_score_computed(self, two_hour_weather):
        """Each lap should have grip_score and track_state."""
        lap_timestamps = [0.0, 3600.0]
        session_start = datetime(2026, 2, 15, 14, 0, 0)

        result = build_weather_timeline(two_hour_weather, lap_timestamps, session_start)

        assert "grip_score" in result.columns
        assert "track_state" in result.columns
        # First lap: no rain -> dry
        assert result.iloc[0]["track_state"] == "dry"
        # Last lap: 2mm rain -> damp
        assert result.iloc[1]["track_state"] == "damp"

    def test_empty_lap_timestamps(self, two_hour_weather):
        """Empty laps -> empty DataFrame with correct columns."""
        session_start = datetime(2026, 2, 15, 14, 0, 0)
        result = build_weather_timeline(two_hour_weather, [], session_start)

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0
        assert "air_temp_c" in result.columns

    def test_single_hour_session(self):
        """Session within a single hour -> all laps get that hour's values."""
        weather = {
            "hours": [
                {
                    "time": "2026-02-15T14:00",
                    "air_temp_c": 22.0,
                    "humidity_pct": 55.0,
                    "wind_speed_mps": 2.0,
                    "wind_dir_deg": 90.0,
                    "rain_mm": 0.0,
                    "cloud_cover_pct": 10.0,
                    "weather_code": 0,
                },
            ],
        }
        lap_timestamps = [0.0, 120.0, 240.0]
        session_start = datetime(2026, 2, 15, 14, 0, 0)

        result = build_weather_timeline(weather, lap_timestamps, session_start)

        assert len(result) == 3
        # All laps should have the same temp
        assert all(abs(result["air_temp_c"] - 22.0) < 0.01)

    def test_missing_weather_fields_graceful(self):
        """Missing optional fields don't crash."""
        weather = {
            "hours": [
                {"time": "2026-02-15T14:00", "air_temp_c": 20.0},
            ],
        }
        lap_timestamps = [0.0, 120.0]
        session_start = datetime(2026, 2, 15, 14, 0, 0)

        result = build_weather_timeline(weather, lap_timestamps, session_start)

        assert len(result) == 2
        assert result.iloc[0]["air_temp_c"] == 20.0

    def test_has_expected_columns(self, two_hour_weather):
        """Output DataFrame has all required columns."""
        lap_timestamps = [0.0, 1800.0]
        session_start = datetime(2026, 2, 15, 14, 0, 0)

        result = build_weather_timeline(two_hour_weather, lap_timestamps, session_start)

        expected_cols = {
            "lap_number", "timestamp", "air_temp_c", "humidity_pct",
            "wind_speed_mps", "wind_dir_deg", "rain_mm", "cloud_cover_pct",
            "weather_code", "grip_score", "track_state", "track_temp_est_c",
        }
        assert expected_cols.issubset(set(result.columns))
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_weather_timeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'telemetry_tool.weather_timeline'`

**Step 3: Write minimal implementation**

```python
# telemetry_tool/weather_timeline.py
"""
weather_timeline.py
-------------------
Interpolate hourly weather data to per-lap resolution for session analysis.

Public API
~~~~~~~~~~
``build_weather_timeline(hourly_weather, lap_timestamps, session_start)``
    Interpolate hourly weather to per-lap resolution.
``parse_session_datetime(csv_path)``
    Extract session date/time from CSV metadata.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_TIMELINE_COLUMNS: Final[list[str]] = [
    "lap_number", "timestamp", "air_temp_c", "humidity_pct",
    "wind_speed_mps", "wind_dir_deg", "rain_mm", "cloud_cover_pct",
    "weather_code", "grip_score", "track_state", "track_temp_est_c",
]

# Continuous variables that can be linearly interpolated
_INTERP_FIELDS: Final[list[str]] = [
    "air_temp_c", "humidity_pct", "wind_speed_mps", "wind_dir_deg",
    "rain_mm", "cloud_cover_pct",
]


def build_weather_timeline(
    hourly_weather: dict[str, Any],
    lap_timestamps: list[float],
    session_start: datetime,
) -> pd.DataFrame:
    """
    Interpolate hourly weather to per-lap resolution.

    Parameters
    ----------
    hourly_weather : dict
        Output of ``meteo_service.fetch_historical_weather()``.
        Must have ``hours`` key with list of hourly dicts.
    lap_timestamps : list[float]
        Cumulative seconds from session start for each lap.
    session_start : datetime
        Absolute start time of the session.

    Returns
    -------
    pd.DataFrame
        Indexed by position with columns: lap_number, timestamp,
        air_temp_c, humidity_pct, wind_speed_mps, wind_dir_deg,
        rain_mm, cloud_cover_pct, weather_code, grip_score,
        track_state, track_temp_est_c.
    """
    if not lap_timestamps:
        return pd.DataFrame(columns=_TIMELINE_COLUMNS)

    hours = hourly_weather.get("hours", [])
    if not hours:
        return pd.DataFrame(columns=_TIMELINE_COLUMNS)

    # Parse hourly timestamps to seconds-from-session-start
    hour_offsets: list[float] = []
    hour_data: list[dict] = []
    for h in hours:
        try:
            t_str = h.get("time", "")
            # Handle both "2026-02-15T14:00" and "2026-02-15T14:00:00"
            for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
                try:
                    t = datetime.strptime(t_str, fmt)
                    break
                except ValueError:
                    continue
            else:
                continue
            offset_s = (t - session_start).total_seconds()
            hour_offsets.append(offset_s)
            hour_data.append(h)
        except Exception:
            continue

    if not hour_data:
        return pd.DataFrame(columns=_TIMELINE_COLUMNS)

    rows: list[dict[str, Any]] = []
    for i, lap_s in enumerate(lap_timestamps):
        lap_time = session_start + timedelta(seconds=lap_s)
        row: dict[str, Any] = {
            "lap_number": i + 1,
            "timestamp": lap_time.isoformat(),
        }

        # Interpolate continuous fields
        for field in _INTERP_FIELDS:
            row[field] = _interpolate_field(
                lap_s, hour_offsets, hour_data, field,
            )

        # Nearest-hour for categorical weather_code
        row["weather_code"] = _nearest_value(
            lap_s, hour_offsets, hour_data, "weather_code", default=0,
        )

        # Compute track conditions from interpolated weather
        from meteo_service import estimate_track_conditions
        conditions = estimate_track_conditions(row)
        if "error" not in conditions:
            row["grip_score"] = conditions.get("grip_score")
            row["track_state"] = conditions.get("track_state", "dry")
            row["track_temp_est_c"] = conditions.get("track_temp_est_c")
        else:
            row["grip_score"] = None
            row["track_state"] = "dry"
            row["track_temp_est_c"] = None

        rows.append(row)

    df = pd.DataFrame(rows)
    # Ensure all expected columns exist
    for col in _TIMELINE_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[_TIMELINE_COLUMNS]


def _interpolate_field(
    target_s: float,
    offsets: list[float],
    data: list[dict],
    field: str,
) -> Optional[float]:
    """Linearly interpolate a field between hourly data points."""
    values = [d.get(field) for d in data]
    # Find bracketing indices
    if len(offsets) == 1:
        return values[0]

    # Before first point -> use first value
    if target_s <= offsets[0]:
        return values[0]
    # After last point -> use last value
    if target_s >= offsets[-1]:
        return values[-1]

    # Find bracketing pair
    for j in range(len(offsets) - 1):
        if offsets[j] <= target_s <= offsets[j + 1]:
            v0 = values[j]
            v1 = values[j + 1]
            if v0 is None or v1 is None:
                return v0 if v0 is not None else v1
            span = offsets[j + 1] - offsets[j]
            if span == 0:
                return v0
            frac = (target_s - offsets[j]) / span
            return v0 + frac * (v1 - v0)

    return values[-1]


def _nearest_value(
    target_s: float,
    offsets: list[float],
    data: list[dict],
    field: str,
    default: Any = None,
) -> Any:
    """Return field value from the nearest hourly data point."""
    if not offsets:
        return default
    dists = [abs(target_s - o) for o in offsets]
    idx = dists.index(min(dists))
    return data[idx].get(field, default)
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_weather_timeline.py -v`
Expected: All 7 tests PASS

**Step 5: Commit**

```bash
git add telemetry_tool/weather_timeline.py telemetry_tool/tests/test_weather_timeline.py
git commit -m "feat(meteo): add weather_timeline module with per-lap interpolation"
```

---

## Task 2: Session DateTime Extraction

**Files:**
- Modify: `telemetry_tool/weather_timeline.py`
- Test: `telemetry_tool/tests/test_weather_timeline.py` (append)

**Step 1: Write failing tests**

Append to `test_weather_timeline.py`:

```python
from telemetry_tool.weather_timeline import parse_session_datetime
import tempfile
import os


class TestParseSessionDatetime:
    def test_racechrono_date_header(self, tmp_path):
        """RaceChrono CSV with '# Date:' header."""
        csv = tmp_path / "session.csv"
        csv.write_text(
            "# RaceChrono Pro\n"
            "# Date: 2026-02-15\n"
            "# Time: 14:05:30\n"
            "Time (s),Speed (m/s)\n"
            "0.0,15.2\n"
        )
        result = parse_session_datetime(csv)
        assert result is not None
        assert result.year == 2026
        assert result.month == 2
        assert result.day == 15
        assert result.hour == 14
        assert result.minute == 5

    def test_date_only_no_time(self, tmp_path):
        """CSV with date but no time header -> date at midnight."""
        csv = tmp_path / "session.csv"
        csv.write_text(
            "# Date: 2026-03-10\n"
            "Time (s),Speed (m/s)\n"
            "0.0,15.2\n"
        )
        result = parse_session_datetime(csv)
        assert result is not None
        assert result.year == 2026
        assert result.month == 3
        assert result.hour == 0

    def test_no_metadata_returns_none(self, tmp_path):
        """CSV with no date headers -> None."""
        csv = tmp_path / "session.csv"
        csv.write_text(
            "Time (s),Speed (m/s)\n"
            "0.0,15.2\n"
        )
        result = parse_session_datetime(csv)
        assert result is None

    def test_racebox_timestamp_header(self, tmp_path):
        """RaceBox CSV with ISO timestamp in first line."""
        csv = tmp_path / "session.csv"
        csv.write_text(
            "# Session: 2026-02-20T09:30:00Z\n"
            "Time (s),Speed (m/s)\n"
            "0.0,10.0\n"
        )
        result = parse_session_datetime(csv)
        assert result is not None
        assert result.day == 20
        assert result.hour == 9
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_weather_timeline.py::TestParseSessionDatetime -v`
Expected: FAIL with `ImportError`

**Step 3: Add `parse_session_datetime` to `weather_timeline.py`**

Add at bottom of `weather_timeline.py`, before any `if __name__` block:

```python
def parse_session_datetime(csv_path: Path) -> Optional[datetime]:
    """
    Extract session date/time from CSV metadata headers.

    Priority order:
    1. RaceChrono ``# Date:`` / ``# Time:`` comment headers (first 30 lines)
    2. ISO-8601 timestamp in comment lines (``# Session: 2026-02-20T09:30:00Z``)
    3. None (caller must prompt user or use file mtime)

    Parameters
    ----------
    csv_path : Path
        Path to the CSV file.

    Returns
    -------
    datetime or None
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        return None

    date_str: Optional[str] = None
    time_str: Optional[str] = None

    try:
        with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= 30:
                    break
                stripped = line.strip()
                if not stripped.startswith("#"):
                    continue
                content = stripped.lstrip("#").strip()

                # Try "Date: YYYY-MM-DD"
                if content.lower().startswith("date:"):
                    date_str = content.split(":", 1)[1].strip()
                elif content.lower().startswith("time:"):
                    time_str = content.split(":", 1)[1].strip()
                # Try "Session: ISO-8601"
                elif content.lower().startswith("session:"):
                    iso_str = content.split(":", 1)[1].strip()
                    try:
                        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
                        return dt.replace(tzinfo=None)
                    except ValueError:
                        pass
    except Exception as exc:
        logger.warning("Failed to read CSV headers for datetime: %s", exc)
        return None

    if date_str:
        try:
            if time_str:
                return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
            return datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            pass

    return None
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_weather_timeline.py -v`
Expected: All 11 tests PASS

**Step 5: Commit**

```bash
git add telemetry_tool/weather_timeline.py telemetry_tool/tests/test_weather_timeline.py
git commit -m "feat(meteo): add parse_session_datetime for CSV metadata extraction"
```

---

## Task 3: DB Schema — `session_weather_laps` Table

**Files:**
- Modify: `telemetry_tool/db/schema.py` (lines 926-929)
- Create: `telemetry_tool/alembic/versions/017_session_weather_laps.py`

**Step 1: Add table definition to SQLite schema**

In `telemetry_tool/db/schema.py`, after `_RACE_RIVAL_EVENTS_TABLE` (line 920) and `PHASE_17_TABLES` (line 926), add:

```python
# -- Phase 18: Weather timeline per-lap data -------------------------

_SESSION_WEATHER_LAPS_TABLE = """
CREATE TABLE IF NOT EXISTS session_weather_laps (
    session_id      TEXT    NOT NULL,
    lap_number      INTEGER NOT NULL,
    timestamp       TEXT,
    air_temp_c      REAL,
    humidity_pct    REAL,
    wind_speed_mps  REAL,
    wind_dir_deg    REAL,
    rain_mm         REAL,
    cloud_cover_pct REAL,
    weather_code    INTEGER,
    grip_score      REAL,
    track_state     TEXT,
    track_temp_est_c REAL,
    PRIMARY KEY (session_id, lap_number)
);
"""

PHASE_18_TABLES: list[tuple[str, str]] = [
    ("session_weather_laps", _SESSION_WEATHER_LAPS_TABLE),
]
```

Update `ALL_TABLES` on line 929 to append `+ PHASE_18_TABLES`.

Update `SCHEMA_VERSION` to `25`.

**Step 2: Add `session_datetime` column to sessions table**

Find the `_SESSIONS_TABLE` definition in schema.py and add `session_datetime TEXT` column.
If the column already exists in the CREATE TABLE, skip. Otherwise, add it to `ensure_schema()` via ALTER TABLE fallback.

**Step 3: Create Alembic migration for PostgreSQL**

```python
# telemetry_tool/alembic/versions/017_session_weather_laps.py
"""session_weather_laps table and session_datetime column

Revision ID: 017
Revises: 016
"""
from alembic import op
import sqlalchemy as sa

revision = "017"
down_revision = "016"


def upgrade():
    op.create_table(
        "session_weather_laps",
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("lap_number", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.Text()),
        sa.Column("air_temp_c", sa.Float()),
        sa.Column("humidity_pct", sa.Float()),
        sa.Column("wind_speed_mps", sa.Float()),
        sa.Column("wind_dir_deg", sa.Float()),
        sa.Column("rain_mm", sa.Float()),
        sa.Column("cloud_cover_pct", sa.Float()),
        sa.Column("weather_code", sa.Integer()),
        sa.Column("grip_score", sa.Float()),
        sa.Column("track_state", sa.Text()),
        sa.Column("track_temp_est_c", sa.Float()),
        sa.Column("workspace_id", sa.Text()),
        sa.PrimaryKeyConstraint("session_id", "lap_number"),
    )

    # RLS policy
    op.execute(
        "ALTER TABLE session_weather_laps ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "CREATE POLICY session_weather_laps_tenant ON session_weather_laps "
        "USING (workspace_id = current_setting('app.workspace_id', true))"
    )

    # Add session_datetime to sessions
    op.add_column("sessions", sa.Column("session_datetime", sa.Text()))


def downgrade():
    op.drop_column("sessions", "session_datetime")
    op.execute("DROP POLICY IF EXISTS session_weather_laps_tenant ON session_weather_laps")
    op.drop_table("session_weather_laps")
```

**Step 4: Verify**

Run: `pytest telemetry_tool/tests/ -k "test_db or test_schema" -v --timeout=30`
Expected: Existing DB tests still pass (ensure_schema creates Phase 18 table in new DBs).

**Step 5: Commit**

```bash
git add telemetry_tool/db/schema.py telemetry_tool/alembic/versions/017_session_weather_laps.py
git commit -m "feat(meteo): add session_weather_laps table (schema phase 18, alembic 017)"
```

---

## Task 4: Grip-Scaled Theoretical Lap

**Files:**
- Modify: `telemetry_tool/theoretical_engine.py`
- Test: `telemetry_tool/tests/test_theoretical_grip_scaling.py` (new)

**Step 1: Write failing tests**

```python
# telemetry_tool/tests/test_theoretical_grip_scaling.py
"""Tests for grip-scaled theoretical lap."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from telemetry_tool.theoretical_engine import scale_theoretical_by_grip, get_phase_theoreticals


@pytest.fixture
def dry_theoretical():
    """A simple dry theoretical lap DataFrame."""
    return pd.DataFrame({
        "distance_m": [0.0, 100.0, 200.0, 300.0],
        "v_env_mps": [30.0, 40.0, 20.0, 35.0],
        "accel_max_mps2": [5.0, 4.0, 6.0, 3.0],
        "brake_max_mps2": [-8.0, -7.0, -9.0, -6.0],
    })


class TestScaleTheoreticalByGrip:
    def test_grip_factor_1_identity(self, dry_theoretical):
        """Grip factor 1.0 (dry) should return identical values."""
        result = scale_theoretical_by_grip(dry_theoretical, 1.0)
        pd.testing.assert_frame_equal(result, dry_theoretical, atol=1e-6)

    def test_grip_factor_scales_speed_by_sqrt(self, dry_theoretical):
        """Speed scales as v * sqrt(grip_factor)."""
        result = scale_theoretical_by_grip(dry_theoretical, 0.64)
        # sqrt(0.64) = 0.8
        expected_speed = dry_theoretical["v_env_mps"] * 0.8
        np.testing.assert_allclose(result["v_env_mps"], expected_speed, atol=1e-6)

    def test_grip_factor_scales_accel_linearly(self, dry_theoretical):
        """Accel scales as a * grip_factor."""
        result = scale_theoretical_by_grip(dry_theoretical, 0.5)
        expected_accel = dry_theoretical["accel_max_mps2"] * 0.5
        np.testing.assert_allclose(result["accel_max_mps2"], expected_accel, atol=1e-6)

    def test_grip_factor_scales_braking_linearly(self, dry_theoretical):
        """Braking scales as b * grip_factor (preserves negative sign)."""
        result = scale_theoretical_by_grip(dry_theoretical, 0.5)
        expected_brake = dry_theoretical["brake_max_mps2"] * 0.5
        np.testing.assert_allclose(result["brake_max_mps2"], expected_brake, atol=1e-6)

    def test_distance_unchanged(self, dry_theoretical):
        """Distance column should not change."""
        result = scale_theoretical_by_grip(dry_theoretical, 0.5)
        pd.testing.assert_series_equal(
            result["distance_m"], dry_theoretical["distance_m"],
        )

    def test_returns_copy(self, dry_theoretical):
        """Should return a new DataFrame, not modify the original."""
        original_speed = dry_theoretical["v_env_mps"].copy()
        _ = scale_theoretical_by_grip(dry_theoretical, 0.5)
        pd.testing.assert_series_equal(
            dry_theoretical["v_env_mps"], original_speed,
        )

    def test_grip_factor_clamped(self, dry_theoretical):
        """Grip factors outside [0,1] should be clamped."""
        result_over = scale_theoretical_by_grip(dry_theoretical, 1.5)
        pd.testing.assert_frame_equal(result_over, dry_theoretical, atol=1e-6)

        result_under = scale_theoretical_by_grip(dry_theoretical, -0.1)
        assert all(result_under["v_env_mps"] == 0.0)


class TestGetPhaseTheoreticals:
    def test_returns_dict_per_phase(self, dry_theoretical):
        """Should return one theoretical per unique phase."""
        weather_tl = pd.DataFrame({
            "lap_number": [1, 2, 3, 4, 5, 6],
            "grip_score": [90, 90, 90, 60, 60, 60],
        })
        phases = pd.DataFrame({
            "phase_id": [0, 1],
            "lap_start": [1, 4],
            "lap_end": [3, 6],
        })
        result = get_phase_theoreticals(dry_theoretical, weather_tl, phases)

        assert isinstance(result, dict)
        assert 0 in result
        assert 1 in result
        # Phase 0 (grip=90) should have higher speeds than Phase 1 (grip=60)
        assert result[0]["v_env_mps"].mean() > result[1]["v_env_mps"].mean()
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_theoretical_grip_scaling.py -v`
Expected: FAIL with `ImportError`

**Step 3: Add functions to `theoretical_engine.py`**

Add before the inline tests section (or at end of public API section):

```python
def scale_theoretical_by_grip(
    theoretical_df: pd.DataFrame,
    grip_factor: float,
) -> pd.DataFrame:
    """
    Apply physics-based grip scaling to a dry theoretical lap.

    Speed: v_scaled = v_dry * sqrt(grip_factor)
    Accel: a_scaled = a_dry * grip_factor
    Braking: b_scaled = b_dry * grip_factor

    Parameters
    ----------
    theoretical_df : pd.DataFrame
        Dry theoretical with columns: distance_m, v_env_mps,
        accel_max_mps2, brake_max_mps2.
    grip_factor : float
        0.0-1.0 from grip_score / 100. Clamped to [0, 1].

    Returns
    -------
    pd.DataFrame with scaled columns (new copy, original unchanged).
    """
    grip_factor = max(0.0, min(1.0, grip_factor))
    result = theoretical_df.copy()
    sqrt_grip = math.sqrt(grip_factor)
    result[_OUT_SPEED] = theoretical_df[_OUT_SPEED] * sqrt_grip
    result[_OUT_ACCEL] = theoretical_df[_OUT_ACCEL] * grip_factor
    result[_OUT_BRAKE] = theoretical_df[_OUT_BRAKE] * grip_factor
    return result


def get_phase_theoreticals(
    dry_theoretical: pd.DataFrame,
    weather_timeline: pd.DataFrame,
    phases_df: pd.DataFrame,
) -> dict[int, pd.DataFrame]:
    """
    Compute a grip-scaled theoretical for each condition phase.

    Parameters
    ----------
    dry_theoretical : pd.DataFrame
        The baseline dry theoretical lap.
    weather_timeline : pd.DataFrame
        Per-lap weather with ``lap_number`` and ``grip_score`` columns.
    phases_df : pd.DataFrame
        With ``phase_id``, ``lap_start``, ``lap_end`` columns.

    Returns
    -------
    dict[int, pd.DataFrame]
        {phase_id: scaled_theoretical_df}
    """
    result: dict[int, pd.DataFrame] = {}
    for _, phase in phases_df.iterrows():
        pid = int(phase["phase_id"])
        lap_start = int(phase["lap_start"])
        lap_end = int(phase["lap_end"])

        # Get average grip for laps in this phase
        mask = (
            (weather_timeline["lap_number"] >= lap_start)
            & (weather_timeline["lap_number"] <= lap_end)
        )
        phase_weather = weather_timeline.loc[mask]
        if phase_weather.empty:
            result[pid] = dry_theoretical.copy()
            continue

        avg_grip = phase_weather["grip_score"].mean()
        if avg_grip is None or math.isnan(avg_grip):
            result[pid] = dry_theoretical.copy()
            continue

        grip_factor = avg_grip / 100.0
        result[pid] = scale_theoretical_by_grip(dry_theoretical, grip_factor)

    return result
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_theoretical_grip_scaling.py -v`
Expected: All 9 tests PASS

**Step 5: Commit**

```bash
git add telemetry_tool/theoretical_engine.py telemetry_tool/tests/test_theoretical_grip_scaling.py
git commit -m "feat(meteo): add grip-scaled theoretical lap + per-phase theoreticals"
```

---

## Task 5: Adaptation Scoring Grade

**Files:**
- Modify: `telemetry_tool/scoring.py` (lines 66-70 constants, lines 331-336 grades, lines 1379 loop, lines 1708-1777 adaptation)
- Test: `telemetry_tool/tests/test_scoring_adaptation.py` (new)

**Step 1: Write failing tests**

```python
# telemetry_tool/tests/test_scoring_adaptation.py
"""Tests for the upgraded Adaptation scoring grade."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from telemetry_tool.scoring import (
    MAX_PACE, MAX_CONSISTENCY, MAX_EXECUTION, MAX_ROBUSTNESS,
    TOTAL_MAX, _score_adaptation_v2,
)


class TestScoreWeights:
    def test_weights_sum_to_100(self):
        """All category maximums must sum to TOTAL_MAX (100)."""
        from telemetry_tool.scoring import MAX_ADAPTATION
        total = MAX_PACE + MAX_CONSISTENCY + MAX_EXECUTION + MAX_ROBUSTNESS + MAX_ADAPTATION
        assert total == TOTAL_MAX == 100.0

    def test_new_weights(self):
        from telemetry_tool.scoring import MAX_ADAPTATION
        assert MAX_PACE == 25.0
        assert MAX_CONSISTENCY == 25.0
        assert MAX_EXECUTION == 20.0
        assert MAX_ROBUSTNESS == 15.0
        assert MAX_ADAPTATION == 15.0


class TestScoreAdaptationV2:
    @pytest.fixture
    def multi_phase_data(self):
        """Session with 2 phases: dry (laps 1-5) -> damp (laps 6-10)."""
        weather_tl = pd.DataFrame({
            "lap_number": list(range(1, 11)),
            "grip_score": [90]*5 + [60]*5,
            "track_state": ["dry"]*5 + ["damp"]*5,
        })
        phases = pd.DataFrame({
            "phase_id": [0, 1],
            "lap_start": [1, 6],
            "lap_end": [5, 10],
            "n_laps": [5, 5],
        })
        # Driver adapts quickly: lap times increase at transition then stabilize
        lap_metrics = [
            {"lap_number": i, "lap_time_s": t, "jerk_rms_mps3": j,
             "braking_max_mps2": b, "line_length_m": l}
            for i, t, j, b, l in [
                (1, 48.0, 5.0, -8.0, 500.0),
                (2, 47.5, 5.1, -8.1, 501.0),
                (3, 47.3, 5.0, -7.9, 499.0),
                (4, 47.2, 5.0, -8.0, 500.0),
                (5, 47.4, 5.0, -8.0, 500.0),
                # Transition: lap 6-7 unstable, 8-10 adapted
                (6, 52.0, 4.0, -6.5, 510.0),  # wet: lower jerk, less braking, wider line
                (7, 51.0, 3.8, -6.3, 512.0),
                (8, 50.5, 3.5, -6.0, 515.0),
                (9, 50.3, 3.4, -6.0, 514.0),
                (10, 50.2, 3.5, -6.1, 513.0),
            ]
        ]
        theo_metrics = {"best_s": 46.5, "speed_mean_mps": 30.0}
        return weather_tl, phases, lap_metrics, theo_metrics

    def test_multi_phase_returns_score(self, multi_phase_data):
        weather_tl, phases, lap_metrics, theo_metrics = multi_phase_data
        result = _score_adaptation_v2(
            weather_timeline=weather_tl,
            lap_metrics_df=pd.DataFrame(lap_metrics),
            phases_df=phases,
            track_evolution=None,
            theoretical_metrics=theo_metrics,
            simulation_method="physics",
        )
        assert "score" in result
        assert 0 <= result["score"] <= 15.0

    def test_stable_session_neutral(self):
        """Single phase with no evolution -> 75% of max."""
        weather_tl = pd.DataFrame({
            "lap_number": [1, 2, 3, 4, 5],
            "grip_score": [90]*5,
            "track_state": ["dry"]*5,
        })
        phases = pd.DataFrame({
            "phase_id": [0],
            "lap_start": [1],
            "lap_end": [5],
            "n_laps": [5],
        })
        lap_metrics = [
            {"lap_number": i, "lap_time_s": 48.0 + i*0.1}
            for i in range(1, 6)
        ]
        result = _score_adaptation_v2(
            weather_timeline=weather_tl,
            lap_metrics_df=pd.DataFrame(lap_metrics),
            phases_df=phases,
            track_evolution={"total_evolution_pct": 0.5, "grip_trend": "stable"},
            theoretical_metrics={"best_s": 47.0},
            simulation_method="physics",
        )
        from telemetry_tool.scoring import MAX_ADAPTATION
        # Should be approximately 75% of max
        expected = 0.75 * MAX_ADAPTATION
        assert abs(result["score"] - expected) < 1.0

    def test_correct_technique_direction_scores_higher(self, multi_phase_data):
        """Driver with correct wet adaptation (smoother, wider) scores higher."""
        weather_tl, phases, lap_metrics, theo_metrics = multi_phase_data
        result = _score_adaptation_v2(
            weather_timeline=weather_tl,
            lap_metrics_df=pd.DataFrame(lap_metrics),
            phases_df=phases,
            track_evolution=None,
            theoretical_metrics=theo_metrics,
            simulation_method="physics",
        )
        # The test data has correct adaptation: lower jerk, less braking, wider line in wet
        assert result.get("technique_adaptation_score", 0) > 0

    def test_none_weather_returns_neutral(self):
        """No weather timeline -> neutral adaptation score."""
        result = _score_adaptation_v2(
            weather_timeline=None,
            lap_metrics_df=pd.DataFrame(),
            phases_df=None,
            track_evolution=None,
            theoretical_metrics={},
            simulation_method="physics",
        )
        from telemetry_tool.scoring import MAX_ADAPTATION
        assert abs(result["score"] - 0.75 * MAX_ADAPTATION) < 1.0
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_scoring_adaptation.py -v`
Expected: FAIL with `ImportError: cannot import name 'MAX_ADAPTATION'`

**Step 3: Modify `scoring.py`**

Changes needed (in order):

1. **Lines 66-70**: Update weight constants
```python
MAX_PACE:        Final[float] = 25.0   # was 30
MAX_CONSISTENCY: Final[float] = 25.0   # unchanged
MAX_EXECUTION:   Final[float] = 20.0   # was 25
MAX_ROBUSTNESS:  Final[float] = 15.0   # was 20
MAX_ADAPTATION:  Final[float] = 15.0   # NEW
TOTAL_MAX:       Final[float] = MAX_PACE + MAX_CONSISTENCY + MAX_EXECUTION + MAX_ROBUSTNESS + MAX_ADAPTATION
```

2. **Lines 331-336**: Update grade thresholds
```python
GRADE_S: Final[float] = 90.0   # was 92
GRADE_A: Final[float] = 78.0   # was 80
GRADE_B: Final[float] = 63.0   # was 65
GRADE_C: Final[float] = 48.0   # was 50
GRADE_D: Final[float] = 33.0   # was 35
```

3. **Add adaptation constants** (after ADAPT_W_INTRA_PHASE, ~line 240):
```python
# -- Adaptation v2 scoring constants (weather-aware) --

ADAPT_V2_TRANSITION_FULL_LAPS: Final[float] = 2.0
ADAPT_V2_TRANSITION_ZERO_LAPS: Final[float] = 8.0
ADAPT_V2_TRANSITION_WEIGHT:    Final[float] = 0.40

ADAPT_V2_PHASE_PACE_FULL_PCT:  Final[float] = 3.0
ADAPT_V2_PHASE_PACE_ZERO_PCT:  Final[float] = 12.0
ADAPT_V2_PHASE_PACE_WEIGHT:    Final[float] = 0.35

ADAPT_V2_TECHNIQUE_WEIGHT:     Final[float] = 0.25
ADAPT_V2_STABLE_DEFAULT_FRAC:  Final[float] = 0.75

ADAPT_V2_DECAY_EXP:            Final[float] = 1.4
```

4. **Lines 1367-1395**: Add "adaptation" to the labels dict and loop:
```python
labels = {
    "pace":        "Pace",
    "consistency": "Consistency",
    "execution":   "Execution Quality",
    "robustness":  "Racecraft / Endurance Robustness",
    "adaptation":  "Condition Adaptation",
}
# ... in the loop:
for cat in ("pace", "consistency", "execution", "robustness", "adaptation"):
```

5. **Add `_score_adaptation_v2` function** (after `_compute_adaptation_score`, ~line 1778):

```python
def _score_adaptation_v2(
    *,
    weather_timeline: Optional[pd.DataFrame],
    lap_metrics_df: pd.DataFrame,
    phases_df: Optional[pd.DataFrame],
    track_evolution: Optional[dict[str, Any]],
    theoretical_metrics: dict[str, Any],
    simulation_method: str,
) -> dict[str, Any]:
    """
    Score driver adaptation to changing conditions (weather-aware).

    Three sub-metrics:
    1. Transition Speed (40%): laps to stabilize after condition change
    2. Phase-Relative Pace (35%): gap to condition-adjusted theoretical
    3. Condition-Appropriate Execution (25%): technique adaptation direction

    Returns dict with score (0-MAX_ADAPTATION), sub-scores, details.
    """
    neutral = {
        "score": round(ADAPT_V2_STABLE_DEFAULT_FRAC * MAX_ADAPTATION, 4),
        "transition_speed_score": 0.0,
        "phase_pace_score": 0.0,
        "technique_adaptation_score": 0.0,
        "details": {"reason": "neutral_default"},
    }

    # No weather data -> neutral
    if weather_timeline is None or (isinstance(weather_timeline, pd.DataFrame) and weather_timeline.empty):
        return neutral

    # No phases or single phase
    if phases_df is None or len(phases_df) < 2:
        # Check track evolution for single-phase scoring
        if (track_evolution is not None
                and abs(track_evolution.get("total_evolution_pct", 0.0)) >= ADAPT_MIN_EVOLUTION_PCT):
            return _score_adaptation_evolution(
                lap_metrics_df, track_evolution, theoretical_metrics,
            )
        return neutral

    if lap_metrics_df is None or lap_metrics_df.empty:
        return neutral

    # --- Sub-metric 1: Transition Speed ---
    transition_score = _score_transition_speed(lap_metrics_df, phases_df)

    # --- Sub-metric 2: Phase-Relative Pace ---
    phase_pace_score = _score_phase_relative_pace(
        lap_metrics_df, phases_df, weather_timeline, theoretical_metrics,
    )

    # --- Sub-metric 3: Condition-Appropriate Execution ---
    technique_score = _score_technique_adaptation(
        lap_metrics_df, phases_df, weather_timeline,
    )

    # Combine
    raw = (
        ADAPT_V2_TRANSITION_WEIGHT * transition_score
        + ADAPT_V2_PHASE_PACE_WEIGHT * phase_pace_score
        + ADAPT_V2_TECHNIQUE_WEIGHT * technique_score
    )
    score = raw * MAX_ADAPTATION

    return {
        "score": round(max(0.0, min(MAX_ADAPTATION, score)), 4),
        "transition_speed_score": round(transition_score, 4),
        "phase_pace_score": round(phase_pace_score, 4),
        "technique_adaptation_score": round(technique_score, 4),
        "details": {
            "n_phases": len(phases_df),
            "has_weather": True,
        },
    }
```

Then implement the three helper functions: `_score_transition_speed`, `_score_phase_relative_pace`, `_score_technique_adaptation`, and `_score_adaptation_evolution`. Each returns a float in [0, 1]. Full implementations should follow the design doc specifications using the decay curve formula:
```python
score = max(0.0, 1.0 - ((value - full) / (zero - full)) ** ADAPT_V2_DECAY_EXP)
```

6. **Wire into `score_session_phase_aware`** (after line 1637):
- Call `_score_adaptation_v2(...)` and store result
- Inject `adaptation` sub-score into `result["sub_scores"]`
- Recompute total as sum of all 5 categories

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_scoring_adaptation.py -v`
Expected: All 5 tests PASS

Also run: `pytest telemetry_tool/tests/test_scoring*.py -v`
Expected: All existing scoring tests still pass (may need threshold adjustments due to weight changes)

**Step 5: Commit**

```bash
git add telemetry_tool/scoring.py telemetry_tool/tests/test_scoring_adaptation.py
git commit -m "feat(meteo): add Adaptation scoring grade (/15), redistribute weights to 25/25/20/15/15"
```

---

## Task 6: Pipeline Integration — Step 8e Weather Timeline

**Files:**
- Modify: `telemetry_tool/pipeline.py` (after line 959, before line 961)

**Step 1: Write failing integration test**

```python
# telemetry_tool/tests/test_pipeline_weather_integration.py
"""Integration test: weather timeline flows through pipeline."""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class TestPipelineWeatherIntegration:
    def test_weather_timeline_none_when_no_datetime(self):
        """Pipeline should produce weather_timeline=None gracefully."""
        # This test verifies the pipeline doesn't crash when weather is unavailable
        from telemetry_tool.weather_timeline import build_weather_timeline
        result = build_weather_timeline({"hours": []}, [0.0, 120.0], datetime.now())
        assert result.empty

    def test_summary_has_weather_timeline_key(self):
        """Pipeline summary dict should include weather_timeline key."""
        # We just check the key exists in the summary init
        from telemetry_tool.pipeline import analyze_session
        # The key should be declared in the summary initialization
        # (verified by grep, not a full pipeline run)
        import inspect
        source = inspect.getsource(analyze_session)
        assert "weather_timeline" in source
```

**Step 2: Add step 8e to pipeline.py**

After line 959 (`summary["track_evolution"] = track_evolution`), before line 961 (`# -- 08d3:`), insert:

```python
    # -- 08e: Weather timeline (per-lap weather interpolation) --

    weather_timeline: "pd.DataFrame | None" = None

    def _weather_timeline():
        wt_mod = _import("weather_timeline")
        ms_mod = _import("meteo_service")
        if wt_mod is None or ms_mod is None:
            return None

        # Try to get session datetime
        session_dt = wt_mod.parse_session_datetime(csv_path)
        if session_dt is None:
            # Check user-provided datetime from web form
            _dt_str = meta.get("session_datetime") or meta.get("date")
            if _dt_str:
                try:
                    session_dt = datetime.fromisoformat(str(_dt_str))
                except (ValueError, TypeError):
                    pass
        if session_dt is None:
            logger.info("No session datetime available; skipping weather timeline")
            return None

        # Get track coordinates
        _tid = summary.get("track_id")
        if not _tid or not conn:
            return None
        _track_row = conn.execute(
            "SELECT start_lat, start_lon FROM tracks WHERE track_id = ?",
            (_tid,)
        ).fetchone()
        if not _track_row or not _track_row["start_lat"]:
            return None

        lat, lon = _track_row["start_lat"], _track_row["start_lon"]

        # Fetch hourly weather
        hourly = ms_mod.fetch_historical_weather(lat, lon, session_dt.strftime("%Y-%m-%d"))
        if "error" in hourly:
            logger.warning("Weather API error: %s", hourly.get("error"))
            return None

        # Build per-lap timestamps from lap_times
        _lap_ts = []
        cumulative = 0.0
        for lt in (summary.get("lap_times") or []):
            _lap_ts.append(cumulative)
            cumulative += lt
        if not _lap_ts:
            return None

        return wt_mod.build_weather_timeline(hourly, _lap_ts, session_dt)

    weather_tl, err = _safe_step("08e_weather_timeline", _weather_timeline)
    _record("08e_weather_timeline", weather_tl, err)
    if weather_tl is not None and not weather_tl.empty:
        weather_timeline = weather_tl
        logger.info("Weather timeline: %d laps enriched", len(weather_tl))
    summary["weather_timeline"] = weather_timeline
```

Also add `"weather_timeline": None,` to the summary dict initialization (~line 548).

**Step 3: Wire weather_timeline into scoring call**

At ~line 1990, where `score_session_phase_aware` is called, add `weather_timeline=weather_timeline`:

```python
return score_mod.score_session_phase_aware(
    m, theo_metrics, meta.get("session_type", "practice"),
    context=context, phases_df=phases_df,
    lap_to_phase=lap_to_phase,
    lap_metrics=lap_metrics,
    track_evolution=track_evolution,
    corner_performances=corner_performances,
    weather_timeline=weather_timeline,  # NEW
)
```

And update `score_session_phase_aware` signature to accept it.

**Step 4: Wire weather_timeline into report generation**

At ~line 2112, where `generate_report()` is called, add:
```python
weather_timeline=weather_timeline,
adaptation_result=score_result.get("sub_scores", {}).get("adaptation", {}).get("detail") if score_result else None,
```

**Step 5: Verify and commit**

Run: `pytest telemetry_tool/tests/test_pipeline_weather_integration.py -v`
Run: `pytest telemetry_tool/tests/ -x --timeout=60`
Expected: All tests pass

```bash
git add telemetry_tool/pipeline.py telemetry_tool/tests/test_pipeline_weather_integration.py
git commit -m "feat(meteo): integrate weather timeline into pipeline step 8e, wire to scoring + reports"
```

---

## Task 7: Race Strategy Weather Alerts

**Files:**
- Modify: `telemetry_tool/web/routes/race_strategy_v2.py` (line 621 `api_state`, line 849 `api_weather`)
- Test: `telemetry_tool/tests/test_strategy_weather_alerts.py` (new)

**Step 1: Write failing tests**

```python
# telemetry_tool/tests/test_strategy_weather_alerts.py
"""Tests for race strategy weather alerts."""
import sys
import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from telemetry_tool.race_strategy_v2 import adjust_stints_for_weather


class TestAdjustStintsForWeather:
    def test_dry_forecast_no_changes(self):
        """Dry forecast should not flag any wet risk."""
        stints = [
            {"stint_number": 1, "planned_start_s": 0, "planned_end_s": 3600},
            {"stint_number": 2, "planned_start_s": 3660, "planned_end_s": 7200},
        ]
        forecast = {
            "forecast": [
                {"time": "2026-02-15T14:00", "rain_prob_pct": 5, "rain_mm": 0, "air_temp_c": 22},
                {"time": "2026-02-15T15:00", "rain_prob_pct": 10, "rain_mm": 0, "air_temp_c": 21},
                {"time": "2026-02-15T16:00", "rain_prob_pct": 5, "rain_mm": 0, "air_temp_c": 20},
            ],
        }
        config = {"race_duration_s": 7200}
        result = adjust_stints_for_weather(stints, forecast, config)

        assert len(result) == 2
        assert not any(s.get("wet_risk") for s in result)

    def test_rain_forecast_flags_wet_risk(self):
        """Rain forecast should flag affected stints."""
        stints = [
            {"stint_number": 1, "planned_start_s": 0, "planned_end_s": 3600},
            {"stint_number": 2, "planned_start_s": 3660, "planned_end_s": 7200},
        ]
        forecast = {
            "forecast": [
                {"time": "2026-02-15T14:00", "rain_prob_pct": 10, "rain_mm": 0, "air_temp_c": 22},
                {"time": "2026-02-15T15:00", "rain_prob_pct": 85, "rain_mm": 3.0, "air_temp_c": 18},
                {"time": "2026-02-15T16:00", "rain_prob_pct": 70, "rain_mm": 2.0, "air_temp_c": 17},
            ],
        }
        config = {"race_duration_s": 7200}
        result = adjust_stints_for_weather(stints, forecast, config)

        # Second stint should be flagged
        assert result[1].get("wet_risk") is True
        assert "recommended_compound" in result[1]

    def test_empty_forecast_no_crash(self):
        """Empty or error forecast returns stints unchanged."""
        stints = [{"stint_number": 1, "planned_start_s": 0, "planned_end_s": 3600}]
        result = adjust_stints_for_weather(stints, {"error": "unavailable"}, {})
        assert len(result) == 1
        assert not result[0].get("wet_risk")
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_strategy_weather_alerts.py -v`
Expected: FAIL with `ImportError`

**Step 3: Add `adjust_stints_for_weather` to `race_strategy_v2.py`**

```python
def adjust_stints_for_weather(
    remaining_stints: list[dict[str, Any]],
    forecast: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Annotate remaining stints with weather risk.

    For each stint, estimates conditions at stint time from forecast,
    flags wet_risk, and suggests compound. Does NOT modify strategy.

    Returns annotated copies of the stint dicts.
    """
    if forecast.get("error") or not forecast.get("forecast"):
        return [dict(s) for s in remaining_stints]

    forecast_hours = forecast["forecast"]
    race_start = datetime.now()  # approximate

    result = []
    for stint in remaining_stints:
        s = dict(stint)
        start_s = s.get("planned_start_s", 0)
        end_s = s.get("planned_end_s", start_s + 3600)

        # Find forecast hour closest to stint midpoint
        mid_s = (start_s + end_s) / 2
        mid_hour_idx = min(int(mid_s / 3600), len(forecast_hours) - 1)
        if mid_hour_idx < 0:
            mid_hour_idx = 0

        hour = forecast_hours[mid_hour_idx]
        rain_prob = hour.get("rain_prob_pct", 0) or 0
        rain_mm = hour.get("rain_mm", 0) or 0

        if rain_prob > 50 or rain_mm > 0.5:
            s["wet_risk"] = True
            s["rain_prob_pct"] = rain_prob
            s["rain_mm_forecast"] = rain_mm

            from meteo_service import estimate_track_conditions
            cond = estimate_track_conditions({
                "air_temp_c": hour.get("air_temp_c", 20),
                "rain_mm": rain_mm,
                "humidity_pct": hour.get("humidity_pct", 70),
            })
            s["recommended_compound"] = cond.get("recommended_compound", "wet")
            s["grip_score_forecast"] = cond.get("grip_score")
        else:
            s["wet_risk"] = False

        result.append(s)

    return result
```

**Step 4: Add `_check_weather_alerts` to route file**

In `telemetry_tool/web/routes/race_strategy_v2.py`, add the forecast cache and alert checker as specified in the design doc. Integrate into `api_state()` by calling `_check_weather_alerts` at the end before `return jsonify(...)`, and including `"weather_alert": alert` in the response dict.

**Step 5: Verify and commit**

Run: `pytest telemetry_tool/tests/test_strategy_weather_alerts.py -v`
Expected: All 3 tests PASS

```bash
git add telemetry_tool/race_strategy_v2.py telemetry_tool/web/routes/race_strategy_v2.py telemetry_tool/tests/test_strategy_weather_alerts.py
git commit -m "feat(meteo): add weather alerts to race strategy + adjust_stints_for_weather"
```

---

## Task 8: Race Strategy Live Dashboard — Weather UI

**Files:**
- Modify: `telemetry_tool/web/templates/race_strategy/live.html`
- Modify: `telemetry_tool/web/static/js/race_strategy_live.js`

**Step 1: Add weather alert card to live.html**

After the race progress section, add:

```html
<!-- Weather Alert Banner -->
<div id="weather-alert" class="weather-alert hidden">
    <div class="alert-icon">&#9888;</div>
    <div class="alert-content">
        <strong id="weather-alert-title">Weather Alert</strong>
        <p id="weather-alert-message"></p>
    </div>
</div>

<!-- Current Conditions Widget -->
<div id="weather-widget" class="weather-widget">
    <div class="weather-stat">
        <span class="weather-label">Temp</span>
        <span id="weather-temp" class="weather-value">--</span>
    </div>
    <div class="weather-stat">
        <span class="weather-label">Grip</span>
        <div class="grip-bar-container">
            <div id="weather-grip-bar" class="grip-bar" style="width: 0%"></div>
        </div>
        <span id="weather-grip-text" class="weather-value">--</span>
    </div>
    <div class="weather-stat">
        <span class="weather-label">Track</span>
        <span id="weather-track-state" class="weather-value">--</span>
    </div>
</div>
```

**Step 2: Add CSS for weather components to `race_strategy.css`**

```css
.weather-alert {
    padding: 12px 16px;
    border-radius: 8px;
    margin-bottom: 16px;
    display: flex;
    align-items: center;
    gap: 12px;
}
.weather-alert.warning { background: #3d3000; border: 1px solid #ffd600; }
.weather-alert.critical { background: #3d0000; border: 1px solid #ff4444; }
.weather-alert.hidden { display: none; }
.weather-widget {
    display: flex;
    gap: 24px;
    padding: 8px 16px;
    background: #1a1d23;
    border-radius: 8px;
    margin-bottom: 16px;
}
.grip-bar-container {
    width: 60px; height: 8px;
    background: #333;
    border-radius: 4px;
    overflow: hidden;
}
.grip-bar {
    height: 100%;
    border-radius: 4px;
    transition: width 0.3s;
    background: #3ddc84;
}
```

**Step 3: Update `race_strategy_live.js` to consume weather data**

In the polling callback where `api/state` response is processed, add:

```javascript
// Weather alert
const alert = data.weather_alert;
const alertEl = document.getElementById('weather-alert');
if (alert) {
    alertEl.classList.remove('hidden', 'warning', 'critical');
    alertEl.classList.add(alert.severity);
    document.getElementById('weather-alert-title').textContent =
        alert.severity === 'critical' ? 'RAIN ALERT' : 'Weather Warning';
    document.getElementById('weather-alert-message').textContent = alert.message;
} else {
    alertEl.classList.add('hidden');
}

// Weather widget (from conditions in engine_data or separate call)
if (data.engine_data && data.engine_data.weather) {
    const w = data.engine_data.weather;
    document.getElementById('weather-temp').textContent =
        w.air_temp_c != null ? w.air_temp_c.toFixed(1) + '\u00b0C' : '--';
    const grip = w.grip_score || 0;
    document.getElementById('weather-grip-bar').style.width = grip + '%';
    document.getElementById('weather-grip-text').textContent = grip + '%';
    document.getElementById('weather-track-state').textContent =
        (w.track_state || '--').toUpperCase();
}
```

**Step 4: Test manually**

Open the race strategy live dashboard in browser, verify:
- Weather widget displays current conditions
- Alert banner appears when rain is detected

**Step 5: Commit**

```bash
git add telemetry_tool/web/templates/race_strategy/live.html telemetry_tool/web/static/js/race_strategy_live.js telemetry_tool/web/static/css/race_strategy.css
git commit -m "feat(meteo): add weather alert card + conditions widget to race strategy live dashboard"
```

---

## Task 9: Next.js Race Strategy Live — Weather UI

**Files:**
- Modify: `lap-website/src/app/app/race-strategy/[id]/live/page.tsx`

**Step 1: Add weather alert and conditions components**

In the live page component, add a `WeatherAlertBanner` and `ConditionsWidget` that consume the `weather_alert` and weather data from the `api/state` response. Follow the existing pattern of the page (TanStack Query polling at 3s).

Add after the race progress section:

```tsx
{/* Weather Alert */}
{stateData?.weather_alert && (
  <div className={`rounded-lg p-3 mb-4 flex items-center gap-3 ${
    stateData.weather_alert.severity === 'critical'
      ? 'bg-red-900/40 border border-red-500'
      : 'bg-yellow-900/40 border border-yellow-500'
  }`}>
    <span className="text-2xl">
      {stateData.weather_alert.severity === 'critical' ? '🌧️' : '⚠️'}
    </span>
    <div>
      <p className="font-semibold text-sm">
        {stateData.weather_alert.severity === 'critical' ? 'RAIN ALERT' : 'Weather Warning'}
      </p>
      <p className="text-sm text-gray-300">{stateData.weather_alert.message}</p>
    </div>
  </div>
)}

{/* Current Conditions Mini-Widget */}
{stateData?.engine_data?.weather && (
  <div className="flex gap-6 bg-[#1a1d23] rounded-lg px-4 py-2 mb-4 text-sm">
    <div>
      <span className="text-gray-400">Temp</span>{' '}
      <span className="font-mono">{stateData.engine_data.weather.air_temp_c?.toFixed(1)}°C</span>
    </div>
    <div className="flex items-center gap-2">
      <span className="text-gray-400">Grip</span>
      <div className="w-16 h-2 bg-gray-700 rounded-full overflow-hidden">
        <div
          className="h-full bg-green-400 rounded-full transition-all"
          style={{ width: `${stateData.engine_data.weather.grip_score || 0}%` }}
        />
      </div>
      <span className="font-mono">{stateData.engine_data.weather.grip_score}%</span>
    </div>
    <div>
      <span className="text-gray-400">Track</span>{' '}
      <span className="font-mono uppercase">{stateData.engine_data.weather.track_state}</span>
    </div>
  </div>
)}
```

**Step 2: Update TypeScript types**

In the types file or inline, add:
```typescript
interface WeatherAlert {
  severity: 'warning' | 'critical';
  message: string;
  alert_type: string;
}
```

**Step 3: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds with no type errors

**Step 4: Commit**

```bash
git add lap-website/src/app/app/race-strategy/
git commit -m "feat(meteo): add weather alert + conditions widget to Next.js race strategy live page"
```

---

## Task 10: Weather-Enriched Report Sections

**Files:**
- Modify: `telemetry_tool/reporting_html.py` (line 2538 signature, template sections)

**Step 1: Update `generate_report` signature**

Add new optional kwargs:

```python
weather_timeline: Optional[pd.DataFrame] = None,
adaptation_result: Optional[dict[str, Any]] = None,
phase_theoreticals: Optional[dict] = None,
```

**Step 2: Add Section 1 — Session Conditions Banner**

After the headline score section, add an HTML block that renders when `weather_timeline` is not None. Shows a one-line summary of conditions + a grip sparkline (matplotlib base64 SVG, 30px tall).

**Step 3: Add Section 2 — Condition Timeline Strip**

Above the lap time heatmap. Horizontal bar of colored segments:
- Dry: `#3ddc84`, Greasy: `#ffd600`, Damp: `#4fc3f7`, Wet: `#1565c0`
Temperature overlay + rain bars. Use matplotlib to render as base64 PNG.

**Step 4: Add Section 3 — Per-Phase Analysis Cards**

After timeline strip. One card per phase with: label, lap range, conditions, best lap vs condition-adjusted theoretical.

**Step 5: Add Section 4 — Adaptation Score Breakdown**

In the sub-scores section. Three sub-metric bars + transition highlights.

**Step 6: Add Section 5 — Enhanced Coaching**

In existing coaching section. Weather-contextual advice.

All new sections are guarded by `if weather_timeline is not None:` — backward compatible.

**Step 7: Verify report generation**

Run the pipeline on a sample CSV with mock weather data and verify the HTML report renders correctly with all new sections.

**Step 8: Commit**

```bash
git add telemetry_tool/reporting_html.py
git commit -m "feat(meteo): add 5 weather-enriched report sections (conditions, timeline, phases, adaptation, coaching)"
```

---

## Task 11: DB Persistence — Save Weather Timeline

**Files:**
- Modify: `telemetry_tool/pipeline.py` (in the DB-write section, after step 14)

**Step 1: Add weather timeline DB write**

In the section where session data is written to the database (~line 2180+), add:

```python
# Persist weather timeline to session_weather_laps table
if weather_timeline is not None and not weather_timeline.empty and conn is not None:
    try:
        for _, row in weather_timeline.iterrows():
            conn.execute(
                "INSERT OR IGNORE INTO session_weather_laps "
                "(session_id, lap_number, timestamp, air_temp_c, humidity_pct, "
                "wind_speed_mps, wind_dir_deg, rain_mm, cloud_cover_pct, "
                "weather_code, grip_score, track_state, track_temp_est_c) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    meta.get("session_id"), int(row["lap_number"]),
                    row.get("timestamp"), row.get("air_temp_c"),
                    row.get("humidity_pct"), row.get("wind_speed_mps"),
                    row.get("wind_dir_deg"), row.get("rain_mm"),
                    row.get("cloud_cover_pct"), row.get("weather_code"),
                    row.get("grip_score"), row.get("track_state"),
                    row.get("track_temp_est_c"),
                ),
            )
        conn.commit()
        logger.info("Saved weather timeline for %d laps", len(weather_timeline))
    except Exception as exc:
        logger.warning("Failed to persist weather timeline: %s", exc)
```

**Step 2: Commit**

```bash
git add telemetry_tool/pipeline.py
git commit -m "feat(meteo): persist weather timeline to session_weather_laps table"
```

---

## Task 12: Existing Test Fixes + Full Test Run

**Files:**
- Modify: various test files that depend on scoring weights

**Step 1: Run full test suite**

Run: `pytest telemetry_tool/tests/ -v --timeout=120`

**Step 2: Fix any tests broken by weight changes**

The scoring weight redistribution (30->25 pace, 25->20 execution, 20->15 robustness) will affect tests that assert specific score values. Update expected values in:
- `telemetry_tool/tests/test_scoring.py`
- Any test that hardcodes `MAX_PACE == 30` or similar

**Step 3: Verify all tests pass**

Run: `pytest telemetry_tool/tests/ -v --timeout=120`
Expected: All tests PASS (existing + new)

Run: `cd lap-website && npm run build`
Expected: Frontend builds without errors

**Step 4: Commit**

```bash
git add -A
git commit -m "fix(tests): update scoring test expectations for redistributed weights"
```

---

## Task 13: Final Integration Verification

**Step 1: Run full backend test suite**

```bash
pytest telemetry_tool/tests/ -v --timeout=120
```

**Step 2: Run frontend build + lint**

```bash
cd lap-website && npm run lint && npm run build
```

**Step 3: Verify design doc accuracy**

Read through `docs/plans/2026-02-27-meteo-deep-integration-design.md` and confirm implementation matches.

**Step 4: Final commit**

If any loose changes remain:
```bash
git add -A
git commit -m "feat(meteo): complete meteo deep integration — weather timeline, adaptation scoring, strategy alerts, enriched reports"
```
