"""Contraseñas (Argon2) y sesiones opacas guardadas en base de datos."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Response
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import settings
from app.models import UserSession

_hasher = PasswordHasher()
# Hash de referencia para gastar el mismo tiempo cuando el correo no existe y no
# revelar así qué cuentas están registradas.
_DUMMY_HASH = _hasher.hash("contraseña-inexistente")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """SQLite devuelve fechas sin zona horaria; todas se guardan en UTC."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, response: Response, user_id: str, tenant_id: str) -> None:
    now = utcnow()
    db.execute(
        delete(UserSession).where(UserSession.user_id == user_id, UserSession.expires_at < now)
    )
    token = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            token_hash=_token_hash(token),
            user_id=user_id,
            tenant_id=tenant_id,
            expires_at=now + timedelta(days=settings.session_days),
        )
    )
    db.commit()
    response.set_cookie(
        settings.session_cookie,
        token,
        max_age=settings.session_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def find_session(db: Session, token: str | None) -> UserSession | None:
    if not token:
        return None
    user_session = db.get(UserSession, _token_hash(token))
    if user_session is None or as_utc(user_session.expires_at) <= utcnow():
        return None
    return user_session


def end_session(db: Session, response: Response, token: str | None) -> None:
    if token:
        db.execute(delete(UserSession).where(UserSession.token_hash == _token_hash(token)))
        db.commit()
    response.delete_cookie(settings.session_cookie, path="/")
