"""HTTP layer of payments (REST API §2.5, §2.7)."""

import ipaddress
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy.orm import Session

from app.common.auth_deps import CurrentUser, client_ip, get_current_user
from app.common.config import get_settings
from app.common.db import get_db, get_session_factory
from app.common.errors import ApiError
from app.payments import events, service
from app.payments.gateway import PaymentGateway, get_gateway
from app.payments.schemas import PaymentCreated

router = APIRouter(tags=["payments"])
log = logging.getLogger("payments.webhook")

# FR-22: addresses YooKassa sends notifications from (its documentation, section "Входящие уведомления")
YOOKASSA_NETWORKS = [ipaddress.ip_network(n) for n in (
    "185.71.76.0/27", "185.71.77.0/27", "77.75.153.0/25", "77.75.156.11/32", "77.75.156.35/32",
    "77.75.154.128/25", "2a02:5180::/32",
)]


def from_yookassa(ip: str | None) -> bool:
    try:
        address = ipaddress.ip_address(ip or "")
    except ValueError:
        return False
    return any(address in network for network in YOOKASSA_NETWORKS)


@router.post("/orders/{order_id}/payments", response_model=PaymentCreated)
def create_payment(
    order_id: int,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    gateway: PaymentGateway = Depends(get_gateway),
) -> PaymentCreated:
    """FR-20, FR-21, FR-30. Errors: 403, 404, 409 INVALID_STATUS, 410 RESERVATION_EXPIRED,
    428 SIGNATURE_REQUIRED, 503 PAYMENT_PROVIDER_UNAVAILABLE (the reservation stays)."""
    return service.create_payment(db, gateway, order_id, user.id, client_ip(request))


@router.post("/payments/webhook")
async def webhook(request: Request, background: BackgroundTasks,
                  gateway: PaymentGateway = Depends(get_gateway)) -> dict:
    """FR-22. No token: the source is checked by IP (when on) and every status by GET /v3/payments/{id}.
    200 only after the commit; any failure → 500 and YooKassa repeats the notification."""
    if get_settings().yookassa_ip_check and not from_yookassa(client_ip(request)):
        raise ApiError(403, "FORBIDDEN")
    try:
        body = await request.json()
        payment_id = str(body["object"]["id"])
    except (ValueError, KeyError, TypeError):
        raise ApiError(400, "VALIDATION_ERROR") from None
    log.info("webhook %s for %s", body.get("event"), payment_id)

    from starlette.concurrency import run_in_threadpool

    followups = await run_in_threadpool(_process, gateway, payment_id)
    # GAP-35: capture / cancel and emails go after the answer
    background.add_task(events.run_followups, get_session_factory(), gateway, followups)
    return {}


def _process(gateway: PaymentGateway, payment_id: str) -> events.Followups:
    with get_session_factory()() as db:
        return events.process(db, gateway, payment_id)
