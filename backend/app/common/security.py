"""Passwords and tokens.

* Passwords: Argon2id, the salt is stored inside the hash string (NFR-4).
* Access token: JWT signed with HS256, lives 1 hour (REST API §2.8).
* Refresh token: a random string; only its SHA-256 hash is stored in the database.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.common.config import get_settings

_hasher = PasswordHasher()  # Argon2id with the library's recommended parameters

# Hash of a random password. Verifying against it when the email is unknown makes
# "no such user" take as long as "wrong password", so timing reveals nothing.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """password_hash is None when the email is unknown: we still spend the same time."""
    try:
        _hasher.verify(password_hash or _DUMMY_HASH, password)
    except (VerifyMismatchError, InvalidHashError):
        return False
    return password_hash is not None


def create_access_token(user_id: int, roles: list[str]) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "roles": sorted(roles),
        "type": "access",
        "iat": now,
        "exp": now + timedelta(seconds=settings.access_token_ttl_seconds),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    """Raises jwt.InvalidTokenError if the signature, expiry or type is wrong."""
    payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("not an access token")
    return payload


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
