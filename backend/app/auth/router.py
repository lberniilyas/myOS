import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.auth import keys, service
from app.auth.deps import AuthContext, get_auth, get_current_user
from app.auth.export import export_user_data
from app.auth.models import User
from app.auth.schemas import (
    AccessKeyCreate,
    AccessKeyCreated,
    AccessKeyOut,
    DeleteAccountRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
    UserUpdate,
)
from app.clock import Clock, get_clock
from app.db.session import get_db

router = APIRouter(prefix="/v1", tags=["account"])


def _token_response(user: User, tokens: service.IssuedTokens) -> TokenResponse:
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        access_expires_at=tokens.session.access_expires_at,
        refresh_expires_at=tokens.session.refresh_expires_at,
        user=UserOut.model_validate(user),
    )


@router.post("/auth/register", response_model=TokenResponse, status_code=201)
def register(
    payload: RegisterRequest, db: Session = Depends(get_db), clock: Clock = Depends(get_clock)
) -> TokenResponse:
    user, tokens = service.register(db, payload, clock)
    return _token_response(user, tokens)


@router.post("/auth/login", response_model=TokenResponse)
def login(
    payload: LoginRequest, db: Session = Depends(get_db), clock: Clock = Depends(get_clock)
) -> TokenResponse:
    user, tokens = service.login(db, payload.email, payload.password, payload.device_name, clock)
    return _token_response(user, tokens)


@router.post("/auth/refresh", response_model=TokenResponse)
def refresh(
    payload: RefreshRequest, db: Session = Depends(get_db), clock: Clock = Depends(get_clock)
) -> TokenResponse:
    user, tokens = service.refresh(db, payload.refresh_token, clock)
    return _token_response(user, tokens)


@router.post("/auth/logout", status_code=204)
def logout(
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> Response:
    service.logout(db, auth.session, clock)
    return Response(status_code=204)


@router.get("/me", response_model=UserOut)
def read_me(user: User = Depends(get_current_user)) -> User:
    return user


@router.patch("/me", response_model=UserOut)
def update_me(
    payload: UserUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> User:
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field in ("timezone", "locale", "week_start", "preferences") and value is None:
            continue
        setattr(user, field, value)
    db.commit()
    return user


@router.get("/me/export")
def export_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return export_user_data(db, user)


@router.delete("/me", status_code=204)
def delete_me(
    payload: DeleteAccountRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Permanently delete the account and every record that belongs to it."""
    service.verify_user_password(user, payload.password)
    db.delete(user)
    db.commit()
    return Response(status_code=204)


@router.get("/me/keys", response_model=list[AccessKeyOut])
def list_keys(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Your personal access keys (Shortcuts, Siri). The keys themselves are never shown again."""
    return keys.active_keys(db, user)


@router.post("/me/keys", response_model=AccessKeyCreated, status_code=201)
def create_key(
    payload: AccessKeyCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AccessKeyCreated:
    """A key that can only send entries, for an iPhone Shortcut or Siri. Shown once."""
    key, secret = keys.create_key(db, user, payload.name)
    return AccessKeyCreated(**AccessKeyOut.model_validate(key).model_dump(), key=secret)


@router.delete("/me/keys/{key_id}", status_code=204)
def revoke_key(
    key_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> Response:
    keys.revoke_key(db, user, key_id, clock)
    return Response(status_code=204)
