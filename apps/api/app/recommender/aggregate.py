"""Ejecuta un ChartSpec sobre el DataFrame y devuelve los datos listos para el frontend.

Aquí se decide si una cifra es correcta, así que cada regla evita un error clásico:
- series de tiempo completas: un periodo sin ventas vale 0, no desaparece;
- primer/último periodo marcados como incompletos si los datos no los cubren enteros;
- día de la semana / hora como promedio por día del calendario (per_day), no como total;
- promedios por transacción (group_by) cuando el archivo trae una fila por producto.
"""

import math
from typing import Any

import numpy as np
import pandas as pd

from app.recommender.schemas import Aggregation, ChartSpec, ChartType, XTransform

TABLE_ROWS = 100
SCATTER_POINTS = 1000
PIE_SLICES = 5
WEEKDAYS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
WEEKDAY_NAMES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábados", "domingos"]
TIME_SERIES = {XTransform.DAY, XTransform.WEEK, XTransform.MONTH}
PERIOD_NAME = {XTransform.DAY: "día", XTransform.WEEK: "semana", XTransform.MONTH: "mes"}
PERIOD_WHOLE = {XTransform.WEEK: "esa semana completa", XTransform.MONTH: "ese mes completo"}
PERIOD_FREQ = {XTransform.DAY: "D", XTransform.WEEK: "W", XTransform.MONTH: "M"}


def chart_data(df: pd.DataFrame, spec: ChartSpec) -> dict[str, Any]:
    if spec.chart_type == ChartType.KPI:
        value, notes = _kpi(df, spec)
        return {"value": _clean(value), "notes": notes}
    if spec.chart_type == ChartType.TABLE:
        head = df.head(TABLE_ROWS)
        return {
            "columns": list(df.columns),
            "rows": [[_clean(v) for v in row] for row in head.itertuples(index=False)],
            "total_rows": len(df),
        }
    if spec.chart_type == ChartType.SCATTER:
        points = df[[spec.x, spec.y]].dropna()
        notes = []
        if len(points) > SCATTER_POINTS:
            notes.append(f"Muestra aleatoria de {SCATTER_POINTS:,} de {len(points):,} puntos.")
            points = points.sample(SCATTER_POINTS, random_state=0)
        return {
            "points": [{"x": _clean(a), "y": _clean(b)} for a, b in points.itertuples(index=False)],
            "notes": notes,
        }
    return _grouped(df, spec)


# --- KPI ----------------------------------------------------------------------------------


def _kpi(df: pd.DataFrame, spec: ChartSpec) -> tuple[Any, list[str]]:
    g = spec.group_by
    if g and spec.y and spec.aggregation in (Aggregation.COUNT, Aggregation.MEAN):
        # Por transacción, solo cuentan las ventas: las devoluciones/cancelaciones (total
        # negativo) y los movimientos en cero no son pedidos ni entran al ticket promedio.
        per_group = df.groupby(g)[spec.y].sum(min_count=1).dropna()
        sales = per_group[per_group > 0]
        excluded = len(per_group) - len(sales)
        notes = [f"Sin contar {excluded:,} '{g}' con total negativo o en cero "
                 "(devoluciones, cancelaciones o ajustes)."] if excluded else []
        if spec.aggregation == Aggregation.COUNT:
            return len(sales), notes
        return sales.mean(), [f"Promedio del total de cada '{g}' ({len(sales):,})."] + notes
    if spec.aggregation == Aggregation.COUNT or spec.y is None:
        if g:
            n = df[g].nunique()
            notes = [f"{n:,} valores distintos de '{g}' en {len(df):,} filas."] if n != len(df) else []
            return n, notes
        return len(df), []
    values = df[spec.y]
    if spec.aggregation == Aggregation.SUM:
        return values.sum(), []
    return values.mean(), []


# --- Gráficos agrupados -------------------------------------------------------------------


def _grouped(df: pd.DataFrame, spec: ChartSpec) -> dict[str, Any]:
    x_col = df[spec.x]
    frame = pd.DataFrame({"x": _group_keys(x_col, spec.x_transform)})
    if spec.y:
        frame["y"] = df[spec.y]
    if spec.group_by:
        frame["g"] = df[spec.group_by]
    frame = frame.dropna(subset=["x"])
    result = _aggregate(frame, spec)
    notes: list[str] = []
    partial: set = set()

    is_date = pd.api.types.is_datetime64_any_dtype(x_col)
    if is_date and x_col.dropna().empty:
        return {"points": [], "notes": [f"'{spec.x}' no tiene fechas válidas."]}
    if is_date and spec.x_transform in (XTransform.HOUR, XTransform.WEEKDAY):
        result = _complete_cyclic(result, x_col, spec, notes)
    elif is_date:
        transform = spec.x_transform or XTransform.DAY
        result, partial = _complete_series(result, x_col, transform, spec, notes)
    else:
        result = result.sort_values(ascending=False)
        if spec.chart_type == ChartType.PIE:
            result = _pie_slices(result, spec)
        elif spec.limit and len(result) > spec.limit:
            notes.append(f"Top {spec.limit} de {len(result)} valores de '{spec.x}'.")
            result = result.head(spec.limit)

    points = [
        {"x": _label(k, spec.x_transform), "y": _clean(v), **({"partial": True} if k in partial else {})}
        for k, v in result.items()
    ]
    return {"points": points, "notes": notes}


