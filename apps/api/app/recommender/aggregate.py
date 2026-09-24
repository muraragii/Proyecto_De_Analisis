"""Ejecuta un ChartSpec sobre el DataFrame y devuelve los datos listos para el frontend."""

import math
from typing import Any

import numpy as np
import pandas as pd

from app.recommender.schemas import Aggregation, ChartSpec, ChartType, XTransform

TABLE_ROWS = 100
SCATTER_POINTS = 1000
PIE_SLICES = 5
WEEKDAYS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def chart_data(df: pd.DataFrame, spec: ChartSpec) -> dict[str, Any]:
    if spec.chart_type == ChartType.KPI:
        return {"value": _clean(_aggregate_all(df, spec))}
    if spec.chart_type == ChartType.TABLE:
        head = df.head(TABLE_ROWS)
        return {
            "columns": list(df.columns),
            "rows": [[_clean(v) for v in row] for row in head.itertuples(index=False)],
            "total_rows": len(df),
        }
    if spec.chart_type == ChartType.SCATTER:
        points = df[[spec.x, spec.y]].dropna()
        if len(points) > SCATTER_POINTS:
            points = points.sample(SCATTER_POINTS, random_state=0)
        return {"points": [{"x": _clean(a), "y": _clean(b)} for a, b in points.itertuples(index=False)]}
    return {"points": _grouped(df, spec)}


def _aggregate_all(df: pd.DataFrame, spec: ChartSpec):
    if spec.aggregation == Aggregation.COUNT or spec.y is None:
        return len(df)
    values = df[spec.y].dropna()
    return values.mean() if spec.aggregation == Aggregation.MEAN else values.sum()


def _grouped(df: pd.DataFrame, spec: ChartSpec) -> list[dict]:
    keys, ordered = _group_keys(df[spec.x], spec.x_transform)
    frame = pd.DataFrame({"x": keys})
    if spec.y and spec.aggregation != Aggregation.COUNT:
        frame["y"] = df[spec.y]
        grouped = frame.dropna(subset=["x"]).groupby("x", sort=False)["y"]
        result = grouped.mean() if spec.aggregation == Aggregation.MEAN else grouped.sum()
    else:
        result = frame.dropna(subset=["x"]).groupby("x", sort=False).size()

    if ordered:
        result = result.sort_index()
    else:
        result = result.sort_values(ascending=False)
        if spec.chart_type == ChartType.PIE and len(result) > PIE_SLICES + 1:
            others = result.iloc[PIE_SLICES:].sum()
            result = pd.concat([result.iloc[:PIE_SLICES], pd.Series({"Otros": others})])
        elif spec.limit:
            result = result.head(spec.limit)

    return [{"x": _label(k, spec.x_transform), "y": _clean(v)} for k, v in result.items()]


def _group_keys(series: pd.Series, transform: XTransform | None) -> tuple[pd.Series, bool]:
    """Devuelve (claves de agrupación, si tienen orden natural)."""
    if pd.api.types.is_datetime64_any_dtype(series):
        match transform:
            case XTransform.HOUR:
                return series.dt.hour, True
            case XTransform.WEEKDAY:
                return series.dt.dayofweek, True
            case XTransform.WEEK:
                return series.dt.to_period("W").dt.start_time, True
            case XTransform.MONTH:
                return series.dt.to_period("M").dt.start_time, True
            case _:
                return series.dt.normalize(), True
    return series.astype("string"), False


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
