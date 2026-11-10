from dataclasses import dataclass

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth import keys, service
from app.auth.models import AuthSession, User
from app.clock import Clock, get_clock
from app.db.session import get_db
from app.errors import AppError, UnauthorizedError

_bearer = HTTPBearer(auto_error=False)


@dataclass
class AuthContext:
    user: User
    session: AuthSession


def _token(credentials: HTTPAuthorizationCredentials | None) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError("Sign in to continue.", code="NOT_AUTHENTICATED")
    return credentials.credentials.strip()


def get_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> AuthContext:
    token = _token(credentials)
    if keys.is_access_key(token):
        raise AppError(
            "An access key can only send entries. Sign in to the app for everything else.",
            code="KEY_NOT_ALLOWED",
            status_code=403,
        )
    user, session = service.authenticate(db, token, clock)
    return AuthContext(user=user, session=session)


def get_current_user(auth: AuthContext = Depends(get_auth)) -> User:
    return auth.user


def get_capture_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> User:
    """Sending an entry: the app's session, or a personal access key (Shortcuts, Siri)."""
    token = _token(credentials)
    if keys.is_access_key(token):
        return keys.authenticate_key(db, token, clock)
    user, _ = service.authenticate(db, token, clock)
    return user
