from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from kart_envelope.config import default_config
from kart_envelope.ingest.metadata import SessionMetadata
from kart_envelope.track.lidar_profile import resolve_track_surface_profile


def test_lidar_profile_exact_asset(oval_geometry, tmp_path):
    cfg = default_config()
    path = tmp_path / "lidar_profile.csv"
    dist = np.asarray(oval_geometry.distance_m, dtype=float)
    pd.DataFrame({
        "s": dist,
        "elevation": 0.02 * dist,
        "bank": 2.0 * np.sin(dist / max(dist[-1], 1.0) * np.pi),
    }).to_csv(path, index=False)
    meta = SessionMetadata(
        session_file="s.csv",
        track_name="TEST",
        track_lidar_profile_path=str(path),
    )

    elev, bank, m = resolve_track_surface_profile(
        geometry=oval_geometry,
        metadata=meta,
        config=cfg,
        fallback_df=None,
        tracks_dir=tmp_path,
    )
    assert len(elev) == len(dist)
    assert len(bank) == len(dist)
    assert m.source == "exact_asset"
    assert m.n_points == len(dist)
    assert np.isfinite(elev).all()


def test_lidar_profile_fallback_telemetry(oval_geometry):
    cfg = replace(default_config(), track_enable_lidar_profile=True, track_lidar_fallback_to_telemetry=True)
    dist = np.asarray(oval_geometry.distance_m, dtype=float)
    lap_df = pd.DataFrame({
        "distance_m": dist,
        "altitude_m": 10.0 + 0.01 * dist,
        "bank_angle_deg": np.sin(dist / max(dist[-1], 1.0) * 2.0 * np.pi),
    })
    meta = SessionMetadata(session_file="s.csv", track_name="TEST")
    elev, bank, m = resolve_track_surface_profile(
        geometry=oval_geometry,
        metadata=meta,
        config=cfg,
        fallback_df=lap_df,
        tracks_dir=None,
    )
    assert m.source == "fallback_telemetry"
    assert float(np.nanstd(elev)) > 0.0
    assert float(np.nanstd(bank)) > 0.0

