from dataclasses import dataclass

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth import service
from app.auth.models import AuthSession, User
from app.clock import Clock, get_clock
from app.db.session import get_db
from app.errors import UnauthorizedError

_bearer = HTTPBearer(auto_error=False)


@dataclass
class AuthContext:
    user: User
    session: AuthSession


def get_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError("Sign in to continue.", code="NOT_AUTHENTICATED")
    user, session = service.authenticate(db, credentials.credentials, clock)
    return AuthContext(user=user, session=session)


def get_current_user(auth: AuthContext = Depends(get_auth)) -> User:
    return auth.user
