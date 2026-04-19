"""Train worker -- incrementally trains the neural surrogate model.

Uses :class:`NeuralTrainer` from ``neural/trainer.py``.  Skips
training if PyTorch is not available or if there are fewer than 10
solutions in the data lake.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from telemetry_tool.lap_oracle.config import OracleConfig
from telemetry_tool.lap_oracle.data_lake import DataLake
from telemetry_tool.lap_oracle.neural.surrogate import HAS_TORCH
from telemetry_tool.lap_oracle.workers.base import BaseWorker

logger = logging.getLogger(__name__)

# Minimum number of solutions before training starts
_MIN_SOLUTIONS = 10


class TrainWorker(BaseWorker):
    """Trains the neural surrogate model on accumulated solutions.

    Skips if PyTorch is not installed or if the data lake contains
    fewer than :data:`_MIN_SOLUTIONS` solved combos.
    """

    worker_type: str = "train"

    def __init__(
        self,
        worker_id: str,
        lake: DataLake,
        config: OracleConfig,
    ) -> None:
        super().__init__(worker_id, lake, config)
        self._trainer = None
        self._initialized = False

    def _ensure_trainer(self) -> bool:
        """Lazily initialize the trainer.  Returns True if ready."""
        if not HAS_TORCH:
            return False

        if not self.config.enable_neural_training:
            return False

        if self._trainer is not None:
            return True

        from telemetry_tool.lap_oracle.neural.trainer import NeuralTrainer

        self._trainer = NeuralTrainer(
            data_dir=self.lake.data_dir,
            config=self.config,
        )

        # Try to load existing checkpoint
        ckpt = self.lake.data_dir / "models" / "oracle_latest.pt"
        if ckpt.exists():
            self._trainer.load_checkpoint(ckpt)

        self._initialized = True
        return True

    def tick(self) -> bool:
        """Train one epoch if enough data is available.

        Returns True if training was performed.
        """
        if not self._ensure_trainer():
            return False

        assert self._trainer is not None

        # Check solution count
        n_solutions = self.lake.count_solutions()
        if n_solutions < _MIN_SOLUTIONS:
            logger.debug(
                "Not enough solutions for training: %d < %d",
                n_solutions, _MIN_SOLUTIONS,
            )
            return False

        # Reload data periodically to pick up new solutions
        self._trainer.reload_data()

        if len(self._trainer.dataset) < _MIN_SOLUTIONS:
            return False

        # Train one epoch
        loss = self._trainer.train_epoch()
        if loss is None:
            return False

        # Log progress
        self.lake.log_progress(
            "train",
            neural_loss=loss,
            details={
                "epoch": self._trainer.epoch,
                "samples": len(self._trainer.dataset),
            },
        )

        # Checkpoint if enough time has passed
        if self._trainer.should_checkpoint:
            ckpt_path = self.lake.data_dir / "models" / "oracle_latest.pt"
            self._trainer.checkpoint(ckpt_path)

        return True
