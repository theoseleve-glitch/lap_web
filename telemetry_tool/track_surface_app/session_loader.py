"""SessionLoader — translates a SaaS session row into a track_surface DatasetEntry.

The research pipeline (``track_surface.validation.harness.run_pipeline``) expects
a strictly validated ``DatasetEntry`` with ``TrackSpec`` (regime enum),
``VehicleSpec`` (mass, wheelbase, bias, etc.), and an ``.ibt`` file on disk.

The SaaS database holds:
  - ``sessions.source_path`` — the uploaded telemetry file (usually CSV)
  - ``sessions.analysis_json`` — optional metadata blob that can carry
    ``track_spec`` + ``vehicle_spec`` sub-objects when the uploader provided them
  - ``sessions.track_id`` / ``sessions.kart_id`` — FKs for fallback lookup

This module is the single seam between those two worlds. If the inputs don't
meet the research stack's preconditions, the loader returns a
``NotSupportedReason`` instead of raising so the caller can map the case to
**SupportTier.D** cleanly — exactly as the application-layer design intends.
"""
from __future__ import annotations

import json
import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from track_surface.validation.manifest import (
    DatasetEntry,
    ExpectedMetrics,
    SessionInfo,
    TrackSpec,
    VehicleSpec,
)

logger = logging.getLogger(__name__)


# ── Structured failure reasons ──────────────────────────────

class NotSupportedReason(str):
    """String subclass so values round-trip cleanly through logs / JSON."""


NOT_SUPPORTED_SESSION_NOT_FOUND = NotSupportedReason("session_not_found")
NOT_SUPPORTED_SOURCE_PATH_MISSING = NotSupportedReason("source_path_missing")
NOT_SUPPORTED_SOURCE_FORMAT_NOT_IBT = NotSupportedReason("source_format_not_ibt")
NOT_SUPPORTED_SOURCE_FILE_MISSING = NotSupportedReason("source_file_missing")
NOT_SUPPORTED_VEHICLE_SPEC_MISSING = NotSupportedReason("vehicle_spec_missing")
NOT_SUPPORTED_TRACK_SPEC_MISSING = NotSupportedReason("track_spec_missing")
NOT_SUPPORTED_METADATA_INVALID = NotSupportedReason("metadata_invalid")


@dataclass(frozen=True)
class LoadResult:
    """Result of attempting to build a DatasetEntry.

    Exactly one of ``entry`` or ``reason`` is non-None.
    """
    entry: DatasetEntry | None = None
    reason: NotSupportedReason | None = None
    detail: str | None = None

    @property
    def is_supported(self) -> bool:
        return self.entry is not None


# ── Public API ──────────────────────────────────────────────

class SessionNotFoundError(RuntimeError):
    """Raised when the session row does not exist at all.

    This IS an error — unlike NotSupportedReason, which is a domain-level
    gate. A missing session row means the caller gave us a bogus session_id.
    """


