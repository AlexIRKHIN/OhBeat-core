"""HTTP layer of the cart and orders (REST API §2.5, §2.6, §2.11)."""

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.common.auth_deps import CurrentUser, client_ip, get_current_user
from app.common.db import get_db
from app.common.storage import ObjectStorage, get_storage
from app.orders import cart, service
from app.orders.schemas import CartOut, CartPut, OrderCreate, OrderCreated, OrderOut

router = APIRouter(tags=["orders"])


@router.get("/cart", response_model=CartOut)
def get_cart(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> CartOut:
    """FR-15. Current prices of the Producers, the service fee and the total; `available: false`
    marks a beat that cannot be bought any more (FR-14)."""
    return cart.get_cart(db, storage, user.id)


@router.put("/cart/items/{beat_id}", response_model=CartOut)
def put_cart_item(
    beat_id: int,
    data: CartPut,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> CartOut:
    """FR-14. Adds a beat or replaces its license. Errors: 404 NOT_FOUND;
    409 BEAT_RESERVED / BEAT_SOLD / BEAT_NOT_AVAILABLE / LICENSE_INACTIVE / OWN_BEAT."""
    return cart.put_item(db, storage, user.id, beat_id, data.license)


@router.delete("/cart/items/{beat_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cart_item(
    beat_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    cart.remove_item(db, user.id, beat_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/orders", status_code=status.HTTP_201_CREATED, response_model=OrderCreated)
def create_order(
    data: OrderCreate,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrderCreated:
    """FR-15 … FR-19. One transaction: order, items, Exclusive reservation for 15 minutes, offer
    contracts. Errors: 409 BEAT_RESERVED / BEAT_SOLD / BEAT_NOT_AVAILABLE / LICENSE_INACTIVE /
    PRICE_CHANGED / BILLING_REQUIRED / OWN_BEAT."""
    return service.create_order(db, user.id, data, client_ip(request))


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(
    order_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> OrderOut:
    """REST API §2.6 (wider, GAP-63). Only the owner of the order. Errors: 403, 404."""
    return service.get_order(db, storage, order_id, user.id)
