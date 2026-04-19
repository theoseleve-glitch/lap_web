"""Pydantic v2 model for the logger's manifest.json (schema_version=2).

Parsing is intentionally strict at the top level and lenient at metadata
sub-objects — we need to detect structural problems hard, but we want to
accept forward-compatible logger versions that add fields we don't yet know.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


_ALLOWED_ROLES = {"telemetry", "analysis_json", "manifest", "aux"}


class _Strict(BaseModel):
    """Top-level blocks use extra='forbid' to catch manifest drift early."""
    model_config = ConfigDict(extra="forbid")


class _Lenient(BaseModel):
    """Sub-objects like vehicle_spec, track_spec tolerate extra fields so
    forward-compatible logger versions don't break intake."""
    model_config = ConfigDict(extra="allow")


# ── Sub-objects ─────────────────────────────────────────────


class ManifestIdentity(_Strict):
    sim: str
    vehicle_key: str = Field(..., min_length=1, max_length=128)
    track_key: str = Field(..., min_length=1, max_length=128)
    session_type: str = Field(..., min_length=1, max_length=32)
    started_at: datetime

    @field_validator("sim")
    @classmethod
    def sim_lowercase(cls, v: str) -> str:
        return v.strip().lower()


class ManifestSource(_Strict):
    logger_version: str = Field(..., min_length=1, max_length=64)
    logger_build: str | None = None
    capture_method: str = Field(..., min_length=1, max_length=64)
    captured_by_user_id: int | None = None
    captured_at: datetime
    client_hostname: str | None = None
    client_os: str | None = None


class ManifestFileEntry(_Strict):
    path: str = Field(..., min_length=1, max_length=512)
    size: int = Field(..., ge=0)
    sha256: str = Field(..., min_length=64, max_length=64)
    role: Literal["telemetry", "analysis_json", "manifest", "aux"]

    @field_validator("sha256")
    @classmethod
    def lowercase_hex(cls, v: str) -> str:
        v2 = v.strip().lower()
        if not all(c in "0123456789abcdef" for c in v2):
            raise ValueError("sha256 must be lowercase hex")
        return v2


class ManifestMetadata(_Lenient):
    """The logger's declared session metadata. Sub-objects are permissive."""
    vehicle_spec: dict[str, Any] = Field(default_factory=dict)
    track_spec: dict[str, Any] = Field(default_factory=dict)
    session_info: dict[str, Any] = Field(default_factory=dict)
    channels_present: list[str] = Field(default_factory=list)
    lap_count: int = 0
    duration_s: float = 0.0
    extra: dict[str, Any] = Field(default_factory=dict)


# ── Top level ───────────────────────────────────────────────


class ManifestV2(_Strict):
    schema_version: Literal[2]
    identity: ManifestIdentity
    source: ManifestSource
    files: list[ManifestFileEntry] = Field(..., min_length=1)
    metadata: ManifestMetadata

    @field_validator("files")
    @classmethod
    def manifest_file_entry_unique_paths(
        cls, v: list[ManifestFileEntry]
    ) -> list[ManifestFileEntry]:
        paths = [f.path for f in v]
        if len(paths) != len(set(paths)):
            raise ValueError("manifest.files contains duplicate paths")
        return v
