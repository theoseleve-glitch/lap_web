"""Vehicle calibration registry — first-class storage for fitted parameters.

The cross-track validation showed that GT4-tuned tire D and roll
compliance do not transfer to other vehicles. This module is the
infrastructure for storing per-vehicle calibration profiles so the
pipeline can use the right values without per-session refitting.

Design rules:
  - Profiles are first-class. No buried metadata blobs.
  - Each profile has explicit version, provenance, fit quality.
  - Active vs deprecated is part of the data model, not a hack.
  - Resolution rule: exact vehicle hit, then class fallback, then default.
  - Default fallback is explicit so callers always know they got it.

The registry is a single JSON file. It's small (a few KB per car), and
JSON is inspectable. If we ever outgrow it, swap to SQLite without
changing the public API.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

logger = logging.getLogger(__name__)


# ── Calibration sub-records ──────────────────────────────────


@dataclass(frozen=True)
class FitQuality:
    """How good was the fit that produced these parameters?"""
    n_samples: int
    residual: float                  # primary residual metric (units depend on context)
    fit_std: float | None = None     # parameter standard error if known
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FitProvenance:
    """Where did this calibration come from?"""
    session_id: str                  # the session/run that produced the fit
    fit_method: str                  # "frozen_baseline" | "session_fit" | "manual" | "default"
    harness_version: str
    fit_date: str                    # ISO-8601 UTC
    n_samples: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TireCalibration:
    """Tire model parameters for one vehicle."""
    d1_lat: float
    d1_long: float
    d2_lat: float
    d2_long: float
    k_lat_scale: float = 1.0         # multiplier from baseline (1.0 = no scaling)
    fit_quality: FitQuality | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.fit_quality is not None:
            d["fit_quality"] = self.fit_quality.to_dict()
        return d


@dataclass(frozen=True)
class RoadStateCalibration:
    """Road-state estimator parameters for one vehicle."""
    roll_compliance_rad_per_mps2: float
    pitch_compliance_rad_per_mps2: float
    smooth_window: int = 60
    transition_threshold: float = 0.008
    fit_quality: FitQuality | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.fit_quality is not None:
            d["fit_quality"] = self.fit_quality.to_dict()
        return d


# ── Profile ──────────────────────────────────────────────────


@dataclass(frozen=True)
class CalibrationProfile:
    """One full calibration profile — a versioned, named record."""
    profile_id: str                  # unique within the registry
    vehicle_key: str                 # e.g. "mclaren570sgt4"
    vehicle_class: str               # e.g. "GT4"
    calibration_version: int         # monotonically increasing per vehicle_key
    active: bool                     # whether this is the live profile
    deprecated: bool                 # explicitly retired (mutually exclusive with active)
    created_at: str
    updated_at: str
    tire: TireCalibration
    road_state: RoadStateCalibration
    provenance: FitProvenance
    notes: str = ""

    def __post_init__(self) -> None:
        if self.active and self.deprecated:
            raise ValueError(
                f"Profile {self.profile_id!r}: cannot be both active and deprecated"
            )
        if self.calibration_version < 1:
            raise ValueError(
                f"Profile {self.profile_id!r}: calibration_version must be >= 1"
            )
        if not self.profile_id:
            raise ValueError("profile_id must be non-empty")
        if not self.vehicle_key:
            raise ValueError("vehicle_key must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "vehicle_key": self.vehicle_key,
            "vehicle_class": self.vehicle_class,
            "calibration_version": self.calibration_version,
            "active": self.active,
            "deprecated": self.deprecated,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "notes": self.notes,
            "tire": self.tire.to_dict(),
            "road_state": self.road_state.to_dict(),
            "provenance": self.provenance.to_dict(),
        }


# ── Default fallback ─────────────────────────────────────────


_DEFAULT_HARNESS_VERSION: Final[str] = "validation_v1"


def default_calibration(vehicle_key: str, vehicle_class: str = "unknown") -> CalibrationProfile:
    """Build a default profile when no fitted calibration exists.

    These are the values the validation harness uses as fallbacks. They
    represent "what we know without fitting" — neutral starting points,
    not anyone's best guess for that vehicle.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return CalibrationProfile(
        profile_id=f"default_{vehicle_key}",
        vehicle_key=vehicle_key,
        vehicle_class=vehicle_class,
        calibration_version=1,
        active=False,                # defaults are NEVER active
        deprecated=False,
        created_at=now,
        updated_at=now,
        tire=TireCalibration(
            d1_lat=2.8,
            d1_long=2.7,
            d2_lat=-0.0001,
            d2_long=-0.0001,
            k_lat_scale=1.0,
            fit_quality=None,
        ),
        road_state=RoadStateCalibration(
            roll_compliance_rad_per_mps2=0.005,
            pitch_compliance_rad_per_mps2=0.003,
            smooth_window=60,
            transition_threshold=0.008,
            fit_quality=None,
        ),
        provenance=FitProvenance(
            session_id="<none>",
            fit_method="default",
            harness_version=_DEFAULT_HARNESS_VERSION,
            fit_date=now,
            n_samples=0,
        ),
        notes="Default fallback — no fitted calibration available for this vehicle",
    )