class SessionLoader:
    """Builds track_surface DatasetEntry objects from SaaS sessions table rows.

    Designed for dependency injection: the Celery adapter passes a
    ``conn_factory`` and ``set_workspace_context_fn`` it trusts; the tests
    pass an in-memory SQLite connection plus no-op context setter.
    """

    def __init__(
        self,
        *,
        conn_factory,
        set_workspace_context_fn=None,
    ):
        self._conn_factory = conn_factory
        self._set_ws = set_workspace_context_fn

    def load_from_bundle(self, bundle_id: str, workspace_id: int) -> LoadResult:
        """Load a DatasetEntry from a bundle_intake bundle row.

        Uses ``bundle_session_metadata`` (the normalized read model) as
        source-of-truth for vehicle_spec/track_spec. Session identity comes
        from ``bundle_session_metadata`` columns. Telemetry file path is
        reconstructed by unpacking the raw bundle on-demand (outside this
        loader — the pipeline adapter handles extraction).

        Raises ``SessionNotFoundError`` if the bundle row is missing.
        Returns ``LoadResult(reason=...)`` when the bundle exists but its
        readiness is not met (e.g. degraded bundle).
        """
        conn = self._conn_factory()
        if self._set_ws is not None and workspace_id is not None:
            try:
                self._set_ws(conn, workspace_id)
            except Exception:
                logger.debug("set_workspace_context failed; continuing", exc_info=True)

        row = _fetch_bundle_metadata_row(conn, bundle_id, workspace_id)
        if row is None:
            raise SessionNotFoundError(f"bundle_id={bundle_id} not found")

        if not bool(_row_get(row, "readiness_is_ready")):
            return LoadResult(
                reason=NOT_SUPPORTED_METADATA_INVALID,
                detail="bundle_readiness_not_met",
            )

        raw_path = _row_get(row, "raw_path")
        if not raw_path or not Path(str(raw_path)).is_file():
            return LoadResult(
                reason=NOT_SUPPORTED_SOURCE_FILE_MISSING,
                detail=f"raw bundle file not on disk: {raw_path}",
            )

        # Extract telemetry IBT from the zip to a cached location.
        ibt_path = _extract_telemetry_ibt(conn, bundle_id, raw_path)
        if ibt_path is None:
            return LoadResult(
                reason=NOT_SUPPORTED_SOURCE_FORMAT_NOT_IBT,
                detail="bundle contains no telemetry/*.ibt entry",
            )

        vehicle_spec = _load_json(_row_get(row, "vehicle_spec")) or {}
        track_spec = _load_json(_row_get(row, "track_spec")) or {}

        try:
            track = _track_spec_from_dict(track_spec)
        except _MetadataGap as gap:
            return LoadResult(reason=NOT_SUPPORTED_TRACK_SPEC_MISSING, detail=str(gap))

        # VehicleSpec: try manifest data first, then fall back to the server-side
        # vehicle_specs.json lookup. In v1 the logger doesn't carry vehicle
        # physics data — the server resolves it from a static registry.
        if not _has_required_vehicle_fields(vehicle_spec):
            vehicle_key = _row_get(
                _fetch_bundle_metadata_row(conn, bundle_id, workspace_id),
                "vehicle_key",
            ) if not vehicle_spec else None
            fallback = _load_vehicle_spec_from_registry(
                vehicle_key or "",
                vehicle_spec.get("name", ""),
            )
            if fallback is not None:
                vehicle_spec = fallback

        try:
            vehicle = _vehicle_spec_from_dict(vehicle_spec)
        except _MetadataGap as gap:
            return LoadResult(reason=NOT_SUPPORTED_VEHICLE_SPEC_MISSING, detail=str(gap))

        session_info = _load_json(_row_get(row, "session_info")) or {}
        info = SessionInfo(
            type=str(session_info.get("type") or "unknown"),
            kappa_available=bool(session_info.get("kappa_available", False)),
            ride_height_available=bool(session_info.get("ride_height_available", True)),
            notes=str(session_info.get("notes") or ""),
        )

        try:
            entry = DatasetEntry(
                id=f"bundle_{bundle_id}",
                ibt_path=str(ibt_path),
                group=_resolve_group(track),
                track=track,
                vehicle=vehicle,
                session=info,
                expected=ExpectedMetrics(),
            )
        except ValueError as exc:
            return LoadResult(reason=NOT_SUPPORTED_METADATA_INVALID, detail=str(exc))

        return LoadResult(entry=entry)

    def load(self, session_id: int, workspace_id: int) -> LoadResult:
        """Load + translate a legacy CSV-path session.

        Raises SessionNotFoundError if the session row is missing. Returns
        ``LoadResult(reason=...)`` for sessions that exist but cannot be
        translated into a DatasetEntry.
        """
        conn = self._conn_factory()
        if self._set_ws is not None and workspace_id is not None:
            try:
                self._set_ws(conn, workspace_id)
            except Exception:   # RLS isn't critical for ibt path lookup
                logger.debug("set_workspace_context failed; continuing", exc_info=True)

        row = _fetch_session_row(conn, session_id)
        if row is None:
            raise SessionNotFoundError(f"session_id={session_id} not found")

        source_path = _row_get(row, "source_path")
        if not source_path:
            return LoadResult(
                reason=NOT_SUPPORTED_SOURCE_PATH_MISSING,
                detail=f"session {session_id} has no source_path",
            )

        path_obj = Path(str(source_path))
        if path_obj.suffix.lower() != ".ibt":
            return LoadResult(
                reason=NOT_SUPPORTED_SOURCE_FORMAT_NOT_IBT,
                detail=f"source_path has extension {path_obj.suffix!r}, expected .ibt",
            )
        if not path_obj.is_file():
            return LoadResult(
                reason=NOT_SUPPORTED_SOURCE_FILE_MISSING,
                detail=f"source_path does not exist: {source_path}",
            )

        analysis_json = _parse_analysis_json(_row_get(row, "analysis_json"))

        try:
            track_spec = _build_track_spec(conn, row, analysis_json)
        except _MetadataGap as gap:
            return LoadResult(reason=NOT_SUPPORTED_TRACK_SPEC_MISSING, detail=str(gap))

        try:
            vehicle_spec = _build_vehicle_spec(conn, row, analysis_json)
        except _MetadataGap as gap:
            return LoadResult(reason=NOT_SUPPORTED_VEHICLE_SPEC_MISSING, detail=str(gap))

        session_info = _build_session_info(row, analysis_json)

        try:
            entry = DatasetEntry(
                id=f"saas_session_{session_id}",
                ibt_path=str(path_obj),
                group=_resolve_group(track_spec),
                track=track_spec,
                vehicle=vehicle_spec,
                session=session_info,
                expected=ExpectedMetrics(),
            )
        except ValueError as exc:
            return LoadResult(reason=NOT_SUPPORTED_METADATA_INVALID, detail=str(exc))

        return LoadResult(entry=entry)


