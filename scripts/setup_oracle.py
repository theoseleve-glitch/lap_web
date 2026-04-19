#!/usr/bin/env python
"""Pre-flight setup and checks for the Lap Oracle system.

Verifies Python dependencies, sim install paths, data zip files,
creates the directory structure, and optionally installs the AC
bridge app.

Usage
-----
    python scripts/setup_oracle.py
"""
from __future__ import annotations

import importlib
import shutil
import sys
from pathlib import Path

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from telemetry_tool.lap_oracle.config import (
    DATA_ZIPS,
    ORACLE_DATA,
    SIM_PATHS,
    OracleConfig,
)

# Required Python packages and their import names
_REQUIRED_DEPS = [
    ("casadi", "casadi"),
    ("torch", "torch"),
    ("gymnasium", "gymnasium"),
    ("stable_baselines3", "stable_baselines3"),
    ("scipy", "scipy"),
    ("numpy", "numpy"),
]


def _check_deps() -> list[str]:
    """Check that required Python packages are importable."""
    missing: list[str] = []
    for pip_name, import_name in _REQUIRED_DEPS:
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing.append(pip_name)
    return missing


def _check_sims() -> dict[str, list[Path]]:
    """Check which sim install paths exist."""
    found: dict[str, list[Path]] = {}
    for sim, paths in SIM_PATHS.items():
        existing = [p for p in paths if p.exists()]
        if existing:
            found[sim] = existing
    return found


def _check_data_zips() -> dict[str, tuple[Path, bool, int]]:
    """Check data zip files.  Returns name -> (path, exists, size_mb)."""
    results: dict[str, tuple[Path, bool, int]] = {}
    for name, path in DATA_ZIPS.items():
        exists = path.exists()
        size_mb = int(path.stat().st_size / (1024 * 1024)) if exists else 0
        results[name] = (path, exists, size_mb)
    return results


def _install_ac_bridge(config: OracleConfig) -> bool:
    """Copy AC bridge app to the AC apps directory.

    Returns True if installed successfully, False otherwise.
    """
    bridge_src = (
        Path(__file__).resolve().parents[1]
        / "telemetry_tool" / "lap_oracle" / "rl" / "ac_bridge"
    )
    if not bridge_src.exists():
        print(f"  [!] Bridge source not found: {bridge_src}")
        return False

    dest = config.ac_apps_dir / "lap_oracle_bridge"
    try:
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(bridge_src, dest)
        print(f"  [OK] AC bridge installed to {dest}")
        return True
    except OSError as exc:
        print(f"  [!] Failed to install AC bridge: {exc}")
        return False


def _create_directories() -> None:
    """Create the oracle data directory structure."""
    for sub in (
        "telemetry", "tracks", "vehicles", "solutions",
        "setups", "models", "reports",
    ):
        (ORACLE_DATA / sub).mkdir(parents=True, exist_ok=True)


def main() -> None:
    print("=" * 60)
    print("  Lap Oracle -- Pre-flight Setup")
    print("=" * 60)
    print()

    config = OracleConfig()

    # 1. Python dependencies
    print("[1] Python Dependencies")
    missing = _check_deps()
    if missing:
        print(f"  MISSING: {', '.join(missing)}")
        print(f"  Install with: pip install {' '.join(missing)}")
    else:
        print("  All required packages found.")
    print()

    # 2. Sim install paths
    print("[2] Sim Install Paths")
    found_sims = _check_sims()
    for sim in SIM_PATHS:
        if sim in found_sims:
            for p in found_sims[sim]:
                print(f"  [OK] {sim}: {p}")
        else:
            print(f"  [--] {sim}: not found")
    print()

    # 3. Data zip files
    print("[3] External Data Files")
    zips = _check_data_zips()
    total_mb = 0
    found_count = 0
    for name, (path, exists, size_mb) in sorted(zips.items()):
        if exists:
            print(f"  [OK] {name}: {path.name} ({size_mb} MB)")
            total_mb += size_mb
            found_count += 1
        else:
            print(f"  [--] {name}: {path.name} (not found)")
    print(f"  Total: {found_count}/{len(zips)} files, {total_mb} MB")
    print()

    # 4. AC bridge app
    print("[4] AC Bridge App")
    if config.enable_ac_driver:
        if config.ac_apps_dir.exists():
            _install_ac_bridge(config)
        else:
            print(f"  [--] AC apps dir not found: {config.ac_apps_dir}")
    else:
        print("  Skipped (AC driver disabled).")
    print()

    # 5. Directory structure
    print("[5] Directory Structure")
    _create_directories()
    print(f"  Created: {ORACLE_DATA}")
    print()

    # Summary
    print("=" * 60)
    all_ok = len(missing) == 0
    if all_ok:
        print("  Ready to launch!  Run:")
        print("    python scripts/launch_oracle.py")
    else:
        print("  Setup incomplete -- fix issues above before launching.")
    print("=" * 60)


if __name__ == "__main__":
    main()
