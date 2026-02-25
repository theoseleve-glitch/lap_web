#!/usr/bin/env python3

"""
main.py
-------
Entry point for the motorsport telemetry analysis tool.

Three modes of operation
~~~~~~~~~~~~~~~~~~~~~~~~
1. **Double-click** (no args) -> opens a file-picker window, then
   interactive console prompts for session type / drivers / laps.
2. **CLI**:  ``python main.py data/raw/CKS_R1.csv``
3. **Batch**: ``python main.py data/raw/CKS_R1.csv --batch config.json``

Build as .exe
~~~~~~~~~~~~~
::

    pyinstaller telemetry_tool.spec --clean --noconfirm

Then double-click ``dist/telemetry_tool/telemetry_tool.exe``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# -- -

# Silence NumExpr thread-limit warning.  Must be set *before* any import of

# NumPy, pandas, or numexpr.  setdefault() ensures a user-provided value

# takes priority over this default.

# -- -

os.environ.setdefault("NUMEXPR_MAX_THREADS", "16")

# -- -

# Extend Windows console scrollback buffer so the user can scroll through

# all output when running the .exe by double-clicking.

# -- -

def _extend_console_buffer() -> None:
    """Increase console buffer to 9999 lines on Windows."""
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes
        STD_OUTPUT_HANDLE = -11
        handle = ctypes.windll.kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        if handle and handle != -1:
            class COORD(ctypes.Structure):
                _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]
            buf_size = COORD(220, 9999)
            ctypes.windll.kernel32.SetConsoleScreenBufferSize(handle, buf_size)
            ctypes.windll.kernel32.SetConsoleTitleW("Telemetry Analysis Tool")
    except Exception:
        pass
    try:
        os.system("mode con: cols=200 lines=55 >nul 2>&1")
    except Exception:
        pass

_extend_console_buffer()

logger = logging.getLogger("main")


# ============================================================================

# File picker (tkinter) -- used when no CSV path is given

# ============================================================================


def _pick_csv_file() -> Optional[Path]:
    """
    Open a native file dialog and return the selected CSV path.

    Returns ``None`` if the user cancels.  Falls back to a console prompt
    if tkinter is unavailable (e.g. headless server).
    """
    # Determine a sensible starting directory

    try:
        from path_manager import get_data_raw_dir
        initial_dir = str(get_data_raw_dir())
    except Exception:
        initial_dir = os.getcwd()

    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()                 # hide the empty root window
        root.attributes("-topmost", 1)  # bring dialog to front

        file_path = filedialog.askopenfilename(
            title="Select a RaceChrono CSV file",
            initialdir=initial_dir,
            filetypes=[
                ("CSV files", "*.csv"),
                ("All files", "*.*"),
            ],
        )
        root.destroy()

        if file_path:
            return Path(file_path)
        return None

    except ImportError:
        # tkinter not available -- fall back to console

        print(f"\n  Default CSV folder: {initial_dir}")
        raw = input("  CSV file path (or filename if in data/raw): ").strip().strip('"').strip("'")
        if not raw:
            return None
        p = Path(raw)
        if not p.exists():
            # Try relative to data/raw

            alt = Path(initial_dir) / raw
            if alt.exists():
                return alt
        return p


# ============================================================================

# Console prompts -- all user I/O is in this section

# ============================================================================


_SESSION_TYPES = (
    "practice", "qualifying", "race", "test",
    "heat", "final", "sprint_race", "feature_race",
    "endurance_stint", "endurance_race",
)

_TRACK_STATES = (
    "dry", "damp", "wet", "drying", "green",
    "rubbered", "dusty", "greasy", "cold", "full_wet",
)


def _prompt_choice(
    prompt: str,
    options: tuple[str, ...],
    default: str,
    *,
    show_all: bool = True,
) -> str:
    """Ask user to pick from *options*.  Return *default* on empty input."""
    if show_all:
        # Display in two columns for readability
        per_row = 4
        for idx in range(0, len(options), per_row):
            row = options[idx : idx + per_row]
            cells = []
            for o in row:
                marker = "*" if o == default else " "
                cells.append(f"  {marker}{o:<18}")
            print("".join(cells))
        print(f"  (* = default)\n")

    while True:
        raw = input(f"  {prompt} [{default}]: ").strip().lower()
        if raw == "":
            return default
        if raw in options:
            return raw
        # Try SessionContext normalizers for extended values
        try:
            from session_context import normalize_session_type
            normalize_session_type(raw)
            return raw
        except (ImportError, ValueError):
            pass
        try:
            from session_context import normalize_track_state
            normalize_track_state(raw)
            return raw
        except (ImportError, ValueError):
            pass
        print(f"    Invalid.  Options: {', '.join(options)}")


def _prompt_int(prompt: str, default: int, *, min_val: int = 0) -> int:
    """Ask for an integer.  Return *default* on empty input."""
    while True:
        raw = input(f"  {prompt} [{default}]: ").strip()
        if raw == "":
            return default
        try:
            val = int(raw)
            if val < min_val:
                print(f"    Must be >= {min_val}.")
                continue
            return val
        except ValueError:
            print("    Please enter a whole number.")


def _prompt_lap_range(prompt: str) -> Optional[tuple[int, int]]:
    """Ask for a lap range like ``3-15``.  Return ``None`` for all laps."""
    while True:
        raw = input(f"  {prompt} [all]: ").strip()
        if raw == "" or raw.lower() == "all":
            return None
        parts = raw.replace(" ", "").split("-")
        if len(parts) == 2:
            try:
                lo, hi = int(parts[0]), int(parts[1])
                if lo <= hi:
                    return (lo, hi)
                print("    First lap must be <= last lap.")
                continue
            except ValueError:
                pass
        print("    Format: first-last  (e.g. 3-15)  or Enter for all.")


def _prompt_string(prompt: str, default: str) -> str:
    """Ask for a free-form string.  Return *default* on empty input."""
    raw = input(f"  {prompt} [{default}]: ").strip()
    return raw if raw else default


def _prompt_optional_float(prompt: str) -> "float | None":
    """Ask for an optional float.  Enter skips (returns None)."""
    raw = input(f"    {prompt} [Enter to skip]: ").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _prompt_exclude_laps(prompt: str) -> Optional[list[int]]:
    """Ask for a comma-separated list of lap numbers to exclude."""
    while True:
        raw = input(f"  {prompt} [none]: ").strip()
        if raw == "" or raw.lower() == "none":
            return None
        try:
            laps = [int(x.strip()) for x in raw.split(",") if x.strip()]
            if laps:
                return laps
            return None
        except ValueError:
            print("    Format: 1,3,7  (comma-separated lap numbers)")


def collect_session_info(csv_path: Path) -> dict[str, Any]:
    """
    Interactively collect session metadata and per-driver lap ranges.

    Returns dict with ``session_type``, ``track_state``, ``drivers``,
    ``weather``, and optional ``exclude_laps``, ``notes``.
    """
    print(f"\n{'=' * 60}")
    print(f"  Telemetry Analysis Tool")
    print(f"  File: {csv_path.name}")
    print(f"{'=' * 60}\n")

    # --- Session type ---
    print("  Session type:")
    session_type = _prompt_choice("Session type", _SESSION_TYPES, "practice")

    # --- Track state ---
    print("\n  Track state:")
    track_state = _prompt_choice("Track state", _TRACK_STATES, "dry")

    # --- Drivers ---
    print()
    n_drivers = _prompt_int("Number of drivers", 1, min_val=1)
    print()

    drivers: list[dict[str, Any]] = []
    for i in range(n_drivers):
        if n_drivers > 1:
            print(f"  --- Driver {i + 1} of {n_drivers} ---")
        prefix = f"Driver {i + 1}" if n_drivers > 1 else "Driver"
        name = _prompt_string(f"{prefix} name", f"Driver_{i + 1}")
        lap_range = _prompt_lap_range(f"{prefix} lap range (e.g. 3-15)")
        exclude = _prompt_exclude_laps(f"{prefix} laps to exclude (e.g. 1,3,7)")
        entry: dict[str, Any] = {"name": name, "lap_range": lap_range}
        if exclude:
            entry["exclude_laps"] = exclude
        drivers.append(entry)
        if n_drivers > 1:
            print()

    # --- Weather ---
    weather_obs = None
    try:
        from session_context import WeatherObs
        raw_wx = input("\n  Enter weather data? [y/N]: ").strip().lower()
        if raw_wx in ("y", "yes", "oui"):
            weather_obs = WeatherObs(
                air_temp_c=_prompt_optional_float("Air temp (C)"),
                track_temp_c=_prompt_optional_float("Track temp (C)"),
                humidity_pct=_prompt_optional_float("Humidity (%)"),
                wind_speed_mps=_prompt_optional_float("Wind speed (m/s)"),
                wind_dir_deg=_prompt_optional_float("Wind direction (deg, 0=N)"),
            )
            errors = weather_obs.validate()
            if errors:
                for e in errors:
                    print(f"    Warning: {e}")
    except ImportError:
        pass

    # --- Notes ---
    notes_raw = input("\n  Session notes [Enter to skip]: ").strip()
    notes = notes_raw if notes_raw else None

    print()
    return {
        "session_type": session_type,
        "track_state":  track_state,
        "drivers":      drivers,
        "weather":      weather_obs,
        "notes":        notes,
    }


def load_batch_config(path: Path) -> dict[str, Any]:
    """
    Load a JSON batch config file.

    Expected::

        {
            "session_type": "race",
            "track_state":  "dry",
            "drivers": [
                {"name": "Alice", "lap_range": [3, 15]},
                {"name": "Bob",   "lap_range": null}
            ]
        }
    """
    with open(path) as f:
        cfg = json.load(f)
    for d in cfg.get("drivers", []):
        lr = d.get("lap_range")
        if isinstance(lr, list) and len(lr) == 2:
            d["lap_range"] = tuple(lr)
        elif lr is None:
            d["lap_range"] = None

    # Reconstruct WeatherObs from batch JSON if present

    wx_raw = cfg.get("weather")
    if isinstance(wx_raw, dict):
        try:
            from session_context import WeatherObs
            cfg["weather"] = WeatherObs.from_dict(wx_raw)
        except ImportError:
            pass

    return cfg


# ============================================================================

# Pipeline execution

# ============================================================================


def _sanitize_driver_tag(name: str) -> str:
    """
    Convert a driver name into a filesystem-safe lowercase slug.

    ``"Theo Dupont"`` -> ``"theo_dupont"``,  ``"William"`` -> ``"william"``.
    """
    import re
    import unicodedata
    tag = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    tag = tag.lower().strip()
    tag = re.sub(r"[^a-z0-9]+", "_", tag).strip("_")
    return tag or "driver"


def _generate_combined_index(
    out_dir: Path,
    driver_reports: list[dict[str, Any]],
    session_info: dict[str, Any],
) -> Path:
    """
    Write a combined ``index.html`` that links to each per-driver report.

    Parameters
    ----------
    out_dir:
        Directory containing the per-driver HTML files.
    driver_reports:
        List of ``{"name": ..., "tag": ..., "html_path": ..., "score": ...}``
        dicts, one per driver.
    session_info:
        Session-level metadata for the banner.

    Returns
    -------
    Path to the generated ``index.html``.
    """
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    stype = session_info.get("session_type", "practice").title()
    tstate = session_info.get("track_state", "dry").title()

    rows = ""
    for dr in driver_reports:
        name = dr["name"]
        tag = dr["tag"]
        score = dr.get("score", "n/a")
        html_file = f"index_{tag}.html"
        rows += (
            f'      <tr>'
            f'<td><a href="{html_file}">{name}</a></td>'
            f'<td>{dr.get("laps", "all")}</td>'
            f'<td>{score}</td>'
            f'<td><a href="{html_file}">View report &rarr;</a></td>'
            f'</tr>\n'
        )

    html = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Session Overview &mdash; {date_str}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
           Roboto, Helvetica, Arial, sans-serif; margin: 2rem; color: #1a1a2e; }}
    h1 {{ color: #16213e; }}
    .meta {{ color: #555; margin-bottom: 1.5rem; }}
    table {{ border-collapse: collapse; width: 100%; max-width: 800px; }}
    th, td {{ text-align: left; padding: 0.6rem 1rem; border-bottom: 1px solid #ddd; }}
    th {{ background: #f0f0f5; }}
    a {{ color: #0f4c75; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <h1>Session Overview</h1>
  <p class="meta">{stype} &middot; {tstate} &middot; {date_str}</p>
  <table>
    <thead>
      <tr><th>Driver</th><th>Laps</th><th>Score</th><th>Report</th></tr>
    </thead>
    <tbody>
{rows}    </tbody>
  </table>
</body>
</html>
"""
    index_path = out_dir / "index.html"
    index_path.write_text(html, encoding="utf-8")
    logger.info("Combined index written: %s", index_path)
    return index_path


