from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from kart_envelope.config import default_config
from kart_envelope.envelope.grip_map import resolve_grip_scale_profile
from kart_envelope.ingest.metadata import SessionMetadata


def test_grip_map_exact_asset_distance(oval_geometry, tmp_path):
    cfg = replace(default_config(), grip_enable_spatial_map=True, grip_map_blend=1.0)
    dist = np.asarray(oval_geometry.distance_m, dtype=float)
    path = tmp_path / "grip_map.csv"
    pd.DataFrame({
        "distance_m": dist,
        "mu_scale": 0.9 + 0.1 * np.sin(2.0 * np.pi * dist / max(dist[-1], 1.0)),
    }).to_csv(path, index=False)
    meta = SessionMetadata(
        session_file="s.csv",
        track_name="TEST",
        track_grip_map_path=str(path),
    )

    prof, m = resolve_grip_scale_profile(
        geometry=oval_geometry,
        metadata=meta,
        config=cfg,
        fallback_df=None,
        tracks_dir=tmp_path,
    )
    assert len(prof) == len(dist)
    assert m.source == "exact_asset"
    assert m.method == "distance_interp"
    assert float(np.nanmean(prof)) < 1.05


def test_grip_map_fallback_condition_prior(oval_geometry):
    cfg = replace(default_config(), grip_enable_spatial_map=True, grip_map_blend=1.0)
    meta = SessionMetadata(session_file="s.csv", track_name="TEST", condition_label="wet")
    prof, m = resolve_grip_scale_profile(
        geometry=oval_geometry,
        metadata=meta,
        config=cfg,
        fallback_df=None,
        tracks_dir=None,
    )
    assert m.source == "fallback_telemetry"
    assert m.method == "condition_prior"
    assert float(np.nanmean(prof)) < 1.0

