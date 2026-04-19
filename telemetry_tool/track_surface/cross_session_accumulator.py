"""Cross-session accumulation of bucketed surface fields.

The cross-track validation showed that single-session bucketed fields
hit `excessive_fallback` warnings on every dataset — there is simply
not enough data in one session to populate 6 buckets × thousands of
cells. This module persists per-bucket evidence across sessions and
merges new sessions with safety guards.

Three pieces:

  AccumulatorKey       : (track_fingerprint, calibration_profile_id)
                         Two sessions can only merge if their keys match.

  CrossSessionAccumulator : per-key persistent dense field with
                            Bayesian Kalman merge per cell, divergence
                            rejection, full provenance trail.

  layered_query()      : combines current-session BucketedSurfaceField +
                         the accumulator into one query path with
                         explicit "current beats accumulated" precedence
                         when current evidence is strong.

Persistence:
  {dir}/{accumulator_key}.npz   — dense arrays per bucket
  {dir}/{accumulator_key}.json  — manifest: contributing sessions, rejections,
                                  merge log, schema version

Critical guarantees:
  - Sessions with different track fingerprint NEVER merge.
  - Sessions with different calibration profile NEVER merge.
  - Transition-bucket data NEVER accumulates.
  - Per-bucket divergence rejection prevents one-bad-session contamination.
  - Confidence stays honest: precision-weighted Kalman merge, not arithmetic averaging.
  - Full session list is queryable per cell.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

import numpy as np

from track_surface.condition_bucketing import (
    ACTIVE_BUCKETS,
    TRANSITION_BUCKET,
    BucketKey,
    BucketedSurfaceField,
    BucketQueryResult,
)
from track_surface.surface_field import SurfaceField, SurfaceFieldConfig

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────

_SCHEMA_VERSION: Final[int] = 1
_MIN_OBS_PER_CELL_DEFAULT: Final[int] = 3
_DIVERGENCE_SIGMAS_DEFAULT: Final[float] = 3.0
_TRACK_LENGTH_TOL_M_DEFAULT: Final[float] = 50.0


# ── Identity ─────────────────────────────────────────────────


@dataclass(frozen=True)
class TrackFingerprint:
    """Stable identity for a track layout.

    Used to gate cross-session merges. Two sessions on the same track
    (but slightly different lap-length measurements) should still match
    via the length tolerance in is_compatible().
    """
    name: str                    # e.g. "Daytona Road Course"
    layout: str                  # e.g. "2011_road"
    length_m: float              # measured centerline length

    @property
    def key(self) -> str:
        """Filesystem-safe key string."""
        safe_name = self.name.replace(" ", "_").replace("/", "-")
        safe_layout = self.layout.replace(" ", "_").replace("/", "-")
        return f"{safe_name}__{safe_layout}__{int(round(self.length_m))}"

    def is_compatible(
        self,
        other: "TrackFingerprint",
        length_tol_m: float = _TRACK_LENGTH_TOL_M_DEFAULT,
    ) -> tuple[bool, str]:
        """Returns (compatible, reason). Reason is empty if compatible."""
        if self.name != other.name:
            return False, f"name mismatch: {self.name!r} vs {other.name!r}"
        if self.layout != other.layout:
            return False, f"layout mismatch: {self.layout!r} vs {other.layout!r}"
        if abs(self.length_m - other.length_m) > length_tol_m:
            return False, (
                f"track length differs by {abs(self.length_m - other.length_m):.1f}m "
                f"(tolerance {length_tol_m}m)"
            )
        return True, ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AccumulatorKey:
    """The unique identity of one accumulator.

    Two BucketedSurfaceFields can only merge into the same accumulator
    if their AccumulatorKeys are equal.
    """
    track_fingerprint: TrackFingerprint
    calibration_profile_id: str

    @property
    def key(self) -> str:
        return f"{self.track_fingerprint.key}__{self.calibration_profile_id}"


@dataclass(frozen=True)
class SessionFingerprint:
    """Identifies one session's contribution to the accumulator.

    Used both as merge-guard input and as a provenance record.
    """
    session_id: str
    track_fingerprint: TrackFingerprint
    calibration_profile_id: str
    n_valid_samples: int
    fit_date: str = ""           # ISO-8601


# ── Merge bookkeeping ────────────────────────────────────────


@dataclass
class SessionContribution:
    """Successful merge record."""
    session_id: str
    accepted_at: str             # ISO-8601
    n_observations_added: int    # total cells*observations contributed
    bucket_breakdown: dict[str, int]  # bucket_key string → cells contributed
    rejected_buckets: list[str] = field(default_factory=list)  # divergence-rejected
    rejected_cells: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MergeRejection:
    """Record of a session that was NOT merged."""
    session_id: str
    rejected_at: str
    reason: str                   # short tag
    details: str                  # human-readable explanation

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AccumulatedQueryResult:
    """One layered query result with full provenance."""
    mean: float
    std: float
    confidence: float
    n_observations: int
    n_sessions_contributing: int
    bucket_used: BucketKey
    fallback_depth: int          # 0 exact, 1 section-merged, 2 prior
    evidence_source: str         # "current_exact" | "accumulated_exact" |
                                 # "current_section" | "accumulated_section" | "prior"
    contributing_sessions: list[str] = field(default_factory=list)


# ── Accumulator ──────────────────────────────────────────────


@dataclass
class AccumulatorConfig:
    """Tuning knobs for the merge logic."""
    min_obs_per_cell: int = _MIN_OBS_PER_CELL_DEFAULT
    divergence_sigmas: float = _DIVERGENCE_SIGMAS_DEFAULT
    track_length_tol_m: float = _TRACK_LENGTH_TOL_M_DEFAULT
    field_config: SurfaceFieldConfig | None = None


class CrossSessionAccumulator:
    """One persistent accumulator for one (track, calibration) combo.

    Maintains an internal BucketedSurfaceField (using the same data
    structure as live sessions) plus per-cell session attribution.
    """

    def __init__(
        self,
        accumulator_key: AccumulatorKey,
        s_bins: np.ndarray,
        n_bins: np.ndarray,
        config: AccumulatorConfig | None = None,
    ) -> None:
        self.key = accumulator_key
        self.s_bins = np.asarray(s_bins, dtype=np.float64)
        self.n_bins = np.asarray(n_bins, dtype=np.float64)
        self.config = config or AccumulatorConfig()
        self.field_config = self.config.field_config or SurfaceFieldConfig()

        # The actual evidence — one SurfaceField per active bucket.
        # We do not use BucketedSurfaceField directly because we need
        # custom Kalman merge semantics, not the per-sample update path.
        self._fields: dict[BucketKey, SurfaceField] = {
            bk: SurfaceField(self.s_bins, self.n_bins, self.field_config)
            for bk in ACTIVE_BUCKETS
        }

        # Per-cell session attribution: dict[bucket_key_str] -> dict[(si,ni) tuple] -> set[session_id]
        # Stored sparsely to keep memory low.
        self._cell_sessions: dict[str, dict[tuple[int, int], set[str]]] = {
            str(bk): {} for bk in ACTIVE_BUCKETS
        }

        # Provenance log
        self.contributions: list[SessionContribution] = []
        self.rejections: list[MergeRejection] = []

    # ── Compatibility check ──────────────────────────────────

    def can_accept(self, session: SessionFingerprint) -> tuple[bool, str]:
        """Pure check: can this session merge into this accumulator?

        Returns (acceptable, reason) — reason is empty when acceptable.
        Does NOT mutate state. Use add_session() to actually merge.
        """
        # Track fingerprint
        ok, reason = self.key.track_fingerprint.is_compatible(
            session.track_fingerprint, length_tol_m=self.config.track_length_tol_m,
        )
        if not ok:
            return False, f"track_geometry_mismatch: {reason}"

        # Calibration profile
        if self.key.calibration_profile_id != session.calibration_profile_id:
            return False, (
                f"calibration_profile_mismatch: accumulator uses "
                f"{self.key.calibration_profile_id!r}, session uses "
                f"{session.calibration_profile_id!r}"
            )

        # Sample-quality lower bound
        if session.n_valid_samples < 1000:
            return False, (
                f"low_quality_session: only {session.n_valid_samples} valid samples"
            )

        return True, ""

    # ── Merge ────────────────────────────────────────────────

    def add_session(
        self,
        session: SessionFingerprint,
        bucketed: BucketedSurfaceField,
    ) -> SessionContribution | MergeRejection:
        """Merge a session's bucketed field into this accumulator.

        Returns either a SessionContribution (successful merge) or a
        MergeRejection (entire session rejected). Per-bucket divergence
        rejection is recorded INSIDE the SessionContribution — it does
        not reject the whole session.
        """
        accept, reason = self.can_accept(session)
        if not accept:
            rej = MergeRejection(
                session_id=session.session_id,
                rejected_at=_now_iso(),
                reason=reason.split(":", 1)[0],
                details=reason,
            )
            self.rejections.append(rej)
            return rej

        # Validate grid shape
        if not (
            np.array_equal(bucketed.s_bins, self.s_bins)
            and np.array_equal(bucketed.n_bins, self.n_bins)
        ):
            rej = MergeRejection(
                session_id=session.session_id,
                rejected_at=_now_iso(),
                reason="grid_mismatch",
                details=(
                    f"session grid {bucketed.mean_grid_shape if hasattr(bucketed, 'mean_grid_shape') else (len(bucketed.s_bins)-1, len(bucketed.n_bins)-1)} "
                    f"!= accumulator grid {(len(self.s_bins)-1, len(self.n_bins)-1)}"
                ),
            )
            self.rejections.append(rej)
            return rej

        rejected_buckets: list[str] = []
        rejected_cells_total = 0
        bucket_breakdown: dict[str, int] = {}
        n_obs_added_total = 0

        for bk in ACTIVE_BUCKETS:
            # Skip TRANSITION_BUCKET — never accumulates
            if bk == TRANSITION_BUCKET:
                continue
            if bk not in bucketed.fields:
                continue

            session_field = bucketed.fields[bk]
            acc_field = self._fields[bk]

            # Find cells that have new evidence
            new_obs_mask = session_field.n_obs >= self.config.min_obs_per_cell
            if not new_obs_mask.any():
                continue

            # Per-bucket divergence check: compare the OBSERVED cells'
            # mean lambda against the accumulator's existing observed mean.
            # Reject the bucket from this session if global divergence is large.
            session_observed_mean = float(
                session_field.mean[new_obs_mask].mean()
            )
            acc_observed_mask = acc_field.n_obs > 0
            if acc_observed_mask.any():
                acc_observed_mean = float(acc_field.mean[acc_observed_mask].mean())
                # Use accumulator-wide std as the divergence yardstick.
                # If accumulator std is tiny, we still tolerate moderate offsets;
                # use a floor of 0.05 to avoid divide-by-zero.
                acc_std = max(float(np.sqrt(acc_field.variance[acc_observed_mask].mean())), 0.05)
                divergence = abs(session_observed_mean - acc_observed_mean) / acc_std
                if divergence > self.config.divergence_sigmas:
                    rejected_buckets.append(str(bk))
                    rejected_cells_total += int(new_obs_mask.sum())
                    logger.warning(
                        "Divergence rejection: session %s bucket %s mean %.3f vs "
                        "accumulator mean %.3f (%.1fσ)",
                        session.session_id, bk, session_observed_mean,
                        acc_observed_mean, divergence,
                    )
                    continue

            # Bayesian Kalman merge per cell: precision-weighted combination
            n_cells_added = self._merge_field(
                acc_field=acc_field,
                session_field=session_field,
                cell_mask=new_obs_mask,
            )

            # Track per-cell session attribution (sparse)
            si_arr, ni_arr = np.where(new_obs_mask)
            cell_dict = self._cell_sessions[str(bk)]
            for si, ni in zip(si_arr, ni_arr):
                cell_dict.setdefault((int(si), int(ni)), set()).add(session.session_id)

            bucket_breakdown[str(bk)] = n_cells_added
            n_obs_added_total += int(session_field.n_obs[new_obs_mask].sum())

        contrib = SessionContribution(
            session_id=session.session_id,
            accepted_at=_now_iso(),
            n_observations_added=n_obs_added_total,
            bucket_breakdown=bucket_breakdown,
            rejected_buckets=rejected_buckets,
            rejected_cells=rejected_cells_total,
        )
        self.contributions.append(contrib)
        return contrib

    def _merge_field(
        self,
        *,
        acc_field: SurfaceField,
        session_field: SurfaceField,
        cell_mask: np.ndarray,
    ) -> int:
        """Bayesian merge of a session SurfaceField into the accumulator.

        For each cell where the session has new evidence:

            1/var_combined = 1/var_acc + 1/var_session
            mean_combined = var_combined * (mean_acc/var_acc + mean_session/var_session)
            n_obs_combined = n_obs_acc + n_obs_session
            total_confidence_combined = total_confidence_acc + total_confidence_session

        Cells that the session didn't observe are left untouched.
        """
        # Precision-weighted combination
        eps = 1e-9
        var_acc = np.maximum(acc_field.variance, eps)
        var_sess = np.maximum(session_field.variance, eps)

        combined_var = 1.0 / (1.0 / var_acc + 1.0 / var_sess)
        combined_mean = combined_var * (
            acc_field.mean / var_acc + session_field.mean / var_sess
        )

        # Apply only on the masked cells
        acc_field.mean[cell_mask] = combined_mean[cell_mask]
        acc_field.variance[cell_mask] = combined_var[cell_mask]
        acc_field.n_obs[cell_mask] = acc_field.n_obs[cell_mask] + session_field.n_obs[cell_mask]
        acc_field.total_confidence[cell_mask] = (
            acc_field.total_confidence[cell_mask] + session_field.total_confidence[cell_mask]
        )

        return int(cell_mask.sum())

    # ── Query ────────────────────────────────────────────────

    def query(
        self,
        s: float, n: float, bucket: BucketKey,
        min_confidence_for_exact: float = 0.05,
    ) -> BucketQueryResult:
        """Query the accumulator (no current-session blending).

        Mirrors BucketedSurfaceField.query() so the same downstream
        consumers can use it. The min_confidence_for_exact threshold
        defaults to 0.05 — same as BucketedSurfaceField — so accumulator
        and live-session queries qualify by the same bar.

        Use layered_query() for the combined current+accumulated path.
        """
        # Transition is never accumulated
        if bucket == TRANSITION_BUCKET:
            return BucketQueryResult(
                mean=self.field_config.prior_mean,
                std=self.field_config.prior_std,
                confidence=0.0,
                bucket_used=BucketKey("global", "prior"),
                fallback_depth=2,
                evidence_count=0,
            )

        # Level 0: exact bucket
        if bucket in self._fields:
            f = self._fields[bucket]
            mean, std, conf = f.query(s, n)
            si, ni = f._cell_index(s, n)
            n_obs = int(f.n_obs[si, ni])
            if conf >= min_confidence_for_exact and n_obs > 0:
                return BucketQueryResult(
                    mean=mean, std=std, confidence=conf,
                    bucket_used=bucket, fallback_depth=0,
                    evidence_count=n_obs,
                )

        # Level 1: same section, any phase
        section_fields = [
            self._fields[k] for k in ACTIVE_BUCKETS
            if k.section_regime == bucket.section_regime and k in self._fields
        ]
        if section_fields:
            means, stds, confs, n_obss = [], [], [], []
            for f in section_fields:
                m, st, c = f.query(s, n)
                si, ni = f._cell_index(s, n)
                means.append(m); stds.append(st); confs.append(c)
                n_obss.append(int(f.n_obs[si, ni]))
            confs_arr = np.array(confs)
            if confs_arr.sum() > min_confidence_for_exact:
                w = confs_arr / max(confs_arr.sum(), 1e-9)
                merged_mean = float(np.sum(np.array(means) * w))
                merged_std = float(np.sqrt(np.sum(np.array(stds) ** 2 * w)))
                merged_conf = float(confs_arr.max() * 0.8)
                return BucketQueryResult(
                    mean=merged_mean, std=merged_std, confidence=merged_conf,
                    bucket_used=BucketKey(bucket.section_regime, "merged"),
                    fallback_depth=1, evidence_count=sum(n_obss),
                )

        return BucketQueryResult(
            mean=self.field_config.prior_mean,
            std=self.field_config.prior_std,
            confidence=0.0,
            bucket_used=BucketKey("global", "prior"),
            fallback_depth=2, evidence_count=0,
        )

    def cell_sessions(self, bucket: BucketKey, s: float, n: float) -> list[str]:
        """Return the session_ids that contributed to this cell."""
        if bucket == TRANSITION_BUCKET or bucket not in self._fields:
            return []
        f = self._fields[bucket]
        si, ni = f._cell_index(s, n)
        s_set = self._cell_sessions[str(bucket)].get((si, ni), set())
        return sorted(s_set)

    # ── Diagnostics ──────────────────────────────────────────

    def diagnostics(self) -> dict[str, Any]:
        """Detailed diagnostics for inspection."""
        per_bucket: dict[str, dict] = {}
        for bk in ACTIVE_BUCKETS:
            f = self._fields[bk]
            observed = f.n_obs > 0
            per_bucket[str(bk)] = {
                "cells_observed": int(observed.sum()),
                "cells_total": int(f.M * f.K),
                "mean_lambda_observed": (
                    round(float(f.mean[observed].mean()), 4) if observed.any() else None
                ),
                "mean_confidence_observed": (
                    round(float(f.confidence_map[observed].mean()), 4)
                    if observed.any() else None
                ),
                "max_observations_per_cell": int(f.n_obs.max()),
                "n_sessions_in_bucket": len({
                    sid
                    for sset in self._cell_sessions[str(bk)].values()
                    for sid in sset
                }),
            }
        return {
            "accumulator_key": self.key.key,
            "track_fingerprint": self.key.track_fingerprint.to_dict(),
            "calibration_profile_id": self.key.calibration_profile_id,
            "grid_shape": [len(self.s_bins) - 1, len(self.n_bins) - 1],
            "n_contributions": len(self.contributions),
            "n_rejections": len(self.rejections),
            "rejection_reasons": _count_by(
                [r.reason for r in self.rejections]
            ),
            "per_bucket": per_bucket,
            "contributing_sessions": [c.session_id for c in self.contributions],
        }

    # ── Persistence ──────────────────────────────────────────

    def save(self, dir_path: Path | str) -> tuple[Path, Path]:
        """Save to {dir}/{key}.npz + {dir}/{key}.json sidecar."""
        d = Path(dir_path)
        d.mkdir(parents=True, exist_ok=True)
        npz_path = d / f"{self.key.key}.npz"
        json_path = d / f"{self.key.key}.json"

        # Pack arrays
        npz_data: dict[str, np.ndarray] = {
            "s_bins": self.s_bins,
            "n_bins": self.n_bins,
        }
        for bk in ACTIVE_BUCKETS:
            f = self._fields[bk]
            tag = _bucket_tag(bk)
            npz_data[f"{tag}__mean"] = f.mean
            npz_data[f"{tag}__variance"] = f.variance
            npz_data[f"{tag}__n_obs"] = f.n_obs
            npz_data[f"{tag}__total_confidence"] = f.total_confidence
        np.savez_compressed(npz_path, **npz_data)

        # Pack JSON sidecar
        cell_sessions_serialized: dict[str, list] = {}
        for bk_str, cell_dict in self._cell_sessions.items():
            cell_sessions_serialized[bk_str] = [
                {"si": si, "ni": ni, "sessions": sorted(sids)}
                for (si, ni), sids in cell_dict.items()
            ]

        sidecar = {
            "schema_version": _SCHEMA_VERSION,
            "saved_at": _now_iso(),
            "key": self.key.key,
            "track_fingerprint": self.key.track_fingerprint.to_dict(),
            "calibration_profile_id": self.key.calibration_profile_id,
            "config": {
                "min_obs_per_cell": self.config.min_obs_per_cell,
                "divergence_sigmas": self.config.divergence_sigmas,
                "track_length_tol_m": self.config.track_length_tol_m,
            },
            "field_config": {
                "prior_mean": self.field_config.prior_mean,
                "prior_std": self.field_config.prior_std,
                "min_confidence": self.field_config.min_confidence,
            },
            "contributions": [c.to_dict() for c in self.contributions],
            "rejections": [r.to_dict() for r in self.rejections],
            "cell_sessions": cell_sessions_serialized,
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(sidecar, f, indent=2)

        return npz_path, json_path

    @classmethod
    def load(
        cls,
        dir_path: Path | str,
        accumulator_key_str: str,
    ) -> "CrossSessionAccumulator":
        d = Path(dir_path)
        npz_path = d / f"{accumulator_key_str}.npz"
        json_path = d / f"{accumulator_key_str}.json"
        if not npz_path.is_file():
            raise FileNotFoundError(f"Accumulator npz missing: {npz_path}")
        if not json_path.is_file():
            raise FileNotFoundError(f"Accumulator sidecar missing: {json_path}")

        with open(json_path, "r", encoding="utf-8") as f:
            sidecar = json.load(f)
        if sidecar.get("schema_version") != _SCHEMA_VERSION:
            raise ValueError(
                f"Accumulator schema version {sidecar.get('schema_version')} "
                f"unsupported (expected {_SCHEMA_VERSION})"
            )

        npz = np.load(npz_path)
        s_bins = npz["s_bins"]
        n_bins = npz["n_bins"]

        tf_d = sidecar["track_fingerprint"]
        tf = TrackFingerprint(
            name=tf_d["name"], layout=tf_d["layout"], length_m=float(tf_d["length_m"]),
        )
        ak = AccumulatorKey(
            track_fingerprint=tf,
            calibration_profile_id=sidecar["calibration_profile_id"],
        )
        cfg = AccumulatorConfig(
            min_obs_per_cell=int(sidecar["config"]["min_obs_per_cell"]),
            divergence_sigmas=float(sidecar["config"]["divergence_sigmas"]),
            track_length_tol_m=float(sidecar["config"]["track_length_tol_m"]),
            field_config=SurfaceFieldConfig(
                prior_mean=float(sidecar["field_config"]["prior_mean"]),
                prior_std=float(sidecar["field_config"]["prior_std"]),
                min_confidence=float(sidecar["field_config"]["min_confidence"]),
            ),
        )

        acc = cls(ak, s_bins, n_bins, cfg)

        # Restore field arrays
        for bk in ACTIVE_BUCKETS:
            tag = _bucket_tag(bk)
            f = acc._fields[bk]
            f.mean = np.array(npz[f"{tag}__mean"])
            f.variance = np.array(npz[f"{tag}__variance"])
            f.n_obs = np.array(npz[f"{tag}__n_obs"])
            f.total_confidence = np.array(npz[f"{tag}__total_confidence"])

        # Restore contributions / rejections / cell_sessions
        acc.contributions = [
            SessionContribution(
                session_id=c["session_id"],
                accepted_at=c["accepted_at"],
                n_observations_added=int(c["n_observations_added"]),
                bucket_breakdown=dict(c["bucket_breakdown"]),
                rejected_buckets=list(c.get("rejected_buckets", [])),
                rejected_cells=int(c.get("rejected_cells", 0)),
            )
            for c in sidecar.get("contributions", [])
        ]
        acc.rejections = [
            MergeRejection(
                session_id=r["session_id"],
                rejected_at=r["rejected_at"],
                reason=r["reason"],
                details=r["details"],
            )
            for r in sidecar.get("rejections", [])
        ]
        for bk_str, entries in sidecar.get("cell_sessions", {}).items():
            target = acc._cell_sessions.setdefault(bk_str, {})
            for entry in entries:
                target[(int(entry["si"]), int(entry["ni"]))] = set(entry["sessions"])

        return acc


# ── Layered query (current beats accumulated when strong) ───


def layered_query(
    *,
    s: float,
    n: float,
    bucket: BucketKey,
    current: BucketedSurfaceField | None,
    accumulator: CrossSessionAccumulator | None,
    confidence_threshold_current: float = 0.05,
    confidence_threshold_accumulated: float = 0.05,
    current_strong_override: float = 0.20,
) -> AccumulatedQueryResult:
    """Combined query: current beats accumulated when strong, accumulated
    fills the gaps otherwise.

    Resolution order (each step short-circuits if confidence threshold met):
      1. current_exact:        current bucket, conf >= threshold_current
                              (matches BucketedSurfaceField default 0.05)
      2. accumulated_exact:    accumulator bucket, conf >= threshold_accumulated
      3. current_section:      current section-merged
      4. accumulated_section:  accumulator section-merged
      5. prior:                global prior

    "Augment, not erase" rule: thresholds are aligned so the layered
    query NEVER returns deeper fallback than a direct current-only query
    would. The accumulator only ever IMPROVES (lowers) the fallback depth.

    "Strong current beats accumulated" rule: when the current cell is
    strongly observed (conf >= current_strong_override), we use it even
    if the accumulator has more sessions for that cell. This protects
    the live signal from being washed out by historical data.
    """
    contributing: list[str] = []

    # 1. Current exact
    if current is not None and bucket != TRANSITION_BUCKET:
        cq = current.query(
            s, n, bucket,
            min_confidence_for_exact=confidence_threshold_current,
        )
        if cq.fallback_depth == 0 and cq.confidence >= confidence_threshold_current:
            # Strong-current override: when current is well-observed, use it
            # even if accumulator might have more.
            if cq.confidence >= current_strong_override:
                return AccumulatedQueryResult(
                    mean=cq.mean, std=cq.std, confidence=cq.confidence,
                    n_observations=cq.evidence_count,
                    n_sessions_contributing=1,
                    bucket_used=cq.bucket_used,
                    fallback_depth=0,
                    evidence_source="current_exact",
                    contributing_sessions=["<current>"],
                )
            # Weaker-but-valid current: prefer accumulator IF it has more
            # confidence at this exact cell, else still use current.
            if accumulator is not None:
                aq = accumulator.query(
                    s, n, bucket,
                    min_confidence_for_exact=confidence_threshold_accumulated,
                )
                if aq.fallback_depth == 0 and aq.confidence > cq.confidence:
                    sessions = accumulator.cell_sessions(bucket, s, n)
                    return AccumulatedQueryResult(
                        mean=aq.mean, std=aq.std, confidence=aq.confidence,
                        n_observations=aq.evidence_count,
                        n_sessions_contributing=len(sessions),
                        bucket_used=aq.bucket_used,
                        fallback_depth=0,
                        evidence_source="accumulated_exact",
                        contributing_sessions=sessions,
                    )
            return AccumulatedQueryResult(
                mean=cq.mean, std=cq.std, confidence=cq.confidence,
                n_observations=cq.evidence_count,
                n_sessions_contributing=1,
                bucket_used=cq.bucket_used,
                fallback_depth=0,
                evidence_source="current_exact",
                contributing_sessions=["<current>"],
            )

    # 2. Accumulated exact (current was depth>0 or absent)
    if accumulator is not None and bucket != TRANSITION_BUCKET:
        aq = accumulator.query(
            s, n, bucket,
            min_confidence_for_exact=confidence_threshold_accumulated,
        )
        if aq.fallback_depth == 0 and aq.confidence >= confidence_threshold_accumulated:
            sessions = accumulator.cell_sessions(bucket, s, n)
            return AccumulatedQueryResult(
                mean=aq.mean, std=aq.std, confidence=aq.confidence,
                n_observations=aq.evidence_count,
                n_sessions_contributing=len(sessions),
                bucket_used=aq.bucket_used,
                fallback_depth=0,
                evidence_source="accumulated_exact",
                contributing_sessions=sessions,
            )

    # 3. Current section
    if current is not None and bucket != TRANSITION_BUCKET:
        cq = current.query(
            s, n, bucket,
            min_confidence_for_exact=confidence_threshold_current,
        )
        if cq.fallback_depth == 1:
            return AccumulatedQueryResult(
                mean=cq.mean, std=cq.std, confidence=cq.confidence,
                n_observations=cq.evidence_count,
                n_sessions_contributing=1,
                bucket_used=cq.bucket_used,
                fallback_depth=1,
                evidence_source="current_section",
                contributing_sessions=["<current>"],
            )

    # 4. Accumulated section
    if accumulator is not None and bucket != TRANSITION_BUCKET:
        aq = accumulator.query(
            s, n, bucket,
            min_confidence_for_exact=confidence_threshold_accumulated,
        )
        if aq.fallback_depth == 1:
            return AccumulatedQueryResult(
                mean=aq.mean, std=aq.std, confidence=aq.confidence,
                n_observations=aq.evidence_count,
                n_sessions_contributing=0,  # not tracked per-cell for section
                bucket_used=aq.bucket_used,
                fallback_depth=1,
                evidence_source="accumulated_section",
                contributing_sessions=[],
            )

    # 5. Prior
    fc = (accumulator.field_config if accumulator is not None
          else (current.field_config if current is not None else SurfaceFieldConfig()))
    return AccumulatedQueryResult(
        mean=fc.prior_mean, std=fc.prior_std, confidence=0.0,
        n_observations=0,
        n_sessions_contributing=0,
        bucket_used=BucketKey("global", "prior"),
        fallback_depth=2,
        evidence_source="prior",
        contributing_sessions=contributing,
    )


# ── Accumulator manager (collection of accumulators) ────────


class AccumulatorRegistry:
    """A directory of accumulators, one per (track, calibration_profile).

    Lookup by AccumulatorKey. Lazy-loaded from disk on demand.
    """

    def __init__(self, base_dir: Path | str) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, CrossSessionAccumulator] = {}

    def get_or_create(
        self,
        key: AccumulatorKey,
        s_bins: np.ndarray,
        n_bins: np.ndarray,
        config: AccumulatorConfig | None = None,
    ) -> CrossSessionAccumulator:
        """Load existing accumulator if present, else create a new empty one."""
        if key.key in self._cache:
            return self._cache[key.key]

        npz_path = self.base_dir / f"{key.key}.npz"
        if npz_path.is_file():
            acc = CrossSessionAccumulator.load(self.base_dir, key.key)
        else:
            acc = CrossSessionAccumulator(key, s_bins, n_bins, config)
        self._cache[key.key] = acc
        return acc

    def get_existing(self, key: AccumulatorKey) -> CrossSessionAccumulator | None:
        """Load if exists, else return None. Does NOT create."""
        if key.key in self._cache:
            return self._cache[key.key]
        npz_path = self.base_dir / f"{key.key}.npz"
        if not npz_path.is_file():
            return None
        acc = CrossSessionAccumulator.load(self.base_dir, key.key)
        self._cache[key.key] = acc
        return acc

    def save(self, acc: CrossSessionAccumulator) -> None:
        acc.save(self.base_dir)

    def list_keys(self) -> list[str]:
        return sorted(p.stem for p in self.base_dir.glob("*.npz"))


# ── Helpers ──────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _bucket_tag(bk: BucketKey) -> str:
    """Filesystem-safe tag for a bucket key (used as npz field prefix)."""
    return f"{bk.section_regime}_{bk.stint_phase}"


def _count_by(items: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for it in items:
        out[it] = out.get(it, 0) + 1
    return out
