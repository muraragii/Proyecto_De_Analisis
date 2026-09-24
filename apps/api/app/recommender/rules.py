"""Reglas genéricas dato -> gráfico (heurísticas tipo "Show Me" de Tableau).

No dependen de la industria: solo miran la estructura del perfil. Cada regla emite
ChartSpec con un score (0-1) que después se combina con los presets de industria.
"""

from itertools import combinations

from app.profiling import ColumnProfile, DatasetProfile, GeoRole, SemanticType
from app.recommender.schemas import Aggregation, ChartSpec, ChartType, XTransform

MAX_MEASURES = 4
MAX_DIMENSIONS = 4
MAX_DATES = 2
MAX_BOOLEANS = 3
MAX_BAR_CATEGORIES = 30
MAX_PIE_CATEGORIES = 6
BAR_LIMIT = 15
MIN_SCATTER_ROWS = 10
DECAY = 0.05  # penalización por posición: las primeras columnas suelen ser las relevantes


def measures(profile: DatasetProfile) -> list[ColumnProfile]:
    return [
        c
        for c in profile.of_type(SemanticType.NUMERIC)
        if c.geo_role not in (GeoRole.LATITUDE, GeoRole.LONGITUDE)
    ]


def dimensions(profile: DatasetProfile) -> list[ColumnProfile]:
    return [
        c
        for c in profile.of_type(SemanticType.CATEGORICAL, SemanticType.BOOLEAN)
        if 2 <= c.n_unique <= MAX_BAR_CATEGORIES
    ]


def dates(profile: DatasetProfile) -> list[ColumnProfile]:
    # "Fecha y hora" combinada repetiría los gráficos de su columna de fecha.
    return [c for c in profile.of_type(SemanticType.DATETIME)
            if c.n_unique > 1 and "derived_datetime_from" not in c.stats]


def time_granularity(column: ColumnProfile) -> XTransform:
    span = column.stats.get("span_days", 0)
    if span <= 31:
        return XTransform.DAY
    if span <= 180:
        return XTransform.WEEK
    return XTransform.MONTH


GRANULARITY_LABEL = {XTransform.DAY: "día", XTransform.WEEK: "semana", XTransform.MONTH: "mes"}


def measure_agg(m: ColumnProfile) -> Aggregation:
    """Las métricas no aditivas (precio unitario, %, calificaciones) se promedian."""
    return Aggregation.MEAN if m.additive is False else Aggregation.SUM


def measure_label(m: ColumnProfile) -> str:
    return m.name if m.additive is not False else f"promedio de {m.name}"