def run(
    csv_path: Path,
    session_info: dict[str, Any],
    *,
    enable_ml: bool = True,
    enable_report: bool = True,
) -> list[dict[str, Any]]:
    """
    Execute the pipeline for every driver in *session_info*.

    Returns one analysis summary dict per driver.
    """
    from pipeline import run_full_analysis

    # -- Construct SessionContext if available
    _context = None
    try:
        from session_context import (
            SessionContext, normalize_session_type, normalize_track_state,
            load_last_session_context,
        )
        from path_manager import get_base_dir as _get_base
        _last = load_last_session_context(_get_base() / 'results')
    except (ImportError, Exception):
        _last = None

    try:
        from session_context import (
            SessionContext, normalize_session_type, normalize_track_state,
        )
        _stype = normalize_session_type(session_info.get('session_type', 'practice'))
        _tstate = normalize_track_state(session_info.get('track_state', 'dry'))
        _weather = session_info.get('weather')
        _context = SessionContext(
            session_id=csv_path.stem,
            track_id=None,
            session_type=_stype,
            baseline_track_state=_tstate,
            weather=_weather,
        )
        logger.info(
            'SessionContext: type=%s state=%s',
            _stype.value, _tstate.value,
        )
    except (ImportError, ValueError) as _ctx_err:
        logger.debug('SessionContext not available: %s', _ctx_err)

    date_str   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    drivers    = session_info.get("drivers", [{"name": "Unknown", "lap_range": None}])
    if not drivers:
        drivers = [{"name": "Unknown", "lap_range": None}]

    # Resolve output directory via path_manager if available

    try:
        from path_manager import get_base_dir
        results_base = get_base_dir() / "results"
    except ImportError:
        results_base = Path("results")

    all_results: list[dict[str, Any]] = []
    multi_driver = len(drivers) > 1
    driver_reports: list[dict[str, Any]] = []   # for combined index

    for i, drv in enumerate(drivers, 1):
        driver_name = drv.get("name", f"Driver_{i}")
        lap_range   = drv.get("lap_range")
        driver_tag  = _sanitize_driver_tag(driver_name) if multi_driver else None

        meta = {
            "session_type": session_info.get("session_type", "practice"),
            "track_state":  session_info.get("track_state",  "dry"),
            "driver_name":  driver_name,
            "date":         date_str,
            "exclude_laps": drv.get("exclude_laps", session_info.get("exclude_laps")),
        }
        # Pass manual condition markers (Phase 2).
        _cc = session_info.get("manual_condition_changes")
        if _cc:
            meta["manual_condition_changes"] = _cc

        logger.info(
            "Running analysis for %s  (driver %d/%d, laps=%s) ...",
            driver_name, i, len(drivers),
            f"{lap_range[0]}-{lap_range[1]}" if lap_range else "all",
        )

        t0 = time.monotonic()
        out_dir = results_base / f"{date_str}_{csv_path.stem}"

        try:
            result = run_full_analysis(
                csv_path,
                meta,
                enable_ml=enable_ml,
                enable_report=enable_report,
                output_dir=out_dir,
                lap_range=lap_range,
                context=_context,
                driver_tag=driver_tag,
            )
        except Exception as exc:
            logger.error("Pipeline failed for %s: %s", driver_name, exc)
            logger.debug(traceback.format_exc())
            result = {
                "session_meta": meta,
                "steps_ok": [],
                "steps_failed": ["pipeline_crash"],
                "errors": {"pipeline_crash": str(exc)},
            }

        elapsed = time.monotonic() - t0

        # -- Console summary -- -

        n_ok   = len(result.get("steps_ok", []))
        n_fail = len(result.get("steps_failed", []))
        score  = result.get("score_result")
        score_str = (
            f"{score['total_score']:.1f}/100 [{score['grade']}]"
            if score else "n/a"
        )
        track = result.get("track_id", "?")

        print(f"\n{'=' * 60}")
        print(f"  {driver_name}  --  {n_ok}/{n_ok + n_fail} steps OK  ({elapsed:.1f}s)")
        print(f"  Track: {track}   Score: {score_str}")

        if result.get("html_path"):
            print(f"  Report: {result['html_path']}")
        if result.get("pdf_path"):
            print(f"  PDF:    {result['pdf_path']}")

        if n_fail > 0:
            print(f"  Warnings ({n_fail}):")
            for step, msg in result.get("errors", {}).items():
                print(f"    * {step}: {msg}")

        print(f"{'=' * 60}")

        all_results.append(result)

        # Collect info for the combined index page

        if multi_driver and driver_tag:
            laps_str = (
                f"{lap_range[0]}-{lap_range[1]}" if lap_range else "all"
            )
            driver_reports.append({
                "name": driver_name,
                "tag": driver_tag,
                "html_path": result.get("html_path"),
                "score": score_str,
                "laps": laps_str,
            })

    # -- Generate combined index.html for multi-driver sessions -- -

    if multi_driver and driver_reports and enable_report:
        try:
            _generate_combined_index(out_dir, driver_reports, session_info)
            print(f"  Combined index: {out_dir / 'index.html'}")
        except Exception as exc:
            logger.warning("Could not generate combined index: %s", exc)

    # -- Comparison report for multi-driver sessions -- -

    if len(all_results) >= 2 and enable_report:
        try:
            from reporting_html import generate_comparison_report
            cmp_path = generate_comparison_report(
                all_results,
                output_path=results_base / f"{date_str}_{csv_path.stem}" / "comparison.html",
            )
            print(f"  Comparison report: {cmp_path}")
        except Exception as exc:
            logger.warning("Could not generate comparison report: %s", exc)

    return all_results


