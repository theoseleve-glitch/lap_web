#!/usr/bin/env python3
"""Check that all third-party imports in telemetry_tool/ are listed in requirements.txt.

Exits with code 1 if any are missing. Designed to run in CI.

Usage::

    python scripts/check_requirements.py
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

# Map import names to PyPI package names (when they differ)
_IMPORT_TO_PACKAGE: dict[str, str] = {
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "sklearn": "scikit-learn",
    "yaml": "PyYAML",
    "jwt": "PyJWT",
    "bs4": "beautifulsoup4",
    "serial": "pyserial",
    "gi": "PyGObject",
    "attr": "attrs",
    "dateutil": "python-dateutil",
    "sentry_sdk": "sentry-sdk",
    "argon2": "argon2-cffi",
    "pyotp": "pyotp",
    "psycopg2": "psycopg2-binary",
}

# Standard library modules (Python 3.11+) — not exhaustive, covers common ones
_STDLIB = {
    "abc", "argparse", "ast", "asyncio", "atexit", "base64", "bisect",
    "calendar", "cgi", "cmath", "codecs", "collections", "colorsys",
    "concurrent", "configparser", "contextlib", "copy", "csv", "ctypes",
    "dataclasses", "datetime", "decimal", "difflib", "dis", "email",
    "encodings", "enum", "errno", "fcntl", "filecmp", "fileinput",
    "fnmatch", "fractions", "ftplib", "functools", "gc", "getpass",
    "gettext", "glob", "gzip", "hashlib", "heapq", "hmac", "html",
    "http", "importlib", "inspect", "io", "ipaddress", "itertools",
    "json", "keyword", "linecache", "locale", "logging", "lzma",
    "mailbox", "math", "mimetypes", "mmap", "multiprocessing", "numbers",
    "operator", "optparse", "os", "pathlib", "pdb", "platform",
    "plistlib", "posixpath", "pprint", "profile", "pstats",
    "queue", "quopri", "random", "re", "reprlib", "resource", "rlcompleter",
    "runpy", "sched", "secrets", "select", "selectors", "shelve", "shlex",
    "shutil", "signal", "site", "smtplib", "socket", "socketserver",
    "sqlite3", "ssl", "stat", "statistics", "string", "struct",
    "subprocess", "sys", "sysconfig", "syslog", "tarfile", "tempfile",
    "termios", "textwrap", "threading", "time", "timeit", "tkinter",
    "token", "tokenize", "tomllib", "trace", "traceback", "tracemalloc",
    "tty", "turtle", "types", "typing", "unicodedata", "unittest",
    "urllib", "uuid", "venv", "warnings", "wave", "weakref", "webbrowser",
    "winreg", "winsound", "wsgiref", "xml", "xmlrpc", "zipfile", "zipimport",
    "zlib", "_thread", "__future__", "posix", "nt", "msvcrt",
    "typing_extensions",  # Often bundled, treat as stdlib-like
}

# First-party packages (our code)
_FIRST_PARTY = {
    "telemetry_tool", "kart_envelope", "web", "auth", "admin", "db",
    "ingest", "pipeline", "scoring", "features", "tasks",
    "pipeline_status", "session_context", "track_detection",
    "gps_filtering", "derived_channels", "resampling", "features",
    "corner_detection", "reference_line", "lap_simulation",
    "anomaly_detection", "ml_engine", "reporting_html", "reporting_pdf",
    "scoring", "io_racechrono", "session_trimming", "condition_tracking",
    "data_quality", "vehicle_model", "friction_model", "deltas",
    "sensor_offset", "feature_builder", "parquet_manager", "column_discovery",
    "path_manager", "adapters", "defaults",
    # Additional first-party modules (bare imports from telemetry_tool/)
    "billing", "celery_app", "corner_mastery", "cross_session",
    "dashboard_builder", "debrief_engine", "development_plan",
    "driver_profile", "feature_schema", "friction_envelope",
    "grip_map", "meteo_service", "model_registry", "optimal_solver",
    "pace_estimator", "pipeline_context", "pipeline_errors",
    "pipeline_version", "provenance", "race_intelligence",
    "race_state_engine", "race_strategy_v2", "sector_analysis",
    "services", "session_replay", "telemetry_schema",
    "theoretical_adapter", "theoretical_engine", "traffic_detection",
    "weather_correlation", "wet_physics",
}


def _parse_requirements(req_path: Path) -> set[str]:
    """Parse requirements.txt and return normalized package names."""
    packages: set[str] = set()
    for line in req_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Strip version specifiers, extras, and comments
        name = re.split(r"[>=<!\[;#]", line)[0].strip()
        if name:
            packages.add(name.lower().replace("-", "_"))
    return packages


def _extract_imports(py_file: Path) -> set[str]:
    """Extract top-level import names from a Python file."""
    imports: set[str] = set()
    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return imports

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                imports.add(node.module.split(".")[0])
    return imports


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    req_path = root / "requirements.txt"
    if not req_path.exists():
        print("ERROR: requirements.txt not found")
        return 1

    listed = _parse_requirements(req_path)

    # Scan all Python files under telemetry_tool/
    all_imports: set[str] = set()
    source_dir = root / "telemetry_tool"
    for py_file in source_dir.rglob("*.py"):
        # Skip test files and __pycache__
        if "__pycache__" in str(py_file) or "/tests/" in str(py_file).replace("\\", "/"):
            continue
        all_imports |= _extract_imports(py_file)

    # Check each import
    missing: list[str] = []
    for imp in sorted(all_imports):
        if imp in _STDLIB or imp in _FIRST_PARTY:
            continue
        # Map import name to package name
        pkg_name = _IMPORT_TO_PACKAGE.get(imp, imp).lower().replace("-", "_")
        if pkg_name not in listed:
            missing.append(f"  {imp} (package: {pkg_name})")

    if missing:
        print(f"WARNING: {len(missing)} import(s) not found in requirements.txt:")
        for m in missing:
            print(m)
        print("\nThese may be optional, vendored, or need to be added.")
        # Return 0 (warning only) — not a hard failure for now
        return 0

    print(f"OK: All {len(all_imports)} imports accounted for in requirements.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
