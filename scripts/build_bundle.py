#!/usr/bin/env python3
"""Build a ManifestV2-compliant session bundle from a capture folder.

Takes the output of ``batch_replay_capture.py`` (flat folder with ``.ibt`` +
``capture_meta.json``) and produces a ``.zip`` ready for the webapp's
``POST /api/v1/bundles`` endpoint.

Usage::

    python scripts/build_bundle.py \\
        --capture-dir output/daytona__MX5/ \\
        --output my_session.zip

    # Or specify an explicit IBT instead of auto-detecting from capture_meta:
    python scripts/build_bundle.py \\
        --ibt ~/Documents/iRacing/telemetry/mx5_daytona.ibt \\
        --track-name "Daytona Road Course" \\
        --car-name "Mazda MX-5" \\
        --output my_session.zip
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA_VERSION = 2
_DEFAULT_SESSION_TYPE = "practice"
_DEFAULT_SIM = "iracing"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalize_key(name: str) -> str:
    """Turn human-readable names into snake_case keys."""
    return name.strip().lower().replace(" ", "_").replace("-", "_").replace("/", "_")


def _logger_version() -> str:
    """Best-effort version stamp."""
    try:
        from telemetry_tool import __version__
        return __version__
    except Exception:
        return "0.0.0-dev"


def _load_capture_meta(capture_dir: Path) -> dict | None:
    meta_path = capture_dir / "capture_meta.json"
    if not meta_path.is_file():
        return None
    with open(meta_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _find_ibt_files(capture_dir: Path) -> list[Path]:
    return sorted(capture_dir.glob("*.ibt"))


def build_bundle(
    *,
    ibt_path: Path,
    track_name: str,
    car_name: str,
    output_path: Path,
    session_type: str = _DEFAULT_SESSION_TYPE,
    sim: str = _DEFAULT_SIM,
    captured_at: str | None = None,
    capture_meta: dict | None = None,
) -> Path:
    """Build the zip and return the output path."""
    if not ibt_path.is_file():
        raise FileNotFoundError(f"IBT file not found: {ibt_path}")

    ibt_sha = _sha256(ibt_path)
    ibt_size = ibt_path.stat().st_size
    now_iso = captured_at or datetime.now(timezone.utc).isoformat(timespec="seconds")

    manifest = {
        "schema_version": _SCHEMA_VERSION,
        "identity": {
            "sim": sim,
            "vehicle_key": _normalize_key(car_name),
            "track_key": _normalize_key(track_name),
            "session_type": session_type,
            "started_at": now_iso,
        },
        "source": {
            "logger_version": _logger_version(),
            "logger_build": None,
            "capture_method": "iracing_ibt",
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
            "vehicle_spec": {},          # resolved server-side from calibration registry
            "track_spec": {"name": track_name},  # regime resolved server-side
            "session_info": {"type": session_type},
            "channels_present": [],
            "lap_count": 0,
            "duration_s": 0.0,
            "extra": {},
        },
    }

    # Include capture_meta as an aux file for provenance
    aux_files = []
    if capture_meta is not None:
        meta_bytes = json.dumps(capture_meta, indent=2).encode("utf-8")
        meta_sha = hashlib.sha256(meta_bytes).hexdigest()
        manifest["files"].append({
            "path": "capture_meta.json",
            "size": len(meta_bytes),
            "sha256": meta_sha,
            "role": "aux",
        })
        aux_files.append(("capture_meta.json", meta_bytes))

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(output_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
        zf.writestr("manifest.json", manifest_bytes)
        zf.write(ibt_path, "telemetry.ibt")
        for name, data in aux_files:
            zf.writestr(name, data)

    print(f"Bundle written: {output_path}")
    print(f"  IBT:      {ibt_path.name} ({ibt_size:,} bytes)")
    print(f"  Checksum: {ibt_sha[:16]}...")
    print(f"  Vehicle:  {car_name} ({_normalize_key(car_name)})")
    print(f"  Track:    {track_name} ({_normalize_key(track_name)})")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Build a ManifestV2 session bundle")
    parser.add_argument("--capture-dir", type=Path, help="Capture folder with .ibt + capture_meta.json")
    parser.add_argument("--ibt", type=Path, help="Explicit IBT file path (alternative to --capture-dir)")
    parser.add_argument("--track-name", type=str, help="Track name (required with --ibt)")
    parser.add_argument("--car-name", type=str, help="Car name (required with --ibt)")
    parser.add_argument("--session-type", type=str, default=_DEFAULT_SESSION_TYPE)
    parser.add_argument("--sim", type=str, default=_DEFAULT_SIM)
    parser.add_argument("--output", "-o", type=Path, required=True, help="Output .zip path")
    args = parser.parse_args()

    if args.capture_dir:
        meta = _load_capture_meta(args.capture_dir)
        ibts = _find_ibt_files(args.capture_dir)
        if not ibts:
            parser.error(f"no .ibt files found in {args.capture_dir}")
        ibt_path = ibts[0]
        track_name = (meta or {}).get("track_name") or args.track_name or "unknown"
        car_name = (meta or {}).get("car_name") or args.car_name or "unknown"
        captured_at = (meta or {}).get("collected_at")
    elif args.ibt:
        if not args.track_name or not args.car_name:
            parser.error("--track-name and --car-name required with --ibt")
        ibt_path = args.ibt
        track_name = args.track_name
        car_name = args.car_name
        captured_at = None
        meta = None
    else:
        parser.error("provide either --capture-dir or --ibt")
        return

    build_bundle(
        ibt_path=Path(ibt_path),
        track_name=track_name,
        car_name=car_name,
        output_path=args.output,
        session_type=args.session_type,
        sim=args.sim,
        captured_at=captured_at,
        capture_meta=meta,
    )


if __name__ == "__main__":
    main()
