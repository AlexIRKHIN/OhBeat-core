"""Fulfillment: FR-26 (PDF contracts), FR-28 / NFR-8 (download links), REST API §2.10, §2.12;
GAP-32, GAP-43, GAP-64, GAP-69."""

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.common.config import get_settings
from app.common.storage import get_storage
from app.contracts.issue import MSK, mask_phone, render_pdf, stamp
from app.main import app
from app.orders.models import Contract
from tests.helpers import auth, make_producer
from tests.test_orders import _artist, _beat, _order
from tests.test_payments import _pay, fake, notify  # noqa: F401 — `fake` is a fixture


@pytest.fixture
def producer(client):
    return make_producer(client)


def _files(owner_engine, test_buckets, beat_id: int) -> None:
    """What Media Worker leaves in the private bucket for a published beat (slice 1)."""
    bucket = get_settings().bucket_private
    with owner_engine.begin() as conn:
        for kind, key in (("clean_mp3", f"beats/{beat_id}/clean.mp3"), ("master", f"beats/{beat_id}/master.wav"),
                          ("stems", f"beats/{beat_id}/stems.zip")):
            conn.execute(text("INSERT INTO beat_files (beat_id, kind, storage_key, size_bytes) VALUES (:b, :k, :s, 5) "
                              "ON CONFLICT (beat_id, kind) DO UPDATE SET storage_key = excluded.storage_key"),
                         {"b": beat_id, "k": kind, "s": key})
            test_buckets.put_object(Bucket=bucket, Key=key, Body=f"{kind}-{beat_id}".encode())


def _paid(client, fake, tokens, items) -> int:
    order_id = _order(client, tokens, items).json()["order_id"]
    payment_id = _pay(client, tokens, order_id).json()["payment_id"]
    fake.hold(payment_id)
    assert notify(client, payment_id).status_code == 200
    assert notify(client, payment_id, "payment.succeeded").status_code == 200
    return order_id


def _contracts(owner_engine, order_id: int):
    with owner_engine.connect() as conn:
        return conn.execute(text("SELECT c.* FROM contracts c JOIN order_items oi ON oi.id = c.order_item_id "
                                 "WHERE oi.order_id = :o ORDER BY oi.id"), {"o": order_id}).all()


# --- PDF contracts (FR-26) ---

def test_fr26_pdf_for_every_item_is_stored_with_its_hash(client, producer, owner_engine, fake, test_buckets):
    a = _beat(client, owner_engine, producer, title="Beat A")
    b = _beat(client, owner_engine, producer, title="Beat B")
    artist = _artist(client)
    order_id = _paid(client, fake, artist, [(a, "basic", 1500), (b, "premium", 3000)])

    contracts = _contracts(owner_engine, order_id)
    assert [c.pdf_key for c in contracts] == [f"contracts/{order_id}-1.pdf", f"contracts/{order_id}-2.pdf"]  # GAP-32
    for c in contracts:
        pdf = test_buckets.get_object(Bucket=get_settings().bucket_private, Key=c.pdf_key)["Body"].read()
        assert pdf.startswith(b"%PDF") and hashlib.sha256(pdf).hexdigest() == c.pdf_sha256
    with owner_engine.connect() as conn:
        generated = conn.execute(text("SELECT count(*) FROM audit_log WHERE action = 'contract.generated'")).scalar()
    assert generated == 2  # NFR-7


def test_gap43_repeated_success_gives_the_same_pdf(client, producer, owner_engine, fake):
    beat_id = _beat(client, owner_engine, producer)
    order_id = _paid(client, fake, _artist(client), [(beat_id, "basic", 1500)])
    first = _contracts(owner_engine, order_id)[0].pdf_sha256
    from app.common.db import get_session_factory
    from app.contracts.issue import issue_contracts
    from app.orders.models import Order

    with get_session_factory()() as db:  # as if the webhook were processed again after a crash
        issue_contracts(db, get_storage(), db.get(Order, order_id))
        db.commit()
    assert _contracts(owner_engine, order_id)[0].pdf_sha256 == first


