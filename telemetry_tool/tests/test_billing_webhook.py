import copy
import json
import sys
import types

from flask import Flask

from web.routes import billing


class FakeConn:
    def __init__(self, users=None):
        self.users = users or {}
        self.stripe_events = {}
        self._users_tx = None
        self._events_tx = None

    def _begin(self):
        if self._users_tx is None:
            self._users_tx = copy.deepcopy(self.users)
            self._events_tx = copy.deepcopy(self.stripe_events)

    def execute(self, sql, params=None):
        self._begin()
        params = params or {}
        if sql.startswith("INSERT INTO stripe_events"):
            event_id = params["event_id"]
            if event_id in self._events_tx:
                raise Exception("unique constraint failed: stripe_events.event_id")
            self._events_tx[event_id] = {
                "event_id": event_id,
                "type": params["event_type"],
                "status": params["status"],
                "payload_hash": params["payload_hash"],
                "processed_at": None,
            }
            return None

        if sql.startswith("UPDATE stripe_events"):
            row = self._events_tx[params["event_id"]]
            row["status"] = params["status"]
            row["processed_at"] = "now"
            return None

        if "UPDATE users SET stripe_customer_id" in sql:
            user = self._users_tx[params["email"]]
            user["stripe_customer_id"] = params["cid"]
            user["stripe_subscription_id"] = params["sid"]
            user["billing_plan"] = params["plan"]
            return None

        if "UPDATE users SET billing_plan = %(plan)s WHERE stripe_customer_id" in sql:
            for user in self._users_tx.values():
                if user.get("stripe_customer_id") == params["cid"] and user.get("stripe_subscription_id") is not None:
                    user["billing_plan"] = params["plan"]
            return None

        if "UPDATE users SET billing_plan = %(plan)s, stripe_subscription_id = NULL" in sql:
            for user in self._users_tx.values():
                if user.get("stripe_customer_id") == params["cid"]:
                    user["billing_plan"] = params["plan"]
                    user["stripe_subscription_id"] = None
            return None

        raise AssertionError(f"Unexpected SQL: {sql}")

    def commit(self):
        self.users = self._users_tx
        self.stripe_events = self._events_tx
        self._users_tx = None
        self._events_tx = None

    def rollback(self):
        self._users_tx = None
        self._events_tx = None


class _FakeSignatureVerificationError(Exception):
    pass


class _FakeWebhook:
    @staticmethod
    def construct_event(payload, sig_header, secret):
        return json.loads(payload)


def _install_fake_stripe():
    stripe_mod = types.SimpleNamespace(
        api_key="",
        Webhook=_FakeWebhook,
        error=types.SimpleNamespace(SignatureVerificationError=_FakeSignatureVerificationError),
    )
    sys.modules["stripe"] = stripe_mod


def _make_client(monkeypatch, conn):
    _install_fake_stripe()
    app = Flask(__name__)
    app.register_blueprint(billing.bp)
    monkeypatch.setattr(billing, "STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setattr(billing, "STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setattr(billing, "_get_conn", lambda: conn)
    return app.test_client()


def _post_event(client, event):
    return client.post(
        "/api/v1/billing/webhook",
        data=json.dumps(event),
        headers={"Stripe-Signature": "t=fake,v1=fake"},
    )


def test_duplicate_delivery_short_circuits(monkeypatch):
    conn = FakeConn(users={"a@test.dev": {"billing_plan": "free"}})
    client = _make_client(monkeypatch, conn)

    event = {
        "id": "evt_duplicate",
        "type": "checkout.session.completed",
        "data": {"object": {"customer_email": "a@test.dev", "subscription": "sub_1", "customer": "cus_1"}},
    }

    first = _post_event(client, event)
    second = _post_event(client, event)

    assert first.status_code == 200
    assert first.json["status"] == "ok"
    assert second.status_code == 200
    assert second.json["status"] == "already_processed"
    assert conn.stripe_events["evt_duplicate"]["status"] == "success"


def test_out_of_order_subscription_events_do_not_reactivate(monkeypatch):
    conn = FakeConn(
        users={
            "a@test.dev": {
                "stripe_customer_id": "cus_1",
                "stripe_subscription_id": "sub_1",
                "billing_plan": "active",
            }
        }
    )
    client = _make_client(monkeypatch, conn)

    deleted = {
        "id": "evt_deleted",
        "type": "customer.subscription.deleted",
        "data": {"object": {"customer": "cus_1"}},
    }
    updated = {
        "id": "evt_updated_late",
        "type": "customer.subscription.updated",
        "data": {"object": {"customer": "cus_1", "status": "active"}},
    }

    assert _post_event(client, deleted).status_code == 200
    assert _post_event(client, updated).status_code == 200
    assert conn.users["a@test.dev"]["billing_plan"] == "free"
    assert conn.users["a@test.dev"]["stripe_subscription_id"] is None


def test_handler_exception_records_failure_without_retry(monkeypatch):
    conn = FakeConn(users={"a@test.dev": {"billing_plan": "free"}})
    client = _make_client(monkeypatch, conn)
    monkeypatch.setattr(billing, "_process_event", lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))

    event = {
        "id": "evt_failure",
        "type": "checkout.session.completed",
        "data": {"object": {"customer_email": "a@test.dev", "subscription": "sub_1", "customer": "cus_1"}},
    }

    response = _post_event(client, event)

    assert response.status_code == 200
    assert response.json["status"] == "failed"
    assert conn.stripe_events["evt_failure"]["status"] == "failure"


def test_transient_exception_returns_5xx_and_rolls_back(monkeypatch):
    conn = FakeConn(users={"a@test.dev": {"billing_plan": "free"}})
    client = _make_client(monkeypatch, conn)
    monkeypatch.setattr(
        billing,
        "_process_event",
        lambda *_: (_ for _ in ()).throw(billing.TransientWebhookError("temporary")),
    )

    event = {
        "id": "evt_retry",
        "type": "checkout.session.completed",
        "data": {"object": {"customer_email": "a@test.dev", "subscription": "sub_1", "customer": "cus_1"}},
    }

    response = _post_event(client, event)

    assert response.status_code == 500
    assert "evt_retry" not in conn.stripe_events
