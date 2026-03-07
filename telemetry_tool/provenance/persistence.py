"""Provenance persistence -- dual-write to DB table and summary dict.

Writes to the ``analysis_provenance`` table when available (PG mode).
Falls back gracefully when the table does not exist (SQLite desktop mode
before migration, or when USE_PG=0).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from provenance.run_context import ProvenanceRecord

logger = logging.getLogger(__name__)


def insert_provenance(
    conn: Any,
    record: ProvenanceRecord,
    session_id: Optional[str] = None,
    workspace_id: Optional[int] = None,
) -> None:
    """Insert a provenance record into the analysis_provenance table.

    Uses INSERT OR IGNORE for idempotency (same run_id = skip).
    Silently skips if the table does not exist.
    """
    try:
        conn.execute(
            "INSERT OR IGNORE INTO analysis_provenance "
            "(analysis_run_id, session_id, workspace_id, input_fingerprint, "
            "file_hash, params_hash, pipeline_version, model_version, "
            "solver_version, method_used, training_data_hash, generated_at) "
            "VALUES (:run_id, :sid, :wid, :fp, :fh, :ph, :pv, :mv, :sv, :mu, :tdh, :ga)",
            {
                "run_id": record.analysis_run_id,
                "sid": session_id,
                "wid": workspace_id,
                "fp": record.input_fingerprint,
                "fh": record.file_hash,
                "ph": record.params_hash,
                "pv": record.pipeline_version,
                "mv": record.model_version,
                "sv": record.solver_version,
                "mu": record.method_used,
                "tdh": record.training_data_hash,
                "ga": record.generated_at,
            },
        )
        conn.commit()
    except Exception as exc:
        logger.debug("Provenance insert skipped: %s", exc)


def get_provenance_by_session(
    conn: Any,
    session_id: str,
) -> Optional[dict[str, Any]]:
    """Retrieve the most recent provenance record for a session."""
    try:
        row = conn.execute(
            "SELECT * FROM analysis_provenance "
            "WHERE session_id = :sid ORDER BY created_at DESC LIMIT 1",
            {"sid": session_id},
        ).fetchone()
        if row is None:
            return None
        return dict(row)
    except Exception:
        return None
