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
from pathlib import Path
from typing import Iterator, Optional, Type

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


# ---------------------------------------------------------------------------
# Extension helpers & two-pass detection
# ---------------------------------------------------------------------------


def supported_extensions() -> set[str]:
    """Collect all file extensions recognised by registered adapters.

    Returns
    -------
    set[str]
        Lowercased extensions including the leading dot, e.g. ``{".csv", ".vbo"}``.
    """
    exts: set[str] = set()
    for cls in _ADAPTERS:
        for ext in cls.EXTENSIONS:
            exts.add(ext.lower())
    return exts


def detect_format_two_pass(
    file_path: str,
) -> tuple[Type[BaseAdapter] | None, float]:
    """Two-pass format detection: extension filter first, then full scan.

    **Pass 1** — Only run ``detect()`` on adapters whose ``EXTENSIONS``
    list contains the file's suffix.  If a match above ``_MIN_CONFIDENCE``
    is found, return immediately.

    **Pass 2** — Fall back to running *all* registered adapters (same
    behaviour as ``detect_format()``).

    Parameters
    ----------
    file_path:
        Path to the telemetry file.

    Returns
    -------
    (adapter_class, confidence)
        Best match, or ``(None, 0.0)`` if nothing exceeds
        ``_MIN_CONFIDENCE`` even after both passes.
    """
    suffix = Path(file_path).suffix.lower()

    # --- Pass 1: extension-filtered ---
    ext_candidates = [
        cls for cls in _ADAPTERS
        if suffix in [e.lower() for e in cls.EXTENSIONS]
    ]

    if ext_candidates:
        best_cls, best_conf = _run_detection(ext_candidates, file_path)
        if best_conf >= _MIN_CONFIDENCE:
            logger.info(
                "Two-pass (ext): %s matched %s (confidence=%.2f)",
                best_cls.FORMAT_NAME if best_cls else "unknown",
                file_path,
                best_conf,
            )
            return best_cls, best_conf

    # --- Pass 2: all adapters ---
    best_cls, best_conf = _run_detection(_ADAPTERS, file_path)
    if best_conf >= _MIN_CONFIDENCE:
        logger.info(
            "Two-pass (full): %s matched %s (confidence=%.2f)",
            best_cls.FORMAT_NAME if best_cls else "unknown",
            file_path,
            best_conf,
        )
    else:
        logger.debug(
            "Two-pass: no adapter matched %s above threshold %.2f.",
            file_path,
            _MIN_CONFIDENCE,
        )
    return best_cls, best_conf


def stream_file(
    file_path: str,
    *,
    config: Optional[object] = None,
    progress_cb: Optional[object] = None,
) -> Iterator[pd.DataFrame]:
    """Detect format and stream the file as chunked DataFrames.

    Uses ``detect_format_two_pass()`` for detection, then delegates to
    the winning adapter's ``stream()`` method.

    Parameters
    ----------
    file_path:
        Path to the telemetry file.
    config:
        Optional ingestion configuration forwarded to the adapter.
    progress_cb:
        Optional progress callback forwarded to the adapter.

    Yields
    ------
    pd.DataFrame
        One chunk at a time.

    Raises
    ------
    ValueError
        If no adapter matches the file.
    """
    cls, confidence = detect_format_two_pass(file_path)
    if cls is None:
        raise ValueError(
            f"No adapter matched file '{file_path}'. "
            f"Registered adapters: "
            f"{[a.FORMAT_NAME for a in _ADAPTERS] or '(none)'}."
        )

    adapter = cls()
    yield from adapter.stream(file_path, config=config, progress_cb=progress_cb)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _run_detection(
    candidates: list[Type[BaseAdapter]],
    file_path: str,
) -> tuple[Type[BaseAdapter] | None, float]:
    """Run ``detect()`` on *candidates* and return the best match."""
    best_cls: Type[BaseAdapter] | None = None
    best_conf: float = 0.0

    for cls in candidates:
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

    return best_cls, best_conf
