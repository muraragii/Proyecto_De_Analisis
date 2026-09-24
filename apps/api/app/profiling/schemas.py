from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class SemanticType(StrEnum):
    NUMERIC = "numeric"
    CATEGORICAL = "categorical"
    DATETIME = "datetime"
    BOOLEAN = "boolean"
    IDENTIFIER = "identifier"
    TEXT = "text"


class GeoRole(StrEnum):
    LATITUDE = "lat"
    LONGITUDE = "lon"
    REGION = "region"


class ColumnProfile(BaseModel):
    name: str
    semantic_type: SemanticType
    source_dtype: str
    null_ratio: float
    n_unique: int
    unique_ratio: float
    geo_role: GeoRole | None = None
    # Solo numéricas: ¿tiene sentido sumarla? Ventas o unidades sí; precio unitario,
    # porcentajes, tasas o calificaciones no (se promedian).
    additive: bool | None = None
    # numeric: min/max/mean/median/std/sum · datetime: min/max/span_days/has_time/date_order
    # categorical/boolean: top_values [{value, count}]
    stats: dict[str, Any] = {}


class WarningLevel(StrEnum):
    INFO = "info"  # decisión que tomamos y conviene saber
    WARNING = "warning"  # puede distorsionar los resultados


class DataWarning(BaseModel):
    level: WarningLevel
    code: str
    message: str
    column: str | None = None


class DatasetProfile(BaseModel):
    n_rows: int
    n_cols: int
    columns: list[ColumnProfile]
    warnings: list[DataWarning] = []

    def of_type(self, *types: SemanticType) -> list[ColumnProfile]:
        return [c for c in self.columns if c.semantic_type in types]

    def column(self, name: str) -> ColumnProfile | None:
        return next((c for c in self.columns if c.name == name), None)
