"""Perfilado de datos: infiere el tipo semántico de cada columna y calcula estadísticas.

El tipo semántico (no el dtype de pandas) es lo que usa el motor de recomendación:
una columna de texto con fechas es DATETIME, un entero con valores únicos llamado
"id_pedido" es IDENTIFIER, etc.
"""

import re
import warnings

import numpy as np
import pandas as pd

from app.profiling.schemas import ColumnProfile, DatasetProfile, GeoRole, SemanticType
from app.text import name_tokens

# Proporción mínima de valores no nulos que deben convertirse para aceptar un tipo.
PARSE_THRESHOLD = 0.9
MAX_CATEGORIES = 50
MAX_CATEGORY_RATIO = 0.5
LONG_TEXT_CHARS = 40
TOP_VALUES = 10

ID_TOKENS = {"id", "uuid", "guid", "folio", "codigo", "code", "key", "clave"}
# Enteros que son etiquetas, no cantidades: sumar números de mesa o años no tiene sentido.
CODE_TOKENS = {"mesa", "table", "habitacion", "cuarto", "room", "piso", "zona", "nivel",
               "grado", "cp", "zip", "ano", "anio", "year", "mes", "month", "semana", "week"}
BOOLEAN_STRINGS = {"si", "sí", "no", "true", "false", "yes", "verdadero", "falso", "y", "n"}
GEO_TOKENS = {
    GeoRole.LATITUDE: {"lat", "latitude", "latitud"},
    GeoRole.LONGITUDE: {"lon", "lng", "long", "longitude", "longitud"},
    GeoRole.REGION: {
        "pais", "country", "ciudad", "city", "estado", "state", "provincia", "province",
        "region", "municipio", "departamento", "comuna", "colonia", "zip", "cp",
    },
}

