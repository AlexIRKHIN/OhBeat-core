"""Cart and orders: REST API §2.5, §2.6, §2.11; FR-14 … FR-19, FR-29, FR-30, FR-32.

The race of buyers for one Exclusive runs on the real PostgreSQL: several requests at the same
time, and a deterministic variant that holds the row lock to show what the second transaction does.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.common.db import get_session_factory
from app.contracts.draft import DraftItem, render_draft, sha256_text
from app.orders.expiry import expire_reservations
from app.orders.schemas import OrderCreate
from app.orders.service import create_order
from tests.helpers import VALID_BILLING, auth, beat_body, make_producer, register


@pytest.fixture
def producer(client):
    return make_producer(client)


def _beat(client, owner_engine, tokens, status: str = "active", **overrides) -> int:
    beat_id = client.post("/v1/beats", json=beat_body(**overrides), headers=auth(tokens)).json()["id"]
    with owner_engine.begin() as conn:
        if status == "reserved":  # CHECK in schema.sql: a reserved beat names its order and the deadline
            _reserve(conn, beat_id)
        else:
            conn.execute(text("UPDATE beats SET status = :s WHERE id = :id"), {"s": status, "id": beat_id})
        conn.execute(text("UPDATE beats SET published_at = now() WHERE id = :id"), {"id": beat_id})
    return beat_id


def _reserve(conn, beat_id: int) -> None:
    """Reserves the beat for a stand-in order of its own Producer (not committed until the caller commits)."""
    order_id = conn.execute(text("INSERT INTO orders (customer_id, status, total_amount, billing_snapshot) "
                                 "SELECT producer_id, 'pending', 100, '{}' FROM beats WHERE id = :id RETURNING id"),
                            {"id": beat_id}).scalar()
    conn.execute(text("UPDATE beats SET status = 'reserved', reserved_order_id = :o, "
                      "reserved_until = now() + interval '15 minutes' WHERE id = :id"),
                 {"o": order_id, "id": beat_id})


def _artist(client, email: str = "artist@example.com", billing: dict | None = VALID_BILLING) -> dict:
    tokens = register(client, email=email)
    if billing is not None:
        assert client.put("/v1/users/me/billing", json=billing, headers=auth(tokens)).status_code == 200
    return tokens


def _order(client, tokens, items: list[tuple[int, str, int | float]], offer: bool = True):
    body = {"items": [{"beat_id": b, "license": lic, "expected_price": p} for b, lic, p in items],
            "offer_accepted": offer}
    return client.post("/v1/orders", json=body, headers=auth(tokens))


def _beat_row(owner_engine, beat_id: int):
    with owner_engine.connect() as conn:
        return conn.execute(text("SELECT status, reserved_order_id, reserved_until FROM beats WHERE id = :id"),
                            {"id": beat_id}).one()


def _set_status(owner_engine, beat_id: int, status: str) -> None:
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE beats SET status = :s WHERE id = :id"), {"s": status, "id": beat_id})


# --- Cart (FR-14, FR-15, FR-19) ---

def test_fr14_put_replaces_license_and_cart_shows_fee_and_total(client, producer, owner_engine):
    beat_id = _beat(client, owner_engine, producer)
    artist = _artist(client)

    assert client.put(f"/v1/cart/items/{beat_id}", json={"license": "basic"}, headers=auth(artist)).status_code == 200
    cart = client.put(f"/v1/cart/items/{beat_id}", json={"license": "premium"}, headers=auth(artist)).json()

    assert [(i["beat_id"], i["license"], i["price"], i["service_fee"]) for i in cart["items"]] == [(beat_id, "premium", 3000, 300)]
    assert (cart["items_total"], cart["service_fee"], cart["total"]) == (3000, 300, 3300)  # FR-30: fee on top
    assert cart["items"][0]["producer"] == "Ivan Artist" and cart["items"][0]["available"] is True


def test_fr14_delete_cart_item(client, producer, owner_engine):
    beat_id = _beat(client, owner_engine, producer)
    artist = _artist(client)
    client.put(f"/v1/cart/items/{beat_id}", json={"license": "basic"}, headers=auth(artist))

    assert client.delete(f"/v1/cart/items/{beat_id}", headers=auth(artist)).status_code == 204
    assert client.get("/v1/cart", headers=auth(artist)).json()["items"] == []


def test_cart_needs_sign_in(client):
    assert client.get("/v1/cart").status_code == 401


@pytest.mark.parametrize(("status", "code"), [
    ("reserved", "BEAT_RESERVED"),  # FR-19
    ("sold", "BEAT_SOLD"),
    ("hidden", "BEAT_NOT_AVAILABLE"),
    ("processing", "BEAT_NOT_AVAILABLE"),
])
def test_fr14_fr19_cannot_add_unavailable_beat(client, producer, owner_engine, status, code):
    beat_id = _beat(client, owner_engine, producer, status=status)
    response = client.put(f"/v1/cart/items/{beat_id}", json={"license": "basic"}, headers=auth(_artist(client)))
    assert (response.status_code, response.json()["error_code"]) == (409, code)


@pytest.mark.parametrize("status", ["uploading", "deleted"])
def test_cart_unknown_beat_is_not_found(client, producer, owner_engine, status):
    beat_id = _beat(client, owner_engine, producer, status=status)
    response = client.put(f"/v1/cart/items/{beat_id}", json={"license": "basic"}, headers=auth(_artist(client)))
    assert response.status_code == 404


def test_cart_license_inactive_and_own_beat(client, producer, owner_engine):
    beat_id = _beat(client, owner_engine, producer)
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE beat_prices SET is_active = false WHERE beat_id = :id AND license_id = "
                          "(SELECT id FROM licenses WHERE code = 'premium')"), {"id": beat_id})
    artist = _artist(client)
    response = client.put(f"/v1/cart/items/{beat_id}", json={"license": "premium"}, headers=auth(artist))
    assert response.json()["error_code"] == "LICENSE_INACTIVE"
    # ASSUMPTION: GAP-26 — a Producer cannot buy their own beat
    response = client.put(f"/v1/cart/items/{beat_id}", json={"license": "basic"}, headers=auth(producer))
    assert (response.status_code, response.json()["error_code"]) == (409, "OWN_BEAT")


def test_fr14_cart_marks_beat_reserved_later_and_excludes_it_from_total(client, producer, owner_engine):
    a = _beat(client, owner_engine, producer, title="Beat A")
    b = _beat(client, owner_engine, producer, title="Beat B")
    artist = _artist(client)
    client.put(f"/v1/cart/items/{a}", json={"license": "basic"}, headers=auth(artist))
    client.put(f"/v1/cart/items/{b}", json={"license": "basic"}, headers=auth(artist))
    _set_status(owner_engine, b, "sold")

    cart = client.get("/v1/cart", headers=auth(artist)).json()
    assert {i["beat_id"]: i["unavailable_reason"] for i in cart["items"]} == {a: None, b: "BEAT_SOLD"}
    assert cart["total"] == 1650


def test_gap66_cart_shows_own_reservation_as_in_your_order(client, producer, owner_engine):
    beat_id = _beat(client, owner_engine, producer)
    artist = _artist(client)
    client.put(f"/v1/cart/items/{beat_id}", json={"license": "exclusive"}, headers=auth(artist))
    order_id = _order(client, artist, [(beat_id, "exclusive", 25000)]).json()["order_id"]

    mine = client.get("/v1/cart", headers=auth(artist)).json()["items"][0]
    assert (mine["unavailable_reason"], mine["order_id"]) == ("IN_YOUR_ORDER", order_id)
    other = _artist(client, email="other@example.com")
    client.put(f"/v1/cart/items/{beat_id}", json={"license": "basic"}, headers=auth(other))  # 409, not added
    with owner_engine.begin() as conn:
        conn.execute(text("INSERT INTO cart_items (user_id, beat_id, license_id) SELECT u.id, :b, 1 FROM users u "
                          "WHERE u.email = 'other@example.com'"), {"b": beat_id})
    theirs = client.get("/v1/cart", headers=auth(other)).json()["items"][0]
    assert (theirs["unavailable_reason"], theirs["order_id"]) == ("BEAT_RESERVED", None)


# --- Creating an order ---

def test_fr15_fr30_fr32_order_for_two_producers(client, producer, owner_engine):
    """The example of slice-3-plan §5: 1 500 + 3 000, fee 10 % on top → 4 950.00."""
    second = make_producer(client, email="producer2@example.com")
    a = _beat(client, owner_engine, producer)
    b = _beat(client, owner_engine, second)
    artist = _artist(client)

    response = _order(client, artist, [(a, "basic", 1500), (b, "premium", 3000)])
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["status"], body["items_total"], body["service_fee"], body["total"]) == ("pending", 4500, 450, 4950)
    assert body["requires_signature"] is False and body["reserved_until"] is None

    with owner_engine.connect() as conn:
        items = conn.execute(text("SELECT beat_id, producer_id, price_at_purchase, platform_fee FROM order_items "
                                  "WHERE order_id = :o ORDER BY id"), {"o": body["order_id"]}).all()
        snapshot = conn.execute(text("SELECT billing_snapshot FROM orders WHERE id = :o"), {"o": body["order_id"]}).scalar()
        contracts = conn.execute(text("SELECT signature_type, draft_sha256, signer_ip FROM contracts")).all()
        actions = conn.execute(text("SELECT action FROM audit_log WHERE entity = 'order' ORDER BY id")).scalars().all()
    assert [(i.price_at_purchase, i.platform_fee) for i in items] == [(Decimal("1500.00"), Decimal("150.00")),
                                                                     (Decimal("3000.00"), Decimal("300.00"))]
    # FR-32: buyer and both licensors frozen in the order (GAP-8)
    assert snapshot["buyer"]["last_name"] == "Иванов"
    assert sorted(snapshot["licensors"]) == sorted(str(i.producer_id) for i in items)
    # FR-16: Basic / Premium — contracts by offer acceptance, one per item
    assert [c.signature_type for c in contracts] == ["offer_accept", "offer_accept"]
    assert all(len(c.draft_sha256) == 64 for c in contracts)
    assert actions == ["order.created", "offer.accepted"]


def test_fr30_fee_is_rounded_to_kopecks_per_item(client, producer, owner_engine):
    beat_id = _beat(client, owner_engine, producer)
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE beat_prices SET price = 999.95 WHERE beat_id = :id"), {"id": beat_id})
    body = _order(client, _artist(client), [(beat_id, "basic", 999.95)]).json()
    assert (body["service_fee"], body["total"]) == (100.0, 1099.95)  # 99.995 → 100.00 (GAP-42)


def test_fr18_exclusive_order_reserves_beat_for_15_minutes(client, producer, owner_engine):
    beat_id = _beat(client, owner_engine, producer)
    response = _order(client, _artist(client), [(beat_id, "exclusive", 25000)])
    assert response.status_code == 201, response.text
    body = response.json()

    row = _beat_row(owner_engine, beat_id)
    assert (row.status, row.reserved_order_id) == ("reserved", body["order_id"])
    left = row.reserved_until - datetime.now(UTC)
    assert timedelta(minutes=14) < left <= timedelta(minutes=15)
    assert body["requires_signature"] is True and body["total"] == 27500
    with owner_engine.connect() as conn:  # Exclusive is signed with a code later (slice 4)
        assert conn.execute(text("SELECT count(*) FROM contracts")).scalar() == 0


def test_fr15_price_changed_returns_new_prices_and_creates_nothing(client, producer, owner_engine):
    beat_id = _beat(client, owner_engine, producer)
    response = _order(client, _artist(client), [(beat_id, "basic", 1000)])
    assert (response.status_code, response.json()["error_code"]) == (409, "PRICE_CHANGED")
    detail = response.json()["details"][0]
    assert (detail["beat_id"], detail["license"], detail["price"]) == (beat_id, "basic", 1500)
    with owner_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM orders")).scalar() == 0


def test_billing_required_and_phone_required_for_exclusive(client, producer, owner_engine):
    beat_id = _beat(client, owner_engine, producer)
    no_billing = _artist(client, billing=None)
    assert _order(client, no_billing, [(beat_id, "basic", 1500)]).json()["error_code"] == "BILLING_REQUIRED"

    no_phone = _artist(client, email="nophone@example.com", billing={**VALID_BILLING, "phone": None})
    assert _order(client, no_phone, [(beat_id, "basic", 1500)]).status_code == 201  # a lease needs no phone
    response = _order(client, no_phone, [(beat_id, "exclusive", 25000)])
    assert response.json()["error_code"] == "BILLING_REQUIRED"
    assert response.json()["details"][0]["field"] == "phone"


def test_fr16_offer_must_be_accepted(client, producer, owner_engine):
    beat_id = _beat(client, owner_engine, producer)
    assert _order(client, _artist(client), [(beat_id, "basic", 1500)], offer=False).status_code == 400


def test_order_own_beat_and_inactive_license(client, producer, owner_engine):
    beat_id = _beat(client, owner_engine, producer)
    assert _order(client, producer, [(beat_id, "basic", 1500)]).json()["error_code"] == "OWN_BEAT"
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE beat_prices SET is_active = false WHERE beat_id = :id"), {"id": beat_id})
    assert _order(client, _artist(client), [(beat_id, "basic", 1500)]).json()["error_code"] == "LICENSE_INACTIVE"


def test_fr19_no_lease_of_a_reserved_beat(client, producer, owner_engine):
    beat_id = _beat(client, owner_engine, producer)
    assert _order(client, _artist(client), [(beat_id, "exclusive", 25000)]).status_code == 201
    other = _artist(client, email="other@example.com")
    response = _order(client, other, [(beat_id, "basic", 1500)])
    assert (response.status_code, response.json()["error_code"]) == (409, "BEAT_RESERVED")


def test_fr18_failed_reservation_rolls_back_the_whole_order(client, producer, owner_engine):
    """Two items, the second is taken: no order, no items, the first beat is not reserved."""
    free = _beat(client, owner_engine, producer, title="Free one")
    taken = _beat(client, owner_engine, producer, title="Taken one")
    assert _order(client, _artist(client, email="first@example.com"), [(taken, "exclusive", 25000)]).status_code == 201
    response = _order(client, _artist(client), [(free, "exclusive", 25000), (taken, "exclusive", 25000)])
    assert response.json()["error_code"] == "BEAT_RESERVED"
    assert _beat_row(owner_engine, free).status == "active"
    with owner_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM orders")).scalar() == 1


# --- The race for one Exclusive (FR-18) ---

@pytest.mark.parametrize("buyers", [2, 10])
def test_fr18_race_of_buyers_for_one_exclusive(client, producer, owner_engine, buyers):
    beat_id = _beat(client, owner_engine, producer)
    artists = [_artist(client, email=f"buyer{i}@example.com") for i in range(buyers)]
    start = threading.Barrier(buyers)

    def buy(tokens):
        start.wait()  # all requests leave at the same moment
        return _order(client, tokens, [(beat_id, "exclusive", 25000)])

    with ThreadPoolExecutor(max_workers=buyers) as pool:
        responses = list(pool.map(buy, artists))

    codes = sorted((r.status_code, r.json().get("error_code")) for r in responses)
    assert codes == [(201, None)] + [(409, "BEAT_RESERVED")] * (buyers - 1)
    winner = next(r.json()["order_id"] for r in responses if r.status_code == 201)
    assert _beat_row(owner_engine, beat_id).reserved_order_id == winner
    with owner_engine.connect() as conn:  # losers left nothing behind
        assert conn.execute(text("SELECT count(*) FROM orders")).scalar() == 1


def test_fr18_second_transaction_waits_for_the_lock_and_finds_reserved(client, producer, owner_engine):
    """Deterministic: transaction A has reserved the beat but not committed. B has already passed its
    checks (it still sees `active`), reaches the UPDATE and waits. A commits → B re-reads the row,
    sees `reserved`, updates nothing → 409 BEAT_RESERVED."""
    beat_id = _beat(client, owner_engine, producer)
    buyer_id = client.get("/v1/users/me", headers=auth(_artist(client))).json()["id"]
    data = OrderCreate(items=[{"beat_id": beat_id, "license": "exclusive", "expected_price": 25000}], offer_accepted=True)

    holder = owner_engine.connect()
    tx = holder.begin()
    _reserve(holder, beat_id)

    result: dict = {}

    def second_buyer():
        with get_session_factory()() as db:
            try:
                create_order(db, buyer_id, data, "127.0.0.1")
                result["code"] = "created"
            except Exception as error:  # ApiError
                result["code"] = getattr(error, "error_code", repr(error))

    thread = threading.Thread(target=second_buyer)
    thread.start()
    thread.join(timeout=2)
    assert thread.is_alive(), "B must be waiting for the row lock held by A"
    tx.commit()
    holder.close()
    thread.join(timeout=10)
    assert result["code"] == "BEAT_RESERVED"


# --- FR-29: the scheduler ---

def _age_order(owner_engine, order_id: int, hours: int) -> None:
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE orders SET created_at = now() - make_interval(hours => :h) WHERE id = :id"),
                     {"h": hours, "id": order_id})


def test_fr29_expired_reservation_releases_beat_and_expires_order(client, producer, owner_engine):
    beat_id = _beat(client, owner_engine, producer)
    order_id = _order(client, _artist(client), [(beat_id, "exclusive", 25000)]).json()["order_id"]
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE beats SET reserved_until = now() - interval '1 second' WHERE id = :id"), {"id": beat_id})

    with get_session_factory()() as db:
        assert expire_reservations(db) == 1

    row = _beat_row(owner_engine, beat_id)
    assert (row.status, row.reserved_order_id, row.reserved_until) == ("active", None, None)
    with owner_engine.connect() as conn:
        assert conn.execute(text("SELECT status FROM orders WHERE id = :id"), {"id": order_id}).scalar() == "expired"


def test_fr29_live_reservation_and_sold_beat_are_left_alone(client, producer, owner_engine):
    live = _beat(client, owner_engine, producer, title="Live")
    sold = _beat(client, owner_engine, producer, title="Sold")
    artist = _artist(client)
    _order(client, artist, [(live, "exclusive", 25000)])
    _order(client, artist, [(sold, "exclusive", 25000)])
    with owner_engine.begin() as conn:  # sold meanwhile by FR-23 (a sale clears the reservation fields)
        conn.execute(text("UPDATE beats SET status = 'sold', reserved_order_id = NULL, reserved_until = NULL WHERE id = :id"),
                     {"id": sold})

    with get_session_factory()() as db:
        assert expire_reservations(db) == 0
    assert _beat_row(owner_engine, live).status == "reserved"
    assert _beat_row(owner_engine, sold).status == "sold"


def test_fr29_unpaid_order_without_exclusive_expires_after_24_hours(client, producer, owner_engine):
    a = _beat(client, owner_engine, producer, title="Beat A")
    b = _beat(client, owner_engine, producer, title="Beat B")
    artist = _artist(client)
    old = _order(client, artist, [(a, "basic", 1500)]).json()["order_id"]
    fresh = _order(client, artist, [(a, "premium", 3000)]).json()["order_id"]
    old_exclusive = _order(client, artist, [(b, "exclusive", 25000)]).json()["order_id"]
    _age_order(owner_engine, old, 25)
    _age_order(owner_engine, old_exclusive, 25)  # query 2 skips orders with Exclusive: query 1 handles them

    with get_session_factory()() as db:
        expire_reservations(db)

    with owner_engine.connect() as conn:
        statuses = dict(conn.execute(text("SELECT id, status FROM orders")).all())
    assert statuses == {old: "expired", fresh: "pending", old_exclusive: "pending"}


# --- Reading an order ---

def test_get_order_only_for_owner(client, producer, owner_engine):
    beat_id = _beat(client, owner_engine, producer)
    artist = _artist(client)
    order_id = _order(client, artist, [(beat_id, "exclusive", 25000)]).json()["order_id"]

    body = client.get(f"/v1/orders/{order_id}", headers=auth(artist)).json()
    assert (body["status"], body["total"], body["requires_signature"], body["signed"]) == ("pending", 27500, True, False)
    assert body["items"][0]["contract_number"] == f"{order_id}-1" and body["reserved_until"] is not None
    assert body["payment_status"] is None

    stranger = _artist(client, email="stranger@example.com")
    assert client.get(f"/v1/orders/{order_id}", headers=auth(stranger)).status_code == 403
    assert client.get("/v1/orders/999999", headers=auth(artist)).status_code == 404


# --- Contract text (FR-26, GAP-9) ---

def test_fr26_contract_draft_is_deterministic_and_uses_snapshot():
    snapshot = {
        "buyer": {**VALID_BILLING, "user_id": 7},
        "licensors": {"3": {**VALID_BILLING, "last_name": "Петров", "user_id": 3, "display_name": "DJ Petrov"}},
    }
    item = DraftItem(order_id=10, number="10-1", beat={"id": 5, "title": "Neon Nights", "bpm": 120, "musical_key": "Dm"},
                     license_code="basic", license_name="Basic", license_files="MP3 320 кбит/с",
                     price=Decimal("1500.00"), fee=Decimal("150.00"), producer_id=3)
    text_one = render_draft(item, snapshot, "offer_accept")
    assert "10-1" in text_one and "Петров" in text_one and "Иванов" in text_one and "1500.00" in text_one
    assert sha256_text(text_one) == sha256_text(render_draft(item, snapshot, "offer_accept"))
    assert sha256_text(text_one) != sha256_text(render_draft(item, snapshot, "otp"))