# ── Registry ─────────────────────────────────────────────────


@dataclass
class ResolvedCalibration:
    """The result of resolving a vehicle to a calibration profile."""
    profile: CalibrationProfile
    source: str                      # "registry_active" | "registry_class_fallback" | "default_fallback"
    matched_vehicle_key: str         # may differ from query when class fallback was used


class VehicleCalibrationRegistry:
    """Collection of CalibrationProfiles with active/version semantics.

    Persistence: one JSON file. Load with .load(path), save with .save().
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path: Path | None = Path(path) if path is not None else None
        self.profiles: list[CalibrationProfile] = []

    # ── Persistence ──────────────────────────────────────────

    @classmethod
    def load(cls, path: Path | str) -> "VehicleCalibrationRegistry":
        p = Path(path)
        registry = cls(p)
        if not p.is_file():
            return registry  # empty registry — caller will populate

        with open(p, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict) or raw.get("version") != 1:
            raise ValueError(f"Unsupported registry version in {p}")
        for d in raw.get("profiles", []):
            registry.profiles.append(_profile_from_dict(d))
        # Validate uniqueness of profile_ids
        seen: set[str] = set()
        for p_ in registry.profiles:
            if p_.profile_id in seen:
                raise ValueError(f"Duplicate profile_id in registry: {p_.profile_id!r}")
            seen.add(p_.profile_id)
        return registry

    def save(self, path: Path | str | None = None) -> None:
        target = Path(path) if path is not None else self.path
        if target is None:
            raise ValueError("No path set on registry — pass path= to save()")
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "profiles": [p.to_dict() for p in self.profiles],
        }
        with open(target, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        self.path = target

    # ── Lookup ───────────────────────────────────────────────

    def get_by_id(self, profile_id: str) -> CalibrationProfile | None:
        for p in self.profiles:
            if p.profile_id == profile_id:
                return p
        return None

    def list_for_vehicle(self, vehicle_key: str) -> list[CalibrationProfile]:
        """All profiles for a given vehicle_key — active, deprecated, all versions."""
        return [p for p in self.profiles if p.vehicle_key == vehicle_key]

    def get_active(self, vehicle_key: str) -> CalibrationProfile | None:
        """The single active profile for this vehicle. Multiple is an error."""
        active = [p for p in self.profiles if p.vehicle_key == vehicle_key and p.active]
        if len(active) > 1:
            raise RuntimeError(
                f"Registry has {len(active)} active profiles for vehicle {vehicle_key!r}: "
                f"{[p.profile_id for p in active]} — exactly one must be active"
            )
        return active[0] if active else None

    def list_active(self) -> list[CalibrationProfile]:
        return [p for p in self.profiles if p.active]

    # ── Mutation ─────────────────────────────────────────────

    def upsert(self, profile: CalibrationProfile) -> None:
        """Insert or update a profile.

        If a profile with the same profile_id exists, it is replaced.
        If `profile.active` is True, all OTHER profiles for the same
        vehicle_key are deactivated automatically (only one active per vehicle).
        """
        existing_idx = None
        for i, p in enumerate(self.profiles):
            if p.profile_id == profile.profile_id:
                existing_idx = i
                break

        if existing_idx is not None:
            self.profiles[existing_idx] = profile
        else:
            self.profiles.append(profile)

        # Enforce single-active invariant
        if profile.active:
            for i, p in enumerate(self.profiles):
                if p.vehicle_key == profile.vehicle_key and p.profile_id != profile.profile_id and p.active:
                    self.profiles[i] = replace(p, active=False, updated_at=_now_iso())

    def deprecate(self, profile_id: str, *, reason: str = "") -> None:
        """Mark a profile as deprecated (also clears the active flag)."""
        idx = None
        for i, p in enumerate(self.profiles):
            if p.profile_id == profile_id:
                idx = i
                break
        if idx is None:
            raise KeyError(f"No profile {profile_id!r} in registry")
        old = self.profiles[idx]
        notes = old.notes
        if reason:
            notes = (notes + " | " if notes else "") + f"DEPRECATED: {reason}"
        self.profiles[idx] = replace(
            old, active=False, deprecated=True,
            updated_at=_now_iso(), notes=notes,
        )

    # ── Resolution (the everyday path) ───────────────────────

    def resolve(
        self,
        vehicle_key: str,
        vehicle_class: str = "unknown",
    ) -> ResolvedCalibration:
        """Resolve a vehicle_key to a calibration profile.

        Resolution order:
          1. Active profile for exact vehicle_key
          2. Active profile for any vehicle in the same class
          3. Default fallback (constructed on the fly, never persisted)

        The returned ResolvedCalibration always has a usable profile and
        explicitly reports which source was used.
        """
        # Step 1: exact hit
        active = self.get_active(vehicle_key)
        if active is not None:
            return ResolvedCalibration(
                profile=active,
                source="registry_active",
                matched_vehicle_key=vehicle_key,
            )

        # Step 2: class fallback
        if vehicle_class and vehicle_class != "unknown":
            class_actives = [
                p for p in self.profiles
                if p.active and p.vehicle_class == vehicle_class
            ]
            if class_actives:
                # Pick the one with the most fit samples — most trustworthy
                best = max(
                    class_actives,
                    key=lambda p: p.provenance.n_samples,
                )
                logger.info(
                    "Vehicle %r has no profile; falling back to class %r profile %r",
                    vehicle_key, vehicle_class, best.profile_id,
                )
                return ResolvedCalibration(
                    profile=best,
                    source="registry_class_fallback",
                    matched_vehicle_key=best.vehicle_key,
                )

        # Step 3: default
        return ResolvedCalibration(
            profile=default_calibration(vehicle_key, vehicle_class),
            source="default_fallback",
            matched_vehicle_key=vehicle_key,
        )

    # ── Versioning helper ────────────────────────────────────

    def next_version_for(self, vehicle_key: str) -> int:
        existing = self.list_for_vehicle(vehicle_key)
        if not existing:
            return 1
        return max(p.calibration_version for p in existing) + 1


# ── Internal helpers ─────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fit_quality_from_dict(d: dict | None) -> FitQuality | None:
    if d is None:
        return None
    return FitQuality(
        n_samples=int(d["n_samples"]),
        residual=float(d["residual"]),
        fit_std=float(d["fit_std"]) if d.get("fit_std") is not None else None,
        notes=str(d.get("notes", "")),
    )


def _profile_from_dict(d: dict) -> CalibrationProfile:
    tire_d = d["tire"]
    road_d = d["road_state"]
    prov_d = d["provenance"]
    return CalibrationProfile(
        profile_id=str(d["profile_id"]),
        vehicle_key=str(d["vehicle_key"]),
        vehicle_class=str(d.get("vehicle_class", "unknown")),
        calibration_version=int(d["calibration_version"]),
        active=bool(d["active"]),
        deprecated=bool(d.get("deprecated", False)),
        created_at=str(d["created_at"]),
        updated_at=str(d["updated_at"]),
        notes=str(d.get("notes", "")),
        tire=TireCalibration(
            d1_lat=float(tire_d["d1_lat"]),
            d1_long=float(tire_d["d1_long"]),
            d2_lat=float(tire_d["d2_lat"]),
            d2_long=float(tire_d["d2_long"]),
            k_lat_scale=float(tire_d.get("k_lat_scale", 1.0)),
            fit_quality=_fit_quality_from_dict(tire_d.get("fit_quality")),
        ),
        road_state=RoadStateCalibration(
            roll_compliance_rad_per_mps2=float(road_d["roll_compliance_rad_per_mps2"]),
            pitch_compliance_rad_per_mps2=float(road_d["pitch_compliance_rad_per_mps2"]),
            smooth_window=int(road_d.get("smooth_window", 60)),
            transition_threshold=float(road_d.get("transition_threshold", 0.008)),
            fit_quality=_fit_quality_from_dict(road_d.get("fit_quality")),
        ),
        provenance=FitProvenance(
            session_id=str(prov_d["session_id"]),
            fit_method=str(prov_d["fit_method"]),
            harness_version=str(prov_d["harness_version"]),
            fit_date=str(prov_d["fit_date"]),
            n_samples=int(prov_d["n_samples"]),
        ),
    )


# ── Construction helpers ─────────────────────────────────────


def make_profile(
    *,
    profile_id: str,
    vehicle_key: str,
    vehicle_class: str,
    tire: TireCalibration,
    road_state: RoadStateCalibration,
    session_id: str,
    fit_method: str,
    n_samples: int,
    harness_version: str = _DEFAULT_HARNESS_VERSION,
    calibration_version: int = 1,
    active: bool = True,
    notes: str = "",
) -> CalibrationProfile:
    """Build a CalibrationProfile with sensible timestamps and provenance."""
    now = _now_iso()
    return CalibrationProfile(
        profile_id=profile_id,
        vehicle_key=vehicle_key,
        vehicle_class=vehicle_class,
        calibration_version=calibration_version,
        active=active,
        deprecated=False,
        created_at=now,
        updated_at=now,
        notes=notes,
        tire=tire,
        road_state=road_state,
        provenance=FitProvenance(
            session_id=session_id,
            fit_method=fit_method,
            harness_version=harness_version,
            fit_date=now,
            n_samples=n_samples,
        ),
    )
