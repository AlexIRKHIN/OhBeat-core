"""Signature of Exclusive by SMS code: RFC ПЭП §3–§6, NFR-31, NFR-7, FR-26; GAP-9, GAP-28, GAP-33,
GAP-34, GAP-70, GAP-72, GAP-73.

"The clock" is moved by shifting created_at / expires_at of the codes in the database: the service
takes the time from the database, so this is the same as waiting.
"""

import hashlib
import hmac
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.common.config import get_settings
from app.main import app
from app.notifications.service import SmsUnavailable, get_notifier
from tests.helpers import VALID_BILLING, auth, make_producer
from tests.test_orders import _artist, _beat, _beat_row, _order
from tests.test_payments import _pay, fake, notify  # noqa: F401 — `fake` is a fixture
from tests.test_purchases import _files


class FakeNotifier:
    def __init__(self) -> None:
        self.sms: list[tuple[str, str]] = []
        self.emails: list[tuple[str, str, str]] = []
        self.down = False

    def send_email(self, to: str, subject: str, body: str) -> None:
        self.emails.append((to, subject, body))

    def send_sms(self, phone: str, text: str) -> None:
        if self.down:
            raise SmsUnavailable("down")
        self.sms.append((phone, text))

    def last_code(self) -> str:
        return re.search(r"код (\d{6})", self.sms[-1][1]).group(1)


@pytest.fixture
def sms():
    notifier = FakeNotifier()
    app.dependency_overrides[get_notifier] = lambda: notifier
    yield notifier
    app.dependency_overrides.pop(get_notifier, None)


@pytest.fixture
def producer(client):
    return make_producer(client)


@pytest.fixture
def exclusive(client, producer, owner_engine):
    """An Artist and an order with one Exclusive: (tokens, order_id, beat_id)."""
    beat_id = _beat(client, owner_engine, producer)
    artist = _artist(client)
    order_id = _order(client, artist, [(beat_id, "exclusive", 25000)]).json()["order_id"]
    return artist, order_id, beat_id


def _send(client, tokens, order_id):
    return client.post(f"/v1/orders/{order_id}/signature/otp", headers=auth(tokens))


def _verify(client, tokens, order_id, code):
    return client.post(f"/v1/orders/{order_id}/signature/verify", json={"code": code}, headers=auth(tokens))


def _wrong(code: str) -> str:
    return f"{(int(code) + 1) % 10**6:06d}"


def _age_codes(owner_engine, seconds: int) -> None:
    """As if `seconds` passed since every code was sent."""
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE signature_otps SET created_at = created_at - make_interval(secs => :s), "
                          "expires_at = expires_at - make_interval(secs => :s)"), {"s": seconds})


def _scalar(owner_engine, sql, **params):
    with owner_engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


# --- The draft (RFC §3 p. 2, REST API §2.12) ---

def test_contract_draft_is_shown_before_the_code(client, producer, owner_engine):
    a = _beat(client, owner_engine, producer, title="Beat A")
    b = _beat(client, owner_engine, producer, title="Beat B")
    artist = _artist(client)
    order_id = _order(client, artist, [(a, "basic", 1500), (b, "exclusive", 25000)]).json()["order_id"]

    body = client.get(f"/v1/orders/{order_id}/contract-draft", headers=auth(artist)).json()
    assert [(i["title"], i["contract_number"], i["license"]) for i in body["items"]] == [("Beat B", f"{order_id}-2", "exclusive")]
    item = body["items"][0]
    assert hashlib.sha256(item["text"].encode()).hexdigest() == item["draft_sha256"]
    assert "исключительную лицензию" in item["text"] and "одноразовым кодом из SMS" in item["text"]
    # nothing is written while reading
    assert _scalar(owner_engine, "SELECT count(*) FROM signature_otps") == 0

    stranger = _artist(client, email="stranger@example.com")
    assert client.get(f"/v1/orders/{order_id}/contract-draft", headers=auth(stranger)).status_code == 403


def test_contract_draft_needs_a_pending_order_with_exclusive(client, producer, owner_engine):
    beat_id = _beat(client, owner_engine, producer)
    artist = _artist(client)
    lease = _order(client, artist, [(beat_id, "basic", 1500)]).json()["order_id"]
    response = client.get(f"/v1/orders/{lease}/contract-draft", headers=auth(artist))
    assert (response.status_code, response.json()["error_code"]) == (409, "INVALID_STATUS")


# --- The happy path (RFC §3, §6) ---

