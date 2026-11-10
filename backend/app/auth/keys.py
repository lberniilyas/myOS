"""Personal access keys: send entries from an iPhone Shortcut, Siri or the Action button.

A key can only send captures. It never reads your records or changes your account, so a key
that leaks can at worst add entries, and revoking it in Me stops that at once.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.models import AccessKey, User
from app.auth.security import hash_token, new_token
from app.clock import Clock
from app.errors import AppError, NotFoundError, UnauthorizedError

KEY_PREFIX = "pos_key"
MAX_KEYS = 10


def is_access_key(token: str) -> bool:
    return token.startswith(f"{KEY_PREFIX}_")


def active_keys(db: Session, user: User) -> list[AccessKey]:
    return list(
        db.scalars(
            select(AccessKey)
            .where(AccessKey.user_id == user.id, AccessKey.revoked_at.is_(None))
            .order_by(AccessKey.created_at.desc())
        )
    )


def create_key(db: Session, user: User, name: str) -> tuple[AccessKey, str]:
    """Returns the stored key and the key itself, which is shown this once and never again."""
    count = db.scalar(
        select(func.count(AccessKey.id)).where(
            AccessKey.user_id == user.id, AccessKey.revoked_at.is_(None)
        )
    )
    if count >= MAX_KEYS:
        raise AppError(
            f"You already have {MAX_KEYS} keys. Revoke one you no longer use first.",
            code="TOO_MANY_KEYS",
            status_code=409,
        )
    secret = new_token(KEY_PREFIX)
    key = AccessKey(user_id=user.id, name=name, key_hash=hash_token(secret), hint=secret[-4:])
    db.add(key)
    db.commit()
    db.refresh(key)
    return key, secret


def revoke_key(db: Session, user: User, key_id: uuid.UUID, clock: Clock) -> None:
    key = db.get(AccessKey, key_id)
    if key is None or key.user_id != user.id or key.revoked_at is not None:
        raise NotFoundError("Key not found.", code="KEY_NOT_FOUND")
    key.revoked_at = clock.now()
    db.commit()


def authenticate_key(db: Session, secret: str, clock: Clock) -> User:
    key = db.scalar(select(AccessKey).where(AccessKey.key_hash == hash_token(secret)))
    if key is None or key.revoked_at is not None:
        raise UnauthorizedError(
            "This key isn't valid. It may have been revoked; create a new one in Me.",
            code="INVALID_KEY",
        )
    user = db.get(User, key.user_id)
    if user is None:  # pragma: no cover - keys are deleted with their account
        raise UnauthorizedError("This key isn't valid.", code="INVALID_KEY")
    key.last_used_at = clock.now()
    db.commit()  # shown in Me, so a key used by someone else is noticed
    return user