# ============================================================================

# Argument parser

# ============================================================================


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    p = argparse.ArgumentParser(
        prog="telemetry_tool",
        description="Motorsport telemetry analysis pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python main.py CKS_R1.csv\n"
            "  python main.py CKS_R1.csv --no-ml\n"
            "  python main.py CKS_R1.csv --batch config.json\n"
            "  python main.py                       (opens file picker)"
        ),
    )
    p.add_argument(
        "csv_path",
        type=Path,
        nargs="?",           # <- optional so double-click works
        default=None,
        help="Path to RaceChrono CSV export.  If omitted, a file picker opens.",
    )
    p.add_argument(
        "--batch", type=Path, default=None, metavar="CONFIG",
        help="Non-interactive JSON config with session_type, track_state, drivers.",
    )
    p.add_argument("--no-ml",     action="store_true", help="Skip ML training.")
    p.add_argument("--no-report", action="store_true", help="Skip HTML/PDF report.")
    p.add_argument("--verbose", "-v", action="store_true", help="DEBUG-level logging.")
    p.add_argument("--quiet", "-q", action="store_true", help="Warnings/errors only.")

    # Condition markers  (Phase 2)
    p.add_argument(
        "--condition-change", action="append", metavar="LAP:STATE",
        dest="condition_changes",
        help=(
            "Manually mark a track condition change.  "
            "Format: LAP:STATE  (e.g. 12:wet, 20:drying).  "
            "May be specified multiple times."
        ),
    )

    # Web dashboard flags
    p.add_argument(
        "--serve", action="store_true",
        help="Launch the web dashboard instead of running analysis.",
    )
    p.add_argument(
        "--port", type=int, default=5000, metavar="PORT",
        help="Port for the web dashboard (default: 5000).",
    )
    return p


