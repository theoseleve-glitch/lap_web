"""Base class and registry for handling balance detectors."""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path

from telemetry_tool.handling.types import CornerWindow, DetectorVote, SessionContext

log = logging.getLogger(__name__)

_MIN_CONFIDENCE = 0.05  # votes below this are discarded

_DEFAULT_PROFILE_PATH = Path(__file__).resolve().parent.parent / "calibration_profiles.json"


class HandlingDetector(ABC):
    """Abstract base for a single over/understeer detector."""

    name: str = "unnamed"
    default_weight: float = 1.0

    @abstractmethod
    def detect(self, corner: CornerWindow, ctx: SessionContext) -> DetectorVote:
        """Return a vote for this corner.

        Return DetectorVote with confidence=0 to abstain.
        """
        ...

    def get_cal(self, ctx: SessionContext, key: str, default=None):
        """Look up a calibration value from the profile for this vehicle class.

        Searches ctx.calibration_profile[detector_name][key].
        Falls back to *default* if the profile or key is missing.
        """
        det_cal = ctx.calibration_profile.get(self.name)
        if det_cal is None:
            return default
        return det_cal.get(key, default)


class DetectorRegistry:
    """Runs a collection of detectors and collects their votes."""

    _calibration_profiles: dict = {}

    def __init__(self, detectors: list[HandlingDetector] | None = None):
        self.detectors: list[HandlingDetector] = list(detectors) if detectors else []
        if not DetectorRegistry._calibration_profiles:
            DetectorRegistry.load_calibration()

    def register(self, detector: HandlingDetector) -> None:
        """Add a detector to the registry."""
        self.detectors.append(detector)

    @classmethod
    def load_calibration(cls, path: str | None = None) -> dict:
        """Load calibration profiles from JSON. Auto-discovers default path.

        Returns the loaded profiles dict (also stored on the class).
        If the file doesn't exist, returns empty dict and detectors
        fall back to their hardcoded defaults.
        """
        profile_path = Path(path) if path else _DEFAULT_PROFILE_PATH
        if profile_path.is_file():
            try:
                with open(profile_path, "r", encoding="utf-8") as f:
                    cls._calibration_profiles = json.load(f)
                log.info("Loaded calibration profiles from %s", profile_path)
            except Exception:
                log.warning("Failed to load calibration profiles from %s",
                            profile_path, exc_info=True)
                cls._calibration_profiles = {}
        else:
            log.debug("No calibration file at %s, using hardcoded defaults",
                       profile_path)
            cls._calibration_profiles = {}
        return cls._calibration_profiles

    def get_profile_for(self, vehicle_class: str) -> dict:
        """Return the calibration profile dict for a vehicle class."""
        return dict(self._calibration_profiles.get(vehicle_class, {}))

    def run_all(
        self, corner: CornerWindow, ctx: SessionContext
    ) -> list[DetectorVote]:
        """Run all detectors, return votes with confidence > threshold."""
        # Inject calibration profile into ctx if not already set
        if not ctx.calibration_profile:
            ctx.calibration_profile = self.get_profile_for(ctx.vehicle_class)

        votes: list[DetectorVote] = []
        for det in self.detectors:
            try:
                vote = det.detect(corner, ctx)
                if vote.confidence > _MIN_CONFIDENCE:
                    votes.append(vote)
            except Exception:
                log.warning(
                    "Detector %s failed on corner %d", det.name, corner.corner_id,
                    exc_info=True,
                )
        return votes