# ── Internal helpers ────────────────────────────────────────


class _MetadataGap(Exception):
    """Raised inside builders when a required field cannot be derived."""


def _fetch_session_row(conn, session_id: int):
    """Fetch the session row using best-effort SQL compat."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT session_id, source_path, analysis_json, track_id, kart_id
            FROM sessions
            WHERE session_id = :sid
            """,
            {"sid": session_id},
        )
        return cur.fetchone()
    finally:
        cur.close()


def _row_get(row, key: str):
    """Fetch a column from a row, works for dict, sqlite3.Row, and tuples with known order."""
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return None


def _parse_analysis_json(raw) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


# ── TrackSpec builder ──────────────────────────────────────


_DEFAULT_TRACK_REGIME = "flat"
_REGIME_ALIASES = {
    "flat": "flat",
    "banked": "banked",
    "mixed": "mixed",
    "hilly": "mixed",     # permissive remap; research stack accepts {flat, banked, mixed}
    "unknown": "flat",
}


def _build_track_spec(conn, row, analysis_json: dict[str, Any]) -> TrackSpec:
    ts = analysis_json.get("track_spec") if analysis_json else None
    if isinstance(ts, dict):
        try:
            return TrackSpec(
                name=str(ts.get("name") or "unknown"),
                layout=str(ts.get("layout") or "default"),
                regime=_normalize_regime(ts.get("regime")),
                expected_max_bank_deg=float(ts.get("expected_max_bank_deg") or 0.0),
                track_length_m=ts.get("track_length_m"),
                notes=str(ts.get("notes") or ""),
            )
        except (ValueError, TypeError) as exc:
            raise _MetadataGap(f"analysis_json.track_spec invalid: {exc}") from exc

    # Fallback: look up tracks table
    track_id = _row_get(row, "track_id")
    if not track_id:
        raise _MetadataGap("no track_spec in analysis_json and no track_id FK")
    track_row = _fetch_track_row(conn, track_id)
    if track_row is None:
        raise _MetadataGap(f"tracks row not found for track_id={track_id!r}")

    return TrackSpec(
        name=str(_row_get(track_row, "track_name") or "unknown"),
        layout="default",
        regime=_DEFAULT_TRACK_REGIME,
        expected_max_bank_deg=0.0,
        track_length_m=_row_get(track_row, "lap_length_m"),
        notes="derived_from_tracks_table",
    )


def _normalize_regime(value) -> str:
    if value is None:
        return _DEFAULT_TRACK_REGIME
    key = str(value).strip().lower()
    return _REGIME_ALIASES.get(key, _DEFAULT_TRACK_REGIME)


def _fetch_track_row(conn, track_id):
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT track_id, track_name, lap_length_m FROM tracks WHERE track_id = :tid",
            {"tid": track_id},
        )
        return cur.fetchone()
    except Exception:
        # Tables schemas drift between SQLite and PG; swallow and fall back.
        return None
    finally:
        cur.close()


# ── VehicleSpec builder ────────────────────────────────────


_REQUIRED_VEHICLE_FIELDS = (
    "name", "klass", "drive_layout", "mass_kg", "wheelbase_m",
    "track_front_m", "track_rear_m", "weight_dist_front", "aero_cla",
    "cg_height_m", "brake_bias_front", "steer_ratio",
    "camber_front_deg", "camber_rear_deg",
)