# ============================================================================

# Entry point

# ============================================================================


def _launch_web_dashboard(*, port: int = 5000, debug: bool = False) -> int:
    """
    Start the Flask web dashboard.

    Returns 0 on normal shutdown, 2 on startup failure.
    """
    try:
        from web.app import create_app
        from web.config import Config
    except ImportError as exc:
        print(f"\n  Web dashboard unavailable: {exc}")
        print("  Make sure Flask is installed:  pip install flask")
        _wait_for_keypress()
        return 2

    cfg = Config()
    cfg.PORT = port
    cfg.DEBUG = debug

    app = create_app(cfg)
    host = cfg.HOST

    print(f"\n  Telemetry Dashboard starting ...")
    print(f"  URL:  http://{host}:{port}/")
    print(f"  DB:   {cfg.DB_PATH}")
    print(f"  Press Ctrl+C to stop.\n")

    try:
        import webbrowser
        webbrowser.open(f"http://{host}:{port}/")
    except Exception:
        pass

    try:
        app.run(host=host, port=port, debug=debug)
    except Exception as exc:
        print(f"\n  Server error: {exc}")
        _wait_for_keypress()
        return 2

    return 0


def main(argv: Optional[list[str]] = None) -> int:
    """
    Parse arguments, collect session info, run pipeline.

    Returns 0 = success, 1 = partial failure, 2 = fatal error.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    # -- Bootstrap frozen directory structure (first run after install)
    try:
        from path_manager import bootstrap_frozen_dirs
        bootstrap_frozen_dirs()
    except ImportError:
        pass

    # -- Logging -- -

    level = logging.DEBUG if args.verbose else (
        logging.WARNING if args.quiet else logging.INFO
    )
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    # -- Web dashboard mode -- -
    if args.serve:
        return _launch_web_dashboard(port=args.port, debug=args.verbose)

    # -- Resolve CSV path
    csv_path: Optional[Path] = args.csv_path

    if csv_path is None:
        # No arg provided -- open file picker (double-click scenario)

        print("\n  No CSV file specified.  Opening file picker ...\n")
        csv_path = _pick_csv_file()
        if csv_path is None:
            print("  No file selected.  Exiting.")
            _wait_for_keypress()
            return 2

    # Resolve relative to data/raw if just a filename

    if not csv_path.exists():
        try:
            from path_manager import get_data_raw_dir
            alt = get_data_raw_dir() / csv_path.name
            if alt.exists():
                csv_path = alt
        except ImportError:
            pass

    if not csv_path.exists():
        print(f"\n  Error: file not found -- {csv_path}")
        _wait_for_keypress()
        return 2
    if not csv_path.is_file():
        print(f"\n  Error: not a regular file -- {csv_path}")
        _wait_for_keypress()
        return 2

    # -- Collect session info (interactive or batch) -- -

    if args.batch is not None:
        if not args.batch.exists():
            print(f"\n  Error: batch config not found -- {args.batch}")
            _wait_for_keypress()
            return 2
        try:
            session_info = load_batch_config(args.batch)
            logger.info("Batch config loaded: %s", args.batch)
        except Exception as exc:
            print(f"\n  Error: invalid batch config -- {exc}")
            _wait_for_keypress()
            return 2
    else:
        try:
            session_info = collect_session_info(csv_path)
        except (KeyboardInterrupt, EOFError):
            print("\n  Aborted.")
            return 2

    # -- Parse manual condition changes (Phase 2)
    if args.condition_changes:
        manual_cc: dict[int, str] = {}
        for spec in args.condition_changes:
            try:
                lap_s, state = spec.split(":", 1)
                manual_cc[int(lap_s)] = state.strip().lower()
            except (ValueError, AttributeError):
                print(f"\n  Warning: ignoring invalid --condition-change '{spec}' "
                      f"(expected LAP:STATE, e.g. 12:wet)")
        if manual_cc:
            session_info["manual_condition_changes"] = manual_cc
            logger.info("Manual condition changes: %s", manual_cc)

    # -- Run pipeline for each driver
    try:
        results = run(
            csv_path,
            session_info,
            enable_ml=not args.no_ml,
            enable_report=not args.no_report,
        )
    except ImportError as exc:
        print(f"\n  Fatal import error: {exc}")
        _wait_for_keypress()
        return 2
    except Exception as exc:
        logger.error("Unexpected error: %s", exc)
        logger.debug(traceback.format_exc())
        print(f"\n  Fatal: {exc}")
        _wait_for_keypress()
        return 2

    # -- Exit code -- -

    any_failures = any(len(r.get("steps_failed", [])) > 0 for r in results)
    if any_failures:
        print("\n  Some steps had issues -- check the log above for details.")
    else:
        print("\n  All analyses completed successfully.")

    _wait_for_keypress()
    return 1 if any_failures else 0


def _wait_for_keypress() -> None:
    """
    Keep the console window open after the run finishes.

    Only waits when we detect a frozen PyInstaller build or when the
    script was launched by double-clicking (no parent terminal).
    """
    if getattr(sys, "frozen", False) or (
        os.name == "nt" and "PROMPT" not in os.environ
    ):
        print("\n  Press Enter to exit ...")
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pass


# ============================================================================

# Inline tests (run with:  python main.py --self-test)

# ============================================================================


def _run_tests() -> None:
    """Self-contained test suite."""
    import tempfile

    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name: str, fn: Any) -> None:
        try:
            fn()
            passed.append(name)
        except Exception:
            failed.append((name, traceback.format_exc()))

    # -- Test 1 -- parser accepts csv_path
    def t_parser_basic() -> None:
        p = build_parser()
        a = p.parse_args(["test.csv"])
        assert a.csv_path == Path("test.csv")
        assert a.no_ml is False

    _test("parser_basic", t_parser_basic)

    # -- Test 2 -- parser flags -- -

    def t_parser_flags() -> None:
        p = build_parser()
        a = p.parse_args(["x.csv", "--no-ml", "--no-report", "-v"])
        assert a.no_ml is True and a.no_report is True and a.verbose is True

    _test("parser_flags", t_parser_flags)

    # -- Test 3 -- csv_path is optional (nargs='?') -- -

    def t_parser_no_arg() -> None:
        p = build_parser()
        a = p.parse_args([])
        assert a.csv_path is None

    _test("parser_no_arg", t_parser_no_arg)

    # -- Test 4 -- batch config loading -- -

    def t_load_batch() -> None:
        cfg_data = {
            "session_type": "qualifying",
            "track_state":  "wet",
            "drivers": [
                {"name": "Alice", "lap_range": [3, 15]},
                {"name": "Bob",   "lap_range": None},
            ],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(cfg_data, f)
            f.flush()
            path = Path(f.name)
        try:
            cfg = load_batch_config(path)
            assert cfg["session_type"] == "qualifying"
            assert cfg["drivers"][0]["lap_range"] == (3, 15)
            assert cfg["drivers"][1]["lap_range"] is None
        finally:
            path.unlink(missing_ok=True)

    _test("load_batch_config", t_load_batch)

    # -- Test 5 -- main returns 2 for missing file
    def t_main_missing() -> None:
        code = main(["/nonexistent/file.csv", "-q"])
        assert code == 2

    _test("main_missing_file", t_main_missing)

    # -- Test 6 -- main returns 2 for directory path
    def t_main_dir() -> None:
        code = main(["/tmp", "-q"])
        assert code == 2

    _test("main_directory_path", t_main_dir)

    # -- Test 7 -- graceful pipeline failure (returns 1, not crash) -- -

    def t_graceful_fail() -> None:
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            f.write(b"x,y\n1,2\n")
            csv = Path(f.name)
        cfg = {"session_type": "practice", "track_state": "dry",
               "drivers": [{"name": "T", "lap_range": None}]}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(cfg, f); f.flush()
            cfg_path = Path(f.name)
        try:
            code = main([str(csv), "--batch", str(cfg_path), "--no-ml", "--no-report", "-q"])
            assert code in (0, 1), f"Expected 0 or 1, got {code}"
        finally:
            csv.unlink(missing_ok=True)
            cfg_path.unlink(missing_ok=True)

    _test("graceful_failure", t_graceful_fail)

    # -- Test 8 -- multi-driver returns one result per driver -- -

    def t_multi_driver() -> None:
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            f.write(b"x\n1\n"); csv = Path(f.name)
        try:
            results = run(
                csv,
                {"session_type": "practice", "track_state": "dry",
                 "drivers": [{"name": "A", "lap_range": None},
                             {"name": "B", "lap_range": (3, 10)}]},
                enable_ml=False, enable_report=False,
            )
            assert len(results) == 2
            assert results[0]["session_meta"]["driver_name"] == "A"
            assert results[1]["session_meta"]["driver_name"] == "B"
        finally:
            csv.unlink(missing_ok=True)

    _test("multi_driver", t_multi_driver)

    # -- Test 9 -- empty drivers defaults to Unknown
    def t_empty_drivers() -> None:
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            f.write(b"x\n1\n"); csv = Path(f.name)
        try:
            results = run(csv, {"drivers": []}, enable_ml=False, enable_report=False)
            assert len(results) == 1
        finally:
            csv.unlink(missing_ok=True)

    _test("empty_drivers", t_empty_drivers)

    # -- Test 10 -- parser help doesn't crash -- -

    def t_help() -> None:
        p = build_parser()
        assert p.format_help()

    _test("parser_help", t_help)

    #
    total = len(passed) + len(failed)
    status = "PASS" if not failed else "FAIL"
    print(f"\nMain Tests: {len(passed)}/{total} passed [{status}]")
    for name in passed:
        print(f"  OK {name}")
    for name, tb in failed:
        print(f"  FAIL {name}\n{tb}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


# ============================================================================

# Script entry

# ============================================================================


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
        _run_tests()
    else:
        sys.exit(main())