"""
Compact int8-quantised binary encoding for animated grip frames.

Produces a base64 string suitable for inlining directly in the HTML
visualization. The JS decoder dequantizes on-demand per frame lookup so
the 3.7 MB of float32 frame data never materialises in the browser.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Final

import numpy as np


@dataclass
class EncodedAnimation:
    base64_payload: str
    shape_f: int
    shape_m: int
    shape_k: int
    mu_min: float
    mu_scale: float       # step size in μ units (mu_max - mu_min) / 255
    lap_numbers: list[int]
    lap_times_s: list[float]

    def to_export_dict(self) -> dict:
        """JSON-serialisable dict for embedding in track-surface data."""
        return {
            "format": "u8-flat-c-order",
            "shape_f": self.shape_f,
            "shape_m": self.shape_m,
            "shape_k": self.shape_k,
            "mu_min": round(self.mu_min, 4),
            "mu_scale": round(self.mu_scale, 5),
            "lap_numbers": list(self.lap_numbers),
            "lap_times_s": [round(float(v), 3) for v in self.lap_times_s],
            "base64_payload": self.base64_payload,
        }


def encode_frames(
    frames: np.ndarray,          # (F, M, K) float32
    lap_numbers: list[int],
    lap_times_s: list[float],
    mu_range: tuple[float, float] = (0.0, 2.55),
) -> EncodedAnimation:
    """Int8 quantise [mu_min, mu_max] -> 0..255, then base64.

    Size budget example: F=74, M=500, K=25 ⇒ 925 kB raw ⇒ ~1.24 MB base64.

    NaN values (propagated empty cells) are stored as mu_min (0.0 by default).
    Frontend legend should treat very low values as "no data".
    """
    if frames.ndim != 3:
        raise ValueError(f"Expected 3D frames, got shape {frames.shape}")

    F, M, K = frames.shape
    mu_min, mu_max = mu_range
    if mu_max <= mu_min:
        raise ValueError("mu_max must be > mu_min")
    mu_scale = (mu_max - mu_min) / 255.0

    # Fill NaN with mu_min (will render as "no data" color)
    clean = np.where(np.isfinite(frames), frames, mu_min)
    # Clip to valid range
    clean = np.clip(clean, mu_min, mu_max)
    # Quantise
    q = np.round((clean - mu_min) / mu_scale).astype(np.uint8)

    # C-order flattened bytes
    payload_bytes = q.tobytes()
    b64 = base64.b64encode(payload_bytes).decode("ascii")

    return EncodedAnimation(
        base64_payload=b64,
        shape_f=F,
        shape_m=M,
        shape_k=K,
        mu_min=mu_min,
        mu_scale=mu_scale,
        lap_numbers=list(lap_numbers),
        lap_times_s=[float(v) for v in lap_times_s],
    )
