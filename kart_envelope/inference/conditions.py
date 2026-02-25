"""
conditions.py
-------------
Classify track conditions from inferred session scalars.
"""
from __future__ import annotations

import logging

from kart_envelope.inference.session_scalars import SessionScalars

logger = logging.getLogger(__name__)


def classify_conditions(scalars: SessionScalars) -> str:
    """Infer a condition label from session scalars.

    Returns
    -------
    str
        One of: ``"wet"``, ``"damp"``, ``"greasy"``, ``"dry"``,
        ``"low_power"``, ``"nominal"``.
    """
    mu = scalars.mu_session
    p = scalars.p_session

    if mu < 0.65:
        label = "wet"
    elif mu < 0.78:
        label = "damp"
    elif mu < 0.88:
        label = "greasy"
    elif p <= 0.85:
        label = "low_power"
    else:
        label = "dry"

    logger.info("Condition classification: %s (μ=%.3f, P=%.3f).", label, mu, p)
    return label
