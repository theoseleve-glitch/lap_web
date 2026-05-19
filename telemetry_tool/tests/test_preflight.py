"""Preflight validator tests — focused on delimiter detection regression.

Bug: the delimiter detector inspected only the first 5 non-empty lines and
required every one of them to contain the candidate delimiter. RaceChrono
Pro CSVs always emit ~10 metadata header lines before the column row, the
first being a banner with zero commas, so the predicate
``all(c > 0 for c in counts)`` rejected every delimiter and uploads failed
with CSV_DELIMITER_NOT_RECOGNIZED.
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from telemetry_tool.preflight import run_preflight
from telemetry_tool.import_errors import ImportErrorCode


def _make_rc_csv(n_data_rows: int = 80) -> str:
    """Build a RaceChrono-format CSV string with metadata header + N data rows."""
    metadata = textwrap.dedent("""\
        This file is created using RaceChrono Pro v10.0.4 ( http://racechrono.com/ ).
        Format,2,"Format 1 = static columns","Format 2 = new format with dynamic columns; only channel header string is fixed, number of columns and channels' column numbers are variable."
        Session title,"KCT"
        Session type,Lap timing
        Track name,"KCT"
        Driver name,
        Export scope,Session start
        Created,29/03/2026,08:06
        Note,

    """)
    header = (
        "Time (s),Session fragment #,Lap #,Trap name,X-position (m),"
        "Y-position (m),Distance (m),Speed (m/s),Altitude (m),"
        "Bearing (deg),Latitude (deg),Longitude (deg)"
    )
    rows = [
        f"{1774771616.0 + i * 0.04:.3f},0,1,,{i * 0.5:.3f},{i * 0.3:.3f},"
        f"{i * 0.6:.3f},{15.0 + i * 0.1:.3f},43.9,347.9,"
        f"{47.3878800 + i * 0.000001:.7f},{0.7891646 + i * 0.000001:.7f}"
        for i in range(n_data_rows)
    ]
    return metadata + header + "\n" + "\n".join(rows) + "\n"


@pytest.fixture
def racechrono_csv(tmp_path) -> Path:
    p = tmp_path / "racechrono_session.csv"
    p.write_text(_make_rc_csv(), encoding="utf-8")
    return p


@pytest.fixture
def racechrono_semi_csv(tmp_path) -> Path:
    """RaceChrono-style file but with semicolon delimiter (European export)."""
    content = _make_rc_csv().replace(",", ";")
    # restore the comma-decimal that semicolon-style locales use? Not needed
    # for delimiter detection — we just need to confirm the anchor picks `;`.
    p = tmp_path / "racechrono_semi.csv"
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture
def plain_csv_no_metadata(tmp_path) -> Path:
    """Plain CSV with header on row 1 and no preceding metadata."""
    rows = [
        f"{0.04 * i:.3f},{15.0 + i * 0.1:.3f},43.9,"
        f"{47.3878800 + i * 0.000001:.7f},{0.7891646 + i * 0.000001:.7f}"
        for i in range(80)
    ]
    content = (
        "Time (s),Speed (m/s),Altitude (m),Latitude (deg),Longitude (deg)\n"
        + "\n".join(rows)
        + "\n"
    )
    p = tmp_path / "plain.csv"
    p.write_text(content, encoding="utf-8")
    return p


def test_racechrono_metadata_header_accepted(racechrono_csv):
    """Regression: RaceChrono CSV must pass preflight despite metadata header."""
    result = run_preflight(str(racechrono_csv))
    assert result.ok, (
        f"Expected preflight to accept RaceChrono CSV; got failure "
        f"{result.failure.code if result.failure else None!r}"
    )
    assert result.delimiter == ","
    assert result.detected_source == "RaceChrono"


def test_racechrono_semicolon_metadata_accepted(racechrono_semi_csv):
    """Anchor logic must work for semicolon-delimited RaceChrono exports too."""
    result = run_preflight(str(racechrono_semi_csv))
    assert result.ok, (
        f"Expected preflight to accept semicolon RaceChrono; got "
        f"{result.failure.code if result.failure else None!r}"
    )
    assert result.delimiter == ";"


def test_plain_csv_without_metadata_still_works(plain_csv_no_metadata):
    """Sanity: a vanilla header-then-data CSV must still pass after the fix."""
    result = run_preflight(str(plain_csv_no_metadata))
    assert result.ok, (
        f"Expected preflight to accept plain CSV; got "
        f"{result.failure.code if result.failure else None!r}"
    )
    assert result.delimiter == ","
