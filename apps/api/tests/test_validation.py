"""Gráficos armados por el usuario: se permite todo lo posible, se bloquea lo imposible y
se advierte lo engañoso."""

import pytest

from app import samples
from app.profiling import profile_dataframe
from app.recommender import Aggregation, ChartSpec, ChartType, XTransform, recommend
from app.recommender.validation import validate_spec
from tests.conftest import register
from tests.test_api import upload


@pytest.fixture(scope="module")
def pos():
    profile, _ = profile_dataframe(samples.restaurante_pos().iloc[:-1])
    return profile


def spec(**kw):
    return ChartSpec(title="t", **kw)


@pytest.mark.parametrize("builder", [samples.ecommerce, samples.restaurante, samples.clinica,
                                     samples.restaurante_pos])
def test_every_recommendation_is_valid(builder):
    profile, _ = profile_dataframe(builder())
    for rec in (recommend(profile), recommend(profile, None)):
        for s in rec.charts:
            check = validate_spec(profile, s)
            assert check.ok, (s.title, check.errors)


@pytest.mark.parametrize("kw, message", [
    (dict(chart_type=ChartType.LINE, x="Mesero", aggregation=Aggregation.COUNT),
     "debe ser una fecha"),
    (dict(chart_type=ChartType.BAR, x="Mesero", y="Platillo", aggregation=Aggregation.SUM),
     "no es numérica"),
    (dict(chart_type=ChartType.PIE, x="Mesero", y="Importe", aggregation=Aggregation.MEAN),
     "partes de un total"),
    (dict(chart_type=ChartType.BAR, x="Fecha", aggregation=Aggregation.COUNT),
     "cómo agruparla"),
    (dict(chart_type=ChartType.BAR, x="Mesero", aggregation=Aggregation.COUNT,
          x_transform=XTransform.MONTH), "no es una fecha"),
    (dict(chart_type=ChartType.KPI, y="Mesero", aggregation=Aggregation.RATE), "sí/no"),
    (dict(chart_type=ChartType.SCATTER, x="Mesero", y="Importe"), "numéricas"),
    (dict(chart_type=ChartType.BAR, x="Mesero", y="no_existe", aggregation=Aggregation.SUM),
     "no existe"),
    (dict(chart_type=ChartType.BAR, x="Fecha", x_transform=XTransform.MONTH, per_day=True,
          aggregation=Aggregation.COUNT), "solo aplica a hora"),
])
def test_impossible_combinations_are_errors(pos, kw, message):
    check = validate_spec(pos, spec(**kw))
    assert not check.ok and message in " ".join(check.errors)


def test_misleading_combinations_are_warnings(pos):
    check = validate_spec(pos, spec(chart_type=ChartType.BAR, x="Mesero", y="Precio unitario",
                                    aggregation=Aggregation.SUM))
    assert check.ok and "no suele tener sentido" in check.warnings[0]


def test_user_can_build_valid_chart(pos):
    check = validate_spec(pos, spec(chart_type=ChartType.BAR, x="Fecha",
                                    x_transform=XTransform.WEEKDAY, y="Importe",
                                    aggregation=Aggregation.MEAN, group_by="No. Ticket"))
    assert check.ok and not check.warnings


def test_preview_endpoint(make_client):
    c = make_client()
    register(c)
    ds = upload(c, samples.ecommerce()).json()
    good = c.post(f"/datasets/{ds['id']}/chart-preview", json={
        "chart_type": "bar", "title": "Ventas por canal", "x": "canal", "y": "total_venta",
        "aggregation": "mean"})
    body = good.json()
    assert good.status_code == 200 and body["errors"] == [] and len(body["data"]["points"]) == 3

    bad = c.post(f"/datasets/{ds['id']}/chart-preview", json={
        "chart_type": "line", "title": "x", "x": "canal", "aggregation": "count"}).json()
    assert bad["data"] is None and "fecha" in bad["errors"][0]

    # guardar un dashboard con un gráfico imposible se rechaza con el motivo
    res = c.post("/dashboards", json={"dataset_id": ds["id"], "title": "d", "charts": [
        {"chart_type": "line", "title": "Mal", "x": "canal", "aggregation": "count"}]})
    assert res.status_code == 422 and "'Mal'" in res.json()["detail"]


def test_preview_is_isolated_between_organizations(make_client):
    ana, beto = make_client(), make_client()
    register(ana, "ana@a.com", "A")
    register(beto, "beto@b.com", "B")
    ds = upload(ana, samples.ecommerce()).json()
    res = beto.post(f"/datasets/{ds['id']}/chart-preview", json={
        "chart_type": "kpi", "title": "x", "aggregation": "count"})
    assert res.status_code == 404
