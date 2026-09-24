"""Modelos de metadata. Toda entidad de negocio lleva tenant_id: el aislamiento por cuenta
se aplica siempre filtrando por él (ver app.deps.current_tenant).

Un Tenant es una organización (un negocio). Los usuarios pertenecen a organizaciones a
través de Membership; una sesión apunta a la organización activa del usuario."""

import secrets
import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


def new_share_token() -> str:
    return secrets.token_urlsafe(16)


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True)  # siempre en minúsculas
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Role(StrEnum):
    OWNER = "owner"
    MEMBER = "member"


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "tenant_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default=Role.MEMBER)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class UserSession(Base):
    """Sesión de navegador. Solo se guarda el hash del token: si se filtra la base de
    datos, las cookies activas no se pueden reconstruir."""

    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(512))
    n_rows: Mapped[int] = mapped_column(Integer)
    n_cols: Mapped[int] = mapped_column(Integer)
    profile: Mapped[dict] = mapped_column(JSON)
    detected_industry: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Dashboard(Base):
    __tablename__ = "dashboards"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    industry: Mapped[str | None] = mapped_column(String(50))
    charts: Mapped[list] = mapped_column(JSON)  # lista de ChartSpec serializados
    share_token: Mapped[str | None] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