_DATE_LIKE = re.compile(r"\d.*[-/:.]|[a-zA-Z]{3,}.*\d|\d.*[a-zA-Z]{3,}")
_CURRENCY_CHARS = re.compile(r"[$€£%\s]|MXN|USD|EUR|COP|ARS|CLP|PEN", re.IGNORECASE)
_THOUSANDS_COMMA = re.compile(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$")
_THOUSANDS_DOT = re.compile(r"^-?\d{1,3}(\.\d{3})+(,\d+)?$")


def profile_dataframe(df: pd.DataFrame) -> tuple[DatasetProfile, pd.DataFrame]:
    """Devuelve el perfil y una copia del DataFrame con los tipos ya convertidos."""
    coerced = df.copy()
    columns = []
    for name in df.columns:
        semantic_type, series = _infer(df[name], name)
        coerced[name] = series
        columns.append(_describe(name, df[name], series, semantic_type))
    return DatasetProfile(n_rows=len(df), n_cols=len(df.columns), columns=columns), coerced


def coerce_dataframe(df: pd.DataFrame, profile: DatasetProfile) -> pd.DataFrame:
    """Reaplica las conversiones de un perfil guardado a un DataFrame recién leído."""
    coerced = df.copy()
    for col in profile.columns:
        if col.name not in coerced.columns:
            continue
        if col.semantic_type == SemanticType.NUMERIC:
            coerced[col.name] = _to_numeric(coerced[col.name])
        elif col.semantic_type == SemanticType.DATETIME:
            coerced[col.name] = _to_datetime(coerced[col.name])
    return coerced


# --- Inferencia ---------------------------------------------------------------------------


def _infer(series: pd.Series, name: str) -> tuple[SemanticType, pd.Series]:
    values = series.dropna()
    tokens = set(name_tokens(name))

    if pd.api.types.is_bool_dtype(series):
        return SemanticType.BOOLEAN, series
    if pd.api.types.is_datetime64_any_dtype(series):
        return SemanticType.DATETIME, series
    if pd.api.types.is_numeric_dtype(series):
        return _classify_numeric(series, values, tokens), series

    as_text = values.astype(str).str.strip()
    lowered = as_text.str.lower()
    if not lowered.empty and lowered.isin(BOOLEAN_STRINGS).all() and lowered.nunique() == 2:
        return SemanticType.BOOLEAN, series

    numeric = _to_numeric(series)
    if _parse_ratio(numeric, values) >= PARSE_THRESHOLD:
        return _classify_numeric(numeric, numeric.dropna(), tokens), numeric

    if as_text.str.contains(_DATE_LIKE).mean() >= PARSE_THRESHOLD:
        dates = _to_datetime(series)
        if _parse_ratio(dates, values) >= PARSE_THRESHOLD:
            return SemanticType.DATETIME, dates

    return _classify_text(as_text, tokens), series


def _classify_numeric(series: pd.Series, values: pd.Series, tokens: set[str]) -> SemanticType:
    if values.nunique() == 2 and set(values.unique()) == {0, 1}:
        return SemanticType.BOOLEAN
    unique_ratio = values.nunique() / len(values) if len(values) else 0
    if tokens & ID_TOKENS and unique_ratio > 0.9:
        return SemanticType.IDENTIFIER
    is_integer = len(values) and np.all(np.mod(values, 1) == 0)
    if is_integer and tokens & CODE_TOKENS and values.nunique() <= MAX_CATEGORIES:
        return SemanticType.CATEGORICAL
    if is_integer and unique_ratio == 1 and len(values) >= 20 and values.is_monotonic_increasing:
        return SemanticType.IDENTIFIER
    return SemanticType.NUMERIC


def _classify_text(values: pd.Series, tokens: set[str]) -> SemanticType:
    if values.empty:
        return SemanticType.CATEGORICAL
    n_unique = values.nunique()
    unique_ratio = n_unique / len(values)
    avg_len = values.str.len().mean()

    if tokens & ID_TOKENS and unique_ratio > 0.9:
        return SemanticType.IDENTIFIER
    if avg_len < LONG_TEXT_CHARS * 1.5 and (
        n_unique <= MAX_CATEGORIES or unique_ratio <= MAX_CATEGORY_RATIO
    ):
        return SemanticType.CATEGORICAL
    return SemanticType.TEXT if avg_len >= LONG_TEXT_CHARS else SemanticType.IDENTIFIER


def _geo_role(name: str, semantic_type: SemanticType) -> GeoRole | None:
    tokens = set(name_tokens(name))
    for role, keywords in GEO_TOKENS.items():
        if not tokens & keywords:
            continue
        if role == GeoRole.REGION and semantic_type == SemanticType.CATEGORICAL:
            return role
        if role != GeoRole.REGION and semantic_type == SemanticType.NUMERIC:
            return role
    return None


# --- Conversión ---------------------------------------------------------------------------


def _parse_ratio(parsed: pd.Series, original_values: pd.Series) -> float:
    if original_values.empty:
        return 0.0
    return parsed.notna().sum() / len(original_values)


def _to_numeric(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        return series
    text = series.astype("string").str.replace(_CURRENCY_CHARS, "", regex=True)
    return pd.to_numeric(text.map(_normalize_number, na_action="ignore"), errors="coerce")


def _normalize_number(text: str) -> str:
    """'1.234,56' -> '1234.56', '1,234.56' -> '1234.56', '12,5' -> '12.5'."""
    if _THOUSANDS_COMMA.match(text):
        return text.replace(",", "")
    if _THOUSANDS_DOT.match(text):
        return text.replace(".", "").replace(",", ".")
    if text.count(",") == 1 and "." not in text:
        return text.replace(",", ".")
    return text


def _to_datetime(series: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        iso = pd.to_datetime(series, errors="coerce", format="ISO8601")
        if iso.notna().sum() >= PARSE_THRESHOLD * series.notna().sum():
            return iso
        # Formato latino (dd/mm/aaaa) por defecto: la mayoría de usuarios son hispanohablantes.
        return pd.to_datetime(series, errors="coerce", format="mixed", dayfirst=True)


# --- Estadísticas -------------------------------------------------------------------------


def _describe(
    name: str, original: pd.Series, series: pd.Series, semantic_type: SemanticType
) -> ColumnProfile:
    values = series.dropna()
    n = len(original)
    n_unique = int(values.nunique())
    return ColumnProfile(
        name=name,
        semantic_type=semantic_type,
        source_dtype=str(original.dtype),
        null_ratio=round(float(original.isna().mean()), 4) if n else 0.0,
        n_unique=n_unique,
        unique_ratio=round(n_unique / len(values), 4) if len(values) else 0.0,
        geo_role=_geo_role(name, semantic_type),
        stats=_stats(values, semantic_type),
    )


def _stats(values: pd.Series, semantic_type: SemanticType) -> dict:
    if values.empty:
        return {}
    if semantic_type == SemanticType.NUMERIC:
        return {
            "min": _num(values.min()),
            "max": _num(values.max()),
            "mean": _num(values.mean()),
            "median": _num(values.median()),
            "std": _num(values.std()) if len(values) > 1 else 0.0,
            "sum": _num(values.sum()),
        }
    if semantic_type == SemanticType.DATETIME:
        lo, hi = values.min(), values.max()
        return {
            "min": lo.isoformat(),
            "max": hi.isoformat(),
            "span_days": (hi - lo).days,
            "has_time": bool((values.dt.normalize() != values).any()),
        }
    if semantic_type in (SemanticType.CATEGORICAL, SemanticType.BOOLEAN):
        counts = values.astype(str).value_counts().head(TOP_VALUES)
        return {"top_values": [{"value": v, "count": int(c)} for v, c in counts.items()]}
    return {}


def _num(value) -> float:
    return round(float(value), 4)
