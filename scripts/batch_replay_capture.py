#!/usr/bin/env python3
"""Batch replay → .ibt extraction for iRacing.

Automates the tedious "open replay, play at 1x, wait, collect .ibt" loop
for 200+ alien .rpy / .rpy.zip files.

Usage:
    1. Start iRacing (any session — even main menu is fine)
    2. Enable disk telemetry logging in iRacing options (Options → Misc)
    3. Run:
       python scripts/batch_replay_capture.py <replay_folder> [output_folder]

       # Also handles .rpy.zip files:
       python scripts/batch_replay_capture.py D:/replays ./ibt_output

       # Faster processing (2x replay speed — .ibt may have gaps on some cars):
       python scripts/batch_replay_capture.py D:/replays ./ibt_output --speed 2

       # Also capture via IRSDK shared memory (CSV fallback):
       python scripts/batch_replay_capture.py D:/replays ./ibt_output --also-capture

What it does for each .rpy:
    1. Snapshots iRacing telemetry dir (knows what .ibt files exist before)
    2. Opens the .rpy via os.startfile (iRacing's file association loads it)
    3. Monitors replay state via IRSDK — waits for it to finish
    4. Diffs telemetry dir — finds the new .ibt file(s)
    5. Copies new .ibt(s) to output folder, organized by track/car/driver

Requirements:
    pip install pyirsdk
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
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

# ── Constants ──────────────────────────────────────────────────────

_RAW_PREFIX = "irsdk__"
_CAPTURE_TIMEOUT_S = 600   # max 10 min per replay before giving up
_SETTLE_TIME_S = 4.0       # wait after loading replay before acting
_MIN_SAMPLES = 100         # minimum samples for IRSDK capture fallback
_TICK_POLL_S = 0.0005      # poll interval for new data ticks
_IBT_WAIT_AFTER_S = 8.0    # extra wait after replay ends for .ibt flush
_INTER_REPLAY_S = 3.0      # pause between replays


# ── iRacing telemetry directory detection ─────────────────────────

def find_iracing_telemetry_dir() -> Path | None:
    """Auto-detect iRacing's telemetry output directory.

    Standard path: ~/Documents/iRacing/telemetry/
    Falls back to searching common locations.
    """
    # Standard location
    docs = Path.home() / "Documents" / "iRacing" / "telemetry"
    if docs.exists():
        return docs

    # OneDrive-redirected Documents
    for candidate in [
        Path.home() / "OneDrive" / "Documents" / "iRacing" / "telemetry",
        Path(os.environ.get("USERPROFILE", "")) / "Documents" / "iRacing" / "telemetry",
    ]:
        if candidate.exists():
            return candidate

    # Check registry for custom install path (rare)
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\iRacing.com\iRacingSim")
        install_dir, _ = winreg.QueryValueEx(key, "InstallDir")
        telem = Path(install_dir) / "telemetry"
        if telem.exists():
            return telem
    except Exception:
        pass

    return None


def snapshot_ibt_files(telemetry_dir: Path) -> dict[str, float]:
    """Return {filename: mtime} for all .ibt files currently in the dir."""
    snapshot = {}
    for f in telemetry_dir.glob("*.ibt"):
        try:
            snapshot[f.name] = f.stat().st_mtime
        except OSError:
            pass
    return snapshot


def find_new_ibts(telemetry_dir: Path,
                  before: dict[str, float]) -> list[Path]:
    """Find .ibt files created or modified since the 'before' snapshot."""
    new_files = []
    for f in telemetry_dir.glob("*.ibt"):
        try:
            name = f.name
            mtime = f.stat().st_mtime
            if name not in before or mtime > before[name] + 0.5:
                new_files.append(f)
        except OSError:
            pass
    return sorted(new_files, key=lambda p: p.stat().st_mtime)


# ── .rpy.zip extraction ──────────────────────────────────────────

def extract_rpy_from_zip(zip_path: Path, temp_dir: Path) -> Path | None:
    """Extract the .rpy file from a .rpy.zip archive.

    Returns path to extracted .rpy, or None on failure.
    """
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            rpy_members = [m for m in zf.namelist() if m.lower().endswith(".rpy")]
            if not rpy_members:
                log.warning("No .rpy file found inside %s", zip_path.name)
                return None
            # Extract the first (usually only) .rpy
            member = rpy_members[0]
            zf.extract(member, temp_dir)
            extracted = temp_dir / member
            log.info("  Extracted: %s from %s", member, zip_path.name)
            return extracted
    except (zipfile.BadZipFile, Exception) as exc:
        log.error("Failed to extract %s: %s", zip_path.name, exc)
        return None


def collect_replay_files(replay_dir: Path, temp_dir: Path) -> list[tuple[Path, str]]:
    """Collect all .rpy and .rpy.zip files, extracting zips.

    Returns list of (rpy_path, original_name) tuples.
    """
    entries: list[tuple[Path, str]] = []

    # Direct .rpy files
    for f in sorted(replay_dir.glob("*.rpy")):
        entries.append((f, f.name))

    # .rpy.zip files → extract
    for f in sorted(replay_dir.glob("*.rpy.zip")):
        extracted = extract_rpy_from_zip(f, temp_dir)
        if extracted:
            entries.append((extracted, f.name))

    # Also check for generic .zip that might contain .rpy
    for f in sorted(replay_dir.glob("*.zip")):
        if f.name.endswith(".rpy.zip"):
            continue  # already handled
        extracted = extract_rpy_from_zip(f, temp_dir)
        if extracted:
            entries.append((extracted, f.name))

    return entries


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
    """Load a .rpy file into iRacing via file association.

    os.startfile triggers iRacing to load the replay.
    """
    if not rpy_path.exists():
        log.error("Replay file not found: %s", rpy_path)
        return False

    log.info("Loading replay: %s", rpy_path.name)
    try:
        os.startfile(str(rpy_path))
    except Exception as exc:
        log.error("Failed to open replay file: %s", exc)
        return False

    # Wait for replay to appear
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        try:
            ir.freeze_var_buffer_latest()
            is_replay = ir["IsReplayPlaying"]
            if is_replay:
                log.info("  Replay loaded and playing")
                return True
        except Exception:
            pass
        time.sleep(0.5)

    log.warning("  Replay did not start playing within 30s")
    return False


def wait_for_replay_active(ir: irsdk.IRSDK, timeout_s: float = 30.0) -> bool:
    """Wait until replay is actively producing telemetry."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            ir.freeze_var_buffer_latest()
            is_replay = ir["IsReplayPlaying"]
            session_time = ir["SessionTime"]
            if is_replay and session_time is not None and session_time > 0:
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def set_replay_speed(ir: irsdk.IRSDK, speed: int = 1) -> None:
    """Set replay playback speed (1=normal, 2/4/8/16=fast)."""
    try:
        ir.replay_set_play_speed(speed)
        log.info("  Replay speed: %dx", speed)
    except Exception as exc:
        log.debug("Could not set replay speed: %s", exc)


