"""HTTP layer of the signature by SMS code (RFC ПЭП §4, REST API §2.12)."""

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.common.auth_deps import CurrentUser, client_ip, get_current_user
from app.common.db import get_db
from app.notifications.service import Notifier, get_notifier
from app.signature import service
from app.signature.schemas import CodeSent, Drafts, Signed, VerifyIn

router = APIRouter(tags=["signature"])


@router.get("/orders/{order_id}/contract-draft", response_model=Drafts)
def contract_draft(
    order_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Drafts:
    """The text of every Exclusive contract and its draft_sha256, read BEFORE asking for a code.
    Errors: 403, 404, 409 INVALID_STATUS (not pending or no Exclusive)."""
    return service.contract_draft(db, order_id, user.id)


@router.post("/orders/{order_id}/signature/otp", status_code=status.HTTP_202_ACCEPTED, response_model=CodeSent)
def send_code(
    order_id: int,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    notifier: Notifier = Depends(get_notifier),
) -> CodeSent:
    """A 6-digit code by SMS to the buyer's phone; lives 5 minutes (NFR-31). Errors: 409 INVALID_STATUS,
    ALREADY_SIGNED, PHONE_REQUIRED; 429 TOO_MANY_REQUESTS (Retry-After); 503 SMS_UNAVAILABLE."""
    return service.send_code(db, notifier, order_id, user.id, client_ip(request))


@router.post("/orders/{order_id}/signature/verify", response_model=Signed)
def verify(
    order_id: int,
    data: VerifyIn,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Signed:
    """Errors: 400 INVALID_CODE {attempts_left}, 410 CODE_EXPIRED, 429 CODE_ATTEMPTS_EXCEEDED,
    409 INVALID_STATUS / ALREADY_SIGNED."""
    return service.verify(db, order_id, user.id, data.code, client_ip(request))
