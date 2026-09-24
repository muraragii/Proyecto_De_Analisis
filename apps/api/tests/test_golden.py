"""Tests de referencia: datasets pequeños y "sucios" como los reales, con las respuestas
correctas calculadas a mano. Si alguno falla, la app estaría mostrando una cifra errónea."""

import io

import pandas as pd
import pytest

from app import samples
from app.ingestion.parsers import read_table
from app.profiling import SemanticType, profile_dataframe
from app.recommender import Aggregation, ChartSpec, ChartType, XTransform, chart_data, recommend


def load(csv: str):
    df = read_table(csv.encode("utf-8"), "datos.csv")
    profile, coerced = profile_dataframe(df)
    return profile, coerced


def chart(profile, df, title):
    spec = next(c for c in recommend(profile).charts if c.title == title)
    return spec, chart_data(df, spec)


def warning_codes(profile):
    return {w.code for w in profile.warnings}


# Exportación típica de punto de venta: una fila por platillo, varias filas por ticket,
# y una fila "TOTAL" al final como la que agrega Excel.
POS = """ticket,fecha,platillo,cantidad,precio_unitario,total
T1,2025-03-03 13:10,Tacos,2,50,100
T1,2025-03-03 13:10,Refresco,1,30,30
T2,2025-03-03 14:20,Mole,1,150,150
T3,2025-03-04 14:05,Tacos,3,50,150
T3,2025-03-04 14:05,Agua,2,20,40
T4,2025-03-10 20:00,Pozole,1,120,120
TOTAL,,,,,590
"""


class TestLineItems:
    """Ticket T1=130, T2=150, T3=190, T4=120. Del lunes 3 al lunes 10 de marzo (8 días)."""

    @pytest.fixture
    def pos(self):
        return load(POS)

    def test_totals_row_is_removed(self, pos):
        profile, df = pos
        assert len(df) == 6
        assert df.attrs["summary_rows"] == ["TOTAL"]
        assert "summary_rows_removed" in warning_codes(profile)
        _, data = chart(profile, df, "Ventas totales")
        assert data["value"] == 590  # no 1180

    def test_detects_order_key_and_non_additive_price(self, pos):
        profile, _ = pos
        assert profile.column("ticket").semantic_type == SemanticType.IDENTIFIER
        assert profile.column("precio_unitario").additive is False
        assert profile.column("total").additive is True
        assert recommend(profile).industry == "restaurante"

    def test_average_ticket_is_per_ticket_not_per_line(self, pos):
        profile, df = pos
        _, data = chart(profile, df, "Ticket promedio")
        assert data["value"] == 147.5  # 590 / 4 tickets; por línea sería 98.33

    def test_ticket_count(self, pos):
        profile, df = pos
        _, data = chart(profile, df, "Tickets")
        assert data["value"] == 4  # no 6 filas

    def test_weekday_is_daily_average(self, pos):
        profile, df = pos
        _, data = chart(profile, df, "Venta promedio por día de la semana")
        by_day = {p["x"]: p["y"] for p in data["points"]}
        # 2 lunes (3 y 10): (130 + 150 + 120) / 2 = 200 · 1 martes: 190
        assert by_day["Lun"] == 200
        assert by_day["Mar"] == 190
        assert by_day["Mié"] == 0 and by_day["Dom"] == 0  # días sin ventas cuentan
        assert len(by_day) == 7

    def test_peak_hours_count_tickets_per_day(self, pos):
        profile, df = pos
        _, data = chart(profile, df, "Horarios pico")
        by_hour = {p["x"]: p["y"] for p in data["points"]}
        assert by_hour["14:00"] == pytest.approx(2 / 8, abs=0.01)  # T2 y T3, 8 días
        assert by_hour["13:00"] == pytest.approx(1 / 8, abs=0.01)  # T1 (2 líneas, 1 ticket)
        assert by_hour["17:00"] == 0  # horas intermedias sin tickets aparecen en 0

    def test_best_sellers_use_quantity(self, pos):
        profile, df = pos
        _, data = chart(profile, df, "Platillos más vendidos")
        assert data["points"][0] == {"x": "Tacos", "y": 5}  # 2 + 3 unidades

    def test_unit_price_is_never_summed(self, pos):
        profile, _ = pos
        for spec in recommend(profile, None).charts:
            if spec.y == "precio_unitario" and spec.aggregation is not None:
                assert spec.aggregation == Aggregation.MEAN, spec.title


