from enum import StrEnum

from pydantic import BaseModel


class ChartType(StrEnum):
    BAR = "bar"
    LINE = "line"
    PIE = "pie"
    SCATTER = "scatter"
    KPI = "kpi"
    TABLE = "table"


class Aggregation(StrEnum):
    SUM = "sum"
    MEAN = "mean"
    COUNT = "count"


class XTransform(StrEnum):
    """Derivaciones de una columna de fecha para el eje X."""

    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    HOUR = "hour"  # hora del día (0-23): horarios pico
    WEEKDAY = "weekday"  # día de la semana


class ChartSpec(BaseModel):
    """Especificación declarativa de un gráfico. El frontend la renderiza; el backend la
    ejecuta sobre el DataFrame (ver recommender.aggregate) para obtener los datos."""

    chart_type: ChartType
    title: str
    x: str | None = None
    y: str | None = None
    aggregation: Aggregation | None = None
    x_transform: XTransform | None = None
    # Unidad de análisis: columna que agrupa filas de una misma transacción (p. ej. el
    # ticket cuando hay una fila por platillo). Con ella, SUM/MEAN se calculan sobre el
    # total de cada transacción y COUNT cuenta transacciones distintas, no filas.
    group_by: str | None = None
    # Solo con x_transform HOUR/WEEKDAY: promedio por día del calendario en lugar de total,
    # para no favorecer a los días de la semana que aparecen más veces en el rango.
    per_day: bool = False
    limit: int | None = None
    score: float = 0.0
    reason: str = ""
    source: str = "rules"  # "rules" o "industry:<id>"

    def key(self) -> tuple:
        """Identidad del gráfico para deduplicar sugerencias equivalentes."""
        return (self.chart_type, self.x, self.y, self.aggregation, self.x_transform,
                self.group_by, self.per_day)
