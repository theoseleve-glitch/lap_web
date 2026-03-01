"""Parity harness: synthetic CSV generators, upload fixtures, and tolerance helpers.

This module provides the foundation for parity tests that validate the
SaaS upload-then-query path against direct pipeline execution.  It does
NOT contain the parity tests themselves (those live in a separate file).

Contents
--------
- TOLERANCES dict with per-metric acceptable deltas
- dump_artifact() for post-mortem JSON inspection
- assert_close() / assert_exact() for parity assertions
- _generate_synthetic_csv() deterministic RaceChrono-style CSV
- _generate_minimal_csv() CSV lacking acceleration columns
- uploaded_session() module-scoped fixture (real pipeline run)
- minimal_session() module-scoped fixture (missing-data contract)
- Smoke tests verifying the helpers and fixture work
"""
from __future__ import annotations

import io
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

# Ensure project root is on path (mirrors conftest.py)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ══════════════════════════════════════════════════════════════════
# 1. TOLERANCES
# ══════════════════════════════════════════════════════════════════

TOLERANCES = {
    "lap_time_s":       0.005,   # +/-5 ms
    "best_lap_index":   0,       # exact
    "total_score":      0.1,     # +/-0.1 out of 100
    "pillar_score":     0.1,     # +/-0.1 per pillar
    "grade":            0,       # exact string
    "sector_time_s":    0.001,   # +/-1 ms
    "corner_s_start":   1.0,     # +/-1 m
    "corner_s_end":     1.0,     # +/-1 m
    "corner_s_apex":    1.0,     # +/-1 m
    "speed_mps":        0.01,    # +/-0.01 m/s per sample
    "gps_lat_lon":      1e-6,    # ~0.1 m at equator
    "accel_g":          0.01,    # +/-0.01 g per sample
}


# ══════════════════════════════════════════════════════════════════
# 2. Helper functions
# ══════════════════════════════════════════════════════════════════

