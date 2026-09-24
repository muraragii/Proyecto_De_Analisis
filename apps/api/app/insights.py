"""Hallazgos en texto ("insights") calculados sobre los datos.

Principio: es mejor no decir nada que afirmar algo falso. Cada hallazgo inferencial pasa
una prueba estadística que controla la probabilidad de presentar ruido como patrón:

- día de la semana, segmentos y hora pico: pruebas de permutación, que ya contemplan que
  se elige "el mejor vs. el peor" entre varios grupos (comparaciones múltiples);
- cambio reciente: intervalo de predicción t sobre los periodos anteriores;
- tendencia: prueba t de la pendiente;
- día atípico: z robusto (mediana/MAD) en escala logarítmica.

Los periodos incompletos nunca se comparan contra periodos completos. Los hallazgos
descriptivos (concentración) son hechos de los datos y no requieren prueba.
Ver tests/test_insights.py, incluido el control de falsos positivos con datos aleatorios.
"""

import math
from dataclasses import dataclass, field
from enum import StrEnum
from statistics import NormalDist

import numpy as np
import pandas as pd
from pydantic import BaseModel

from app.profiling import DatasetProfile, SemanticType
from app.recommender.aggregate import as_flags
from app.recommender.engine import AUTO
from app.recommender.industries import INDUSTRIES, Industry, detect_industry, resolve_roles

MAX_INSIGHTS = 6
ALPHA = 0.01  # nivel de significancia de las pruebas

MIN_CATEGORIES = 5
MIN_GENERIC_CATEGORIES = 10
CONCENTRATION_SHARE = 0.5  # el 20% superior de categorías aporta al menos la mitad
MIN_CHANGE = 0.10
MIN_BASELINE_PERIODS = 4
MAX_BASELINE_PERIODS = 8
MIN_TREND_PERIODS = 8
MIN_TREND_SLOPE = 0.02
MIN_WEEKDAY_WEEKS = 3
MIN_WEEKDAY_RATIO = 1.15
LOW_ACTIVITY_SHARE = 0.2  # un día de la semana con < 20% de la actividad típica  # +15% ya importa para planear personal
MIN_SEGMENT_N = 20
MIN_SEGMENT_LIFT = 0.15
MIN_PEAK_TX = 50
PEAK_FACTOR = 1.5
MIN_RATE_GROUP = 100
MIN_RATE_DIFF = 0.02  # 2 puntos porcentuales
MIN_RATE_LIFT = 0.20  # y 20% relativo
MIN_ANOMALY_DAYS = 21
ANOMALY_LOG_Z = 3.5
ANOMALY_RATIO = 2.5

N_PERMUTATIONS = 1000
MAX_PERMUTATION_ROWS = 5000

# Valores críticos de t de Student (dos colas) para gl = 1..30: 95% y 99%.
_T_95 = [12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179,
         2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064,
         2.060, 2.056, 2.052, 2.048, 2.045, 2.042]
_T_99 = [63.657, 9.925, 5.841, 4.604, 4.032, 3.707, 3.499, 3.355, 3.250, 3.169, 3.106, 3.055,
         3.012, 2.977, 2.947, 2.921, 2.898, 2.878, 2.861, 2.845, 2.831, 2.819, 2.807, 2.797,
         2.787, 2.779, 2.771, 2.763, 2.756, 2.750]

MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre"]
WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
WEEKDAYS_PLURAL = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábados", "domingos"]

# Cómo nombrar las categorías de cada rol en los textos (singular, plural).
ROLE_NOUNS = {
    "product": ("producto", "productos"),
    "dish": ("platillo", "platillos"),
    "category": ("categoría", "categorías"),
    "customer": ("cliente", "clientes"),
    "channel": ("canal", "canales"),
    "waiter": ("mesero", "meseros"),
    "branch": ("sucursal", "sucursales"),
    "doctor": ("médico", "médicos"),
    "specialty": ("especialidad", "especialidades"),
    "insurance": ("aseguradora", "aseguradoras"),
    "status": ("estado", "estados"),
}
CONCENTRATION_ROLES = ["product", "dish", "customer", "doctor", "specialty", "category"]
# Segmentos que comparan desempeño. No se incluyen producto/categoría/especialidad: que un
# producto barato tenga pedidos más baratos es cierto pero obvio.
SEGMENT_ROLES = ["waiter", "channel", "branch", "doctor", "insurance"]