def test_rfc3_send_code_and_sign(client, owner_engine, sms, exclusive):
    artist, order_id, beat_id = exclusive
    response = _send(client, artist, order_id)
    assert response.status_code == 202, response.text
    body = response.json()
    expires = datetime.fromisoformat(body["expires_at"]) - datetime.now(UTC)
    resend = datetime.fromisoformat(body["resend_after"]) - datetime.now(UTC)
    assert timedelta(minutes=4) < expires <= timedelta(minutes=5)  # NFR-31: 5 minutes
    assert timedelta(seconds=50) < resend <= timedelta(seconds=60)
    assert body["phone"] == "+7 (900) ***-**-67"
    assert sms.sms[0][0] == VALID_BILLING["phone"]  # GAP-33: the phone of the order's snapshot
    code = sms.last_code()

    signed = _verify(client, artist, order_id, code)
    assert signed.status_code == 200, signed.text
    with owner_engine.connect() as conn:
        contract = conn.execute(text("SELECT * FROM contracts")).one()
        otp = conn.execute(text("SELECT attempts, confirmed_at FROM signature_otps")).one()
        actions = conn.execute(text("SELECT action FROM audit_log WHERE entity = 'order' ORDER BY id")).scalars().all()
    assert (contract.signature_type, contract.signer_phone) == ("otp", VALID_BILLING["phone"])
    draft = client.get(f"/v1/orders/{order_id}/contract-draft", headers=auth(artist)).json()["items"][0]
    assert contract.draft_sha256 == draft["draft_sha256"]  # the text that was shown is the text signed
    assert otp.attempts == 0 and otp.confirmed_at is not None
    assert actions[-2:] == ["signature.otp_sent", "contract.signed"]  # NFR-7

    order = client.get(f"/v1/orders/{order_id}", headers=auth(artist)).json()
    assert (order["requires_signature"], order["signed"]) == (True, True)


def test_nfr31_only_an_hmac_of_the_code_is_stored(client, owner_engine, sms, exclusive):
    artist, order_id, _ = exclusive
    _send(client, artist, order_id)
    code = sms.last_code()
    stored = _scalar(owner_engine, "SELECT code_hash FROM signature_otps")
    assert code not in stored and stored.startswith("hmac-sha256$")
    plain_sha = hashlib.sha256(f"{order_id}:{code}".encode()).hexdigest()
    other_key = hmac.new(b"another-secret", f"{order_id}:{code}".encode(), hashlib.sha256).hexdigest()
    assert plain_sha not in stored and other_key not in stored  # without OTP_SECRET the hash is useless


# --- Attempts (NFR-31) ---

def test_nfr31_three_wrong_attempts_then_429_even_for_the_right_code(client, owner_engine, sms, exclusive):
    artist, order_id, _ = exclusive
    _send(client, artist, order_id)
    code = sms.last_code()
    lefts = []
    for _ in range(3):
        response = _verify(client, artist, order_id, _wrong(code))
        assert (response.status_code, response.json()["error_code"]) == (400, "INVALID_CODE")
        lefts.append(response.json()["details"][0]["attempts_left"])
    assert lefts == [2, 1, 0]
    response = _verify(client, artist, order_id, code)
    assert (response.status_code, response.json()["error_code"]) == (429, "CODE_ATTEMPTS_EXCEEDED")
    assert _scalar(owner_engine, "SELECT count(*) FROM audit_log WHERE action = 'signature.code_rejected'") == 3


def test_nfr31_parallel_guessing_counts_only_three_attempts(client, owner_engine, sms, exclusive):
    """Ten wrong codes at the same moment: the row lock lines them up, the counter stops at 3."""
    artist, order_id, _ = exclusive
    _send(client, artist, order_id)
    code = sms.last_code()
    start = threading.Barrier(10)

    def guess(i):
        start.wait()
        return _verify(client, artist, order_id, f"{(int(code) + 1 + i) % 10**6:06d}").status_code

    with ThreadPoolExecutor(max_workers=10) as pool:
        codes = sorted(pool.map(guess, range(10)))
    assert codes == [400] * 3 + [429] * 7
    assert _scalar(owner_engine, "SELECT attempts FROM signature_otps") == 3
    assert _verify(client, artist, order_id, code).status_code == 429  # the right code is too late now


def test_wrong_format_does_not_spend_an_attempt(client, owner_engine, sms, exclusive):
    artist, order_id, _ = exclusive
    _send(client, artist, order_id)
    for bad in ("12345", "abcdef", "1234567"):
        assert _verify(client, artist, order_id, bad).status_code == 400
    assert _scalar(owner_engine, "SELECT attempts FROM signature_otps") == 0