def seek_replay_start(ir: irsdk.IRSDK) -> None:
    """Seek to the beginning of the replay."""
    try:
        ir.replay_set_play_position(0, 0)
        time.sleep(0.5)
    except Exception as exc:
        log.debug("Could not seek replay: %s", exc)


def get_session_info(ir: irsdk.IRSDK) -> dict[str, str]:
    """Extract track, car, driver from IRSDK session info."""
    info = {"track_name": "unknown", "car_name": "unknown", "driver_name": "unknown"}
    try:
        weekend = ir["WeekendInfo"]
        if weekend:
            info["track_name"] = (
                weekend.get("TrackDisplayName")
                or weekend.get("TrackName", "unknown")
            )

        driver_info = ir["DriverInfo"]
        if driver_info:
            drivers = driver_info.get("Drivers", [])
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


def wait_for_replay_end(ir: irsdk.IRSDK, speed: int = 1,
                        timeout_s: float = _CAPTURE_TIMEOUT_S) -> str:
    """Wait until the replay stops playing or times out.

    Returns reason: "ended", "stalled", "timeout", "disconnected"
    """
    start = time.monotonic()
    stale_ticks = 0
    last_session_time = None
    last_log_time = start

    while time.monotonic() - start < timeout_s:
        try:
            ir.freeze_var_buffer_latest()
        except Exception:
            return "disconnected"

        is_replay = ir["IsReplayPlaying"]
        if not is_replay:
            return "ended"

        # Track progress
        session_time = ir["SessionTime"]
        lap = ir["Lap"]
        lap_pct = ir["LapDistPct"]

        # Log progress every 15s
        now = time.monotonic()
        if now - last_log_time > 15.0:
            elapsed = now - start
            pct_str = f"{lap_pct * 100:.1f}%" if lap_pct else "?"
            log.info("    [%.0fs] Lap %s, %.1f%% through lap, session_t=%.1f",
                     elapsed, lap, float(pct_str.replace("%", "")) if lap_pct else 0,
                     session_time or 0)
            last_log_time = now

        # Detect stall (session time not advancing)
        if session_time is not None:
            if last_session_time is not None and abs(session_time - last_session_time) < 0.01:
                stale_ticks += 1
                if stale_ticks > 100:  # ~10s of no progress
                    return "stalled"
            else:
                stale_ticks = 0
            last_session_time = session_time

        time.sleep(0.1)

    return "timeout"


