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

    session_cookie: str = "session"
    session_days: int = 30
    # En producción (HTTPS) debe ser True para que la cookie nunca viaje sin cifrar.
    cookie_secure: bool = False
    max_login_failures: int = 5
    login_lockout_minutes: int = 15


settings = Settings()
