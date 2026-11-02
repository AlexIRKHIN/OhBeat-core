"""Payment and webhook: FR-20 … FR-25, FR-30; GAP-6, GAP-7, GAP-35 … GAP-41, GAP-62.

YooKassa is replaced by FakeGateway; the database is the real PostgreSQL. Each test plays what
happens outside: the buyer pays on the YooKassa page (`fake.hold`), YooKassa sends a webhook
(`notify`), and checks what Core API did and which calls it made to YooKassa.
"""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.common.config import get_settings
from app.common.db import get_session_factory
from app.main import app
from app.payments import gateway as gateway_module
from app.payments.events import settle_stuck_payments
from app.payments.gateway import GatewayUnavailable, YooKassaGateway, get_gateway
from app.payments.service import transfers_for
from tests.fake_gateway import FakeGateway
from tests.helpers import auth, make_producer
from tests.test_orders import _artist, _beat, _beat_row, _order


@pytest.fixture
def fake():
    gateway = FakeGateway()
    app.dependency_overrides[get_gateway] = lambda: gateway
    yield gateway
    app.dependency_overrides.pop(get_gateway, None)


@pytest.fixture
def producer(client):
    return make_producer(client)


def _sign(owner_engine, order_id: int) -> None:
    """Slice 4 signs Exclusive with an SMS code; here the signed contracts are put in place directly."""
    with owner_engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO contracts (order_item_id, signature_type, draft_sha256, signer_ip, signed_at, signer_phone) "
            "SELECT oi.id, 'otp', repeat('a', 64), '127.0.0.1', now(), '+79001234567' FROM order_items oi "
            "JOIN licenses l ON l.id = oi.license_id WHERE oi.order_id = :o AND l.is_exclusive"), {"o": order_id})


def _pay(client, tokens, order_id: int):
    return client.post(f"/v1/orders/{order_id}/payments", headers=auth(tokens))


def notify(client, payment_id: str, event: str = "payment.waiting_for_capture"):
    """A YooKassa notification. The body is not trusted: Core API asks the gateway for the status."""
    return client.post("/v1/payments/webhook", json={"type": "notification", "event": event, "object": {"id": payment_id}})


def _scalar(owner_engine, sql: str, **params):
    with owner_engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


@pytest.fixture
def exclusive_order(client, producer, owner_engine, fake):
    """An Artist with a signed Exclusive order and a created payment: (tokens, order_id, beat_id, payment_id)."""
    beat_id = _beat(client, owner_engine, producer)
    artist = _artist(client)
    client.put(f"/v1/cart/items/{beat_id}", json={"license": "exclusive"}, headers=auth(artist))
    order_id = _order(client, artist, [(beat_id, "exclusive", 25000)]).json()["order_id"]
    _sign(owner_engine, order_id)
    payment_id = _pay(client, artist, order_id).json()["payment_id"]
    return artist, order_id, beat_id, payment_id


# --- Creating a payment (FR-20, FR-30) ---

