from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

API_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="APP_", extra="ignore")

    # SQLite en desarrollo; en producción: postgresql+psycopg://user:pass@host/db
    database_url: str = f"sqlite:///{(API_ROOT / 'data' / 'app.db').as_posix()}"
    upload_dir: Path = API_ROOT / "data" / "uploads"
    max_upload_mb: int = 50
    cors_origins: list[str] = ["http://localhost:3000"]


settings = Settings()