def test_gap43_storage_failure_rolls_back_and_answers_500(client, producer, owner_engine, fake, monkeypatch):
    beat_id = _beat(client, owner_engine, producer)
    artist = _artist(client)
    order_id = _order(client, artist, [(beat_id, "basic", 1500)]).json()["order_id"]
    payment_id = _pay(client, artist, order_id).json()["payment_id"]
    fake.hold(payment_id)
    notify(client, payment_id)

    from app.common import storage as storage_module

    def broken(*_a, **_k):
        raise storage_module.StorageUnavailable("down")

    monkeypatch.setattr(storage_module.S3Storage, "put", broken)
    with TestClient(app, raise_server_exceptions=False) as raw:
        assert notify(raw, payment_id, "payment.succeeded").status_code == 500  # YooKassa will repeat
    with owner_engine.connect() as conn:
        assert conn.execute(text("SELECT status FROM orders WHERE id = :o"), {"o": order_id}).scalar() == "pending"
        assert conn.execute(text("SELECT count(*) FROM payment_events WHERE event = 'payment.succeeded'")).scalar() == 0
    monkeypatch.undo()
    assert notify(client, payment_id, "payment.succeeded").status_code == 200
    assert _contracts(owner_engine, order_id)[0].pdf_sha256 is not None


def test_fr26_contract_text_must_be_the_signed_one(client, producer, owner_engine, fake):
    """If the data changed after signing, the PDF is not made: it would not be what was accepted."""
    beat_id = _beat(client, owner_engine, producer)
    artist = _artist(client)
    order_id = _order(client, artist, [(beat_id, "basic", 1500)]).json()["order_id"]
    payment_id = _pay(client, artist, order_id).json()["payment_id"]
    fake.hold(payment_id)
    notify(client, payment_id)
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE contracts SET draft_sha256 = repeat('0', 64)"))
    with TestClient(app, raise_server_exceptions=False) as raw:
        assert notify(raw, payment_id, "payment.succeeded").status_code == 500


def test_fr26_stamps_and_determinism():
    snapshot = {"buyer": {"last_name": "Иванов", "first_name": "Иван", "middle_name": "Иванович", "user_id": 7,
                          "email": "a@example.com"},
                "licensors": {"3": {"display_name": "Kirill Beats", "pep_agreement_at": "2026-09-12T09:00:00+00:00"}}}
    signed = datetime(2026, 10, 4, 11, 22, 15, tzinfo=UTC)
    otp = Contract(signature_type="otp", draft_sha256="4a" * 32, signer_ip="1.2.3.4", signed_at=signed,
                   signer_phone="+79001234545")
    rows = dict(stamp(otp, snapshot, 3, "889900-1")["rows"])
    # RFC ПЭП §5: masked phone, Moscow time, the basis of the Producer's agreement, the full hash
    assert rows["Идентификатор ключа"] == "+7 (900) ***-**-45"
    assert rows["Дата и время (МСК)"] == "04.10.2026 14:22:15"
    assert rows["Основание"] == "соглашение о ПЭП от 12.09.2026"
    assert rows["SHA-256 проекта"] == "4a" * 32 and rows["Лицензиар"] == "Kirill Beats (ID 3)"

    offer = Contract(signature_type="offer_accept", draft_sha256="b" * 64, signer_ip="1.2.3.4", signed_at=signed)
    offer_stamp = stamp(offer, snapshot, 3, "889900-2")
    assert offer_stamp["title"] == "ДОГОВОР ЗАКЛЮЧЁН АКЦЕПТОМ ПУБЛИЧНОЙ ОФЕРТЫ"
    assert dict(offer_stamp["rows"])["IP-адрес"] == "1.2.3.4"
    assert render_pdf("Текст договора", offer_stamp, "889900-2") == render_pdf("Текст договора", offer_stamp, "889900-2")
    assert mask_phone(None) == "—"


