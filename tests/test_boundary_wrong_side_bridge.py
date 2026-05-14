"""Day-10.5 Phase B — wrong-side projection bridge regression (F1).

OK_R1's centerline runs slightly off-track at a tight apex (s≈228m); the
gt RIGHT polyline's projected signed_n flips sign through zero across
~25m of the s-grid. ``np.interp`` linearly bridges the crossings, leaving
signed_n collapsed near zero, and the assembled polygon self-intersects
when the boundary curve folds back at high curvature.

These tests:

  T1. Synthetic — small polyline projection with a sign-flip island in the
      middle. After ``_gt_boundary_signed_offsets``, no bin in the flip
      region should retain the wrong sign or near-zero magnitude.

  T2. OK_R1 real mesh — regenerate and verify
        polygon.is_valid AND polygon.is_simple
      i.e., G1 passes. Pre-fix this assertion failed at (52.29, -22.84).

  T3. OK_R4 regression — same regen + G1 check. Should still pass; the
      fix must not introduce new artifacts on previously-clean sessions.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import Polygon

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TELEMETRY_PKG = _REPO_ROOT / "telemetry_tool"
for _p in (_REPO_ROOT, _TELEMETRY_PKG):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _resolve_csv(session: str) -> Path | None:
    """Multi-candidate CSV resolver (mirrors test_boundary_geometric_correctness)."""
    env = os.environ.get("LAP_DATA_RAW")
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env) / session)
    candidates.append(_REPO_ROOT / "data" / "raw" / session)
    candidates.append(_REPO_ROOT.parent / "Analysis" / "V2_claude_ai" / "data" / "raw" / session)
    for c in candidates:
        if c.exists():
            return c
    return None


def _regenerate_mesh(session: str, track: str, out_name: str) -> Path:
    """Run scripts/generate_mesh.py for one session; return output path."""
    csv = _resolve_csv(session)
    if csv is None:
        pytest.skip(f"{session} not findable; set $LAP_DATA_RAW")
    out = Path(tempfile.gettempdir()) / out_name
    if out.exists():
        out.unlink()  # Force regen to exercise the actual algorithm post-fix
    cmd = [
        sys.executable, str(_REPO_ROOT / "scripts" / "generate_mesh.py"),
        "--session", str(csv), "--track", track,
        "--output", str(out), "--log-level", "ERROR",
    ]
    res = subprocess.run(cmd, cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, (
        f"generate_mesh.py failed for {session}: {res.stderr[-500:]}"
    )
    assert out.exists()
    return out


def _polygon_from_mesh(mesh_path: Path) -> Polygon:
    m = json.load(open(mesh_path))
    lx, ly = m["left_boundary"]["x_m"], m["left_boundary"]["y_m"]
    rx, ry = m["right_boundary"]["x_m"], m["right_boundary"]["y_m"]
    return Polygon(list(zip(lx, ly)) + list(zip(rx[::-1], ry[::-1])))


# ── T1 — synthetic ────────────────────────────────────────────────────


def test_t1_synthetic_sign_flip_island_gets_bridged():
    """Build a synthetic frenet frame + a polyline whose projected signed_n
    crosses zero in the middle. After ``_gt_boundary_signed_offsets`` the
    output should be consistent with the polyline's dominant side and
    have no bins whose dominant-side magnitude drops below the floor.

    Sign-convention-agnostic: a CCW unit circle's "left normal" points
    INWARD, so a polyline at radius > centerline produces NEGATIVE
    signed_n. We assert that the dominant side is preserved and that no
    bin contradicts it — not that the dominant side is positive."""
    from track_surface.frenet import FrenetFrame
    from track_surface.boundary import _gt_boundary_signed_offsets, _GT_DOMINANT_SIDE_FLOOR_M

    # Circle centerline radius 50 m, n=400 pts.
    n = 400
    theta = np.linspace(0, 2 * np.pi, n, endpoint=False)
    cl_xy = np.column_stack([50.0 * np.cos(theta), 50.0 * np.sin(theta)])
    frenet = FrenetFrame.from_centerline(cl_xy)

    # gt polyline mostly +3 m off centerline (radius 53), with a 20-degree
    # slice at θ ≈ 0 where it crosses to the OPPOSITE side (radius 47).
    pl_theta = np.linspace(0, 2 * np.pi, 200, endpoint=False)
    pl_r = np.full(200, 53.0)
    flip_mask = (pl_theta < np.deg2rad(10)) | (pl_theta > 2 * np.pi - np.deg2rad(10))
    pl_r[flip_mask] = 47.0
    gt_xy = np.column_stack([pl_r * np.cos(pl_theta), pl_r * np.sin(pl_theta)])

    signed = _gt_boundary_signed_offsets(frenet, gt_xy, side="left")
    # Identify dominant side from the bridged output: bins with magnitude
    # > 1 m should all carry the same sign (the bulk corridor side).
    bulk = signed[np.abs(signed) > 1.0]
    assert bulk.size > 0, "no bulk-magnitude bins in bridged output"
    dom_sign = np.sign(np.median(bulk))
    # No bin should violate the dominant-side floor after bridging.
    dom_side_offset = signed * dom_sign
    violations = (dom_side_offset < _GT_DOMINANT_SIDE_FLOOR_M)
    assert not violations.any(), (
        f"{int(violations.sum())} bins violate the dominant-side floor "
        f"({_GT_DOMINANT_SIDE_FLOOR_M:.2f} m) post-bridge. "
        f"dom_sign={dom_sign:+.0f}; min dom-side = "
        f"{float(dom_side_offset.min()):.3f} m."
    )


# ── T2 — OK_R1 real mesh polygon validity ──────────────────────────────


def test_t2_ok_r1_polygon_simple_and_valid_post_fix():
    """The F1 customer bug: pre-fix OK_R1's assembled polygon was not
    simple (self-intersection at (52.29, -22.84) near bin 456, s≈228m).
    Post-fix the polygon must be valid + simple."""
    mesh_path = _regenerate_mesh("OK_R1.csv", "ok", "mesh_ok_r1_f1_test.json")
    poly = _polygon_from_mesh(mesh_path)
    assert poly.is_valid, (
        "OK_R1 polygon invalid post-F1 fix"
    )
    assert poly.is_simple, (
        "OK_R1 polygon self-intersects post-F1 fix — wrong-side bridge "
        "did not fully cover the s=228m apex"
    )


# ── T3 — OK_R4 + KCT_R1 regression check ───────────────────────────────


def test_t3_ok_r4_still_simple():
    """OK_R4 was clean pre-fix; must stay clean post-fix."""
    mesh_path = _regenerate_mesh("OK_R4.csv", "ok", "mesh_ok_r4_f1_test.json")
    poly = _polygon_from_mesh(mesh_path)
    assert poly.is_valid and poly.is_simple


def test_t3b_kct_r1_still_simple():
    """KCT_R1 was clean pre-fix; must stay clean post-fix (different track,
    no side_swap, hairpin geometry)."""
    mesh_path = _regenerate_mesh("KCT_R1.csv", "kct", "mesh_kct_r1_f1_test.json")
    poly = _polygon_from_mesh(mesh_path)
    assert poly.is_valid and poly.is_simple