def test_fr20_fr30_payment_with_split_for_three_producers(client, owner_engine, fake):
    producers = [make_producer(client, email=f"p{i}@example.com") for i in range(3)]
    with owner_engine.begin() as conn:  # distinct seller ids in YooKassa
        conn.execute(text("UPDATE producer_accounts SET yookassa_account_id = 'seller-' || user_id"))
    beats = [_beat(client, owner_engine, p, title=f"Beat {i}") for i, p in enumerate(producers)]
    with owner_engine.begin() as conn:  # prices that give fees with kopecks: 99.90, 133.30, 10.50
        for beat_id, price in zip(beats, (999, 1333, 105)):
            conn.execute(text("UPDATE beat_prices SET price = :p WHERE beat_id = :b"), {"p": price, "b": beat_id})
    artist = _artist(client)
    order = _order(client, artist, [(beats[0], "basic", 999), (beats[1], "basic", 1333), (beats[2], "premium", 105)]).json()

    response = _pay(client, artist, order["order_id"])
    assert response.status_code == 200, response.text
    assert response.json()["confirmation_url"].startswith("http://mock/checkout/")

    body = fake.created_bodies[0]
    assert body["capture"] is False and body["amount"] == {"value": "2680.70", "currency": "RUB"}
    assert body["confirmation"]["return_url"] == f"{get_settings().frontend_url}/orders/{order['order_id']}/return"
    assert body["metadata"] == {"order_id": str(order["order_id"]), "platform_fee": "243.70"}
    assert sorted(t["amount"]["value"] for t in body["transfers"]) == ["105.00", "1333.00", "999.00"]
    assert len({t["account_id"] for t in body["transfers"]}) == 3
    # Σ transfers + fee = amount (the fake, like the mock, refuses anything else)
    split = sum(Decimal(t["amount"]["value"]) for t in body["transfers"])
    assert split + Decimal(body["metadata"]["platform_fee"]) == Decimal(body["amount"]["value"])

    with owner_engine.connect() as conn:
        row = conn.execute(text("SELECT status, amount, idempotence_key FROM payments")).one()
    assert (row.status, row.amount) == ("pending", Decimal("2680.70")) and row.idempotence_key is not None


def test_fr30_transfers_group_items_of_one_producer(client, producer, owner_engine):
    a = _beat(client, owner_engine, producer, title="Beat A")
    b = _beat(client, owner_engine, producer, title="Beat B")
    order_id = _order(client, _artist(client), [(a, "basic", 1500), (b, "premium", 3000)]).json()["order_id"]
    with get_session_factory()() as db:
        from app.orders.models import Order

        transfers, fee = transfers_for(db, db.get(Order, order_id))
    assert [t["amount"]["value"] for t in transfers] == ["4500.00"] and fee == Decimal("450.00")


def test_gap40_second_click_returns_the_same_payment(client, producer, owner_engine, fake):
    beat_id = _beat(client, owner_engine, producer)
    artist = _artist(client)
    order_id = _order(client, artist, [(beat_id, "basic", 1500)]).json()["order_id"]
    first, second = _pay(client, artist, order_id).json(), _pay(client, artist, order_id).json()
    assert first == second and fake.count("create") == 1


def test_fr25_after_bank_decline_a_new_payment_has_a_new_key(client, producer, owner_engine, fake):
    beat_id = _beat(client, owner_engine, producer)
    artist = _artist(client)
    order_id = _order(client, artist, [(beat_id, "basic", 1500)]).json()["order_id"]
    first = _pay(client, artist, order_id).json()["payment_id"]
    fake.decline(first)
    assert notify(client, first, "payment.canceled").status_code == 200

    order = client.get(f"/v1/orders/{order_id}", headers=auth(artist)).json()
    assert (order["status"], order["payment_status"], order["payment_cancel_reason"]) == ("pending", "canceled", "insufficient_funds")
    second = _pay(client, artist, order_id).json()["payment_id"]
    assert second != first
    assert _scalar(owner_engine, "SELECT count(DISTINCT idempotence_key) FROM payments") == 2


def test_payment_errors_409_410_428(client, producer, owner_engine, fake):
    beat_id = _beat(client, owner_engine, producer)
    artist = _artist(client)
    order_id = _order(client, artist, [(beat_id, "exclusive", 25000)]).json()["order_id"]
    assert _pay(client, artist, order_id).json()["error_code"] == "SIGNATURE_REQUIRED"  # 428
    _sign(owner_engine, order_id)
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE beats SET reserved_until = now() - interval '1 second' WHERE id = :b"), {"b": beat_id})
    response = _pay(client, artist, order_id)
    assert (response.status_code, response.json()["error_code"]) == (410, "RESERVATION_EXPIRED")
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE orders SET status = 'expired' WHERE id = :o"), {"o": order_id})
    response = _pay(client, artist, order_id)
    assert (response.status_code, response.json()["error_code"]) == (409, "INVALID_STATUS")
    stranger = _artist(client, email="stranger@example.com")
    assert _pay(client, stranger, order_id).status_code == 403