# --- Download links (FR-28, NFR-8) ---

def test_fr28_links_follow_the_license_and_open(client, producer, owner_engine, fake, test_buckets):
    basic_beat = _beat(client, owner_engine, producer, title="Basic one")
    trackout_beat = _beat(client, owner_engine, producer, title="Trackout one")
    for b in (basic_beat, trackout_beat):
        _files(owner_engine, test_buckets, b)
    artist = _artist(client)
    order_id = _paid(client, fake, artist, [(basic_beat, "basic", 1500), (trackout_beat, "trackout", 6000)])

    body = client.get(f"/v1/orders/{order_id}/downloads", headers=auth(artist)).json()
    kinds = {i["beat_id"]: [f["kind"] for f in i["files"]] for i in body["items"]}
    assert kinds == {basic_beat: ["mp3", "contract"], trackout_beat: ["mp3", "wav", "stems", "contract"]}

    expires = datetime.fromisoformat(body["expires_at"])
    assert timedelta(minutes=59) < expires - datetime.now(UTC) <= timedelta(hours=1)
    first = body["items"][0]["files"][0]["url"]
    assert parse_qs(urlparse(first).query)["X-Amz-Expires"] == ["3600"]
    response = httpx.get(first)
    assert response.status_code == 200 and response.content == f"clean_mp3-{basic_beat}".encode()
    assert "attachment" in response.headers["content-disposition"]

    contract_url = body["items"][0]["files"][-1]["url"]
    pdf = httpx.get(contract_url).content
    assert hashlib.sha256(pdf).hexdigest() == _contracts(owner_engine, order_id)[0].pdf_sha256


def test_nfr8_link_lifetime_never_exceeds_an_hour(client, producer, owner_engine, fake, test_buckets, monkeypatch):
    beat_id = _beat(client, owner_engine, producer)
    _files(owner_engine, test_buckets, beat_id)
    artist = _artist(client)
    order_id = _paid(client, fake, artist, [(beat_id, "basic", 1500)])
    monkeypatch.setattr(get_settings(), "download_link_ttl_seconds", 7200)
    url = client.get(f"/v1/orders/{order_id}/downloads", headers=auth(artist)).json()["items"][0]["files"][0]["url"]
    assert parse_qs(urlparse(url).query)["X-Amz-Expires"] == ["3600"]


def test_fr28_only_the_owner_of_a_paid_order(client, producer, owner_engine, fake):
    beat_id = _beat(client, owner_engine, producer)
    artist = _artist(client)
    unpaid = _order(client, artist, [(beat_id, "basic", 1500)]).json()["order_id"]
    response = client.get(f"/v1/orders/{unpaid}/downloads", headers=auth(artist))
    assert (response.status_code, response.json()["error_code"]) == (409, "ORDER_NOT_PAID")

    paid = _paid(client, fake, artist, [(beat_id, "premium", 3000)])
    stranger = _artist(client, email="stranger@example.com")
    assert client.get(f"/v1/orders/{paid}/downloads", headers=auth(stranger)).status_code == 403
    assert client.get(f"/v1/orders/{paid}/downloads").status_code == 401


def test_nfr20_files_stay_available_after_the_beat_is_deleted(client, producer, owner_engine, fake, test_buckets):
    beat_id = _beat(client, owner_engine, producer)
    _files(owner_engine, test_buckets, beat_id)
    artist = _artist(client)
    order_id = _paid(client, fake, artist, [(beat_id, "basic", 1500)])
    assert client.delete(f"/v1/beats/{beat_id}", headers=auth(producer)).status_code == 204
    files = client.get(f"/v1/orders/{order_id}/downloads", headers=auth(artist)).json()["items"][0]["files"]
    assert [f["kind"] for f in files] == ["mp3", "contract"]


