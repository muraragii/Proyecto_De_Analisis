from sqlalchemy import select

from app.config import settings
from app.db import get_session
from app.main import app
from app.models import User, UserSession
from tests.conftest import register

PASSWORD = "clave-segura-1"


def login(client, email="ana@negocio.com", password=PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def db_session():
    return next(app.dependency_overrides[get_session]())


def test_register_creates_owner_org_and_session(make_client):
    c = make_client()
    me = register(c, email="Ana@Negocio.com")
    assert me["user"]["email"] == "ana@negocio.com"  # normalizado
    assert me["organization"]["name"] == "Negocio de Ana"
    assert me["organization"]["role"] == "owner"
    assert c.get("/auth/me").json()["user"]["email"] == "ana@negocio.com"


def test_cookie_is_http_only(make_client):
    c = make_client()
    res = c.post(
        "/auth/register",
        json={"name": "A", "email": "a@a.com", "password": PASSWORD, "organization_name": "O"},
    )
    cookie = res.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_password_is_hashed_and_token_not_stored(client):
    db = db_session()
    user = db.scalar(select(User))
    assert user.password_hash.startswith("$argon2") and PASSWORD not in user.password_hash
    token = client.cookies.get(settings.session_cookie)
    assert db.get(UserSession, token) is None  # solo se guarda el hash


def test_duplicate_email(make_client):
    register(make_client())
    res = make_client().post(
        "/auth/register",
        json={"name": "Otra", "email": "ANA@negocio.com", "password": PASSWORD,
              "organization_name": "X"},
    )
    assert res.status_code == 409


def test_validation(make_client):
    c = make_client()
    base = {"name": "A", "email": "a@a.com", "password": PASSWORD, "organization_name": "O"}
    assert c.post("/auth/register", json={**base, "password": "corta"}).status_code == 422
    assert c.post("/auth/register", json={**base, "email": "no-es-correo"}).status_code == 422


def test_login_logout(make_client):
    register(make_client())
    c = make_client()
    assert c.get("/auth/me").status_code == 401
    assert login(c, password="incorrecta").status_code == 401
    assert login(c, email="nadie@x.com").status_code == 401
    res = login(c, email="ANA@negocio.com")
    assert res.status_code == 200 and res.json()["organization"]["role"] == "owner"
    assert c.get("/auth/me").status_code == 200

    old_token = c.cookies.get(settings.session_cookie)
    assert c.post("/auth/logout").status_code == 204
    assert c.get("/auth/me").status_code == 401
    # la sesión se revocó en el servidor: reusar la cookie robada no sirve
    c.cookies.set(settings.session_cookie, old_token)
    assert c.get("/auth/me").status_code == 401


def test_lockout_after_failures(make_client):
    register(make_client())
    c = make_client()
    for _ in range(settings.max_login_failures):
        assert login(c, password="mala-clave").status_code == 401
    # bloqueada incluso con la contraseña correcta
    res = login(c)
    assert res.status_code == 429 and "min" in res.json()["detail"]


def test_same_error_for_unknown_email_and_bad_password(make_client):
    register(make_client())
    c = make_client()
    a = login(c, email="nadie@x.com").json()["detail"]
    b = login(c, password="mala-clave").json()["detail"]
    assert a == b


def test_switch_organization_requires_membership(make_client):
    ana, beto = make_client(), make_client()
    register(ana, "ana@a.com", "Org A")
    beto_org = register(beto, "beto@b.com", "Org B")["organization"]["id"]
    assert ana.post("/auth/organization", json={"organization_id": beto_org}).status_code == 404
