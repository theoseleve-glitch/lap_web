"""Geometry rejection withholds ONLY the geometry sidecar; grip still persists;
the pipeline is never crashed by a gate failure (spec A3)."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from track_surface import store
from track_surface.geometry_gates import GateReport


def _degenerate_surface():
    xy = np.tile([[10.0, 5.0]], (362, 1))
    frenet = SimpleNamespace(centerline_xy=xy, s_grid=np.zeros(362),
                             total_length_m=0.0)
    # Adaptation (see task-2-report.md): merge_track_model's bootstrap path
    # unconditionally logs new_surface.n_laps (store.py ~:293-294, runs
    # regardless of gate outcome). A bare SimpleNamespace without n_laps
    # raises AttributeError before the gate logic under test ever executes.
    # n_laps is a real TrackSurface field (default 0, see model.py); adding
    # it here touches no gate-relevant attribute (frenet/widths/elevation
    # are unchanged), so the contract under test is unaffected.
    return SimpleNamespace(frenet=frenet, width_left=None, width_right=None,
                           elevation_m=None, grip_2d=None, n_laps=1)


def test_rejected_geometry_not_saved_but_callback_fires(tmp_path, monkeypatch):
    # Adaptation (see task-2-report.md): store._default_sidecar_root() honors
    # the SIDECAR_ROOT env var, not LAP_SIDECAR_ROOT — monkeypatching the env
    # var here would silently no-op and fall through to the real dev sidecar
    # dir. Per the brief's own fallback instruction, monkeypatch the resolver
    # directly instead.
    monkeypatch.setattr(store, "_default_sidecar_root", lambda: tmp_path)
    saved = {"parquet": 0}
    monkeypatch.setattr(store, "_save_surface_parquet",
                        lambda path, s: saved.__setitem__("parquet", saved["parquet"] + 1))
    reports: list[GateReport] = []
    result = store.merge_track_model(
        "t-degenerate", _degenerate_surface(), vehicle_class="generic",
        condition="dry", on_geometry_rejected=reports.append,
    )
    assert saved["parquet"] == 0          # geometry withheld
    assert len(reports) == 1 and not reports[0].passed
    assert result is not None             # pipeline continues


def test_healthy_geometry_still_saves(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_default_sidecar_root", lambda: tmp_path)
    th = np.linspace(0.0, 2.0 * np.pi, 400, endpoint=False)
    xy = np.column_stack([100 * np.cos(th), 100 * np.sin(th)])
    xy = np.vstack([xy, xy[0] + 0.01])
    seg = np.linalg.norm(np.diff(xy, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    frenet = SimpleNamespace(centerline_xy=xy, s_grid=s, total_length_m=float(s[-1]))
    surface = SimpleNamespace(frenet=frenet, width_left=np.full(401, 4.0),
                              width_right=np.full(401, 4.0),
                              elevation_m=np.zeros(401), grip_2d=None, n_laps=1)
    calls = {"parquet": 0}
    monkeypatch.setattr(store, "_save_surface_parquet",
                        lambda path, s2: calls.__setitem__("parquet", calls["parquet"] + 1))
    reports: list[GateReport] = []
    store.merge_track_model("t-healthy", surface, vehicle_class="generic",
                            condition="dry", on_geometry_rejected=reports.append)
    assert calls["parquet"] >= 1
    assert reports == []