# --- My purchases (REST API §2.12) ---

def test_my_purchases_lists_paid_items_with_date_and_hash(client, producer, owner_engine, fake):
    a = _beat(client, owner_engine, producer, title="Beat A")
    b = _beat(client, owner_engine, producer, title="Beat B")
    artist = _artist(client)
    paid = _paid(client, fake, artist, [(a, "basic", 1500), (b, "premium", 3000)])
    _order(client, artist, [(a, "trackout", 6000)])  # not paid: not shown

    items = client.get("/v1/users/me/purchases", headers=auth(artist)).json()["items"]
    assert [(i["order_id"], i["contract_number"], i["license"]) for i in items] == [
        (paid, f"{paid}-1", "basic"), (paid, f"{paid}-2", "premium")]
    assert all(i["paid_at"] and len(i["pdf_sha256"]) == 64 for i in items)
    assert items[0]["producer"] == "Ivan Artist" and items[0]["price"] == 1500 and items[0]["service_fee"] == 150
    assert client.get("/v1/users/me/purchases", headers=auth(producer)).json()["items"] == []


# --- My sales (REST API §2.10, UC-14) ---

def test_uc14_sales_for_a_period(client, producer, owner_engine, fake):
    second = make_producer(client, email="producer2@example.com")
    mine = _beat(client, owner_engine, producer, title="Mine")
    theirs = _beat(client, owner_engine, second, title="Theirs")
    artist = _artist(client)
    old = _paid(client, fake, artist, [(mine, "basic", 1500)])
    _paid(client, fake, artist, [(mine, "premium", 3000), (theirs, "basic", 1500)])
    with owner_engine.begin() as conn:  # the first sale happened 40 days ago
        conn.execute(text("UPDATE payment_events SET received_at = now() - interval '40 days' "
                          "WHERE provider_payment_id IN (SELECT provider_payment_id FROM payments WHERE order_id = :o)"), {"o": old})

    recent = client.get("/v1/users/me/sales", headers=auth(producer)).json()  # last 30 days
    assert [(s["title"], s["license"], s["price"]) for s in recent["items"]] == [("Mine", "premium", 3000)]
    assert (recent["count"], recent["total"]) == (1, 3000)  # the Producer's price, no service fee

    today = datetime.now(MSK).date()
    whole = client.get("/v1/users/me/sales", params={"from": str(today - timedelta(days=60)), "to": str(today)},
                       headers=auth(producer)).json()
    assert (whole["count"], Decimal(str(whole["total"]))) == (2, Decimal("4500"))


def test_uc14_sales_access_and_period_checks(client, producer):
    artist = _artist(client)
    assert client.get("/v1/users/me/sales", headers=auth(artist)).status_code == 403
    reversed_period = client.get("/v1/users/me/sales", params={"from": "2026-10-10", "to": "2026-10-01"}, headers=auth(producer))
    assert (reversed_period.status_code, reversed_period.json()["details"][0]["field"]) == (400, "from")
    too_long = client.get("/v1/users/me/sales", params={"from": "2024-01-01", "to": "2026-01-01"}, headers=auth(producer))
    assert too_long.status_code == 400


def test_gap43_pdf_is_the_same_in_another_process():
    """A repeated webhook may be processed by another process (after a restart): the bytes and so
    pdf_sha256 must not depend on it. Each run is a fresh interpreter without SOURCE_DATE_EPOCH."""
    import os
    import subprocess
    import sys

    code = ("import hashlib; from app.contracts.issue import render_pdf; "
            "print(hashlib.sha256(render_pdf('Текст', {'title': 'T', 'rows': [('Лицензиат', 'Иванов')]}, '1-1')).hexdigest())")
    env = {k: v for k, v in os.environ.items() if k != "SOURCE_DATE_EPOCH"}
    runs = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True).stdout
            for _ in range(2)}
    assert len(runs) == 1