def test_fr21_provider_unavailable_keeps_the_reservation(client, producer, owner_engine, fake):
    beat_id = _beat(client, owner_engine, producer)
    artist = _artist(client)
    order_id = _order(client, artist, [(beat_id, "exclusive", 25000)]).json()["order_id"]
    _sign(owner_engine, order_id)
    fake.fail["create"] = "unavailable"
    response = _pay(client, artist, order_id)
    assert (response.status_code, response.json()["error_code"]) == (503, "PAYMENT_PROVIDER_UNAVAILABLE")
    assert _beat_row(owner_engine, beat_id).status == "reserved"
    assert _scalar(owner_engine, "SELECT count(*) FROM payments") == 0


def test_fr21_gap62_http_client_retries_three_times_with_the_same_key(monkeypatch):
    sent = []

    def flaky(method, url, json=None, headers=None, auth=None, timeout=None):
        sent.append(headers.get("Idempotence-Key"))
        if len(sent) < 4:
            raise httpx.ReadTimeout("slow")
        return httpx.Response(200, json={"id": "p", "status": "pending"})

    monkeypatch.setattr(gateway_module.httpx, "request", flaky)
    monkeypatch.setattr(gateway_module.time, "sleep", lambda _: None)
    assert YooKassaGateway().create_payment("key-1", {})["id"] == "p"
    assert sent == ["key-1"] * 4  # 1 attempt + 3 retries, one key

    sent.clear()
    monkeypatch.setattr(gateway_module.httpx, "request",
                        lambda *a, **k: sent.append(1) or httpx.Response(503, json={}))
    with pytest.raises(GatewayUnavailable):
        YooKassaGateway().create_payment("key-2", {})
    assert len(sent) == 4


# --- Webhook: the happy path (FR-22 … FR-24) ---

def test_fr22_fr24_hold_capture_and_paid(client, owner_engine, fake, exclusive_order):
    artist, order_id, beat_id, payment_id = exclusive_order
    fake.hold(payment_id)

    assert notify(client, payment_id).status_code == 200
    assert _beat_row(owner_engine, beat_id).status == "sold"  # FR-23 in the webhook transaction
    assert fake.count("capture", payment_id) == 1  # after the commit (GAP-35)
    assert notify(client, payment_id, "payment.succeeded").status_code == 200

    order = client.get(f"/v1/orders/{order_id}", headers=auth(artist)).json()
    assert (order["status"], order["payment_status"]) == ("paid", "succeeded")
    assert client.get("/v1/cart", headers=auth(artist)).json()["items"] == []  # GAP-29
    actions = [a for a, in _rows(owner_engine, "SELECT action FROM audit_log WHERE entity = 'order' AND entity_id = :o ORDER BY id", o=order_id)]
    assert actions[-3:] == ["payment.waiting_for_capture", "order.paid", "payment.succeeded"]
    assert client.get(f"/v1/beats/{beat_id}").status_code == 404  # FR-24: hidden from the catalog


def _rows(owner_engine, sql: str, **params):
    with owner_engine.connect() as conn:
        return conn.execute(text(sql), params).all()


def test_fr22_body_is_not_trusted(client, owner_engine, fake, exclusive_order):
    """The notification says "succeeded", YooKassa says the payment is still pending: nothing happens."""
    _, order_id, beat_id, payment_id = exclusive_order
    assert notify(client, payment_id, "payment.succeeded").status_code == 200
    assert _scalar(owner_engine, "SELECT status FROM orders WHERE id = :o", o=order_id) == "pending"
    assert _scalar(owner_engine, "SELECT count(*) FROM payment_events") == 0


def test_gap7_unknown_payment_gets_200(client, fake):
    assert notify(client, str(uuid.uuid4())).status_code == 200
    assert notify(client, "not-a-uuid").status_code == 200


def test_fr22_yookassa_unreachable_on_verification_answers_500_and_retry_works(client, owner_engine, fake, exclusive_order):
    _, order_id, beat_id, payment_id = exclusive_order
    fake.hold(payment_id)
    fake.fail["get"] = "unavailable"
    with TestClient(app, raise_server_exceptions=False) as raw:  # see the real answer, not the exception
        assert notify(raw, payment_id).status_code == 500  # YooKassa will repeat
    assert _scalar(owner_engine, "SELECT count(*) FROM payment_events") == 0
    del fake.fail["get"]
    assert notify(client, payment_id).status_code == 200
    assert _beat_row(owner_engine, beat_id).status == "sold"


