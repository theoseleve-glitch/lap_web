"""Account lockout — Redis-backed brute-force protection.

After MAX_ATTEMPTS failed logins within WINDOW_SECONDS for a given
(email, IP) pair, that pair is locked for LOCKOUT_SECONDS.  The hard lock
is scoped by IP as well as email: an attacker who only knows a victim's
email address can lock out their OWN IP for that email, but cannot lock
the victim out of a login attempt from the victim's own IP/device.

That IP-scoping deliberately removes the only email-*global* signal, so a
distributed attacker (many IPs, few guesses each) trips no hard lock at
all against one victim email. ``_check_distributed_attack`` below adds a
SOFT, detection-only counterpart: it watches for the same email failing
from many DISTINCT IPs in a short window and raises a security ALERT
(observability only, never a block). A full CAPTCHA/step-up flow driven by
that signal is the fuller follow-up — see the fix report.

Uses the same Redis sorted-set sliding window pattern as the rate limiter.

Fails open to a BOUNDED degraded mode: if Redis is unavailable, a small
in-process, per-worker fixed-window limiter keyed by (email, IP) throttles
attempts instead of letting them through unbounded.  This is intentionally
looser/faster than the real 15-minute/30-minute Redis lockout — it only
needs to bound the brute-force *rate* during an outage, not reproduce the
full lockout policy, and it must not require cross-worker coordination.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict

from web.redis_health import alert_redis_failopen, record_degraded_mode, record_recovery

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 900       # 15 minutes
LOCKOUT_SECONDS = 1800     # 30 minutes

# Degraded-mode (Redis down) fallback — deliberately smaller/faster than
# the real lockout above; see module docstring.
_DEGRADED_MAX_ATTEMPTS = 5
_DEGRADED_WINDOW_SECONDS = 60

_degraded_lock = threading.Lock()
# OrderedDict (not plain dict) so we can LRU-evict: every distinct
# (email, IP) scope key creates an entry, and during a Redis outage an
# attacker sprays either to grow this dict without bound (crash-DoS). Empty
# buckets are popped outright (see _degraded_peek); the dict is additionally
# capped at _DEGRADED_MAX_KEYS, evicting the oldest (least-recently-touched)
# key once exceeded.
_degraded_buckets: "OrderedDict[str, list[float]]" = OrderedDict()
_DEGRADED_MAX_KEYS = 50_000

# Soft, email-scoped DETECTION signal (Fix #2 follow-up) -- see
# _check_distributed_attack. Deliberately separate window/threshold from
# the (email, IP) hard lock's MAX_ATTEMPTS/WINDOW_SECONDS above: this is an
# alert trigger, not a lockout policy.
DISTRIBUTED_ATTACK_WINDOW_SECONDS = 300   # 5 minutes
DISTRIBUTED_ATTACK_IP_THRESHOLD = 5       # >= 5 distinct IPs -> alert


def _get_redis():
    """Return the application's Redis client, or None."""
    try:
        from flask import current_app, g
        r = getattr(g, "_redis", None)
        if r is not None:
            return r
        return current_app.extensions.get("redis")
    except Exception:
        return None


def _key(email: str, ip: str | None = None) -> str:
    """Hard-lock key, scoped by (email, IP) — see module docstring."""
    return f"login_attempts:{email.lower()}:{ip or 'unknown'}"


def _degraded_key(email: str, ip: str | None) -> str:
    return f"{email.lower()}:{ip or 'unknown'}"


def _degraded_peek(email: str, ip: str | None) -> int | None:
    """Check (without recording) the in-process degraded-mode bucket.

    Returns seconds-remaining if throttled, else None.
    """
    record_degraded_mode("lockout")
    key = _degraded_key(email, ip)
    now = time.time()
    window_start = now - _DEGRADED_WINDOW_SECONDS
    with _degraded_lock:
        bucket = [t for t in _degraded_buckets.get(key, ()) if t > window_start]
        if bucket:
            _degraded_buckets[key] = bucket
            _degraded_buckets.move_to_end(key)
        else:
            # Nothing left in the window -- drop the entry entirely instead
            # of writing back an empty list. A key that's never removed is
            # exactly the unbounded-growth crash-DoS this fix closes.
            _degraded_buckets.pop(key, None)
        count = len(bucket)
    if count >= _DEGRADED_MAX_ATTEMPTS:
        return _DEGRADED_WINDOW_SECONDS
    return None


