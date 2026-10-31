"""Registration, sign-in and token rotation (FR-31, REST API §2.8)."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import LoginAttempt, RefreshToken
from app.auth.schemas import LoginRequest, RegisterRequest, TokenPair
from app.common.audit import write_audit
from app.common.config import get_settings
from app.common.errors import ApiError
from app.common.security import (
    create_access_token,
    hash_password,
    hash_token,
    new_refresh_token,
    verify_password,
)
from app.users.models import Profile, User, UserRole


def normalize_email(email: str) -> str:
    # ASSUMPTION: GAP-12 — emails are compared case-insensitively
    return email.strip().lower()


def get_roles(db: Session, user_id: int) -> list[str]:
    return list(db.scalars(select(UserRole.role).where(UserRole.user_id == user_id)))


def _issue_tokens(db: Session, user_id: int, family_id: uuid.UUID | None = None) -> tuple[TokenPair, RefreshToken]:
    """Create an access token and a new refresh token (its hash goes to the database)."""
    settings = get_settings()
    refresh = new_refresh_token()
    row = RefreshToken(
        user_id=user_id,
        family_id=family_id or uuid.uuid4(),
        token_hash=hash_token(refresh),
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days),
    )
    db.add(row)
    db.flush()
    pair = TokenPair(
        access_token=create_access_token(user_id, get_roles(db, user_id)),
        refresh_token=refresh,
        expires_in=settings.access_token_ttl_seconds,
    )
    return pair, row


def register(db: Session, data: RegisterRequest, ip: str | None) -> TokenPair:
    """FR-31: one transaction — user, role Artist, profile, Audit Log, first refresh token."""
    email = normalize_email(data.email)
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise ApiError(409, "EMAIL_TAKEN")

    now = datetime.now(UTC)
    user = User(email=email, password_hash=hash_password(data.password), pd_consent_at=now)
    db.add(user)
    try:
        db.flush()  # gets user.id; a parallel registration with the same email fails here
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "EMAIL_TAKEN") from None

    db.add(UserRole(user_id=user.id, role="artist"))
    db.add(Profile(user_id=user.id, display_name=data.display_name))
    write_audit(
        db, action="user.registered", entity="user", entity_id=user.id, actor_user_id=user.id, ip=ip,
        details={"pd_consent_at": now.isoformat()},
    )
    # RFC ПЭП §1: the fact of accepting the e-signature agreement goes to the Audit Log
    write_audit(
        db, action="pep_agreement.accepted", entity="user", entity_id=user.id, actor_user_id=user.id, ip=ip,
        details={"role": "artist"},
    )
    pair, _ = _issue_tokens(db, user.id)
    db.commit()
    return pair


def _recent_failures(db: Session, email: str) -> int:
    """Failures within the window, counted after the last successful sign-in."""
    settings = get_settings()
    window_start = datetime.now(UTC) - timedelta(minutes=settings.login_window_minutes)
    last_success = db.scalar(
        select(func.max(LoginAttempt.attempted_at)).where(
            LoginAttempt.email == email, LoginAttempt.succeeded.is_(True)
        )
    )
    since = max(window_start, last_success) if last_success else window_start
    return db.scalar(
        select(func.count()).where(
            LoginAttempt.email == email,
            LoginAttempt.succeeded.is_(False),
            LoginAttempt.attempted_at > since,
        )
    )


def login(db: Session, data: LoginRequest, ip: str | None) -> TokenPair:
    settings = get_settings()
    email = normalize_email(data.email)

    # REST API §2.8: after 5 failures in 15 minutes the password is not even checked
    # ASSUMPTION: GAP-11 — the limit is counted per email
    if _recent_failures(db, email) >= settings.login_max_failures:
        raise ApiError(429, "TOO_MANY_ATTEMPTS")

    user = db.scalar(select(User).where(User.email == email))
    ok = verify_password(data.password, user.password_hash if user else None)
    db.add(LoginAttempt(email=email, succeeded=ok, ip=ip))
    if not ok:
        db.commit()  # the failed attempt must be remembered
        # One message for "no such email" and "wrong password": existence of an account is not revealed
        raise ApiError(401, "INVALID_CREDENTIALS")

    pair, _ = _issue_tokens(db, user.id)
    db.commit()
    return pair


def refresh(db: Session, token: str) -> TokenPair:
    """Rotation: the used refresh token is revoked at once and a new one is issued in the same family."""
    now = datetime.now(UTC)
    row = db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(token)).with_for_update()
    )
    if row is None or row.expires_at <= now:
        raise ApiError(401, "INVALID_REFRESH_TOKEN")

    if row.revoked_at is not None:
        # A revoked token came back: someone may have stolen it. Revoke the whole family.
        db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == row.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        db.commit()
        raise ApiError(401, "INVALID_REFRESH_TOKEN")

    pair, new_row = _issue_tokens(db, row.user_id, family_id=row.family_id)
    row.revoked_at = now
    row.replaced_by_id = new_row.id
    db.commit()
    return pair


def logout(db: Session, user_id: int, token: str) -> None:
    """Revokes the given refresh token of this user. Repeating the call is harmless."""
    db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.token_hash == hash_token(token),
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    db.commit()
