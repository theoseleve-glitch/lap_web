"""Founding-50 slot reservation — the hard, race-safe ≤50 cap.

Backed by the ``founding_slots`` table (migration 062): exactly 50 pre-seeded
rows. A checkout claims the lowest available (open, or expired-held) slot via
``FOR UPDATE SKIP LOCKED``; the webhook confirms (claimed) on payment;
cancel/expiry releases. Oversell is impossible — only 50 rows exist, each
claimable once.

Flow:  reserve_slot -> (create Stripe session) -> attach_session
       webhook paid -> confirm_slot ;  cancel -> release_slot_by_subscription
       Stripe error -> release_slot
"""
from __future__ import annotations

# Hold window: an abandoned checkout frees its slot after this long.
HOLD_MINUTES = 60

_RESERVE_SQL = """
UPDATE founding_slots
SET status='held', holder_email=%(email)s, held_at=now(),
    expires_at=now() + make_interval(mins => %(hold)s)
WHERE slot_no = (
    SELECT slot_no FROM founding_slots
    WHERE status='open' OR (status='held' AND expires_at < now())
    ORDER BY slot_no
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
RETURNING slot_no;
"""

_EXISTING_HOLD_SQL = """
SELECT slot_no FROM founding_slots
WHERE holder_email = %(email)s AND status = 'held' AND expires_at > now()
ORDER BY slot_no
LIMIT 1;
"""

_ATTACH_SQL = """
UPDATE founding_slots SET stripe_session_id=%(sid)s
WHERE slot_no=%(slot)s AND status='held' RETURNING slot_no;
"""

_CONFIRM_SQL = """
UPDATE founding_slots
SET status='claimed', stripe_subscription_id=%(sub)s, claimed_at=now()
WHERE slot_no=%(slot)s AND status IN ('held','claimed')
RETURNING slot_no;
"""

_OPEN_FIELDS = ("status='open', holder_email=NULL, stripe_session_id=NULL, "
                "stripe_subscription_id=NULL, held_at=NULL, expires_at=NULL, claimed_at=NULL")
_RELEASE_BY_SLOT_SQL = f"UPDATE founding_slots SET {_OPEN_FIELDS} WHERE slot_no=%(slot)s RETURNING slot_no;"
_RELEASE_BY_SUB_SQL = f"UPDATE founding_slots SET {_OPEN_FIELDS} WHERE stripe_subscription_id=%(sub)s RETURNING slot_no;"


def _scalar(cur):
    row = cur.fetchone()
    if row is None:
        return None
    return (dict(row) if not isinstance(row, dict) else row)["slot_no"]


def reserve_slot(conn, email: str | None) -> int | None:
    """Atomically claim the lowest available founding slot. Returns slot_no, or
    None if sold out (caller then uses the standard price). Caller must commit.

    Idempotent per email: if this buyer already holds an unexpired slot (a
    double-submitted checkout), return that SAME slot rather than consuming a
    second one of the scarce 50. (Truly-concurrent dupes are additionally
    guarded by the @idempotent Idempotency-Key lock on the checkout route.)
    """
    if email:
        existing = _scalar(conn.execute(_EXISTING_HOLD_SQL, {"email": email}))
        if existing is not None:
            return existing
    return _scalar(conn.execute(_RESERVE_SQL, {"email": email, "hold": HOLD_MINUTES}))


def attach_session(conn, slot_no: int, session_id: str) -> int | None:
    return _scalar(conn.execute(_ATTACH_SQL, {"slot": slot_no, "sid": session_id}))


def confirm_slot(conn, slot_no: int, subscription_id: str | None) -> int | None:
    """Mark a held slot as claimed (called from the webhook on payment)."""
    return _scalar(conn.execute(_CONFIRM_SQL, {"slot": slot_no, "sub": subscription_id}))


def release_slot(conn, slot_no: int) -> int | None:
    return _scalar(conn.execute(_RELEASE_BY_SLOT_SQL, {"slot": slot_no}))


def release_slot_by_subscription(conn, subscription_id: str) -> int | None:
    """Free a slot when its subscription is canceled/deleted."""
    return _scalar(conn.execute(_RELEASE_BY_SUB_SQL, {"sub": subscription_id}))
