"""Build a ManifestV2 session bundle from a capture/pipeline output folder.

Importable version of ``scripts/build_bundle.py`` — same logic, no CLI overhead.
Called from ``main.py`` after pipeline finalize and from ``batch_replay_capture.py``
after IBT capture.
"""
from __future__ import annotations

import hashlib
import json
import logging
import platform
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 2
_DEFAULT_SIM = "iracing"
_DEFAULT_SESSION_TYPE = "practice"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalize_key(name: str) -> str:
    return name.strip().lower().replace(" ", "_").replace("-", "_").replace("/", "_")


def _logger_version() -> str:
    try:
        from telemetry_tool import __version__   # type: ignore
        return __version__
    except Exception:
        return "0.0.0-dev"


def build_session_bundle(
    *,
    ibt_path: Path,
    track_name: str,
    car_name: str,
    output_dir: Path | None = None,
    session_type: str = _DEFAULT_SESSION_TYPE,
    sim: str = _DEFAULT_SIM,
    captured_at: str | None = None,
    capture_meta: dict[str, Any] | None = None,
) -> Path:
    """Build a ManifestV2-compliant zip and return its path.

    The output lands in ``output_dir`` (defaults to ``ibt_path.parent``).
    Filename is ``<track_key>_<vehicle_key>.zip``.
    """
    ibt_path = Path(ibt_path)
    if not ibt_path.is_file():
        raise FileNotFoundError(f"IBT file not found: {ibt_path}")

    output_dir = Path(output_dir) if output_dir else ibt_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    vehicle_key = _normalize_key(car_name)
    track_key = _normalize_key(track_name)
    out_path = output_dir / f"{track_key}_{vehicle_key}.zip"

    ibt_sha = _sha256(ibt_path)
    ibt_size = ibt_path.stat().st_size
    now_iso = captured_at or datetime.now(timezone.utc).isoformat(timespec="seconds")

    manifest: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "identity": {
            "sim": sim,
            "vehicle_key": vehicle_key,
            "track_key": track_key,
            "session_type": session_type,
            "started_at": now_iso,
        },
        "source": {
            "logger_version": _logger_version(),
            "logger_build": None,
            "capture_method": f"{sim}_ibt",
            "captured_by_user_id": None,
            "captured_at": now_iso,
            "client_hostname": platform.node(),
            "client_os": f"{platform.system()} {platform.release()}",
        },
        "files": [
            {
                "path": "telemetry.ibt",
                "size": ibt_size,
                "sha256": ibt_sha,
                "role": "telemetry",
            },
        ],
        "metadata": {
            "vehicle_spec": {},
            "track_spec": {"name": track_name},
            "session_info": {"type": session_type},
            "channels_present": [],
            "lap_count": 0,
            "duration_s": 0.0,
            "extra": {},
        },
    }

    aux_entries: list[tuple[str, bytes]] = []
    if capture_meta is not None:
        meta_bytes = json.dumps(capture_meta, indent=2).encode("utf-8")
        manifest["files"].append({
            "path": "capture_meta.json",
            "size": len(meta_bytes),
            "sha256": _sha256_bytes(meta_bytes),
            "role": "aux",
        })
        aux_entries.append(("capture_meta.json", meta_bytes))

    with zipfile.ZipFile(out_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.write(ibt_path, "telemetry.ibt")
        for name, data in aux_entries:
            zf.writestr(name, data)

    logger.info("[SYNC] Bundle built: %s (%d bytes)", out_path.name, out_path.stat().st_size)
    return out_path


def compute_bundle_checksum(bundle_path: Path) -> str:
    """Compute the outer SHA-256 of a bundle zip."""
    return _sha256(bundle_path)
