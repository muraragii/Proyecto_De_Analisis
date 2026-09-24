"""Hallazgos en texto: deben detectar efectos reales con la cifra correcta y NO inventar
patrones en datos aleatorios."""

import numpy as np
import pandas as pd
import pytest

from app.insights import generate_insights
from app.profiling import profile_dataframe

INFERENTIAL = {"weekday", "segment", "recent_change", "trend", "anomaly", "peak_hours"}


def pos(seed=0, weeks=12, per_day=20, weekday_factor=None, waiter_lift=None,
        hours=range(12, 23), daily_factor=None):
    """Tickets de restaurante sin ningún patrón salvo los que se "siembren".
    Empieza un lunes y cubre semanas completas."""
    rng = np.random.default_rng(seed)
    days = pd.date_range("2025-01-06", periods=weeks * 7, freq="D")
    rows, ticket = [], 0
    for day in days:
        factor = (weekday_factor or {}).get(day.dayofweek, 1.0)
        factor *= (daily_factor or {}).get(day, 1.0)
        for _ in range(rng.poisson(per_day * factor)):
            ticket += 1
            waiter = rng.choice(["Ana", "Luis", "Carla", "Jorge"])
            amount = rng.gamma(9, 300 / 9) * (waiter_lift if waiter == "Ana" and waiter_lift else 1)
            hour = int(rng.choice(list(hours)))
            rows.append({
                "ticket": ticket,
                "fecha": day + pd.Timedelta(hours=hour, minutes=int(rng.integers(0, 60))),
                "mesero": waiter,
                "platillo": rng.choice(["Tacos", "Mole", "Pozole", "Enchiladas", "Sopa",
                                        "Flan", "Agua", "Café"]),
                "total": round(amount, 2),
            })
    return pd.DataFrame(rows)


def insights_of(df):
    profile, coerced = profile_dataframe(df)
    return generate_insights(profile, coerced)


def by_kind(insights):
    return {i.kind: i for i in insights}


# --- Falsos positivos -----------------------------------------------------------------------


def test_random_data_produces_no_inferential_insights():
    """30 negocios sin ningún patrón: el motor no debe "descubrir" nada. Con nivel de
    significancia de 1% por prueba, esperamos a lo sumo un par de falsos positivos."""
    false_positives = []
    for seed in range(30):
        kinds = {i.kind for i in insights_of(pos(seed))} & INFERENTIAL
        if kinds:
            false_positives.append((seed, kinds))
    assert len(false_positives) <= 2, false_positives


def test_partial_last_week_is_not_a_drop():
    # 12 semanas completas + 2 días de la semana 13: esos 2 días no son una "caída".
    df = pos(seed=1, weeks=13)
    df = df[df["fecha"] < pd.Timestamp("2025-03-31") + pd.Timedelta(days=2)]
    assert "recent_change" not in by_kind(insights_of(df))


# --- Efectos reales ---------------------------------------------------------------------------


def test_detects_best_weekday():
    df = pos(seed=2, weekday_factor={5: 2.0})  # sábados con el doble de clientes
    insight = by_kind(insights_of(df))["weekday"]
    assert insight.text.startswith("Los sábados son tu día más fuerte")
    ratio = float(insight.text.split(" veces")[0].split(", ")[-1])
    assert 1.7 <= ratio <= 2.4


def test_detects_closed_day():
    df = pos(seed=3, weekday_factor={0: 0.0})  # cerrado los lunes
    kinds = by_kind(insights_of(df))
    assert "ningún lunes" in kinds["closed_days"].text
    assert "weekday" not in kinds or "lunes (" not in kinds["weekday"].text


def test_detects_recent_jump():
    last_week = pd.date_range("2025-03-24", periods=7, freq="D")  # semana 12
    df = pos(seed=4, daily_factor={d: 1.6 for d in last_week})
    insight = by_kind(insights_of(df))["recent_change"]
    assert insight.title == "Cambio reciente"
    assert "semana del 24 al 30 de marzo" in insight.text
    pct = int(insight.text.split("%")[0].split(": ")[-1])
    assert 40 <= pct <= 80


def test_detects_trend():
    days = pd.date_range("2025-01-06", periods=84, freq="D")
    growth = {d: 1.06 ** ((d - days[0]).days / 7) for d in days}  # +6% semanal
    df = pos(seed=5, daily_factor=growth, per_day=30)
    insight = by_kind(insights_of(df))["trend"]
    assert insight.title == "Tendencia al alza"
    pct = int(insight.text.split("promedio ")[1].split("%")[0])
    assert 4 <= pct <= 10


def test_detects_anomalous_day():
    special = pd.Timestamp("2025-02-14")
    df = pos(seed=6, daily_factor={special: 4.0})
    insight = by_kind(insights_of(df))["anomaly"]
    assert "viernes 14 de febrero" in insight.text


def test_detects_waiter_with_higher_ticket():
    df = pos(seed=7, waiter_lift=1.3)
    insight = by_kind(insights_of(df))["segment"]
    assert insight.text.startswith("Con mesero Ana, el ticket promedio es")
    pct = int(insight.text.split(": ")[1].split("%")[0])
    assert 20 <= pct <= 40


def test_detects_peak_hours():
    rng_hours = [13, 14, 14, 14, 15, 15, 19, 20, 21]
    df = pos(seed=8, hours=rng_hours)
    insight = by_kind(insights_of(df))["peak_hours"]
    assert insight.text.startswith("De 14:00 a 16:00")


def test_concentration_exact_numbers():
    df = pd.DataFrame({
        "producto": ["A"] * 6 + ["B", "C", "D", "E", "F", "G", "H", "I", "J"],
        "ventas": [100] * 6 + [10] * 9,
    })
    insight = by_kind(insights_of(df))["concentration"]
    # 2 de 10 productos (20%): A=600 y B=10 -> 610 de 690 = 88%. Sin industria detectada
    # (solo 2 columnas) la redacción es genérica.
    assert insight.text == "2 de tus 10 valores de 'producto' (A, B) generan el 88% del total de 'ventas'."


def test_line_items_are_analyzed_per_ticket():
    """Con una fila por platillo, la comparación de meseros usa el total de cada ticket."""
    base = pos(seed=9, waiter_lift=1.3)
    lines = base.loc[base.index.repeat(3)].copy()
    lines["total"] = lines["total"] / 3  # cada ticket partido en 3 líneas
    single = by_kind(insights_of(base))["segment"].text
    split = by_kind(insights_of(lines))["segment"].text
    assert single.split(": ")[0] == split.split(": ")[0]  # mismo ticket promedio


@pytest.mark.parametrize("builder", [lambda: pos(10), lambda: pos(11, weekday_factor={5: 2})])
def test_texts_are_clean(builder):
    for i in insights_of(builder()):
        assert "None" not in i.text and "nan" not in i.text.lower()
        assert i.basis


def test_one_off_event_does_not_inflate_weekday_pattern():
    """Un sábado excepcional (evento) no debe exagerar el patrón de los sábados."""
    event = pd.Timestamp("2025-03-08")  # sábado
    df = pos(seed=2, weekday_factor={5: 2.0}, daily_factor={event: 4.0})
    found = by_kind(insights_of(df))
    assert "sábado 8 de marzo" in found["anomaly"].text
    weekday = found["weekday"]
    ratio = float(weekday.text.split(" veces")[0].split(", ")[-1])
    assert 1.7 <= ratio <= 2.4  # el efecto real es 2x
    assert "sin contar el día atípico 8 de marzo" in weekday.basis
