"""Ops tooling — safe procedural operations for productionization.

Pure functions that future operators can call without understanding the
research stack:

  - add_vehicle_profile / deprecate_profile / activate_profile / list_profiles
  - add_dataset_to_manifest / validate_manifest
  - inspect_accumulator
  - smoke_test_manifest

Each function returns a structured result + a human-readable message.
The script ``scripts/ops.py`` wraps these in argparse subcommands.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── Result envelopes ─────────────────────────────────────────


@dataclass
class OpsResult:
    """Standardized return value for ops functions."""
    ok: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


# ── Vehicle calibration registry ops ─────────────────────────


def add_vehicle_profile(
    *,
    registry_path: Path,
    profile_id: str,
    vehicle_key: str,
    vehicle_class: str,
    tire_d1_lat: float,
    tire_d1_long: float,
    roll_compliance: float,
    pitch_compliance: float = 0.003,
    fit_method: str = "manual",
    n_samples: int = 0,
    notes: str = "",
    activate: bool = True,
) -> OpsResult:
    """Add a new calibration profile to the registry."""
    from track_surface.vehicle_calibration_registry import (
        RoadStateCalibration,
        TireCalibration,
        VehicleCalibrationRegistry,
        make_profile,
    )

    p = Path(registry_path)
    reg = VehicleCalibrationRegistry.load(p)

    existing = reg.get_by_id(profile_id)
    if existing is not None:
        return OpsResult(
            ok=False,
            message=f"Profile {profile_id!r} already exists. Use --force or pick a different id.",
            details={"existing": existing.to_dict()},
        )

    next_version = reg.next_version_for(vehicle_key)
    profile = make_profile(
        profile_id=profile_id,
        vehicle_key=vehicle_key,
        vehicle_class=vehicle_class,
        tire=TireCalibration(
            d1_lat=tire_d1_lat, d1_long=tire_d1_long,
            d2_lat=-0.0001, d2_long=-0.0001,
        ),
        road_state=RoadStateCalibration(
            roll_compliance_rad_per_mps2=roll_compliance,
            pitch_compliance_rad_per_mps2=pitch_compliance,
        ),
        session_id="<manual>",
        fit_method=fit_method,
        n_samples=n_samples,
        calibration_version=next_version,
        active=activate,
        notes=notes,
    )
    reg.upsert(profile)
    reg.save(p)
    return OpsResult(
        ok=True,
        message=f"Added profile {profile_id!r} (v{next_version}, vehicle_key={vehicle_key!r}, active={activate}).",
        details={"profile": profile.to_dict()},
    )


def deprecate_profile(*, registry_path: Path, profile_id: str, reason: str = "") -> OpsResult:
    from track_surface.vehicle_calibration_registry import VehicleCalibrationRegistry

    p = Path(registry_path)
    reg = VehicleCalibrationRegistry.load(p)
    if reg.get_by_id(profile_id) is None:
        return OpsResult(
            ok=False,
            message=f"Profile {profile_id!r} not found in registry.",
        )
    reg.deprecate(profile_id, reason=reason)
    reg.save(p)
    return OpsResult(
        ok=True,
        message=f"Deprecated {profile_id!r}." + (f" Reason: {reason}" if reason else ""),
    )


def activate_profile(*, registry_path: Path, profile_id: str) -> OpsResult:
    """Activate a profile — automatically deactivates other profiles
    for the same vehicle_key (single-active invariant)."""
    from dataclasses import replace as _replace
    from datetime import datetime, timezone
    from track_surface.vehicle_calibration_registry import VehicleCalibrationRegistry

    p = Path(registry_path)
    reg = VehicleCalibrationRegistry.load(p)
    target = reg.get_by_id(profile_id)
    if target is None:
        return OpsResult(
            ok=False,
            message=f"Profile {profile_id!r} not found.",
        )
    if target.deprecated:
        return OpsResult(
            ok=False,
            message=f"Profile {profile_id!r} is deprecated — un-deprecate first.",
        )
    # Re-upsert with active=True triggers the single-active invariant
    activated = _replace(
        target, active=True,
        updated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    reg.upsert(activated)
    reg.save(p)
    return OpsResult(
        ok=True,
        message=f"Activated {profile_id!r} (other {target.vehicle_key!r} profiles deactivated).",
    )


def list_profiles(*, registry_path: Path) -> OpsResult:
    from track_surface.vehicle_calibration_registry import VehicleCalibrationRegistry

    p = Path(registry_path)
    reg = VehicleCalibrationRegistry.load(p)
    rows: list[dict[str, Any]] = []
    for prof in reg.profiles:
        rows.append({
            "profile_id": prof.profile_id,
            "vehicle_key": prof.vehicle_key,
            "vehicle_class": prof.vehicle_class,
            "version": prof.calibration_version,
            "active": prof.active,
            "deprecated": prof.deprecated,
            "tire_d1_lat": prof.tire.d1_lat,
            "roll_compliance": prof.road_state.roll_compliance_rad_per_mps2,
            "fit_method": prof.provenance.fit_method,
            "n_samples": prof.provenance.n_samples,
            "updated_at": prof.updated_at,
        })
    return OpsResult(
        ok=True,
        message=f"{len(rows)} profile(s) in registry.",
        details={"profiles": rows},
    )


# ── Manifest ops ─────────────────────────────────────────────


def add_dataset_to_manifest(
    *,
    manifest_path: Path,
    entry: dict[str, Any],
) -> OpsResult:
    """Append a dataset entry to the manifest after schema validation.

    The entry dict must follow the manifest schema (see manifest.py).
    """
    from track_surface.validation.manifest import _parse_entry

    p = Path(manifest_path)
    if not p.is_file():
        return OpsResult(ok=False, message=f"Manifest not found: {p}")
    with open(p, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if "datasets" not in raw or not isinstance(raw["datasets"], list):
        return OpsResult(ok=False, message="Manifest has no 'datasets' list.")

    # Validate the new entry by parsing it
    try:
        new_entry = _parse_entry(entry, len(raw["datasets"]))
    except Exception as e:
        return OpsResult(
            ok=False,
            message=f"Entry rejected by validator: {type(e).__name__}: {e}",
        )

    existing_ids = {d.get("id") for d in raw["datasets"] if isinstance(d, dict)}
    if new_entry.id in existing_ids:
        return OpsResult(
            ok=False,
            message=f"Dataset id {new_entry.id!r} already in manifest.",
        )

    raw["datasets"].append(entry)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2)
    return OpsResult(
        ok=True,
        message=f"Added dataset {new_entry.id!r} to manifest ({len(raw['datasets'])} total).",
    )


def validate_manifest(*, manifest_path: Path) -> OpsResult:
    """Validate the manifest end-to-end. Returns details about each entry."""
    from track_surface.validation.manifest import load_manifest

    p = Path(manifest_path)
    try:
        manifest = load_manifest(p)
    except Exception as e:
        return OpsResult(
            ok=False,
            message=f"Manifest invalid: {type(e).__name__}: {e}",
        )

    rows = []
    for e in manifest.datasets:
        rows.append({
            "id": e.id, "group": e.group,
            "track": e.track.name, "vehicle": e.vehicle.name,
            "ibt_exists": e.file_exists,
        })
    n_present = sum(1 for r in rows if r["ibt_exists"])
    return OpsResult(
        ok=True,
        message=(
            f"Manifest version {manifest.version} valid: "
            f"{len(manifest.datasets)} datasets, "
            f"{n_present} with .ibt present, {len(manifest.datasets) - n_present} missing."
        ),
        details={"datasets": rows},
    )


# ── Accumulator ops ──────────────────────────────────────────


def inspect_accumulator(*, accumulator_dir: Path) -> OpsResult:
    """Summarize all accumulators in a directory."""
    d = Path(accumulator_dir)
    if not d.is_dir():
        return OpsResult(ok=False, message=f"Accumulator dir not found: {d}")
    entries = []
    for json_path in sorted(d.glob("*.json")):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                sidecar = json.load(f)
        except Exception as e:
            entries.append({
                "key": json_path.stem, "error": f"{type(e).__name__}: {e}",
            })
            continue
        contributing = [c.get("session_id") for c in sidecar.get("contributions", [])]
        rejected = sidecar.get("rejections", [])
        per_bucket_counts = {}
        for c in sidecar.get("contributions", []):
            for bk, count in c.get("bucket_breakdown", {}).items():
                per_bucket_counts[bk] = per_bucket_counts.get(bk, 0) + int(count)
        entries.append({
            "key": json_path.stem,
            "track": sidecar.get("track_fingerprint", {}).get("name", "?"),
            "calibration_profile_id": sidecar.get("calibration_profile_id"),
            "n_contributions": len(contributing),
            "contributing_sessions": contributing,
            "n_rejections": len(rejected),
            "rejection_reasons": [r.get("reason") for r in rejected],
            "per_bucket_cells_added": per_bucket_counts,
            "saved_at": sidecar.get("saved_at"),
        })
    return OpsResult(
        ok=True,
        message=f"{len(entries)} accumulator(s) in {d}.",
        details={"accumulators": entries},
    )


# ── Smoke test ───────────────────────────────────────────────


def smoke_test_manifest(
    *,
    manifest_path: Path,
    only: list[str] | None = None,
    max_datasets: int = 1,
) -> OpsResult:
    """Pick the smallest N datasets from the manifest for a smoke run.

    Returns the dataset ids that should be passed to the release gate
    via ``--only``. Selection prefers datasets whose .ibt file exists
    on disk and has the smallest file size, since smoke runs are
    intentionally short.
    """
    from track_surface.validation.manifest import load_manifest

    p = Path(manifest_path)
    try:
        manifest = load_manifest(p)
    except Exception as e:
        return OpsResult(ok=False, message=f"Manifest load failed: {e}")

    candidates = manifest.datasets
    if only:
        wanted = set(only)
        candidates = [e for e in candidates if e.id in wanted]
        missing = wanted - {e.id for e in candidates}
        if missing:
            return OpsResult(
                ok=False,
                message=f"Manifest missing requested ids: {sorted(missing)}",
            )

    # Filter to those with files on disk and rank by file size
    available = []
    for e in candidates:
        ibt = Path(e.ibt_path)
        if not ibt.is_file():
            continue
        available.append((e.id, ibt.stat().st_size))

    if not available:
        return OpsResult(
            ok=False,
            message="No manifest datasets with .ibt files present on disk.",
        )

    available.sort(key=lambda x: x[1])
    chosen = [eid for eid, _ in available[:max_datasets]]
    return OpsResult(
        ok=True,
        message=f"Smoke selection: {chosen} (smallest .ibt files of {len(available)} available).",
        details={"chosen_ids": chosen},
    )