# ── Optional IRSDK shared-memory capture (CSV fallback) ──────────

def get_var_headers(ir: irsdk.IRSDK) -> list[dict[str, Any]]:
    """Read all variable headers from IRSDK."""
    headers = []
    try:
        var_headers = getattr(ir, '_IRSDK__var_headers', None) or getattr(ir, '_var_headers', None)
        if var_headers:
            for vh in var_headers:
                headers.append({"name": vh.name, "count": vh.count, "type": vh.type})
        elif hasattr(ir, 'var_headers_names'):
            for name in ir.var_headers_names:
                headers.append({"name": name, "count": 1, "type": 0})
    except Exception as exc:
        log.warning("Error reading var headers: %s", exc)
    return headers


def _safe_value(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, (int, float, bool, str)):
        return val
    try:
        f = float(val)
        return None if f != f else f  # NaN → None
    except (TypeError, ValueError):
        return str(val)


def read_raw_sample(ir: irsdk.IRSDK, var_headers: list[dict]) -> dict[str, Any]:
    """Read all IRSDK variables into a flat dict."""
    ir.freeze_var_buffer_latest()
    row: dict[str, Any] = {}
    for vh in var_headers:
        name, count = vh["name"], vh["count"]
        try:
            val = ir[name]
        except Exception:
            val = None
        if val is None:
            row[f"{_RAW_PREFIX}{name}"] = None
        elif isinstance(val, (list, tuple)):
            for i, v in enumerate(val):
                row[f"{_RAW_PREFIX}{name}__{i}"] = _safe_value(v)
        elif count > 1:
            row[f"{_RAW_PREFIX}{name}__0"] = _safe_value(val)
            for i in range(1, count):
                row[f"{_RAW_PREFIX}{name}__{i}"] = None
        else:
            row[f"{_RAW_PREFIX}{name}"] = _safe_value(val)
    row[f"{_RAW_PREFIX}capture_timestamp_utc"] = datetime.now(timezone.utc).isoformat()
    return row


def capture_replay_irsdk(ir: irsdk.IRSDK, var_headers: list[dict],
                         max_duration_s: float = _CAPTURE_TIMEOUT_S) -> list[dict[str, Any]]:
    """Capture telemetry via IRSDK shared memory while replay plays.

    This is the CSV fallback — runs in parallel with .ibt collection.
    """
    samples: list[dict[str, Any]] = []
    start_time = time.monotonic()
    last_tick = None
    stale_count = 0

    while time.monotonic() - start_time < max_duration_s:
        try:
            ir.freeze_var_buffer_latest()

            is_replay = ir["IsReplayPlaying"]
            if not is_replay and len(samples) > _MIN_SAMPLES:
                break

            try:
                tick = ir["SessionTick"]
            except Exception:
                tick = None

            if tick is not None and tick == last_tick:
                time.sleep(_TICK_POLL_S)
                continue
            last_tick = tick

            row = read_raw_sample(ir, var_headers)
            samples.append(row)

            if len(samples) % 1000 == 0:
                elapsed = time.monotonic() - start_time
                log.info("    IRSDK capture: %d samples (%.1fs)", len(samples), elapsed)

            speed = ir["Speed"]
            if speed is not None and speed < 0.01:
                stale_count += 1
                if stale_count > 300:
                    break
            else:
                stale_count = 0

        except Exception:
            time.sleep(0.01)

    elapsed = time.monotonic() - start_time
    log.info("  IRSDK capture: %d samples in %.1fs (%.1f Hz)",
             len(samples), elapsed, len(samples) / max(elapsed, 0.1))
    return samples


