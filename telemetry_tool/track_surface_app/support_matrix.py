"""SupportMatrix — static lookup for (sim, vehicle, track) → max tier.

Seed data lives next to this module at ``data/support_matrix.json``. Frontend
queries ``/support/resolve?sim=...`` against this table BEFORE uploading a
session, so it knows which analysis controls to enable.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from track_surface_app.domain import SupportTier

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SupportMatrixEntry:
    sim: str
    vehicle: str
    track: str
    max_support_tier: SupportTier
    validated_vehicle_profile: str | None = None
    validated_track_profile: str | None = None


def _norm(s: str) -> str:
    return s.strip().lower() if s else ""


class SupportMatrix:
    """Static (sim, vehicle, track) → SupportMatrixEntry lookup."""

    def __init__(self, entries: list[SupportMatrixEntry]):
        self._entries = list(entries)
        self._index: dict[tuple[str, str, str], SupportMatrixEntry] = {
            (_norm(e.sim), _norm(e.vehicle), _norm(e.track)): e for e in entries
        }

    @property
    def entries(self) -> list[SupportMatrixEntry]:
        return list(self._entries)

    def resolve(self, *, sim: str, vehicle: str, track: str) -> SupportMatrixEntry | None:
        return self._index.get((_norm(sim), _norm(vehicle), _norm(track)))

    @classmethod
    def load(cls, path: Path | str) -> "SupportMatrix":
        p = Path(path)
        if not p.is_file():
            logger.warning("Support matrix file not found at %s — using empty", p)
            return cls(entries=[])
        with open(p, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raise ValueError("support_matrix root must be a JSON object")
        version = raw.get("version", 1)
        if version != 1:
            raise ValueError(f"Unsupported support_matrix version: {version}")
        entries_raw = raw.get("entries", [])
        entries: list[SupportMatrixEntry] = []
        for i, e in enumerate(entries_raw):
            try:
                entries.append(SupportMatrixEntry(
                    sim=str(e["sim"]),
                    vehicle=str(e["vehicle"]),
                    track=str(e["track"]),
                    max_support_tier=SupportTier(e["max_support_tier"]),
                    validated_vehicle_profile=e.get("validated_vehicle_profile"),
                    validated_track_profile=e.get("validated_track_profile"),
                ))
            except (KeyError, ValueError) as exc:
                logger.warning("Skipping malformed support matrix entry #%d: %s", i, exc)
        return cls(entries=entries)

    @classmethod
    def load_default(cls) -> "SupportMatrix":
        """Load from the packaged default location (``data/support_matrix.json``)."""
        default_path = Path(__file__).parent / "data" / "support_matrix.json"
        return cls.load(default_path)
