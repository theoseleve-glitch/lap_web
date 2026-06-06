"""Tests for the Founding-50 slot reservation (web/founding.py).

Focus: the per-email idempotency that stops a double-submitted checkout from
consuming two of the scarce 50 slots for one buyer.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from web.founding import reserve_slot


def _cur(slot_no):
    cur = MagicMock()
    cur.fetchone.return_value = ({"slot_no": slot_no} if slot_no is not None else None)
    return cur


def test_reserve_slot_returns_existing_hold_for_same_email():
    """A double-submit by the same buyer returns the SAME held slot — it must
    not claim a second one (the 50-slot cap is scarce)."""
    conn = MagicMock()
    conn.execute.return_value = _cur(5)  # existing-hold lookup finds slot 5

    assert reserve_slot(conn, "buyer@example.com") == 5

    sql = " ".join(str(c.args[0]) for c in conn.execute.call_args_list)
    assert "SELECT slot_no FROM founding_slots" in sql
    assert "UPDATE founding_slots" not in sql, "must not claim a new slot when one is held"


def test_reserve_slot_claims_new_when_no_existing_hold():
    """First-time buyer with no held slot claims the lowest available one."""
    conn = MagicMock()
    conn.execute.side_effect = [_cur(None), _cur(1)]  # no hold -> reserve slot 1

    assert reserve_slot(conn, "new@example.com") == 1


def test_reserve_slot_skips_email_dedup_when_no_email():
    """Guest checkout without an email cannot be de-duped — go straight to claim."""
    conn = MagicMock()
    conn.execute.return_value = _cur(2)

    assert reserve_slot(conn, None) == 2

    sql = " ".join(str(c.args[0]) for c in conn.execute.call_args_list)
    assert "holder_email = " not in sql, "no email -> no existing-hold lookup"
