"""audit_track_geometry: FAILing sidecars are found and quarantined
without touching grip files."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from audit_track_geometry import audit_sidecars, main  # noqa: E402


def _write_sidecar(root: Path, track_id: str, degenerate: bool) -> None:
    d = root / "track_models" / track_id
    (d / "generic" / "dry").mkdir(parents=True)
    n = 400
    if degenerate:
        x = np.full(n, 10.0); y = np.full(n, 5.0)
    else:
        th = np.linspace(0, 2 * np.pi, n, endpoint=False)
        x, y = 100 * np.cos(th), 100 * np.sin(th)
    seg = np.sqrt(np.diff(x) ** 2 + np.diff(y) ** 2)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    pd.DataFrame({
        "centerline_x": x, "centerline_y": y, "s_grid": s,
        "heading_rad": np.zeros(n), "curvature_1pm": np.zeros(n),
    }).to_parquet(d / "track_model.parquet")
    (d / "generic" / "dry" / "grip_2d.parquet").write_bytes(b"PAR1fakePAR1")


def test_audit_finds_and_quarantines_only_geometry(tmp_path):
    _write_sidecar(tmp_path, "good-track", degenerate=False)
    _write_sidecar(tmp_path, "bad-track", degenerate=True)
    res = audit_sidecars(tmp_path, quarantine=True)
    assert res["good-track"]["passed"] is True
    assert res["bad-track"]["passed"] is False
    bad = tmp_path / "track_models" / "bad-track"
    assert not (bad / "track_model.parquet").exists()
    assert list(bad.glob("track_model.parquet.quarantined-*"))
    assert (bad / "generic" / "dry" / "grip_2d.parquet").exists()  # grip untouched
    good = tmp_path / "track_models" / "good-track"
    assert (good / "track_model.parquet").exists()


def test_json_output_cli(tmp_path, capsys):
    """Test --json flag: main accepts argv and outputs valid JSON with both tracks."""
    _write_sidecar(tmp_path, "good-track", degenerate=False)
    _write_sidecar(tmp_path, "bad-track", degenerate=True)
    exit_code = main(["--sidecar-root", str(tmp_path), "--json"])
    captured = capsys.readouterr()
    result_json = json.loads(captured.out)
    assert "good-track" in result_json
    assert "bad-track" in result_json
    assert result_json["good-track"]["passed"] is True
    assert result_json["bad-track"]["passed"] is False
    assert exit_code == 2  # 2 because bad-track failed


def test_quarantine_replace_handles_existing(tmp_path):
    """Test that os.replace silently replaces same-day quarantined file without FileExistsError."""
    import datetime
    _write_sidecar(tmp_path, "bad-track", degenerate=True)
    bad = tmp_path / "track_models" / "bad-track"
    # Pre-create a same-day quarantined file
    today = datetime.date.today().strftime("%Y%m%d")
    quarantined_path = bad / f"track_model.parquet.quarantined-{today}"
    quarantined_path.write_text("old quarantined content")
    # Run audit with quarantine=True; should replace the old quarantined file
    res = audit_sidecars(tmp_path, quarantine=True)
    assert res["bad-track"]["passed"] is False
    assert res["bad-track"]["quarantined"] is True
    # Verify exactly one quarantined file exists (the new one)
    quarantined_files = list(bad.glob("track_model.parquet.quarantined-*"))
    assert len(quarantined_files) == 1
    assert quarantined_files[0].read_text() != "old quarantined content"  # new one replaced


def test_audit_prints_correct_sql_schema(tmp_path, capsys):
    """Test that printed SQL for quarantined tracks uses correct schema (track_id, vehicle_class, condition, gate, details).

    - Must use only real columns (no passed, failed_gates, audited_at)
    - One INSERT per failed gate, not one per track
    - Details must be valid ::jsonb with gate, message, values fields
    """
    _write_sidecar(tmp_path, "bad-track", degenerate=True)
    # Run audit with quarantine=True to trigger SQL printing
    res = audit_sidecars(tmp_path, quarantine=True)
    captured = capsys.readouterr()

    assert res["bad-track"]["passed"] is False
    assert len(res["bad-track"]["failures"]) > 0

    # Should print at least one INSERT (one per failed gate)
    lines = [l.strip() for l in captured.out.strip().split("\n") if l.strip()]
    insert_lines = [l for l in lines if l.startswith("INSERT INTO")]
    assert len(insert_lines) == len(res["bad-track"]["failures"]), \
        f"Expected {len(res['bad-track']['failures'])} INSERTs (one per gate), got {len(insert_lines)}"

    # Check structure of each INSERT
    for insert_line in insert_lines:
        # Must contain the correct column names
        assert "(track_id, vehicle_class, condition, gate, details)" in insert_line, \
            f"INSERT missing correct columns: {insert_line}"
        # Must not contain incorrect columns
        assert "passed" not in insert_line, f"INSERT incorrectly contains 'passed': {insert_line}"
        assert "failed_gates" not in insert_line, f"INSERT incorrectly contains 'failed_gates': {insert_line}"
        assert "audited_at" not in insert_line, f"INSERT incorrectly contains 'audited_at': {insert_line}"
        # Must end with ::jsonb cast
        assert "::jsonb);" in insert_line, f"INSERT missing ::jsonb cast: {insert_line}"
        # Must have NULL for vehicle_class and condition
        assert "NULL, NULL" in insert_line, f"INSERT missing NULLs for vehicle_class/condition: {insert_line}"