def _build_vehicle_spec(conn, row, analysis_json: dict[str, Any]) -> VehicleSpec:
    vs = analysis_json.get("vehicle_spec") if analysis_json else None
    if not isinstance(vs, dict):
        raise _MetadataGap(
            "analysis_json.vehicle_spec not present — SaaS sessions must carry "
            "full VehicleSpec in analysis_json until kart-registry integration lands"
        )

    missing = [k for k in _REQUIRED_VEHICLE_FIELDS if vs.get(k) is None]
    if missing:
        raise _MetadataGap(f"analysis_json.vehicle_spec missing fields: {missing}")

    try:
        return VehicleSpec(
            name=str(vs["name"]),
            klass=str(vs["klass"]),
            drive_layout=str(vs["drive_layout"]),
            mass_kg=float(vs["mass_kg"]),
            wheelbase_m=float(vs["wheelbase_m"]),
            track_front_m=float(vs["track_front_m"]),
            track_rear_m=float(vs["track_rear_m"]),
            weight_dist_front=float(vs["weight_dist_front"]),
            aero_cla=float(vs["aero_cla"]),
            cg_height_m=float(vs["cg_height_m"]),
            brake_bias_front=float(vs["brake_bias_front"]),
            steer_ratio=float(vs["steer_ratio"]),
            camber_front_deg=float(vs["camber_front_deg"]),
            camber_rear_deg=float(vs["camber_rear_deg"]),
            tire_d1_lat_default=float(vs.get("tire_d1_lat_default", 2.8)),
            tire_d1_long_default=float(vs.get("tire_d1_long_default", 2.7)),
        )
    except (ValueError, TypeError) as exc:
        raise _MetadataGap(f"analysis_json.vehicle_spec invalid: {exc}") from exc


# ── SessionInfo builder ────────────────────────────────────


def _build_session_info(row, analysis_json: dict[str, Any]) -> SessionInfo:
    si = analysis_json.get("session_info") if analysis_json else None
    if isinstance(si, dict):
        try:
            return SessionInfo(
                type=str(si.get("type") or "unknown"),
                kappa_available=bool(si.get("kappa_available", False)),
                ride_height_available=bool(si.get("ride_height_available", True)),
                notes=str(si.get("notes") or ""),
            )
        except ValueError:
            pass  # fall through to default
    return SessionInfo()


# ── Group resolution ───────────────────────────────────────


