from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


class Settings(BaseSettings):
    app_name: str = "Veedcast"
    environment: str = "development"
    admin_password: str = "mble'e"
    database_url: str = "sqlite:///./veedcast.db"
    base_url: str = "http://127.0.0.1:8000"
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_config_id: str = ""
    meta_graph_version: str = "v26.0"
    token_encryption_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("database_url")
    @classmethod
    def normalize_db_url(cls, v: str) -> str:
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return v.replace(prefix, "postgresql+psycopg://", 1)
        return v

settings = Settings()