def test_pos_export_end_to_end():
    """Archivo de ejemplo completo (Excel) contra un cálculo independiente con pandas."""
    raw = samples.restaurante_pos()
    buf = io.BytesIO()
    raw.to_excel(buf, index=False)
    df = read_table(buf.getvalue(), "pos.xlsx")
    profile, coerced = profile_dataframe(df)

    # Referencia calculada a mano, sin pasar por el motor.
    lines = raw[raw["Platillo"] != "TOTAL"].copy()
    lines["monto"] = pd.to_numeric(
        lines["Importe"].str.replace(r"[$,]", "", regex=True), errors="coerce"
    )
    expected_total = lines["monto"].sum()
    expected_ticket = lines.groupby("No. Ticket")["monto"].sum().mean()

    assert len(coerced) == len(lines)  # la fila TOTAL (con importe como texto) se quitó
    assert df.attrs["summary_rows"] == ["TOTAL"]
    assert {"summary_rows_removed", "unparsed_values"} <= warning_codes(profile)
    assert profile.column("Fecha").stats["date_order"] == "dmy"
    rec = recommend(profile)
    assert rec.industry == "restaurante"
    by_title = {c.title: chart_data(coerced, c) for c in rec.charts}
    assert by_title["Ventas totales"]["value"] == pytest.approx(expected_total, abs=0.01)
    assert by_title["Ticket promedio"]["value"] == pytest.approx(expected_ticket, abs=0.01)
    assert by_title["Tickets"]["value"] == raw["No. Ticket"].nunique()


class TestReturns:
    """Factura de venta + cancelación con prefijo "C" (formato de muchos sistemas)."""

    CSV = """Invoice,InvoiceDate,Description,Quantity,Price
1001,2025-01-06 10:00,Taza,2,50
1001,2025-01-06 10:00,Plato,1,100
1002,2025-01-06 11:00,Taza,4,50
1003,2025-01-07 12:00,Vaso,1,300
C1003,2025-01-07 15:00,Vaso,-1,300
1004,2025-01-08 09:00,Taza,0,0
""" + "\n".join(f"{2000 + i},2025-01-{9 + i % 20:02d} 10:00,Plato,1,100" for i in range(40))

    def test_cancellation_codes_are_kept(self):
        profile, df = load(self.CSV)
        assert profile.column("Invoice").semantic_type == SemanticType.IDENTIFIER
        assert "C1003" in set(df["Invoice"].astype(str))  # no se convierte en vacío

    def test_line_total_is_derived(self):
        profile, df = load(self.CSV)
        derived = profile.column("Importe (calculado)")
        assert derived.additive and derived.stats["derived_from"] == ["Quantity", "Price"]
        assert "derived_total" in warning_codes(profile)
        # 200 + 200 + 300 - 300 + 0 + 40 x 100 = 4,400 (neto)
        assert chart(profile, df, "Ventas totales")[1]["value"] == 4400

    def test_average_ticket_counts_only_sales(self):
        profile, df = load(self.CSV)
        # ventas: 1001=200, 1002=200, 1003=300 y 40 de 100 -> 4,700 / 43 = 109.30
        _, avg = chart(profile, df, "Ticket promedio")
        assert avg["value"] == pytest.approx(4700 / 43, abs=0.01)
        assert any("Sin contar 2" in n for n in avg["notes"])  # C1003 y 1004 (en cero)
        _, orders = chart(profile, df, "Pedidos")
        assert orders["value"] == 43


