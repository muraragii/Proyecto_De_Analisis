"""Validación de gráficos armados por el usuario.

El usuario decide, pero con el mismo rigor que las recomendaciones:
- errores: combinaciones imposibles (una línea sobre texto, sumar una columna de texto);
- advertencias: combinaciones posibles pero engañosas (sumar precios unitarios, un pastel
  con 40 categorías). Se permiten, explicando por qué conviene cambiarlas.
"""

from pydantic import BaseModel

from app.profiling import ColumnProfile, DatasetProfile, SemanticType
from app.recommender.schemas import Aggregation, ChartSpec, ChartType, XTransform

MAX_LIMIT = 100
MAX_PIE_SLICES = 8
MANY_CATEGORIES = 30

NUMERIC = {SemanticType.NUMERIC}
DATE_TRANSFORMS = {XTransform.DAY, XTransform.WEEK, XTransform.MONTH, XTransform.HOUR,
                   XTransform.WEEKDAY}
CATEGORY_TYPES = {SemanticType.CATEGORICAL, SemanticType.BOOLEAN, SemanticType.IDENTIFIER}
KEY_TYPES = {SemanticType.IDENTIFIER, SemanticType.CATEGORICAL}

AGG_NAMES = {Aggregation.SUM: "suma", Aggregation.MEAN: "promedio", Aggregation.COUNT: "conteo",
             Aggregation.RATE: "porcentaje"}


class SpecCheck(BaseModel):
    errors: list[str] = []
    warnings: list[str] = []

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_spec(profile: DatasetProfile, spec: ChartSpec) -> SpecCheck:
    check = SpecCheck()
    err, warn = check.errors.append, check.warnings.append

    def column(name: str | None, what: str) -> ColumnProfile | None:
        if name is None:
            return None
        col = profile.column(name)
        if col is None:
            err(f"La columna '{name}' ({what}) no existe en el dataset.")
        return col

    x = column(spec.x, "eje X")
    y = column(spec.y, "métrica")
    group = column(spec.group_by, "agrupar por")
    if check.errors:
        return check

    kind = spec.chart_type
    if kind == ChartType.TABLE:
        return check

    if kind == ChartType.SCATTER:
        if not x or not y:
            err("La dispersión necesita dos columnas numéricas (eje X y eje Y).")
        elif x.semantic_type not in NUMERIC or y.semantic_type not in NUMERIC:
            err("La dispersión compara dos columnas numéricas; "
                f"'{(x if x.semantic_type not in NUMERIC else y).name}' no lo es.")
        return check

    _check_measure(spec, y, err, warn)

    if kind == ChartType.KPI:
        if spec.x:
            err("Un indicador (KPI) es una sola cifra: no lleva eje X.")
    else:
        _check_axis(spec, x, err, warn)

    if group is not None:
        if group.semantic_type not in KEY_TYPES:
            err(f"'{group.name}' no identifica transacciones (pedido, ticket, cita…); "
                "elige una columna de identificador.")
        elif spec.x == group.name:
            err("La columna para agrupar transacciones no puede ser la misma del eje X.")
        elif spec.aggregation == Aggregation.RATE:
            err("El porcentaje se calcula por fila; quita 'contar por transacción'.")

    if spec.limit is not None and not 1 <= spec.limit <= MAX_LIMIT:
        err(f"El top debe estar entre 1 y {MAX_LIMIT}.")
    return check


def _check_measure(spec: ChartSpec, y: ColumnProfile | None, err, warn) -> None:
    agg = spec.aggregation
    if agg is None:
        err("Elige cómo calcular la métrica (suma, promedio, conteo o porcentaje).")
        return
    if agg == Aggregation.COUNT:
        return  # cuenta filas (o transacciones distintas); la métrica es opcional
    if y is None:
        err(f"El {AGG_NAMES[agg]} necesita una columna de métrica.")
        return
    if agg == Aggregation.RATE:
        if y.semantic_type != SemanticType.BOOLEAN:
            err(f"El porcentaje es para columnas sí/no; '{y.name}' no lo es.")
        return
    if y.semantic_type not in NUMERIC:
        err(f"No se puede calcular {AGG_NAMES[agg]} de '{y.name}' porque no es numérica. "
            "Usa conteo.")
        return
    if agg == Aggregation.SUM and y.additive is False:
        warn(f"Sumar '{y.name}' no suele tener sentido (es un precio unitario, porcentaje, "
             "calificación o similar). Considera usar promedio.")


def _check_axis(spec: ChartSpec, x: ColumnProfile | None, err, warn) -> None:
    kind, agg = spec.chart_type, spec.aggregation
    if x is None:
        err("Elige la columna del eje X (categoría o fecha).")
        return
    is_date = x.semantic_type == SemanticType.DATETIME

    if kind == ChartType.LINE and not is_date:
        err("Las líneas muestran evolución en el tiempo: el eje X debe ser una fecha. "
            "Para comparar categorías usa barras.")
        return
    if is_date:
        if spec.x_transform not in DATE_TRANSFORMS:
            err("Con una fecha en el eje X, elige cómo agruparla (día, semana, mes, hora o "
                "día de la semana).")
        if kind == ChartType.LINE and spec.x_transform in (XTransform.HOUR, XTransform.WEEKDAY):
            err("Hora del día y día de la semana no son una línea de tiempo: usa barras.")
        if kind == ChartType.PIE:
            err("Un pastel sobre fechas no se lee bien; usa líneas o barras.")
    else:
        if spec.x_transform is not None:
            err(f"'{x.name}' no es una fecha: quita la agrupación de tiempo.")
        if x.semantic_type not in CATEGORY_TYPES and x.semantic_type != SemanticType.NUMERIC:
            err(f"'{x.name}' es texto libre: no sirve como categoría.")
        elif x.semantic_type == SemanticType.NUMERIC:
            warn(f"'{x.name}' es numérica: cada valor distinto será una barra. Si es una "
                 "métrica, úsala como métrica y no como eje X.")
        if x.n_unique > MANY_CATEGORIES and not spec.limit and kind == ChartType.BAR:
            warn(f"'{x.name}' tiene {x.n_unique:,} valores: conviene mostrar solo el top.")

    if spec.per_day:
        if spec.x_transform not in (XTransform.HOUR, XTransform.WEEKDAY):
            err("'Promedio por día' solo aplica a hora del día o día de la semana.")
        elif agg not in (Aggregation.SUM, Aggregation.COUNT):
            err("'Promedio por día' solo aplica a sumas y conteos.")

    if kind == ChartType.PIE:
        if agg in (Aggregation.MEAN, Aggregation.RATE):
            err("Un pastel muestra partes de un total: usa suma o conteo.")
        elif x.n_unique > MAX_PIE_SLICES:
            warn(f"'{x.name}' tiene {x.n_unique} valores: el pastel agrupará los menores en "
                 "'Otros'. Unas barras se leen mejor.")
