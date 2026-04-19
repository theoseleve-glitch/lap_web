#!/usr/bin/env python
"""Oracle Autopilot — minimal reliable approach.

Pre-requisites (ONE-TIME manual setup in CM):
  1. Open Content Manager → DRIVE → QUICK → single
  2. Click RACE tab
  3. Set 23 opponents, AI ~80%, Grid: Same car
  4. Leave CM open

Autopilot does ONLY:
  1. Change car (click car image → filter → select → Back)
  2. Change track (click track image → click track in list → OK)
  3. Click Go!
  4. Wait for AC → press Escape → click Drive button at y=165
  5. Wait for Lua app to finish batches
  6. Kill AC → post-process → next job

Kill: press ² to emergency stop.

Usage:
    python scripts/oracle_autopilot.py              # from job 0
    python scripts/oracle_autopilot.py --start-at 5
    python scripts/oracle_autopilot.py --dry-run
    python scripts/oracle_autopilot.py --test-one
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from telemetry_tool.lap_oracle.config import ORACLE_DATA, SIM_PATHS

# Lua app writes inside AC's Documents folder (CSP sandbox)
AC_DOCS = Path("C:/Users/Admin/Documents/Assetto Corsa")
LUA_ORACLE_DIR = AC_DOCS / "lap_oracle"
STATE_PATH = LUA_ORACLE_DIR / "ac_state.lua"

# Python-side paths
JOBS_PATH = ORACLE_DATA / "ac_jobs.lua"
PILOT_STATE = ORACLE_DATA / "autopilot_progress.json"
TEL_DEST = ORACLE_DATA / "telemetry" / "ac"  # where we copy CSVs to

TOTAL_BATCHES = 10
STALL_TIMEOUT_S = 25 * 60
POLL_INTERVAL_S = 30
AC_LOAD_WAIT_S = 60

# DPI awareness
try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import pyautogui
import pywinauto
pyautogui.FAILSAFE = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [autopilot] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("autopilot")


# ── Kill key ──────────────────────────────────────────────────────────

def _setup_kill_key():
    try:
        import keyboard
        keyboard.on_press_key(41, lambda e: (log.warning("KILL"), _kill_ac(), os._exit(0)))
        log.info("Kill: press [²]")
    except Exception:
        pass


# ── Jobs ──────────────────────────────────────────────────────────────

def _load_jobs():
    if not JOBS_PATH.exists():
        return []
    raw = JOBS_PATH.read_text(encoding="utf-8")
    jobs = []
    for m in re.finditer(r"\{([^{}]+)\}", raw):
        job = {}
        for p in re.finditer(r'(\w+)\s*=\s*(?:"([^"]*)"|([\d.]+))', m.group(1)):
            k = p.group(1)
            job[k] = p.group(2) if p.group(2) is not None else (int(p.group(3)) if "." not in p.group(3) else float(p.group(3)))
        if job:
            jobs.append(job)
    return jobs


# ── Process helpers ───────────────────────────────────────────────────

def _is_ac():
    try:
        return "acs.exe" in subprocess.run(["tasklist", "/FI", "IMAGENAME eq acs.exe"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return False


def _kill_ac():
    for exe in ("acs.exe", "acs_x86.exe"):
        try:
            subprocess.run(["taskkill", "/F", "/IM", exe], capture_output=True, timeout=10)
        except Exception:
            pass
    time.sleep(3)


def _connect_cm():
    """Connect to CM — try by title first, fall back to process name."""
    try:
        return pywinauto.Application(backend="uia").connect(title_re=".*Content Manager.*", timeout=5)
    except Exception:
        pass
    # Fallback: find by process name
    import subprocess as _sp
    r = _sp.run(["tasklist", "/FI", "IMAGENAME eq Content Manager.exe", "/FO", "CSV"],
                capture_output=True, text=True, timeout=5)
    for line in r.stdout.strip().split("\n")[1:]:
        parts = line.strip('"').split('","')
        if len(parts) >= 2:
            pid = int(parts[1])
            return pywinauto.Application(backend="uia").connect(process=pid, timeout=10)
    raise RuntimeError("Content Manager not found")


# ── Car selection ─────────────────────────────────────────────────────

def _car_hint(folder):
    name = folder
    for pfx in ("ks_", "rss_", "ac_", "gt_"):
        if name.startswith(pfx):
            name = name[len(pfx):]
            break
    name = name.replace("_", " ")
    name = re.sub(r"([a-zA-Z])(\d)", r"\1 \2", name)
    name = re.sub(r"(\d)([a-zA-Z])", r"\1 \2", name)
    return name.strip()


def _select_car(app, car_folder):
    win = app.top_window()
    win.set_focus()
    time.sleep(0.5)

    # Click car image (left side of Drive page)
    pyautogui.click(311, 440)
    time.sleep(2)

    hint = _car_hint(car_folder)
    log.info("  Car filter: '%s'", hint)

    # Find filter box on car page and type
    win = app.top_window()
    for ctrl in list(win.descendants(control_type="ComboBox")) + list(win.descendants(control_type="Edit")):
        try:
            r = ctrl.rectangle()
            if r.left > 1500 and 100 < r.top < 500 and (r.right - r.left) > 200:
                ctrl.click_input()
                time.sleep(0.3)
                pyautogui.hotkey("ctrl", "a")
                pyautogui.typewrite(hint, interval=0.04)
                time.sleep(1.5)
                break
        except Exception:
            pass

    # Click first match
    frag = hint.lower().split()[0]
    win = app.top_window()
    for item in win.descendants(control_type="ListItem"):
        try:
            t = item.window_text()
            if frag in t.lower():
                r = item.rectangle()
                pyautogui.doubleClick((r.left + r.right) // 2, (r.top + r.bottom) // 2)
                log.info("  Selected: %s", t)
                time.sleep(1)
                break
        except Exception:
            pass

    # Back to Drive page
    for b in win.descendants(control_type="Button"):
        try:
            if b.window_text() == "Back":
                b.click_input()
                time.sleep(1)
                return
        except Exception:
            pass
    pyautogui.press("escape")
    time.sleep(1)


# ── Track selection ───────────────────────────────────────────────────

def _track_hint(spec):
    name = spec.split("/")[0]
    if name.startswith("ks_"):
        name = name[3:]
    return name.replace("_", " ").replace("-", " ").title()


def _select_track(app, track_spec):
    win = app.top_window()
    win.set_focus()
    time.sleep(0.5)

    # Click track image (right side of Drive page)
    pyautogui.click(988, 440)
    time.sleep(2)

    hint = _track_hint(track_spec)
    log.info("  Track: '%s'", hint)

    # Track list shows as Text items on the right side
    win = app.top_window()
    for t in win.descendants(control_type="Text"):
        try:
            r = t.rectangle()
            txt = t.window_text()
            if r.left > 2000 and r.top > 350 and hint.lower() in txt.lower() and len(txt) < 100:
                pyautogui.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
                log.info("  Selected: %s", txt)
                time.sleep(1)
                break
        except Exception:
            pass

    # Click OK
    for b in win.descendants(control_type="Button"):
        try:
            if b.window_text() == "OK" and b.rectangle().top > 1500:
                b.click_input()
                time.sleep(1)
                return
        except Exception:
            pass


# ── Go! ───────────────────────────────────────────────────────────────

def _click_go(win):
    # Try Text "Go!"
    for t in win.descendants(control_type="Text"):
        try:
            if "Go!" in t.window_text():
                r = t.rectangle()
                pyautogui.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
                log.info("  Go! (text)")
                return True
        except Exception:
            pass
    # Try Button with Go! or rightmost bottom button
    bottom = []
    for b in win.descendants(control_type="Button"):
        try:
            r = b.rectangle()
            t = b.window_text()
            if r.top > 1700 and (r.right - r.left) > 30:
                bottom.append((r.left, b, t))
                if "Go" in t:
                    pyautogui.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
                    log.info("  Go! (button: '%s')", t)
                    return True
        except Exception:
            pass
    # Fallback: click rightmost bottom button
    if bottom:
        bottom.sort(key=lambda x: x[0], reverse=True)
        _, btn, txt = bottom[0]
        r = btn.rectangle()
        pyautogui.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
        log.info("  Go! (rightmost: '%s' at %d,%d)", txt, r.left, r.top)
        return True
    log.warning("  Go! not found")
    return False


# ── AC Drive button ───────────────────────────────────────────────────

def _click_drive():
    """Press Escape (dismiss overlays) then click steering wheel at y≈165."""
    import ctypes.wintypes
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, "Assetto Corsa")
    if not hwnd:
        return False

    user32.ShowWindow(hwnd, 9)
    time.sleep(0.5)
    user32.SetForegroundWindow(hwnd)
    time.sleep(2)

    # Dismiss overlays
    pyautogui.press("escape")
    time.sleep(1.5)

    # Click steering wheel — from screenshot: center at (60, 165)
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))

    for y in [165, 140, 190, 120, 210, 100]:
        pyautogui.click(rect.left + 60, rect.top + y)
        time.sleep(0.5)

    time.sleep(2)
    pyautogui.hotkey("ctrl", "c")
    log.info("  Drive + Ctrl+C sent")
    return True


# ── State / Progress ─────────────────────────────────────────────────

def _read_state():
    if not STATE_PATH.exists():
        return {}
    raw = STATE_PATH.read_text(encoding="utf-8").strip()
    if raw.startswith("return"):
        raw = raw[6:].strip()
    raw = raw.strip("{}")
    result = {}
    for part in raw.split(","):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            k, v = k.strip(), v.strip().strip('"')
            try:
                result[k] = int(v)
            except ValueError:
                result[k] = v
    return result


def _reset_state(job):
    LUA_ORACLE_DIR.mkdir(parents=True, exist_ok=True)
    (LUA_ORACLE_DIR / "telemetry").mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        f'return {{batch=0, lapsDone=0, car="{job["car"]}", track="{job.get("track","?")}"}}\n',
        encoding="utf-8",
    )


def _collect_csvs():
    """Copy new CSVs from Lua output (app folder + AC Documents) to our data directory."""
    import shutil
    # CSP only allows .lua file writes. Telemetry is in batch_NN.lua files
    # containing CSV wrapped in: return [[\n..CSV..\n]]
    src = LUA_ORACLE_DIR
    if not src.exists():
        return 0
    lua_files = list(src.glob("batch_*.lua"))
    if not lua_files:
        return 0

    # Convert each .lua to .csv
    for lf in lua_files:
        raw = lf.read_text(encoding="utf-8")
        # Extract CSV between [[ and ]]
        start = raw.find("[[")
        end_ = raw.rfind("]]")
        if start < 0 or end_ < 0:
            continue
        csv_data = raw[start + 3:end_].strip()  # skip [[\n
        csv_name = lf.stem + ".csv"  # batch_00.csv
    TEL_DEST.mkdir(parents=True, exist_ok=True)
    count = 0
    for lf in lua_files:
        raw = lf.read_text(encoding="utf-8")
        start = raw.find("[[")
        end_ = raw.rfind("]]")
        if start < 0 or end_ < 0:
            continue
        csv_data = raw[start + 3:end_].strip()
        csv_name = lf.stem + ".csv"
        dest = TEL_DEST / csv_name
        if not dest.exists():
            dest.write_text(csv_data, encoding="utf-8")
            log.info("  Converted: %s → %s (%.1f MB)", lf.name, csv_name, len(csv_data) / 1e6)
            count += 1
    return count


def _load_progress():
    return json.loads(PILOT_STATE.read_text()) if PILOT_STATE.exists() else {"job_index": 0}


def _save_progress(idx):
    PILOT_STATE.write_text(json.dumps({"job_index": idx}, indent=2))


# ── Wait ──────────────────────────────────────────────────────────────

def _wait():
    last, stall = -1, 0
    while True:
        time.sleep(POLL_INTERVAL_S)
        if not _is_ac():
            return _read_state().get("batch", 0) >= TOTAL_BATCHES
        st = _read_state()
        batch = st.get("batch", 0)
        if batch != last:
            log.info("  batch %d/%d laps %d", batch, TOTAL_BATCHES, st.get("lapsDone", 0))
            last, stall = batch, 0
        else:
            stall += POLL_INTERVAL_S
        if batch >= TOTAL_BATCHES:
            return True
        if stall >= STALL_TIMEOUT_S:
            log.warning("  Stalled")
            return False


# ── Post-process ──────────────────────────────────────────────────────

def _postprocess():
    tel = ORACLE_DATA / "telemetry" / "ac"
    out = ORACLE_DATA / "telemetry" / "processed"
    if not tel.exists():
        return
    new = [f for f in sorted(tel.glob("*.csv")) if not (out / f.name).exists()]
    if not new:
        return
    log.info("Post-processing %d CSVs...", len(new))
    try:
        from scripts.postprocess_ac_telemetry import process_file
        for f in new:
            process_file(f, out)
    except Exception as e:
        log.warning("Post-process error: %s", e)


# ── Main ──────────────────────────────────────────────────────────────

def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--start-at", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--test-one", action="store_true")
    args = p.parse_args()

    jobs = _load_jobs()
    if not jobs:
        log.error("No jobs. Run: python scripts/generate_ac_jobs.py")
        return

    idx = args.start_at if args.start_at is not None else _load_progress().get("job_index", 0)
    _setup_kill_key()

    log.info("Oracle Autopilot (minimal)")
    log.info("  %d jobs, starting #%d. Press [²] to kill.", len(jobs), idx)
    log.info("  PRE-REQ: CM open, RACE tab, 23 opponents, AI set.")

    if args.dry_run:
        for i, j in enumerate(jobs[idx:], start=idx):
            log.info("  [%d] %s @ %s AI=%s %s", i, j.get("car"), j.get("track"), j.get("ai_level"), j.get("weather"))
        return

    # Check CM is running
    try:
        _connect_cm()
    except Exception:
        log.error("CM not running! Open it first with RACE tab configured.")
        return

    while idx < len(jobs):
        job = jobs[idx]
        log.info("")
        log.info("=== JOB %d/%d: %s @ %s ===", idx + 1, len(jobs), job.get("car"), job.get("track"))

        try:
            if _is_ac():
                _kill_ac()

            app = _connect_cm()

            # 1. Go to DRIVE
            win = app.top_window()
            win.set_focus()
            time.sleep(0.5)
            for b in win.descendants(control_type="Button"):
                if b.window_text() == "DRIVE":
                    b.click_input()
                    time.sleep(2)
                    break

            # 2. Select car
            _select_car(app, job["car"])
            time.sleep(1)

            # Back to DRIVE
            app = _connect_cm()
            win = app.top_window()
            for b in win.descendants(control_type="Button"):
                if b.window_text() == "DRIVE":
                    b.click_input()
                    time.sleep(2)
                    break

            # 3. Select track
            _select_track(app, job.get("track", "imola"))
            time.sleep(1)

            # Back to DRIVE
            app = _connect_cm()
            win = app.top_window()
            for b in win.descendants(control_type="Button"):
                if b.window_text() == "DRIVE":
                    b.click_input()
                    time.sleep(2)
                    break

            # 4. Go!
            win = app.top_window()
            _click_go(win)

            # 5. Wait for AC
            log.info("Waiting for AC...")
            launched = False
            for _ in range(AC_LOAD_WAIT_S // 5):
                time.sleep(5)
                if _is_ac():
                    log.info("AC running!")
                    time.sleep(10)
                    launched = True
                    break

            if not launched:
                log.error("AC didn't start — skipping")
                idx += 1
                _save_progress(idx)
                continue

            # 6. Click Drive button
            _reset_state(job)
            _click_drive()

            # 7. Wait for batches
            log.info("Waiting for batches...")
            ok = _wait()
            log.info("Job %d %s", idx, "DONE" if ok else "incomplete")

            _kill_ac()
            n_csv = _collect_csvs()
            log.info("  Collected %d CSVs", n_csv)
            _postprocess()
            idx += 1
            _save_progress(idx)

            if args.test_one:
                return

        except KeyboardInterrupt:
            _save_progress(idx)
            _kill_ac()
            return
        except Exception as e:
            log.exception("Error: %s", e)
            _kill_ac()
            # If CM died, stop — don't burn through jobs
            try:
                _connect_cm()
            except Exception:
                log.error("CM died. Stopping. Restart CM and re-run.")
                _save_progress(idx)
                return
            idx += 1
            _save_progress(idx)
            time.sleep(5)

    log.info("=== ALL DONE ===")
    _postprocess()


if __name__ == "__main__":
    main()