class TestMessyValues:
    def test_currency_na_and_percent(self):
        csv = "id,fecha,monto,descuento\n" + "\n".join(
            [f"{i},2025-01-{i:02d},\"$1,{i:03d}.50\",10%" for i in range(1, 21)]
            + ["21,2025-01-21,N/A,5%", "22,2025-01-22,pendiente,0%"]
        )
        profile, df = load(csv)
        monto = profile.column("monto")
        assert monto.semantic_type == SemanticType.NUMERIC
        assert df["monto"].iloc[0] == 1001.5
        # "N/A" es un vacío estándar; "pendiente" es texto que no se pudo convertir.
        unparsed = next(w for w in profile.warnings if w.code == "unparsed_values")
        assert "1 valor de 'monto'" in unparsed.message and "'pendiente'" in unparsed.message
        assert df["monto"].isna().sum() == 2
        assert profile.column("descuento").additive is False  # es un %

    def test_outliers_negatives_and_duplicates(self):
        rows = [f"{i},{100 + i}" for i in range(1, 40)]
        rows += ["40,100000", "41,-50", "41,-50"]  # error de captura, devolución duplicada
        profile, _ = load("id_venta,importe\n" + "\n".join(rows))
        codes = warning_codes(profile)
        assert {"outliers", "negative_values", "duplicate_rows"} <= codes
        outlier = next(w for w in profile.warnings if w.code == "outliers")
        assert "100,000" in outlier.message

    def test_long_tail_is_not_flagged_as_outliers(self):
        # Ventas con cola larga (pocos pedidos grandes) son normales, no errores.
        values = [10] * 50 + [50] * 20 + [200] * 10 + [900, 1200, 1500, 2000, 2500]
        csv = "total\n" + "\n".join(map(str, values))
        profile, _ = load(csv)
        assert "outliers" not in warning_codes(profile)


class TestDates:
    @pytest.mark.parametrize(
        "dates, order, first",
        [
            (["25/04/2025", "03/05/2025"], "dmy", "2025-04-25"),  # 25 solo puede ser día
            (["04/25/2025", "05/03/2025"], "mdy", "2025-04-25"),  # formato EE.UU.
            (["03/04/2025", "05/06/2025"], "dmy?", "2025-04-03"),  # ambiguo -> latino
        ],
    )
    def test_day_month_order_from_data(self, dates, order, first):
        profile, df = load("fecha,venta\n" + "\n".join(f"{d},10" for d in dates))
        assert profile.column("fecha").stats["date_order"] == order
        assert df["fecha"].min().date().isoformat() == first
        assert ("ambiguous_date_order" in warning_codes(profile)) == (order == "dmy?")


class TestTimeSeries:
    @pytest.fixture
    def january(self):
        # Mié 1 a vie 31 de enero de 2025, sin datos del 13 al 19 (una semana completa).
        days = [d for d in pd.date_range("2025-01-01", "2025-01-31")
                if not pd.Timestamp("2025-01-13") <= d <= pd.Timestamp("2025-01-19")]
        df = pd.DataFrame({"fecha": days, "venta": 10.0})
        return df

    def weekly(self, df, agg=Aggregation.SUM):
        spec = ChartSpec(chart_type=ChartType.LINE, title="t", x="fecha", y="venta",
                         aggregation=agg, x_transform=XTransform.WEEK)
        return chart_data(df, spec)

    def test_gaps_are_zero_not_skipped(self, january):
        points = {p["x"]: p for p in self.weekly(january)["points"]}
        assert points["2025-01-13"]["y"] == 0
        assert list(points) == ["2024-12-30", "2025-01-06", "2025-01-13", "2025-01-20",
                                "2025-01-27"]
        assert any("1 semana(s) sin registros" in n for n in self.weekly(january)["notes"])

    def test_partial_first_and_last_week(self, january):
        data = self.weekly(january)
        points = data["points"]
        assert points[0]["x"] == "2024-12-30" and points[0].get("partial")
        assert points[0]["y"] == 50  # mié-dom: 5 días, se ve bajo pero es real
        assert points[-1].get("partial")  # semana del 27 termina el 2 de feb
        assert not points[1].get("partial")
        assert any("incompleto" in n for n in data["notes"])

    def test_mean_gaps_stay_empty(self, january):
        points = {p["x"]: p["y"] for p in self.weekly(january, Aggregation.MEAN)["points"]}
        assert points["2025-01-13"] is None  # sin datos no es "promedio 0"

    def test_complete_month_is_not_partial(self):
        df = pd.DataFrame({"fecha": pd.date_range("2025-01-01", "2025-03-15"), "venta": 1.0})
        spec = ChartSpec(chart_type=ChartType.LINE, title="t", x="fecha", y="venta",
                         aggregation=Aggregation.SUM, x_transform=XTransform.MONTH)
        points = chart_data(df, spec)["points"]
        assert [p["x"] for p in points] == ["2025-01", "2025-02", "2025-03"]
        assert [bool(p.get("partial")) for p in points] == [False, False, True]
        assert [p["y"] for p in points] == [31, 28, 15]


