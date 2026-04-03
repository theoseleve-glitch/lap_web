"""Lap Oracle configuration -- shared dataclasses and constants.

Every downstream module imports from here.  All dataclasses use
``field(default_factory=...)`` for mutable defaults.  Serialization
is JSON-only.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

# -- Project paths -----------------------------------------------------
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
ORACLE_DATA: Path = PROJECT_ROOT / "data" / "oracle"
ORACLE_DB: Path = ORACLE_DATA / "oracle.db"

# -- Discovered sim install paths --------------------------------------
SIM_PATHS: Dict[str, List[Path]] = {
    "ac": [
        Path("D:/SteamLibrary/steamapps/common/assettocorsa"),  # primary (has CSP)
        Path("C:/Program Files (x86)/Steam/steamapps/common/assettocorsa"),
    ],
    "acc": [
        Path(
            "C:/Program Files (x86)/Steam/steamapps/common/"
            "Assetto Corsa Competizione"
        ),
    ],
    "lmu": [
        Path("D:/SteamLibrary/steamapps/common/Le Mans Ultimate"),
    ],
    "iracing": [
        Path("C:/Users/Admin/Documents/iRacing"),
    ],
}

# -- External data zip paths -------------------------------------------
_DL = Path("C:/Users/Admin/Downloads")
DATA_ZIPS: Dict[str, Path] = {
    "f1_2022": _DL / "2022-main.zip",
    "f1_2023": _DL / "2023-main.zip",
    "f1_2024": _DL / "2024-main.zip",
    "f1_2025": _DL / "2025-main.zip",
    "f1_2026": _DL / "2026-main.zip",
    "raw_kart": _DL / "raw.zip",
    "dallara": _DL / "archive (1).zip",
    "motorsport": _DL / "archive (2).zip",
    "simulated": _DL / "archive (3).zip",
    "kaggle_f1": _DL / "archive.zip",
}


# -- Tyre model --------------------------------------------------------

@dataclass(frozen=True)
class PacejkaParams:
    """Pacejka Magic Formula coefficients (simplified form).

    F = D * sin(C * arctan(B*x - E*(B*x - arctan(B*x))))
    """

    B: float = 10.0
    C: float = 1.3
    D: float = 1.0
    E: float = -0.5

    def to_array(self) -> np.ndarray:
        return np.array([self.B, self.C, self.D, self.E], dtype=np.float64)

    @classmethod
    def from_array(cls, arr: np.ndarray) -> PacejkaParams:
        return cls(B=float(arr[0]), C=float(arr[1]),
                   D=float(arr[2]), E=float(arr[3]))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> PacejkaParams:
        return cls(**d)


# -- Vehicle setup -----------------------------------------------------

@dataclass
class SetupParams:
    """Car setup parameters -- the search space for setup sweeps."""

    front_wing: float = 5.0
    rear_wing: float = 5.0
    front_arb: float = 3.0
    rear_arb: float = 3.0
    front_spring: float = 80000.0
    rear_spring: float = 80000.0
    front_ride_height: float = 0.030
    rear_ride_height: float = 0.035
    front_camber: float = -3.0
    rear_camber: float = -1.5
    front_toe: float = -0.1
    rear_toe: float = 0.2
    brake_bias: float = 0.57
    brake_pressure: float = 100.0
    diff_preload: float = 40.0
    diff_power_ramp: float = 50.0
    diff_coast_ramp: float = 30.0
    front_pressure_psi: float = 26.0
    rear_pressure_psi: float = 25.0

    def to_array(self) -> np.ndarray:
        """Return all setup values as a flat numpy array."""
        return np.array(
            [getattr(self, f.name) for f in fields(self)],
            dtype=np.float64,
        )

    @classmethod
    def from_array(cls, arr: np.ndarray) -> SetupParams:
        """Reconstruct from a flat array (same order as ``to_array``)."""
        names = [f.name for f in fields(cls)]
        if len(arr) != len(names):
            raise ValueError(
                f"Expected {len(names)} values, got {len(arr)}"
            )
        return cls(**{n: float(arr[i]) for i, n in enumerate(names)})

    @classmethod
    def n_params(cls) -> int:
        """Number of tuneable setup parameters."""
        return len(fields(cls))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> SetupParams:
        return cls(**d)


# -- Vehicle -----------------------------------------------------------

@dataclass
class VehicleParams:
    """Full vehicle specification for physics simulation."""

    sim: str = ""
    car_name: str = ""
    mass_kg: float = 1300.0
    wheelbase_m: float = 2.65
    track_width_front_m: float = 1.6
    track_width_rear_m: float = 1.6
    cg_height_m: float = 0.35
    weight_dist_front: float = 0.47
    cda: float = 0.80
    cla: float = 2.5
    max_power_w: float = 400_000.0
    max_brake_decel: float = 12.0
    tyre_lat: PacejkaParams = field(default_factory=PacejkaParams)
    tyre_long: PacejkaParams = field(
        default_factory=lambda: PacejkaParams(B=12.0, C=1.4, D=1.0, E=-0.3),
    )
    setup: SetupParams = field(default_factory=SetupParams)

    def to_dict(self) -> dict:
        """Serialize to a plain dict (JSON-safe except numpy)."""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> VehicleParams:
        """Reconstruct from dict, handling nested PacejkaParams/SetupParams."""
        d = dict(d)  # shallow copy
        if "tyre_lat" in d and isinstance(d["tyre_lat"], dict):
            d["tyre_lat"] = PacejkaParams.from_dict(d["tyre_lat"])
        if "tyre_long" in d and isinstance(d["tyre_long"], dict):
            d["tyre_long"] = PacejkaParams.from_dict(d["tyre_long"])
        if "setup" in d and isinstance(d["setup"], dict):
            d["setup"] = SetupParams.from_dict(d["setup"])
        return cls(**d)


# -- Track -------------------------------------------------------------

@dataclass
class TrackModel:
    """Discretized track representation for the OCP solver."""

    name: str = ""
    sim: str = ""
    centerline_xy: np.ndarray = field(
        default_factory=lambda: np.empty((0, 2), dtype=np.float64),
    )
    width_left: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=np.float64),
    )
    width_right: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=np.float64),
    )
    curvature: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=np.float64),
    )
    elevation: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=np.float64),
    )
    banking: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=np.float64),
    )
    grip_map: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=np.float64),
    )
    sector_boundaries: List[int] = field(default_factory=list)
    total_length_m: float = 0.0

    @property
    def n_points(self) -> int:
        """Number of discretization points."""
        return self.centerline_xy.shape[0]

    @property
    def ds(self) -> np.ndarray:
        """Distance step between consecutive centerline points."""
        if self.n_points < 2:
            return np.empty(0, dtype=np.float64)
        diffs = np.diff(self.centerline_xy, axis=0)
        return np.sqrt((diffs ** 2).sum(axis=1))


# -- Weather -----------------------------------------------------------

@dataclass(frozen=True)
class WeatherConditions:
    """Track-session weather snapshot (frozen for hashing)."""

    air_temp_c: float = 25.0
    track_temp_c: float = 35.0
    humidity_pct: float = 0.5
    is_wet: bool = False
    rain_intensity: float = 0.0
    wind_speed_ms: float = 0.0
    wind_direction_rad: float = 0.0
    grip_multiplier: float = 1.0

    def to_array(self) -> np.ndarray:
        """10-element normalized feature vector.

        Elements:
          0: air_temp_c / 50
          1: track_temp_c / 70
          2: humidity_pct (already 0-1)
          3: float(is_wet)
          4: rain_intensity (0-1 clipped)
          5: wind_speed_ms / 30
          6: sin(wind_direction_rad)
          7: cos(wind_direction_rad)
          8: grip_multiplier
          9: track_temp_c - air_temp_c (delta, / 30)
        """
        return np.array([
            self.air_temp_c / 50.0,
            self.track_temp_c / 70.0,
            self.humidity_pct,
            float(self.is_wet),
            np.clip(self.rain_intensity, 0.0, 1.0),
            self.wind_speed_ms / 30.0,
            np.sin(self.wind_direction_rad),
            np.cos(self.wind_direction_rad),
            self.grip_multiplier,
            (self.track_temp_c - self.air_temp_c) / 30.0,
        ], dtype=np.float64)


# -- OCP solution ------------------------------------------------------

@dataclass
class OCPSolution:
    """Result of an optimal-control-problem solve."""

    sim: str = ""
    track_name: str = ""
    car_name: str = ""
    weather: WeatherConditions = field(default_factory=WeatherConditions)
    optimal_lap_time_s: float = 0.0
    sector_times_s: List[float] = field(default_factory=list)
    distance_m: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=np.float64),
    )
    speed_mps: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=np.float64),
    )
    throttle: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=np.float64),
    )
    brake: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=np.float64),
    )
    steering_rad: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=np.float64),
    )
    lateral_offset_m: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=np.float64),
    )
    solver_status: str = "unsolved"
    solver_time_s: float = 0.0
    vehicle_params: Optional[VehicleParams] = None


# -- Oracle runtime config ---------------------------------------------

@dataclass
class OracleConfig:
    """Top-level configuration for a 48-hour oracle run."""

    # -- Run parameters ------------------------------------------------
    run_hours: float = 48.0
    data_dir: Path = field(default_factory=lambda: ORACLE_DATA)
    db_path: Path = field(default_factory=lambda: ORACLE_DB)

    # -- Worker counts -------------------------------------------------
    harvest_workers: int = 4
    identify_workers: int = 2
    solve_workers: int = 4
    sweep_workers: int = 2

    # -- Feature flags -------------------------------------------------
    enable_ac_driver: bool = True
    enable_neural_training: bool = True

    # -- OCP solver parameters -----------------------------------------
    ocp_n_points: int = 500
    ocp_max_solve_time: float = 120.0

    # -- RL parameters -------------------------------------------------
    rl_lr: float = 3e-4
    rl_gamma: float = 0.99
    rl_batch_size: int = 256
    rl_buffer_size: int = 100_000

    # -- Assetto Corsa paths -------------------------------------------
    ac_exe: Path = field(
        default_factory=lambda: (
            SIM_PATHS["ac"][0] / "AssettoCorsa.exe"
            if SIM_PATHS["ac"]
            else Path("AssettoCorsa.exe")
        ),
    )
    ac_cfg_dir: Path = field(
        default_factory=lambda: Path(
            "C:/Users/Admin/Documents/Assetto Corsa/cfg"
        ),
    )
    ac_apps_dir: Path = field(
        default_factory=lambda: (
            SIM_PATHS["ac"][0] / "apps" / "python"
            if SIM_PATHS["ac"]
            else Path("apps/python")
        ),
    )
    ac_bridge_port: int = 9876
    ac_launch_timeout: int = 90
    ac_max_retries: int = 3

    # -- Neural surrogate parameters -----------------------------------
    neural_lr: float = 1e-3
    neural_batch_size: int = 2048
    neural_checkpoint_minutes: int = 30

    # -- Setup sweep parameters ----------------------------------------
    sweep_n_samples: int = 100
