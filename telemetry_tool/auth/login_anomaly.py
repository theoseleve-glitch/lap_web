"""Login anomaly detection for account takeover prevention.

Detects:
- New IP address for a user (first-time login from an IP)
- High-velocity logins (multiple IPs in short window)
- Password spray patterns (many failed logins across different users from same IP)

Requires Redis. Fails open if Redis is unavailable.
"""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Detection thresholds
NEW_IP_HISTORY_DAYS = 90
VELOCITY_WINDOW_SECONDS = 3600  # 1 hour
VELOCITY_MAX_IPS = 5  # Max distinct IPs per user in window
SPRAY_WINDOW_SECONDS = 300  # 5 minutes
SPRAY_MAX_USERS = 10  # Max distinct users failing from same IP


def _get_redis():
    try:
        from flask import current_app, g
        r = getattr(g, "_redis", None)
        if r is not None:
            return r
        return current_app.extensions.get("redis")
    except Exception:
        return None


def check_login_anomalies(
    user_id: int,
    ip_address: str,
    user_agent: str = "",
) -> list[dict[str, Any]]:
    """Check for suspicious login patterns. Returns list of anomaly dicts.

    Each anomaly has: {"type": str, "severity": "low"|"medium"|"high", "detail": str}
    Returns empty list if no anomalies or Redis unavailable.
    """
    r = _get_redis()
    if r is None:
        return []

    anomalies: list[dict[str, Any]] = []

    try:
        # 1. New IP detection
        known_key = f"login:known_ips:{user_id}"
        is_known = r.sismember(known_key, ip_address)
        if not is_known:
            known_count = r.scard(known_key) or 0
            if known_count > 0:
                # User has logged in before, but not from this IP
                anomalies.append({
                    "type": "new_ip",
                    "severity": "medium",
                    "detail": f"First login from IP {ip_address} (user has {known_count} known IPs)",
                })
            # Record this IP
            r.sadd(known_key, ip_address)
            r.expire(known_key, NEW_IP_HISTORY_DAYS * 86400)

        # 2. High-velocity: many IPs for same user in short window
        velocity_key = f"login:velocity:{user_id}"
        now = time.time()
        r.zadd(velocity_key, {ip_address: now})
        r.zremrangebyscore(velocity_key, 0, now - VELOCITY_WINDOW_SECONDS)
        r.expire(velocity_key, VELOCITY_WINDOW_SECONDS + 60)
        distinct_ips = r.zcard(velocity_key) or 0
        if distinct_ips > VELOCITY_MAX_IPS:
            anomalies.append({
                "type": "high_velocity",
                "severity": "high",
                "detail": f"{distinct_ips} distinct IPs in last hour for user {user_id}",
            })

    except Exception as exc:
        logger.debug("Login anomaly check failed: %s", exc)

    return anomalies


def record_failed_login(ip_address: str, email: str) -> list[dict[str, Any]]:
    """Record a failed login attempt and check for spray patterns.

    Returns anomalies if a password spray is detected from this IP.
    """
    r = _get_redis()
    if r is None:
        return []

    anomalies: list[dict[str, Any]] = []

    try:
        spray_key = f"login:spray:{ip_address}"
        now = time.time()
        r.zadd(spray_key, {email.lower(): now})
        r.zremrangebyscore(spray_key, 0, now - SPRAY_WINDOW_SECONDS)
        r.expire(spray_key, SPRAY_WINDOW_SECONDS + 60)
        distinct_users = r.zcard(spray_key) or 0
        if distinct_users >= SPRAY_MAX_USERS:
            anomalies.append({
                "type": "password_spray",
                "severity": "high",
                "detail": f"{distinct_users} distinct emails failed from IP {ip_address} in {SPRAY_WINDOW_SECONDS}s",
            })
    except Exception as exc:
        logger.debug("Failed login recording error: %s", exc)

    return anomalies