def _degraded_record(email: str, ip: str | None) -> None:
    key = _degraded_key(email, ip)
    now = time.time()
    window_start = now - _DEGRADED_WINDOW_SECONDS
    with _degraded_lock:
        bucket = [t for t in _degraded_buckets.get(key, ()) if t > window_start]
        bucket.append(now)
        _degraded_buckets[key] = bucket
        _degraded_buckets.move_to_end(key)
        while len(_degraded_buckets) > _DEGRADED_MAX_KEYS:
            _degraded_buckets.popitem(last=False)


def check_lockout(email: str, ip: str | None = None) -> int | None:
    """Check if an (email, IP) pair is locked out.

    Returns seconds remaining if locked, or None if not locked.  Falls back
    to the bounded in-process degraded-mode limiter (rather than failing
    fully open) if Redis is unavailable.
    """
    r = _get_redis()
    if r is None:
        return _degraded_peek(email, ip)

    try:
        key = _key(email, ip)
        now = time.time()
        window_start = now - WINDOW_SECONDS

        # Count recent failed attempts
        r.zremrangebyscore(key, "-inf", window_start)
        count = r.zcard(key)

        # Redis just answered successfully -- if a prior outage had this
        # worker in degraded mode, close that window out so degraded-mode
        # stats show "recovered" instead of growing forever.
        record_recovery("lockout")

        if count >= MAX_ATTEMPTS:
            # Check when the oldest attempt in window was — lockout starts then
            oldest = r.zrange(key, 0, 0, withscores=True)
            if oldest:
                lockout_start = oldest[0][1]
                lockout_end = lockout_start + LOCKOUT_SECONDS
                remaining = int(lockout_end - now)
                if remaining > 0:
                    return remaining
            # Lockout expired — clear the set
            r.delete(key)
        return None
    except Exception as exc:
        logger.exception("Lockout check failed (falling back to bounded degraded mode)")
        alert_redis_failopen("lockout", str(exc))
        return _degraded_peek(email, ip)


def record_failed_attempt(email: str, ip: str | None = None) -> None:
    """Record a failed login attempt for the (email, IP) pair."""
    r = _get_redis()
    if r is None:
        _degraded_record(email, ip)
        return

    try:
        key = _key(email, ip)
        now = time.time()
        # Add with score=now, member=now (unique enough for our purposes)
        r.zadd(key, {f"{now}": now})
        r.expire(key, LOCKOUT_SECONDS + WINDOW_SECONDS)
    except Exception:
        logger.exception("Failed to record login attempt (falling back to degraded mode)")
        _degraded_record(email, ip)
        return

    # Soft, email-scoped distributed-attack detection -- see
    # _check_distributed_attack. Only runs on the successful-Redis path;
    # a Redis error above already falls back to the bounded per-(email, IP)
    # degraded limiter, which is the actual control during an outage.
    _check_distributed_attack(r, email, ip)


def clear_attempts(email: str, ip: str | None = None) -> None:
    """Clear failed attempts for this (email, IP) pair on successful login."""
    r = _get_redis()
    if r is None:
        # No Redis state to clear, but do clear our own in-process
        # fallback bucket -- otherwise a real login success during an
        # outage leaves stale degraded-mode state sitting in memory
        # instead of being freed like the Redis-backed path would.
        key = _degraded_key(email, ip)
        with _degraded_lock:
            _degraded_buckets.pop(key, None)
        return

    try:
        r.delete(_key(email, ip))
    except Exception:
        logger.exception("Failed to clear login attempts")


# ---------------------------------------------------------------------------
# Fix #2 follow-up: soft, email-scoped DETECTION signal for a *distributed*
# brute force -- see module docstring for why this is needed alongside the
# (email, IP)-scoped hard lock above.
# ---------------------------------------------------------------------------

def _distributed_ips_key(email: str) -> str:
    return f"login_attempts_distinct_ips:{email.lower()}"


def _distributed_alert_key(email: str) -> str:
    return f"login_attempts_distinct_ips_alerted:{email.lower()}"


