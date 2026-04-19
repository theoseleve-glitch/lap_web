"""Oracle dataset -- loads OCP solutions for neural surrogate training.

Scans the ``solutions/`` directory for ``*_meta.json`` files and encodes
each as a (car_features, track_features, setup_features, weather_features,
targets) tuple.

Requires PyTorch; gracefully degrades if unavailable.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from telemetry_tool.lap_oracle.config import (
    PacejkaParams,
    SetupParams,
    VehicleParams,
    WeatherConditions,
)
from telemetry_tool.lap_oracle.neural.surrogate import (
    CAR_DIM,
    HAS_TORCH,
    SETUP_DIM,
    SPEED_PROFILE_N,
    TRACK_DIM,
    WEATHER_DIM,
)

logger = logging.getLogger(__name__)

if HAS_TORCH:
    import torch
    from torch.utils.data import Dataset as _TorchDataset

    _BASE = _TorchDataset
else:
    _BASE = object  # type: ignore[misc,assignment]


# -- Feature encoding helpers ----------------------------------------------

def _encode_car(vp: dict) -> np.ndarray:
    """Encode vehicle params dict into a fixed-size feature vector."""
    feats: List[float] = [
        vp.get("mass_kg", 1300.0) / 2000.0,
        vp.get("wheelbase_m", 2.65) / 4.0,
        vp.get("cda", 0.80) / 2.0,
        vp.get("cla", 2.5) / 5.0,
        vp.get("max_power_w", 400_000.0) / 1_000_000.0,
        vp.get("max_brake_decel", 12.0) / 20.0,
        vp.get("cg_height_m", 0.35) / 1.0,
        vp.get("weight_dist_front", 0.47),
        vp.get("track_width_front_m", 1.6) / 2.5,
        vp.get("track_width_rear_m", 1.6) / 2.5,
    ]
    # Add tyre params
    for tyre_key in ("tyre_lat", "tyre_long"):
        tp = vp.get(tyre_key, {})
        if isinstance(tp, dict):
            feats.extend([
                tp.get("B", 10.0) / 20.0,
                tp.get("C", 1.3) / 3.0,
                tp.get("D", 1.0) / 2.0,
                tp.get("E", -0.5) / 2.0,
            ])
        else:
            feats.extend([0.5, 0.43, 0.5, -0.25])

    # Pad to CAR_DIM
    arr = np.zeros(CAR_DIM, dtype=np.float32)
    arr[: len(feats)] = feats
    return arr


def _encode_track(meta: dict) -> np.ndarray:
    """Encode track metadata into a fixed-size feature vector."""
    arr = np.zeros(TRACK_DIM, dtype=np.float32)
    return arr


def _encode_setup(vp: dict) -> np.ndarray:
    """Encode setup params from vehicle dict."""
    setup = vp.get("setup", {})
    if isinstance(setup, dict):
        sp = SetupParams.from_dict(setup)
    else:
        sp = SetupParams()
    raw = sp.to_array()
    # Normalize each to rough [0, 1] range
    norms = np.array([
        20.0, 20.0, 10.0, 10.0,       # wings, arbs
        200_000.0, 200_000.0,            # springs
        0.1, 0.1,                        # ride heights
        10.0, 10.0,                      # cambers
        1.0, 1.0,                        # toe
        1.0, 200.0,                      # brake bias, pressure
        100.0, 100.0, 100.0,             # diff
        40.0, 40.0,                      # pressures
    ], dtype=np.float64)
    normalized = raw / norms
    arr = np.zeros(SETUP_DIM, dtype=np.float32)
    arr[: len(normalized)] = normalized.astype(np.float32)
    return arr


def _encode_weather(w: dict) -> np.ndarray:
    """Encode weather conditions dict."""
    wc = WeatherConditions(**{
        k: v for k, v in w.items()
        if k in WeatherConditions.__dataclass_fields__
    })
    return wc.to_array().astype(np.float32)


# -- Dataset ---------------------------------------------------------------

class OracleDataset(_BASE):
    """Dataset of OCP solutions for neural surrogate training.

    Parameters
    ----------
    data_dir : Path
        Root oracle data directory containing ``solutions/``.
    """

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.samples: List[Dict] = []
        self._scan()

    def _scan(self) -> None:
        """Scan solutions directory for meta JSON files."""
        solutions_dir = self.data_dir / "solutions"
        if not solutions_dir.exists():
            return
        self.samples = []
        for meta_path in sorted(solutions_dir.rglob("*_meta.json")):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                meta["_meta_path"] = str(meta_path)
                self.samples.append(meta)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Cannot read %s: %s", meta_path, exc)

        logger.info("OracleDataset: loaded %d samples", len(self.samples))

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int):
        meta = self.samples[idx]
        vp = meta.get("vehicle_params", {})

        car_feat = _encode_car(vp)
        track_feat = _encode_track(meta)
        setup_feat = _encode_setup(vp)
        weather_feat = _encode_weather(meta.get("weather", {}))

        # Targets
        lap_time = np.float32(meta.get("optimal_lap_time_s", 0.0))
        sector_times = np.array(
            meta.get("sector_times_s", [0.0, 0.0, 0.0])[:3],
            dtype=np.float32,
        )
        if len(sector_times) < 3:
            sector_times = np.pad(
                sector_times, (0, 3 - len(sector_times)),
            ).astype(np.float32)

        # Speed profile: load npz if available, otherwise zeros
        speed_profile = np.zeros(SPEED_PROFILE_N, dtype=np.float32)
        meta_path_str = meta.get("_meta_path", "")
        if meta_path_str:
            npz_path = Path(meta_path_str).parent / Path(
                meta_path_str
            ).name.replace("_meta.json", ".npz")
            if npz_path.exists():
                try:
                    data = np.load(str(npz_path))
                    raw_speed = data.get("speed_mps", np.empty(0))
                    if len(raw_speed) > 0:
                        indices = np.linspace(
                            0, len(raw_speed) - 1, SPEED_PROFILE_N,
                        ).astype(int)
                        speed_profile = raw_speed[indices].astype(np.float32)
                except Exception:
                    pass

        if HAS_TORCH:
            return (
                torch.from_numpy(car_feat),
                torch.from_numpy(track_feat),
                torch.from_numpy(setup_feat),
                torch.from_numpy(weather_feat),
                {
                    "lap_time": torch.tensor([lap_time]),
                    "sectors": torch.from_numpy(sector_times),
                    "speed_profile": torch.from_numpy(speed_profile),
                },
            )
        return (car_feat, track_feat, setup_feat, weather_feat, lap_time)
