"""Presets por industria: la capa que diferencia el producto.

Cada industria define:
- roles: conceptos de negocio ("ventas", "producto", "médico"...) que se buscan en los
  nombres de columna mediante palabras clave, restringidos a tipos semánticos compatibles.
- templates: gráficos que ese negocio suele necesitar, expresados en términos de roles.

Si los roles de una plantilla se resuelven contra el dataset, se genera un ChartSpec con
título de negocio y score alto, que desplaza a las sugerencias genéricas equivalentes.
"""

from dataclasses import dataclass, field

from app.profiling import ColumnProfile, DatasetProfile, SemanticType
from app.recommender.rules import time_granularity
from app.recommender.schemas import Aggregation, ChartSpec, ChartType, XTransform
from app.text import name_tokens

AUTO = "auto"  # granularidad temporal elegida según el rango de fechas
CAT = {SemanticType.CATEGORICAL}
NUM = {SemanticType.NUMERIC}
DATE = {SemanticType.DATETIME}


@dataclass(frozen=True)
class Role:
    id: str
    keywords: tuple[str, ...]
    types: frozenset[SemanticType]
    requires_time: bool = False  # solo fechas con componente horario
    shared: bool = False  # puede reutilizar una columna ya asignada a otro rol


@dataclass(frozen=True)
class Template:
    title: str
    chart_type: ChartType
    aggregation: Aggregation
    score: float
    reason: str
    x: str | None = None  # id de rol
    y: str | None = None  # id de rol
    x_transform: XTransform | str | None = None
    limit: int | None = None


@dataclass(frozen=True)
class Industry:
    id: str
    name: str
    description: str
    roles: tuple[Role, ...]
    templates: tuple[Template, ...] = field(default_factory=tuple)


def _role(id, keywords, types, **kw) -> Role:
    return Role(id, tuple(keywords), frozenset(types), **kw)


_REVENUE = ["venta", "ventas", "revenue", "ingreso", "total", "importe", "monto", "amount",
            "sales", "subtotal", "facturacion", "pago", "cobro"]

ECOMMERCE = Industry(
    id="ecommerce",
    name="E-commerce",
    description="Tiendas en línea: ventas, productos, canales y clientes.",
    roles=(
        _role("date", ["fecha", "date", "created", "timestamp", "dia"], DATE),
        _role("revenue", _REVENUE, NUM),
        _role("quantity", ["cantidad", "qty", "quantity", "unidades", "units", "piezas"], NUM),
        _role("category", ["categoria", "category", "departamento", "familia", "linea"], CAT),
        _role("product", ["producto", "product", "articulo", "item", "sku"], CAT),
        _role("channel", ["canal", "channel", "origen", "source", "medio", "marketplace",
                          "plataforma"], CAT),
        _role("status", ["estado", "estatus", "status"], CAT),
        _role("customer", ["cliente", "customer", "comprador", "usuario"], CAT),
    ),
    templates=(
        Template("Ventas en el tiempo", ChartType.LINE, Aggregation.SUM, 0.98,
                 "La tendencia de ventas es la métrica principal de una tienda.",
                 x="date", y="revenue", x_transform=AUTO),
        Template("Top productos por ventas", ChartType.BAR, Aggregation.SUM, 0.96,
                 "Identifica los productos que más ingresos generan.",
                 x="product", y="revenue", limit=10),
        Template("Ventas totales", ChartType.KPI, Aggregation.SUM, 0.95,
                 "Ingreso total del periodo.", y="revenue"),
        Template("Ticket promedio", ChartType.KPI, Aggregation.MEAN, 0.93,
                 "Valor medio de cada venta.", y="revenue"),
        Template("Pedidos", ChartType.KPI, Aggregation.COUNT, 0.9,
                 "Número de pedidos (filas) en el periodo."),
        Template("Ventas por categoría", ChartType.BAR, Aggregation.SUM, 0.9,
                 "Qué líneas de producto sostienen el negocio.",
                 x="category", y="revenue", limit=15),
        Template("Productos más vendidos (unidades)", ChartType.BAR, Aggregation.SUM, 0.88,
                 "Rotación de inventario por producto.",
                 x="product", y="quantity", limit=10),
        Template("Unidades vendidas", ChartType.KPI, Aggregation.SUM, 0.85,
                 "Volumen total de unidades.", y="quantity"),
        Template("Ventas por canal", ChartType.PIE, Aggregation.SUM, 0.85,
                 "Peso de cada canal de adquisición en las ventas.",
                 x="channel", y="revenue"),
        Template("Mejores clientes", ChartType.BAR, Aggregation.SUM, 0.75,
                 "Clientes que más compran.", x="customer", y="revenue", limit=10),
        Template("Pedidos por estado", ChartType.BAR, Aggregation.COUNT, 0.7,
                 "Seguimiento operativo: pagados, enviados, cancelados...", x="status"),
    ),
)

