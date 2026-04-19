#!/usr/bin/env python3
"""Capture a concise runtime snapshot from a running iRacing simulator."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import irsdk
import psutil


KEYWORDS = (
    "track",
    "surface",
    "wet",
    "rubber",
    "marble",
    "dirt",
    "grip",
    "weather",
)

TELEM_KEYS = [
    "SessionState",
    "SessionNum",
    "SessionFlags",
    "IsOnTrack",
    "IsOnTrackCar",
    "PlayerTrackSurface",
    "PlayerTrackSurfaceMaterial",
    "TrackTemp",
    "TrackTempCrew",
    "AirTemp",
    "TrackWetness",
    "Precipitation",
    "WeatherDeclaredWet",
    "ReplayFrameNum",
    "CamCarIdx",
    "CamCameraNumber",
    "CamGroupNumber",
]


def find_iracing_process() -> psutil.Process:
    for proc in psutil.process_iter(["name", "exe"]):
        name = (proc.info.get("name") or "").lower()
        if name == "iracingsim64dx11.exe":
            return proc
    raise RuntimeError("iRacingSim64DX11.exe is not running")


def collect_runtime_snapshot(pid: int) -> dict[str, object]:
    proc = psutil.Process(pid)
    result: dict[str, object] = {
        "pid": pid,
        "name": proc.name(),
        "exe": proc.exe(),
    }

    try:
        files = [entry.path for entry in proc.open_files()]
    except Exception as exc:
        files = [f"<open_files unavailable: {type(exc).__name__}: {exc}>"]
    result["open_files"] = files
    result["open_laguna_files"] = [path for path in files if "lagunaseca" in path.lower()]

    ir = irsdk.IRSDK()
    if not ir.startup():
        raise RuntimeError("irsdk failed to connect even though the simulator process is running")

    weekend_info = ir["WeekendInfo"] or {}
    result["weekend_info"] = weekend_info

    telem = {}
    for key in TELEM_KEYS:
        try:
            telem[key] = ir[key]
        except Exception as exc:
            telem[key] = f"<error: {type(exc).__name__}: {exc}>"
    result["telemetry"] = telem

    session_yaml_path = Path("artifacts/iracing_runtime_session_info.yaml")
    session_yaml_path.parent.mkdir(parents=True, exist_ok=True)
    ir.parse_to(str(session_yaml_path))
    raw_session = session_yaml_path.read_text(encoding="cp1252", errors="ignore")
    result["session_info_yaml_path"] = str(session_yaml_path)
    result["session_info_matches"] = [
        line for line in raw_session.splitlines() if any(keyword in line.lower() for keyword in KEYWORDS)
    ]

    ir.shutdown()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, help="Optional explicit iRacing process ID")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("artifacts/iracing_runtime_probe.json"),
        help="Output JSON path",
    )
    args = parser.parse_args()

    if args.pid is not None:
        pid = args.pid
    else:
        pid = find_iracing_process().pid

    snapshot = collect_runtime_snapshot(pid)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    print(json.dumps(snapshot, indent=2))


if __name__ == "__main__":
    main()
