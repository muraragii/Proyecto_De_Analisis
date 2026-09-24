from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import find_session
from app.config import settings
from app.db import get_session
from app.ingestion.storage import LocalStorage, Storage
from app.models import Membership, Tenant, User, UserSession

SessionDep = Annotated[Session, Depends(get_session)]


@lru_cache
def get_storage() -> Storage:
    return LocalStorage(settings.upload_dir)


StorageDep = Annotated[Storage, Depends(get_storage)]


@dataclass
class AuthContext:
    user: User
    tenant: Tenant
    role: str
    session: UserSession


def current_auth(
    db: SessionDep,
    token: Annotated[str | None, Cookie(alias=settings.session_cookie)] = None,
) -> AuthContext:
    user_session = find_session(db, token)
    if user_session is None:
        raise HTTPException(401, "Inicia sesión para continuar")
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user_session.user_id,
            Membership.tenant_id == user_session.tenant_id,
        )
    )
    if membership is None:  # lo quitaron de la organización
        raise HTTPException(401, "Ya no perteneces a esta organización")
    return AuthContext(
        user=db.get(User, user_session.user_id),
        tenant=db.get(Tenant, user_session.tenant_id),
        role=membership.role,
        session=user_session,
    )


AuthDep = Annotated[AuthContext, Depends(current_auth)]


def current_tenant(auth: AuthDep) -> Tenant:
    """Organización activa de la sesión: todo acceso a datos de negocio se filtra por ella."""
    return auth.tenant


TenantDep = Annotated[Tenant, Depends(current_tenant)]
