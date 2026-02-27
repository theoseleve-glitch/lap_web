from __future__ import annotations

from datetime import datetime, timezone

from web.billing_entitlements import resolve_entitlements
from web.routes import billing as billing_routes


class FakeConn:
    def __init__(self, user: dict):
        self.user = user

    def execute(self, sql: str, params: dict):
        if "WHERE email" in sql and self.user["email"] == params["email"]:
            self.user["stripe_customer_id"] = params.get("cid")
            self.user["stripe_subscription_id"] = params.get("sid")
            self.user["plan_tier"] = params.get("plan_tier")
            self.user["billing_status"] = params.get("billing_status")
            self.user["stripe_price_id"] = params.get("stripe_price_id")
        if "WHERE stripe_customer_id" in sql and self.user["stripe_customer_id"] == params["cid"]:
            if "billing_status" in params:
                self.user["billing_status"] = params["billing_status"]
            if "plan_tier" in params:
                self.user["plan_tier"] = params["plan_tier"]
            if "sid" in params:
                self.user["stripe_subscription_id"] = params["sid"]
            if "stripe_price_id" in params:
                self.user["stripe_price_id"] = params["stripe_price_id"]
            if "period_end" in params:
                self.user["period_end"] = params["period_end"]
            if "cancel_at" in params:
                self.user["cancel_at"] = params["cancel_at"]
            if "stripe_subscription_id = NULL" in sql:
                self.user["stripe_subscription_id"] = None
            if "stripe_price_id = NULL" in sql:
                self.user["stripe_price_id"] = None

    def commit(self):
        return None


def test_upgrade_downgrade_cancel_transitions(monkeypatch):
    user = {"email": "driver@example.com", "stripe_customer_id": None}
    conn = FakeConn(user)
    monkeypatch.setattr(billing_routes, "_get_conn", lambda: conn)
    monkeypatch.setattr(
        billing_routes,
        "_PLAN_FROM_PRICE_ENV",
        {"price_racer": "racer", "price_world": "world_class"},
    )

    billing_routes._handle_checkout_completed(
        {
            "customer_email": "driver@example.com",
            "subscription": "sub_1",
            "customer": "cus_1",
            "price": "price_racer",
        }
    )
    assert user["plan_tier"] == "racer"
    assert user["billing_status"] == "active"

    billing_routes._handle_subscription_updated(
        {
            "id": "sub_1",
            "customer": "cus_1",
            "status": "active",
            "items": {"data": [{"price": {"id": "price_world"}}]},
            "current_period_end": 1760000000,
            "cancel_at": None,
        }
    )
    assert user["plan_tier"] == "world_class"
    assert user["stripe_price_id"] == "price_world"

    billing_routes._handle_subscription_updated(
        {
            "id": "sub_1",
            "customer": "cus_1",
            "status": "active",
            "items": {"data": [{"price": {"id": "price_racer"}}]},
            "current_period_end": 1760000100,
            "cancel_at": None,
        }
    )
    assert user["plan_tier"] == "racer"

    billing_routes._handle_subscription_deleted(
        {
            "customer": "cus_1",
            "current_period_end": 1760000200,
            "canceled_at": 1760000200,
        }
    )
    assert user["plan_tier"] == "free"
    assert user["billing_status"] == "canceled"
    assert user["stripe_subscription_id"] is None


def test_failed_payment_transition_keeps_tier(monkeypatch):
    user = {
        "email": "driver@example.com",
        "stripe_customer_id": "cus_1",
        "plan_tier": "racer",
        "billing_status": "active",
    }
    conn = FakeConn(user)
    monkeypatch.setattr(billing_routes, "_get_conn", lambda: conn)

    billing_routes._handle_payment_failed({"customer": "cus_1"})

    assert user["plan_tier"] == "racer"
    assert user["billing_status"] == "past_due"


def test_entitlement_resolver_uses_normalized_billing_fields():
    entitlements = resolve_entitlements(
        {"plan_tier": "world_class", "billing_status": "active"}
    )
    assert entitlements["is_paid"] is True
    assert entitlements["entitlements"]["team_workspaces"] is True

    free_entitlements = resolve_entitlements(
        {"plan_tier": "world_class", "billing_status": "canceled"}
    )
    assert free_entitlements["plan_tier"] == "free"
    assert free_entitlements["entitlements"]["advanced_analytics"] is False


def test_unix_timestamp_conversion_is_utc():
    dt = billing_routes._from_unix(1760000000)
    assert dt == datetime.fromtimestamp(1760000000, tz=timezone.utc)
