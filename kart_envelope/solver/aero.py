"""
aero.py
-------
Aero runtime model (drag/downforce) with conservative defaults.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from kart_envelope.config import KartEnvelopeConfig
from kart_envelope.ingest.metadata import SessionMetadata

_G = 9.80665


@dataclass
class AeroRuntime:
    """Compact aero model for online solver usage."""

    enabled_drag: bool = False
    enabled_downforce: bool = False
    air_density_kg_m3: float = 1.20
    cda: float = 0.80
    cl: float = 0.0
    source: str = "config_default"
    confidence: float = 0.5

    def drag_accel(self, speed_mps: float, mass_kg: float) -> float:
        """Aerodynamic drag contribution in m/s^2."""
        if not self.enabled_drag:
            return 0.0
        m = max(float(mass_kg), 40.0)
        v = max(float(speed_mps), 0.0)
        f_drag = 0.5 * float(self.air_density_kg_m3) * float(self.cda) * v * v
        return float(np.clip(f_drag / m, 0.0, 9.0))

    def downforce_load_factor(self, speed_mps: float, mass_kg: float) -> float:
        """
        Return multiplicative tire-load factor from downforce.

        Uses 1 + F_down / (m*g), capped conservatively.
        """
        if not self.enabled_downforce:
            return 1.0
        m = max(float(mass_kg), 40.0)
        v = max(float(speed_mps), 0.0)
        f_down = 0.5 * float(self.air_density_kg_m3) * max(float(self.cl), 0.0) * v * v
        lf = 1.0 + f_down / (m * _G)
        return float(np.clip(lf, 1.0, 1.20))

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled_drag": bool(self.enabled_drag),
            "enabled_downforce": bool(self.enabled_downforce),
            "air_density_kg_m3": round(float(self.air_density_kg_m3), 4),
            "cda": round(float(self.cda), 4),
            "cl": round(float(self.cl), 4),
            "source": self.source,
            "confidence": round(float(self.confidence), 4),
        }


def build_aero_runtime(
    metadata: SessionMetadata | None,
    config: KartEnvelopeConfig,
    *,
    condition_label: str = "",
) -> AeroRuntime:
    """Build aero runtime from metadata + config with condition-adjusted density."""
    enabled_drag = bool(config.aero_enable_drag)
    enabled_downforce = bool(config.aero_enable_downforce)
    base_rho = float(np.clip(config.aero_air_density_kg_m3, 0.9, 1.5))

    cda = float(np.clip(config.aero_default_cda, 0.1, 2.5))
    cl = float(np.clip(config.aero_default_cl, -0.5, 2.5))
    source = "config_default"
    conf = 0.40
    if metadata is not None:
        if metadata.aero_cda is not None:
            cda = float(np.clip(metadata.aero_cda, 0.1, 2.5))
            source = "metadata"
            conf = 0.75
        if metadata.aero_cl is not None:
            cl = float(np.clip(metadata.aero_cl, -0.5, 2.5))
            source = "metadata"
            conf = max(conf, 0.70)

    # Condition proxy for density (temperature/humidity unavailable).
    cond = str(condition_label or (metadata.condition_label if metadata is not None else "") or "").lower()
    rho_scale = 1.0
    if "wet" in cond:
        rho_scale = 1.02
    elif "damp" in cond:
        rho_scale = 1.01
    elif "dry" in cond:
        rho_scale = 0.99

    return AeroRuntime(
        enabled_drag=enabled_drag,
        enabled_downforce=enabled_downforce,
        air_density_kg_m3=float(np.clip(base_rho * rho_scale, 0.9, 1.5)),
        cda=cda,
        cl=cl,
        source=source,
        confidence=conf,
    )