def _load_json(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


# ── Bundle-aware helpers ───────────────────────────────────


def _fetch_bundle_metadata_row(conn, bundle_id: str, workspace_id: int):
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT b.raw_path,
                   m.vehicle_spec, m.track_spec, m.session_info,
                   m.readiness_is_ready
            FROM uploaded_bundles b
            LEFT JOIN bundle_session_metadata m ON m.bundle_id = b.bundle_id
            WHERE b.bundle_id = :bid AND b.workspace_id = :ws
            """,
            {"bid": bundle_id, "ws": workspace_id},
        )
        return cur.fetchone()
    finally:
        cur.close()


def _extract_telemetry_ibt(conn, bundle_id: str, raw_path: str) -> Path | None:
    """Extract the telemetry file from the bundle zip to a cached location.

    Returns the path on disk, or None if no telemetry file is present.
    Idempotent — re-extract overwrites atomically.
    """
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT path FROM bundle_artifacts "
            "WHERE bundle_id = :bid AND role = 'telemetry' "
            "ORDER BY path LIMIT 1",
            {"bid": bundle_id},
        )
        row = cur.fetchone()
    finally:
        cur.close()

    if row is None:
        return None

    inner_path = row["path"] if _row_get(row, "path") is not None else row[0]
    if not inner_path.lower().endswith(".ibt"):
        return None

    # Cache extracted file next to the raw zip: <raw_path_dir>/<bundle_id>_telem.ibt
    raw = Path(str(raw_path))
    cache_dir = raw.parent / f".{raw.stem}.extracted"
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / f"{bundle_id}_telem.ibt"

    if dest.is_file():
        return dest

    try:
        with zipfile.ZipFile(raw, "r") as zf:
            with zf.open(inner_path, "r") as src, open(dest, "wb") as sink:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    sink.write(chunk)
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        logger.warning("telemetry extract failed for bundle %s: %s", bundle_id, exc)
        return None
    return dest


def _track_spec_from_dict(ts: dict) -> TrackSpec:
    if not isinstance(ts, dict) or not ts:
        raise _MetadataGap("bundle_session_metadata.track_spec is empty")
    try:
        return TrackSpec(
            name=str(ts.get("name") or "unknown"),
            layout=str(ts.get("layout") or "default"),
            regime=_normalize_regime(ts.get("regime")),
            expected_max_bank_deg=float(ts.get("expected_max_bank_deg") or 0.0),
            track_length_m=ts.get("track_length_m"),
            notes=str(ts.get("notes") or ""),
        )
    except (ValueError, TypeError) as exc:
        raise _MetadataGap(f"track_spec invalid: {exc}") from exc


def _has_required_vehicle_fields(vs: dict) -> bool:
    """True iff the dict has all 14 required VehicleSpec fields."""
    if not isinstance(vs, dict) or not vs:
        return False
    return all(vs.get(k) is not None for k in _REQUIRED_VEHICLE_FIELDS)


_VEHICLE_SPECS_CACHE: dict[str, dict] | None = None


def _load_vehicle_spec_from_registry(vehicle_key: str, vehicle_name: str) -> dict | None:
    """Look up VehicleSpec from ``data/vehicle_specs.json`` by normalized key.

    Falls back to matching by name. Returns None if no match found.
    """
    global _VEHICLE_SPECS_CACHE
    if _VEHICLE_SPECS_CACHE is None:
        _VEHICLE_SPECS_CACHE = _read_vehicle_specs_file()

    if not _VEHICLE_SPECS_CACHE:
        return None

    # Try exact vehicle_key match first
    key_norm = vehicle_key.strip().lower().replace(" ", "_").replace("-", "_") if vehicle_key else ""
    if key_norm in _VEHICLE_SPECS_CACHE:
        return dict(_VEHICLE_SPECS_CACHE[key_norm])

    # Try matching by name
    name_norm = vehicle_name.strip().lower().replace(" ", "_").replace("-", "_") if vehicle_name else ""
    if name_norm in _VEHICLE_SPECS_CACHE:
        return dict(_VEHICLE_SPECS_CACHE[name_norm])

    # Try partial match on name
    for k, v in _VEHICLE_SPECS_CACHE.items():
        spec_name = v.get("name", "").strip().lower().replace(" ", "_")
        if spec_name and (spec_name in key_norm or key_norm in spec_name):
            return dict(v)

    return None


def _read_vehicle_specs_file() -> dict[str, dict]:
    """Read ``data/vehicle_specs.json`` from the repo root."""
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "data" / "vehicle_specs.json",
        Path(__file__).resolve().parent.parent / "data" / "vehicle_specs.json",
    ]
    for p in candidates:
        if p.is_file():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                return raw.get("vehicles", {}) if isinstance(raw, dict) else {}
            except (json.JSONDecodeError, OSError):
                pass
    return {}


def _vehicle_spec_from_dict(vs: dict) -> VehicleSpec:
    if not isinstance(vs, dict) or not vs:
        raise _MetadataGap("bundle_session_metadata.vehicle_spec is empty")
    missing = [k for k in _REQUIRED_VEHICLE_FIELDS if vs.get(k) is None]
    if missing:
        raise _MetadataGap(f"vehicle_spec missing fields: {missing}")
    try:
        return VehicleSpec(
            name=str(vs["name"]),
            klass=str(vs["klass"]),
            drive_layout=str(vs["drive_layout"]),
            mass_kg=float(vs["mass_kg"]),
            wheelbase_m=float(vs["wheelbase_m"]),
            track_front_m=float(vs["track_front_m"]),
            track_rear_m=float(vs["track_rear_m"]),
            weight_dist_front=float(vs["weight_dist_front"]),
            aero_cla=float(vs["aero_cla"]),
            cg_height_m=float(vs["cg_height_m"]),
            brake_bias_front=float(vs["brake_bias_front"]),
            steer_ratio=float(vs["steer_ratio"]),
            camber_front_deg=float(vs["camber_front_deg"]),
            camber_rear_deg=float(vs["camber_rear_deg"]),
            tire_d1_lat_default=float(vs.get("tire_d1_lat_default", 2.8)),
            tire_d1_long_default=float(vs.get("tire_d1_long_default", 2.7)),
        )
    except (ValueError, TypeError) as exc:
        raise _MetadataGap(f"vehicle_spec invalid: {exc}") from exc


def _resolve_group(track_spec: TrackSpec) -> str:
    """Map the (regime) into one of the manifest's six group slots."""
    regime = track_spec.regime
    if regime == "banked":
        return "A_banked"
    # For SaaS-derived sessions the research taxonomy doesn't map cleanly;
    # using F_other keeps the research invariant (valid group name) without
    # misrepresenting the session as a benchmarked validation dataset.
    return "F_other"
