"""Admin audit logging and security event helpers.

All functions take a connection as first arg and INSERT into the
appropriate table.  They never commit — callers decide transaction scope.
"""
from __future__ import annotations

import copy
import json
import logging

logger = logging.getLogger(__name__)

# Fields stripped from Stripe payloads before storage (PCI compliance).
_SENSITIVE_OBJECT_KEYS = {"card", "bank_account", "source"}


def log_admin_action(
    conn,
    admin_user_id: int,
    action: str,
    *,
    target_type: str | None = None,
    target_id: str | None = None,
    reason: str | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
    request_id: str | None = None,
) -> None:
    """INSERT into admin_audit_log."""
    details_json = json.dumps(details) if details else None
    conn.execute(
        "INSERT INTO admin_audit_log "
        "(admin_user_id, action, target_type, target_id, reason, "
        "details_json, ip_address, request_id) "
        "VALUES (%(admin_user_id)s, %(action)s, %(target_type)s, "
        "%(target_id)s, %(reason)s, %(details_json)s, %(ip_address)s, "
        "%(request_id)s)",
        {
            "admin_user_id": admin_user_id,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "reason": reason,
            "details_json": details_json,
            "ip_address": ip_address,
            "request_id": request_id,
        },
    )


def log_security_event(
    conn,
    event_type: str,
    *,
    user_id: int | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    details: dict | None = None,
    severity: str = "info",
) -> None:
    """INSERT into security_events."""
    details_json = json.dumps(details) if details else None
    conn.execute(
        "INSERT INTO security_events "
        "(event_type, user_id, ip_address, user_agent, details_json, severity) "
        "VALUES (%(event_type)s, %(user_id)s, %(ip_address)s, "
        "%(user_agent)s, %(details_json)s, %(severity)s)",
        {
            "event_type": event_type,
            "user_id": user_id,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "details_json": details_json,
            "severity": severity,
        },
    )


def log_stripe_webhook(
    conn,
    stripe_event_id: str,
    event_type: str,
    payload: dict,
    signature_valid: bool,
    processing_status: str = "pending",
    error_message: str | None = None,
) -> None:
    """INSERT into stripe_webhook_log with sanitized payload."""
    sanitized = _sanitize_payload(payload)
    conn.execute(
        "INSERT INTO stripe_webhook_log "
        "(stripe_event_id, event_type, payload_json, signature_valid, "
        "processing_status, error_message) "
        "VALUES (%(stripe_event_id)s, %(event_type)s, %(payload_json)s, "
        "%(signature_valid)s, %(processing_status)s, %(error_message)s)",
        {
            "stripe_event_id": stripe_event_id,
            "event_type": event_type,
            "payload_json": json.dumps(sanitized),
            "signature_valid": signature_valid,
            "processing_status": processing_status,
            "error_message": error_message,
        },
    )


def _sanitize_payload(payload: dict) -> dict:
    """Remove PCI-sensitive fields from a Stripe webhook payload.

    Strips: card, bank_account, source from data.object,
    and billing_details from data.object.payment_method.
    """
    result = copy.deepcopy(payload)
    obj = result.get("data", {}).get("object", {})
    if not obj:
        return result

    for key in _SENSITIVE_OBJECT_KEYS:
        obj.pop(key, None)

    pm = obj.get("payment_method")
    if isinstance(pm, dict):
        pm.pop("billing_details", None)

    return result
