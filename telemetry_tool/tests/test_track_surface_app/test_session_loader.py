"""Tests for SessionLoader — translates SaaS session rows to DatasetEntry."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from track_surface_app.session_loader import (
    NOT_SUPPORTED_METADATA_INVALID,
    NOT_SUPPORTED_SOURCE_FILE_MISSING,
    NOT_SUPPORTED_SOURCE_FORMAT_NOT_IBT,
    NOT_SUPPORTED_SOURCE_PATH_MISSING,
    NOT_SUPPORTED_TRACK_SPEC_MISSING,
    NOT_SUPPORTED_VEHICLE_SPEC_MISSING,
    SessionLoader,
    SessionNotFoundError,
)


# Fully populated vehicle_spec suitable for VehicleSpec(...) construction.
_VALID_VEHICLE_SPEC = {
    "name": "Mazda MX-5 2024",
    "klass": "MX5",
    "drive_layout": "RWD",
    "mass_kg": 1100.0,
    "wheelbase_m": 2.31,
    "track_front_m": 1.495,
    "track_rear_m": 1.505,
    "weight_dist_front": 0.52,
    "aero_cla": 0.35,
    "cg_height_m": 0.50,
    "brake_bias_front": 0.58,
    "steer_ratio": 15.0,
    "camber_front_deg": -2.5,
    "camber_rear_deg": -1.5,
}

_VALID_TRACK_SPEC = {
    "name": "Daytona Road Course",
    "layout": "road_course",
    "regime": "banked",
    "expected_max_bank_deg": 31.0,
    "track_length_m": 5726.0,
}


@pytest.fixture
def sqlite_conn():
    """In-memory sqlite with a minimal sessions + tracks schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE sessions (
            session_id INTEGER PRIMARY KEY,
            source_path TEXT,
            analysis_json TEXT,
            track_id TEXT,
            kart_id INTEGER
        );
        CREATE TABLE tracks (
            track_id TEXT PRIMARY KEY,
            track_name TEXT,
            lap_length_m REAL
        );
        """
    )
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def loader(sqlite_conn):
    return SessionLoader(conn_factory=lambda: sqlite_conn, set_workspace_context_fn=None)


def _insert_session(conn, *, session_id=1, source_path=None, analysis_json=None,
                    track_id="daytona_rc", kart_id=None):
    conn.execute(
        """
        INSERT INTO sessions (session_id, source_path, analysis_json, track_id, kart_id)
        VALUES (:sid, :src, :aj, :tid, :kid)
        """,
        {
            "sid": session_id,
            "src": source_path,
            "aj": json.dumps(analysis_json) if analysis_json else None,
            "tid": track_id,
            "kid": kart_id,
        },
    )
    conn.commit()


class TestSessionNotFound:
    def test_missing_row_raises(self, loader):
        with pytest.raises(SessionNotFoundError):
            loader.load(session_id=42, workspace_id=1)


class TestSourcePathGating:
    def test_missing_source_path(self, loader, sqlite_conn):
        _insert_session(sqlite_conn, session_id=1, source_path=None)
        result = loader.load(session_id=1, workspace_id=1)
        assert not result.is_supported
        assert result.reason == NOT_SUPPORTED_SOURCE_PATH_MISSING

    def test_csv_source_rejected(self, loader, sqlite_conn, tmp_path):
        csv = tmp_path / "sess.csv"
        csv.write_text("fake,csv")
        _insert_session(sqlite_conn, session_id=1, source_path=str(csv))
        result = loader.load(session_id=1, workspace_id=1)
        assert not result.is_supported
        assert result.reason == NOT_SUPPORTED_SOURCE_FORMAT_NOT_IBT

    def test_ibt_file_missing(self, loader, sqlite_conn, tmp_path):
        bogus = tmp_path / "never_existed.ibt"
        _insert_session(sqlite_conn, session_id=1, source_path=str(bogus))
        result = loader.load(session_id=1, workspace_id=1)
        assert not result.is_supported
        assert result.reason == NOT_SUPPORTED_SOURCE_FILE_MISSING


class TestMetadataGating:
    def test_vehicle_spec_missing(self, loader, sqlite_conn, tmp_path):
        ibt = tmp_path / "sess.ibt"
        ibt.write_bytes(b"\x00" * 16)   # file must exist but content not needed
        aj = {"track_spec": _VALID_TRACK_SPEC}   # no vehicle_spec
        _insert_session(sqlite_conn, session_id=1, source_path=str(ibt),
                        analysis_json=aj)
        result = loader.load(session_id=1, workspace_id=1)
        assert not result.is_supported
        assert result.reason == NOT_SUPPORTED_VEHICLE_SPEC_MISSING

    def test_vehicle_spec_missing_field_returns_not_supported(self, loader, sqlite_conn, tmp_path):
        ibt = tmp_path / "sess.ibt"
        ibt.write_bytes(b"\x00" * 16)
        incomplete = dict(_VALID_VEHICLE_SPEC)
        del incomplete["mass_kg"]
        aj = {"track_spec": _VALID_TRACK_SPEC, "vehicle_spec": incomplete}
        _insert_session(sqlite_conn, session_id=1, source_path=str(ibt),
                        analysis_json=aj)
        result = loader.load(session_id=1, workspace_id=1)
        assert not result.is_supported
        assert result.reason == NOT_SUPPORTED_VEHICLE_SPEC_MISSING
        assert "mass_kg" in (result.detail or "")

    def test_invalid_vehicle_spec_values(self, loader, sqlite_conn, tmp_path):
        ibt = tmp_path / "sess.ibt"
        ibt.write_bytes(b"\x00" * 16)
        bad = dict(_VALID_VEHICLE_SPEC)
        bad["drive_layout"] = "HYBRID"   # not in {RWD, FWD, AWD}
        aj = {"track_spec": _VALID_TRACK_SPEC, "vehicle_spec": bad}
        _insert_session(sqlite_conn, session_id=1, source_path=str(ibt),
                        analysis_json=aj)
        result = loader.load(session_id=1, workspace_id=1)
        assert not result.is_supported
        # VehicleSpec rejects bad drive_layout; we surface it as vehicle_spec_missing
        # (since the builder was unable to construct it).
        assert result.reason in (
            NOT_SUPPORTED_VEHICLE_SPEC_MISSING,
            NOT_SUPPORTED_METADATA_INVALID,
        )


class TestTrackSpecFallback:
    def test_track_spec_from_analysis_json(self, loader, sqlite_conn, tmp_path):
        ibt = tmp_path / "sess.ibt"
        ibt.write_bytes(b"\x00" * 16)
        aj = {"track_spec": _VALID_TRACK_SPEC, "vehicle_spec": _VALID_VEHICLE_SPEC}
        _insert_session(sqlite_conn, session_id=1, source_path=str(ibt),
                        analysis_json=aj)
        result = loader.load(session_id=1, workspace_id=1)
        assert result.is_supported
        assert result.entry.track.regime == "banked"
        assert result.entry.track.name == "Daytona Road Course"

    def test_track_spec_fallback_from_tracks_table(self, loader, sqlite_conn, tmp_path):
        ibt = tmp_path / "sess.ibt"
        ibt.write_bytes(b"\x00" * 16)
        sqlite_conn.execute(
            "INSERT INTO tracks (track_id, track_name, lap_length_m) VALUES (?,?,?)",
            ("mytrack", "My Circuit", 3820.0),
        )
        sqlite_conn.commit()
        aj = {"vehicle_spec": _VALID_VEHICLE_SPEC}   # no track_spec
        _insert_session(sqlite_conn, session_id=1, source_path=str(ibt),
                        analysis_json=aj, track_id="mytrack")
        result = loader.load(session_id=1, workspace_id=1)
        assert result.is_supported
        assert result.entry.track.name == "My Circuit"
        assert result.entry.track.regime == "flat"    # default fallback

    def test_track_spec_missing_when_no_json_and_no_track_id(self, loader, sqlite_conn, tmp_path):
        ibt = tmp_path / "sess.ibt"
        ibt.write_bytes(b"\x00" * 16)
        aj = {"vehicle_spec": _VALID_VEHICLE_SPEC}
        _insert_session(sqlite_conn, session_id=1, source_path=str(ibt),
                        analysis_json=aj, track_id=None)
        result = loader.load(session_id=1, workspace_id=1)
        assert not result.is_supported
        assert result.reason == NOT_SUPPORTED_TRACK_SPEC_MISSING


class TestSupportedEntry:
    def test_full_round_trip_produces_valid_entry(self, loader, sqlite_conn, tmp_path):
        ibt = tmp_path / "sess.ibt"
        ibt.write_bytes(b"\x00" * 16)
        aj = {"track_spec": _VALID_TRACK_SPEC, "vehicle_spec": _VALID_VEHICLE_SPEC}
        _insert_session(sqlite_conn, session_id=42, source_path=str(ibt),
                        analysis_json=aj)
        result = loader.load(session_id=42, workspace_id=7)
        assert result.is_supported
        entry = result.entry
        assert entry.id == "saas_session_42"
        assert entry.ibt_path == str(ibt)
        assert entry.group in {"A_banked", "F_other"}   # banked regime → A_banked
        assert entry.vehicle.klass == "MX5"
        assert entry.track.regime == "banked"