def test_fr22_ip_check(client, fake, monkeypatch):
    monkeypatch.setattr(get_settings(), "yookassa_ip_check", True)
    assert notify(client, str(uuid.uuid4())).status_code == 403  # the test client is not YooKassa
    from app.payments.router import from_yookassa

    assert from_yookassa("185.71.76.5") and from_yookassa("77.75.156.11") and not from_yookassa("10.0.0.1")


# --- Repeated webhook (mandatory) ---

def test_fr22_repeated_webhook_three_times_in_a_row(client, owner_engine, fake, exclusive_order):
    _, order_id, beat_id, payment_id = exclusive_order
    fake.hold(payment_id)
    fake.fail["capture"] = "unavailable"  # keep the payment in the hold: every repeat sees the same status
    assert [notify(client, payment_id).status_code for _ in range(3)] == [200, 200, 200]
    assert fake.count("capture", payment_id) == 1  # only the first one decided anything
    assert _scalar(owner_engine, "SELECT count(*) FROM payment_events") == 1
    del fake.fail["capture"]
    fake.hold(payment_id)
    fake.capture(payment_id, {})

    assert [notify(client, payment_id, "payment.succeeded").status_code for _ in range(3)] == [200, 200, 200]
    assert _scalar(owner_engine, "SELECT count(*) FROM audit_log WHERE action = 'order.paid'") == 1


def test_fr22_repeated_webhook_three_times_at_once(client, owner_engine, fake, exclusive_order):
    _, order_id, beat_id, payment_id = exclusive_order
    fake.hold(payment_id)
    fake.fail["capture"] = "unavailable"  # the status stays waiting_for_capture for all three
    start = threading.Barrier(3)

    def send(_):
        start.wait()
        return notify(client, payment_id).status_code

    with ThreadPoolExecutor(max_workers=3) as pool:
        assert list(pool.map(send, range(3))) == [200, 200, 200]
    assert fake.count("capture", payment_id) == 1
    assert _scalar(owner_engine, "SELECT count(*) FROM payment_events") == 1
    assert _scalar(owner_engine, "SELECT count(*) FROM audit_log WHERE action = 'payment.waiting_for_capture'") == 1


# --- Expired reservation when waiting_for_capture comes (mandatory) ---

def _expire_reservation(owner_engine, beat_id: int) -> None:
    """FR-29 ran: the beat is back on sale, the order expired."""
    from app.orders.expiry import expire_reservations

    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE beats SET reserved_until = now() - interval '1 second' WHERE id = :b"), {"b": beat_id})
    with get_session_factory()() as db:
        expire_reservations(db)


def test_fr23_expired_reservation_beat_still_free_is_sold(client, owner_engine, fake, exclusive_order):
    artist, order_id, beat_id, payment_id = exclusive_order
    _expire_reservation(owner_engine, beat_id)
    assert _beat_row(owner_engine, beat_id).status == "active"
    fake.hold(payment_id)

    notify(client, payment_id)
    assert _beat_row(owner_engine, beat_id).status == "sold"
    assert fake.count("capture", payment_id) == 1
    notify(client, payment_id, "payment.succeeded")
    # FR-24: payment after expiry that passed the check — expired → paid
    assert client.get(f"/v1/orders/{order_id}", headers=auth(artist)).json()["status"] == "paid"


