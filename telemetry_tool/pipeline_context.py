"""Per-job pipeline context backed by Redis metadata + temp-dir DataFrames.

Each pipeline job gets:
- A Redis key ``pipeline:ctx:{job_id}`` storing JSON metadata (workspace_id,
  session_id, file_path, stage info, errors, joker_decision).
- A temp directory ``{temp_root}/pipeline/{job_id}/`` where intermediate
  DataFrames are persisted as Parquet files.

Usage::

    ctx = PipelineContext.create(redis, "job-1", "ws-1", "sess-1", "/data/f.csv")
    ctx.update_stage("gps_filter", "running")
    ctx.save_dataframe("gps_filtered", df)
    ctx.save()

    # Later (e.g. in another Celery task):
    ctx = PipelineContext.load(redis, "job-1")
    df = ctx.load_dataframe("gps_filtered")
    ctx.cleanup()
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import pandas as pd

# Default temp root — overridable via create()/load() parameters.
_DEFAULT_TEMP_ROOT = "/tmp"

# Redis key TTL for pipeline context (2 hours).
_CONTEXT_TTL_SECONDS = 7200


def _redis_key(job_id: str) -> str:
    return f"pipeline:ctx:{job_id}"


@dataclass
class PipelineContext:
    """Manages per-job state across pipeline stages.

    Attributes
    ----------
    job_id : str
        Unique job identifier.
    workspace_id : str
        Workspace that owns this job.
    session_id : str
        Telemetry session being processed.
    file_path : str
        Path to the source CSV file.
    current_stage : str | None
        Name of the stage currently executing.
    stage_status : str | None
        Status of the current stage (e.g. "running", "completed", "failed").
    errors : list[dict]
        Accumulated errors across stages.
    joker_decision : str | None
        Optional joker/strategy decision for the pipeline run.
    temp_dir : Path
        Directory for intermediate Parquet files.
    redis_client : Any
        Redis connection used for metadata persistence.
    """

    job_id: str
    workspace_id: str
    session_id: str
    file_path: str
    current_stage: Optional[str] = None
    stage_status: Optional[str] = None
    errors: list = field(default_factory=list)
    joker_decision: Optional[str] = None
    selected_corner_ids: Optional[list] = None
    custom_corners: Optional[list] = None
    temp_dir: Path = field(default_factory=lambda: Path(_DEFAULT_TEMP_ROOT))
    redis_client: Any = field(default=None, repr=False)

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        redis_client,
        job_id: str,
        workspace_id: str,
        session_id: str,
        file_path: str,
        temp_root: str = _DEFAULT_TEMP_ROOT,
    ) -> "PipelineContext":
        """Create a new pipeline context, persist to Redis, and set up temp dir.

        Parameters
        ----------
        redis_client :
            Redis connection (or mock).
        job_id : str
            Unique identifier for this pipeline run.
        workspace_id, session_id, file_path :
            Job metadata.
        temp_root : str
            Root directory under which ``pipeline/{job_id}/`` will be created.

        Returns
        -------
        PipelineContext
        """
        temp_dir = Path(temp_root) / "pipeline" / job_id
        temp_dir.mkdir(parents=True, exist_ok=True)

        ctx = cls(
            job_id=job_id,
            workspace_id=workspace_id,
            session_id=session_id,
            file_path=file_path,
            temp_dir=temp_dir,
            redis_client=redis_client,
        )
        ctx.save()
        return ctx

    @classmethod
    def load(
        cls,
        redis_client,
        job_id: str,
        temp_root: str = _DEFAULT_TEMP_ROOT,
    ) -> Optional["PipelineContext"]:
        """Load an existing pipeline context from Redis.

        Returns ``None`` if the key does not exist.
        """
        raw = redis_client.get(_redis_key(job_id))
        if raw is None:
            return None

        data = json.loads(raw)
        temp_dir = Path(temp_root) / "pipeline" / job_id
        temp_dir.mkdir(parents=True, exist_ok=True)

        return cls(
            job_id=job_id,
            workspace_id=data["workspace_id"],
            session_id=data["session_id"],
            file_path=data["file_path"],
            current_stage=data.get("current_stage"),
            stage_status=data.get("stage_status"),
            errors=data.get("errors", []),
            joker_decision=data.get("joker_decision"),
            selected_corner_ids=data.get("selected_corner_ids"),
            custom_corners=data.get("custom_corners"),
            temp_dir=temp_dir,
            redis_client=redis_client,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _to_dict(self) -> dict:
        """Serialize context metadata to a JSON-safe dict."""
        return {
            "workspace_id": self.workspace_id,
            "session_id": self.session_id,
            "file_path": self.file_path,
            "current_stage": self.current_stage,
            "stage_status": self.stage_status,
            "errors": self.errors,
            "joker_decision": self.joker_decision,
            "selected_corner_ids": self.selected_corner_ids,
            "custom_corners": self.custom_corners,
        }

    def save(self) -> None:
        """Write metadata to Redis with a 2-hour TTL."""
        payload = json.dumps(self._to_dict())
        self.redis_client.set(
            _redis_key(self.job_id), payload, ex=_CONTEXT_TTL_SECONDS
        )

    # ------------------------------------------------------------------
    # Stage tracking
    # ------------------------------------------------------------------

    def update_stage(self, stage_name: str, status: str) -> None:
        """Record current pipeline stage and its status."""
        self.current_stage = stage_name
        self.stage_status = status

    def add_error(self, stage: str, message: str) -> None:
        """Append an error entry for the given stage."""
        self.errors.append({"stage": stage, "message": message})

    def set_joker_decision(self, decision: str) -> None:
        """Set the joker/strategy decision for this run."""
        self.joker_decision = decision

    def set_selected_corner_ids(self, corner_ids: list) -> None:
        """Set the user-selected corner IDs for analysis."""
        self.selected_corner_ids = corner_ids

    def set_custom_corners(self, corners: list) -> None:
        """Set user-defined corner geometry for analysis."""
        self.custom_corners = corners

    # ------------------------------------------------------------------
    # DataFrame I/O (temp dir)
    # ------------------------------------------------------------------

    def save_dataframe(self, name: str, df: pd.DataFrame) -> Path:
        """Write a DataFrame as Parquet to the job temp dir.

        Parameters
        ----------
        name : str
            Logical name for this intermediate result (e.g. "gps_filtered").
        df : pd.DataFrame
            Data to persist.

        Returns
        -------
        Path
            Path to the written Parquet file.
        """
        path = self.temp_dir / f"{name}.parquet"
        df.to_parquet(path, index=False)
        return path

    def load_dataframe(self, name: str) -> Optional[pd.DataFrame]:
        """Read a previously saved DataFrame from the temp dir.

        Returns ``None`` if the file does not exist.
        """
        path = self.temp_dir / f"{name}.parquet"
        if not path.exists():
            return None
        return pd.read_parquet(path)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup(self) -> None:
        """Remove temp directory and Redis key for this job."""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
        self.redis_client.delete(_redis_key(self.job_id))
