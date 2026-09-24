import numpy as np
import pandas as pd
import pytest

from app import samples
from app.profiling import profile_dataframe
from app.recommender import ChartType, XTransform, chart_data, detect_industry, recommend


def profiled(df):
    return profile_dataframe(df)


@pytest.mark.parametrize(
    "builder, expected",
    [(samples.ecommerce, "ecommerce"), (samples.restaurante, "restaurante"),
     (samples.clinica, "clinica")],
)
def test_detects_industry(builder, expected):
    profile, _ = profiled(builder())
    assert detect_industry(profile)[0] == expected


def test_generic_dataset_has_no_industry():
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"a": rng.normal(10, 2, 50), "b": rng.normal(5, 1, 50)})
    profile, _ = profiled(df)
    rec = recommend(profile)
    assert rec.industry is None
    assert ChartType.SCATTER in {c.chart_type for c in rec.charts}


def test_ecommerce_recommendations_use_business_templates():
    profile, _ = profiled(samples.ecommerce())
    rec = recommend(profile, "ecommerce")
    titles = [c.title for c in rec.charts]
    assert titles[0] == "Ventas en el tiempo"
    top = next(c for c in rec.charts if c.title == "Top productos por ventas")
    assert (top.x, top.y, top.chart_type) == ("producto", "total_venta", ChartType.BAR)
    # la categoría no debe confundirse con el producto
    cat = next(c for c in rec.charts if c.title == "Ventas por categoría")
    assert cat.x == "categoría"


def test_restaurant_peak_hours():
    profile, df = profiled(samples.restaurante())
    rec = recommend(profile, "restaurante")
    peak = next(c for c in rec.charts if c.title == "Horarios pico")
    assert peak.x_transform == XTransform.HOUR
    hours = [p["x"] for p in chart_data(df, peak)["points"]]
    assert hours == sorted(hours) and "20:00" in hours


def test_no_duplicate_charts_and_type_caps():
    profile, _ = profiled(samples.clinica())
    charts = recommend(profile).charts
    keys = [c.key() for c in charts]
    assert len(keys) == len(set(keys))
    assert sum(c.chart_type == ChartType.KPI for c in charts) <= 4
    assert len(charts) <= 12


def test_forcing_generic_only():
    profile, _ = profiled(samples.ecommerce())
    rec = recommend(profile, None)
    assert rec.industry is None and rec.detected_industry == "ecommerce"
    assert all(c.source == "rules" for c in rec.charts)


def test_unknown_industry():
    profile, _ = profiled(samples.ecommerce())
    with pytest.raises(ValueError):
        recommend(profile, "aerolinea")


def test_every_recommended_chart_produces_data():
    for builder in (samples.ecommerce, samples.restaurante, samples.clinica):
        profile, df = profiled(builder())
        for spec in recommend(profile).charts:
            data = chart_data(df, spec)
            assert data, spec.title
            if "points" in data:
                assert len(data["points"]) > 0, spec.title


def test_pie_groups_small_slices():
    df = pd.DataFrame({"cat": list("abcdefghij") * 3, "v": range(30)})
    profile, coerced = profiled(df)
    from app.recommender import Aggregation, ChartSpec

    spec = ChartSpec(chart_type=ChartType.PIE, title="t", x="cat", y="v",
                     aggregation=Aggregation.SUM)
    labels = [p["x"] for p in chart_data(coerced, spec)["points"]]
    assert len(labels) == 6 and labels[-1] == "Otros"