RESTAURANTE = Industry(
    id="restaurante",
    name="Restaurante",
    description="Restaurantes y cafeterías: ticket promedio, horarios pico y platillos.",
    roles=(
        _role("date", ["fecha", "date", "dia", "timestamp", "apertura"], DATE),
        _role("time", ["hora", "horario", "time", "fecha", "date", "timestamp"], DATE,
              requires_time=True, shared=True),
        _role("revenue", _REVENUE + ["ticket", "cuenta", "consumo"], NUM),
        _role("covers", ["comensales", "personas", "pax", "cubiertos", "guests", "covers"], NUM),
        _role("category", ["categoria", "category", "seccion", "tipo"], CAT),
        _role("dish", ["platillo", "plato", "producto", "item", "articulo", "bebida", "menu"], CAT),
        _role("waiter", ["mesero", "mesera", "camarero", "camarera", "empleado", "waiter",
                         "server", "atendio"], CAT),
        _role("branch", ["sucursal", "local", "branch", "restaurante", "tienda"], CAT),
    ),
    templates=(
        Template("Ticket promedio", ChartType.KPI, Aggregation.MEAN, 0.97,
                 "El indicador clave de un restaurante: gasto medio por cuenta.", y="revenue"),
        Template("Horarios pico", ChartType.BAR, Aggregation.COUNT, 0.96,
                 "Volumen por hora del día para planear personal y cocina.",
                 x="time", x_transform=XTransform.HOUR),
        Template("Ventas totales", ChartType.KPI, Aggregation.SUM, 0.95,
                 "Ingreso total del periodo.", y="revenue"),
        Template("Ventas por día de la semana", ChartType.BAR, Aggregation.SUM, 0.92,
                 "Qué días concentran la demanda.",
                 x="date", y="revenue", x_transform=XTransform.WEEKDAY),
        Template("Ventas en el tiempo", ChartType.LINE, Aggregation.SUM, 0.9,
                 "Evolución de ventas.", x="date", y="revenue", x_transform=AUTO),
        Template("Platillos más vendidos", ChartType.BAR, Aggregation.COUNT, 0.9,
                 "Los platillos con más pedidos.", x="dish", limit=10),
        Template("Comensales atendidos", ChartType.KPI, Aggregation.SUM, 0.85,
                 "Total de personas atendidas (ocupación).", y="covers"),
        Template("Platillos con más ingresos", ChartType.BAR, Aggregation.SUM, 0.85,
                 "Qué platillos aportan más dinero.", x="dish", y="revenue", limit=10),
        Template("Ventas por sucursal", ChartType.BAR, Aggregation.SUM, 0.82,
                 "Comparativa entre locales.", x="branch", y="revenue"),
        Template("Tickets", ChartType.KPI, Aggregation.COUNT, 0.8,
                 "Número de cuentas/tickets registrados."),
        Template("Ventas por mesero", ChartType.BAR, Aggregation.SUM, 0.8,
                 "Desempeño del personal de servicio.", x="waiter", y="revenue"),
        Template("Ventas por categoría", ChartType.PIE, Aggregation.SUM, 0.75,
                 "Mezcla de ventas entre comida, bebida, postres...", x="category", y="revenue"),
    ),
)

