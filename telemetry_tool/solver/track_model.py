"""Track mesh for OCP collocation.

Converts curvature profile to a discretized mesh with adaptive refinement.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np


@dataclass
class TrackMesh:
    s: np.ndarray       # distance at each node (m), shape (N,)
    kappa: np.ndarray   # curvature at each node (1/m), shape (N,)
    ds: np.ndarray      # interval lengths (m), shape (N-1,)
    track_length: float


def build_mesh(distances: np.ndarray, curvatures: np.ndarray, n_nodes: int = 500) -> TrackMesh:
    track_length = float(distances[-1] - distances[0])
    s = np.linspace(float(distances[0]), float(distances[-1]), n_nodes)
    kappa = np.interp(s, distances, curvatures)
    ds = np.diff(s)
    return TrackMesh(s=s, kappa=kappa, ds=ds, track_length=track_length)


def refine_mesh(mesh: TrackMesh, speed_profile: np.ndarray, gradient_threshold: float = 0.5) -> TrackMesh:
    dv_ds = np.abs(np.diff(speed_profile) / mesh.ds)
    new_points = [mesh.s[0]]
    for i in range(len(mesh.ds)):
        if dv_ds[i] > gradient_threshold:
            mid = (mesh.s[i] + mesh.s[i + 1]) / 2.0
            new_points.append(mid)
        new_points.append(mesh.s[i + 1])
    s_refined = np.array(sorted(set(new_points)))
    kappa_refined = np.interp(s_refined, mesh.s, mesh.kappa)
    ds_refined = np.diff(s_refined)
    return TrackMesh(s=s_refined, kappa=kappa_refined, ds=ds_refined, track_length=mesh.track_length)


def build_mesh_from_curvature_profile(curvature_profile_df, n_nodes: int = 500) -> TrackMesh | None:
    import logging
    _log = logging.getLogger(__name__)
    if curvature_profile_df is None:
        _log.warning("build_mesh: input is None")
        return None
    cols = list(curvature_profile_df.columns)
    _log.info("build_mesh: cols=%s, rows=%d, n_nodes=%d", cols, len(curvature_profile_df), n_nodes)
    if "distance_m" not in curvature_profile_df.columns:
        _log.warning("build_mesh: missing distance_m column")
        return None
    if "curvature_1pm" not in curvature_profile_df.columns:
        _log.warning("build_mesh: missing curvature_1pm column")
        return None
    distances = curvature_profile_df["distance_m"].to_numpy(dtype=float)
    curvatures = curvature_profile_df["curvature_1pm"].to_numpy(dtype=float)
    valid = np.isfinite(distances) & np.isfinite(curvatures)
    n_valid = int(valid.sum())
    n_dist_nan = int((~np.isfinite(distances)).sum()) if len(distances) > 0 else 0
    n_curv_nan = int((~np.isfinite(curvatures)).sum()) if len(curvatures) > 0 else 0
    _log.info("build_mesh: valid=%d/%d (dist_nan=%d, curv_nan=%d)", n_valid, len(distances), n_dist_nan, n_curv_nan)
    if n_valid < 10:
        _log.warning("build_mesh: too few valid points (%d < 10)", n_valid)
        return None
    return build_mesh(distances[valid], curvatures[valid], n_nodes=n_nodes)
