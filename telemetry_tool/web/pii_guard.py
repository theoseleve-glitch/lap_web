# web/pii_guard.py
"""Shared PII guard for behavioral-event ingest.

Single source of truth for the denylist + email/IPv4 stripping + size cap
applied to `properties` JSON across:
  - POST /api/v1/events       (web/routes/events.py)
  - POST /api/v1/marketing-events (web/routes/marketing.py)
  - GDPR export scrubbing     (tasks/gdpr_tasks.py)

`scrub_properties` is deliberately conservative: it returns a *flat* dict of
only string/number/bool scalar values, with denylisted keys and any value
that looks like an email or IPv4 address removed, capped to a byte budget.
"""
from __future__ import annotations

import json
import re
from typing import Any

# Keys that must never be persisted (case-insensitive match).
PII_DENYLIST_KEYS: frozenset[str] = frozenset({
    "email", "ip", "ip_address", "token", "access_token",
    "password", "phone", "ssn",
})

# Conservative email + IPv4 detectors applied to string *values*.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

# Hard cap on the serialized size of a single event's properties.
MAX_PROPERTIES_BYTES = 4096


def _value_is_pii(value: Any) -> bool:
    if isinstance(value, str):
        if _EMAIL_RE.search(value) or _IPV4_RE.search(value):
            return True
    return False


def _is_flat_scalar(value: Any) -> bool:
    # Allow JSON scalars only; drop nested dicts/lists.
    return isinstance(value, (str, int, float, bool)) or value is None


def scrub_properties(props: Any) -> dict[str, Any]:
    """Return a PII-safe, flat, size-capped copy of *props*.

    Non-dict input → ``{}``. Denylisted keys, PII-looking string values, and
    nested containers are dropped. If the result still exceeds
    ``MAX_PROPERTIES_BYTES`` once serialized, keys are dropped (longest value
    first) until it fits.
    """
    if not isinstance(props, dict):
        return {}

    cleaned: dict[str, Any] = {}
    for key, value in props.items():
        if not isinstance(key, str):
            continue
        if key.lower() in PII_DENYLIST_KEYS:
            continue
        if not _is_flat_scalar(value):
            continue
        if _value_is_pii(value):
            continue
        cleaned[key] = value

    # Enforce size cap: drop keys (largest serialized value first) until it fits.
    while cleaned and len(json.dumps(cleaned).encode("utf-8")) > MAX_PROPERTIES_BYTES:
        victim = max(cleaned, key=lambda k: len(json.dumps(cleaned[k])))
        del cleaned[victim]

    return cleaned