def generic_rules(profile: DatasetProfile) -> list[ChartSpec]:
    ms = measures(profile)[:MAX_MEASURES]
    ds = dimensions(profile)[:MAX_DIMENSIONS]
    ts = dates(profile)[:MAX_DATES]
    specs: list[ChartSpec] = []

    # KPIs: varias métricas -> tarjetas de resumen
    specs.append(
        ChartSpec(
            chart_type=ChartType.KPI,
            title="Total de registros",
            aggregation=Aggregation.COUNT,
            score=0.6,
            reason="Conteo general del conjunto de datos.",
        )
    )
    for i, m in enumerate(ms):
        additive = m.additive is not False
        specs.append(
            ChartSpec(
                chart_type=ChartType.KPI,
                title=f"Total {m.name}" if additive else f"Promedio de {m.name}",
                y=m.name,
                aggregation=measure_agg(m),
                score=0.7 - DECAY * i,
                reason=f"'{m.name}' es una métrica numérica: su total resume el negocio."
                if additive
                else f"'{m.name}' no se puede sumar (precio, %, calificación…): se promedia.",
            )
        )

    # Columnas sí/no -> porcentaje (p. ej. "% de citas con No-show = Sí")
    categoricals = [d for d in ds if d.semantic_type == SemanticType.CATEGORICAL]
    for i, b in enumerate(profile.of_type(SemanticType.BOOLEAN)[:MAX_BOOLEANS]):
        specs.append(
            ChartSpec(
                chart_type=ChartType.KPI,
                title=f"% con {b.name} = Sí",
                y=b.name,
                aggregation=Aggregation.RATE,
                score=0.5 - DECAY * i,
                reason=f"'{b.name}' es sí/no: su porcentaje resume la columna.",
            )
        )
        if categoricals:
            d = categoricals[0]
            specs.append(
                ChartSpec(
                    chart_type=ChartType.BAR,
                    title=f"% con {b.name} = Sí por {d.name}",
                    x=d.name,
                    y=b.name,
                    aggregation=Aggregation.RATE,
                    limit=BAR_LIMIT,
                    score=0.45 - DECAY * i,
                    reason=f"Compara la proporción de '{b.name}' entre valores de '{d.name}'.",
                )
            )

    # Serie temporal + numérica -> líneas
    for i, t in enumerate(ts):
        gran = time_granularity(t)
        label = GRANULARITY_LABEL[gran]
        specs.append(
            ChartSpec(
                chart_type=ChartType.LINE,
                title=f"Registros por {label}",
                x=t.name,
                aggregation=Aggregation.COUNT,
                x_transform=gran,
                score=0.6 - DECAY * i,
                reason=f"'{t.name}' es una fecha: la evolución del volumen en el tiempo.",
            )
        )
        for j, m in enumerate(ms):
            specs.append(
                ChartSpec(
                    chart_type=ChartType.LINE,
                    title=f"{measure_label(m)} por {label}",
                    x=t.name,
                    y=m.name,
                    aggregation=measure_agg(m),
                    x_transform=gran,
                    score=0.9 - DECAY * (i + j),
                    reason=f"Fecha + métrica: tendencia de '{m.name}' en el tiempo.",
                )
            )

    # Categórica + numérica -> barras; pocas categorías -> pastel
    for i, d in enumerate(ds):
        specs.append(
            ChartSpec(
                chart_type=ChartType.BAR,
                title=f"Registros por {d.name}",
                x=d.name,
                aggregation=Aggregation.COUNT,
                limit=BAR_LIMIT,
                score=0.55 - DECAY * i,
                reason=f"'{d.name}' es categórica: distribución de registros por categoría.",
            )
        )
        for j, m in enumerate(ms):
            specs.append(
                ChartSpec(
                    chart_type=ChartType.BAR,
                    title=f"{measure_label(m)} por {d.name}",
                    x=d.name,
                    y=m.name,
                    aggregation=measure_agg(m),
                    limit=BAR_LIMIT,
                    score=0.8 - DECAY * (i + j),
                    reason=f"Categoría + métrica: compara '{m.name}' entre valores de '{d.name}'.",
                )
            )
        if d.n_unique <= MAX_PIE_CATEGORIES:
            specs.append(
                ChartSpec(
                    chart_type=ChartType.PIE,
                    title=f"Proporción por {d.name}",
                    x=d.name,
                    aggregation=Aggregation.COUNT,
                    score=0.5 - DECAY * i,
                    reason=f"'{d.name}' tiene {d.n_unique} categorías: proporciones de un total.",
                )
            )
            for j, m in enumerate(ms):
                if m.stats.get("min", 0) < 0 or m.additive is False:
                    continue  # un pastel solo muestra partes de un total positivo
                specs.append(
                    ChartSpec(
                        chart_type=ChartType.PIE,
                        title=f"Participación de {m.name} por {d.name}",
                        x=d.name,
                        y=m.name,
                        aggregation=Aggregation.SUM,
                        score=0.65 - DECAY * (i + j),
                        reason=f"Pocas categorías en '{d.name}': qué parte de '{m.name}' aporta cada una.",
                    )
                )

    # Dos numéricas -> dispersión
    if profile.n_rows >= MIN_SCATTER_ROWS:
        for k, (a, b) in enumerate(combinations(ms[:3], 2)):
            specs.append(
                ChartSpec(
                    chart_type=ChartType.SCATTER,
                    title=f"{b.name} vs {a.name}",
                    x=a.name,
                    y=b.name,
                    score=0.5 - DECAY * k,
                    reason=f"Dos métricas numéricas: relación entre '{a.name}' y '{b.name}'.",
                )
            )

    specs.append(
        ChartSpec(
            chart_type=ChartType.TABLE,
            title="Datos",
            score=0.3,
            reason="Vista tabular para consultar el detalle.",
        )
    )
    for spec in specs:
        spec.title = spec.title[:1].upper() + spec.title[1:]
    return specs
