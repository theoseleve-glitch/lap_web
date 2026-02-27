"""Tests for Cycle-A tire runtime stack."""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from kart_envelope.config import default_config
from kart_envelope.envelope.tire_stack import (
    apply_tire_runtime_to_envelope,
    build_tire_runtime_meta,
)
from kart_envelope.ingest.metadata import SessionMetadata
from kart_envelope.inference.session_scalars import SessionScalars


def _mock_laps() -> dict[int, pd.DataFrame]:
    n = 120
    s = np.linspace(0.0, 300.0, n)
    v = 12.0 + 4.0 * np.sin(np.linspace(0.0, 4.0 * np.pi, n))
    ax = np.gradient(v, s)
    ay = 3.0 * np.sin(np.linspace(0.0, 8.0 * np.pi, n))
    return {
        1: pd.DataFrame({
            "distance_m": s,
            "speed_mps": v,
            "accel_long_mps2": ax,
            "accel_lat_mps2": ay,
        })
    }


def test_tire_runtime_disabled_defaults(known_envelope):
    cfg = default_config()
    meta = SessionMetadata(session_file="s.csv", condition_label="dry", tire_type="slick")
    scalars = SessionScalars()
    tire = build_tire_runtime_meta(_mock_laps(), meta, scalars, cfg)
    assert tire.enabled is False
    env2 = apply_tire_runtime_to_envelope(known_envelope, tire)
    assert np.allclose(env2.ay_max, known_envelope.ay_max)


def test_tire_runtime_enabled_scales_envelope(known_envelope):
    cfg = replace(
        default_config(),
        tire_enable_pacejka=True,
        tire_enable_thermal=True,
        tire_enable_pressure=True,
    )
    meta = SessionMetadata(session_file="s.csv", condition_label="damp", tire_type="slick")
    scalars = SessionScalars(condition_label="damp")
    tire = build_tire_runtime_meta(_mock_laps(), meta, scalars, cfg)
    assert tire.enabled is True
    assert 0.5 <= tire.lateral_scale <= 1.1
    env2 = apply_tire_runtime_to_envelope(known_envelope, tire)
    assert np.all(np.isfinite(env2.ay_max))
    assert np.all(env2.ay_max > 0.0)
