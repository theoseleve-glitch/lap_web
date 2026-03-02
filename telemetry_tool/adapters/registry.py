"""Adapter registry: format detection pipeline and file parsing entry point.

Maintains a list of registered adapter classes.  ``detect_format()`` runs
each adapter's ``detect()`` method and returns the best match above a
minimum confidence threshold.  ``parse_file()`` combines detection and
parsing into a single call.

Usage
-----
::

    from telemetry_tool.adapters.registry import register_adapter, parse_file
    from telemetry_tool.adapters.racechrono_adapter import RaceChronoAdapter

    register_adapter(RaceChronoAdapter)
    df, adapter = parse_file("session.csv")
"""

from __future__ import annotations

import logging
from typing import Optional, Type

import pandas as pd

from telemetry_tool.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global registry
# ---------------------------------------------------------------------------
_ADAPTERS: list[Type[BaseAdapter]] = []

#: Minimum confidence required to accept a format match.
_MIN_CONFIDENCE: float = 0.5


def register_adapter(cls: Type[BaseAdapter]) -> None:
    """Add *cls* to the adapter registry.

    Duplicate registrations are silently ignored.
    """
    if cls in _ADAPTERS:
        logger.debug("Adapter %s already registered; skipping.", cls.FORMAT_NAME)
        return
    _ADAPTERS.append(cls)
    logger.debug("Registered adapter: %s", cls.FORMAT_NAME)


def detect_format(
    file_path: str,
) -> tuple[Type[BaseAdapter] | None, float]:
    """Run all registered adapters' ``detect()`` and return the best match.

    Parameters
    ----------
    file_path:
        Path to the telemetry file to probe.

    Returns
    -------
    (adapter_class, confidence)
        The adapter class with the highest confidence score, or
        ``(None, 0.0)`` if no adapter exceeds ``_MIN_CONFIDENCE``.
    """
    best_cls: Type[BaseAdapter] | None = None
    best_conf: float = 0.0

    for cls in _ADAPTERS:
        try:
            conf = cls.detect(file_path)
        except Exception:
            logger.debug(
                "Adapter %s raised during detect() for %s; skipping.",
                cls.FORMAT_NAME,
                file_path,
                exc_info=True,
            )
            conf = 0.0

        if conf > best_conf:
            best_conf = conf
            best_cls = cls

    if best_conf < _MIN_CONFIDENCE:
        logger.debug(
            "No adapter matched %s above threshold %.2f (best: %.2f from %s).",
            file_path,
            _MIN_CONFIDENCE,
            best_conf,
            best_cls.FORMAT_NAME if best_cls else "none",
        )
        return None, best_conf

    logger.info(
        "Format detected: %s (confidence=%.2f) for %s",
        best_cls.FORMAT_NAME if best_cls else "unknown",
        best_conf,
        file_path,
    )
    return best_cls, best_conf


def parse_file(
    file_path: str,
    progress_cb: Optional[object] = None,
) -> tuple[pd.DataFrame, BaseAdapter]:
    """Detect the format of *file_path*, parse it, and return both the
    DataFrame and the adapter instance.

    Parameters
    ----------
    file_path:
        Path to the telemetry file.
    progress_cb:
        Optional progress callback forwarded to the adapter's ``parse()``.

    Returns
    -------
    (DataFrame, adapter_instance)

    Raises
    ------
    ValueError
        If no registered adapter matches *file_path* above the confidence
        threshold.
    """
    cls, confidence = detect_format(file_path)
    if cls is None:
        raise ValueError(
            f"No adapter matched file '{file_path}'. "
            f"Registered adapters: "
            f"{[a.FORMAT_NAME for a in _ADAPTERS] or '(none)'}."
        )

    adapter = cls()
    df = adapter.parse(file_path, progress_cb=progress_cb)
    return df, adapter
