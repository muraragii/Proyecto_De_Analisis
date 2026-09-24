import io

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


def cache_key(dataset_key: str) -> str:
    return f"{dataset_key}.parquet"


def save_cache(storage: Storage, dataset_key: str, df: pd.DataFrame) -> None:
    """Guarda el DataFrame ya limpio y convertido en Parquet: leerlo toma décimas de
    segundo, contra decenas de segundos de volver a leer y convertir un Excel grande."""
    out = df.copy()
    # Parquet exige un tipo por columna; el texto con valores mixtos (p. ej. códigos que a
    # veces son números) se guarda como texto.
    for name in out.columns:
        if out[name].dtype == object:
            out[name] = out[name].astype("string")
    buf = io.BytesIO()
    out.to_parquet(buf, index=False)
    storage.put(cache_key(dataset_key), buf.getvalue())


def load_dataframe(storage: Storage, dataset: Dataset) -> pd.DataFrame:
    try:
        return pd.read_parquet(io.BytesIO(storage.read(cache_key(dataset.storage_key))))
    except FileNotFoundError:
        pass  # datasets subidos antes de existir la caché
    df = read_table(storage.read(dataset.storage_key), dataset.filename)
    df = coerce_dataframe(df, DatasetProfile.model_validate(dataset.profile))
    save_cache(storage, dataset.storage_key, df)
    return df


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
