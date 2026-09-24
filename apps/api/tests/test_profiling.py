import pandas as pd

from app import samples
from app.ingestion.parsers import read_table
from app.profiling import GeoRole, SemanticType, profile_dataframe


def types_of(df):
    profile, _ = profile_dataframe(df)
    return {c.name: c.semantic_type for c in profile.columns}


def test_ecommerce_column_types():
    types = types_of(samples.ecommerce())
    assert types["id_pedido"] == SemanticType.IDENTIFIER
    assert types["fecha_pedido"] == SemanticType.DATETIME
    assert types["producto"] == SemanticType.CATEGORICAL
    assert types["total_venta"] == SemanticType.NUMERIC
    assert types["cantidad"] == SemanticType.NUMERIC


def test_integer_codes_are_categorical():
    types = types_of(samples.restaurante())
    assert types["mesa"] == SemanticType.CATEGORICAL
    assert types["comensales"] == SemanticType.NUMERIC


def test_strings_with_dates_and_currency_are_coerced():
    profile, coerced = profile_dataframe(samples.restaurante())
    fecha = profile.column("fecha")
    assert fecha.semantic_type == SemanticType.DATETIME
    assert fecha.stats["has_time"] is True
    assert profile.column("total").semantic_type == SemanticType.NUMERIC
    assert pd.api.types.is_numeric_dtype(coerced["total"])
    # dd/mm/aaaa: 01/03/2025 debe ser 1 de marzo, no 3 de enero
    assert coerced["fecha"].min() >= pd.Timestamp("2025-03-01")


def test_number_formats():
    df = pd.DataFrame({
        "latino": ["1.234,50", "2.000,00", "15,5"],
        "anglo": ["1,234.50", "2,000.00", "15.5"],
    })
    _, coerced = profile_dataframe(df)
    assert coerced["latino"].tolist() == [1234.5, 2000.0, 15.5]
    assert coerced["anglo"].tolist() == [1234.5, 2000.0, 15.5]


def test_boolean_text_and_geo():
    df = pd.DataFrame({
        "activo": ["Sí", "No", "Sí", "No"],
        "comentario": ["Texto largo " * 5 + str(i) for i in range(4)],
        "latitud": [19.4, 20.6, 25.6, 19.0],
        "pais": ["México", "México", "Chile", "Perú"],
    })
    profile, _ = profile_dataframe(df)
    assert profile.column("activo").semantic_type == SemanticType.BOOLEAN
    assert profile.column("comentario").semantic_type == SemanticType.TEXT
    assert profile.column("latitud").geo_role == GeoRole.LATITUDE
    assert profile.column("pais").geo_role == GeoRole.REGION


def test_nulls_and_stats():
    df = pd.DataFrame({"monto": [10, None, 30, None]})
    col = profile_dataframe(df)[0].column("monto")
    assert col.null_ratio == 0.5
    assert col.stats["sum"] == 40
    assert col.stats["mean"] == 20


def test_read_csv_semicolon_latin1():
    content = "producto;precio\nCafé;35,5\nTé;20\n".encode("latin-1")
    df = read_table(content, "datos.csv")
    assert list(df.columns) == ["producto", "precio"]
    assert df["producto"].tolist() == ["Café", "Té"]
