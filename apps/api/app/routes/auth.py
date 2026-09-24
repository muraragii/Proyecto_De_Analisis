from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth import (
    as_utc,
    create_session,
    end_session,
    hash_password,
    needs_rehash,
    utcnow,
    verify_password,
)
from app.config import settings
from app.deps import AuthDep, SessionDep
from app.models import Membership, Role, Tenant, User

router = APIRouter(prefix="/auth", tags=["auth"])

PASSWORD = Field(min_length=8, max_length=128)


class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = PASSWORD
    organization_name: str = Field(min_length=1, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


class SwitchIn(BaseModel):
    organization_id: str


class UserOut(BaseModel):
    id: str
    email: str
    name: str


class OrganizationOut(BaseModel):
    id: str
    name: str
    role: str


class MeOut(BaseModel):
    user: UserOut
    organization: OrganizationOut
    organizations: list[OrganizationOut]


def _me(db, user: User, tenant_id: str) -> MeOut:
    rows = db.execute(
        select(Tenant, Membership.role)
        .join(Membership, Membership.tenant_id == Tenant.id)
        .where(Membership.user_id == user.id)
        .order_by(Membership.created_at)
    ).all()
    orgs = [OrganizationOut(id=t.id, name=t.name, role=role) for t, role in rows]
    return MeOut(
        user=UserOut(id=user.id, email=user.email, name=user.name),
        organization=next(o for o in orgs if o.id == tenant_id),
        organizations=orgs,
    )


@router.post("/register", response_model=MeOut, status_code=201)
def register(body: RegisterIn, db: SessionDep, response: Response):
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Ya existe una cuenta con ese correo")

    user = User(email=email, name=body.name.strip(), password_hash=hash_password(body.password))
    tenant = Tenant(name=body.organization_name.strip())
    db.add_all([user, tenant])
    db.flush()
    db.add(Membership(user_id=user.id, tenant_id=tenant.id, role=Role.OWNER))
    try:
        db.commit()
    except IntegrityError as exc:  # registro simultáneo con el mismo correo
        db.rollback()
        raise HTTPException(409, "Ya existe una cuenta con ese correo") from exc

    create_session(db, response, user.id, tenant.id)
    return _me(db, user, tenant.id)


@router.post("/login", response_model=MeOut)
def login(body: LoginIn, db: SessionDep, response: Response):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    now = utcnow()

    if user and user.locked_until and as_utc(user.locked_until) > now:
        minutes = int((as_utc(user.locked_until) - now).total_seconds() // 60) + 1
        raise HTTPException(429, f"Demasiados intentos fallidos. Intenta de nuevo en {minutes} min.")

    if not verify_password(user.password_hash if user else None, body.password):
        if user:
            user.failed_logins += 1
            if user.failed_logins >= settings.max_login_failures:
                user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
                user.failed_logins = 0
            db.commit()
        raise HTTPException(401, "Correo o contraseña incorrectos")

    user.failed_logins = 0
    user.locked_until = None
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    membership = db.scalar(
        select(Membership).where(Membership.user_id == user.id).order_by(Membership.created_at)
    )
    if membership is None:
        db.commit()
        raise HTTPException(403, "Tu usuario no pertenece a ninguna organización")

    create_session(db, response, user.id, membership.tenant_id)
    return _me(db, user, membership.tenant_id)


@router.post("/logout", status_code=204)
def logout(
    db: SessionDep,
    response: Response,
    token: Annotated[str | None, Cookie(alias=settings.session_cookie)] = None,
):
    end_session(db, response, token)


@router.get("/me", response_model=MeOut)
def me(auth: AuthDep, db: SessionDep):
    return _me(db, auth.user, auth.tenant.id)


@router.post("/organization", response_model=MeOut)
def switch_organization(body: SwitchIn, auth: AuthDep, db: SessionDep):
    """Cambia la organización activa de la sesión (para usuarios en varios equipos)."""
    member = db.scalar(
        select(Membership).where(
            Membership.user_id == auth.user.id, Membership.tenant_id == body.organization_id
        )
    )
    if member is None:
        raise HTTPException(404, "Organización no encontrada")
    auth.session.tenant_id = body.organization_id
    db.commit()
    return _me(db, auth.user, body.organization_id)
