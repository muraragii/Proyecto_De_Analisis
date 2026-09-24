"""Perfilado de datos: infiere el tipo semántico de cada columna, calcula estadísticas y
detecta problemas de calidad que podrían distorsionar los resultados.

El tipo semántico (no el dtype de pandas) es lo que usa el motor de recomendación:
una columna de texto con fechas es DATETIME, un entero con valores únicos llamado
"id_pedido" es IDENTIFIER, etc.
"""

import re
import warnings

import numpy as np
import pandas as pd

from app.profiling.schemas import (
    ColumnProfile,
    DatasetProfile,
    DataWarning,
    GeoRole,
    SemanticType,
    WarningLevel,
)
from app.text import name_tokens

# Proporción mínima de valores no nulos que deben convertirse para aceptar un tipo.
PARSE_THRESHOLD = 0.9
MAX_CATEGORIES = 50
MAX_LEVELS = 5  # enteros con tan pocos valores distintos son una escala, no una cantidad
MAX_CATEGORY_RATIO = 0.5
LONG_TEXT_CHARS = 40
TOP_VALUES = 10
HIGH_NULL_RATIO = 0.2
OUTLIER_IQR_FACTOR = 3.0
MAX_OUTLIER_RATIO = 0.01  # si hay más, es una distribución de cola larga, no errores

ID_TOKENS = {"id", "uuid", "guid", "folio", "codigo", "code", "key", "clave"}
# Claves de transacción: agrupan filas de un mismo pedido/ticket (exportaciones con una
# fila por producto). Solo cuentan si el nombre no dice nada más ("estado_pedido" no es clave).
ORDER_TOKENS = {"ticket", "pedido", "orden", "order", "folio", "factura", "invoice",
                "transaccion", "transaction", "recibo", "receipt", "comanda"}
ORDER_FILLER = {"id", "no", "num", "numero", "nro", "n", "de", "del", "number", "nbr"}
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

# --- Aditividad: qué métricas se pueden sumar ---
NON_ADDITIVE_TOKENS = {
    "tasa", "rate", "porcentaje", "porc", "pct", "percent", "percentage", "ratio",
    "promedio", "avg", "average", "media", "mean", "rating", "calificacion", "puntuacion",
    "score", "estrellas", "stars", "edad", "age", "temperatura", "temp", "saldo", "balance",
}
ADDITIVE_TOKENS = {
    "total", "importe", "monto", "venta", "ventas", "ingreso", "ingresos", "cantidad",
    "unidades", "qty", "quantity", "subtotal", "revenue", "sales", "amount", "costo", "cost",
    "propina", "tip", "pago", "cobro", "comensales", "personas", "visitas", "piezas",
}
# El precio unitario no se suma cuando existe una columna de cantidad (la venta es
# precio x cantidad). Sin cantidad, cada fila suele ser una venta y sí se suma.
PRICE_TOKENS = {"precio", "price", "unitario", "unit"}
AGE_TOKENS = {"edad", "age", "anos"}
MAX_AGE = 110
QUANTITY_TOKENS = {"cantidad", "qty", "quantity", "unidades", "units", "piezas"}
LINE_TOTAL_TOKENS = {"total", "subtotal", "importe", "monto", "amount"}
# Columnas que ya son el importe de la venta (si existe una, no se calcula cantidad x precio).
MONEY_TOKENS = {"total", "subtotal", "importe", "monto", "amount", "venta", "ventas", "ingreso",
                "ingresos", "revenue", "sales", "facturacion"}

