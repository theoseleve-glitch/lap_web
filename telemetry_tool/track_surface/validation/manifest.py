"""Cross-track validation manifest format.

A manifest describes the datasets the validation harness should run on.
Each entry binds a telemetry file to its track, vehicle, and the
metric expectations we use to detect silent regressions.

The manifest is a plain JSON document — no PyYAML dependency.

Example
-------
{
  "version": 1,
  "datasets": [
    {
      "id": "daytona_mclaren570sgt4",
      "ibt_path": "C:/.../mclaren570sgt4_daytona ....ibt",
      "group": "A_banked",
      "track":   { "name": "Daytona", "regime": "banked", ... },
      "vehicle": { "name": "McLaren 570S GT4", "mass_kg": 1222.5, ... },
      "session": { "type": "practice", "kappa_available": false, ... },
      "expected": { "lambda_band": [0.8, 1.6], ... }
    }
  ]
}

Strict validation is preferred over silent defaults so transfer-test
regressions are not masked by missing metadata.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

# ── Allowed enum-like fields ─────────────────────────────────

_VALID_REGIMES: Final[set[str]] = {"banked", "flat", "mixed"}
_VALID_DRIVE_LAYOUTS: Final[set[str]] = {"RWD", "FWD", "AWD"}
_VALID_GROUPS: Final[set[str]] = {
    "A_banked",
    "B_flat_low_speed",
    "C_flat_high_speed",
    "D_different_car",
    "E_short_circuit",
    "F_other",
}
_VALID_SESSION_TYPES: Final[set[str]] = {
    "practice", "qualifying", "race", "test", "hotlap", "unknown",
}


# ── Sub-records ──────────────────────────────────────────────


@dataclass(frozen=True)
class TrackSpec:
    """Track / layout descriptor."""
    name: str
    layout: str                  # e.g. "2011_road", "full", "gp"
    regime: str                  # "banked" | "flat" | "mixed"
    expected_max_bank_deg: float = 0.0
    track_length_m: float | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if self.regime not in _VALID_REGIMES:
            raise ValueError(
                f"TrackSpec.regime must be one of {sorted(_VALID_REGIMES)}, "
                f"got {self.regime!r}"
            )


@dataclass(frozen=True)
class VehicleSpec:
    """Vehicle / chassis descriptor.

    The pipeline needs these to reconstruct per-wheel loads. Values
    here are seed values, not fits — the harness must NOT retune them
    per session in Pass 1.
    """
    name: str
    klass: str                   # e.g. "GT4", "TCR", "F3"
    drive_layout: str            # "RWD" | "FWD" | "AWD"
    mass_kg: float
    wheelbase_m: float
    track_front_m: float
    track_rear_m: float
    weight_dist_front: float     # 0-1
    aero_cla: float              # m²
    cg_height_m: float
    brake_bias_front: float      # 0-1
    steer_ratio: float
    camber_front_deg: float      # negative = top-in
    camber_rear_deg: float
    tire_d1_lat_default: float = 2.8
    tire_d1_long_default: float = 2.7

    def __post_init__(self) -> None:
        if self.drive_layout not in _VALID_DRIVE_LAYOUTS:
            raise ValueError(
                f"VehicleSpec.drive_layout must be one of "
                f"{sorted(_VALID_DRIVE_LAYOUTS)}, got {self.drive_layout!r}"
            )
        if not (0.0 < self.weight_dist_front < 1.0):
            raise ValueError(
                f"VehicleSpec.weight_dist_front must be in (0,1), "
                f"got {self.weight_dist_front}"
            )
        if not (0.0 < self.brake_bias_front < 1.0):
            raise ValueError(
                f"VehicleSpec.brake_bias_front must be in (0,1), "
                f"got {self.brake_bias_front}"
            )
        if self.mass_kg <= 0:
            raise ValueError(f"VehicleSpec.mass_kg must be > 0, got {self.mass_kg}")


@dataclass(frozen=True)
class SessionInfo:
    """Per-session ingestion hints."""
    type: str = "unknown"            # "practice" | "qualifying" | "race" | ...
    kappa_available: bool = False    # wheel speed → slip ratio
    ride_height_available: bool = True
    notes: str = ""

    def __post_init__(self) -> None:
        if self.type not in _VALID_SESSION_TYPES:
            raise ValueError(
                f"SessionInfo.type must be one of "
                f"{sorted(_VALID_SESSION_TYPES)}, got {self.type!r}"
            )


@dataclass(frozen=True)
class ExpectedMetrics:
    """Per-dataset expectations used to detect regressions.

    Wide bands so we don't false-flag honest variation, narrow enough
    to catch silent failures.
    """
    lambda_band: tuple[float, float] = (0.6, 1.6)   # median lambda must land here
    min_observability_pct: float = 5.0              # accepted-block fraction
    racing_line_lift_min: float = -0.05             # center >= mean(off)+lift
    min_field_coverage_pct: float = 5.0
    max_lap_to_lap_std: float = 0.20
    max_fy_residual_std: float = 3000.0  # N
    notes: str = ""


# ── Top-level entry ──────────────────────────────────────────


@dataclass(frozen=True)
class DatasetEntry:
    """One row in the manifest — a telemetry file plus all metadata."""
    id: str
    ibt_path: str
    group: str
    track: TrackSpec
    vehicle: VehicleSpec
    session: SessionInfo
    expected: ExpectedMetrics

    def __post_init__(self) -> None:
        if not self.id or not self.id.replace("_", "").replace("-", "").isalnum():
            raise ValueError(
                f"DatasetEntry.id must be alphanumeric (with _ or -), "
                f"got {self.id!r}"
            )
        if self.group not in _VALID_GROUPS:
            raise ValueError(
                f"DatasetEntry.group must be one of {sorted(_VALID_GROUPS)}, "
                f"got {self.group!r}"
            )

    @property
    def file_exists(self) -> bool:
        """Whether the .ibt file is reachable on disk RIGHT NOW."""
        return Path(self.ibt_path).is_file()


@dataclass
class ValidationManifest:
    """Parsed manifest with all datasets."""
    version: int
    datasets: list[DatasetEntry] = field(default_factory=list)

    @property
    def by_group(self) -> dict[str, list[DatasetEntry]]:
        """Group entries by benchmark group label."""
        result: dict[str, list[DatasetEntry]] = {}
        for entry in self.datasets:
            result.setdefault(entry.group, []).append(entry)
        return result

    def get(self, dataset_id: str) -> DatasetEntry:
        """Look up an entry by id."""
        for entry in self.datasets:
            if entry.id == dataset_id:
                return entry
        raise KeyError(f"No dataset with id {dataset_id!r} in manifest")

    def filter(self, ids: list[str] | None = None) -> list[DatasetEntry]:
        """Return entries matching the given ids, or all if None."""
        if ids is None:
            return list(self.datasets)
        wanted = set(ids)
        result = [e for e in self.datasets if e.id in wanted]
        missing = wanted - {e.id for e in result}
        if missing:
            raise KeyError(
                f"Manifest missing requested datasets: {sorted(missing)}"
            )
        return result


# ── Loading / parsing ────────────────────────────────────────


def _required(d: dict, key: str, ctx: str) -> object:
    if key not in d:
        raise ValueError(f"{ctx}: missing required field {key!r}")
    return d[key]


def _parse_track(d: dict, ctx: str) -> TrackSpec:
    return TrackSpec(
        name=str(_required(d, "name", ctx)),
        layout=str(_required(d, "layout", ctx)),
        regime=str(_required(d, "regime", ctx)),
        expected_max_bank_deg=float(d.get("expected_max_bank_deg", 0.0)),
        track_length_m=(
            float(d["track_length_m"]) if "track_length_m" in d else None
        ),
        notes=str(d.get("notes", "")),
    )


def _parse_vehicle(d: dict, ctx: str) -> VehicleSpec:
    return VehicleSpec(
        name=str(_required(d, "name", ctx)),
        klass=str(_required(d, "class", ctx)),
        drive_layout=str(_required(d, "drive_layout", ctx)),
        mass_kg=float(_required(d, "mass_kg", ctx)),
        wheelbase_m=float(_required(d, "wheelbase_m", ctx)),
        track_front_m=float(_required(d, "track_front_m", ctx)),
        track_rear_m=float(_required(d, "track_rear_m", ctx)),
        weight_dist_front=float(_required(d, "weight_dist_front", ctx)),
        aero_cla=float(_required(d, "aero_cla", ctx)),
        cg_height_m=float(_required(d, "cg_height_m", ctx)),
        brake_bias_front=float(_required(d, "brake_bias_front", ctx)),
        steer_ratio=float(_required(d, "steer_ratio", ctx)),
        camber_front_deg=float(_required(d, "camber_front_deg", ctx)),
        camber_rear_deg=float(_required(d, "camber_rear_deg", ctx)),
        tire_d1_lat_default=float(d.get("tire_d1_lat_default", 2.8)),
        tire_d1_long_default=float(d.get("tire_d1_long_default", 2.7)),
    )


def _parse_session(d: dict, ctx: str) -> SessionInfo:
    return SessionInfo(
        type=str(d.get("type", "unknown")),
        kappa_available=bool(d.get("kappa_available", False)),
        ride_height_available=bool(d.get("ride_height_available", True)),
        notes=str(d.get("notes", "")),
    )


def _parse_expected(d: dict | None, ctx: str) -> ExpectedMetrics:
    if d is None:
        return ExpectedMetrics()
    band = d.get("lambda_band", [0.6, 1.6])
    if not (isinstance(band, list) and len(band) == 2):
        raise ValueError(f"{ctx}: lambda_band must be a 2-element list")
    return ExpectedMetrics(
        lambda_band=(float(band[0]), float(band[1])),
        min_observability_pct=float(d.get("min_observability_pct", 5.0)),
        racing_line_lift_min=float(d.get("racing_line_lift_min", -0.05)),
        min_field_coverage_pct=float(d.get("min_field_coverage_pct", 5.0)),
        max_lap_to_lap_std=float(d.get("max_lap_to_lap_std", 0.20)),
        max_fy_residual_std=float(d.get("max_fy_residual_std", 3000.0)),
        notes=str(d.get("notes", "")),
    )


def _parse_entry(d: dict, idx: int) -> DatasetEntry:
    ctx = f"datasets[{idx}]"
    entry_id = str(_required(d, "id", ctx))
    return DatasetEntry(
        id=entry_id,
        ibt_path=str(_required(d, "ibt_path", ctx)),
        group=str(_required(d, "group", ctx)),
        track=_parse_track(_required(d, "track", ctx), f"{ctx}.track"),
        vehicle=_parse_vehicle(_required(d, "vehicle", ctx), f"{ctx}.vehicle"),
        session=_parse_session(d.get("session", {}), f"{ctx}.session"),
        expected=_parse_expected(d.get("expected"), f"{ctx}.expected"),
    )


def load_manifest(path: str | Path) -> ValidationManifest:
    """Load and validate a JSON manifest file.

    Raises
    ------
    FileNotFoundError : path does not exist
    ValueError        : structural / semantic validation failure
    json.JSONDecodeError : malformed JSON
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Manifest not found: {p}")

    with open(p, "r", encoding="utf-8") as f:
        raw = json.load(f)

    if not isinstance(raw, dict):
        raise ValueError("Manifest root must be a JSON object")
    if "version" not in raw:
        raise ValueError("Manifest missing 'version' field")
    version = int(raw["version"])
    if version != 1:
        raise ValueError(f"Unsupported manifest version: {version} (expected 1)")

    datasets_raw = raw.get("datasets", [])
    if not isinstance(datasets_raw, list):
        raise ValueError("Manifest 'datasets' must be a list")

    entries: list[DatasetEntry] = []
    seen_ids: set[str] = set()
    for i, d in enumerate(datasets_raw):
        if not isinstance(d, dict):
            raise ValueError(f"datasets[{i}]: must be an object")
        entry = _parse_entry(d, i)
        if entry.id in seen_ids:
            raise ValueError(f"Duplicate dataset id: {entry.id!r}")
        seen_ids.add(entry.id)
        entries.append(entry)

    return ValidationManifest(version=version, datasets=entries)
