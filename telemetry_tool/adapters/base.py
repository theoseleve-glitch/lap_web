"""Base adapter interface for telemetry file formats.

Every telemetry source (RaceChrono, iRacing, ACC, MoTeC, AiM, etc.) must
implement this interface.  The adapter is responsible for:

1. **Detecting** whether a given file belongs to this format (confidence 0-1).
2. **Parsing** the file into a canonical ``pd.DataFrame`` whose column names
   match ``channel_registry.CHANNELS``.
3. **Reporting** metadata, available channels, and data tier.

Concrete subclasses MUST override all ``@abstractmethod`` members and set
``FORMAT_NAME`` to a unique, lowercase identifier.
"""

from __future__ import annotations

import abc
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


class BaseAdapter(abc.ABC):
    """Abstract base class for all telemetry format adapters."""

    FORMAT_NAME: str = "unknown"

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @staticmethod
    @abc.abstractmethod
    def detect(file_path: str) -> float:
        """Return confidence 0.0-1.0 that this adapter handles *file_path*.

        Implementations should read at most the first ~100 lines or a small
        header portion to make this determination quickly.  The method must
        never raise; return 0.0 on any I/O error.
        """

    @abc.abstractmethod
    def parse(
        self,
        file_path: str,
        progress_cb: Optional[object] = None,
    ) -> pd.DataFrame:
        """Parse *file_path* into a canonical DataFrame.

        Column names MUST use the canonical names defined in
        ``telemetry_tool.channel_registry``.  Unit conversions (e.g. G to
        m/s^2) are applied during parsing so downstream code never sees
        raw units.

        Parameters
        ----------
        file_path:
            Path to the telemetry file.
        progress_cb:
            Optional progress callback (protocol TBD).

        Returns
        -------
        pd.DataFrame
            Cleaned, canonical DataFrame.
        """

    @abc.abstractmethod
    def metadata(self) -> dict:
        """Return session metadata extracted during parsing.

        Typical keys: ``session``, ``track``, ``driver``, ``vehicle``,
        ``date``, ``comment_0`` ... ``comment_N``.

        Returns an empty dict if ``parse()`` has not been called yet.
        """

    @abc.abstractmethod
    def available_channels(self) -> list[str]:
        """Return canonical channel names present after parsing.

        Returns an empty list if ``parse()`` has not been called yet.
        """

    # ------------------------------------------------------------------
    # Concrete helpers
    # ------------------------------------------------------------------

    def data_tier(self) -> int:
        """Determine the data tier from available channels.

        Uses ``channel_registry.detect_data_tier()`` on the result of
        ``available_channels()``.  Returns 0 if no channels are available.
        """
        from telemetry_tool.channel_registry import detect_data_tier

        channels = self.available_channels()
        if not channels:
            return 0
        return detect_data_tier(channels)
