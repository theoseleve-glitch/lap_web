"""
corner_persistence.py
---------------------
Ensures that corner IDs remain stable across sessions for a given track.

Without persistence, ``corner_detection.detect_corners`` assigns sequential
IDs (1, 2, 3 …) by position order — so adding a new corner to the reference
set, or detecting a corner slightly earlier in one session, would shift all
subsequent IDs.  This module anchors IDs to a stored reference so that
Corner 3 at Spa always means the same physical section of track.

Algorithm
~~~~~~~~~
1. ``match_corners(new_corners, stored_corners)``
   For every new corner, find the stored corner with the highest IoU
   (arc-distance Intersection-over-Union).  Assign that stored corner's ID
   if IoU ≥ ``min_iou``.  Unmatched new corners receive new IDs beyond the
   current maximum.  Deterministic: ties broken by stored corner order
   (lowest stored ID wins).

2. ``update_corner_reference(track_id, corners)``
   Persist the given corner list as the new reference for *track_id*,
   then return the stored list.

3. ``load_corner_reference(track_id)``
   Load the persisted reference from
   ``Data/models/tracks/<track_id>/corners.json``.

4. ``resolve_corners(track_id, new_corners)``
   One-call convenience: load reference → match → update if needed → return
   the ID-stabilised corner list and a per-corner match report.

Persistence path
~~~~~~~~~~~~~~~~
``Data/models/tracks/<track_id>/corners.json``

Design principles
~~~~~~~~~~~~~~~~~
- Fully deterministic: identical inputs always produce identical outputs.
- The stored reference is updated only when a corner's mid-point shifts by
  more than ``update_tolerance_m`` or a new/deleted corner is detected.
- No mutation of caller-supplied lists.
- Structured logging only; zero print statements.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from path_manager import get_models_dir

logger = logging.getLogger(__name__)

# -- -

# Constants

# -- -


_CORNERS_FILENAME:      Final[str]   = "corners.json"
_DEFAULT_MIN_IOU:       Final[float] = 0.50    # minimum arc-IoU to consider a match
_DEFAULT_UPDATE_TOL_M:  Final[float] = 10.0    # mid-point shift (m) that triggers update
_TRACKS_SUBDIR:         Final[str]   = "tracks"


# -- -

# Exceptions

# -- -


class CornerPersistenceError(OSError):
    """Raised when the corner reference cannot be read or written."""


# -- -

# Data structures

# -- -


@dataclass(frozen=True)
class Corner:
    """Immutable representation of a single corner."""
    corner_id: int
    s_start:   float     # arc distance at entry  [m]
    s_end:     float     # arc distance at exit   [m]

    @property
    def length(self) -> float:
        return self.s_end - self.s_start

    @property
    def midpoint(self) -> float:
        return (self.s_start + self.s_end) / 2.0

    def iou(self, other: "Corner") -> float:
        """Arc-distance Intersection-over-Union with *other*."""
        inter_start = max(self.s_start, other.s_start)
        inter_end   = min(self.s_end,   other.s_end)
        inter       = max(0.0, inter_end - inter_start)
        union       = (self.s_end - self.s_start) + (other.s_end - other.s_start) - inter
        return inter / union if union > 0.0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "corner_id": self.corner_id,
            "s_start":   round(self.s_start, 2),
            "s_end":     round(self.s_end,   2),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Corner":
        return cls(
            corner_id = int(d["corner_id"]),
            s_start   = float(d["s_start"]),
            s_end     = float(d["s_end"]),
        )


@dataclass
class CornerMatchResult:
    """Per-corner result produced by ``match_corners``."""
    corner_id:    int      # assigned persistent ID
    s_start:      float
    s_end:        float
    matched:      bool     # True  → paired with a stored corner
    stored_id:    int | None  # ID of the matched stored corner (None if new)
    iou:          float    # IoU with matched stored corner (0.0 if unmatched)
    id_changed:   bool     # True if the raw detection ID ≠ assigned ID
    ref_updated:  bool     # True if the reference entry was updated/added

    def to_dict(self) -> dict[str, Any]:
        return {
            "corner_id":   self.corner_id,
            "s_start":     round(self.s_start,  2),
            "s_end":       round(self.s_end,    2),
            "matched":     self.matched,
            "stored_id":   self.stored_id,
            "iou":         round(self.iou,      4),
            "id_changed":  self.id_changed,
            "ref_updated": self.ref_updated,
        }


# -- -

# Persistence helpers

# -- -


def _corner_file_path(track_id: str) -> Path:
    return get_models_dir() / _TRACKS_SUBDIR / track_id / _CORNERS_FILENAME


def load_corner_reference(track_id: str) -> list[Corner]:
    """
    Load the persisted corner reference for *track_id*.

    Returns an empty list if no reference has been stored yet (first-run case).

    Raises
    ------
    CornerPersistenceError
        If the file exists but cannot be parsed as valid JSON.
    """
    path = _corner_file_path(track_id)
    if not path.exists():
        logger.info("No corner reference found for track %r; starting empty.", track_id)
        return []

    try:
        raw: list[dict] = json.loads(path.read_text(encoding="utf-8"))
        corners = [Corner.from_dict(d) for d in raw]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise CornerPersistenceError(
            f"Failed to parse corner reference at {path}: {exc}"
        ) from exc

    logger.info(
        "Loaded %d stored corner(s) for track %r from %s.",
        len(corners), track_id, path,
    )
    return corners


def update_corner_reference(
    track_id: str,
    corners:  list[Corner] | list[dict[str, Any]],
) -> list[Corner]:
    """
    Persist *corners* as the new reference for *track_id*.

    Parameters
    ----------
    track_id:
        Track identifier (used to locate the storage path).
    corners:
        List of :class:`Corner` objects or plain dicts with keys
        ``corner_id``, ``s_start``, ``s_end``.

    Returns
    -------
    list[Corner]
        The list that was written, normalised to :class:`Corner` objects.

    Raises
    ------
    CornerPersistenceError
        If the file cannot be written (permissions, disk full, etc.).
    """
    normalised: list[Corner] = [
        c if isinstance(c, Corner) else Corner.from_dict(c)
        for c in corners
    ]
    # Sort by ID for deterministic JSON output

    normalised.sort(key=lambda c: c.corner_id)

    path = _corner_file_path(track_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        path.write_text(
            json.dumps([c.to_dict() for c in normalised], indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        raise CornerPersistenceError(
            f"Could not write corner reference to {path}: {exc}"
        ) from exc

    logger.info(
        "Saved %d corner(s) for track %r to %s.",
        len(normalised), track_id, path,
    )
    return normalised


# -- -

# Core matching logic

# -- -


def match_corners(
    new_corners:    list[dict[str, Any]] | list[Corner],
    stored_corners: list[dict[str, Any]] | list[Corner],
    *,
    min_iou:           float = _DEFAULT_MIN_IOU,
    update_tolerance_m: float = _DEFAULT_UPDATE_TOL_M,
) -> tuple[list[CornerMatchResult], bool]:
    """
    Assign persistent IDs to *new_corners* by matching against *stored_corners*.

    Matching rules
    ~~~~~~~~~~~~~~
    1. For each new corner, compute IoU against every stored corner.
    2. Assign the stored corner's ID if the best-match IoU ≥ *min_iou*.
       Ties are broken by stored-corner order (lowest ``corner_id`` wins),
       ensuring determinism.
    3. Each stored corner is consumed at most once (one-to-one matching).
    4. Unmatched new corners receive IDs starting from
       ``max(stored_ids) + 1``, assigned in order of ``s_start``.
    5. A matched corner is flagged ``ref_updated=True`` when its mid-point
       shifts by more than *update_tolerance_m* relative to the stored entry.

    Parameters
    ----------
    new_corners:
        Detected corners from the current session (dicts or :class:`Corner`).
    stored_corners:
        Previously persisted reference corners for the track.
    min_iou:
        Minimum arc-IoU to accept a match.  Default: 0.50.
    update_tolerance_m:
        Mid-point displacement (metres) that marks a match as needing a
        reference update.  Default: 10.0 m.

    Returns
    -------
    (results, reference_needs_update) : tuple
        ``results``               – list of :class:`CornerMatchResult`, sorted
                                    by ``s_start``.
        ``reference_needs_update`` – True if any corner was unmatched, newly
                                     assigned, or flagged for update.
    """
    # Normalise inputs

    new_list:    list[Corner] = [
        c if isinstance(c, Corner) else Corner.from_dict(c) for c in new_corners
    ]
    stored_list: list[Corner] = [
        c if isinstance(c, Corner) else Corner.from_dict(c) for c in stored_corners
    ]

    # Sort new corners by s_start for deterministic processing

    new_list = sorted(new_list, key=lambda c: c.s_start)

    stored_by_id:  dict[int, Corner] = {c.corner_id: c for c in stored_list}
    available_ids: list[int]         = sorted(stored_by_id.keys())

    # Pre-compute IoU matrix: new[i] × stored[j]

    # shape: (n_new, n_stored) — using stored_list order for determinism

    stored_sorted = sorted(stored_list, key=lambda c: c.corner_id)
    iou_matrix: list[list[float]] = [
        [new_c.iou(st_c) for st_c in stored_sorted]
        for new_c in new_list
    ]

    results:       list[CornerMatchResult] = []
    matched_stored: set[int]               = set()   # consumed stored corner IDs
    max_stored_id  = max(available_ids, default=0)

    # Greedy assignment sorted by best-IoU descending (highest-confidence first)

    # Build (iou, new_idx, stored_idx) triples

    candidates: list[tuple[float, int, int]] = []
    for i, row in enumerate(iou_matrix):
        for j, iou_val in enumerate(row):
            if iou_val >= min_iou:
                candidates.append((iou_val, i, j))

    # Sort by IoU descending; ties broken by stored ID ascending (deterministic)

    candidates.sort(key=lambda t: (-t[0], stored_sorted[t[2]].corner_id))

    assignment: dict[int, int] = {}   # new_idx → stored_idx

    for iou_val, ni, si in candidates:
        stored_id = stored_sorted[si].corner_id
        if ni in assignment:
            continue              # new corner already matched
        if stored_id in matched_stored:
            continue              # stored corner already consumed
        assignment[ni] = si
        matched_stored.add(stored_id)

    # Build results for matched corners

    next_new_id = max_stored_id + 1
    reference_needs_update = False

    # Track which new corners remain unmatched

    matched_new_idxs: set[int] = set(assignment.keys())

    for i, new_c in enumerate(new_list):
        if i in assignment:
            si        = assignment[i]
            stored_c  = stored_sorted[si]
            iou_val   = iou_matrix[i][si]
            mid_shift = abs(new_c.midpoint - stored_c.midpoint)
            ref_upd   = mid_shift > update_tolerance_m

            if ref_upd:
                reference_needs_update = True
                logger.debug(
                    "Corner %d mid-point shifted %.1f m (threshold %.1f m) → update.",
                    stored_c.corner_id, mid_shift, update_tolerance_m,
                )

            results.append(CornerMatchResult(
                corner_id   = stored_c.corner_id,
                s_start     = new_c.s_start,
                s_end       = new_c.s_end,
                matched     = True,
                stored_id   = stored_c.corner_id,
                iou         = iou_val,
                id_changed  = (new_c.corner_id != stored_c.corner_id),
                ref_updated = ref_upd,
            ))
        else:
            # New corner — assign next available ID

            reference_needs_update = True
            results.append(CornerMatchResult(
                corner_id   = next_new_id,
                s_start     = new_c.s_start,
                s_end       = new_c.s_end,
                matched     = False,
                stored_id   = None,
                iou         = 0.0,
                id_changed  = True,
                ref_updated = True,
            ))
            logger.info(
                "New corner at s=%.1f–%.1f m assigned id=%d.",
                new_c.s_start, new_c.s_end, next_new_id,
            )
            next_new_id += 1

    # Detect deleted corners (stored but not matched by any new corner)

    deleted_ids = sorted(set(stored_by_id.keys()) - matched_stored)
    if deleted_ids:
        reference_needs_update = True
        logger.info("Stored corners not matched in new detection: %s.", deleted_ids)

    # Sort final results by s_start for consistent ordering

    results.sort(key=lambda r: r.s_start)
    # Re-assign corner_id sequentially? No — IDs must be stable. Keep assigned IDs.


    logger.info(
        "Corner matching: %d new, %d stored → %d matched, %d new IDs, %d deleted. "
        "reference_needs_update=%s",
        len(new_list), len(stored_list),
        len(matched_new_idxs), len(new_list) - len(matched_new_idxs),
        len(deleted_ids), reference_needs_update,
    )
    return results, reference_needs_update


def resolve_corners(
    track_id:    str,
    new_corners: list[dict[str, Any]],
    *,
    min_iou:            float = _DEFAULT_MIN_IOU,
    update_tolerance_m: float = _DEFAULT_UPDATE_TOL_M,
    db_path_override:   Path | None = None,
) -> tuple[list[dict[str, Any]], list[CornerMatchResult]]:
    """
    Full pipeline: load reference → match → persist if needed → return results.

    Parameters
    ----------
    track_id:
        Track identifier.
    new_corners:
        Corner list from ``corner_detection.detect_corners`` (list of dicts
        with ``corner_id``, ``s_start``, ``s_end``).
    min_iou / update_tolerance_m:
        Forwarded to :func:`match_corners`.
    db_path_override:
        If provided, overrides the default models directory for the track
        folder (used in tests to redirect I/O to a temp directory).

    Returns
    -------
    (stable_corners, match_report) : tuple
        ``stable_corners``  – list[dict] with persistent ``corner_id`` values,
                              ready to be used by downstream analysis modules.
        ``match_report``    – list[:class:`CornerMatchResult`] for diagnostics.
    """
    # Allow path override for tests

    if db_path_override is not None:
        import unittest.mock as _mock
        with _mock.patch(
            "corner_persistence.get_models_dir",
            return_value=db_path_override,
        ):
            return _resolve_corners_impl(
                track_id, new_corners,
                min_iou=min_iou,
                update_tolerance_m=update_tolerance_m,
            )
    return _resolve_corners_impl(
        track_id, new_corners,
        min_iou=min_iou,
        update_tolerance_m=update_tolerance_m,
    )


def _resolve_corners_impl(
    track_id:    str,
    new_corners: list[dict[str, Any]],
    *,
    min_iou:            float,
    update_tolerance_m: float,
) -> tuple[list[dict[str, Any]], list[CornerMatchResult]]:
    stored   = load_corner_reference(track_id)
    results, needs_update = match_corners(
        new_corners, stored,
        min_iou=min_iou,
        update_tolerance_m=update_tolerance_m,
    )

    if needs_update or not stored:
        updated_corners = [
            Corner(corner_id=r.corner_id, s_start=r.s_start, s_end=r.s_end)
            for r in results
        ]
        update_corner_reference(track_id, updated_corners)

    stable = [
        {"corner_id": r.corner_id, "s_start": r.s_start, "s_end": r.s_end}
        for r in results
    ]
    return stable, results


# -- -

# Unit tests

# -- -


def _run_tests() -> None:
    import traceback
    import tempfile

    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name: str, fn) -> None:   # type: ignore[type-arg]
        try:
            fn()
            passed.append(name)
        except Exception:   # noqa: BLE001
            failed.append((name, traceback.format_exc()))

    #
    # Helpers

    #

    def _c(cid: int, s: float, e: float) -> Corner:
        return Corner(corner_id=cid, s_start=s, s_end=e)

    def _cd(cid: int, s: float, e: float) -> dict:
        return {"corner_id": cid, "s_start": s, "s_end": e}

    # Reference corners for a fictional 4-corner circuit

    REF = [_c(1, 100, 200), _c(2, 400, 550), _c(3, 800, 950), _c(4, 1200, 1350)]

    #
    # Test 1 – identical detection → all matched, IDs preserved, no update

    #
    def t_identical_match() -> None:
        new = [_cd(1, 100, 200), _cd(2, 400, 550), _cd(3, 800, 950), _cd(4, 1200, 1350)]
        results, needs_update = match_corners(new, REF)
        assert not needs_update, "Identical corners should not trigger update"
        for r in results:
            assert r.matched
            assert not r.id_changed
            assert not r.ref_updated

    _test("identical_match", t_identical_match)

    #
    # Test 2 – slight shift within tolerance → matched, no update

    #
    def t_small_shift_no_update() -> None:
        # Shift corner 2 by 5 m (< default 10 m tolerance)

        new = [_cd(1, 100, 200), _cd(2, 405, 555), _cd(3, 800, 950), _cd(4, 1200, 1350)]
        results, needs_update = match_corners(new, REF, update_tolerance_m=10.0)
        c2 = next(r for r in results if r.stored_id == 2)
        assert c2.matched
        assert not c2.ref_updated, "5 m shift < 10 m tolerance → no update"
        assert not needs_update

    _test("small_shift_no_update", t_small_shift_no_update)

    #
    # Test 3 – shift beyond tolerance → matched, ref_updated = True

    #
    def t_large_shift_triggers_update() -> None:
        # Shift corner 3 mid-point by 25 m (> default 10 m)

        new = [_cd(1, 100, 200), _cd(2, 400, 550), _cd(3, 825, 975), _cd(4, 1200, 1350)]
        results, needs_update = match_corners(new, REF, update_tolerance_m=10.0)
        c3 = next(r for r in results if r.stored_id == 3)
        assert c3.matched
        assert c3.ref_updated, "25 m mid-point shift > 10 m tolerance → update"
        assert needs_update

    _test("large_shift_triggers_update", t_large_shift_triggers_update)

    #
    # Test 4 – new corner discovered → assigned ID = max + 1

    #
    def t_new_corner_assigned_new_id() -> None:
        # Add a 5th corner not in reference

        new = [_cd(1, 100, 200), _cd(2, 400, 550), _cd(3, 800, 950),
               _cd(4, 1200, 1350), _cd(5, 1600, 1700)]
        results, needs_update = match_corners(new, REF)
        unmatched = [r for r in results if not r.matched]
        assert len(unmatched) == 1, f"Expected 1 new corner, got {len(unmatched)}"
        assert unmatched[0].corner_id == 5    # max(1,2,3,4) + 1
        assert needs_update

    _test("new_corner_assigned_new_id", t_new_corner_assigned_new_id)

    #
    # Test 5 – deleted corner → reference_needs_update = True

    #
    def t_deleted_corner_flags_update() -> None:
        # Only 3 of 4 reference corners detected

        new = [_cd(1, 100, 200), _cd(2, 400, 550), _cd(4, 1200, 1350)]
        _, needs_update = match_corners(new, REF)
        assert needs_update, "Missing stored corner should flag update"

    _test("deleted_corner_flags_update", t_deleted_corner_flags_update)

    #
    # Test 6 – ID reassignment: detection order ≠ stored order

    #
    def t_id_reassignment_regardless_of_detection_order() -> None:
        # Pass corners in reversed order; should still get correct IDs

        new = [_cd(99, 1200, 1350), _cd(99, 800, 950),
               _cd(99, 400, 550),   _cd(99, 100, 200)]
        results, _ = match_corners(new, REF)
        assigned = {r.s_start: r.corner_id for r in results}
        assert assigned[100.0] == 1
        assert assigned[400.0] == 2
        assert assigned[800.0] == 3
        assert assigned[1200.0] == 4

    _test("id_reassignment_order_independent", t_id_reassignment_regardless_of_detection_order)

    #
    # Test 7 – IoU too low → no match, new ID assigned

    #
    def t_low_iou_no_match() -> None:
        # Corner completely elsewhere on the lap

        new = [_cd(1, 2000, 2100)]
        results, needs_update = match_corners(new, REF, min_iou=0.5)
        assert len(results) == 1
        assert not results[0].matched
        assert results[0].corner_id == 5   # max(REF IDs) + 1
        assert needs_update

    _test("low_iou_no_match", t_low_iou_no_match)

    #
    # Test 8 – empty stored reference → all new IDs, update flagged

    #
    def t_empty_reference() -> None:
        new = [_cd(1, 100, 200), _cd(2, 500, 600)]
        results, needs_update = match_corners(new, [])
        assert needs_update
        ids = sorted(r.corner_id for r in results)
        assert ids == [1, 2], f"Expected [1, 2], got {ids}"

    _test("empty_reference", t_empty_reference)

    #
    # Test 9 – empty new corners → no results, update flagged (deletions)

    #
    def t_empty_new_corners() -> None:
        results, needs_update = match_corners([], REF)
        assert results == []
        assert needs_update, "Stored corners without matches should flag update"

    _test("empty_new_corners", t_empty_new_corners)

    #
    # Test 10 – determinism: same input always same output

    #
    def t_deterministic() -> None:
        new = [_cd(1, 105, 205), _cd(2, 395, 545), _cd(3, 810, 960), _cd(4, 1190, 1340)]
        r1, _ = match_corners(new, REF)
        r2, _ = match_corners(new, REF)
        assert [(r.corner_id, r.s_start, r.s_end) for r in r1] == \
               [(r.corner_id, r.s_start, r.s_end) for r in r2], \
               "match_corners is not deterministic"

    _test("deterministic", t_deterministic)

    #
    # Test 11 – one-to-one: a stored corner cannot be matched twice

    #
    def t_one_to_one_matching() -> None:
        # Two very similar new corners both overlapping stored corner 1

        new = [_cd(99, 100, 200), _cd(99, 110, 210)]
        results, _ = match_corners(new, [_c(1, 100, 200)], min_iou=0.3)
        # One should be matched to ID 1, the other should get a new ID

        ids = sorted(r.corner_id for r in results)
        assert 1 in ids, "Stored corner 1 must appear once"
        assert len(set(ids)) == 2, "Two distinct IDs expected"

    _test("one_to_one_matching", t_one_to_one_matching)

    #
    # Test 12 – persistence round-trip (load → save → load)

    #
    def t_persistence_roundtrip() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            import unittest.mock as mock
            with mock.patch("corner_persistence.get_models_dir", return_value=tmp):
                update_corner_reference("spa", [_c(1, 100, 200), _c(2, 400, 550)])
                loaded = load_corner_reference("spa")

            assert len(loaded) == 2
            assert loaded[0].corner_id == 1
            assert abs(loaded[0].s_start - 100.0) < 1e-6
            assert loaded[1].corner_id == 2
            assert abs(loaded[1].s_end - 550.0) < 1e-6

    _test("persistence_roundtrip", t_persistence_roundtrip)

    #
    # Test 13 – resolve_corners: first session registers all corners

    #
    def t_resolve_first_session() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            new = [_cd(1, 100, 200), _cd(2, 400, 550), _cd(3, 800, 950)]
            stable, report = resolve_corners("track_a", new, db_path_override=Path(tmpdir))
            assert len(stable) == 3
            assert all(not r.matched for r in report), "No stored → all should be unmatched"
            # Verify file was created

            import unittest.mock as mock
            with mock.patch("corner_persistence.get_models_dir", return_value=Path(tmpdir)):
                loaded = load_corner_reference("track_a")
            assert len(loaded) == 3

    _test("resolve_first_session", t_resolve_first_session)

    #
    # Test 14 – resolve_corners: second session matches persisted IDs

    #
    def t_resolve_second_session_stable_ids() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            session1 = [_cd(1, 100, 200), _cd(2, 400, 550), _cd(3, 800, 950)]
            stable1, _ = resolve_corners("track_b", session1, db_path_override=Path(tmpdir))

            # Second session with slightly different boundaries

            session2 = [_cd(9, 102, 198), _cd(9, 402, 548), _cd(9, 802, 948)]
            stable2, _ = resolve_corners("track_b", session2, db_path_override=Path(tmpdir))

            ids1 = sorted(c["corner_id"] for c in stable1)
            ids2 = sorted(c["corner_id"] for c in stable2)
            assert ids1 == ids2, (
                f"IDs should be stable across sessions: {ids1} vs {ids2}"
            )

    _test("resolve_second_session_stable_ids", t_resolve_second_session_stable_ids)

    #
    # Test 15 – IoU geometry: identical corners → IoU = 1.0

    #
    def t_iou_identical() -> None:
        c = _c(1, 100, 200)
        assert abs(c.iou(c) - 1.0) < 1e-9

    _test("iou_identical", t_iou_identical)

    #
    # Test 16 – IoU geometry: non-overlapping → IoU = 0.0

    #
    def t_iou_no_overlap() -> None:
        a = _c(1, 100, 200)
        b = _c(2, 300, 400)
        assert a.iou(b) == 0.0

    _test("iou_no_overlap", t_iou_no_overlap)

    #
    # Test 17 – results always sorted by s_start

    #
    def t_results_sorted_by_s_start() -> None:
        new = [_cd(4, 1200, 1350), _cd(1, 100, 200), _cd(3, 800, 950), _cd(2, 400, 550)]
        results, _ = match_corners(new, REF)
        starts = [r.s_start for r in results]
        assert starts == sorted(starts), f"Results not sorted by s_start: {starts}"

    _test("results_sorted_by_s_start", t_results_sorted_by_s_start)

    #
    # Summary

    #
    total = len(passed) + len(failed)
    print(f"\nCorner Persistence Tests: {len(passed)}/{total} passed")
    for name in passed:
        print(f"  ✓ {name}")
    for name, tb in failed:
        print(f"  ✗ {name}\n{tb}")

    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


# -- -

# Entry point

# -- -


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()