CLINICA = Industry(
    id="clinica",
    name="Clínica / consultorio",
    description="Servicios de salud: citas, médicos, especialidades y asistencia.",
    roles=(
        _role("date", ["fecha", "cita", "date", "appointment", "consulta", "dia"], DATE),
        _role("time", ["hora", "horario", "time", "fecha", "cita", "date"], DATE,
              requires_time=True, shared=True),
        _role("revenue", _REVENUE + ["costo", "precio", "honorarios", "tarifa"], NUM),
        _role("specialty", ["especialidad", "specialty", "servicio", "area", "departamento"], CAT),
        _role("doctor", ["medico", "doctor", "doctora", "especialista", "profesional", "dr"], CAT),
        _role("status", ["estado", "estatus", "status", "asistencia", "asistio"],
              {SemanticType.CATEGORICAL, SemanticType.BOOLEAN}),
        _role("insurance", ["aseguradora", "seguro", "convenio", "insurance", "pagador"], CAT),
    ),
    templates=(
        Template("Citas en el tiempo", ChartType.LINE, Aggregation.COUNT, 0.95,
                 "Demanda de citas a lo largo del tiempo.", x="date", x_transform=AUTO),
        Template("Citas por médico", ChartType.BAR, Aggregation.COUNT, 0.93,
                 "Carga de trabajo por profesional.", x="doctor"),
        Template("Estado de las citas", ChartType.PIE, Aggregation.COUNT, 0.92,
                 "Asistidas vs. canceladas vs. inasistencias.", x="status"),
        Template("Citas", ChartType.KPI, Aggregation.COUNT, 0.9, "Total de citas del periodo."),
        Template("Ingresos totales", ChartType.KPI, Aggregation.SUM, 0.9,
                 "Facturación del periodo.", y="revenue"),
        Template("Citas por especialidad", ChartType.BAR, Aggregation.COUNT, 0.9,
                 "Qué servicios tienen más demanda.", x="specialty"),
        Template("Ingresos por especialidad", ChartType.BAR, Aggregation.SUM, 0.88,
                 "Qué servicios generan más ingresos.", x="specialty", y="revenue"),
        Template("Ingreso promedio por cita", ChartType.KPI, Aggregation.MEAN, 0.85,
                 "Valor medio de cada consulta.", y="revenue"),
        Template("Horarios de mayor demanda", ChartType.BAR, Aggregation.COUNT, 0.85,
                 "Horas con más citas agendadas.", x="time", x_transform=XTransform.HOUR),
        Template("Citas por día de la semana", ChartType.BAR, Aggregation.COUNT, 0.8,
                 "Qué días hay más carga en la agenda.", x="date",
                 x_transform=XTransform.WEEKDAY),
        Template("Pacientes por aseguradora", ChartType.PIE, Aggregation.COUNT, 0.75,
                 "Mezcla de pagadores.", x="insurance"),
    ),
)

INDUSTRIES: dict[str, Industry] = {i.id: i for i in (ECOMMERCE, RESTAURANTE, CLINICA)}


# --- Resolución de roles ------------------------------------------------------------------


def _match_rank(column: ColumnProfile, keywords: tuple[str, ...]) -> int | None:
    """Menor = mejor coincidencia. Prioriza el orden de las palabras clave y que la palabra
    aparezca al inicio del nombre ('producto' > 'categoria_producto' para el rol producto)."""
    tokens = name_tokens(column.name)
    best = None
    for k, keyword in enumerate(keywords):
        for pos, token in enumerate(tokens):
            if token == keyword or (len(keyword) >= 4 and token.startswith(keyword)):
                rank = k * 10 + pos
                best = rank if best is None else min(best, rank)
    return best


def resolve_roles(profile: DatasetProfile, industry: Industry) -> dict[str, str]:
    """Asigna a cada rol la columna que mejor lo representa: {rol: nombre_columna}."""
    assigned: dict[str, str] = {}
    used: set[str] = set()
    for role in industry.roles:
        candidates = []
        for col in profile.columns:
            if col.semantic_type not in role.types or (col.name in used and not role.shared):
                continue
            if role.requires_time and not col.stats.get("has_time"):
                continue
            rank = _match_rank(col, role.keywords)
            if rank is not None:
                candidates.append((rank, col.name))
        if candidates:
            name = min(candidates)[1]
            assigned[role.id] = name
            if not role.shared:
                used.add(name)
    return assigned


def industry_specs(profile: DatasetProfile, industry: Industry) -> list[ChartSpec]:
    roles = resolve_roles(profile, industry)
    specs = []
    for t in industry.templates:
        if (t.x and t.x not in roles) or (t.y and t.y not in roles):
            continue
        x = roles.get(t.x) if t.x else None
        transform = t.x_transform
        if transform == AUTO:
            transform = time_granularity(profile.column(x))
        specs.append(
            ChartSpec(
                chart_type=t.chart_type,
                title=t.title,
                x=x,
                y=roles.get(t.y) if t.y else None,
                aggregation=t.aggregation,
                x_transform=transform,
                limit=t.limit,
                score=t.score,
                reason=t.reason,
                source=f"industry:{industry.id}",
            )
        )
    return specs


def detect_industry(profile: DatasetProfile) -> tuple[str | None, float]:
    """Industria más probable según cuántas plantillas con columnas propias se pueden armar.
    Las plantillas sin roles (conteos) no cuentan: aplican a cualquier dataset."""
    best_id, best_score = None, 0.0
    for industry in INDUSTRIES.values():
        roles = resolve_roles(profile, industry)
        role_templates = [t for t in industry.templates if t.x or t.y]
        usable = [
            t for t in role_templates
            if (not t.x or t.x in roles) and (not t.y or t.y in roles)
        ]
        score = len(usable) / len(role_templates)
        if score > best_score:
            best_id, best_score = industry.id, score
    # Umbral: con menos de un tercio de plantillas aplicables no hay señal suficiente.
    if best_score < 1 / 3:
        return None, round(best_score, 3)
    return best_id, round(best_score, 3)
