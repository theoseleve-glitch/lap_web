from __future__ import annotations

import numpy as np
import pandas as pd

from kart_envelope.config import default_config
from kart_envelope.ingest.metadata import SessionMetadata
from kart_envelope.solver.load_transfer_fe import resolve_load_transfer_scale_profile


def test_load_transfer_exact_asset(oval_geometry, tmp_path):
    cfg = default_config()
    path = tmp_path / "load_transfer_fe.csv"
    ax_g = np.linspace(-0.8, 0.4, 30)
    ay_g = np.linspace(0.0, 1.4, 30)
    df = pd.DataFrame({
        "ax_g": np.repeat(ax_g, len(ay_g)),
        "ay_g": np.tile(ay_g, len(ax_g)),
        "lateral_scale": 1.0 - 0.05 * np.tile(ay_g, len(ax_g)),
        "drive_scale": 0.98 - 0.03 * np.tile(ay_g, len(ax_g)),
        "brake_scale": 0.99 - 0.02 * np.tile(ay_g, len(ax_g)),
    })
    df.to_csv(path, index=False)

    dist = np.asarray(oval_geometry.distance_m, dtype=float)
    lap_df = pd.DataFrame({
        "distance_m": dist,
        "accel_long_mps2": -2.0 + 4.0 * np.sin(dist / max(dist[-1], 1.0) * np.pi),
        "accel_lat_mps2": 6.0 * np.abs(np.sin(2.0 * np.pi * dist / max(dist[-1], 1.0))),
    })
    meta = SessionMetadata(
        session_file="s.csv",
        track_name="TEST",
        load_transfer_fe_map_path=str(path),
    )
    lat, drv, brk, m = resolve_load_transfer_scale_profile(
        geometry=oval_geometry,
        metadata=meta,
        config=cfg,
        fallback_df=lap_df,
        tracks_dir=tmp_path,
    )
    assert m.source == "exact_asset"
    assert len(lat) == len(dist)
    assert np.isfinite(lat).all()
    assert np.isfinite(drv).all()
    assert np.isfinite(brk).all()


def test_load_transfer_fallback_surrogate(oval_geometry):
    cfg = default_config()
    dist = np.asarray(oval_geometry.distance_m, dtype=float)
    lap_df = pd.DataFrame({
        "distance_m": dist,
        "accel_long_mps2": -1.5 + 3.0 * np.sin(dist / max(dist[-1], 1.0) * np.pi),
        "accel_lat_mps2": 7.0 * np.abs(np.sin(2.0 * np.pi * dist / max(dist[-1], 1.0))),
    })
    meta = SessionMetadata(session_file="s.csv", track_name="TEST")
    lat, drv, brk, m = resolve_load_transfer_scale_profile(
        geometry=oval_geometry,
        metadata=meta,
        config=cfg,
        fallback_df=lap_df,
        tracks_dir=None,
    )
    assert m.source == "fallback_telemetry"
    assert m.method.startswith("surrogate")
    assert float(np.nanmean(lat)) > 0.8

