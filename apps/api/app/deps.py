from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.ingestion.storage import LocalStorage, Storage
from app.models import Tenant

SessionDep = Annotated[Session, Depends(get_session)]


@lru_cache
def get_storage() -> Storage:
    return LocalStorage(settings.upload_dir)


StorageDep = Annotated[Storage, Depends(get_storage)]


def current_tenant(
    session: SessionDep, x_tenant_id: Annotated[str | None, Header()] = None
) -> Tenant:
    """PROVISIONAL hasta integrar autenticación: el tenant llega en la cabecera X-Tenant-ID
    y se crea si no existe. Con auth real, el tenant saldrá del token del usuario."""
    if not x_tenant_id or len(x_tenant_id) > 64 or not x_tenant_id.replace("-", "").isalnum():
        raise HTTPException(401, "Falta o es inválida la cabecera X-Tenant-ID")
    tenant = session.get(Tenant, x_tenant_id)
    if tenant is None:
        session.add(Tenant(id=x_tenant_id, name=x_tenant_id))
        try:
            session.commit()
        except IntegrityError:
            # Otra petición simultánea del mismo navegador lo creó primero.
            session.rollback()
        tenant = session.get(Tenant, x_tenant_id)
    return tenant


TenantDep = Annotated[Tenant, Depends(current_tenant)]