# --- Lifetime, resending and limits (NFR-31, GAP-34, GAP-70, GAP-73) ---

def test_nfr31_code_lives_five_minutes(client, owner_engine, sms, exclusive):
    artist, order_id, _ = exclusive
    _send(client, artist, order_id)
    code = sms.last_code()
    _age_codes(owner_engine, 301)
    response = _verify(client, artist, order_id, code)
    assert (response.status_code, response.json()["error_code"]) == (410, "CODE_EXPIRED")


def test_gap73_verify_without_a_code_is_expired(client, sms, exclusive):
    artist, order_id, _ = exclusive
    assert _verify(client, artist, order_id, "123456").json()["error_code"] == "CODE_EXPIRED"


def test_nfr31_resend_not_earlier_than_60_seconds_and_new_code_cancels_old(client, owner_engine, sms, exclusive):
    artist, order_id, _ = exclusive
    _send(client, artist, order_id)
    old = sms.last_code()
    _age_codes(owner_engine, 10)
    early = _send(client, artist, order_id)
    assert (early.status_code, early.json()["error_code"]) == (429, "TOO_MANY_REQUESTS")
    wait = early.json()["details"][0]["retry_after"]
    assert 49 <= wait <= 50 and early.headers["Retry-After"] == str(wait)

    _age_codes(owner_engine, 51)  # 61 s after the first code
    assert _send(client, artist, order_id).status_code == 202
    new = sms.last_code()
    if new != old:  # one chance in a million that both codes are equal
        assert _verify(client, artist, order_id, old).json()["error_code"] == "INVALID_CODE"
    assert _verify(client, artist, order_id, new).status_code == 200
    # GAP-34: the old code is canceled by setting its time over
    assert _scalar(owner_engine, "SELECT count(*) FROM signature_otps WHERE expires_at > now() AND confirmed_at IS NULL") == 0


def test_nfr31_five_codes_per_hour_per_user_over_all_orders(client, producer, owner_engine, sms):
    a = _beat(client, owner_engine, producer, title="Beat A")
    b = _beat(client, owner_engine, producer, title="Beat B")
    c = _beat(client, owner_engine, producer, title="Beat C")
    artist = _artist(client)
    first = _order(client, artist, [(a, "exclusive", 25000)]).json()["order_id"]
    second = _order(client, artist, [(b, "exclusive", 25000)]).json()["order_id"]
    for i in range(5):
        assert _send(client, artist, first if i % 2 == 0 else second).status_code == 202
        _age_codes(owner_engine, 61)
    sixth = _send(client, artist, second)
    assert (sixth.status_code, sixth.json()["error_code"]) == (429, "TOO_MANY_REQUESTS")
    # the oldest of the five was sent 5 × 61 s ago: the next slot opens in about 55 minutes
    assert 3600 - 5 * 61 - 2 <= sixth.json()["details"][0]["retry_after"] <= 3600 - 5 * 61 + 1

    other = _artist(client, email="other@example.com")
    other_order = _order(client, other, [(c, "exclusive", 25000)]).json()["order_id"]
    assert _send(client, other, other_order).status_code == 202  # the limit is per user


def test_gap72_sms_failure_keeps_nothing_and_spends_no_limit(client, owner_engine, sms, exclusive):
    artist, order_id, _ = exclusive
    sms.down = True
    response = _send(client, artist, order_id)
    assert (response.status_code, response.json()["error_code"]) == (503, "SMS_UNAVAILABLE")
    assert _scalar(owner_engine, "SELECT count(*) FROM signature_otps") == 0
    sms.down = False
    assert _send(client, artist, order_id).status_code == 202  # no "wait 60 s" after a failure


def test_log_mock_can_pretend_the_provider_is_down(monkeypatch):
    from app.notifications.service import LogNotifier

    monkeypatch.setattr(get_settings(), "sms_mode", "unavailable")
    with pytest.raises(SmsUnavailable):
        LogNotifier().send_sms("+79001234567", "code")


# --- When signing is not allowed (GAP-33, GAP-34) ---

def test_gap34_signed_once(client, sms, exclusive):
    artist, order_id, _ = exclusive
    _send(client, artist, order_id)
    code = sms.last_code()
    assert _verify(client, artist, order_id, code).status_code == 200
    assert _verify(client, artist, order_id, code).json()["error_code"] == "ALREADY_SIGNED"
    assert _send(client, artist, order_id).json()["error_code"] == "ALREADY_SIGNED"


