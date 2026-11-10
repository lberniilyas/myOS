import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.money import normalize_currency
from app.core.timeutil import is_valid_timezone

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SUPPORTED_LOCALES = ("en", "fr", "ar")


def _check_timezone(value: str | None) -> str | None:
    if value is not None and not is_valid_timezone(value):
        raise ValueError("Unknown timezone; use an IANA name such as 'Africa/Casablanca'.")
    return value


def _check_currency(value: str | None) -> str | None:
    if value is None:
        return None
    code = normalize_currency(value)
    if code is None:
        raise ValueError("Use an ISO 4217 currency code such as 'MAD' or 'EUR'.")
    return code


def _check_locale(value: str | None) -> str | None:
    if value is not None and value not in SUPPORTED_LOCALES:
        raise ValueError(f"Supported locales: {', '.join(SUPPORTED_LOCALES)}.")
    return value


class RegisterRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=10, max_length=200)
    name: str | None = Field(default=None, max_length=200)
    timezone: str | None = None
    locale: str | None = None
    default_currency: str | None = None
    device_name: str | None = Field(default=None, max_length=200)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        value = value.strip().lower()
        if not _EMAIL.match(value):
            raise ValueError("Enter a valid email address.")
        return value

    _tz = field_validator("timezone")(_check_timezone)
    _currency = field_validator("default_currency")(_check_currency)
    _locale = field_validator("locale")(_check_locale)


class LoginRequest(BaseModel):
    email: str
    password: str
    device_name: str | None = Field(default=None, max_length=200)


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str | None
    timezone: str
    locale: str
    default_currency: str | None
    week_start: int
    preferences: dict
    created_at: datetime


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    timezone: str | None = None
    locale: str | None = None
    default_currency: str | None = None
    week_start: int | None = Field(default=None, ge=0, le=6)
    preferences: dict | None = None

    _tz = field_validator("timezone")(_check_timezone)
    _currency = field_validator("default_currency")(_check_currency)
    _locale = field_validator("locale")(_check_locale)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    access_expires_at: datetime
    refresh_expires_at: datetime
    user: UserOut


class DeleteAccountRequest(BaseModel):
    password: str


class AccessKeyCreate(BaseModel):
    name: str = Field(default="iPhone Shortcut", max_length=100, description="Where it's used.")

    @field_validator("name")
    @classmethod
    def _named(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Give the key a name, such as 'iPhone Shortcut'.")
        return value.strip()


class AccessKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    hint: str = Field(description="The key's last 4 characters.")
    created_at: datetime
    last_used_at: datetime | None


class AccessKeyCreated(AccessKeyOut):
    key: str = Field(description="Shown this once; only a hash is stored.")
