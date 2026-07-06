"""Test onboarding/bless_service.py (Task 8): bless_geometry + the extracted
install_gt_geojson core shared with scripts/bless_gt.py.

``conn`` is a lightweight fake (records executed SQL + commit calls) rather
than a real Postgres connection -- bless_geometry never opens its own
connection, so no DB is needed to exercise every gate. ``GT_RUNTIME_DIR`` is
monkeypatched to a tmp dir for every test so nothing here ever touches the
real corpus/registry.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from telemetry_tool.onboarding import bless_service  # noqa: E402
from track_surface.gt_validate import validate_gt_geojson  # noqa: E402

_SCHEMA = "trackreco_ground_truth_v1"
_LAT0, _LON0 = 47.388, 0.789
_MX = 111_320 * np.cos(np.radians(_LAT0))
_MY = 110_540


def _ring(r: float, n: int = 60) -> list[list[float]]:
    th = np.linspace(0, 2 * np.pi, n, endpoint=False)
    pts = [[_LON0 + r * np.cos(t) / _MX, _LAT0 + r * np.sin(t) / _MY] for t in th]
    pts.append(pts[0])
    return pts


def _oval_geojson(
    *, reviewed_by: str | None = "theo", left_r: float = 60.0, right_r: float = 52.0,
    n: int = 60, extra_props: dict | None = None,
) -> dict:
    """A clean concentric-ring annulus -- passes validate_gt_geojson AND
    (unlike a synthetic degenerate fixture) is a real enough closed loop
    for the medial-axis/cross-section midline builder to succeed on, so it
    also passes run_geometry_gates. Mirrors the ``_gt()`` helper in
    ``tests/test_track_surface/test_gt_validate.py``.
    """
    props: dict = {"schema": _SCHEMA, "track_name": "t"}
    if reviewed_by is not None:
        props["reviewed_by"] = reviewed_by
    if extra_props:
        props.update(extra_props)
    return {
        "type": "FeatureCollection",
        "properties": props,
        "features": [
            {"type": "Feature", "properties": {"role": "left_boundary_gt"},
             "geometry": {"type": "LineString", "coordinates": _ring(left_r, n)}},
            {"type": "Feature", "properties": {"role": "right_boundary_gt"},
             "geometry": {"type": "LineString", "coordinates": _ring(right_r, n)}},
        ],
    }


def _crossing_geojson(*, reviewed_by: str | None = "theo") -> dict:
    """Left/right boundaries deliberately crossing (validate_gt_geojson
    rejects this with an 'intersect' message) -- same construction as
    test_gt_validate.py's test_crossing_boundaries_fail.
    """
    left = _ring(60.0)
    right = _ring(52.0)
    n = len(left) - 1
    swap_start, swap_end = n // 4, n // 2
    for i in range(swap_start, swap_end):
        left[i], right[i] = right[i], left[i]
    props: dict = {"schema": _SCHEMA, "track_name": "t"}
    if reviewed_by is not None:
        props["reviewed_by"] = reviewed_by
    return {
        "type": "FeatureCollection",
        "properties": props,
        "features": [
            {"type": "Feature", "properties": {"role": "left_boundary_gt"},
             "geometry": {"type": "LineString", "coordinates": left}},
            {"type": "Feature", "properties": {"role": "right_boundary_gt"},
             "geometry": {"type": "LineString", "coordinates": right}},
        ],
    }


class _FakeCursor:
    def __init__(self, recorder: list) -> None:
        self._recorder = recorder

    def execute(self, sql, params=None) -> None:
        self._recorder.append((sql, params))

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple]] = []
        self.committed = 0

    def cursor(self):
        return _FakeCursor(self.executed)

    def commit(self) -> None:
        self.committed += 1


@pytest.fixture
def conn() -> _FakeConn:
    return _FakeConn()


@pytest.fixture(autouse=True)
def _gt_runtime_dir(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "gt_runtime"
    monkeypatch.setenv("GT_RUNTIME_DIR", str(runtime_dir))
    return runtime_dir


@pytest.fixture(autouse=True)
def _mock_invalidate(monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        bless_service, "invalidate_gt_cache",
        lambda canonical_id=None: calls.append(canonical_id),
    )
    return calls


def _write(tmp_path: Path, name: str, data: dict | str) -> Path:
    p = tmp_path / name
    if isinstance(data, dict):
        p.write_text(json.dumps(data), encoding="utf-8")
    else:
        p.write_text(data, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestValidBless:
    def test_ok_installs_registers_invalidates_and_audits(
        self, tmp_path, conn, _gt_runtime_dir, _mock_invalidate,
    ):
        draft = _oval_geojson(reviewed_by="auto_draft:gps_only", left_r=60.0, right_r=52.0)
        corrected = _oval_geojson(
            reviewed_by="attacker",  # client-supplied -- must be overwritten server-side
            left_r=61.0, right_r=53.0,  # operator actually moved the boundaries
        )
        src = _write(tmp_path, "submitted.geojson", corrected)

        result = bless_service.bless_geometry(
            geojson_path=src, canonical_id="zz", reviewed_by="theo_the_operator",
            auto_draft_geojson=draft, conn=conn,
        )

        assert result.ok is True
        assert result.failures == []

        dest = _gt_runtime_dir / "gt_zz.geojson"
        assert dest.exists()
        installed = json.loads(dest.read_text(encoding="utf-8"))
        assert installed["properties"]["reviewed_by"] == "theo_the_operator"
        assert "attacker" not in dest.read_text(encoding="utf-8")

        registry = json.loads((_gt_runtime_dir / "track_aliases.json").read_text(encoding="utf-8"))
        assert registry["tracks"]["zz"]["canonical_id"] == "zz"

        assert _mock_invalidate == ["zz"]

        gates = [row[1][3] for row in conn.executed]  # gate column
        assert "bless_accept" in gates
        assert conn.committed >= 1


# ---------------------------------------------------------------------------
# Unreviewed draft
# ---------------------------------------------------------------------------


class TestUnreviewedDraft:
    def test_identical_geometry_to_draft_is_rejected(self, tmp_path, conn, _gt_runtime_dir):
        draft = _oval_geojson(reviewed_by="auto_draft:gps_only")
        submitted = _oval_geojson(reviewed_by="auto_draft:gps_only")  # byte-identical geometry
        src = _write(tmp_path, "submitted.geojson", submitted)

        result = bless_service.bless_geometry(
            geojson_path=src, canonical_id="zz", reviewed_by="theo",
            auto_draft_geojson=draft, conn=conn,
        )

        assert result.ok is False
        assert result.failures == ["unreviewed_draft"]
        assert not (_gt_runtime_dir / "gt_zz.geojson").exists()
        assert not _gt_runtime_dir.exists() or not any(_gt_runtime_dir.iterdir())

    def test_only_reviewed_by_differs_still_rejected(self, tmp_path, conn, _gt_runtime_dir):
        """Metadata-only edits (e.g. just a different reviewed_by) must NOT
        count as "the operator reviewed this" -- only a geometry change does.
        """
        draft = _oval_geojson(reviewed_by="auto_draft:gps_only", left_r=60.0, right_r=52.0)
        # Same rings as draft; only properties differ.
        submitted = _oval_geojson(reviewed_by="someone", left_r=60.0, right_r=52.0)
        src = _write(tmp_path, "submitted.geojson", submitted)

        result = bless_service.bless_geometry(
            geojson_path=src, canonical_id="zz", reviewed_by="theo",
            auto_draft_geojson=draft, conn=conn,
        )

        assert result.ok is False
        assert result.failures == ["unreviewed_draft"]
        assert not (_gt_runtime_dir / "gt_zz.geojson").exists()

    def test_boundary_features_reordered_still_rejected_as_unreviewed(
        self, tmp_path, conn, _gt_runtime_dir,
    ):
        """CRITICAL 1 regression: ``json.dumps(list, sort_keys=True)`` does
        NOT sort list element order, so a naive list-based signature let
        byte-identical geometry evade the unreviewed_draft gate by simply
        submitting the two boundary features in swapped order. The
        signature must be invariant to feature order (keyed by role).
        """
        draft = _oval_geojson(reviewed_by="auto_draft:gps_only")
        submitted = _oval_geojson(reviewed_by="auto_draft:gps_only")
        submitted["features"] = list(reversed(submitted["features"]))  # only reordered
        src = _write(tmp_path, "submitted.geojson", submitted)

        result = bless_service.bless_geometry(
            geojson_path=src, canonical_id="zz", reviewed_by="theo",
            auto_draft_geojson=draft, conn=conn,
        )

        assert result.ok is False
        assert result.failures == ["unreviewed_draft"]
        assert not (_gt_runtime_dir / "gt_zz.geojson").exists()

    def test_reordered_but_genuinely_changed_geometry_still_accepted(
        self, tmp_path, conn, _gt_runtime_dir,
    ):
        """The order-invariance fix must not become a false-positive trap:
        reordered features whose coordinates actually differ from the draft
        are still a real edit and must pass the unreviewed_draft gate.
        """
        draft = _oval_geojson(reviewed_by="auto_draft:gps_only", left_r=60.0, right_r=52.0)
        submitted = _oval_geojson(reviewed_by="operator", left_r=61.0, right_r=53.0)
        submitted["features"] = list(reversed(submitted["features"]))
        src = _write(tmp_path, "submitted.geojson", submitted)

        result = bless_service.bless_geometry(
            geojson_path=src, canonical_id="zz", reviewed_by="theo",
            auto_draft_geojson=draft, conn=conn,
        )

        assert result.ok is True
        assert (_gt_runtime_dir / "gt_zz.geojson").exists()


# ---------------------------------------------------------------------------
# Invalid reviewer
# ---------------------------------------------------------------------------


class TestInvalidReviewer:
    @pytest.mark.parametrize(
        "bad_reviewer",
        ["", "   ", "auto_draft:gps_only", "Auto_Draft:gps_only", "  AUTO_DRAFT:x  "],
    )
    def test_rejected_no_install(self, tmp_path, conn, _gt_runtime_dir, bad_reviewer):
        submitted = _oval_geojson(reviewed_by="theo")
        src = _write(tmp_path, "submitted.geojson", submitted)

        result = bless_service.bless_geometry(
            geojson_path=src, canonical_id="zz", reviewed_by=bad_reviewer,
            auto_draft_geojson=None, conn=conn,
        )

        assert result.ok is False
        assert result.failures == ["invalid_reviewer"]
        assert not (_gt_runtime_dir / "gt_zz.geojson").exists()


# ---------------------------------------------------------------------------
# Degenerate geometry -- validate_gt_geojson rejects
# ---------------------------------------------------------------------------


class TestDegenerateGeometry:
    def test_crossing_boundaries_rejected_with_validator_messages(
        self, tmp_path, conn, _gt_runtime_dir,
    ):
        submitted = _crossing_geojson(reviewed_by="theo")
        src = _write(tmp_path, "submitted.geojson", submitted)

        result = bless_service.bless_geometry(
            geojson_path=src, canonical_id="zz", reviewed_by="theo",
            auto_draft_geojson=None, conn=conn,
        )

        assert result.ok is False
        assert any("intersect" in m.lower() for m in result.failures)
        assert not (_gt_runtime_dir / "gt_zz.geojson").exists()
        gates = [row[1][3] for row in conn.executed]
        assert "bless_reject:validate_gt_geojson" in gates

    def test_too_few_points_rejected(self, tmp_path, conn, _gt_runtime_dir):
        submitted = _oval_geojson(reviewed_by="theo", n=5)  # < MIN_BOUNDARY_POINTS (20)
        src = _write(tmp_path, "submitted.geojson", submitted)

        result = bless_service.bless_geometry(
            geojson_path=src, canonical_id="zz", reviewed_by="theo",
            auto_draft_geojson=None, conn=conn,
        )

        assert result.ok is False
        assert any("points" in m for m in result.failures)
        assert not (_gt_runtime_dir / "gt_zz.geojson").exists()


# ---------------------------------------------------------------------------
# Geometry gates REJECT branch -- passes validate_gt_geojson, fails
# run_geometry_gates (IMPORTANT 3: this branch was previously untested).
# ---------------------------------------------------------------------------


class TestGeometryGatesReject:
    def test_width_below_minimum_rejected_by_geometry_gates_not_validator(
        self, tmp_path, conn, _gt_runtime_dir,
    ):
        """A closed annulus, valid schema, >=20 pts/boundary, non-crossing,
        valid reviewed_by -- validate_gt_geojson has no opinion on track
        width, so this passes it. But the boundaries are only ~0.2-0.45 m
        apart, under geometry_gates.WIDTH_MIN_M (0.5 m), so run_geometry_
        gates must reject it -- proving that gate is actually reachable and
        wired into bless_geometry's reject path, not just validate_gt_geojson
        catching every degenerate fixture first.
        """
        submitted = _oval_geojson(reviewed_by="theo", left_r=52.6, right_r=52.0)
        src = _write(tmp_path, "submitted.geojson", submitted)

        assert validate_gt_geojson(src) == []  # confirms validator alone lets this through

        result = bless_service.bless_geometry(
            geojson_path=src, canonical_id="zz", reviewed_by="theo",
            auto_draft_geojson=None, conn=conn,
        )

        assert result.ok is False
        assert any("width" in m.lower() for m in result.failures)
        gates = [row[1][3] for row in conn.executed]
        assert "bless_reject:geometry_gates" in gates
        assert not (_gt_runtime_dir / "gt_zz.geojson").exists()
        assert not _gt_runtime_dir.exists() or not any(_gt_runtime_dir.iterdir())


# ---------------------------------------------------------------------------
# Malformed / empty input -- fail-closed, never crashes
# ---------------------------------------------------------------------------


class TestMalformedInput:
    def test_empty_file_rejected_not_crashed(self, tmp_path, conn, _gt_runtime_dir):
        src = _write(tmp_path, "empty.geojson", "")

        result = bless_service.bless_geometry(
            geojson_path=src, canonical_id="zz", reviewed_by="theo",
            auto_draft_geojson=None, conn=conn,
        )

        assert result.ok is False
        assert not (_gt_runtime_dir / "gt_zz.geojson").exists()

    def test_not_json_rejected_not_crashed(self, tmp_path, conn, _gt_runtime_dir):
        src = _write(tmp_path, "bad.geojson", "not { valid json at all")

        result = bless_service.bless_geometry(
            geojson_path=src, canonical_id="zz", reviewed_by="theo",
            auto_draft_geojson=None, conn=conn,
        )

        assert result.ok is False
        assert not (_gt_runtime_dir / "gt_zz.geojson").exists()

    def test_missing_file_rejected_not_crashed(self, tmp_path, conn, _gt_runtime_dir):
        result = bless_service.bless_geometry(
            geojson_path=tmp_path / "does_not_exist.geojson", canonical_id="zz",
            reviewed_by="theo", auto_draft_geojson=None, conn=conn,
        )

        assert result.ok is False
        assert not (_gt_runtime_dir / "gt_zz.geojson").exists()

    def test_json_but_not_an_object_rejected(self, tmp_path, conn, _gt_runtime_dir):
        src = _write(tmp_path, "list.geojson", "[1, 2, 3]")

        result = bless_service.bless_geometry(
            geojson_path=src, canonical_id="zz", reviewed_by="theo",
            auto_draft_geojson=None, conn=conn,
        )

        assert result.ok is False


# ---------------------------------------------------------------------------
# canonical_id format allow-list (IMPORTANT 2: defense-in-depth before the
# install path/alias-registry key are built).
# ---------------------------------------------------------------------------


class TestCanonicalIdFormat:
    @pytest.mark.parametrize(
        "bad_id", ["../etc", "zz/../../x", "UPPER", "has space", "", "-leading-dash"],
    )
    def test_malformed_canonical_id_rejected_installs_nothing(
        self, tmp_path, conn, _gt_runtime_dir, bad_id,
    ):
        submitted = _oval_geojson(reviewed_by="theo")
        src = _write(tmp_path, "submitted.geojson", submitted)

        result = bless_service.bless_geometry(
            geojson_path=src, canonical_id=bad_id, reviewed_by="theo",
            auto_draft_geojson=None, conn=conn,
        )

        assert result.ok is False
        assert not _gt_runtime_dir.exists() or not any(_gt_runtime_dir.rglob("*"))


# ---------------------------------------------------------------------------
# GT_RUNTIME_DIR unset -- fail-closed (never falls back to the baked corpus)
# ---------------------------------------------------------------------------


class TestRuntimeDirUnset:
    def test_unset_env_var_rejects(self, tmp_path, conn, monkeypatch):
        monkeypatch.delenv("GT_RUNTIME_DIR", raising=False)
        submitted = _oval_geojson(reviewed_by="theo")
        src = _write(tmp_path, "submitted.geojson", submitted)

        result = bless_service.bless_geometry(
            geojson_path=src, canonical_id="zz", reviewed_by="theo",
            auto_draft_geojson=None, conn=conn,
        )

        assert result.ok is False
        assert result.failures == [
            "GT_RUNTIME_DIR is not set -- refusing to install (fail-closed)"
        ]


# ---------------------------------------------------------------------------
# Duplicate canonical_id -- force is always False on the web path
# ---------------------------------------------------------------------------


class TestForceNeverReachable:
    def test_duplicate_canonical_id_is_refused_not_overwritten(
        self, tmp_path, conn, _gt_runtime_dir,
    ):
        first = _oval_geojson(reviewed_by="theo", left_r=60.0, right_r=52.0)
        src1 = _write(tmp_path, "first.geojson", first)
        r1 = bless_service.bless_geometry(
            geojson_path=src1, canonical_id="zz", reviewed_by="theo",
            auto_draft_geojson=None, conn=conn,
        )
        assert r1.ok is True

        second = _oval_geojson(reviewed_by="theo", left_r=61.0, right_r=53.0)
        src2 = _write(tmp_path, "second.geojson", second)
        r2 = bless_service.bless_geometry(
            geojson_path=src2, canonical_id="zz", reviewed_by="theo",
            auto_draft_geojson=None, conn=conn,
        )
        assert r2.ok is False
        # Original file untouched -- the second attempt never overwrote it.
        installed = json.loads((_gt_runtime_dir / "gt_zz.geojson").read_text(encoding="utf-8"))
        left_coords = next(
            f["geometry"]["coordinates"] for f in installed["features"]
            if f["properties"]["role"] == "left_boundary_gt"
        )
        assert left_coords == first["features"][0]["geometry"]["coordinates"]


# ---------------------------------------------------------------------------
# scripts/bless_gt.py CLI still works through the extracted core
# ---------------------------------------------------------------------------


_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def test_cli_bless_gt_still_works_via_extracted_core(tmp_path):
    from scripts.bless_gt import BlessError, bless_gt

    src = _write(tmp_path, "src.geojson", _oval_geojson(reviewed_by="theo"))
    gt_dir = tmp_path / "gt_out"
    aliases_file = tmp_path / "track_aliases.json"

    dest = bless_gt(src, "zz", gt_dir=gt_dir, aliases_file=aliases_file)
    assert dest == gt_dir / "gt_zz.geojson"
    assert dest.exists()

    registry = json.loads(aliases_file.read_text(encoding="utf-8"))
    assert registry["tracks"]["zz"]["canonical_id"] == "zz"

    # Absolute refusal (missing reviewed_by) still holds even with force.
    unreviewed_src = _write(tmp_path, "unreviewed.geojson", _oval_geojson(reviewed_by=None))
    with pytest.raises(BlessError, match="reviewed_by"):
        bless_gt(unreviewed_src, "yy", force=True, gt_dir=gt_dir, aliases_file=aliases_file)