def test_gap34_reservation_over_blocks_signing(client, owner_engine, sms, exclusive):
    artist, order_id, beat_id = exclusive
    _send(client, artist, order_id)
    code = sms.last_code()
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE beats SET reserved_until = now() - interval '1 second' WHERE id = :b"), {"b": beat_id})
    for response in (_verify(client, artist, order_id, code), _send(client, artist, order_id)):
        assert (response.status_code, response.json()["error_code"]) == (409, "INVALID_STATUS")


def test_signature_only_for_the_owner(client, sms, exclusive):
    artist, order_id, _ = exclusive
    stranger = _artist(client, email="stranger@example.com")
    assert _send(client, stranger, order_id).status_code == 403
    assert _verify(client, stranger, order_id, "123456").status_code == 403


def test_gap33_phone_required_if_the_snapshot_has_none(client, owner_engine, sms, exclusive):
    artist, order_id, _ = exclusive
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE orders SET billing_snapshot = jsonb_set(billing_snapshot, '{buyer,phone}', 'null')"))
    assert _send(client, artist, order_id).json()["error_code"] == "PHONE_REQUIRED"


# --- The whole Exclusive purchase (FR-26, GAP-28) ---

def test_fr26_exclusive_purchase_end_to_end(client, producer, owner_engine, sms, fake, test_buckets):
    """Two Exclusive and one Basic: one code signs both Exclusive contracts; after the payment the beats
    are sold and every contract is a PDF whose hash is in the database."""
    x1 = _beat(client, owner_engine, producer, title="Exclusive one")
    x2 = _beat(client, owner_engine, producer, title="Exclusive two")
    lease = _beat(client, owner_engine, producer, title="Lease one")
    for beat_id in (x1, x2):
        _files(owner_engine, test_buckets, beat_id)
    artist = _artist(client)
    order_id = _order(client, artist, [(lease, "basic", 1500), (x1, "exclusive", 25000), (x2, "exclusive", 25000)]).json()["order_id"]

    assert _pay(client, artist, order_id).status_code == 428  # not signed yet
    drafts = {i["contract_number"]: i["draft_sha256"]
              for i in client.get(f"/v1/orders/{order_id}/contract-draft", headers=auth(artist)).json()["items"]}
    _send(client, artist, order_id)
    assert _verify(client, artist, order_id, sms.last_code()).status_code == 200

    payment_id = _pay(client, artist, order_id).json()["payment_id"]
    fake.hold(payment_id)
    notify(client, payment_id)
    notify(client, payment_id, "payment.succeeded")
    assert _beat_row(owner_engine, x1).status == "sold" and _beat_row(owner_engine, x2).status == "sold"

    with owner_engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT c.signature_type, c.draft_sha256, c.pdf_key, c.pdf_sha256 FROM contracts c "
            "JOIN order_items oi ON oi.id = c.order_item_id WHERE oi.order_id = :o ORDER BY oi.id"), {"o": order_id}).all()
        sent_hashes = conn.execute(text("SELECT details->'drafts' FROM audit_log WHERE action = 'signature.otp_sent'")).scalar()
    assert [r.signature_type for r in rows] == ["offer_accept", "otp", "otp"]
    assert {f"{order_id}-2": rows[1].draft_sha256, f"{order_id}-3": rows[2].draft_sha256} == drafts == sent_hashes  # GAP-9
    for r in rows:
        pdf = test_buckets.get_object(Bucket=get_settings().bucket_private, Key=r.pdf_key)["Body"].read()
        assert hashlib.sha256(pdf).hexdigest() == r.pdf_sha256

    files = client.get(f"/v1/orders/{order_id}/downloads", headers=auth(artist)).json()["items"]
    assert [f["kind"] for f in files[1]["files"]] == ["mp3", "wav", "stems", "contract"]


def test_mock_inbox_keeps_sms_and_email(tmp_path, monkeypatch):
    """The end-to-end test reads the SMS code from the inbox file of the mock."""
    import json

    from app.notifications.service import LogNotifier

    inbox = tmp_path / "messages.jsonl"
    monkeypatch.setenv("MOCK_INBOX_PATH", str(inbox))
    LogNotifier().send_sms("+79001234567", "OhBeat: код 123456")
    LogNotifier().send_email("a@example.com", "Тема", "Текст")
    lines = [json.loads(line) for line in inbox.read_text(encoding="utf-8").splitlines()]
    assert [(m["kind"], m["to"]) for m in lines] == [("sms", "+79001234567"), ("email", "a@example.com")]
