"""Provenance run context -- builds a ProvenanceRecord for each analysis run.

Captures: unique run ID, input fingerprint, config hash, pipeline/model
versions, and timestamp.  This record is embedded in the analysis summary
and optionally persisted to the ``analysis_provenance`` table.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd

from provenance.fingerprint import compute_data_fingerprint, compute_file_hash


@dataclass
class ProvenanceRecord:
    """Immutable provenance snapshot for a single analysis run."""

    analysis_run_id: str
    input_fingerprint: str
    file_hash: Optional[str]
    params_hash: str
    pipeline_version: str
    model_version: str
    solver_version: Optional[str]
    method_used: str
    generated_at: str
    training_data_hash: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_FROZEN_TIMESTAMP = "2000-01-01T00:00:00+00:00"


def _hash_config(config: Any) -> str:
    """SHA-256 of the JSON-serialised config."""
    payload = json.dumps(config, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_provenance(
    input_df: pd.DataFrame,
    config: Any,
    *,
    method_used: str,
    file_path: Optional[str] = None,
    pipeline_version: Optional[str] = None,
    model_version: Optional[str] = None,
    solver_version: Optional[str] = None,
    training_data_hash: Optional[str] = None,
    deterministic: bool = False,
) -> ProvenanceRecord:
    """Build a ProvenanceRecord for the current analysis run.

    Parameters
    ----------
    deterministic : bool
        When ``True``, the ``analysis_run_id`` is derived from a SHA-256
        hash of the input fingerprint, params hash, and pipeline version,
        and ``generated_at`` is set to a fixed epoch timestamp.  This
        makes outputs reproducible for the same inputs.
    """
    if pipeline_version is None:
        try:
            from pipeline_status import compute_pipeline_version_string

            pipeline_version = compute_pipeline_version_string()
        except ImportError:
            pipeline_version = "unknown"

    if model_version is None:
        try:
            from pipeline_status import get_model_version

            model_version = get_model_version()
        except ImportError:
            model_version = "none"

    input_fingerprint = compute_data_fingerprint(input_df)
    params_hash = _hash_config(config)

    if deterministic:
        seed = f"{input_fingerprint}|{params_hash}|{pipeline_version}"
        analysis_run_id = hashlib.sha256(seed.encode()).hexdigest()[:16]
        generated_at = _FROZEN_TIMESTAMP
    else:
        analysis_run_id = str(uuid.uuid4())
        generated_at = datetime.now(timezone.utc).isoformat()

    return ProvenanceRecord(
        analysis_run_id=analysis_run_id,
        input_fingerprint=input_fingerprint,
        file_hash=compute_file_hash(file_path) if file_path else None,
        params_hash=params_hash,
        pipeline_version=pipeline_version,
        model_version=model_version,
        solver_version=solver_version,
        method_used=method_used,
        generated_at=generated_at,
        training_data_hash=training_data_hash,
    )