def test_top_n_says_how_many_were_left_out():
    df = pd.DataFrame({"producto": [f"P{i}" for i in range(30)], "venta": range(30)})
    spec = ChartSpec(chart_type=ChartType.BAR, title="t", x="producto", y="venta",
                     aggregation=Aggregation.SUM, limit=10)
    data = chart_data(df, spec)
    assert len(data["points"]) == 10 and data["points"][0]["x"] == "P29"
    assert "Top 10 de 30" in data["notes"][0]


def test_pie_rejects_negative_totals():
    df = pd.DataFrame({"canal": ["a", "b"], "neto": [100, -20]})
    spec = ChartSpec(chart_type=ChartType.PIE, title="t", x="canal", y="neto",
                     aggregation=Aggregation.SUM)
    with pytest.raises(ValueError):
        chart_data(df, spec)


def test_excel_sheets_with_same_columns_are_combined():
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as writer:
        pd.DataFrame({"fecha": ["2024-01-01"], "ventas": [10]}).to_excel(writer, sheet_name="2024", index=False)
        pd.DataFrame({"fecha": ["2025-01-01"], "ventas": [20]}).to_excel(writer, sheet_name="2025", index=False)
        pd.DataFrame({"otra": [1]}).to_excel(writer, sheet_name="Notas", index=False)
    df = read_table(buf.getvalue(), "ventas.xlsx")
    # La hoja "Notas" tiene otras columnas: no se mezcla y se avisa.
    assert len(df) == 1 and df.attrs["sheets_ignored"] == ["2025", "Notas"]

    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as writer:
        pd.DataFrame({"fecha": ["2024-01-01"], "ventas": [10]}).to_excel(writer, sheet_name="2024", index=False)
        pd.DataFrame({"fecha": ["2025-01-01"], "ventas": [20]}).to_excel(writer, sheet_name="2025", index=False)
    df = read_table(buf.getvalue(), "ventas.xlsx")
    assert df["ventas"].sum() == 30 and df.attrs["sheets_combined"] == ["2024", "2025"]
    profile, _ = profile_dataframe(df)
    assert "sheets_combined" in warning_codes(profile)


def test_repeated_numeric_id_is_never_summed():
    csv = "Customer ID,Quantity\n" + "\n".join(f"{12000 + i % 30},{i % 5 + 1}" for i in range(200))
    profile, _ = load(csv)
    # Con pocos valores es una categoría (sirve para agrupar); con muchos, un identificador.
    # En ningún caso es una métrica que se sume.
    assert profile.column("Customer ID").semantic_type in (SemanticType.CATEGORICAL,
                                                            SemanticType.IDENTIFIER)
    assert all(c.y != "Customer ID" for c in recommend(profile).charts if c.aggregation)


def test_excel_totals_row():
    df = pd.DataFrame({"producto": ["A", "B", "Total general"], "ventas": [10, 20, 30]})
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    loaded = read_table(buf.getvalue(), "ventas.xlsx")
    assert loaded["ventas"].sum() == 30
    assert loaded.attrs["summary_rows"] == ["Total general"]
