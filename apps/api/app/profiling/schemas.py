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
    # numeric: min/max/mean/median/std/sum · datetime: min/max/span_days/has_time
    # categorical/boolean: top_values [{value, count}]
    stats: dict[str, Any] = {}


class DatasetProfile(BaseModel):
    n_rows: int
    n_cols: int
    columns: list[ColumnProfile]

    def of_type(self, *types: SemanticType) -> list[ColumnProfile]:
        return [c for c in self.columns if c.semantic_type in types]

    def column(self, name: str) -> ColumnProfile | None:
        return next((c for c in self.columns if c.name == name), None)
