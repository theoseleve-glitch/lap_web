#!/usr/bin/env python3
"""Batch replay telemetry capture — extract full 286-var telemetry from iRacing .rpy files.

Usage:
    1. Start iRacing (must be running with any session loaded)
    2. Run: python scripts/batch_replay_capture.py <replay_folder> [output_folder]

The script will:
    - Scan replay_folder for .rpy files
    - For each replay: load it via IRSDK, capture all 286 vars at 60Hz
    - Save as Parquet + CSV in output_folder
    - Move to the next replay automatically

Requirements:
    - iRacing must be running (any session — the replay loading switches context)
    - pyirsdk must be installed: pip install pyirsdk
"""
from __future__ import annotations

import csv
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("replay_capture")

try:
    import irsdk
except ImportError:
    log.error("pyirsdk not installed. Run: pip install pyirsdk")
    sys.exit(1)

import numpy as np

# ── Constants ──────────────────────────────────────────────────────

_RAW_PREFIX = "irsdk__"
_CAPTURE_TIMEOUT_S = 300  # max 5 min per replay before giving up
_SETTLE_TIME_S = 3.0      # wait after loading replay before capturing
_MIN_SAMPLES = 100        # minimum samples to consider a valid capture
_TICK_POLL_S = 0.0005     # poll interval for new data ticks


# ── IRSDK helpers ──────────────────────────────────────────────────

def connect_irsdk(timeout_s: float = 30.0) -> irsdk.IRSDK:
    """Connect to iRacing shared memory. Waits up to timeout_s."""
    ir = irsdk.IRSDK()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if ir.startup():
            log.info("Connected to iRacing IRSDK")
            return ir
        time.sleep(1.0)
    raise RuntimeError(f"Could not connect to iRacing within {timeout_s}s. Is iRacing running?")


def load_replay_file(ir: irsdk.IRSDK, rpy_path: Path) -> bool:
    """Load a .rpy file into iRacing via file open.

    iRacing registers .rpy as a file association. Opening the file
    triggers iRacing to load the replay.
    """
    if not rpy_path.exists():
        log.error("Replay file not found: %s", rpy_path)
        return False

    log.info("Loading replay: %s", rpy_path.name)
    # Use os.startfile on Windows to open .rpy with its registered handler (iRacing)
    try:
        os.startfile(str(rpy_path))
    except Exception as exc:
        log.error("Failed to open replay file: %s", exc)
        return False

    # Wait for replay to be loaded
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        try:
            ir.freeze_var_buffer_latest()
            is_replay = ir["IsReplayPlaying"]
            if is_replay:
                log.info("Replay loaded and playing")
                return True
        except Exception:
            pass
        time.sleep(0.5)

    log.warning("Replay did not start playing within 30s")
    return False


