from datetime import datetime

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select

from app.config import settings
from app.deps import SessionDep, StorageDep, TenantDep
from app.ingestion.parsers import SUPPORTED_EXTENSIONS, UnsupportedFileError, file_extension, read_table
from app.models import Dataset
from app.profiling import DatasetProfile, profile_dataframe
from app.recommender import detect_industry, recommend
from app.services import get_dataset, load_dataframe, render_charts

router = APIRouter(prefix="/datasets", tags=["datasets"])


class DatasetOut(BaseModel):
    id: str
    name: str
    filename: str
    n_rows: int
    n_cols: int
    detected_industry: str | None
    created_at: datetime
    profile: DatasetProfile | None = None


def _out(dataset: Dataset, with_profile: bool = False) -> DatasetOut:
    return DatasetOut(
        id=dataset.id,
        name=dataset.name,
        filename=dataset.filename,
        n_rows=dataset.n_rows,
        n_cols=dataset.n_cols,
        detected_industry=dataset.detected_industry,
        created_at=dataset.created_at,
        profile=DatasetProfile.model_validate(dataset.profile) if with_profile else None,
    )


@router.post("", response_model=DatasetOut, status_code=201)
async def upload_dataset(
    file: UploadFile, tenant: TenantDep, session: SessionDep, storage: StorageDep
):
    filename = file.filename or "archivo"
    if file_extension(filename) not in SUPPORTED_EXTENSIONS:
        raise HTTPException(415, "Formato no soportado. Sube un archivo CSV o Excel.")

    max_bytes = settings.max_upload_mb * 1024 * 1024
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(413, f"El archivo supera el límite de {settings.max_upload_mb} MB.")

    try:
        df = read_table(content, filename)
    except UnsupportedFileError as exc:
        raise HTTPException(415, str(exc)) from exc
    except Exception as exc:  # archivo corrupto / formato ilegible
        raise HTTPException(422, f"No se pudo leer el archivo: {exc}") from exc
    if df.empty:
        raise HTTPException(422, "El archivo no contiene datos.")

    profile, _ = profile_dataframe(df)
    industry, _ = detect_industry(profile)
    dataset = Dataset(
        tenant_id=tenant.id,
        name=filename.rsplit(".", 1)[0],
        filename=filename,
        storage_key=storage.save(tenant.id, filename, content),
        n_rows=profile.n_rows,
        n_cols=profile.n_cols,
        profile=profile.model_dump(mode="json"),
        detected_industry=industry,
    )
    session.add(dataset)
    session.commit()
    return _out(dataset, with_profile=True)


@router.get("", response_model=list[DatasetOut])
def list_datasets(tenant: TenantDep, session: SessionDep):
    rows = session.scalars(
        select(Dataset).where(Dataset.tenant_id == tenant.id).order_by(Dataset.created_at.desc())
    )
    return [_out(d) for d in rows]


@router.get("/{dataset_id}", response_model=DatasetOut)
def read_dataset(dataset_id: str, tenant: TenantDep, session: SessionDep):
    return _out(get_dataset(session, tenant.id, dataset_id), with_profile=True)


@router.get("/{dataset_id}/recommendations")
def dataset_recommendations(
    dataset_id: str,
    tenant: TenantDep,
    session: SessionDep,
    storage: StorageDep,
    industry: str = "auto",
):
    """industry: 'auto' (detectar), un id de industria, o 'none' (solo reglas genéricas)."""
    dataset = get_dataset(session, tenant.id, dataset_id)
    profile = DatasetProfile.model_validate(dataset.profile)
    try:
        rec = recommend(profile, None if industry == "none" else industry)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    df = load_dataframe(storage, dataset)
    return {
        "industry": rec.industry,
        "detected_industry": rec.detected_industry,
        "detection_confidence": rec.detection_confidence,
        "charts": render_charts(df, rec.charts),
    }
