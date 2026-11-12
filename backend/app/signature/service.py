"""Signing Exclusive contracts with a one-time SMS code (RFC ПЭП §3, §4; NFR-31).

    GET  contract-draft   the text of every Exclusive item and its SHA-256 — nothing is written
    POST signature/otp    checks → limits (60 s, 5 per hour per user) → previous codes canceled
                          → HMAC of a new code saved → SMS → 202
    POST signature/verify the code row locked (FOR UPDATE) → expired? attempts left? HMAC equal?
                          → contracts (otp) for every Exclusive item + audit → 200

Time is always the database's now(): the limits do not depend on the clock of a process.
"""

import hashlib
import hmac
import secrets
from datetime import timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.catalog.models import Beat
from app.common.audit import write_audit
from app.common.config import get_settings
from app.common.errors import ApiError
from app.common.i18n import t
from app.contracts.draft import render_draft, sha256_text
from app.contracts.issue import contract_number, draft_item, mask_phone
from app.dictionaries.models import License
from app.notifications.service import Notifier, SmsUnavailable
from app.orders.models import Contract, Order, OrderItem, SignatureOtp
from app.orders.service import owned_order
from app.signature.schemas import CodeSent, DraftItemOut, Drafts, Signed
from app.users.models import User


def _exclusive_drafts(db: Session, order: Order) -> list[tuple[OrderItem, str, str, str]]:
    """(item, contract number, text, draft_sha256) for every Exclusive item. The numbers count ALL
    items of the order (GAP-32), the text is made for the signature by code (RFC ПЭП §2)."""
    rows = db.execute(
        select(OrderItem, Beat, License)
        .join(Beat, Beat.id == OrderItem.beat_id)
        .join(License, License.id == OrderItem.license_id)
        .where(OrderItem.order_id == order.id)
        .order_by(OrderItem.id)
    ).all()
    result = []
    for n, row in enumerate(rows, start=1):
        if row.License.is_exclusive:
            draft = render_draft(draft_item(order, row.OrderItem, row.Beat, row.License, n), order.billing_snapshot, "otp")
            result.append((row.OrderItem, contract_number(order.id, n), draft, sha256_text(draft)))
    return result


def _code_hash(order_id: int, code: str) -> str:
    """HMAC-SHA256 with the secret from .env (NFR-31: only a hash in the database)."""
    digest = hmac.new(get_settings().otp_secret.encode(), f"{order_id}:{code}".encode(), hashlib.sha256).hexdigest()
    return f"hmac-sha256${digest}"


def _signable(db: Session, order: Order, drafts: list) -> None:
    """The order can be signed now: pending, has Exclusive, the reservation is alive, not signed yet."""
    if order.status != "pending" or not drafts:
        raise ApiError(409, "INVALID_STATUS")
    ids = [item.beat_id for item, *_ in drafts]
    alive = db.scalar(select(func.count()).select_from(Beat).where(
        Beat.id.in_(ids), Beat.status == "reserved", Beat.reserved_order_id == order.id, Beat.reserved_until > func.now()))
    if alive != len(ids):
        raise ApiError(409, "INVALID_STATUS")  # ASSUMPTION: GAP-34 — the 15 minutes are over
    signed = db.scalar(select(func.count()).select_from(Contract).where(
        Contract.order_item_id.in_([item.id for item, *_ in drafts]), Contract.signature_type == "otp"))
    if signed:
        raise ApiError(409, "ALREADY_SIGNED")  # ASSUMPTION: GAP-34


# --- The draft ---

def contract_draft(db: Session, order_id: int, user_id: int) -> Drafts:
    order = owned_order(db, order_id, user_id)
    drafts = _exclusive_drafts(db, order)
    if order.status != "pending" or not drafts:
        raise ApiError(409, "INVALID_STATUS")  # REST API §2.12
    titles = dict(db.execute(select(Beat.id, Beat.title).where(Beat.id.in_([i.beat_id for i, *_ in drafts]))).all())
    return Drafts(items=[DraftItemOut(item_id=item.id, contract_number=number, title=titles[item.beat_id],
                                      license="exclusive", text=draft, draft_sha256=sha)
                         for item, number, draft, sha in drafts])


# --- Sending a code ---

def _too_many(seconds: float) -> ApiError:
    wait = max(1, int(seconds + 0.999))
    return ApiError(429, "TOO_MANY_REQUESTS",
                    [{"field": "code", "issue": t("retry_after", seconds=wait), "retry_after": wait}],
                    headers={"Retry-After": str(wait)})


