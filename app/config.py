from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Veedcast"
    environment: str = "development"
    admin_password: str = "change-me"
    database_url: str = "sqlite:///./veedcast.db"
    base_url: str = "http://127.0.0.1:8000"   # alamat publik Veedcast

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()