def test_fr23_expired_reservation_beat_taken_by_another_order_is_canceled(client, owner_engine, fake, exclusive_order):
    artist, order_id, beat_id, payment_id = exclusive_order
    _expire_reservation(owner_engine, beat_id)
    other = _artist(client, email="other@example.com")
    other_order = _order(client, other, [(beat_id, "exclusive", 25000)]).json()["order_id"]
    fake.hold(payment_id)

    notify(client, payment_id)
    row = _beat_row(owner_engine, beat_id)
    assert (row.status, row.reserved_order_id) == ("reserved", other_order)  # the other buyer keeps it
    assert fake.count("cancel", payment_id) == 1 and fake.count("capture", payment_id) == 0
    order = client.get(f"/v1/orders/{order_id}", headers=auth(artist)).json()
    assert (order["status"], order["cancel_reason"]) == ("canceled", "BEAT_RESERVED")


def test_fr23_expired_reservation_beat_already_sold_is_canceled(client, owner_engine, fake, exclusive_order):
    artist, order_id, beat_id, payment_id = exclusive_order
    _expire_reservation(owner_engine, beat_id)
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE beats SET status = 'sold' WHERE id = :b"), {"b": beat_id})
    fake.hold(payment_id)

    notify(client, payment_id)
    assert fake.count("cancel", payment_id) == 1
    assert client.get(f"/v1/orders/{order_id}", headers=auth(artist)).json()["cancel_reason"] == "BEAT_SOLD"
    notify(client, payment_id, "payment.canceled")
    assert _beat_row(owner_engine, beat_id).status == "sold"  # the other sale is untouched


# --- Payment after expired (mandatory) ---

def test_fr24_lease_order_expired_after_24h_still_paid(client, producer, owner_engine, fake):
    beat_id = _beat(client, owner_engine, producer)
    artist = _artist(client)
    order_id = _order(client, artist, [(beat_id, "basic", 1500)]).json()["order_id"]
    payment_id = _pay(client, artist, order_id).json()["payment_id"]
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE orders SET status = 'expired' WHERE id = :o"), {"o": order_id})
    fake.hold(payment_id)
    notify(client, payment_id)
    notify(client, payment_id, "payment.succeeded")
    assert client.get(f"/v1/orders/{order_id}", headers=auth(artist)).json()["status"] == "paid"


def test_fr23_lease_of_a_beat_sold_meanwhile_is_canceled(client, producer, owner_engine, fake):
    beat_id = _beat(client, owner_engine, producer)
    artist = _artist(client)
    order_id = _order(client, artist, [(beat_id, "basic", 1500)]).json()["order_id"]
    payment_id = _pay(client, artist, order_id).json()["payment_id"]
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE beats SET status = 'sold' WHERE id = :b"), {"b": beat_id})
    fake.hold(payment_id)
    notify(client, payment_id)
    assert fake.count("cancel", payment_id) == 1
    assert _scalar(owner_engine, "SELECT status FROM orders WHERE id = :o", o=order_id) == "canceled"


def test_gap39_lease_of_a_hidden_beat_is_still_sold(client, producer, owner_engine, fake):
    beat_id = _beat(client, owner_engine, producer)
    artist = _artist(client)
    order_id = _order(client, artist, [(beat_id, "basic", 1500)]).json()["order_id"]
    payment_id = _pay(client, artist, order_id).json()["payment_id"]
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE beats SET status = 'hidden' WHERE id = :b"), {"b": beat_id})
    fake.hold(payment_id)
    notify(client, payment_id)
    assert fake.count("capture", payment_id) == 1


# --- Amount, final capture failure, the scheduler ---

def test_gap38_amount_mismatch_is_canceled(client, owner_engine, fake, exclusive_order):
    artist, order_id, beat_id, payment_id = exclusive_order
    fake.hold(payment_id)
    fake.payments[payment_id]["amount"] = {"value": "1.00", "currency": "RUB"}
    notify(client, payment_id)
    assert fake.count("cancel", payment_id) == 1 and fake.count("capture") == 0
    assert _beat_row(owner_engine, beat_id).status == "active"
    assert client.get(f"/v1/orders/{order_id}", headers=auth(artist)).json()["cancel_reason"] == "AMOUNT_MISMATCH"


