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
    limit: int | None = None
    score: float = 0.0
    reason: str = ""
    source: str = "rules"  # "rules" o "industry:<id>"

    def key(self) -> tuple:
        """Identidad del gráfico para deduplicar sugerencias equivalentes."""
        return (self.chart_type, self.x, self.y, self.aggregation, self.x_transform)