def send_code(db: Session, notifier: Notifier, order_id: int, user_id: int, ip: str | None) -> CodeSent:
    settings = get_settings()
    # One user at a time: two requests at once (even for two orders) cannot both pass the limits
    db.execute(select(User.id).where(User.id == user_id).with_for_update())
    order = owned_order(db, order_id, user_id, lock=True)
    drafts = _exclusive_drafts(db, order)
    _signable(db, order, drafts)
    phone = (order.billing_snapshot.get("buyer") or {}).get("phone")
    if not phone:
        raise ApiError(409, "PHONE_REQUIRED")  # ASSUMPTION: GAP-33 — the phone of the order's snapshot

    # NFR-31, ASSUMPTION: GAP-34 — both limits per user, over all their orders
    now = db.scalar(select(func.now()))
    sent = db.scalars(
        select(SignatureOtp.created_at)
        .join(Order, Order.id == SignatureOtp.order_id)
        .where(Order.customer_id == user_id, SignatureOtp.created_at > now - timedelta(hours=1))
        .order_by(SignatureOtp.created_at)
    ).all()
    if sent and (now - sent[-1]).total_seconds() < settings.otp_resend_seconds:
        raise _too_many(settings.otp_resend_seconds - (now - sent[-1]).total_seconds())
    if len(sent) >= settings.otp_hourly_limit:
        raise _too_many((sent[-settings.otp_hourly_limit] + timedelta(hours=1) - now).total_seconds())

    # A new code cancels the previous one (GAP-34): its time is simply over
    db.execute(text("UPDATE signature_otps SET expires_at = now() "
                    "WHERE order_id = :o AND confirmed_at IS NULL AND expires_at > now()"), {"o": order.id})
    code = f"{secrets.randbelow(10**6):06d}"
    otp = SignatureOtp(order_id=order.id, code_hash=_code_hash(order.id, code), attempts=0,
                       expires_at=now + timedelta(seconds=settings.otp_ttl_seconds), created_at=now)
    db.add(otp)
    db.flush()
    # ASSUMPTION: GAP-9 — the hashes of the drafts at the moment of sending, to compare with the contracts
    write_audit(db, action="signature.otp_sent", entity="order", entity_id=order.id, actor_user_id=user_id, ip=ip,
                details={"otp_id": otp.id, "phone": mask_phone(phone),
                         "drafts": {number: sha for _, number, _, sha in drafts}})
    try:
        # Sent before the commit: if the provider fails, nothing is kept and no limit is spent (GAP-72)
        notifier.send_sms(phone, f"OhBeat: код {code} для подписи договора по заказу № {order.id}. "
                                 f"Действует {settings.otp_ttl_seconds // 60} мин. Никому не сообщайте.")
    except SmsUnavailable:
        db.rollback()
        raise ApiError(503, "SMS_UNAVAILABLE") from None
    db.commit()
    return CodeSent(expires_at=otp.expires_at, resend_after=now + timedelta(seconds=settings.otp_resend_seconds),
                    phone=mask_phone(phone))


# --- Checking the code ---

def verify(db: Session, order_id: int, user_id: int, code: str, ip: str | None) -> Signed:
    settings = get_settings()
    order = owned_order(db, order_id, user_id)
    drafts = _exclusive_drafts(db, order)
    _signable(db, order, drafts)

    # The latest code of the order, locked: parallel guesses wait here one after another, so the
    # counter of attempts cannot be read as "0" by ten requests at once
    otp = db.scalar(select(SignatureOtp).where(SignatureOtp.order_id == order.id)
                    .order_by(SignatureOtp.created_at.desc(), SignatureOtp.id.desc()).limit(1).with_for_update())
    if otp is not None and otp.confirmed_at is not None:
        raise ApiError(409, "ALREADY_SIGNED")
    now = db.scalar(select(func.now()))
    if otp is None or otp.expires_at <= now:
        raise ApiError(410, "CODE_EXPIRED")  # ASSUMPTION: GAP-73 — also when no code was requested
    if otp.attempts >= settings.otp_max_attempts:
        raise ApiError(429, "CODE_ATTEMPTS_EXCEEDED")

    if not hmac.compare_digest(otp.code_hash, _code_hash(order.id, code)):
        otp.attempts += 1
        left = settings.otp_max_attempts - otp.attempts
        write_audit(db, action="signature.code_rejected", entity="order", entity_id=order.id, actor_user_id=user_id,
                    ip=ip, details={"otp_id": otp.id, "attempts": otp.attempts})
        db.commit()  # the attempt counts even though the answer is an error
        raise ApiError(400, "INVALID_CODE", [{"field": "code", "issue": t("attempts_left", attempts_left=left),
                                             "attempts_left": left}])

    otp.confirmed_at = now
    phone = order.billing_snapshot["buyer"]["phone"]
    for item, number, _, sha in drafts:
        # GAP-9: the hash is computed again from the same frozen data — the same text as when the code was sent
        db.add(Contract(order_item_id=item.id, signature_type="otp", draft_sha256=sha, signer_phone=phone,
                        signer_ip=ip or "unknown", signed_at=now))
        write_audit(db, action="contract.signed", entity="order", entity_id=order.id, actor_user_id=user_id, ip=ip,
                    details={"contract": number, "draft_sha256": sha, "otp_id": otp.id, "phone": mask_phone(phone)})
    db.commit()
    return Signed(signed_at=now)
