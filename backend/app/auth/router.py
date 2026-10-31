"""HTTP layer of /auth: takes the request, calls the service, returns the response."""

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.auth import service
from app.auth.schemas import LoginRequest, RefreshRequest, RegisterRequest, TokenPair
from app.common.auth_deps import CurrentUser, client_ip, get_current_user
from app.common.db import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=TokenPair)
def register(data: RegisterRequest, request: Request, db: Session = Depends(get_db)) -> TokenPair:
    """FR-31. Errors: 400 VALIDATION_ERROR, 409 EMAIL_TAKEN."""
    return service.register(db, data, client_ip(request))


@router.post("/login", response_model=TokenPair)
def login(data: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenPair:
    """Errors: 401 INVALID_CREDENTIALS, 429 TOO_MANY_ATTEMPTS."""
    return service.login(db, data, client_ip(request))


@router.post("/refresh", response_model=TokenPair)
def refresh(data: RefreshRequest, db: Session = Depends(get_db)) -> TokenPair:
    """Errors: 401 INVALID_REFRESH_TOKEN."""
    return service.refresh(db, data.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    data: RefreshRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    service.logout(db, user.id, data.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
