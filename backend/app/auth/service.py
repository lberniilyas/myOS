from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.areas.models import Area
from app.auth.models import AuthSession, User
from app.auth.schemas import RegisterRequest
from app.auth.security import (
    hash_password,
    hash_token,
    new_token,
    verify_dummy_password,
    verify_password,
)
from app.clock import Clock
from app.config import get_settings
from app.core.text import compact_key
from app.errors import AppError, ConflictError, UnauthorizedError

STARTER_AREAS = ("Career", "Education", "Finance", "Health", "Personal")


@dataclass
class IssuedTokens:
    session: AuthSession
    access_token: str
    refresh_token: str


def _issue(db: Session, user: User, device_name: str | None, clock: Clock) -> IssuedTokens:
    settings = get_settings()
    now = clock.now()
    access_token = new_token("pos_at")
    refresh_token = new_token("pos_rt")
    session = AuthSession(
        user_id=user.id,
        access_token_hash=hash_token(access_token),
        refresh_token_hash=hash_token(refresh_token),
        access_expires_at=now + timedelta(minutes=settings.access_token_ttl_minutes),
        refresh_expires_at=now + timedelta(days=settings.refresh_token_ttl_days),
        device_name=device_name,
        last_used_at=now,
    )
    db.add(session)
    db.flush()
    return IssuedTokens(session, access_token, refresh_token)


def register(db: Session, request: RegisterRequest, clock: Clock) -> tuple[User, IssuedTokens]:
    if not get_settings().may_register(request.email):
        raise AppError(
            "Sign-up is closed on this server. Add your email to ALLOWED_EMAILS to open it.",
            code="REGISTRATION_CLOSED",
            status_code=403,
        )
    if db.scalar(select(User.id).where(User.email == request.email)) is not None:
        raise ConflictError("An account with this email already exists.", code="EMAIL_TAKEN")
    user = User(
        email=request.email,
        password_hash=hash_password(request.password),
        name=request.name,
        timezone=request.timezone or "UTC",
        locale=request.locale or "en",
        default_currency=request.default_currency,
        preferences={},
        privacy_settings={},
    )
    db.add(user)
    db.flush()
    for name in STARTER_AREAS:
        db.add(Area(user_id=user.id, name=name, name_key=compact_key(name)))
    tokens = _issue(db, user, request.device_name, clock)
    db.commit()
    return user, tokens


def login(
    db: Session, email: str, password: str, device_name: str | None, clock: Clock
) -> tuple[User, IssuedTokens]:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        verify_dummy_password(password)
        raise UnauthorizedError("Email or password is incorrect.", code="INVALID_CREDENTIALS")
    if not verify_password(password, user.password_hash):
        raise UnauthorizedError("Email or password is incorrect.", code="INVALID_CREDENTIALS")
    tokens = _issue(db, user, device_name, clock)
    db.commit()
    return user, tokens


def refresh(db: Session, refresh_token: str, clock: Clock) -> tuple[User, IssuedTokens]:
    """Rotate both tokens.

    The refresh token being replaced keeps working until the next rotation: on a phone the reply
    carrying the new one can be lost (bad signal, app suspended), and the old one must still get
    the person back in rather than signing them out. The row lock makes concurrent refreshes take
    turns, so each one leaves the other's token valid.
    """
    settings = get_settings()
    now = clock.now()
    presented = hash_token(refresh_token)
    session = db.scalar(
        select(AuthSession)
        .where(
            or_(
                AuthSession.refresh_token_hash == presented,
                AuthSession.previous_refresh_token_hash == presented,
            )
        )
        .with_for_update()
    )
    if session is None or session.revoked_at is not None or session.refresh_expires_at <= now:
        raise UnauthorizedError(
            "Your session has expired. Please sign in again.", code="SESSION_EXPIRED"
        )
    access_token = new_token("pos_at")
    new_refresh_token = new_token("pos_rt")
    session.access_token_hash = hash_token(access_token)
    session.previous_refresh_token_hash = session.refresh_token_hash
    session.refresh_token_hash = hash_token(new_refresh_token)
    session.access_expires_at = now + timedelta(minutes=settings.access_token_ttl_minutes)
    session.refresh_expires_at = now + timedelta(days=settings.refresh_token_ttl_days)
    session.last_used_at = now
    user = db.get(User, session.user_id)
    db.commit()
    return user, IssuedTokens(session, access_token, new_refresh_token)


def authenticate(db: Session, access_token: str, clock: Clock) -> tuple[User, AuthSession]:
    now = clock.now()
    session = db.scalar(
        select(AuthSession).where(AuthSession.access_token_hash == hash_token(access_token))
    )
    if session is None or session.revoked_at is not None:
        raise UnauthorizedError("Invalid access token.", code="INVALID_TOKEN")
    if session.access_expires_at <= now:
        raise UnauthorizedError("Access token expired; refresh it.", code="TOKEN_EXPIRED")
    user = db.get(User, session.user_id)
    if user is None:
        raise UnauthorizedError("Invalid access token.", code="INVALID_TOKEN")
    return user, session


def logout(db: Session, session: AuthSession, clock: Clock) -> None:
    session.revoked_at = clock.now()
    db.commit()


def verify_user_password(user: User, password: str) -> None:
    if not verify_password(password, user.password_hash):
        raise UnauthorizedError("Password is incorrect.", code="INVALID_CREDENTIALS")
