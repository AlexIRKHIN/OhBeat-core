"""The mock must behave like YooKassa by its contract, including the bad days (CLAUDE.md)."""

import base64
import uuid

import pytest
from fastapi.testclient import TestClient

from mock import main, store, webhooks

SHOP, SECRET = "123456", "test_secret"


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("YOOKASSA_SHOP_ID", SHOP)
    monkeypatch.setenv("YOOKASSA_SECRET_KEY", SECRET)
    monkeypatch.setenv("MOCK_TIMEOUT_SECONDS", "0")
    store.connect(str(tmp_path / "mock.sqlite3"))


@pytest.fixture
def sent(monkeypatch):
    """Webhooks are recorded instead of sent."""
    calls = []
    monkeypatch.setattr(webhooks, "send", lambda payment, event: calls.append((event, payment["status"])))
    return calls


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def headers(key: str | None = None) -> dict:
    token = base64.b64encode(f"{SHOP}:{SECRET}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Idempotence-Key": key or str(uuid.uuid4())}


def payment_body(amount="4950.00", transfers=(("mock-seller-1", "1500.00"), ("mock-seller-2", "3000.00")), fee="450.00"):
    return {
        "amount": {"value": amount, "currency": "RUB"},
        "capture": False,
        "confirmation": {"type": "redirect", "return_url": "http://localhost:5173/orders/1/return"},
        "metadata": {"order_id": "1", "platform_fee": fee},
        "transfers": [{"account_id": a, "amount": {"value": v, "currency": "RUB"}} for a, v in transfers],
    }


def test_auth_is_required(client):
    response = client.post("/v3/payments", json=payment_body(), headers={"Idempotence-Key": "k"})
    assert (response.status_code, response.json()["code"]) == (401, "invalid_credentials")


def test_create_returns_pending_payment_with_confirmation_url(client):
    payment = client.post("/v3/payments", json=payment_body(), headers=headers()).json()
    assert payment["status"] == "pending" and payment["paid"] is False
    assert payment["confirmation"]["confirmation_url"].endswith(f"/checkout/{payment['id']}")
    assert [t["status"] for t in payment["transfers"]] == ["pending", "pending"]


def test_same_idempotence_key_returns_the_same_payment(client):
    key = str(uuid.uuid4())
    first = client.post("/v3/payments", json=payment_body(), headers=headers(key)).json()
    second = client.post("/v3/payments", json=payment_body(), headers=headers(key)).json()
    assert first["id"] == second["id"]
    assert len(store.list_payments()) == 1


def test_idempotence_key_is_required(client):
    h = headers()
    del h["Idempotence-Key"]
    assert client.post("/v3/payments", json=payment_body(), headers=h).status_code == 400


def test_fr30_wrong_split_is_refused(client):
    """Σ transfers + platform fee must equal the amount (GAP-41)."""
    response = client.post("/v3/payments", json=payment_body(fee="449.99"), headers=headers())
    assert (response.status_code, response.json()["parameter"]) == (400, "transfers")
    assert client.post("/v3/payments", json=payment_body(amount="4950.01"), headers=headers()).status_code == 400


def test_kopecks_in_split(client):
    body = payment_body(amount="5340.50", transfers=(("a", "3255.00"), ("b", "1600.00")), fee="485.50")
    assert client.post("/v3/payments", json=body, headers=headers()).status_code == 200


def test_two_stage_payment_success(client, sent):
    payment = client.post("/v3/payments", json=payment_body(), headers=headers()).json()
    page = client.post(f"/checkout/{payment['id']}", data={"outcome": "success"}, follow_redirects=False)
    assert page.status_code == 303 and page.headers["location"].endswith("/orders/1/return")
    assert sent == [("payment.waiting_for_capture", "waiting_for_capture")]

    captured = client.post(f"/v3/payments/{payment['id']}/capture", json={}, headers=headers()).json()
    assert captured["status"] == "succeeded"
    assert [t["status"] for t in captured["transfers"]] == ["succeeded", "succeeded"]
    assert sent[-1] == ("payment.succeeded", "succeeded")


def test_bank_decline_and_cancel_after_hold(client, sent):
    declined = client.post("/v3/payments", json=payment_body(), headers=headers()).json()
    client.post(f"/checkout/{declined['id']}", data={"outcome": "decline"})
    got = client.get(f"/v3/payments/{declined['id']}", headers=headers()).json()
    assert (got["status"], got["cancellation_details"]["reason"]) == ("canceled", "insufficient_funds")

    held = client.post("/v3/payments", json=payment_body(), headers=headers()).json()
    client.post(f"/checkout/{held['id']}", data={"outcome": "success"})
    canceled = client.post(f"/v3/payments/{held['id']}/cancel", headers=headers()).json()
    assert (canceled["status"], canceled["cancellation_details"]["reason"]) == ("canceled", "canceled_by_merchant")
    assert sent[-1] == ("payment.canceled", "canceled")


def test_silent_hold_sends_no_webhook(client, sent):
    payment = client.post("/v3/payments", json=payment_body(), headers=headers()).json()
    client.post(f"/checkout/{payment['id']}", data={"outcome": "silent"})
    assert client.get(f"/v3/payments/{payment['id']}", headers=headers()).json()["status"] == "waiting_for_capture"
    assert sent == []


def test_capture_of_canceled_payment_is_a_final_error(client, sent):
    payment = client.post("/v3/payments", json=payment_body(), headers=headers()).json()
    client.post(f"/checkout/{payment['id']}", data={"outcome": "success"})
    client.post(f"/admin/payments/{payment['id']}/expire-hold")
    response = client.post(f"/v3/payments/{payment['id']}/capture", json={}, headers=headers())
    assert (response.status_code, response.json()["code"]) == (400, "invalid_request")


@pytest.mark.parametrize(("kind", "status"), [("500", 500), ("429", 429)])
def test_faults_break_the_next_requests(client, kind, status):
    client.post("/admin/fault", data={"operation": "create", "kind": kind, "count": 2})
    key = str(uuid.uuid4())
    assert client.post("/v3/payments", json=payment_body(), headers=headers(key)).status_code == status
    assert client.post("/v3/payments", json=payment_body(), headers=headers(key)).status_code == status
    assert client.post("/v3/payments", json=payment_body(), headers=headers(key)).status_code == 200
    assert len(store.list_payments()) == 1  # broken requests did nothing


def test_timeout_fault_creates_the_payment_and_retry_with_same_key_gets_it(client):
    client.post("/admin/fault", data={"operation": "create", "kind": "timeout", "count": 1})
    key = str(uuid.uuid4())
    late = client.post("/v3/payments", json=payment_body(), headers=headers(key)).json()  # the client "lost" this
    again = client.post("/v3/payments", json=payment_body(), headers=headers(key)).json()
    assert late["id"] == again["id"] and len(store.list_payments()) == 1


def test_webhook_is_retried_until_200(monkeypatch):
    answers = iter([500, 503, 200])
    monkeypatch.setattr(webhooks, "RETRY_DELAYS", [0, 0, 0])
    monkeypatch.setattr(webhooks.httpx, "post", lambda *a, **k: type("R", (), {"status_code": next(answers)})())
    assert webhooks.deliver({"id": "p1"}, "payment.succeeded") is True
    assert [d["result"] for d in store.list_deliveries()] == ["200", "503", "500"]


def test_admin_page_renders(client):
    client.post("/v3/payments", json=payment_body(), headers=headers())
    assert "Пульт мока" in client.get("/admin").text