class Tone(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class Insight(BaseModel):
    kind: str
    title: str
    text: str
    tone: Tone = Tone.NEUTRAL
    basis: str  # sobre qué datos y con qué prueba se calculó
    score: float


@dataclass
class _Dim:
    column: str
    nouns: tuple[str, str]
    role: str | None  # None = columna categórica sin rol de industria
    constant: bool  # ¿tiene un solo valor dentro de cada transacción?


@dataclass
class _Context:
    df: pd.DataFrame
    tx: pd.DataFrame  # una fila por transacción: "value", "date", "time" y dimensiones
    measure: str | None
    money: bool
    currency: str  # símbolo si el archivo lo trae ("$", "€", "£"); si no, sin símbolo
    unit: tuple[str, str]
    measure_noun: str
    dims: list[_Dim] = field(default_factory=list)
    # Columna sí/no del resultado que importa (inasistencia/asistencia) y columnas con las
    # que comparar su tasa: (columna, ¿es sí/no?).
    flag: str | None = None
    flag_role: str | None = None
    rate_dims: list[tuple[str, bool]] = field(default_factory=list)


def generate_insights(
    profile: DatasetProfile, df: pd.DataFrame, industry: str | None = AUTO
) -> list[Insight]:
    if industry == AUTO:
        industry = detect_industry(profile)[0]
    ctx = _context(profile, df, INDUSTRIES.get(industry) if industry else None)
    if ctx.tx.empty:
        return []

    daily = _daily(ctx)
    found: list[Insight | None] = [_peak_hours(ctx), _best_segment(ctx), _rate_segment(ctx)]
    if daily is not None:
        found += [_anomaly(ctx, daily), _recent_change(ctx, daily), _trend(ctx, daily),
                  _weekday(ctx, daily), _closed_weekdays(ctx, daily)]
    found += [_concentration(ctx, d) for d in ctx.dims
              if d.role in CONCENTRATION_ROLES or d.role is None]

    insights = sorted((i for i in found if i), key=lambda i: i.score, reverse=True)
    return _dedupe(insights)[:MAX_INSIGHTS]


# --- Contexto -----------------------------------------------------------------------------


def _context(profile: DatasetProfile, df: pd.DataFrame, industry: Industry | None) -> _Context:
    roles = resolve_roles(profile, industry) if industry else {}

    def first(*types, pred=lambda c: True):
        return next((c.name for c in profile.of_type(*types) if pred(c)), None)

    date = roles.get("date") or first(SemanticType.DATETIME, pred=lambda c: c.n_unique > 1)
    time = roles.get("time")
    if not time and date and profile.column(date).stats.get("has_time"):
        time = date
    # Con industria sin dinero (p. ej. una clínica) se cuentan transacciones (citas); una
    # columna numérica cualquiera no es "el desempeño" del negocio.
    measure = roles.get("revenue") or (None if industry else first(
        SemanticType.NUMERIC, pred=lambda c: c.additive is not False and c.geo_role is None
    ))
    money = "revenue" in roles
    unit = industry.unit if industry else ("registro", "registros")
    if money:
        measure_noun = industry.revenue_noun
    elif measure:
        measure_noun = f"'{measure}'"
    else:
        measure_noun = unit[1]

    candidates: dict[str, tuple[tuple[str, str], str | None]] = {}
    for role in CONCENTRATION_ROLES + SEGMENT_ROLES:
        if role in roles and roles[role] not in candidates:
            candidates[roles[role]] = (ROLE_NOUNS[role], role)
    for c in profile.of_type(SemanticType.CATEGORICAL):
        if c.name not in candidates and 2 <= c.n_unique <= 30:
            candidates[c.name] = ((f"valor de '{c.name}'", f"valores de '{c.name}'"), None)

    tx, dims = _transactions(df, roles.get("order"), measure, date, time, candidates)
    currency = profile.column(measure).stats.get("currency", "") if money else ""
    flag_role = next((r for r in ("no_show", "attended") if r in roles), None)
    flag = roles.get(flag_role) if flag_role else None
    rate_dims = [(c.name, c.semantic_type == SemanticType.BOOLEAN)
                 for c in profile.of_type(SemanticType.CATEGORICAL, SemanticType.BOOLEAN)
                 if c.name != flag and 2 <= c.n_unique <= 10]
    return _Context(df=df, tx=tx, measure=measure, money=money, currency=currency, unit=unit,
                    measure_noun=measure_noun, dims=dims, flag=flag, flag_role=flag_role,
                    rate_dims=rate_dims)


def _transactions(df, order, measure, date, time, candidates):
    """Una fila por transacción. Si el archivo trae una fila por producto, se agrupa por
    la clave de transacción; las dimensiones que varían dentro de un ticket (el platillo)
    no sirven para comparar tickets entre sí."""
    if order:
        grouped = df.groupby(order, dropna=True)
        tx = pd.DataFrame({"value": grouped[measure].sum(min_count=1) if measure else 1.0})
        if date:
            tx["date"] = grouped[date].min()
        if time:
            tx["time"] = grouped[time].min()
        dims = []
        for name, (nouns, role) in candidates.items():
            constant = bool((grouped[name].nunique() <= 1).mean() >= 0.95)
            if constant:
                tx[name] = grouped[name].first()
            dims.append(_Dim(name, nouns, role, constant))
        return tx.reset_index(drop=True), dims

    tx = pd.DataFrame({"value": df[measure] if measure else 1.0}, index=df.index)
    if date:
        tx["date"] = df[date]
    if time:
        tx["time"] = df[time]
    for name in candidates:
        tx[name] = df[name]
    return tx, [_Dim(name, nouns, role, True) for name, (nouns, role) in candidates.items()]


# --- Redacción ----------------------------------------------------------------------------


def _fmt(ctx: _Context, value: float) -> str:
    if ctx.money:
        # Sin símbolo si el archivo no dice la moneda: mejor que suponer dólares.
        return f"{ctx.currency}{value:,.0f}" if abs(value) >= 100 else f"{ctx.currency}{value:,.2f}"
    if ctx.measure is None or float(value).is_integer():
        return f"{value:,.0f}"
    return f"{value:,.1f}"


def _amount(ctx: _Context, value: float) -> str:
    """'$12,000 en ventas' · '120 tickets' · '1,200 de 'importe''."""
    if ctx.money:
        return f"{_fmt(ctx, value)} en {ctx.measure_noun}"
    if ctx.measure:
        return f"{_fmt(ctx, value)} de {ctx.measure_noun}"
    return f"{_fmt(ctx, value)} {ctx.unit[1]}"


def _subject(ctx: _Context) -> str:
    """Sujeto de la frase: 'tus ventas' · 'tus tickets' · ''importe''."""
    return f"tus {ctx.measure_noun}" if ctx.money or not ctx.measure else ctx.measure_noun


def _of_total(ctx: _Context) -> str:
    if ctx.money or not ctx.measure:
        return f"de {_subject(ctx)}"
    return f"del total de {ctx.measure_noun}"


def _label(value) -> str:
    """Nombre de una categoría; IDs leídos como float (12346.0) se muestran enteros."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _pct(x: float) -> str:
    return f"{abs(x) * 100:.0f}%"


def _day(d: pd.Timestamp) -> str:
    return f"{WEEKDAYS[d.dayofweek]} {d.day} de {MONTHS[d.month - 1]}"


def _period_label(start: pd.Timestamp, freq: str) -> str:
    if freq == "M":
        return f"{MONTHS[start.month - 1]} de {start.year}"
    end = start + pd.Timedelta(days=6)
    if start.month == end.month:
        return f"la semana del {start.day} al {end.day} de {MONTHS[end.month - 1]}"
    return (f"la semana del {start.day} de {MONTHS[start.month - 1]} al {end.day} de "
            f"{MONTHS[end.month - 1]}")


# --- Estadística --------------------------------------------------------------------------


def _t_critical(df: int, table: list[float]) -> float:
    if df < 1:
        return math.inf
    if df <= len(table):
        return table[df - 1]
    return 1.96 if table is _T_95 else 2.576


def _permutation_p(values: np.ndarray, codes: np.ndarray, statistic, observed: float) -> float:
    """Proporción de reordenamientos aleatorios de las etiquetas con un estadístico al menos
    tan extremo como el observado. Determinista (semilla fija)."""
    rng = np.random.default_rng(0)
    if len(values) > MAX_PERMUTATION_ROWS:
        idx = rng.choice(len(values), MAX_PERMUTATION_ROWS, replace=False)
        values, codes = values[idx], codes[idx]
    hits = sum(
        statistic(values, rng.permutation(codes)) >= observed - 1e-12
        for _ in range(N_PERMUTATIONS)
    )
    return (hits + 1) / (N_PERMUTATIONS + 1)


def _group_means(values: np.ndarray, codes: np.ndarray) -> np.ndarray:
    return np.bincount(codes, weights=values) / np.bincount(codes)


def _max_min_ratio(values: np.ndarray, codes: np.ndarray) -> float:
    means = _group_means(values, codes)
    return means.max() / means.min() if means.min() > 0 else math.inf


def _group_vs_rest_t(values: np.ndarray, codes: np.ndarray, eligible: np.ndarray) -> np.ndarray:
    """t de Welch de cada grupo contra el resto, vectorizado (NaN si el grupo no califica)."""
    n = np.bincount(codes, minlength=len(eligible)).astype(float)
    s = np.bincount(codes, weights=values, minlength=len(eligible))
    ss = np.bincount(codes, weights=values**2, minlength=len(eligible))
    n_r, s_r, ss_r = n.sum() - n, s.sum() - s, ss.sum() - ss
    with np.errstate(divide="ignore", invalid="ignore"):
        m, m_r = s / n, s_r / n_r
        v = (ss - n * m**2) / (n - 1)
        v_r = (ss_r - n_r * m_r**2) / (n_r - 1)
        t = (m - m_r) / np.sqrt(v / n + v_r / n_r)
    return np.where(eligible, t, np.nan)


def _sales(ctx: _Context) -> pd.DataFrame:
    """Transacciones que son ventas: sin devoluciones/cancelaciones (total negativo) ni
    movimientos en cero. Las series diarias sí usan el neto (ventas menos devoluciones)."""
    return ctx.tx[ctx.tx["value"] > 0] if ctx.measure else ctx.tx


# --- Series de tiempo ---------------------------------------------------------------------


def _daily(ctx: _Context) -> pd.Series | None:
    """Total por día del calendario; los días sin registros valen 0."""
    if "date" not in ctx.tx:
        return None
    tx = ctx.tx.dropna(subset=["date"])
    if tx.empty:
        return None
    days = tx["date"].dt.normalize()
    daily = tx.groupby(days)["value"].sum()
    return daily.reindex(pd.date_range(days.min(), days.max(), freq="D"), fill_value=0)


def _complete_periods(daily: pd.Series, freq: str) -> pd.Series:
    """Totales por semana/mes, solo de periodos que los datos cubren enteros."""
    periods = daily.index.to_period(freq)
    totals = daily.groupby(periods).sum()
    first, last = daily.index.min(), daily.index.max()
    keep = [p for p in totals.index if p.start_time >= first and p.end_time.normalize() <= last]
    return totals.loc[keep]


def _granularity(daily: pd.Series) -> str | None:
    if len(daily) >= 180:
        return "M"
    if len(daily) >= 35:
        return "W"
    return None


def _recent_change(ctx: _Context, daily: pd.Series) -> Insight | None:
    if not (freq := _granularity(daily)):
        return None
    periods = _complete_periods(daily, freq)
    if len(periods) < MIN_BASELINE_PERIODS + 1:
        return None
    last = periods.iloc[-1]
    baseline = periods.iloc[-1 - MAX_BASELINE_PERIODS:-1]
    n, mean, std = len(baseline), baseline.mean(), baseline.std(ddof=1)
    if mean <= 0:
        return None
    change = last / mean - 1
    # ¿Cae el último periodo fuera del intervalo de predicción al 99%?
    t = (last - mean) / (std * math.sqrt(1 + 1 / n)) if std > 0 else math.inf
    if abs(change) < MIN_CHANGE or abs(t) < _t_critical(n - 1, _T_99):
        return None
    unit = "semanas" if freq == "W" else "meses"
    return Insight(
        kind="recent_change",
        title="Cambio reciente" if change > 0 else "Caída reciente",
        text=f"En {_period_label(periods.index[-1].start_time, freq)} registraste "
             f"{_amount(ctx, last)}: {_pct(change)} {'más' if change > 0 else 'menos'} que el "
             f"promedio de los {n} {unit} anteriores ({_fmt(ctx, mean)}).",
        tone=Tone.POSITIVE if change > 0 else Tone.NEGATIVE,
        basis=f"Último periodo completo vs. los {n} anteriores; queda fuera de su rango de "
              "variación normal (intervalo de predicción al 99%).",
        score=0.85 + min(abs(change), 1) * 0.1,
    )


def _trend(ctx: _Context, daily: pd.Series) -> Insight | None:
    if not (freq := _granularity(daily)):
        return None
    periods = _complete_periods(daily, freq).iloc[-12:]
    n = len(periods)
    if n < MIN_TREND_PERIODS or periods.mean() <= 0:
        return None
    y = periods.to_numpy(dtype=float)
    r = np.corrcoef(np.arange(n), y)[0, 1]
    if not np.isfinite(r) or abs(r) >= 1:
        return None
    t = r * math.sqrt((n - 2) / (1 - r**2))
    slope = np.polyfit(np.arange(n), y, 1)[0]
    rel = slope / periods.mean()
    if abs(t) < _t_critical(n - 2, _T_99) or abs(rel) < MIN_TREND_SLOPE:
        return None
    unit = ("semana", "semanas") if freq == "W" else ("mes", "meses")
    up = slope > 0
    return Insight(
        kind="trend",
        title="Tendencia al alza" if up else "Tendencia a la baja",
        text=f"En las últimas {n} {unit[1]} completas, {_subject(ctx)} "
             f"{'crecen' if up else 'bajan'} en promedio {_pct(rel)} por {unit[0]} de forma "
             "sostenida.",
        tone=Tone.POSITIVE if up else Tone.NEGATIVE,
        basis=f"Regresión lineal sobre {n} {unit[1]} completas (R² = {r**2:.2f}; pendiente "
              "significativa al 99%).",
        score=0.8,
    )


def _anomalous_days(daily: pd.Series) -> pd.Series:
    """z robusto de los días excepcionalmente altos (vacío si no hay o faltan datos).
    En escala logarítmica: con pocas ventas diarias el ruido crece con el nivel, y un día
    2x "normal" no es raro. El log estabiliza esa variación."""
    open_days = daily[daily > 0]
    if len(open_days) < MIN_ANOMALY_DAYS:
        return pd.Series(dtype=float)
    logs = np.log(open_days)
    median, mad = logs.median(), (logs - logs.median()).abs().median()
    if mad == 0:
        return pd.Series(dtype=float)
    robust_z = 0.6745 * (logs - median) / mad
    extreme = (robust_z >= ANOMALY_LOG_Z) & (open_days >= ANOMALY_RATIO * open_days.median())
    return robust_z[extreme]


def _anomaly(ctx: _Context, daily: pd.Series) -> Insight | None:
    flagged = _anomalous_days(daily)
    if flagged.empty:
        return None
    open_days = daily[daily > 0]
    typical = open_days.median()
    candidates = daily[flagged.index]
    day, value = candidates.idxmax(), candidates.max()
    robust_z = flagged
    return Insight(
        kind="anomaly",
        title="Día fuera de lo común",
        text=f"El {_day(day)} registraste {_amount(ctx, value)}, {value / typical:.1f} veces "
             f"un día típico ({_fmt(ctx, typical)}). Revisa si hubo un evento especial o un "
             "error de captura.",
        basis=f"Comparado con la mediana de {len(open_days)} días con actividad (z robusto "
              f"{robust_z[day]:.1f}).",
        score=0.9,
    )


def _weekday(ctx: _Context, daily: pd.Series) -> Insight | None:
    # Un evento único (p. ej. el Día de las Madres) no es un patrón semanal: se excluye.
    excluded = _anomalous_days(daily).index
    daily = daily.drop(excluded)
    weekday = daily.index.dayofweek.to_numpy()
    counts = np.bincount(weekday, minlength=7)
    if counts.min() < MIN_WEEKDAY_WEEKS:
        return None
    means = pd.Series(_group_means(daily.to_numpy(dtype=float), weekday))
    # Días cerrados (se reportan aparte) o casi cerrados (un sábado con 3 citas) no sirven
    # de base: inflarían la ventaja del mejor día.
    typical = means[means > 0].median() if (means > 0).any() else 0
    open_days = [d for d in range(7) if means[d] > LOW_ACTIVITY_SHARE * typical]
    if len(open_days) < 2:
        return None
    mask = np.isin(weekday, open_days)
    values = daily.to_numpy(dtype=float)[mask]
    codes = pd.Series(weekday[mask]).map({d: i for i, d in enumerate(open_days)}).to_numpy()
    ratio = _max_min_ratio(values, codes)
    if ratio < MIN_WEEKDAY_RATIO:
        return None
    p = _permutation_p(values, codes, _max_min_ratio, ratio)
    if p > ALPHA:
        return None
    # El efecto se reporta contra el promedio del resto de los días, no contra el peor:
    # elegir el mínimo exagera la diferencia (el peor día siempre sale bajo por azar).
    best = int(means[open_days].idxmax())
    others = [d for d in open_days if d != best]
    rest_mean = daily[np.isin(daily.index.dayofweek, others)].mean()
    lift = means[best] / rest_mean
    if lift < MIN_WEEKDAY_RATIO:
        return None
    return Insight(
        kind="weekday",
        title="Tu mejor día",
        text=f"Los {WEEKDAYS_PLURAL[best]} son tu día más fuerte: "
             f"{_amount(ctx, means[best])} en promedio, {lift:.1f} veces el promedio del resto "
             f"de los días ({_fmt(ctx, rest_mean)}).",
        basis=f"Promedio por día en {len(daily)} días ({counts.min()}+ de cada día de la "
              f"semana){_excluded_note(excluded)}; prueba de permutación, p = {p:.3f}.",
        score=0.7,
    )


def _excluded_note(days: pd.Index) -> str:
    if days.empty:
        return ""
    names = ", ".join(f"{d.day} de {MONTHS[d.month - 1]}" for d in days)
    return f", sin contar {'el día atípico' if len(days) == 1 else 'los días atípicos'} {names}"


def _closed_weekdays(ctx: _Context, daily: pd.Series) -> Insight | None:
    weekday = daily.index.dayofweek
    counts = np.bincount(weekday, minlength=7)
    if counts.min() < MIN_WEEKDAY_WEEKS:
        return None
    closed = [d for d in range(7) if (daily[weekday == d] == 0).all()]
    if not closed or len(closed) > 2:
        return None
    names = " ni en ningún ".join(WEEKDAYS[d] for d in closed)
    return Insight(
        kind="closed_days",
        title="Días sin actividad",
        text=f"No hay {ctx.unit[1]} en ningún {names} del periodo. Si no es tu día de "
             "descanso, podría faltar información en el archivo.",
        basis=f"{counts.min()}+ semanas de datos.",
        score=0.5,
    )


def _peak_hours(ctx: _Context) -> Insight | None:
    if "time" not in ctx.tx:
        return None
    hours = _sales(ctx)["time"].dropna().dt.hour
    if len(hours) < MIN_PEAK_TX:
        return None
    span = range(int(hours.min()), int(hours.max()) + 1)
    counts = hours.value_counts().reindex(span, fill_value=0).to_numpy()
    if len(counts) < 4:
        return None
    windows = counts[:-1] + counts[1:]
    start = int(windows.argmax())
    share = windows[start] / counts.sum()
    if share < PEAK_FACTOR * 2 / len(counts):
        return None
    # Hipótesis nula: la actividad se reparte al azar entre las horas de operación.
    rng = np.random.default_rng(0)
    sims = rng.multinomial(counts.sum(), np.full(len(counts), 1 / len(counts)), N_PERMUTATIONS)
    sim_max = (sims[:, :-1] + sims[:, 1:]).max(axis=1)
    p = ((sim_max >= windows[start]).sum() + 1) / (N_PERMUTATIONS + 1)
    if p > ALPHA:
        return None
    first = span[0] + start
    return Insight(
        kind="peak_hours",
        title="Hora pico",
        text=f"De {first:02d}:00 a {first + 2:02d}:00 se concentra el {_pct(share)} de tus "
             f"{ctx.unit[1]}.",
        basis=f"{len(hours):,} {ctx.unit[1]} entre las {span[0]:02d}:00 y las "
              f"{span[-1] + 1:02d}:00.",
        score=0.65,
    )


# --- Categorías ---------------------------------------------------------------------------


def _concentration(ctx: _Context, dim: _Dim) -> Insight | None:
    values = ctx.df[ctx.measure] if ctx.measure else pd.Series(1.0, index=ctx.df.index)
    totals = values.groupby(ctx.df[dim.column]).sum().sort_values(ascending=False)
    totals = totals[totals > 0]
    n = len(totals)
    # Para entidades (productos, clientes, médicos) basta con 5; para una columna cualquiera
    # con pocos valores (una escala 0-4) "el 0 concentra el 98%" es una distribución, no
    # una concentración interesante.
    if n < (MIN_CATEGORIES if dim.role else MIN_GENERIC_CATEGORIES):
        return None
    top_n = math.ceil(0.2 * n)
    share = totals.iloc[:top_n].sum() / totals.sum()
    if share < CONCENTRATION_SHARE:
        return None
    names = ", ".join(_label(v) for v in totals.index[:min(top_n, 3)])
    if top_n == 1:
        text = (f"{names} genera por sí solo el {_pct(share)} {_of_total(ctx)} "
                f"(entre {n} {dim.nouns[1]}).")
    else:
        extra = "…" if top_n > 3 else ""
        text = (f"{top_n} de tus {n} {dim.nouns[1]} ({names}{extra}) generan el "
                f"{_pct(share)} {_of_total(ctx)}.")
    return Insight(
        kind="concentration",
        title=f"Concentración por {dim.nouns[0]}",
        text=text,
        basis=f"{n} {dim.nouns[1]} con actividad.",
        score=0.75 + (share - CONCENTRATION_SHARE) * 0.2,
    )


def _best_segment(ctx: _Context) -> Insight | None:
    """El segmento (mesero, canal, sucursal…) cuyo valor por transacción se aleja más del
    resto. Solo con métrica monetaria o numérica; los conteos ya los muestran los gráficos."""
    if not ctx.measure:
        return None
    dims = [d for d in ctx.dims if d.constant and d.column in ctx.tx
            and (d.role in SEGMENT_ROLES or d.role is None)]
    best = None
    for dim in dims:
        data = _sales(ctx)[[dim.column, "value"]].dropna()
        codes, labels = pd.factorize(data[dim.column])
        if not 2 <= len(labels) <= 10:
            continue
        values = data["value"].to_numpy(dtype=float)
        sizes = np.bincount(codes)
        eligible = (sizes >= MIN_SEGMENT_N) & (len(values) - sizes >= MIN_SEGMENT_N)
        if not eligible.any():
            continue
        t = _group_vs_rest_t(values, codes, eligible)
        g = int(np.nanargmax(np.abs(t)))
        in_group = codes == g
        rest_mean = values[~in_group].mean()
        if rest_mean <= 0:
            continue
        lift = values[in_group].mean() / rest_mean - 1
        if abs(lift) < MIN_SEGMENT_LIFT:
            continue

        def max_abs_t(v, c, eligible=eligible):
            return np.nanmax(np.abs(_group_vs_rest_t(v, c, eligible)))

        # Corrección de Bonferroni por el número de dimensiones evaluadas.
        p = _permutation_p(values, codes, max_abs_t, abs(t[g]))
        if p <= ALPHA / len(dims) and (best is None or p < best[0]):
            best = (p, dim, labels[g], lift, values[in_group], values[~in_group])
    if best is None:
        return None
    p, dim, name, lift, group, rest = best
    per = f"{ctx.unit[0]} promedio" if ctx.money else f"promedio de {ctx.measure_noun}"
    return Insight(
        kind="segment",
        title=f"Diferencia por {dim.nouns[0]}",
        text=f"Con {dim.nouns[0]} {_label(name)}, el {per} es {_fmt(ctx, group.mean())}: {_pct(lift)} "
             f"{'más' if lift > 0 else 'menos'} que con el resto ({_fmt(ctx, rest.mean())}).",
        tone=Tone.POSITIVE if lift > 0 else Tone.NEGATIVE,
        basis=f"{len(group):,} vs. {len(rest):,} {ctx.unit[1]}; prueba de permutación, "
              f"p = {p:.3f}.",
        score=0.6,
    )


def _rate_segment(ctx: _Context) -> Insight | None:
    """¿Qué grupo tiene una tasa de inasistencia (o asistencia) distinta al resto? Prueba de
    dos proporciones con corrección de Bonferroni por todas las comparaciones hechas."""
    if not ctx.flag:
        return None
    flags = as_flags(ctx.df[ctx.flag])
    tests = []
    for column, is_bool in ctx.rate_dims:
        keys = as_flags(ctx.df[column]).map({1.0: "Sí", 0.0: "No"}) if is_bool else ctx.df[column]
        data = pd.DataFrame({"g": keys, "y": flags}).dropna()
        stats = data.groupby("g")["y"].agg(["sum", "count"])
        total_n, total_s = stats["count"].sum(), stats["sum"].sum()
        if not 2 <= len(stats) <= 10 or total_n == 0:
            continue
        p = total_s / total_n
        for group, (s_g, n_g) in stats.iterrows():
            if is_bool and group != "Sí":
                continue  # "No" es el espejo de "Sí"
            n_r, s_r = total_n - n_g, total_s - s_g
            if n_g < MIN_RATE_GROUP or n_r < MIN_RATE_GROUP or not 0 < p < 1:
                continue
            p_g, p_r = s_g / n_g, s_r / n_r
            z = (p_g - p_r) / math.sqrt(p * (1 - p) * (1 / n_g + 1 / n_r))
            tests.append((column, is_bool, group, p_g, p_r, int(n_g), int(n_r), z))
    if not tests:
        return None
    z_crit = NormalDist().inv_cdf(1 - ALPHA / (2 * len(tests)))
    valid = [t for t in tests if abs(t[7]) >= z_crit and abs(t[3] - t[4]) >= MIN_RATE_DIFF
             and t[4] > 0 and abs(t[3] / t[4] - 1) >= MIN_RATE_LIFT]
    if not valid:
        return None
    column, is_bool, group, p_g, p_r, n_g, n_r, _ = max(valid, key=lambda t: abs(t[3] - t[4]))
    noun = "inasistencia" if ctx.flag_role == "no_show" else "asistencia"
    more = p_g > p_r
    bad = more == (ctx.flag_role == "no_show")
    who = f"con {column} = Sí" if is_bool else f"con {column} = {_label(group)}"
    return Insight(
        kind="rate_segment",
        title=f"Diferencia en {noun}",
        text=f"Las {ctx.unit[1]} {who} tienen {'más' if more else 'menos'} {noun}: "
             f"{p_g * 100:.1f}% vs {p_r * 100:.1f}% en el resto.",
        tone=Tone.NEGATIVE if bad else Tone.POSITIVE,
        basis=f"{n_g:,} vs {n_r:,} {ctx.unit[1]}; prueba de proporciones corregida por "
              f"{len(tests)} comparaciones. Es una asociación, no necesariamente la causa.",
        score=0.82,
    )


def _dedupe(insights: list[Insight]) -> list[Insight]:
    """Un solo hallazgo por tipo, salvo concentración (una por dimensión)."""
    seen, out = set(), []
    for i in insights:
        key = i.kind if i.kind != "concentration" else i.title
        if key not in seen:
            seen.add(key)
            out.append(i)
    return out
