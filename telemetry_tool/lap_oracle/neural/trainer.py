"""Neural surrogate trainer -- manages training loop and checkpoints.

Uses :class:`LapOracle` from ``surrogate.py`` and :class:`OracleDataset``
from ``dataset.py``.  Training is incremental: new solutions can be
picked up by calling :meth:`reload_data`.

Requires PyTorch; all methods are no-ops if unavailable.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

import numpy as np

from telemetry_tool.lap_oracle.config import OracleConfig
from telemetry_tool.lap_oracle.neural.surrogate import HAS_TORCH

logger = logging.getLogger(__name__)

if HAS_TORCH:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader

    from telemetry_tool.lap_oracle.neural.dataset import OracleDataset
    from telemetry_tool.lap_oracle.neural.surrogate import LapOracle


class NeuralTrainer:
    """Manages training of the :class:`LapOracle` neural surrogate.

    Parameters
    ----------
    data_dir : Path
        Root oracle data directory.
    config : OracleConfig
        Oracle runtime configuration.
    """

    def __init__(
        self,
        data_dir: Path,
        config: Optional[OracleConfig] = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.config = config or OracleConfig()
        self.epoch = 0
        self.last_loss: Optional[float] = None

        if not HAS_TORCH:
            logger.warning("PyTorch not available -- NeuralTrainer disabled")
            self.model = None
            return

        self.model = LapOracle()
        self.optimizer = torch.optim.Adam(
            self.model.parameters(),
            lr=self.config.neural_lr,
        )
        self.scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
            self.optimizer, T_max=1000, eta_min=1e-6,
        )
        self.dataset = OracleDataset(self.data_dir)
        self._last_checkpoint = time.time()

    def train_epoch(self) -> Optional[float]:
        """Run one training epoch over the dataset.

        Returns the mean loss, or ``None`` if torch is unavailable or
        the dataset is empty.
        """
        if not HAS_TORCH or self.model is None:
            return None

        if len(self.dataset) == 0:
            return None

        loader = DataLoader(
            self.dataset,
            batch_size=min(self.config.neural_batch_size, len(self.dataset)),
            shuffle=True,
            drop_last=False,
        )

        self.model.train()
        total_loss = 0.0
        n_batches = 0

        for batch in loader:
            car, track, setup, weather, targets = batch
            self.optimizer.zero_grad()

            preds = self.model(car, track, setup, weather)

            # Multi-target loss
            loss = nn.functional.mse_loss(
                preds["lap_time"], targets["lap_time"],
            )
            loss = loss + 0.5 * nn.functional.mse_loss(
                preds["sectors"], targets["sectors"],
            )
            loss = loss + 0.1 * nn.functional.mse_loss(
                preds["speed_profile"], targets["speed_profile"],
            )

            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
            self.optimizer.step()

            total_loss += loss.item()
            n_batches += 1

        self.scheduler.step()
        self.epoch += 1

        mean_loss = total_loss / max(n_batches, 1)
        self.last_loss = mean_loss
        logger.info(
            "Epoch %d: loss=%.6f (lr=%.2e, %d samples)",
            self.epoch, mean_loss,
            self.scheduler.get_last_lr()[0],
            len(self.dataset),
        )
        return mean_loss

    def checkpoint(self, path: Path) -> None:
        """Save model state dict and training metadata."""
        if not HAS_TORCH or self.model is None:
            return
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "model_state_dict": self.model.state_dict(),
                "optimizer_state_dict": self.optimizer.state_dict(),
                "scheduler_state_dict": self.scheduler.state_dict(),
                "epoch": self.epoch,
                "last_loss": self.last_loss,
            },
            str(path),
        )
        self._last_checkpoint = time.time()
        logger.info("Checkpoint saved: %s (epoch %d)", path, self.epoch)

    def load_checkpoint(self, path: Path) -> bool:
        """Restore model from a checkpoint.  Returns True on success."""
        if not HAS_TORCH or self.model is None:
            return False
        path = Path(path)
        if not path.exists():
            logger.warning("Checkpoint not found: %s", path)
            return False
        data = torch.load(str(path), map_location="cpu", weights_only=True)
        self.model.load_state_dict(data["model_state_dict"])
        self.optimizer.load_state_dict(data["optimizer_state_dict"])
        self.scheduler.load_state_dict(data["scheduler_state_dict"])
        self.epoch = data.get("epoch", 0)
        self.last_loss = data.get("last_loss")
        logger.info("Loaded checkpoint: %s (epoch %d)", path, self.epoch)
        return True

    def reload_data(self) -> int:
        """Re-scan the solutions directory for new data.

        Returns the new sample count.
        """
        if not HAS_TORCH:
            return 0
        self.dataset._scan()
        return len(self.dataset)

    @property
    def should_checkpoint(self) -> bool:
        """True if enough time has passed since the last checkpoint."""
        interval = self.config.neural_checkpoint_minutes * 60
        return (time.time() - self._last_checkpoint) >= interval