def wait_for_replay_active(ir: irsdk.IRSDK, timeout_s: float = 30.0) -> bool:
    """Wait until the replay is actively playing with valid telemetry."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            ir.freeze_var_buffer_latest()
            is_replay = ir["IsReplayPlaying"]
            speed = ir["Speed"]
            if is_replay and speed is not None and speed > 0.1:
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def set_replay_speed(ir: irsdk.IRSDK, speed: int = 1) -> None:
    """Set replay playback speed (1 = normal, 0 = pause)."""
    try:
        ir.replay_set_play_speed(speed)
        log.info("Replay speed set to %dx", speed)
    except Exception as exc:
        log.debug("Could not set replay speed: %s", exc)


def seek_replay_start(ir: irsdk.IRSDK) -> None:
    """Seek to the beginning of the replay."""
    try:
        ir.replay_set_play_position(0, 0)  # frame 0
        time.sleep(0.5)
        ir.replay_set_play_speed(1)  # normal speed
        log.info("Seeked to replay start")
    except Exception as exc:
        log.debug("Could not seek replay: %s", exc)


def get_var_headers(ir: irsdk.IRSDK) -> list[dict[str, Any]]:
    """Read all variable headers from IRSDK."""
    headers = []
    try:
        for i in range(ir._var_headers_cnt):
            vh = ir._var_headers[i]
            headers.append({
                "name": vh.name,
                "count": vh.count,
                "type": vh.type,
            })
    except Exception as exc:
        log.warning("Error reading var headers: %s", exc)
    return headers


def read_raw_sample(ir: irsdk.IRSDK, var_headers: list[dict]) -> dict[str, Any]:
    """Read all IRSDK variables into a flat dict."""
    ir.freeze_var_buffer_latest()
    row: dict[str, Any] = {}

    for vh in var_headers:
        name = vh["name"]
        count = vh["count"]
        try:
            val = ir[name]
        except Exception:
            val = None

        if count == 1:
            row[f"{_RAW_PREFIX}{name}"] = _safe_value(val)
        else:
            if isinstance(val, (list, tuple)):
                for i, v in enumerate(val):
                    row[f"{_RAW_PREFIX}{name}__{i}"] = _safe_value(v)
                for i in range(len(val), count):
                    row[f"{_RAW_PREFIX}{name}__{i}"] = None
            else:
                row[f"{_RAW_PREFIX}{name}__0"] = _safe_value(val)
                for i in range(1, count):
                    row[f"{_RAW_PREFIX}{name}__{i}"] = None

    row[f"{_RAW_PREFIX}capture_timestamp_utc"] = datetime.now(timezone.utc).isoformat()
    return row


def _safe_value(val: Any) -> Any:
    """Convert IRSDK value to a safe Python type."""
    if val is None:
        return None
    if isinstance(val, (int, float, bool, str)):
        return val
    try:
        f = float(val)
        if not (f == f):  # NaN check
            return None
        return f
    except (TypeError, ValueError):
        return str(val)


def get_session_info(ir: irsdk.IRSDK) -> dict[str, str]:
    """Extract track name, car name from session info."""
    info = {"track_name": "unknown", "car_name": "unknown", "driver_name": "unknown"}
    try:
        weekend = ir["WeekendInfo"]
        if weekend:
            info["track_name"] = weekend.get("TrackDisplayName") or weekend.get("TrackName", "unknown")

        driver_info = ir["DriverInfo"]
        if driver_info:
            drivers = driver_info.get("Drivers", [])
            # In replay, the camera target is usually the driver we want
            cam_idx = ir["CamCarIdx"]
            for d in drivers:
                if d.get("CarIdx") == cam_idx:
                    info["car_name"] = d.get("CarScreenName") or d.get("CarPath", "unknown")
                    info["driver_name"] = d.get("UserName", "unknown")
                    break
            if info["car_name"] == "unknown" and drivers:
                info["car_name"] = drivers[0].get("CarScreenName", "unknown")
                info["driver_name"] = drivers[0].get("UserName", "unknown")
    except Exception as exc:
        log.debug("Error reading session info: %s", exc)
    return info


# ── Capture loop ──────────────────────────────────────────────────

def capture_replay(ir: irsdk.IRSDK, var_headers: list[dict],
                   max_duration_s: float = _CAPTURE_TIMEOUT_S) -> list[dict[str, Any]]:
    """Capture telemetry samples while replay is playing.

    Stops when replay stops or timeout is reached.
    Returns list of raw sample dicts.
    """
    samples: list[dict[str, Any]] = []
    start_time = time.monotonic()
    last_tick = None
    stale_count = 0

    log.info("Starting capture (max %.0fs)...", max_duration_s)

    while time.monotonic() - start_time < max_duration_s:
        try:
            ir.freeze_var_buffer_latest()

            # Check if replay is still playing
            is_replay = ir["IsReplayPlaying"]
            if not is_replay and len(samples) > _MIN_SAMPLES:
                log.info("Replay ended after %d samples", len(samples))
                break

            # Check for new tick (avoid duplicate samples)
            try:
                tick = ir["SessionTick"]
            except Exception:
                tick = None

            if tick is not None and tick == last_tick:
                time.sleep(_TICK_POLL_S)
                continue

            last_tick = tick

            # Capture
            row = read_raw_sample(ir, var_headers)
            samples.append(row)

            # Progress logging every 1000 samples
            if len(samples) % 1000 == 0:
                elapsed = time.monotonic() - start_time
                speed = ir["Speed"]
                lap = ir["Lap"]
                log.info("  %d samples (%.1fs elapsed, speed=%.1f, lap=%s)",
                         len(samples), elapsed, speed or 0, lap)

            # Check for stale data (replay might be paused)
            speed = ir["Speed"]
            if speed is not None and speed < 0.01:
                stale_count += 1
                if stale_count > 300:  # 5 seconds of no movement
                    log.info("Replay appears stalled after %d samples", len(samples))
                    break
            else:
                stale_count = 0

        except Exception as exc:
            log.debug("Capture error: %s", exc)
            time.sleep(0.01)

    elapsed = time.monotonic() - start_time
    log.info("Capture complete: %d samples in %.1fs (%.1f Hz)",
             len(samples), elapsed, len(samples) / max(elapsed, 0.1))
    return samples


def save_capture(samples: list[dict], session_info: dict,
                 rpy_name: str, output_dir: Path) -> Path | None:
    """Save captured telemetry as CSV + metadata JSON."""
    if len(samples) < _MIN_SAMPLES:
        log.warning("Only %d samples — skipping save", len(samples))
        return None

    # Build output filename from replay name + track + car
    safe_name = rpy_name.replace(".rpy", "")
    track = session_info.get("track_name", "unknown").replace(" ", "_").replace("/", "_")
    car = session_info.get("car_name", "unknown").replace(" ", "_").replace("/", "_")
    folder_name = f"{safe_name}__{track}__{car}"
    out_path = output_dir / folder_name
    out_path.mkdir(parents=True, exist_ok=True)

    # Save CSV
    csv_path = out_path / "telemetry_raw.csv"
    fieldnames = list(samples[0].keys())
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(samples)
    log.info("Saved: %s (%d rows, %d cols)", csv_path, len(samples), len(fieldnames))

    # Save metadata
    meta = {
        "source_replay": rpy_name,
        "track_name": session_info.get("track_name"),
        "car_name": session_info.get("car_name"),
        "driver_name": session_info.get("driver_name"),
        "sample_count": len(samples),
        "column_count": len(fieldnames),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "capture_type": "replay",
    }
    meta_path = out_path / "capture_meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    return out_path


# ── Batch orchestrator ────────────────────────────────────────────

def batch_capture(replay_dir: Path, output_dir: Path,
                  skip_existing: bool = True) -> None:
    """Process all .rpy files in a directory."""
    rpy_files = sorted(replay_dir.glob("*.rpy"))
    if not rpy_files:
        log.error("No .rpy files found in %s", replay_dir)
        return

    log.info("Found %d replay files in %s", len(rpy_files), replay_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Connect to iRacing
    ir = connect_irsdk()
    var_headers = get_var_headers(ir)
    log.info("IRSDK connected: %d variables available", len(var_headers))

    results = {"success": 0, "skipped": 0, "failed": 0, "details": []}

    for i, rpy_path in enumerate(rpy_files, 1):
        log.info("=" * 60)
        log.info("[%d/%d] %s", i, len(rpy_files), rpy_path.name)
        log.info("=" * 60)

        # Check if already captured
        if skip_existing:
            existing = list(output_dir.glob(f"{rpy_path.stem}__*"))
            if existing:
                log.info("  Already captured — skipping")
                results["skipped"] += 1
                results["details"].append({"file": rpy_path.name, "status": "skipped"})
                continue

        try:
            # Load replay
            if not load_replay_file(ir, rpy_path):
                log.warning("  Failed to load replay")
                results["failed"] += 1
                results["details"].append({"file": rpy_path.name, "status": "load_failed"})
                continue

            # Wait for replay to settle
            time.sleep(_SETTLE_TIME_S)

            # Wait for active telemetry
            if not wait_for_replay_active(ir, timeout_s=15.0):
                log.warning("  Replay not producing telemetry")
                results["failed"] += 1
                results["details"].append({"file": rpy_path.name, "status": "no_telemetry"})
                continue

            # Get session info
            session_info = get_session_info(ir)
            log.info("  Track: %s, Car: %s, Driver: %s",
                     session_info["track_name"], session_info["car_name"],
                     session_info["driver_name"])

            # Refresh var headers (may change between sessions)
            var_headers = get_var_headers(ir)

            # Seek to start and set normal speed
            seek_replay_start(ir)
            time.sleep(1.0)
            set_replay_speed(ir, 1)

            # Wait for replay to actually start moving
            if not wait_for_replay_active(ir, timeout_s=10.0):
                log.warning("  Replay not moving after seek")
                results["failed"] += 1
                results["details"].append({"file": rpy_path.name, "status": "not_moving"})
                continue

            # Capture
            samples = capture_replay(ir, var_headers)

            # Save
            out_path = save_capture(samples, session_info, rpy_path.name, output_dir)
            if out_path:
                results["success"] += 1
                results["details"].append({
                    "file": rpy_path.name,
                    "status": "success",
                    "samples": len(samples),
                    "track": session_info["track_name"],
                    "car": session_info["car_name"],
                    "driver": session_info["driver_name"],
                    "output": str(out_path),
                })
            else:
                results["failed"] += 1
                results["details"].append({"file": rpy_path.name, "status": "too_few_samples"})

        except KeyboardInterrupt:
            log.info("Interrupted by user")
            break
        except Exception as exc:
            log.error("  Error processing %s: %s", rpy_path.name, exc, exc_info=True)
            results["failed"] += 1
            results["details"].append({"file": rpy_path.name, "status": "error", "error": str(exc)})

        # Brief pause between replays
        time.sleep(2.0)

    # Summary
    log.info("")
    log.info("=" * 60)
    log.info("BATCH COMPLETE")
    log.info("  Success: %d", results["success"])
    log.info("  Skipped: %d", results["skipped"])
    log.info("  Failed:  %d", results["failed"])
    log.info("=" * 60)

    # Save results summary
    summary_path = output_dir / "batch_summary.json"
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2)
    log.info("Summary saved to %s", summary_path)


# ── Entry point ───────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python batch_replay_capture.py <replay_folder> [output_folder]")
        print()
        print("  replay_folder: directory containing .rpy files")
        print("  output_folder: where to save captured telemetry (default: ./replay_captures)")
        print()
        print("iRacing must be running before starting this script.")
        sys.exit(1)

    replay_dir = Path(sys.argv[1])
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("replay_captures")

    if not replay_dir.exists():
        log.error("Replay directory does not exist: %s", replay_dir)
        sys.exit(1)

    batch_capture(replay_dir, output_dir)
