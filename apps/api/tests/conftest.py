import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_session
from app.deps import get_storage
from app.ingestion.storage import LocalStorage
from app.main import app


@pytest.fixture
def make_client(tmp_path):
    """Fábrica de clientes: cada uno es un navegador distinto (cookies propias)
    contra la misma base de datos de prueba."""
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def session_override():
        with Session() as s:
            yield s

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_storage] = lambda: LocalStorage(tmp_path / "uploads")
    yield lambda: TestClient(app)
    app.dependency_overrides.clear()


def register(client, email="ana@negocio.com", org="Negocio de Ana", password="clave-segura-1"):
    res = client.post(
        "/auth/register",
        json={"name": "Ana", "email": email, "password": password, "organization_name": org},
    )
    assert res.status_code == 201, res.text
    return res.json()


@pytest.fixture
def client(make_client):
    """Cliente con un usuario ya registrado y con sesión iniciada."""
    c = make_client()
    register(c)
    return c
