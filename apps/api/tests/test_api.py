import io
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine

from app import samples
from app.db import Base, get_session
from app.deps import get_storage
from app.ingestion.storage import LocalStorage
from app.main import app

A = {"X-Tenant-ID": "tenant-a"}
B = {"X-Tenant-ID": "tenant-b"}


@pytest.fixture
def client(tmp_path):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def session_override():
        with Session() as s:
            yield s

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_storage] = lambda: LocalStorage(tmp_path)
    yield TestClient(app)
    app.dependency_overrides.clear()


def upload(client, df, headers=A, name="ventas.csv"):
    buf = io.BytesIO(df.to_csv(index=False).encode())
    return client.post("/datasets", files={"file": (name, buf, "text/csv")}, headers=headers)


def test_upload_profile_and_recommend(client):
    res = upload(client, samples.ecommerce())
    assert res.status_code == 201, res.text
    ds = res.json()
    assert ds["detected_industry"] == "ecommerce"
    assert ds["n_rows"] == 500

    rec = client.get(f"/datasets/{ds['id']}/recommendations", headers=A).json()
    assert rec["industry"] == "ecommerce"
    first = rec["charts"][0]
    assert first["spec"]["title"] == "Ventas en el tiempo"
    assert first["error"] is None and len(first["data"]["points"]) == 12  # 12 meses

    generic = client.get(f"/datasets/{ds['id']}/recommendations?industry=none", headers=A)
    assert generic.json()["industry"] is None


def test_tenant_isolation(client):
    ds = upload(client, samples.clinica()).json()
    assert client.get(f"/datasets/{ds['id']}", headers=B).status_code == 404
    assert client.get("/datasets", headers=B).json() == []
    assert client.get("/datasets", headers={}).status_code == 401


def test_new_tenant_concurrent_requests(tmp_path):
    # El navegador de un usuario nuevo dispara varias peticiones a la vez; todas deben
    # responder bien aunque compitan por crear el mismo tenant.
    engine = create_engine(
        f"sqlite:///{(tmp_path / 't.db').as_posix()}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def session_override():
        with Session() as s:
            yield s

    app.dependency_overrides[get_session] = session_override
    try:
        client = TestClient(app)
        headers = {"X-Tenant-ID": "tenant-nuevo"}
        with ThreadPoolExecutor(8) as pool:
            codes = list(pool.map(lambda _: client.get("/datasets", headers=headers).status_code,
                                  range(16)))
        assert codes == [200] * 16
    finally:
        app.dependency_overrides.clear()


def test_dashboard_save_and_share(client):
    ds = upload(client, samples.restaurante()).json()
    rec = client.get(f"/datasets/{ds['id']}/recommendations", headers=A).json()
    specs = [c["spec"] for c in rec["charts"][:4]]

    created = client.post(
        "/dashboards",
        json={"dataset_id": ds["id"], "title": "Mi restaurante", "industry": "restaurante",
              "charts": specs},
        headers=A,
    )
    assert created.status_code == 201, created.text
    dash_id = created.json()["id"]
    assert client.get(f"/dashboards/{dash_id}", headers=B).status_code == 404

    token = client.post(f"/dashboards/{dash_id}/share", headers=A).json()["share_token"]
    public = client.get(f"/public/dashboards/{token}")
    assert public.status_code == 200
    body = public.json()
    assert body["title"] == "Mi restaurante" and len(body["charts"]) == 4
    assert body["share_token"] is None

    client.delete(f"/dashboards/{dash_id}/share", headers=A)
    assert client.get(f"/public/dashboards/{token}").status_code == 404


def test_dashboard_rejects_unknown_columns(client):
    ds = upload(client, samples.ecommerce()).json()
    res = client.post(
        "/dashboards",
        json={"dataset_id": ds["id"], "title": "x",
              "charts": [{"chart_type": "bar", "title": "t", "x": "no_existe",
                          "aggregation": "count"}]},
        headers=A,
    )
    assert res.status_code == 422


def test_rejects_bad_files(client):
    bad = client.post(
        "/datasets", files={"file": ("x.pdf", io.BytesIO(b"%PDF"), "application/pdf")}, headers=A
    )
    assert bad.status_code == 415
    empty = client.post(
        "/datasets", files={"file": ("x.csv", io.BytesIO(b"a,b\n"), "text/csv")}, headers=A
    )
    assert empty.status_code == 422


def test_excel_upload(client):
    buf = io.BytesIO()
    samples.clinica(50).to_excel(buf, index=False)
    buf.seek(0)
    res = client.post(
        "/datasets",
        files={"file": ("citas.xlsx", buf,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=A,
    )
    assert res.status_code == 201, res.text
    assert res.json()["detected_industry"] == "clinica"
