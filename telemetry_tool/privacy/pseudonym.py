"""Privacy-safe pseudonymization for session identifiers.

Generates stable, non-reversible pseudonyms (PIDs) from session/workspace IDs
using HMAC-SHA256. PIDs replace raw session_ids in logs and exports.

Secret management:
    LOG_PSEUDONYM_SECRET       — current HMAC key (required)
    LOG_PSEUDONYM_SECRET_PREV  — previous key for dual-secret rotation grace

The pseudonym is: base64url(HMAC-SHA256(secret, workspace_id:session_id))[:PID_LENGTH]
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re

logger = logging.getLogger(__name__)

# Truncated PID length (characters). 24 base64url chars = 144 bits of entropy.
PID_LENGTH = 24

# Validation: PIDs contain only base64url-safe characters
_PID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Env var names
_SECRET_ENV = "LOG_PSEUDONYM_SECRET"
_SECRET_PREV_ENV = "LOG_PSEUDONYM_SECRET_PREV"


def _get_secrets() -> tuple[str | None, str | None]:
    """Return (current_secret, previous_secret) from environment."""
    current = os.environ.get(_SECRET_ENV)
    previous = os.environ.get(_SECRET_PREV_ENV)
    return current, previous


def _compute_pid(secret: str, workspace_id: int | str, session_id: str) -> str:
    """Compute a pseudonym ID from secret + identifiers.

    Returns a URL-safe, fixed-length string that:
    - Is deterministic for the same inputs
    - Cannot be reversed without the secret
    - Never equals the raw session_id
    """
    message = f"{workspace_id}:{session_id}".encode("utf-8")
    digest = hmac.new(
        secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).digest()
    pid = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return pid[:PID_LENGTH]


def generate_session_pid(
    workspace_id: int | str,
    session_id: str,
    *,
    secret: str | None = None,
) -> str:
    """Generate a privacy-safe pseudonym for a session.

    Args:
        workspace_id: Workspace the session belongs to.
        session_id: Raw session identifier.
        secret: Override secret (for testing). Falls back to env var.

    Returns:
        A stable, non-reversible PID string of length PID_LENGTH.

    Raises:
        ValueError: If no secret is configured.
    """
    if secret is None:
        secret, _ = _get_secrets()
    if not secret:
        raise ValueError(
            f"{_SECRET_ENV} environment variable is required for pseudonymization"
        )

    pid = _compute_pid(secret, workspace_id, session_id)

    # Safety: PID must never equal the raw session_id
    assert pid != session_id, "PID collision with raw session_id"

    return pid


def resolve_session_pid(
    workspace_id: int | str,
    session_id: str,
    *,
    pid_to_match: str | None = None,
) -> str | None:
    """Resolve a PID, checking both current and previous secrets.

    If pid_to_match is provided, returns the PID only if it matches
    against either secret (useful for lookup/validation during rotation).

    If pid_to_match is None, returns the PID using the current secret.

    Returns None if no secret is configured or no match found.
    """
    current, previous = _get_secrets()

    if pid_to_match is None:
        if not current:
            return None
        return _compute_pid(current, workspace_id, session_id)

    # Check current secret
    if current:
        pid = _compute_pid(current, workspace_id, session_id)
        if pid == pid_to_match:
            return pid

    # Check previous secret (rotation grace period)
    if previous:
        pid = _compute_pid(previous, workspace_id, session_id)
        if pid == pid_to_match:
            return pid

    return None


def is_valid_pid(pid: str) -> bool:
    """Check if a string looks like a valid PID (format only, not content)."""
    return (
        isinstance(pid, str)
        and len(pid) == PID_LENGTH
        and bool(_PID_RE.match(pid))
    )


def pseudonymize_for_log(
    workspace_id: int | str,
    session_id: str,
) -> str:
    """Return a PID for logging. Falls back to '<redacted>' if no secret."""
    try:
        return generate_session_pid(workspace_id, session_id)
    except ValueError:
        return "<redacted>"


def pseudonymize_export_manifest(
    manifest: list[dict],
    workspace_id: int | str,
    *,
    secret: str | None = None,
) -> list[dict]:
    """Replace raw session_ids with PIDs in an export manifest.

    Each dict in the manifest must have a 'session_id' key.
    The key is replaced with 'session_pid' and 'session_id' is removed.

    Returns a new list (does not mutate input).
    """
    result = []
    for entry in manifest:
        new_entry = dict(entry)
        raw_sid = new_entry.pop("session_id", None)
        if raw_sid is not None:
            new_entry["session_pid"] = generate_session_pid(
                workspace_id, raw_sid, secret=secret,
            )
        result.append(new_entry)
    return result
