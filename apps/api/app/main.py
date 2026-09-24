from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import Base, engine
from app.recommender import INDUSTRIES
from app.routes import auth, dashboards, datasets


@asynccontextmanager
async def lifespan(_: FastAPI):
    # MVP: crea las tablas al arrancar. Antes de producción, migrar a Alembic.
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="Proyecto Análisis API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,  # la cookie de sesión viaja en peticiones desde la web
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth.router)
app.include_router(datasets.router)
app.include_router(dashboards.router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/industries")
def list_industries():
    return [
        {"id": i.id, "name": i.name, "description": i.description}
        for i in INDUSTRIES.values()
    ]