def _check_distributed_attack(r, email: str, ip: str | None) -> None:
    """Track distinct failing IPs for *email* and ALERT past a threshold.

    Detection only -- never blocks a request. Adds *ip* to a short-lived
    Redis set keyed by email; once the set's distinct-member count crosses
    ``DISTRIBUTED_ATTACK_IP_THRESHOLD`` within
    ``DISTRIBUTED_ATTACK_WINDOW_SECONDS``, raises a security ALERT via
    Sentry (mirroring ``alert_redis_failopen``'s best-effort log+capture
    pattern) so the attack is visible + on-call actionable. A separate
    SET-NX dedup key (same pattern as
    ``tasks/billing_tasks.py::_pending_conflict_already_alerted``) ensures
    only the FIRST call to cross the threshold within a window alerts --
    every additional attacking IP in the same window does not re-alert.

    A full mitigation (CAPTCHA / step-up authentication triggered by this
    signal) is the fuller follow-up; for now this only makes the pattern
    detectable.

    Best-effort: never raises into the login path. Silently skipped when
    Redis is unavailable -- the bounded per-(email, IP) degraded-mode
    fallback above already bounds the attack *rate* during an outage; this
    signal is an alert, not a control, so it's fine for it to go dark too.
    """
    if not ip:
        return
    try:
        ips_key = _distributed_ips_key(email)
        r.sadd(ips_key, ip)
        r.expire(ips_key, DISTRIBUTED_ATTACK_WINDOW_SECONDS)
        distinct_ips = r.scard(ips_key)
        if distinct_ips >= DISTRIBUTED_ATTACK_IP_THRESHOLD:
            claimed = r.set(
                _distributed_alert_key(email), "1",
                nx=True, ex=DISTRIBUTED_ATTACK_WINDOW_SECONDS,
            )
            if claimed:
                _alert_distributed_credential_attack(email, distinct_ips)
    except Exception:
        logger.debug(
            "Distributed-attack detection failed for email=%s (best-effort, ignoring)",
            email, exc_info=True,
        )


def _alert_distributed_credential_attack(email: str, distinct_ip_count: int) -> None:
    """Best-effort security ALERT for a suspected distributed credential
    attack against one email. Mirrors ``alert_redis_failopen``
    (web/redis_health.py): log at ERROR + forward to Sentry via
    ``sentry_sdk.capture_message``. Never raises.
    """
    message = (
        f"Distributed credential attack suspected for {email}: "
        f"{distinct_ip_count} distinct IPs failed login within "
        f"{DISTRIBUTED_ATTACK_WINDOW_SECONDS}s"
    )
    logger.error(message)
    try:
        import sentry_sdk
        sentry_sdk.capture_message(message, level="error")
    except Exception:
        # sentry_sdk not installed/initialized, or the capture call itself
        # failed -- must never raise into the login path.
        pass


# ---------------------------------------------------------------------------
# Step-up challenge decision -- the fuller follow-up promised by the module
# docstring and by _check_distributed_attack above: turns the soft,
# email-scoped distributed-attack DETECTION signal into an actual (mild)
# response, closing the last open residual (distributed credential-stuffing
# against one email trips no hard lock -- see module docstring) WITHOUT
# reintroducing an account-level hard lock and its account-DoS (the reason
# the hard lock was scoped to (email, IP) in the first place). A step-up
# challenge annoys a distributed attacker but never locks the victim out.
# ---------------------------------------------------------------------------

def challenge_required(email: str, ip: str | None = None) -> bool:
    """Should this login be forced through a Turnstile challenge first?

    True only when BOTH:

    - this email's distinct-failing-IP count (the same Redis set
      ``_check_distributed_attack`` maintains) has crossed
      ``DISTRIBUTED_ATTACK_IP_THRESHOLD`` within
      ``DISTRIBUTED_ATTACK_WINDOW_SECONDS``, AND
    - Turnstile is actually configured (``auth.turnstile.turnstile_configured()``),
      so there is something to enforce.

    *ip* is accepted (mirroring the (email, ip)-scoped hard lock's call
    signature) but not currently part of the decision -- the distinct-IP
    counter is inherently email-scoped; it exists precisely because the
    hard lock above is IP-scoped and therefore blind to a many-IPs-one-email
    attack.

    Best-effort and fail-safe: unconfigured Turnstile, Redis being
    unavailable, or a Redis error mid-check all degrade to False (no
    challenge demanded) rather than raising into the login path -- this is a
    step-up ADD-ON, not a new hard gate, so its own failure must never block
    a legitimate login attempt.
    """
    from auth.turnstile import turnstile_configured
    if not turnstile_configured():
        return False

    r = _get_redis()
    if r is None:
        return False

    try:
        distinct_ips = r.scard(_distributed_ips_key(email))
        return distinct_ips >= DISTRIBUTED_ATTACK_IP_THRESHOLD
    except Exception:
        logger.debug(
            "challenge_required check failed for email=%s ip=%s (best-effort, "
            "treating as not required)",
            email, ip, exc_info=True,
        )
        return False
