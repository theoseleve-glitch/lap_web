"""Neural surrogate model for fast lap-time prediction.

Predicts lap time, sector times, speed profile, and setup sensitivity
from car + track + setup + weather feature vectors.  Uses PyTorch if
available; otherwise the module exports ``HAS_TORCH = False`` and the
model class is not defined.
"""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

# -- Optional PyTorch import -----------------------------------------------
try:
    import torch
    import torch.nn as nn

    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

# -- Feature dimensions ----------------------------------------------------
CAR_DIM = 50
TRACK_DIM = 30
SETUP_DIM = 19
WEATHER_DIM = 10
SPEED_PROFILE_N = 200  # fixed-length resampled speed trace


# -- Model -----------------------------------------------------------------

if HAS_TORCH:

    class LapOracle(nn.Module):
        """Multi-head neural surrogate for lap-time prediction.

        Encoders compress each feature group into a latent vector.
        A shared backbone processes the concatenated latents.  Four
        heads predict different quantities.

        Parameters
        ----------
        speed_n : int
            Length of the speed-profile output vector.
        """

        def __init__(self, speed_n: int = SPEED_PROFILE_N) -> None:
            super().__init__()
            self.speed_n = speed_n

            # -- Encoders --------------------------------------------------
            self.car_enc = nn.Sequential(
                nn.Linear(CAR_DIM, 128), nn.ReLU(),
            )
            self.track_enc = nn.Sequential(
                nn.Linear(TRACK_DIM, 128), nn.ReLU(),
            )
            self.setup_enc = nn.Sequential(
                nn.Linear(SETUP_DIM, 64), nn.ReLU(),
            )
            self.weather_enc = nn.Sequential(
                nn.Linear(WEATHER_DIM, 32), nn.ReLU(),
            )

            # -- Backbone (128+128+64+32 = 352 input) ---------------------
            self.backbone = nn.Sequential(
                nn.Linear(352, 512),
                nn.ReLU(),
                nn.Dropout(0.1),
                nn.Linear(512, 512),
                nn.ReLU(),
                nn.Dropout(0.1),
                nn.Linear(512, 256),
                nn.ReLU(),
            )

            # -- Heads -----------------------------------------------------
            self.head_lap_time = nn.Linear(256, 1)
            self.head_sectors = nn.Linear(256, 3)
            self.head_speed = nn.Linear(256, speed_n)
            self.head_setup_delta = nn.Linear(256, SETUP_DIM)

        def forward(
            self,
            car: torch.Tensor,
            track_feat: torch.Tensor,
            setup: torch.Tensor,
            weather: torch.Tensor,
        ) -> dict[str, torch.Tensor]:
            """Forward pass.

            Parameters
            ----------
            car : Tensor [B, 50]
            track_feat : Tensor [B, 30]
            setup : Tensor [B, 19]
            weather : Tensor [B, 10]

            Returns
            -------
            dict with keys ``lap_time``, ``sectors``, ``speed_profile``,
            ``setup_delta``.
            """
            c = self.car_enc(car)
            t = self.track_enc(track_feat)
            s = self.setup_enc(setup)
            w = self.weather_enc(weather)

            x = torch.cat([c, t, s, w], dim=-1)
            x = self.backbone(x)

            return {
                "lap_time": self.head_lap_time(x),
                "sectors": self.head_sectors(x),
                "speed_profile": self.head_speed(x),
                "setup_delta": self.head_setup_delta(x),
            }
