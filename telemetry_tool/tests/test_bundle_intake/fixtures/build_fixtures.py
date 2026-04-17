"""Hermetic bundle fixture builder.

Used by conftest.py to construct in-memory ZIP bundles tailored to each
scenario. No binary drift in git history — every fixture is regenerated
from source each test session.
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Canonical vehicle + track specs that satisfy readiness ─────
_FULL_VEHICLE_SPEC = {
    "name": "Mazda MX-5 2024", "klass": "MX5", "drive_layout": "RWD",
    "mass_kg": 1100.0, "wheelbase_m": 2.31,
    "track_front_m": 1.495, "track_rear_m": 1.505,
    "weight_dist_front": 0.52, "aero_cla": 0.35, "cg_height_m": 0.50,
    "brake_bias_front": 0.58, "steer_ratio": 15.0,
    "camber_front_deg": -2.5, "camber_rear_deg": -1.5,
}

_FULL_TRACK_SPEC = {
    "name": "Daytona Road Course", "layout": "road_course",
    "regime": "banked", "expected_max_bank_deg": 31.0,
    "track_length_m": 5726.0,
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _build_manifest(
    *,
    schema_version: int = 2,
    identity_overrides: dict[str, Any] | None = None,
    source_overrides: dict[str, Any] | None = None,
    metadata_overrides: dict[str, Any] | None = None,
    files: list[dict[str, Any]] | None = None,
) -> dict:
    identity = {
        "sim": "iracing",
        "vehicle_key": "iracing_mx5_2024",
        "track_key": "daytona_rc_v5",
        "session_type": "practice",
        "started_at": "2026-04-15T10:20:00+00:00",
    }
    if identity_overrides:
        identity.update(identity_overrides)

    source = {
        "logger_version": "2.3.0",
        "logger_build": "abc123",
        "capture_method": "iracing_ibt",
        "captured_by_user_id": 42,
        "captured_at": "2026-04-15T10:20:00+00:00",
        "client_hostname": "driver-rig",
        "client_os": "Windows 11",
    }
    if source_overrides:
        source.update(source_overrides)

    # v1 contract: vehicle_spec is empty (resolved server-side from calibration
    # registry). track_spec has name only (regime defaults to "flat").
    metadata = {
        "vehicle_spec": {},
        "track_spec": {"name": "Daytona Road Course"},
        "session_info": {"type": "practice"},
        "channels_present": [],
        "lap_count": 0,
        "duration_s": 0.0,
        "extra": {},
    }
    if metadata_overrides:
        # Deep-ish merge: if caller provides vehicle_spec={...} that REPLACES.
        for k, v in metadata_overrides.items():
            metadata[k] = v

    return {
        "schema_version": schema_version,
        "identity": identity,
        "source": source,
        "files": files or [],
        "metadata": metadata,
    }


def build_good_bundle() -> tuple[bytes, dict]:
    """Return (zip_bytes, manifest_dict) for a fully-valid bundle."""
    telemetry_bytes = b"FAKE_IBT_PAYLOAD" * 64   # 1 KB
    analysis_bytes = json.dumps({"notes": "synth"}).encode("utf-8")

    files = [
        {"path": "telemetry.ibt", "size": len(telemetry_bytes),
         "sha256": _sha256(telemetry_bytes), "role": "telemetry"},
        {"path": "analysis.json", "size": len(analysis_bytes),
         "sha256": _sha256(analysis_bytes), "role": "analysis_json"},
    ]
    manifest = _build_manifest(files=files)
    zip_bytes = _zip_with({
        "manifest.json": json.dumps(manifest).encode("utf-8"),
        "telemetry.ibt": telemetry_bytes,
        "analysis.json": analysis_bytes,
    })
    return zip_bytes, manifest


def build_degraded_bundle() -> tuple[bytes, dict]:
    """Valid schema, valid vehicle_key, but sim is unknown → degraded.

    The v1 readiness gate is: sim known + vehicle_key present + track_key
    present + telemetry file. An unknown sim triggers DEGRADED.
    """
    telemetry_bytes = b"FAKE_IBT" * 32
    files = [
        {"path": "telemetry.ibt", "size": len(telemetry_bytes),
         "sha256": _sha256(telemetry_bytes), "role": "telemetry"},
    ]
    manifest = _build_manifest(
        identity_overrides={"sim": "fictional_sim"},   # triggers unknown_sim gate
        files=files,
    )
    zip_bytes = _zip_with({
        "manifest.json": json.dumps(manifest).encode("utf-8"),
        "telemetry.ibt": telemetry_bytes,
    })
    return zip_bytes, manifest


def build_unknown_sim_bundle() -> tuple[bytes, dict]:
    """Valid schema but sim is not in SimKey enum → degraded."""
    telemetry_bytes = b"FAKE_IBT" * 32
    files = [
        {"path": "telemetry.ibt", "size": len(telemetry_bytes),
         "sha256": _sha256(telemetry_bytes), "role": "telemetry"},
    ]
    manifest = _build_manifest(
        identity_overrides={"sim": "fictional_sim"},
        files=files,
    )
    zip_bytes = _zip_with({
        "manifest.json": json.dumps(manifest).encode("utf-8"),
        "telemetry.ibt": telemetry_bytes,
    })
    return zip_bytes, manifest


def build_bad_inner_checksum_bundle() -> tuple[bytes, dict]:
    """Manifest declares sha256 that doesn't match the actual file."""
    telemetry_bytes = b"REAL_BYTES" * 16
    files = [
        {"path": "telemetry.ibt", "size": len(telemetry_bytes),
         "sha256": "0" * 64,   # wrong
         "role": "telemetry"},
    ]
    manifest = _build_manifest(files=files)
    zip_bytes = _zip_with({
        "manifest.json": json.dumps(manifest).encode("utf-8"),
        "telemetry.ibt": telemetry_bytes,
    })
    return zip_bytes, manifest


def build_v1_legacy_bundle() -> tuple[bytes, dict]:
    """Legacy schema_version=1 bundle — must be rejected."""
    telemetry_bytes = b"x" * 16
    manifest = {"schema_version": 1, "notes": "legacy"}
    zip_bytes = _zip_with({
        "manifest.json": json.dumps(manifest).encode("utf-8"),
        "telemetry.ibt": telemetry_bytes,
    })
    return zip_bytes, manifest


def build_no_manifest_bundle() -> bytes:
    """Valid zip but missing manifest.json entirely."""
    return _zip_with({"telemetry.ibt": b"x" * 16})


def build_invalid_json_manifest_bundle() -> bytes:
    """manifest.json present but not valid JSON."""
    return _zip_with({
        "manifest.json": b"{this is not json,}",
        "telemetry.ibt": b"x" * 16,
    })


def build_no_telemetry_bundle() -> tuple[bytes, dict]:
    """Valid metadata but no file with role=telemetry → degraded."""
    aux_bytes = b"auxiliary_blob" * 8
    files = [
        {"path": "notes.txt", "size": len(aux_bytes),
         "sha256": _sha256(aux_bytes), "role": "aux"},
    ]
    manifest = _build_manifest(files=files)
    zip_bytes = _zip_with({
        "manifest.json": json.dumps(manifest).encode("utf-8"),
        "notes.txt": aux_bytes,
    })
    return zip_bytes, manifest


def _zip_with(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def write_bundle_to(path: Path, zip_bytes: bytes) -> str:
    """Persist bundle bytes and return its outer SHA-256."""
    path.write_bytes(zip_bytes)
    return _sha256(zip_bytes)
