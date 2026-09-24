import io

from app import samples
from tests.conftest import register


def upload(client, df, name="ventas.csv"):
    buf = io.BytesIO(df.to_csv(index=False).encode())
    return client.post("/datasets", files={"file": (name, buf, "text/csv")})


def test_upload_profile_and_recommend(client):
    res = upload(client, samples.ecommerce())
    assert res.status_code == 201, res.text
    ds = res.json()
    assert ds["detected_industry"] == "ecommerce"
    assert ds["n_rows"] == 500

    rec = client.get(f"/datasets/{ds['id']}/recommendations").json()
    assert rec["industry"] == "ecommerce"
    first = rec["charts"][0]
    assert first["spec"]["title"] == "Ventas en el tiempo"
    assert first["error"] is None and len(first["data"]["points"]) == 12  # 12 meses

    generic = client.get(f"/datasets/{ds['id']}/recommendations?industry=none")
    assert generic.json()["industry"] is None


def test_requires_login(make_client):
    anon = make_client()
    assert anon.get("/datasets").status_code == 401
    assert anon.post("/dashboards", json={}).status_code in (401, 422)


def test_organization_isolation(make_client):
    ana, beto = make_client(), make_client()
    register(ana, "ana@a.com", "Clínica Ana")
    register(beto, "beto@b.com", "Tienda Beto")

    ds = upload(ana, samples.clinica()).json()
    assert beto.get(f"/datasets/{ds['id']}").status_code == 404
    assert beto.get(f"/datasets/{ds['id']}/recommendations").status_code == 404
    assert beto.get("/datasets").json() == []
    assert len(ana.get("/datasets").json()) == 1


def test_dashboard_save_and_share(make_client):
    ana, beto = make_client(), make_client()
    register(ana, "ana@a.com")
    register(beto, "beto@b.com")

    ds = upload(ana, samples.restaurante()).json()
    rec = ana.get(f"/datasets/{ds['id']}/recommendations").json()
    assert any(i["kind"] == "peak_hours" for i in rec["insights"])
    specs = [c["spec"] for c in rec["charts"][:4]]

    created = ana.post(
        "/dashboards",
        json={"dataset_id": ds["id"], "title": "Mi restaurante", "industry": "restaurante",
              "charts": specs},
    )
    assert created.status_code == 201, created.text
    dash_id = created.json()["id"]
    assert beto.get(f"/dashboards/{dash_id}").status_code == 404
    assert beto.post(f"/dashboards/{dash_id}/share").status_code == 404

    token = ana.post(f"/dashboards/{dash_id}/share").json()["share_token"]
    anon = make_client()
    public = anon.get(f"/public/dashboards/{token}")
    assert public.status_code == 200
    body = public.json()
    assert body["title"] == "Mi restaurante" and len(body["charts"]) == 4
    # el restaurante de ejemplo tiene horarios concentrados a propósito
    assert "peak_hours" in {i["kind"] for i in body["insights"]}
    assert body["share_token"] is None

    ana.delete(f"/dashboards/{dash_id}/share")
    assert anon.get(f"/public/dashboards/{token}").status_code == 404


def test_dashboard_rejects_unknown_columns(client):
    ds = upload(client, samples.ecommerce()).json()
    res = client.post(
        "/dashboards",
        json={"dataset_id": ds["id"], "title": "x",
              "charts": [{"chart_type": "bar", "title": "t", "x": "no_existe",
                          "aggregation": "count"}]},
    )
    assert res.status_code == 422


def test_rejects_bad_files(client):
    bad = client.post("/datasets", files={"file": ("x.pdf", io.BytesIO(b"%PDF"), "application/pdf")})
    assert bad.status_code == 415
    empty = client.post("/datasets", files={"file": ("x.csv", io.BytesIO(b"a,b\n"), "text/csv")})
    assert empty.status_code == 422


def test_excel_upload(client):
    buf = io.BytesIO()
    samples.clinica(50).to_excel(buf, index=False)
    buf.seek(0)
    res = client.post(
        "/datasets",
        files={"file": ("citas.xlsx", buf,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert res.status_code == 201, res.text
    assert res.json()["detected_industry"] == "clinica"