def save_irsdk_capture(samples: list[dict], session_info: dict,
                       label: str, output_dir: Path) -> Path | None:
    """Save IRSDK-captured telemetry as CSV + metadata."""
    if len(samples) < _MIN_SAMPLES:
        log.warning("  Only %d IRSDK samples — too few, skipping CSV save", len(samples))
        return None

    out_path = output_dir / label
    out_path.mkdir(parents=True, exist_ok=True)

    csv_path = out_path / "telemetry_raw.csv"
    fieldnames = list(samples[0].keys())
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(samples)

    meta = {
        "track_name": session_info.get("track_name"),
        "car_name": session_info.get("car_name"),
        "driver_name": session_info.get("driver_name"),
        "sample_count": len(samples),
        "column_count": len(fieldnames),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "capture_type": "irsdk_replay",
    }
    with open(out_path / "capture_meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    log.info("  IRSDK CSV saved: %s (%d rows)", csv_path, len(samples))
    return out_path


# ── .ibt collection ───────────────────────────────────────────────

def collect_ibt(new_ibts: list[Path], session_info: dict,
                label: str, output_dir: Path) -> list[Path]:
    """Copy new .ibt files to the organized output directory.

    Returns list of copied paths.
    """
    out_path = output_dir / label
    out_path.mkdir(parents=True, exist_ok=True)
    copied = []

    for ibt in new_ibts:
        dest = out_path / ibt.name
        # Avoid overwriting if same name exists (rare)
        if dest.exists():
            stem = ibt.stem
            suffix = ibt.suffix
            dest = out_path / f"{stem}_{int(time.time())}{suffix}"

        shutil.copy2(ibt, dest)
        size_mb = dest.stat().st_size / 1e6
        copied.append(dest)
        log.info("  Collected .ibt: %s (%.1f MB)", dest.name, size_mb)

    # Write metadata alongside
    meta = {
        "track_name": session_info.get("track_name"),
        "car_name": session_info.get("car_name"),
        "driver_name": session_info.get("driver_name"),
        "ibt_files": [p.name for p in copied],
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "source": "replay_ibt_capture",
    }
    with open(out_path / "capture_meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    return copied


# ── Batch orchestrator ────────────────────────────────────────────

def make_output_label(rpy_name: str, session_info: dict) -> str:
    """Build a folder name like: replay_name__Track__Car."""
    safe = rpy_name.replace(".rpy.zip", "").replace(".rpy", "").replace(".zip", "")
    track = session_info.get("track_name", "unknown").replace(" ", "_").replace("/", "_")
    car = session_info.get("car_name", "unknown").replace(" ", "_").replace("/", "_")
    return f"{safe}__{track}__{car}"


def batch_capture(replay_dir: Path, output_dir: Path,
                  speed: int = 1,
                  also_capture: bool = False,
                  skip_existing: bool = True) -> None:
    """Process all .rpy / .rpy.zip files in a directory.

    For each replay:
      1. Snapshot iRacing telemetry dir
      2. Open .rpy → iRacing loads it
      3. Set replay speed, wait for it to finish
      4. Collect new .ibt files from telemetry dir
      5. Optionally also capture via IRSDK shared memory to CSV
    """

    # ── Find iRacing telemetry dir ─────────────────────────────
    telem_dir = find_iracing_telemetry_dir()
    if telem_dir:
        log.info("iRacing telemetry dir: %s", telem_dir)
        ibt_count = len(list(telem_dir.glob("*.ibt")))
        log.info("  Existing .ibt files: %d", ibt_count)
    else:
        log.warning("Could not find iRacing telemetry directory!")
        log.warning("  .ibt collection disabled — will only capture via IRSDK if --also-capture")
        also_capture = True  # Force IRSDK capture as only option

    # ── Collect replay files ───────────────────────────────────
    temp_dir = Path(tempfile.mkdtemp(prefix="rpy_extract_"))
    log.info("Temp dir for zip extraction: %s", temp_dir)

    entries = collect_replay_files(replay_dir, temp_dir)
    if not entries:
        log.error("No .rpy or .rpy.zip files found in %s", replay_dir)
        return

    log.info("Found %d replay files to process", len(entries))
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Connect to iRacing ─────────────────────────────────────
    ir = connect_irsdk()
    var_headers = get_var_headers(ir) if also_capture else []
    if also_capture:
        log.info("IRSDK vars available: %d (CSV capture enabled)", len(var_headers))

    # ── Check disk logging hint ────────────────────────────────
    if telem_dir:
        try:
            ir.freeze_var_buffer_latest()
            disk_log = ir["DiskSubHeader"]  # may not exist
        except Exception:
            pass
        log.info("")
        log.info("  IMPORTANT: Make sure disk telemetry logging is ON in iRacing")
        log.info("  (Options → Misc → Enable telemetry logging)")
        log.info("")

    # ── Process each replay ────────────────────────────────────
    results = {"success": 0, "skipped": 0, "failed": 0, "no_ibt": 0, "details": []}

    for i, (rpy_path, original_name) in enumerate(entries, 1):
        log.info("")
        log.info("=" * 65)
        log.info("[%d/%d] %s", i, len(entries), original_name)
        log.info("=" * 65)

        # Check if already processed
        if skip_existing:
            stem = original_name.replace(".rpy.zip", "").replace(".rpy", "").replace(".zip", "")
            existing = list(output_dir.glob(f"{stem}__*"))
            if existing:
                log.info("  Already captured — skipping")
                results["skipped"] += 1
                results["details"].append({"file": original_name, "status": "skipped"})
                continue

        try:
            # 1. Snapshot telemetry dir
            before_ibts = snapshot_ibt_files(telem_dir) if telem_dir else {}

            # 2. Load replay
            if not load_replay_file(ir, rpy_path):
                log.warning("  Failed to load replay")
                results["failed"] += 1
                results["details"].append({"file": original_name, "status": "load_failed"})
                continue

            # 3. Wait for replay to settle, get session info
            time.sleep(_SETTLE_TIME_S)

            if not wait_for_replay_active(ir, timeout_s=15.0):
                log.warning("  Replay not producing telemetry")
                results["failed"] += 1
                results["details"].append({"file": original_name, "status": "no_telemetry"})
                continue

            session_info = get_session_info(ir)
            log.info("  Track: %s | Car: %s | Driver: %s",
                     session_info["track_name"], session_info["car_name"],
                     session_info["driver_name"])

            # 4. Seek to start, set speed
            seek_replay_start(ir)
            time.sleep(1.0)
            set_replay_speed(ir, speed)

            if not wait_for_replay_active(ir, timeout_s=10.0):
                log.warning("  Replay not moving after seek")
                results["failed"] += 1
                results["details"].append({"file": original_name, "status": "not_moving"})
                continue

            # 5. Wait for replay to finish (or capture via IRSDK in parallel)
            if also_capture:
                var_headers = get_var_headers(ir)
                samples = capture_replay_irsdk(ir, var_headers)
            else:
                reason = wait_for_replay_end(ir, speed=speed)
                log.info("  Replay finished: %s", reason)
                samples = []

            # 6. Wait a bit for iRacing to flush .ibt to disk
            if telem_dir:
                log.info("  Waiting %.0fs for .ibt flush...", _IBT_WAIT_AFTER_S)
                time.sleep(_IBT_WAIT_AFTER_S)

            # 7. Collect new .ibt files
            label = make_output_label(original_name, session_info)
            ibt_collected = []

            if telem_dir:
                new_ibts = find_new_ibts(telem_dir, before_ibts)
                if new_ibts:
                    ibt_collected = collect_ibt(new_ibts, session_info, label, output_dir)
                    log.info("  Collected %d .ibt file(s)", len(ibt_collected))
                else:
                    log.warning("  No new .ibt files found — is disk logging enabled?")
                    results["no_ibt"] += 1

            # 8. Save IRSDK CSV if requested
            if also_capture and samples:
                save_irsdk_capture(samples, session_info, label, output_dir)

            # Record result
            if ibt_collected or (also_capture and samples):
                results["success"] += 1
                results["details"].append({
                    "file": original_name,
                    "status": "success",
                    "track": session_info["track_name"],
                    "car": session_info["car_name"],
                    "driver": session_info["driver_name"],
                    "ibt_count": len(ibt_collected),
                    "irsdk_samples": len(samples) if also_capture else 0,
                    "output_label": label,
                })
            else:
                results["failed"] += 1
                results["details"].append({"file": original_name, "status": "no_output"})

        except KeyboardInterrupt:
            log.info("Interrupted by user — stopping batch")
            break
        except Exception as exc:
            log.error("  Error processing %s: %s", original_name, exc, exc_info=True)
            results["failed"] += 1
            results["details"].append({
                "file": original_name, "status": "error", "error": str(exc),
            })

        # Pause between replays
        time.sleep(_INTER_REPLAY_S)

    # ── Summary ────────────────────────────────────────────────
    log.info("")
    log.info("=" * 65)
    log.info("BATCH COMPLETE")
    log.info("  Success:  %d", results["success"])
    log.info("  Skipped:  %d", results["skipped"])
    log.info("  Failed:   %d", results["failed"])
    if results["no_ibt"] > 0:
        log.info("  No .ibt:  %d  (check iRacing disk logging setting!)", results["no_ibt"])
    log.info("  Total:    %d", len(entries))
    log.info("=" * 65)

    # Save results
    summary_path = output_dir / "batch_summary.json"
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2)
    log.info("Summary: %s", summary_path)

    # Cleanup temp dir
    try:
        shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception:
        pass


# ── CLI ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Batch extract .ibt telemetry from iRacing .rpy replay files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic: extract .ibt from all replays in a folder
  python scripts/batch_replay_capture.py D:/alien_replays ./ibt_output

  # Handles .rpy.zip files automatically
  python scripts/batch_replay_capture.py D:/replays ./output

  # 2x replay speed (faster but may miss samples)
  python scripts/batch_replay_capture.py D:/replays ./output --speed 2

  # Also capture full IRSDK telemetry as CSV (fallback)
  python scripts/batch_replay_capture.py D:/replays ./output --also-capture

  # Custom iRacing telemetry dir
  python scripts/batch_replay_capture.py D:/replays ./output --telem-dir "E:/iRacing/telemetry"

Prerequisites:
  1. iRacing must be running (any session loaded)
  2. Disk telemetry logging must be ON (Options > Misc)
  3. pip install pyirsdk
""",
    )
    parser.add_argument("replay_dir", type=Path,
                        help="Directory containing .rpy and/or .rpy.zip files")
    parser.add_argument("output_dir", type=Path, nargs="?", default=Path("replay_captures"),
                        help="Output directory (default: ./replay_captures)")
    parser.add_argument("--speed", type=int, default=1, choices=[1, 2, 4, 8, 16],
                        help="Replay playback speed (default: 1)")
    parser.add_argument("--also-capture", action="store_true",
                        help="Also capture via IRSDK shared memory to CSV")
    parser.add_argument("--telem-dir", type=Path, default=None,
                        help="Override iRacing telemetry directory path")
    parser.add_argument("--no-skip", action="store_true",
                        help="Re-process replays even if output already exists")

    args = parser.parse_args()

    if not args.replay_dir.exists():
        log.error("Replay directory does not exist: %s", args.replay_dir)
        sys.exit(1)

    # Override telemetry dir if specified
    if args.telem_dir:
        if not args.telem_dir.exists():
            log.error("Telemetry directory does not exist: %s", args.telem_dir)
            sys.exit(1)
        # Monkey-patch the auto-detect function
        global find_iracing_telemetry_dir
        _override = args.telem_dir
        find_iracing_telemetry_dir = lambda: _override

    batch_capture(
        replay_dir=args.replay_dir,
        output_dir=args.output_dir,
        speed=args.speed,
        also_capture=args.also_capture,
        skip_existing=not args.no_skip,
    )


if __name__ == "__main__":
    main()