def dump_artifact(directory, name, data):
    """Write JSON artifact for post-mortem inspection."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    return path


def assert_close(actual, expected, tol_key, label=""):
    """Assert numeric value within tolerance."""
    tol = TOLERANCES[tol_key]
    diff = abs(actual - expected)
    assert diff <= tol, (
        f"PARITY FAIL [{label}]: {actual} vs {expected} "
        f"(diff={diff:.6f}, tol={tol} [{tol_key}])"
    )


def assert_exact(actual, expected, label=""):
    """Assert exact equality."""
    assert actual == expected, (
        f"PARITY FAIL [{label}]: {actual!r} != {expected!r}"
    )


# ══════════════════════════════════════════════════════════════════
# 3. Synthetic CSV generators
# ══════════════════════════════════════════════════════════════════

def _generate_synthetic_csv(
    n_laps: int = 5,
    points_per_lap: int = 200,
    seed: int = 42,
) -> Path:
    """Generate a deterministic RaceChrono-like CSV on a 500m oval.

    Parameters
    ----------
    n_laps : int
        Number of laps to generate.
    points_per_lap : int
        Data points per lap (evenly spaced in distance).
    seed : int
        Random seed for reproducibility.

    Returns
    -------
    Path
        Path to the generated temporary CSV file.
    """
    rng = np.random.RandomState(seed)

    # Track geometry: 500m oval
    lap_length_m = 500.0
    base_lat = 51.5074   # London
    base_lon = -0.1278
    lat_amplitude = 0.001
    lon_amplitude = 0.002

    # Speed model: ~15 m/s base with dips at 4 corners
    base_speed_mps = 15.0
    corner_positions = [0.25, 0.50, 0.75, 1.00]  # fraction of lap
    corner_dip = 5.0          # m/s reduction at corner centre
    corner_width = 0.05       # fraction of lap for gaussian sigma

    # Lap variation factors: lap 3 fastest (x1.02 speed), lap 1 slowest (x0.97)
    # For n_laps laps, interpolate between 0.97 and 1.02 with lap 3 peak.
    lap_speed_factors = []
    for i in range(n_laps):
        lap_num = i + 1
        if lap_num == 1:
            lap_speed_factors.append(0.97)
        elif lap_num == 3:
            lap_speed_factors.append(1.02)
        else:
            # Slight variation, not as extreme
            lap_speed_factors.append(1.0 + rng.uniform(-0.005, 0.005))

    # Build CSV lines
    lines = []

    # RaceChrono metadata header (3 lines)
    lines.append("# Format: RaceChrono Pro v7.5 export")
    lines.append("# Session: Synthetic parity test session")
    lines.append("# Track: Parity Oval 500m")

    # Column header
    cols = [
        "Time (s)",
        "Lap #",
        "Distance (m)",
        "Speed (m/s)",
        "Latitude (deg)",
        "Longitude (deg)",
        "Lateral acceleration (m/s\u00b2)",
        "Longitudinal acceleration (m/s\u00b2)",
    ]
    lines.append(",".join(cols))

    cumulative_time = 0.0

    for lap_idx in range(n_laps):
        lap_num = lap_idx + 1
        speed_factor = lap_speed_factors[lap_idx]

        for pt in range(points_per_lap):
            frac = pt / points_per_lap          # 0.0 .. just under 1.0
            dist = frac * lap_length_m

            # Speed with corner dips
            speed = base_speed_mps * speed_factor
            for cp in corner_positions:
                delta_frac = frac - cp
                # Wrap around for the 1.0 corner (also affects start of lap)
                if abs(delta_frac) > 0.5:
                    delta_frac = delta_frac - np.sign(delta_frac)
                gaussian = np.exp(-0.5 * (delta_frac / corner_width) ** 2)
                speed -= corner_dip * gaussian

            # Add small random noise
            speed += rng.normal(0, 0.05)
            speed = max(speed, 2.0)  # floor to avoid negatives

            # Time: dt = distance_step / speed
            if pt == 0:
                dt = 0.0
            else:
                ds = lap_length_m / points_per_lap
                dt = ds / speed
            cumulative_time += dt

            # GPS: oval via sin/cos
            angle = 2.0 * math.pi * frac
            lat = base_lat + lat_amplitude * math.cos(angle)
            lon = base_lon + lon_amplitude * math.sin(angle)

            # Curvature for lateral acceleration:
            # For an oval, curvature k = (a^2 b^2) / (...)^(3/2) but we
            # approximate: a_lat = v^2 * curvature_estimate
            # Use second derivative of position wrt arc length as proxy.
            curvature = (2.0 * math.pi / lap_length_m) * abs(math.sin(angle))
            accel_lat = speed ** 2 * curvature / 9.80665  # in g

            # Longitudinal acceleration from speed change at corners
            accel_long = 0.0
            for cp in corner_positions:
                delta_frac = frac - cp
                if abs(delta_frac) > 0.5:
                    delta_frac = delta_frac - np.sign(delta_frac)
                # Derivative of gaussian dip = braking/accel profile
                accel_long += (
                    corner_dip * delta_frac / (corner_width ** 2)
                    * np.exp(-0.5 * (delta_frac / corner_width) ** 2)
                )
            # Convert to m/s^2 (approximate)
            accel_long_mps2 = accel_long * 0.5  # scale factor

            # Convert lat accel to m/s^2 for the column
            accel_lat_mps2 = accel_lat * 9.80665

            line = (
                f"{cumulative_time:.4f},"
                f"{lap_num},"
                f"{dist:.2f},"
                f"{speed:.4f},"
                f"{lat:.7f},"
                f"{lon:.7f},"
                f"{accel_lat_mps2:.4f},"
                f"{accel_long_mps2:.4f}"
            )
            lines.append(line)

    # Write to temp file
    fd, tmp_path = tempfile.mkstemp(suffix=".csv", prefix="parity_synth_")
    os.close(fd)
    tmp = Path(tmp_path)
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp


def _generate_minimal_csv(
    n_laps: int = 3,
    points_per_lap: int = 50,
    seed: int = 42,
) -> Path:
    """Generate a minimal CSV lacking acceleration columns.

    Only includes: Time (s), Lap #, Distance (m), Speed (m/s),
    Latitude (deg), Longitude (deg).  No acceleration data.

    Returns
    -------
    Path
        Path to the generated temporary CSV file.
    """
    rng = np.random.RandomState(seed)

    lap_length_m = 500.0
    base_lat = 51.5074
    base_lon = -0.1278
    base_speed = 14.0

    lines = []

    # Metadata header
    lines.append("# Format: RaceChrono Pro v7.5 export")
    lines.append("# Session: Minimal parity test")
    lines.append("# Track: Parity Oval 500m")

    # Column header (no acceleration columns)
    cols = [
        "Time (s)",
        "Lap #",
        "Distance (m)",
        "Speed (m/s)",
        "Latitude (deg)",
        "Longitude (deg)",
    ]
    lines.append(",".join(cols))

    cumulative_time = 0.0

    for lap_idx in range(n_laps):
        lap_num = lap_idx + 1

        for pt in range(points_per_lap):
            frac = pt / points_per_lap
            dist = frac * lap_length_m
            speed = base_speed + rng.normal(0, 0.5)
            speed = max(speed, 2.0)

            if pt == 0:
                dt = 0.0
            else:
                ds = lap_length_m / points_per_lap
                dt = ds / max(speed, 1.0)
            cumulative_time += dt

            angle = 2.0 * math.pi * frac
            lat = base_lat + 0.001 * math.cos(angle)
            lon = base_lon + 0.002 * math.sin(angle)

            line = (
                f"{cumulative_time:.4f},"
                f"{lap_num},"
                f"{dist:.2f},"
                f"{speed:.4f},"
                f"{lat:.7f},"
                f"{lon:.7f}"
            )
            lines.append(line)

    fd, tmp_path = tempfile.mkstemp(suffix=".csv", prefix="parity_minimal_")
    os.close(fd)
    tmp = Path(tmp_path)
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp


# ══════════════════════════════════════════════════════════════════
# 4. Upload fixtures
# ══════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def uploaded_session():
    """Upload synthetic CSV via Flask test client, capture pipeline result.

    Returns (client, session_id, pipeline_summary).

    The fixture runs the real pipeline (no mocks on run_full_analysis)
    but patches the DB persistence layer since we use in-memory SQLite.
    """
    csv_path = _generate_synthetic_csv()

    try:
        from web.app import create_app

        app = create_app()
        app.config["TESTING"] = True

        # Capture the pipeline summary returned by run_full_analysis
        captured = {}
        _original_run = None

        # Import the module to get the original function reference
        import web.routes.sessions_v2 as sessions_mod
        _original_run = sessions_mod.run_full_analysis

        def _capturing_wrapper(**kwargs):
            result = _original_run(**kwargs)
            captured["summary"] = result
            return result

        client = app.test_client()

        # Read CSV content for upload
        csv_content = csv_path.read_bytes()

        with patch(
            "web.routes.sessions_v2.run_full_analysis",
            side_effect=_capturing_wrapper,
        ):
            resp = client.post(
                "/api/v1/sessions/upload",
                data={
                    "file": (io.BytesIO(csv_content), "parity_synth.csv"),
                    "session_type": "practice",
                    "track_state": "dry",
                    "driver_name": "ParityDriver",
                },
                content_type="multipart/form-data",
            )

        assert resp.status_code == 200, (
            f"Upload failed with status {resp.status_code}: "
            f"{resp.data.decode('utf-8', errors='replace')[:500]}"
        )

        body = resp.get_json()
        assert body["ok"] is True, f"Upload response not OK: {body}"

        session_id = body["data"]["session_id"]
        summary = captured.get("summary", {})

        yield client, session_id, summary

    finally:
        # Cleanup temp file
        try:
            csv_path.unlink(missing_ok=True)
        except Exception:
            pass


@pytest.fixture(scope="module")
def minimal_session():
    """Upload minimal CSV (no acceleration columns), capture pipeline result.

    Returns (client, session_id, pipeline_summary).
    Tests the missing-data contract.
    """
    csv_path = _generate_minimal_csv()

    try:
        from web.app import create_app

        app = create_app()
        app.config["TESTING"] = True

        captured = {}

        import web.routes.sessions_v2 as sessions_mod
        _original_run = sessions_mod.run_full_analysis

        def _capturing_wrapper(**kwargs):
            result = _original_run(**kwargs)
            captured["summary"] = result
            return result

        client = app.test_client()
        csv_content = csv_path.read_bytes()

        with patch(
            "web.routes.sessions_v2.run_full_analysis",
            side_effect=_capturing_wrapper,
        ):
            resp = client.post(
                "/api/v1/sessions/upload",
                data={
                    "file": (io.BytesIO(csv_content), "parity_minimal.csv"),
                    "session_type": "practice",
                    "track_state": "dry",
                    "driver_name": "MinimalDriver",
                },
                content_type="multipart/form-data",
            )

        assert resp.status_code == 200, (
            f"Minimal upload failed with status {resp.status_code}: "
            f"{resp.data.decode('utf-8', errors='replace')[:500]}"
        )

        body = resp.get_json()
        assert body["ok"] is True, f"Minimal upload response not OK: {body}"

        session_id = body["data"]["session_id"]
        summary = captured.get("summary", {})

        yield client, session_id, summary

    finally:
        try:
            csv_path.unlink(missing_ok=True)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════
# 5. Smoke tests
# ══════════════════════════════════════════════════════════════════

def test_assert_close_passes():
    """assert_close passes when values are within tolerance."""
    assert_close(60.003, 60.0, "lap_time_s", "test lap")


def test_assert_close_fails():
    """assert_close raises AssertionError with PARITY FAIL message."""
    with pytest.raises(AssertionError, match="PARITY FAIL"):
        assert_close(60.1, 60.0, "lap_time_s", "test lap")


def test_assert_exact_passes():
    """assert_exact passes on equal values."""
    assert_exact("A", "A", "grade check")


def test_assert_exact_fails():
    """assert_exact raises AssertionError with PARITY FAIL message."""
    with pytest.raises(AssertionError, match="PARITY FAIL"):
        assert_exact("A", "B", "grade check")


def test_dump_artifact(tmp_path):
    """dump_artifact writes a readable JSON file."""
    data = {"score": 75.5, "grade": "B"}
    path = dump_artifact(tmp_path, "test_artifact", data)
    assert path.exists()
    loaded = json.loads(path.read_text())
    assert loaded["score"] == 75.5
    assert loaded["grade"] == "B"


def test_synthetic_csv_is_valid():
    """The synthetic CSV generator produces a file the pipeline can parse."""
    csv_path = _generate_synthetic_csv()
    try:
        content = csv_path.read_text()
        csv_lines = content.strip().split("\n")

        # Should have metadata + header + data rows
        assert len(csv_lines) > 10, "CSV too short"

        # First 3 lines are metadata
        assert csv_lines[0].startswith("#")
        assert csv_lines[1].startswith("#")
        assert csv_lines[2].startswith("#")

        # Line 3 (0-indexed) is the header
        header = csv_lines[3]
        assert "Time (s)" in header
        assert "Lap #" in header
        assert "Distance (m)" in header
        assert "Speed (m/s)" in header
        assert "Latitude (deg)" in header
        assert "Longitude (deg)" in header

        # Data starts at line 4
        first_data = csv_lines[4].split(",")
        assert len(first_data) == 8, f"Expected 8 columns, got {len(first_data)}"

        # Verify we have the right number of data rows
        n_data_rows = len(csv_lines) - 4  # minus 3 metadata + 1 header
        assert n_data_rows == 5 * 200, f"Expected 1000 data rows, got {n_data_rows}"
    finally:
        csv_path.unlink(missing_ok=True)


def test_minimal_csv_lacks_accel():
    """The minimal CSV generator produces a file without acceleration columns."""
    csv_path = _generate_minimal_csv()
    try:
        content = csv_path.read_text()
        csv_lines = content.strip().split("\n")
        header = csv_lines[3]
        assert "acceleration" not in header.lower()
        assert "Time (s)" in header
        assert "Lap #" in header

        # Should have 3 laps x 50 points = 150 data rows
        n_data_rows = len(csv_lines) - 4
        assert n_data_rows == 3 * 50, f"Expected 150 data rows, got {n_data_rows}"
    finally:
        csv_path.unlink(missing_ok=True)


def test_upload_fixture_produces_session(uploaded_session):
    """The uploaded_session fixture successfully runs the pipeline."""
    client, session_id, summary = uploaded_session
    assert session_id is not None, "session_id should not be None"
    assert "steps_ok" in summary, "summary should contain steps_ok"
    assert len(summary.get("steps_ok", [])) > 0, (
        f"At least one pipeline step should succeed. "
        f"steps_ok={summary.get('steps_ok')}, "
        f"steps_failed={summary.get('steps_failed')}"
    )
