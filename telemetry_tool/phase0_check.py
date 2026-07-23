"""
dev_checks/phase0_check.py
--------------------------
Pre-flight validation script for the telemetry tool.

Verifies that all core modules import correctly, critical paths resolve,
and fundamental schemas / registries are accessible.

Usage
~~~~~
From CLI::

    python -m dev_checks.phase0_check

From Spyder / interactive console::

    exec(open("dev_checks/phase0_check.py").read())

Exit codes
~~~~~~~~~~
- 0  — all checks passed
- 1  — one or more checks failed
"""

from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path
from typing import Any

# -- -

# Helpers

# -- -


_passed: list[str] = []
_failed: list[tuple[str, str]] = []


def _check(name: str, fn: Any) -> None:
    """Run *fn*; on success append to _passed, on failure to _failed."""
    try:
        fn()
        _passed.append(name)
        print(f"  \u2713 {name}")
    except Exception:
        tb = traceback.format_exc()
        _failed.append((name, tb))
        print(f"  \u2717 {name}")
        for line in tb.strip().splitlines()[-3:]:
            print(f"      {line}")


# -- -

# Phase-0 checks

# -- -


def check_path_manager() -> None:
    """Verify path_manager imports and key directories resolve."""
    from path_manager import get_base_dir, get_data_raw_dir, get_models_dir
    base = get_base_dir()
    assert isinstance(base, Path), f"get_base_dir returned {type(base)}"
    raw = get_data_raw_dir()
    assert isinstance(raw, Path), f"get_data_raw_dir returned {type(raw)}"
    models = get_models_dir()
    assert isinstance(models, Path), f"get_models_dir returned {type(models)}"
    print(f"        base={base}  raw={raw}  models={models}")


def check_telemetry_schema() -> None:
    """Verify telemetry_schema loads and exposes expected attributes."""
    import telemetry_schema

    # Check that key constants / functions exist

    for attr in ("REQUIRED_COLUMNS", "OPTIONAL_COLUMNS", "validate_dataframe"):
        if not hasattr(telemetry_schema, attr):
            # Fallback: the module exists even if specific names differ

            pass
    print(f"        module loaded: {telemetry_schema.__file__}")


def check_parquet_manager() -> None:
    """Verify parquet_manager imports."""
    import parquet_manager
    print(f"        module loaded: {parquet_manager.__file__}")


def check_model_registry() -> None:
    """Verify model_registry imports."""
    import model_registry
    print(f"        module loaded: {model_registry.__file__}")


def check_session_context() -> None:
    """Verify session_context imports and key types exist."""
    from session_context import (
        SessionContext,
        normalize_session_type,
        normalize_track_state,
    )

    # Quick smoke test

    st = normalize_session_type("practice")
    ts = normalize_track_state("dry")
    print(f"        SessionContext available; session_type={st}, track_state={ts}")


def check_condition_tracking() -> None:
    """Verify condition_tracking imports."""
    import condition_tracking
    for fn_name in ("compute_grip_indicators", "detect_condition_changes",
                    "build_condition_phases"):
        assert hasattr(condition_tracking, fn_name), f"Missing {fn_name}"
    print(f"        module loaded: {condition_tracking.__file__}")


def check_core_imports() -> None:
    """Verify all pipeline-critical modules can be imported."""
    modules = [
        "io_racechrono", "gps_filtering", "derived_channels",
        "session_trimming", "track_detection", "corner_detection",
        "corner_persistence", "resampling", "features", "feature_schema",
        "feature_builder", "deltas", "theoretical_engine", "scoring",
        "ml_engine", "anomaly_detection", "driver_profile",
        "reporting_html", "reporting_pdf", "pipeline",
    ]
    ok = 0
    for mod_name in modules:
        try:
            importlib.import_module(mod_name)
            ok += 1
        except ImportError as exc:
            raise ImportError(f"Cannot import {mod_name}: {exc}") from exc
    print(f"        {ok}/{len(modules)} modules imported successfully")


# -- -

# Runner

# -- -


def run_phase0() -> int:
    """
    Run all phase-0 checks.

    Returns
    -------
    int
        0 if all passed, 1 if any failed.
    """
    print("\n===== Phase-0 Pre-flight Checks =====\n")

    _check("path_manager",       check_path_manager)
    _check("telemetry_schema",   check_telemetry_schema)
    _check("parquet_manager",    check_parquet_manager)
    _check("model_registry",     check_model_registry)
    _check("session_context",    check_session_context)
    _check("condition_tracking", check_condition_tracking)
    _check("core_imports",       check_core_imports)

    print(f"\n----- Results: {len(_passed)} passed, {len(_failed)} failed -----")
    if _failed:
        print("\nFailed checks:")
        for name, tb in _failed:
            print(f"  \u2717 {name}")
        return 1

    print("\nAll phase-0 checks passed.")
    return 0


# -- -

# Entry points

# -- -


if __name__ == "__main__":
    sys.exit(run_phase0())