def _aggregate(frame: pd.DataFrame, spec: ChartSpec) -> pd.Series:
    grouped = frame.groupby("x", sort=True)
    has_g = "g" in frame
    if spec.aggregation == Aggregation.COUNT or "y" not in frame:
        return grouped["g"].nunique() if has_g else grouped.size()
    if spec.aggregation == Aggregation.SUM:
        return grouped["y"].sum()
    if has_g:  # promedio de los totales de cada transacción
        per_group = frame.groupby(["x", "g"])["y"].sum(min_count=1)
        return per_group.groupby(level="x").mean()
    return grouped["y"].mean()


def _complete_series(result, x_col, transform, spec, notes):
    """Rellena periodos sin registros (0 en sumas/conteos) y marca los incompletos."""
    first_day, last_day = x_col.min().normalize(), x_col.max().normalize()
    periods = pd.period_range(first_day, last_day, freq=PERIOD_FREQ[transform])
    index = periods.start_time
    fill = np.nan if spec.aggregation == Aggregation.MEAN else 0
    missing = len(index.difference(result.index))
    result = result.reindex(index, fill_value=fill)
    name = PERIOD_NAME[transform]

    if missing and spec.aggregation != Aggregation.MEAN:
        notes.append(f"{missing} {name}(s) sin registros se muestran en 0.")

    partial = set()
    if transform != XTransform.DAY:
        if periods[0].start_time < first_day:
            partial.add(index[0])
        if periods[-1].end_time.normalize() > last_day:
            partial.add(index[-1])
        if partial and spec.aggregation != Aggregation.MEAN:
            which = " y ".join(
                label for label, key in (("el primer", index[0]), ("el último", index[-1]))
                if key in partial
            )
            notes.append(
                f"Periodo incompleto ({which} punto, línea punteada): los datos no cubren "
                f"{PERIOD_WHOLE[transform]}, así que su valor se ve más bajo de lo real."
            )
    return result, partial


def _complete_cyclic(result, x_col, spec, notes):
    """Hora del día / día de la semana: todas las categorías y, con per_day, el promedio
    por día del calendario en lugar del total."""
    if spec.x_transform == XTransform.WEEKDAY:
        index = pd.Index(range(7))
    else:
        hours = result.index
        index = pd.Index(range(int(hours.min()), int(hours.max()) + 1)) if len(hours) else hours
    fill = np.nan if spec.aggregation == Aggregation.MEAN else 0
    result = result.reindex(index, fill_value=fill)

    if spec.per_day and spec.aggregation != Aggregation.MEAN:
        days = pd.date_range(x_col.min().normalize(), x_col.max().normalize(), freq="D")
        if spec.x_transform == XTransform.WEEKDAY:
            occurrences = pd.Series(days.dayofweek).value_counts().reindex(index, fill_value=0)
            result = result / occurrences.replace(0, np.nan)
            counts = ", ".join(
                f"{occurrences[d]} {WEEKDAY_NAMES[d]}" for d in index if occurrences[d]
            )
            notes.append(f"Promedio por día: el periodo incluye {counts}.")
        else:
            result = result / len(days)
            notes.append(f"Promedio por día en los {len(days)} días del periodo.")
    return result


def _pie_slices(result: pd.Series, spec: ChartSpec) -> pd.Series:
    if spec.aggregation == Aggregation.MEAN:
        raise ValueError("un gráfico de pastel muestra partes de un total; no aplica a promedios")
    if (result < 0).any():
        raise ValueError("un gráfico de pastel no puede mostrar valores negativos")
    if len(result) > PIE_SLICES + 1:
        others = result.iloc[PIE_SLICES:].sum()
        result = pd.concat([result.iloc[:PIE_SLICES], pd.Series({"Otros": others})])
    return result


def _group_keys(series: pd.Series, transform: XTransform | None) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(series):
        match transform:
            case XTransform.HOUR:
                return series.dt.hour
            case XTransform.WEEKDAY:
                return series.dt.dayofweek
            case XTransform.WEEK | XTransform.MONTH:
                return series.dt.to_period(PERIOD_FREQ[transform]).dt.start_time
            case _:
                return series.dt.normalize()
    if pd.api.types.is_bool_dtype(series):
        return series.map({True: "Sí", False: "No"})
    if pd.api.types.is_float_dtype(series) and (series.dropna() % 1 == 0).all():
        series = series.astype("Int64")  # códigos/IDs leídos como float: 12346.0 -> 12346
    return series.astype("string")


def _label(key, transform: XTransform | None):
    if transform == XTransform.WEEKDAY:
        return WEEKDAYS[int(key)]
    if transform == XTransform.HOUR:
        return f"{int(key):02d}:00"
    if isinstance(key, pd.Timestamp):
        return key.strftime("%Y-%m") if transform == XTransform.MONTH else key.date().isoformat()
    return _clean(key)


def _clean(value):
    """Convierte tipos de numpy/pandas a JSON serializable."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return None if math.isnan(value) else round(float(value), 2)
    if isinstance(value, np.bool_):
        return bool(value)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value
