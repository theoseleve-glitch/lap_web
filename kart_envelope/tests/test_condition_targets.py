"""Tests for condition-adjusted target lap time resolution."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from kart_envelope.config import default_config
from kart_envelope.ingest.metadata import SessionMetadata
from kart_envelope.pipeline import (
    _parse_target_time_seconds,
    _resolve_session_target_lap_time,
)


def test_parse_target_time_seconds_formats() -> None:
    assert _parse_target_time_seconds("42.513") == pytest.approx(42.513, abs=1e-9)
    assert _parse_target_time_seconds("1.03.040") == pytest.approx(63.04, abs=1e-9)
    assert _parse_target_time_seconds("1.09.4") == pytest.approx(69.4, abs=1e-9)
    assert _parse_target_time_seconds("1.134.4") == pytest.approx(73.44, abs=1e-9)
    assert _parse_target_time_seconds("1:23.5") == pytest.approx(83.5, abs=1e-9)


def test_resolve_target_uses_condition_table(tmp_path: Path) -> None:
    csv_path = tmp_path / "condition_targets.csv"
    csv_path.write_text(
        "track,condition,target_lap_s\n"
        "OK,wet,1.23.5\n",
        encoding="utf-8",
    )
    cfg = replace(
        default_config(),
        sensitivity_condition_targets_csv=str(csv_path),
        sensitivity_target_lap_time_s=43.4,
    )
    meta = SessionMetadata(
        session_file="OK_R1.csv",
        track_name="OK",
        condition_label="wet",
        track_record_s=63.097,
    )
    assert _resolve_session_target_lap_time(cfg, meta) == pytest.approx(83.5, abs=1e-9)


def test_resolve_target_falls_back_to_cfg_and_record(tmp_path: Path) -> None:
    cfg = replace(
        default_config(),
        sensitivity_condition_targets_csv=str(tmp_path / "missing.csv"),
        sensitivity_target_lap_time_s=43.4,
    )
    meta = SessionMetadata(
        session_file="CKS_FP+Q.csv",
        track_name="CKS",
        condition_label="dry",
        track_record_s=42.513,
    )
    assert _resolve_session_target_lap_time(cfg, meta) == pytest.approx(43.4, abs=1e-9)