def test_gap37_final_capture_failure_returns_beat_to_sale(client, owner_engine, fake, exclusive_order):
    artist, order_id, beat_id, payment_id = exclusive_order
    fake.hold(payment_id)
    fake.fail["capture"] = "rejected"
    notify(client, payment_id)

    assert _beat_row(owner_engine, beat_id).status == "active"  # FR-23: back on sale
    order = client.get(f"/v1/orders/{order_id}", headers=auth(artist)).json()
    assert (order["status"], order["payment_status"], order["cancel_reason"]) == ("canceled", "canceled", "CAPTURE_FAILED")


def test_gap37_hold_expired_after_the_check(client, owner_engine, fake, exclusive_order):
    artist, order_id, beat_id, payment_id = exclusive_order
    fake.hold(payment_id)
    fake.fail["capture"] = "unavailable"  # capture never got through
    notify(client, payment_id)
    assert _beat_row(owner_engine, beat_id).status == "sold"
    fake.expire_hold(payment_id)
    notify(client, payment_id, "payment.canceled")
    assert _beat_row(owner_engine, beat_id).status == "active"
    assert _scalar(owner_engine, "SELECT status FROM orders WHERE id = :o", o=order_id) == "canceled"


def test_gap35_crash_before_capture_is_finished_by_the_scheduler(client, owner_engine, fake, exclusive_order, monkeypatch):
    artist, order_id, beat_id, payment_id = exclusive_order
    fake.hold(payment_id)
    fake.fail["capture"] = "unavailable"  # as if Core API died right after the commit
    notify(client, payment_id)
    assert fake.payments[payment_id]["status"] == "waiting_for_capture"
    # a repeated webhook is a duplicate and cannot help
    assert notify(client, payment_id).status_code == 200 and fake.count("capture", payment_id) == 1

    del fake.fail["capture"]
    monkeypatch.setattr(get_settings(), "payment_settle_after_seconds", 0)
    with get_session_factory()() as db:
        assert settle_stuck_payments(db, gateway=fake) == 1
    assert fake.payments[payment_id]["status"] == "succeeded"
    # the "succeeded" webhook was lost too: the next run applies the actual status by itself
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE payment_events SET received_at = now() - interval '1 hour'"))
    with get_session_factory()() as db:
        settle_stuck_payments(db, gateway=fake)
    assert client.get(f"/v1/orders/{order_id}", headers=auth(artist)).json()["status"] == "paid"


def test_gap35_scheduler_cancels_for_a_canceled_order(client, owner_engine, fake, exclusive_order, monkeypatch):
    _, order_id, beat_id, payment_id = exclusive_order
    _expire_reservation(owner_engine, beat_id)
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE beats SET status = 'sold' WHERE id = :b"), {"b": beat_id})
    fake.hold(payment_id)
    fake.fail["cancel"] = "unavailable"
    notify(client, payment_id)
    del fake.fail["cancel"]
    monkeypatch.setattr(get_settings(), "payment_settle_after_seconds", 0)
    with get_session_factory()() as db:
        settle_stuck_payments(db, gateway=fake)
    assert fake.payments[payment_id]["status"] == "canceled"


def test_second_payment_of_a_paid_order_is_released(client, producer, owner_engine, fake):
    """Two payment pages were open; both got paid. The second hold is canceled, the order stays paid."""
    beat_id = _beat(client, owner_engine, producer)
    artist = _artist(client)
    order_id = _order(client, artist, [(beat_id, "basic", 1500)]).json()["order_id"]
    first = _pay(client, artist, order_id).json()["payment_id"]
    fake.decline(first)
    notify(client, first, "payment.canceled")
    second = _pay(client, artist, order_id).json()["payment_id"]
    fake.hold(second)
    notify(client, second)
    notify(client, second, "payment.succeeded")
    # the "declined" first payment turned out held after all (out-of-order statuses)
    fake.payments[first].update(status="waiting_for_capture")
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE payments SET status = 'pending' WHERE provider_payment_id = :p"), {"p": first})
        conn.execute(text("DELETE FROM payment_events WHERE provider_payment_id = :p"), {"p": first})
    notify(client, first)
    assert fake.count("cancel", first) == 1
    assert _scalar(owner_engine, "SELECT status FROM orders WHERE id = :o", o=order_id) == "paid"