_DATE_LIKE = re.compile(r"\d.*[-/:.]|[a-zA-Z]{3,}.*\d|\d.*[a-zA-Z]{3,}")
_TIME_OF_DAY = re.compile(r"\d{1,2}:\d{2}(:\d{2}(\.\d+)?)?\s*([ap]\.?\s?m\.?)?", re.IGNORECASE)
_DAY_MONTH = re.compile(r"^\s*(\d{1,2})[/\-.](\d{1,2})[/\-.]\d{2,4}")
_CURRENCY_CHARS = re.compile(r"[$€£%\s]|MXN|USD|EUR|COP|ARS|CLP|PEN", re.IGNORECASE)
_THOUSANDS_COMMA = re.compile(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$")
_THOUSANDS_DOT = re.compile(r"^-?\d{1,3}(\.\d{3})+(,\d+)?$")


def profile_dataframe(df: pd.DataFrame) -> tuple[DatasetProfile, pd.DataFrame]:
    """Devuelve el perfil y una copia del DataFrame con los tipos ya convertidos."""
    coerced = df.copy()
    columns: list[ColumnProfile] = []
    issues: list[DataWarning] = []

    for name in df.columns:
        semantic_type, series, extra = _infer(df[name], name)
        coerced[name] = series
        column = _describe(name, df[name], series, semantic_type)
        column.stats.update(extra)
        columns.append(column)
        issues += _conversion_issues(column, df[name], series)

    has_quantity = any(
        c.semantic_type == SemanticType.NUMERIC and set(name_tokens(c.name)) & QUANTITY_TOKENS
        for c in columns
    )
    for column in columns:
        if column.semantic_type == SemanticType.NUMERIC:
            column.additive = _is_additive(column, df[column.name], has_quantity)
            issues += _value_issues(column, coerced[column.name])

    combined = _combine_date_and_time(columns, coerced)
    if combined is not None:
        columns.append(combined)
        date, time = combined.stats["derived_datetime_from"]
        issues.append(DataWarning(
            level=WarningLevel.INFO, code="date_time_combined", column=combined.name,
            message=f"La fecha y la hora vienen en columnas separadas: se combinaron "
                    f"'{date}' y '{time}' en '{combined.name}' para analizar horarios.",
        ))

    derived = _derive_line_total(columns, coerced)
    if derived is not None:
        columns.append(derived)
        quantity, price = derived.stats["derived_from"]
        issues.append(DataWarning(
            level=WarningLevel.INFO, code="derived_total", column=derived.name,
            message=f"No hay una columna con el importe de cada venta: se calculó "
                    f"'{derived.name}' = '{quantity}' × '{price}'.",
        ))

    profile = DatasetProfile(n_rows=len(df), n_cols=len(df.columns), columns=columns)
    profile.warnings = _dataset_issues(df, profile) + issues
    return profile, coerced


def coerce_dataframe(df: pd.DataFrame, profile: DatasetProfile) -> pd.DataFrame:
    """Reaplica las conversiones de un perfil guardado a un DataFrame recién leído."""
    coerced = df.copy()
    for col in profile.columns:
        if datetime_from := col.stats.get("derived_datetime_from"):
            date, time = datetime_from
            coerced[col.name] = coerced[date].dt.normalize() + coerced[time]
            continue
        if derived_from := col.stats.get("derived_from"):
            quantity, price = derived_from
            coerced[col.name] = coerced[quantity] * coerced[price]
            continue
        if col.name not in coerced.columns:
            continue
        if col.semantic_type == SemanticType.NUMERIC:
            coerced[col.name] = _to_numeric(coerced[col.name])
        elif col.semantic_type == SemanticType.DATETIME:
            coerced[col.name] = _to_datetime(coerced[col.name], col.stats.get("date_order"))
        elif col.semantic_type == SemanticType.TIME:
            coerced[col.name] = _to_time_of_day(coerced[col.name])
    return coerced


# --- Inferencia ---------------------------------------------------------------------------


def _infer(series: pd.Series, name: str) -> tuple[SemanticType, pd.Series, dict]:
    values = series.dropna()
    tokens = set(name_tokens(name))

    if pd.api.types.is_bool_dtype(series):
        return SemanticType.BOOLEAN, series, {}
    if pd.api.types.is_datetime64_any_dtype(series):
        return SemanticType.DATETIME, _without_timezone(series), {}
    if pd.api.types.is_numeric_dtype(series):
        return _classify_numeric(values, tokens), series, {}

    as_text = values.astype(str).str.strip()
    lowered = as_text.str.lower()
    if not lowered.empty and lowered.isin(BOOLEAN_STRINGS).all() and lowered.nunique() == 2:
        return SemanticType.BOOLEAN, series, {}

    numeric = _to_numeric(series) if _looks_numeric(values) else None
    ratio = _parse_ratio(numeric, values) if numeric is not None else 0.0
    if ratio >= PARSE_THRESHOLD:
        semantic_type = _classify_numeric(numeric.dropna(), tokens)
        if semantic_type in (SemanticType.IDENTIFIER, SemanticType.CATEGORICAL) and ratio < 1:
            # Códigos casi siempre numéricos ("489434") con excepciones ("C489449", una
            # cancelación): convertirlos borraría justo las excepciones. Se quedan como texto.
            return semantic_type, series, {}
        extra = {"percent": True} if as_text.str.endswith("%").mean() >= 0.5 else {}
        symbols = as_text.str.extract(r"([$€£])", expand=False).dropna()
        if len(symbols) >= 0.5 * len(as_text):
            extra["currency"] = symbols.mode().iloc[0]  # solo si el archivo la trae
        return semantic_type, numeric, extra

    if as_text.str.fullmatch(_TIME_OF_DAY).mean() >= PARSE_THRESHOLD:
        return SemanticType.TIME, _to_time_of_day(series), {}

    if as_text.str.contains(_DATE_LIKE).mean() >= PARSE_THRESHOLD:
        order = _date_order(as_text)
        dates = _to_datetime(series, order)
        if _parse_ratio(dates, values) >= PARSE_THRESHOLD:
            return SemanticType.DATETIME, dates, {"date_order": order} if order else {}

    return _classify_text(as_text, tokens), series, {}


def _is_order_key(tokens: set[str]) -> bool:
    return bool(tokens & ORDER_TOKENS) and tokens <= ORDER_TOKENS | ORDER_FILLER


def _classify_numeric(values: pd.Series, tokens: set[str]) -> SemanticType:
    if values.nunique() == 2 and set(values.unique()) == {0, 1}:
        return SemanticType.BOOLEAN
    unique_ratio = values.nunique() / len(values) if len(values) else 0
    is_integer = len(values) and np.all(np.mod(values, 1) == 0)
    if tokens & ID_TOKENS:
        # "Customer ID" se repite en muchas filas y "PatientId" a veces trae decimales por
        # errores de exportación; siguen siendo claves: nunca se suman.
        few = values.nunique() <= MAX_CATEGORIES
        return SemanticType.CATEGORICAL if few and unique_ratio < 0.9 else SemanticType.IDENTIFIER
    if is_integer and _is_order_key(tokens):
        return SemanticType.IDENTIFIER
    if is_integer and tokens & CODE_TOKENS and values.nunique() <= MAX_CATEGORIES:
        return SemanticType.CATEGORICAL
    if (is_integer and 2 <= values.nunique() <= MAX_LEVELS and len(values) >= 50
            and not tokens & (ADDITIVE_TOKENS | QUANTITY_TOKENS | PRICE_TOKENS)):
        # Escalas/niveles (0-4, 1-5): "Handcap", "nivel_dolor", "satisfaccion". Sumarlos no
        # tiene sentido; como categoría sirven para agrupar.
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

    if _is_order_key(tokens) or (tokens & ID_TOKENS and unique_ratio > 0.9):
        return SemanticType.IDENTIFIER
    if avg_len < LONG_TEXT_CHARS * 1.5 and (
        n_unique <= MAX_CATEGORIES or unique_ratio <= MAX_CATEGORY_RATIO
    ):
        return SemanticType.CATEGORICAL
    return SemanticType.TEXT if avg_len >= LONG_TEXT_CHARS else SemanticType.IDENTIFIER


def _is_additive(column: ColumnProfile, original: pd.Series, has_quantity: bool) -> bool:
    tokens = set(name_tokens(column.name))
    if column.stats.get("percent") or tokens & NON_ADDITIVE_TOKENS:
        return False
    # "precio_venta" es unitario; "precio_total" no.
    if tokens & PRICE_TOKENS and has_quantity and not tokens & LINE_TOTAL_TOKENS:
        return False
    if tokens & ADDITIVE_TOKENS:
        return True
    lo, hi = column.stats.get("min"), column.stats.get("max")
    if lo is not None and 0 <= lo and hi <= 1 and pd.api.types.is_float_dtype(original):
        return False  # proporciones 0-1
    return True


DERIVED_TOTAL_NAME = "Importe (calculado)"
DERIVED_DATETIME_NAME = "Fecha y hora"


def _to_time_of_day(series: pd.Series) -> pd.Series:
    """'11:38:36' / '7:05 pm' / datetime.time -> tiempo transcurrido desde medianoche."""
    if pd.api.types.is_timedelta64_dtype(series):
        return series
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parsed = pd.to_datetime(series.astype("string").str.strip(), errors="coerce",
                                format="mixed")
    return parsed - parsed.dt.normalize()


def _combine_date_and_time(columns: list[ColumnProfile], coerced: pd.DataFrame):
    """Muchos puntos de venta exportan la fecha y la hora en columnas separadas; sin
    combinarlas no hay análisis de horarios (y la hora sola parecería una fecha de hoy)."""
    times = [c for c in columns if c.semantic_type == SemanticType.TIME]
    dates = [c for c in columns if c.semantic_type == SemanticType.DATETIME
             and not c.stats.get("has_time")]
    if not times or not dates or DERIVED_DATETIME_NAME in coerced.columns:
        return None
    date, time = dates[0], times[0]
    coerced[DERIVED_DATETIME_NAME] = coerced[date.name].dt.normalize() + coerced[time.name]
    column = _describe(DERIVED_DATETIME_NAME, coerced[DERIVED_DATETIME_NAME],
                       coerced[DERIVED_DATETIME_NAME], SemanticType.DATETIME)
    column.source_dtype = "calculada"
    column.stats["derived_datetime_from"] = [date.name, time.name]
    return column


def _derive_line_total(columns: list[ColumnProfile], coerced: pd.DataFrame) -> ColumnProfile | None:
    """Exportaciones con cantidad y precio unitario pero sin importe (muy común en tiendas
    en línea): sin esta columna no habría ninguna cifra de ventas que se pueda sumar."""
    numeric = [c for c in columns if c.semantic_type == SemanticType.NUMERIC]
    if any(c.additive and set(name_tokens(c.name)) & MONEY_TOKENS for c in numeric):
        return None
    quantity = next((c for c in numeric if set(name_tokens(c.name)) & QUANTITY_TOKENS), None)
    price = next((c for c in numeric if c.additive is False
                  and set(name_tokens(c.name)) & PRICE_TOKENS), None)
    if quantity is None or price is None or DERIVED_TOTAL_NAME in coerced.columns:
        return None
    coerced[DERIVED_TOTAL_NAME] = coerced[quantity.name] * coerced[price.name]
    column = _describe(DERIVED_TOTAL_NAME, coerced[DERIVED_TOTAL_NAME],
                       coerced[DERIVED_TOTAL_NAME], SemanticType.NUMERIC)
    column.additive = True
    column.source_dtype = "calculada"
    column.stats["derived_from"] = [quantity.name, price.name]
    if currency := price.stats.get("currency"):
        column.stats["currency"] = currency
    return column


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
    """Texto a número entendiendo formatos latinos y anglosajones, vectorizado:
    '1.234,56' -> 1234.56 · '1,234.56' -> 1234.56 · '12,5' -> 12.5 · '$1,200' -> 1200."""
    if pd.api.types.is_numeric_dtype(series):
        return series
    text = series.astype("string").str.replace(_CURRENCY_CHARS, "", regex=True)
    comma_thousands = text.str.fullmatch(_THOUSANDS_COMMA).fillna(False)
    dot_thousands = text.str.fullmatch(_THOUSANDS_DOT).fillna(False)
    decimal_comma = (~comma_thousands & ~dot_thousands & (text.str.count(",") == 1)
                     & ~text.str.contains(".", regex=False)).fillna(False)
    text = text.mask(comma_thousands, text.str.replace(",", "", regex=False))
    text = text.mask(dot_thousands,
                     text.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    text = text.mask(decimal_comma, text.str.replace(",", ".", regex=False))
    return pd.to_numeric(text, errors="coerce")


def _looks_numeric(values: pd.Series) -> bool:
    """Filtro rápido con una muestra: evita convertir columnas enteras de texto libre."""
    sample = values.sample(min(len(values), 5000), random_state=0)
    return _parse_ratio(_to_numeric(sample), sample) >= PARSE_THRESHOLD - 0.05


def _date_order(text: pd.Series) -> str | None:
    """Decide si las fechas numéricas son día/mes o mes/día mirando los datos:
    un primer número > 12 solo puede ser día; un segundo > 12, solo día en formato EE.UU.
    Devuelve 'dmy', 'mdy', 'dmy?' (ambiguo, asumimos latino) o None (sin ese formato)."""
    parts = text.str.extract(_DAY_MONTH).dropna()
    if parts.empty:
        return None
    first, second = parts[0].astype(int), parts[1].astype(int)
    if (first > 12).any():
        return "dmy"
    if (second > 12).any():
        return "mdy"
    return "dmy?"


def _to_datetime(series: pd.Series, order: str | None = None) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(series):
        return _without_timezone(series)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if order is None:
            iso = pd.to_datetime(series, errors="coerce", format="ISO8601")
            if iso.notna().sum() >= PARSE_THRESHOLD * series.notna().sum():
                return _without_timezone(iso)
        parsed = pd.to_datetime(series, errors="coerce", format="mixed", dayfirst=order != "mdy")
        return _without_timezone(parsed)


def _without_timezone(series: pd.Series) -> pd.Series:
    """'2016-04-29T18:38:08Z' trae zona horaria; se conserva la hora tal como está escrita
    (la del negocio) y se quita la zona, para que todas las fechas sean comparables."""
    if isinstance(series.dtype, pd.DatetimeTZDtype):
        return series.dt.tz_localize(None)
    return series


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
        null_ratio=round(float(series.isna().mean()), 4) if n else 0.0,
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


# --- Calidad de datos ---------------------------------------------------------------------


def _fmt(value: float) -> str:
    return f"{value:,.0f}" if abs(value) >= 100 else f"{value:,.2f}"


def _conversion_issues(column: ColumnProfile, original: pd.Series, parsed: pd.Series) -> list:
    issues = []
    if column.semantic_type in (SemanticType.NUMERIC, SemanticType.DATETIME) and not (
        pd.api.types.is_numeric_dtype(original) or pd.api.types.is_datetime64_any_dtype(original)
    ):
        text = original.astype("string").str.strip()
        bad = text.notna() & (text != "") & parsed.isna()
        if bad.any():
            n = int(bad.sum())
            number = column.semantic_type == SemanticType.NUMERIC
            examples = ", ".join(f"'{v}'" for v in text[bad].unique()[:3])
            if n == 1:
                what = f"1 valor de '{column.name}' no es {'un número' if number else 'una fecha'} " \
                       f"válido ({examples}) y se excluyó de los cálculos."
            else:
                what = f"{n} valores de '{column.name}' no son {'números' if number else 'fechas'} " \
                       f"válidos ({examples}) y se excluyeron de los cálculos."
            issues.append(DataWarning(
                level=WarningLevel.WARNING, code="unparsed_values", column=column.name,
                message=what,
            ))
    if column.stats.get("date_order") == "dmy?":
        issues.append(DataWarning(
            level=WarningLevel.INFO, code="ambiguous_date_order", column=column.name,
            message=f"Las fechas de '{column.name}' pueden leerse como día/mes o mes/día; "
                    "asumimos día/mes (formato latino).",
        ))
    if column.null_ratio > HIGH_NULL_RATIO:
        issues.append(DataWarning(
            level=WarningLevel.INFO, code="high_nulls", column=column.name,
            message=f"'{column.name}' está vacía en {column.null_ratio:.0%} de las filas; "
                    "los cálculos con ella usan solo las filas con dato.",
        ))
    return issues


def _value_issues(column: ColumnProfile, values: pd.Series) -> list:
    values = values.dropna()
    issues = []
    if set(name_tokens(column.name)) & AGE_TOKENS:
        impossible = values[(values < 0) | (values > MAX_AGE)]
        if len(impossible):
            examples = ", ".join(f"{v:g}" for v in sorted(impossible.unique())[:3])
            issues.append(DataWarning(
                level=WarningLevel.WARNING, code="impossible_values", column=column.name,
                message=f"{len(impossible)} valor(es) de '{column.name}' son imposibles para una "
                        f"edad ({examples}). Revisa la captura; afectan los promedios.",
            ))
    if len(values) >= 20:
        q1, q3 = values.quantile([0.25, 0.75])
        iqr = q3 - q1
        if iqr > 0:
            # Solo por arriba: los errores de captura típicos son ceros de más; los valores
            # bajos o negativos suelen ser devoluciones reales (se avisan aparte).
            outliers = values[values > q3 + OUTLIER_IQR_FACTOR * iqr]
            if 0 < len(outliers) <= max(1, MAX_OUTLIER_RATIO * len(values)):
                extreme = outliers.max()
                issues.append(DataWarning(
                    level=WarningLevel.WARNING, code="outliers", column=column.name,
                    message=f"{len(outliers)} valor(es) de '{column.name}' se salen mucho de lo "
                            f"normal (hasta {_fmt(extreme)}; la mediana es "
                            f"{_fmt(values.median())}). Revisa si son errores de captura.",
                ))
    if column.additive:
        negatives = int((values < 0).sum())
        if 0 < negatives < len(values):
            issues.append(DataWarning(
                level=WarningLevel.INFO, code="negative_values", column=column.name,
                message=f"'{column.name}' tiene {negatives} valores negativos (¿devoluciones o "
                        "ajustes?); se restan en los totales.",
            ))
    return issues


def _dataset_issues(df: pd.DataFrame, profile: DatasetProfile) -> list:
    issues = []
    summary_rows = df.attrs.get("summary_rows") or []
    if summary_rows:
        labels = ", ".join(f"'{v}'" for v in dict.fromkeys(summary_rows))
        n = len(summary_rows)
        rows = "1 fila de totales" if n == 1 else f"{n} filas de totales"
        issues.append(DataWarning(
            level=WarningLevel.INFO, code="summary_rows_removed",
            message=f"Se ignoró {rows} ({labels}) para no contar las cifras dos veces."
            if n == 1 else f"Se ignoraron {rows} ({labels}) para no contar las cifras dos veces.",
        ))
    if combined := df.attrs.get("sheets_combined"):
        issues.append(DataWarning(
            level=WarningLevel.INFO, code="sheets_combined",
            message=f"Se combinaron las {len(combined)} hojas del Excel "
                    f"({', '.join(repr(n) for n in combined)}) porque tienen las mismas columnas.",
        ))
    if ignored := df.attrs.get("sheets_ignored"):
        issues.append(DataWarning(
            level=WarningLevel.WARNING, code="sheets_ignored",
            message=f"Se analizó solo la hoja '{df.attrs['sheets_used']}'. Las hojas "
                    f"{', '.join(repr(n) for n in ignored)} tienen otras columnas; súbelas "
                    "como archivos aparte.",
        ))
    duplicates = int(df.duplicated().sum())
    if duplicates:
        has_id = bool(profile.of_type(SemanticType.IDENTIFIER))
        issues.append(DataWarning(
            level=WarningLevel.WARNING if has_id else WarningLevel.INFO,
            code="duplicate_rows",
            message=f"Hay {duplicates} fila(s) idénticas a otra. "
                    + ("Como incluyen el mismo identificador, probablemente sean duplicados "
                       "de la exportación e inflan las cifras."
                       if has_id else "Si no son ventas o registros reales repetidos, "
                       "inflarían las cifras."),
        ))
    return issues
