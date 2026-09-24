from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.deps import SessionDep, StorageDep, TenantDep
from app.models import Dashboard, new_share_token
from app.profiling import DatasetProfile
from app.recommender import INDUSTRIES, ChartSpec
from app.services import get_dashboard, get_dataset, load_dataframe, render_charts

router = APIRouter(tags=["dashboards"])


class DashboardIn(BaseModel):
    dataset_id: str
    title: str = Field(min_length=1, max_length=255)
    industry: str | None = None
    charts: list[ChartSpec] = Field(min_length=1, max_length=50)


class DashboardUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    charts: list[ChartSpec] | None = Field(default=None, min_length=1, max_length=50)


class DashboardOut(BaseModel):
    id: str
    dataset_id: str
    title: str
    industry: str | None
    share_token: str | None
    created_at: datetime
    updated_at: datetime
    charts: list[dict] | None = None  # [{spec, data, error}] al leer un dashboard concreto


def _out(d: Dashboard, charts: list[dict] | None = None) -> DashboardOut:
    return DashboardOut(
        id=d.id, dataset_id=d.dataset_id, title=d.title, industry=d.industry,
        share_token=d.share_token, created_at=d.created_at, updated_at=d.updated_at,
        charts=charts,
    )


def _validate_columns(profile: DatasetProfile, charts: list[ChartSpec]) -> None:
    names = {c.name for c in profile.columns}
    for spec in charts:
        for col in (spec.x, spec.y):
            if col is not None and col not in names:
                raise HTTPException(422, f"La columna '{col}' no existe en el dataset")


def _rendered(storage, session, dashboard: Dashboard) -> list[dict]:
    dataset = get_dataset(session, dashboard.tenant_id, dashboard.dataset_id)
    specs = [ChartSpec.model_validate(c) for c in dashboard.charts]
    return render_charts(load_dataframe(storage, dataset), specs)


@router.post("/dashboards", response_model=DashboardOut, status_code=201)
def create_dashboard(body: DashboardIn, tenant: TenantDep, session: SessionDep):
    dataset = get_dataset(session, tenant.id, body.dataset_id)
    if body.industry is not None and body.industry not in INDUSTRIES:
        raise HTTPException(400, f"Industria desconocida: {body.industry}")
    _validate_columns(DatasetProfile.model_validate(dataset.profile), body.charts)
    dashboard = Dashboard(
        tenant_id=tenant.id,
        dataset_id=dataset.id,
        title=body.title,
        industry=body.industry,
        charts=[c.model_dump(mode="json") for c in body.charts],
    )
    session.add(dashboard)
    session.commit()
    return _out(dashboard)


@router.get("/dashboards", response_model=list[DashboardOut])
def list_dashboards(tenant: TenantDep, session: SessionDep):
    rows = session.scalars(
        select(Dashboard)
        .where(Dashboard.tenant_id == tenant.id)
        .order_by(Dashboard.updated_at.desc())
    )
    return [_out(d) for d in rows]


@router.get("/dashboards/{dashboard_id}", response_model=DashboardOut)
def read_dashboard(
    dashboard_id: str, tenant: TenantDep, session: SessionDep, storage: StorageDep
):
    dashboard = get_dashboard(session, tenant.id, dashboard_id)
    return _out(dashboard, _rendered(storage, session, dashboard))


@router.patch("/dashboards/{dashboard_id}", response_model=DashboardOut)
def update_dashboard(
    dashboard_id: str, body: DashboardUpdate, tenant: TenantDep, session: SessionDep
):
    dashboard = get_dashboard(session, tenant.id, dashboard_id)
    if body.title is not None:
        dashboard.title = body.title
    if body.charts is not None:
        dataset = get_dataset(session, tenant.id, dashboard.dataset_id)
        _validate_columns(DatasetProfile.model_validate(dataset.profile), body.charts)
        dashboard.charts = [c.model_dump(mode="json") for c in body.charts]
    session.commit()
    return _out(dashboard)


@router.delete("/dashboards/{dashboard_id}", status_code=204)
def delete_dashboard(dashboard_id: str, tenant: TenantDep, session: SessionDep):
    session.delete(get_dashboard(session, tenant.id, dashboard_id))
    session.commit()


@router.post("/dashboards/{dashboard_id}/share", response_model=DashboardOut)
def share_dashboard(dashboard_id: str, tenant: TenantDep, session: SessionDep):
    dashboard = get_dashboard(session, tenant.id, dashboard_id)
    if dashboard.share_token is None:
        dashboard.share_token = new_share_token()
        session.commit()
    return _out(dashboard)


@router.delete("/dashboards/{dashboard_id}/share", response_model=DashboardOut)
def unshare_dashboard(dashboard_id: str, tenant: TenantDep, session: SessionDep):
    dashboard = get_dashboard(session, tenant.id, dashboard_id)
    dashboard.share_token = None
    session.commit()
    return _out(dashboard)


@router.get("/public/dashboards/{token}", response_model=DashboardOut)
def public_dashboard(token: str, session: SessionDep, storage: StorageDep):
    """Vista de solo lectura por enlace compartido; no requiere tenant."""
    dashboard = session.scalar(select(Dashboard).where(Dashboard.share_token == token))
    if dashboard is None:
        raise HTTPException(404, "Enlace inválido o revocado")
    out = _out(dashboard, _rendered(storage, session, dashboard))
    out.share_token = None  # no reexponer el token
    return out
