"""Data classification system for privacy and access control.

Classifies all data domains into sensitivity levels:
- PUBLIC: Anonymized/aggregate data safe for public exposure
- INTERNAL: Business data requiring authentication
- CONFIDENTIAL: Personal/financial data with restricted access
- RESTRICTED: Credentials, tokens, secrets — never exposed in APIs

Used by audit middleware, export filters, and GDPR compliance.
"""
from __future__ import annotations

from enum import Enum
from typing import Any


class DataLevel(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


# Classification registry: table/field → sensitivity level
_CLASSIFICATIONS: dict[str, DataLevel] = {
    # ── RESTRICTED (credentials, secrets) ──
    "users.password_hash": DataLevel.RESTRICTED,
    "users.totp_secret": DataLevel.RESTRICTED,
    "refresh_tokens.token_hash": DataLevel.RESTRICTED,
    "password_reset_tokens.token_hash": DataLevel.RESTRICTED,
    "oauth_connections.access_token": DataLevel.RESTRICTED,
    "oauth_connections.refresh_token": DataLevel.RESTRICTED,

    # ── CONFIDENTIAL (PII, financial) ──
    "users.email": DataLevel.CONFIDENTIAL,
    "users.display_name": DataLevel.CONFIDENTIAL,
    "users.created_at": DataLevel.CONFIDENTIAL,
    "stripe_customers.*": DataLevel.CONFIDENTIAL,
    "stripe_webhook_log.*": DataLevel.CONFIDENTIAL,
    "audit_log.*": DataLevel.CONFIDENTIAL,
    "gdpr_requests.*": DataLevel.CONFIDENTIAL,
    "email_log.*": DataLevel.CONFIDENTIAL,

    # ── INTERNAL (business data, requires auth) ──
    "sessions.*": DataLevel.INTERNAL,
    "laps.*": DataLevel.INTERNAL,
    "score_details.*": DataLevel.INTERNAL,
    "corner_metrics.*": DataLevel.INTERNAL,
    "workspaces.*": DataLevel.INTERNAL,
    "teams.*": DataLevel.INTERNAL,
    "drivers.*": DataLevel.INTERNAL,
    "ingestion_jobs.*": DataLevel.INTERNAL,

    # ── PUBLIC (safe for aggregates/anonymous) ──
    "tracks.*": DataLevel.PUBLIC,
    "predefined_tracks.*": DataLevel.PUBLIC,
    "predefined_karts.*": DataLevel.PUBLIC,
}


def classify(table: str, field: str | None = None) -> DataLevel:
    """Return the data classification level for a table or table.field.

    Checks specific field first, then wildcard table match, defaults to INTERNAL.
    """
    if field:
        specific = f"{table}.{field}"
        if specific in _CLASSIFICATIONS:
            return _CLASSIFICATIONS[specific]

    wildcard = f"{table}.*"
    if wildcard in _CLASSIFICATIONS:
        return _CLASSIFICATIONS[wildcard]

    # Default to INTERNAL — require auth for unclassified data
    return DataLevel.INTERNAL


def get_restricted_fields(table: str) -> list[str]:
    """Return field names classified as RESTRICTED for a given table."""
    prefix = f"{table}."
    return [
        key.split(".", 1)[1]
        for key, level in _CLASSIFICATIONS.items()
        if key.startswith(prefix) and level == DataLevel.RESTRICTED
    ]


def get_classification_report() -> dict[str, list[str]]:
    """Return all classifications grouped by level (for audit)."""
    report: dict[str, list[str]] = {level.value: [] for level in DataLevel}
    for key, level in sorted(_CLASSIFICATIONS.items()):
        report[level.value].append(key)
    return report


def is_exportable(table: str, field: str | None = None) -> bool:
    """Check if data can be included in user-facing exports (not RESTRICTED)."""
    return classify(table, field) != DataLevel.RESTRICTED
