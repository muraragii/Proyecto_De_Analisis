import pandas as pd
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.parsers import read_table
from app.ingestion.storage import Storage
from app.models import Dashboard, Dataset
from app.profiling import DatasetProfile, coerce_dataframe
from app.recommender import ChartSpec, chart_data


def get_dataset(session: Session, tenant_id: str, dataset_id: str) -> Dataset:
    dataset = session.scalar(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.tenant_id == tenant_id)
    )
    if dataset is None:
        raise HTTPException(404, "Dataset no encontrado")
    return dataset


def get_dashboard(session: Session, tenant_id: str, dashboard_id: str) -> Dashboard:
    dashboard = session.scalar(
        select(Dashboard).where(Dashboard.id == dashboard_id, Dashboard.tenant_id == tenant_id)
    )
    if dashboard is None:
        raise HTTPException(404, "Dashboard no encontrado")
    return dashboard


def load_dataframe(storage: Storage, dataset: Dataset) -> pd.DataFrame:
    df = read_table(storage.read(dataset.storage_key), dataset.filename)
    return coerce_dataframe(df, DatasetProfile.model_validate(dataset.profile))


def render_charts(df: pd.DataFrame, specs: list[ChartSpec]) -> list[dict]:
    """Specs + datos calculados; un gráfico cuyo cálculo falla no tumba al dashboard."""
    rendered = []
    for spec in specs:
        try:
            data, error = chart_data(df, spec), None
        except (KeyError, ValueError, TypeError) as exc:
            data, error = None, f"No se pudo calcular: {exc}"
        rendered.append({"spec": spec.model_dump(), "data": data, "error": error})
    return rendered
