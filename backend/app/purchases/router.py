"""HTTP layer of downloads, "My purchases" and "My sales" (REST API §2.6, §2.10, §2.12)."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.common.auth_deps import CurrentUser, get_current_user, require_role
from app.common.db import get_db
from app.common.storage import ObjectStorage, get_storage
from app.purchases import service
from app.purchases.schemas import Downloads, Purchases, Sales

router = APIRouter(tags=["purchases"])


@router.get("/orders/{order_id}/downloads", response_model=Downloads)
def downloads(
    order_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> Downloads:
    """FR-28. Fresh links for the files of the bought licenses and the contracts, 1 hour (NFR-8).
    Errors: 403 FORBIDDEN, 404, 409 ORDER_NOT_PAID."""
    return service.downloads(db, storage, order_id, user.id)


@router.get("/users/me/purchases", response_model=Purchases)
def purchases(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> Purchases:
    """REST API §2.12. Paid items of the Artist with the payment date and pdf_sha256 of the contract."""
    return service.purchases(db, storage, user.id)


@router.get("/users/me/sales", response_model=Sales)
def sales(
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    user: CurrentUser = Depends(require_role("producer")),
    db: Session = Depends(get_db),
) -> Sales:
    """REST API §2.10, UC-14. Sold items and the total for the period (YYYY-MM-DD, Moscow days)."""
    return service.sales(db, user.id, date_from, date_to)
