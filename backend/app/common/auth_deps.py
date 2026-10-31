"""Who is calling: dependencies that check the access token and roles on every endpoint."""

from dataclasses import dataclass

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.common.errors import ApiError
from app.common.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    id: int
    roles: frozenset[str]


def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> CurrentUser:
    if credentials is None:
        raise ApiError(401, "AUTH_ERROR")
    try:
        claims = decode_access_token(credentials.credentials)
    except jwt.InvalidTokenError:
        raise ApiError(401, "AUTH_ERROR") from None
    return CurrentUser(id=int(claims["sub"]), roles=frozenset(claims.get("roles", [])))


def require_role(role: str):
    """Dependency factory: 403 FORBIDDEN if the user lacks the role."""

    def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if role not in user.roles:
            raise ApiError(403, "FORBIDDEN")
        return user

    return checker


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
